# Architecture Patterns: n8n Workflow Reliability

**Domain:** n8n workflow automation — batch processing, race condition prevention, polling, pagination
**Researched:** 2026-03-23
**Overall confidence:** HIGH (all patterns verified against official n8n docs and community sources)

---

## Recommended Architecture

The RAYN enrichment workflow has five distinct reliability failure modes. Each requires a specific n8n pattern. The sections below address each in order of severity.

---

## Pattern 1: Batch Loop — Process All Items, Not Just the First

### The Bug

The `.first()` call on a NocoDB GET All result returns a single n8n item object (the first record). Everything downstream processes only that one lead. The fix replaces `.first()` with a Loop Over Items node consuming all returned records.

### Recommended Node: Loop Over Items (Split in Batches)

This is n8n's built-in core node (`n8n-nodes-base.splitInBatches`). It divides an incoming collection into batches and feeds them through the loop body one batch at a time, reconnecting output back to its own input until all items are exhausted.

**Node configuration:**
- **Batch Size:** `1` — process each lead individually through the enrichment chain (API calls are per-lead, not bulk)
- **Reset:** off (default) — do not reset on every execution

### Loop Wiring Pattern

```
NocoDB Get All (returns 5 filtered leads)
       ↓
Loop Over Items [Batch Size: 1]
  ├── loop output → [entire enrichment chain: HTTP Check → HIA → Scrape → Contact → Email]
  │                         ↓ (last enrichment node output)
  └────────────────── loop back to Loop Over Items input
       ↓ (done output, fires when all items exhausted)
  [End / status update]
```

The "loop" output fires once per batch. The "done" output fires once when all batches are complete. Connect the enrichment chain's final node back to Loop Over Items input (not to the done output). n8n handles termination automatically when the internal pointer reaches the end of the collection.

### Code Node Alternative (if loop node is insufficient)

If fine-grained control is needed inside a Code node:

```javascript
// Mode: "Run Once for All Items"
const leads = $input.all();

const results = [];
for (const lead of leads) {
  const data = lead.json;
  // process data here, push to results
  results.push({ json: { ...data, processed: true } });
}

return results;
```

`$input.all()` returns every item from the upstream node as an array. This is the correct alternative to `$input.first()` when you want all items. Set Code node mode to "Run Once for All Items" — not the default "Run Once for Each Item".

**Confidence:** HIGH — verified against n8n docs and community patterns.

---

## Pattern 2: Race Condition Prevention — Status-Before-Fetch Lock

### The Bug

Two executions of the 3-minute trigger both read NocoDB at the same time. Both see the same 5 leads with `status = "pending"`. Both process the same leads. The result is duplicate API calls, duplicate emails, and corrupted lead state.

### Recommended Pattern: Pessimistic Status Lock

This is an application-level mutex using the NocoDB `status` field as the lock. The pattern is: **fetch IDs only → immediately write lock status → then process**.

**Step-by-step flow:**

```
1. NocoDB: Get All rows WHERE status = "pending" LIMIT 5
         [Returns row IDs + minimal fields only]
         ↓
2. Loop Over Items [Batch Size: 1]
         ↓ (loop output)
3. NocoDB: Update row
         Set status = "processing"
         [Write happens BEFORE any API call]
         ↓
4. NocoDB: Get single row (full record)
         [Fetch full data now that row is locked]
         ↓
5. [Enrichment chain: HTTP → HIA → Contact → Email]
         ↓
6. NocoDB: Update row
         Set status = "enriched" (or "failed" on error branch)
```

### Status Values

| Value | Set When | Next State |
|-------|----------|------------|
| `pending` | Row inserted by discovery workflow | `processing` |
| `processing` | Immediately after fetch, before enrichment | `enriched` or `failed` |
| `enriched` | All enrichment steps complete | terminal |
| `failed` | Error branch caught | can retry → `pending` |
| `verification_timeout` | No2Bounce polling exhausted | retry candidate |

### Why This Works

Steps 1 and 3 are sequential within a single n8n execution. If two executions start at the same 3-minute tick, the second one to reach step 3 will attempt to update a row that the first has already updated to `processing`. NocoDB will write successfully (no conflict detection), but step 1 of the second execution filtered only `status = "pending"` — so a row the first execution already claimed will not appear in the second execution's result set. The window where both executions read `pending` simultaneously narrows to the milliseconds between the two GET calls, and a second-execution claim on an already-`processing` row is harmless because the enrichment will be a duplicate that gets overwritten (or detected as enriched and skipped).

**To close the window entirely:** Add a WHERE filter in step 4 (full record GET) that also checks `status = "processing"`. If the row has already been moved past `processing` by another execution, skip it with an IF node.

### n8n Concurrency Control (Secondary Defense)

For Railway-hosted self-managed n8n, set the environment variable:

```
N8N_CONCURRENCY_PRODUCTION_LIMIT=1
```

This queues all production executions (trigger/webhook-started) and runs them strictly sequentially. With a 3-minute trigger and enrichment that typically completes in under 3 minutes, this eliminates overlap entirely without application-level locks. Setting to `1` is the simplest fix if Redis is not available.

**Requires:** n8n v1.0+. Does not require queue mode. Set in Railway environment variables and restart n8n.

**Confidence:** HIGH for both the status-lock pattern and the concurrency variable. The status-lock pattern is the more robust solution; the env var is a fast fallback.

---

## Pattern 3: Reliable Polling Loop — No2Bounce Verification

### The Bug

Poll 4 (the final No2Bounce status check) forces a verdict regardless of whether No2Bounce has finished processing. If the job is still `processing`, the workflow marks the email as valid or invalid based on an incomplete result.

### Recommended Pattern: Counter-Gated Wait Loop

Use a Set → HTTP Request → IF → (Wait → loop back) chain with a decrementing counter for max retries.

**Node sequence:**

```
Set Node ("Init poll vars")
  max_retries = 6
  retry_delay_seconds = 10
  email_validation_id = {{$json.validation_id}}
       ↓
HTTP Request: GET No2Bounce status endpoint
  URL: https://api.no2bounce.com/v2/single/{{$json.email_validation_id}}
  On Error: Continue (using error output)
       ↓
IF Node: Check completion
  Condition 1: {{$json.status}} equals "valid" OR "invalid"     → TRUE branch → continue workflow
  Condition 2: {{$json.max_retries}} <= 0                       → TRUE branch → verification_timeout branch
  Otherwise                                                     → FALSE branch → decrement + wait
       ↓ FALSE branch
Set Node ("Decrement retries")
  max_retries = {{$json.max_retries - 1}}
  retry_delay_seconds = {{$json.retry_delay_seconds}}      [keep same or multiply by 2 for backoff]
       ↓
Wait Node
  Wait For: Duration
  Seconds: {{$json.retry_delay_seconds}}
       ↓ (loop back to HTTP Request node)
```

**Timeout behavior:** 6 retries × 10-second wait = 60-second max wait before `verification_timeout`. If the status is still not terminal after 60 seconds, update NocoDB with `email_status = "verification_timeout"` and continue. A separate cleanup workflow can re-queue these rows later.

**Critical wiring note:** When looping the Wait node back to the HTTP Request node, pass `email_validation_id` through the Set node so the HTTP Request always has access to it. Do not connect the Wait node directly back to a node that loses the ID field.

**n8n built-in retry is insufficient here:** The built-in Retry on Fail max delay is 5,000ms and max retries is 5. For polling an async job, custom loop is required.

**Confidence:** HIGH — pattern verified from official n8n retry documentation and community polling loop implementations.

---

## Pattern 4: NocoDB Pagination Beyond 10,000 Rows

### The Bug

The NocoDB GET All node (or HTTP Request node) has a hardcoded `limit=10000`. NocoDB's default `DB_QUERY_LIMIT_MAX` is 100 rows. Even if increased server-side, a single-call approach silently misses rows once the table exceeds the limit.

### NocoDB v2 API Pagination Parameters

**Endpoint:**
```
GET /api/v2/tables/{tableId}/records
```

**Query parameters:**

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `limit` | integer | 25 | Rows per page (max determined by server config) |
| `offset` | integer | 0 | Skip N rows (SQL OFFSET) |
| `where` | string | — | Filter condition, e.g. `(status,eq,pending)` |
| `sort` | string | — | Sort field, e.g. `-created_at` |

**Response structure:**
```json
{
  "list": [ /* array of record objects */ ],
  "pageInfo": {
    "totalRows": 1500,
    "page": 1,
    "pageSize": 25,
    "isFirstPage": true,
    "isLastPage": false
  }
}
```

**End-of-data detection:** `pageInfo.isLastPage === true` means no more rows remain.

### Pagination Loop Pattern in n8n Code Node

Use a Code node ("Run Once for All Items") to collect all rows across pages:

```javascript
// Code node — Run Once for All Items
// Upstream: pass in baseUrl, tableId, token, filterWhere as workflow variables

const baseUrl    = $vars.NOCODB_BASE_URL;        // e.g. https://nocodb.railway.app
const tableId    = $vars.LEADS_TABLE_ID;
const token      = $vars.NOCODB_API_TOKEN;
const filterWhere = "(status,eq,pending)";

const pageSize = 200;  // increase if DB_QUERY_LIMIT_MAX allows
let offset = 0;
let allRecords = [];
let isLastPage = false;

while (!isLastPage) {
  const url = `${baseUrl}/api/v2/tables/${tableId}/records` +
    `?limit=${pageSize}&offset=${offset}&where=${encodeURIComponent(filterWhere)}`;

  const response = await $http.request({
    method: 'GET',
    url,
    headers: { 'xc-auth': token }
  });

  const { list, pageInfo } = response;
  allRecords = allRecords.concat(list);
  isLastPage = pageInfo.isLastPage;
  offset += pageSize;
}

return allRecords.map(record => ({ json: record }));
```

**Alternatively, use the n8n NocoDB node** with "Return All" = true (if available in your n8n version). The NocoDB node's built-in pagination handles this automatically. Check the node's "Options" section for a "Return All" toggle before writing custom pagination code.

**Server-side limit increase:** On self-hosted NocoDB (Railway), set environment variable:
```
DB_QUERY_LIMIT_MAX=1000
```
This raises the maximum rows returnable per single API call. Still use pagination for correctness as table grows.

**Confidence:** MEDIUM-HIGH — pageInfo structure verified via NocoDB GitHub discussion and API response examples. The `isLastPage` field name confirmed from multiple sources. The Code node `$http.request` pattern is LOW confidence — verify against your n8n version; the HTTP Request node inside a loop may be more reliable.

---

## Pattern 5: Anymail → Hunter Fallback — OR Logic Fix

### The Bug

The IF node after Anymail uses AND logic: `name IS empty AND email IS empty`. This means Hunter is only called when Anymail returns nothing at all. If Anymail returns a name but no email, Hunter is never called — even though the email is still missing.

### Fix

Replace the AND condition with OR logic in the IF node:

**Current (wrong):**
```
name IS empty  AND  email IS empty  →  call Hunter
```

**Correct:**
```
name IS empty  OR  email IS empty  →  call Hunter
```

In the n8n IF node: set the Combine Conditions operator to **"OR"** (not "AND"). Each condition row checks one field.

**Confidence:** HIGH — this is a straightforward IF node configuration change.

---

## Pattern 6: Error Handling and Recovery

### n8n Error Handling Options

| Mechanism | Scope | How to Enable |
|-----------|-------|---------------|
| Retry on Fail | Per-node | Node settings → "Retry On Fail" toggle, max 5 retries, max 5s delay |
| Continue on Fail | Per-node | Node settings → "On Error" → "Continue (using error output)" |
| Error output branch | Per-node | Adds red error output connector to node |
| Error Trigger Workflow | Per-workflow | Workflow settings → "Error Workflow" → point to error handler workflow |
| Stop and Error node | Per-flow | Deliberately halts execution with custom error message |

### Recovery Pattern for Enrichment Chain

When a mid-workflow node fails (e.g., Anymail API timeout), the enrichment chain should:

1. Write `status = "failed"` back to NocoDB with an error reason field
2. NOT leave the row in `status = "processing"` — a stuck `processing` row will never be retried

**Implementation:**

```
[Any enrichment node]
  ├── success output → next enrichment node
  └── error output → Set Node: { status: "failed", error_reason: {{$json.error.message}} }
                           ↓
                     NocoDB Update: write status + error_reason to row
```

**Stuck-processing cleanup:** Add a second scheduled workflow (or a periodic branch in the main workflow) that queries:
```
WHERE status = "processing" AND updated_at < (NOW - 10 minutes)
```
Reset these to `status = "pending"` for reprocessing. This handles cases where n8n crashed mid-execution and left rows locked in `processing`.

**Confidence:** HIGH — verified against n8n error handling documentation.

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| Schedule Trigger | Fires every 3 min | Loop Over Items |
| Loop Over Items | Iterates 5 pending leads | NocoDB Update (lock), Enrichment chain |
| Status Lock Step | Writes `processing` before enrichment | NocoDB |
| Enrichment Chain | HTTP → HIA → Contact → Email | Serper, OpenRouter, Anymail, Hunter, No2Bounce |
| Polling Loop | Retries No2Bounce until terminal status | No2Bounce API |
| Error Branch | Catches failures, writes `failed` status | NocoDB |
| Pagination Code | Fetches all pending leads across pages | NocoDB API |

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Single `.first()` After NocoDB Fetch
**What:** Calling `.first()` on a multi-item result set discards all items except the first.
**Why bad:** 4 of 5 leads are silently dropped each run.
**Instead:** Feed the full result into Loop Over Items with Batch Size 1.

### Anti-Pattern 2: Read-Then-Process Without Locking
**What:** Fetching rows and processing them without immediately writing a lock status.
**Why bad:** Any overlapping execution reads the same rows and processes duplicates.
**Instead:** Write `status = "processing"` as the first action after fetching row IDs.

### Anti-Pattern 3: Hardcoded Row Limit
**What:** `limit=10000` in a single NocoDB GET call.
**Why bad:** Silently misses rows once the table exceeds the limit; NocoDB server-side max may be lower than 10000.
**Instead:** Pagination loop using `pageInfo.isLastPage` as termination condition.

### Anti-Pattern 4: Forced Verdict on Async Poll
**What:** After N polls, assume the last-seen status is the final answer.
**Why bad:** If the validation job is still running, the verdict is wrong.
**Instead:** Write `verification_timeout` status and re-queue for later retry.

### Anti-Pattern 5: AND Logic for Fallback Triggers
**What:** Fallback API called only when ALL fields are empty.
**Why bad:** Partial results (name but no email) never trigger the fallback.
**Instead:** Use OR logic — call fallback if ANY required field is empty.

---

## Scalability Considerations

| Concern | Current (< 5K leads) | At 50K leads | At 500K leads |
|---------|----------------------|--------------|---------------|
| NocoDB row fetch | Hardcoded limit risky | Pagination required | Pagination + indexed status column |
| Enrichment throughput | 5 leads/3 min = 2,400/day | Increase batch size or run frequency | Sub-workflow parallel fan-out |
| Race condition risk | Low (single Railway instance) | Medium if multi-worker | Distributed lock (Redis) required |
| No2Bounce polling | 6 polls × 10s = 60s per lead | Same | Same, but increase retries if SLA degrades |

---

## Sources

- [n8n Loop Over Items (Split in Batches) — Official Docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.splitinbatches/) — HIGH confidence
- [n8n Looping — Official Docs](https://docs.n8n.io/flow-logic/looping/) — HIGH confidence
- [n8n Error Handling — Official Docs](https://docs.n8n.io/flow-logic/error-handling/) — HIGH confidence
- [n8n Concurrency Control — Official Docs](https://docs.n8n.io/hosting/scaling/concurrency-control/) — HIGH confidence
- [n8n Redis Locking Workflow Template](https://n8n.io/workflows/3444-redis-locking-for-concurrent-task-handling/) — MEDIUM confidence
- [n8n Prevent Concurrent Workflows](https://n8nplaybook.com/post/2025/07/how-to-prevent-concurrent-n8n-workflows/) — MEDIUM confidence
- [n8n Race Conditions in Parallel Executions](https://flowgenius.in/n8n-race-conditions-parallel-executions/) — MEDIUM confidence
- [n8n Custom Retry and Delay Logic](https://n8nplaybook.com/post/2025/06/mastering-custom-retry-and-delay-logic-in-n8n/) — HIGH confidence
- [n8n Polling Loop Community Discussion](https://community.n8n.io/t/how-to-build-a-polling-loop/110997) — MEDIUM confidence
- [NocoDB REST APIs — Official Docs](https://nocodb.com/docs/product-docs/developer-resources/rest-apis) — MEDIUM confidence
- [NocoDB Pagination Discussion](https://github.com/nocodb/nocodb/discussions/1999) — MEDIUM confidence
- [NocoDB Bug: API Row Limit](https://github.com/nocodb/nocodb/issues/7761) — MEDIUM confidence (confirms server-side limit applies)
- [n8n Code Node $input.all() vs $json — Medium](https://medium.com/@krishnaagarwal.in/mastering-the-n8n-code-node-a-deep-dive-into-input-all-vs-json-dfc66be6bd52) — MEDIUM confidence
- [N8N_CONCURRENCY_PRODUCTION_LIMIT Guide — GitHub Gist](https://gist.github.com/Ryan-PG/879ff8acaea8d70af265b9685a5d6d67) — MEDIUM confidence
