# Phase 1: Workflow Reliability - Research

**Researched:** 2026-03-24
**Domain:** n8n workflow automation — concurrency, batch processing, race conditions, NocoDB pagination, polling loops
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Redesign No2Bounce verification as a separate scheduled workflow (every 30 min) that checks NocoDB for `status=verification_timeout` leads and re-submits them to No2Bounce. Do NOT use Wait node inline polling.

**D-02:** Enrichment workflow writes `verification_timeout` status after 6 retries and moves on — it never blocks waiting for No2Bounce to respond.

**D-03:** Separate retry workflow runs independently: read `verification_timeout` leads → re-submit to No2Bounce → poll once → update status to `valid`/`invalid`/`verification_timeout` (reset counter).

**D-04:** Auto-cleanup built into wf-latest — at the start of each enrichment run, before fetching pending leads, reset any rows where `status=processing` AND `updated_at` is older than 10 minutes back to `status=pending`.

**D-05:** This cleanup runs on every trigger, not as a separate workflow. Ensures no manual NocoDB intervention ever needed for stuck leads.

**D-06:** Pessimistic status lock pattern: fetch 5 lead IDs only → immediately `UPDATE status=processing` → then fetch full records → begin enrichment chain. Two-step fetch prevents concurrent runs from grabbing the same lead.

**D-07:** Additionally set `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` on Railway as a secondary defense.

**D-08:** Replace `.first()` with Loop Over Items node (Split in Batches, batch size 1) so all 5 filtered leads are processed per run.

**D-09:** Add OpenRouter backoff (1s → 2s → 5s → 13s) before enabling 5x throughput to avoid rate limiting.

**D-10:** Change IF No Contact condition from AND to OR — Hunter is triggered when name or email is empty (not both).

**D-11:** Replace hardcoded GET calls with `pageInfo.isLastPage` pagination loops in both wf-latest (pending lead fetches) and wf-discovery (Read Discovery + Read Leads fetches).

**D-12:** Set `DB_QUERY_LIMIT_MAX=100000` on NocoDB Railway service (env var), and `DB_QUERY_LIMIT_DEFAULT=1000` to cap page size.

**D-13:** Set on n8n service: `N8N_CONCURRENCY_PRODUCTION_LIMIT=1`, `N8N_PAYLOAD_SIZE_MAX=128`, `N8N_RUNNERS_TASK_TIMEOUT=600`.

**D-14:** Set on NocoDB service: `DB_QUERY_LIMIT_MAX=100000`, `DB_QUERY_LIMIT_DEFAULT=1000`.

### Claude's Discretion

- Exact backoff timing implementation (Wait node durations)
- Pagination loop node structure (Code node vs chained HTTP Request nodes)
- In-batch URL hash dedup implementation in wf-discovery

### Deferred Ideas (OUT OF SCOPE)

- HTTP status check in wf-discovery (low priority; wf-latest already has it)
- Monitoring/alerting for stuck leads
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | Set `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` on Railway n8n env vars | Railway env var API confirmed; D-07/D-13 specify exact values; secondary to status-lock pattern |
| INFRA-02 | Raise `DB_QUERY_LIMIT_MAX` on Railway NocoDB env vars | NocoDB default cap confirmed at 25-100 rows; D-12/D-14 specify exact values |
| FIX-01 | Fix race condition — set lead status to `processing` immediately after fetching | Pessimistic status lock pattern fully documented in ARCHITECTURE.md; D-06 specifies two-step fetch pattern |
| FIX-02 | Fix batch processing — replace `.first()` pattern with Loop Over Items (batch size 1) | Bug confirmed in wf-latest.json line 139 (`Filter Unprocessed` + `.first()` references); D-08 specifies Loop Over Items |
| FIX-03 | Add OpenRouter backoff before enabling 5x throughput | PITFALLS.md confirms 429 risk; D-09 specifies 1s→2s→5s→13s timing; must precede FIX-02 deployment |
| FIX-04 | Fix contact fallback logic — AND to OR | Bug confirmed in wf-latest.json: IF No Contact uses `"combinator": "and"` (node id f8e0ec97); D-10 specifies OR fix |
| FIX-05 | Fix email verification final poll — write `verification_timeout`, not forced verdict | Bug confirmed in wf-latest.json: Parse Poll 4 forces `valid`/`invalid` regardless of ready state (node id e51b9dfe); D-01/D-02/D-03 specify separate retry workflow design |
| FIX-06 | Fix NocoDB row pagination in wf-latest | Bug confirmed: Read All Rows uses `limit=10000` (node id 90b8fd61); Read Column E uses `limit=10000` (node id 60be1b05); D-11 specifies isLastPage loop |
| FIX-07 | Fix NocoDB row pagination in wf-discovery | Bug confirmed: Read Discovery uses `limit=10000` (node id disc-read-discovery); Read Leads uses `limit=10000` (node id disc-read-leads); D-11 same approach |
</phase_requirements>

---

## Summary

Phase 1 fixes six distinct reliability failures in two existing n8n workflows. All bugs have been confirmed by direct inspection of `wf-latest.json` and `wf-discovery.json`. No new capabilities are introduced — this phase is purely correctness and stability.

The most severe bug is the race condition (FIX-01): two overlapping 3-minute trigger executions read the same `pending` leads before either writes a status update, causing duplicate API spend and corrupted NocoDB state. The fix requires a two-step fetch pattern (IDs only → write `processing` → fetch full record) plus `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` as secondary defense. The batch processing bug (FIX-02) is the second most impactful: `Filter Unprocessed` builds a 5-item array but all downstream nodes reference `$('Filter Unprocessed').first()`, so only one lead is enriched per run. The No2Bounce polling bug (FIX-05) causes forced verdicts on still-processing validations; the user has locked a separate 30-minute scheduled workflow as the solution.

The NocoDB row cap is a silent failure: the server default `DB_QUERY_LIMIT_MAX` is 25-100 rows. Any table with more rows than this cap silently stops feeding the enrichment pipeline with no error. Three env vars (INFRA-01, INFRA-02 on two separate Railway services) plus pagination loops in both workflows (FIX-06, FIX-07) together eliminate this risk.

**Primary recommendation:** Execute plans in dependency order — Railway env vars first (INFRA-01/02, no workflow changes needed), then race condition lock (FIX-01), then backoff (FIX-03) before batch fix (FIX-02), then contact fallback (FIX-04), then No2Bounce redesign (FIX-05), then pagination (FIX-06/FIX-07).

---

## Standard Stack

### Core — Already in Use (no new installs)

| Library / Node | Version | Purpose | Notes |
|----------------|---------|---------|-------|
| n8n-nodes-base.splitInBatches | built-in | Loop Over Items — iterate all 5 leads per run | Replaces `.first()` pattern |
| n8n-nodes-base.httpRequest | built-in v4.2 | All NocoDB PATCH/GET calls | Already used throughout; same version |
| n8n-nodes-base.if | built-in v2 | IF No Contact combinator change | In-place edit only |
| n8n-nodes-base.code | built-in v2 | Pagination loop, cleanup logic, backoff init | Used extensively already |
| n8n-nodes-base.wait | built-in | Backoff delay between retries | Available in n8n; Insert between OpenRouter calls |
| n8n-nodes-base.scheduleTrigger | built-in v1.2 | New No2Bounce retry workflow trigger | Every 30 min |

### No New Libraries Required

This phase involves no npm installs, no new credentials, and no new n8n community nodes. All fixes use existing built-in n8n nodes and the existing NocoDB REST API v1 (already confirmed in both workflow files).

### NocoDB API Version in Use

Both workflows use NocoDB REST API **v1** (path: `/api/v1/db/data/noco/...`), not v2. The `pageInfo` pagination response structure applies to both v1 and v2. The existing API token (`xc-token` header) is reused.

---

## Architecture Patterns

### Recommended Execution Order

```
Wave 0 (env vars — no workflow edit)
  Railway: n8n service → INFRA-01, INFRA-02 env vars

Wave 1 (wf-latest core fixes)
  Plan 1: Stuck-processing cleanup + pessimistic status lock (FIX-01)
  Plan 2: OpenRouter backoff (FIX-03) — MUST precede FIX-02
  Plan 3: Batch loop fix (FIX-02) — enabled after backoff in place
  Plan 4: Contact fallback OR fix (FIX-04)

Wave 2 (No2Bounce redesign)
  Plan 5: Remove Poll 4 forced verdict, write verification_timeout (FIX-05 part A)
  Plan 6: New wf-no2bounce-retry standalone workflow (FIX-05 part B)

Wave 3 (pagination)
  Plan 7: Pagination in wf-latest — Read All Rows + Read Column E (FIX-06)
  Plan 8: Pagination in wf-discovery — Read Discovery + Read Leads (FIX-07)
```

### Pattern 1: Stuck-Processing Cleanup (D-04, D-05)

**What:** Code node runs at the very start of wf-latest trigger, before any lead fetching. Queries NocoDB for rows where `status=processing` and `UpdatedAt` is older than 10 minutes. Resets them to `status=pending`.

**Node placement:** Between Schedule Trigger and Read All Rows (new node, inserted first).

**NocoDB filter syntax (v1 API):**
```
GET /api/v1/db/data/noco/{projectId}/{tableId}
  ?where=(status,eq,processing)~and(UpdatedAt,lt,{10_minutes_ago_iso})
  &limit=100
```

Then PATCH each matched row: `{ "status": "pending" }`.

**Implementation options:**
- Option A (Code node + HTTP loop): Single Code node with `$http.request()` loop — handles bulk reset in one node
- Option B (HTTP Request + Split + PATCH): HTTP GET → Code parse → Loop Over Items → PATCH — more verbose but more debuggable in n8n execution UI

Recommendation: Option B for debuggability — execution log shows each reset individually.

### Pattern 2: Pessimistic Status Lock (D-06)

**What:** Split the existing `Filter Unprocessed` → enrichment chain into three steps: (1) fetch IDs only with `WHERE status=pending LIMIT 5`, (2) immediately PATCH all 5 to `status=processing`, (3) then fetch full records and begin enrichment.

**Wiring:**
```
Schedule Trigger
  ↓
[NEW] Cleanup Stuck Processing (Code node → PATCH loop)
  ↓
[MODIFIED] Get Pending IDs — GET ?where=(status,eq,pending)&limit=5&fields=Id
  ↓
[NEW] Loop Over Items [Batch Size: 1]
  ↓ (loop output)
[NEW] PATCH status=processing — HTTP PATCH /api/v1/.../Id
  ↓
[NEW] GET Full Record — HTTP GET /api/v1/.../Id
  ↓
[EXISTING enrichment chain, re-wired into loop]
  ↓ (last node in chain)
  └── back to Loop Over Items input
  ↓ (done output)
[END]
```

**Key design point:** The current `Filter Unprocessed` Code node does `unique.slice(0, 5)` — this logic moves to the API query (`LIMIT 5` + `WHERE status=pending`). The Code node is replaced by the Loop Over Items node.

### Pattern 3: Batch Loop Fix (D-08)

**What:** Replace the single-item processing chain (all nodes reference `$('Filter Unprocessed').first()`) with Loop Over Items.

**Confirmed bug locations in wf-latest.json:**
- `OpenRouter - Clean Name`: references `$('Filter Unprocessed').first().json.company_name`
- `Serper - Search`: references `$('OpenRouter - Clean Name').first().json...`
- `OpenRouter - URL Dedup`: references `$('OpenRouter - Clean Name').first().json...` and `$('Serper - Search').first().json...`
- All NocoDB PATCH nodes: reference `$('Filter Unprocessed').item.json.Id`

After Loop Over Items wraps the chain, all `.first()` references change to `$json.` (current item context) or `$node["NodeName"].json.` — items flow through naturally.

### Pattern 4: OpenRouter Backoff (D-09)

**What:** Add Wait nodes before each OpenRouter HTTP Request node with durations 1s, 2s, 5s, 13s (Fibonacci-adjacent).

**Implementation (Claude's Discretion):** Single Wait node with configurable duration set by a preceding Set node, placed before each `OpenRouter - *` node. Duration escalates if retry is triggered.

**Simpler approach for Phase 1:** Fixed 1-second Wait node before each of the 4 OpenRouter calls in the enrichment chain. This adds 4 seconds per lead but eliminates 429 risk entirely at 5-lead batch volume.

```
Set Node: { wait_seconds: 1 }
  ↓
Wait Node: {{ $json.wait_seconds }} seconds
  ↓
HTTP Request: OpenRouter
```

### Pattern 5: Contact Fallback OR Fix (D-10)

**What:** Change `"combinator": "and"` to `"combinator": "or"` in the IF No Contact node (id: `f8e0ec97-1d87-46b4-9160-ebebdba9b5c8`).

**Confirmed bug in wf-latest.json lines 1088-1089:**
```json
"combinator": "and"
```

**Fix:** Change to `"combinator": "or"`. No other changes needed — the two conditions (first_name empty, email empty) remain identical.

### Pattern 6: No2Bounce Redesign (D-01, D-02, D-03)

**What:** Two-part change:
- Part A (wf-latest): Replace Poll 3 → Poll 4 → forced verdict with: IF `is_ready === false` after Poll 3 → write `verification_timeout` to NocoDB → continue to next lead.
- Part B (new workflow): wf-no2bounce-retry, triggered every 30 minutes by Schedule Trigger. Reads rows with `status=verification_timeout` → re-submits to No2Bounce → single poll → writes result.

**Confirmed bug in Parse Poll 4 (id: e51b9dfe, line ~2197-2199):**
```javascript
// Final poll - accept whatever we have
const status = isValid ? 'valid' : 'invalid';  // BUG: forced verdict
```

**Part A fix:** Replace Parse Poll 4's forced verdict with:
```javascript
const status = isReady ? (isValid ? 'valid' : 'invalid') : 'verification_timeout';
```

Then add NocoDB PATCH node on the `verification_timeout` branch before continuing.

**Part B new workflow nodes:**
```
Schedule Trigger (every 30 min)
  ↓
HTTP GET — ?where=(status,eq,verification_timeout)&limit=50
  ↓
Code — parse list
  ↓
IF No Rows → Stop
  ↓
Loop Over Items [Batch Size: 1]
  ↓
No2Bounce Submit (re-submit email)
  ↓
Wait 15s
  ↓
No2Bounce Poll 1
  ↓
Parse Poll result
  ↓
PATCH NocoDB — status = valid / invalid / verification_timeout (reset)
  ↓ back to loop
```

### Pattern 7: NocoDB Pagination (D-11, D-12)

**What:** Replace single HTTP GET with `limit=10000` with a Code node loop that pages until `pageInfo.isLastPage === true`.

**Implementation (Claude's Discretion — Code node approach):**

NocoDB v1 `pageInfo` response structure (confirmed in ARCHITECTURE.md):
```json
{
  "list": [...],
  "pageInfo": {
    "totalRows": N,
    "page": 1,
    "pageSize": 25,
    "isFirstPage": true,
    "isLastPage": false
  }
}
```

Code node pattern (Run Once for All Items):
```javascript
// Set pageSize to match DB_QUERY_LIMIT_DEFAULT (1000 after env var change)
const pageSize = 1000;
const baseUrl = 'https://nocodb-production-f802.up.railway.app';
const projectId = 'pb7f1zou786xyqc';
const tableId = 'mey3zgihq7o4at9';   // leads table
const token = 'SqqM8YcDuzXGijg0oY7PvqTcPX5H-r2sYqbAOWTN';
const where = encodeURIComponent('(status,eq,pending)');

let page = 1;
let allRecords = [];
let isLastPage = false;

while (!isLastPage) {
  const url = `${baseUrl}/api/v1/db/data/noco/${projectId}/${tableId}` +
    `?where=${where}&limit=${pageSize}&page=${page}`;
  const response = await $http.request({
    method: 'GET',
    url,
    headers: { 'xc-token': token }
  });
  allRecords = allRecords.concat(response.list || []);
  isLastPage = response.pageInfo?.isLastPage ?? true;
  page += 1;
}

return allRecords.map(r => ({ json: r }));
```

**Note on `$http.request` availability:** The Code node's `$http.request()` helper is available in n8n v1.x (confirmed in ARCHITECTURE.md as LOW confidence — if unavailable, use chained HTTP Request nodes inside a loop instead). For wf-discovery, the same Code node pattern applies to both Read Discovery (table: `mp36f8mgk115qse`) and Read Leads (table: `mey3zgihq7o4at9`).

**wf-discovery pagination targets:**
- `Read Discovery` (id: disc-read-discovery) → table `mp36f8mgk115qse`, no filter
- `Read Leads` (id: disc-read-leads) → table `mey3zgihq7o4at9`, no filter

### Anti-Patterns to Avoid

- **`.first()` after multi-item node:** All references to `$('NodeName').first()` in the enrichment chain must become `$json.` after the loop wraps the chain.
- **Inline No2Bounce polling loop with Wait node:** User has locked against this (D-01). The separate workflow approach is the only acceptable pattern.
- **Single-shot NocoDB GET at any limit:** Even with `DB_QUERY_LIMIT_MAX=100000`, a single GET is not safe as the table scales. Pagination loop is the correct pattern.
- **Setting `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` as the only race condition fix:** The status lock (D-06) is the primary fix. The env var is secondary defense only — it does not help if Railway restarts reset the counter.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Iterating all N leads per run | Custom Code node loop | Loop Over Items (splitInBatches, batch 1) | Built-in, handles done/loop outputs natively, visible in execution log |
| Retry delays between API calls | Code node `sleep()` / busy-wait | Wait node (Duration mode) | `sleep()` in Code node counts against 300s task timeout; Wait node pauses execution and resumes |
| Pagination beyond server page limit | Recursive HTTP Request node chain | Code node while-loop with `$http.request()` | Cleaner, single node, easy to modify page size |
| Distributed concurrency lock | Redis/Mutex pattern | `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` + status lock | Railway has no Redis by default; env var + status lock is sufficient for single-instance n8n |

**Key insight:** n8n's built-in Wait node is the only safe way to introduce delays in long-running workflows on Railway — Code node timing functions count against the task runner's 300-second hard limit.

---

## Common Pitfalls

### Pitfall 1: `.first()` References After Loop Rewire

**What goes wrong:** After wrapping the enrichment chain with Loop Over Items, all existing `$('Filter Unprocessed').first()` references in downstream nodes break — they reference a node that no longer exists or no longer feeds `.first()` correctly.

**Why it happens:** n8n node references are by name, not by wire position. When Loop Over Items replaces the flow, the current item is `$json` not `$('oldNode').first()`.

**How to avoid:** Systematically audit every node in the enrichment chain for `.first()` references before rewiring. Replace with `$json.fieldName` or `$('nodeInLoop').item.json.fieldName` as appropriate.

**Confirmed affected nodes:** OpenRouter - Clean Name, Serper - Search, OpenRouter - URL Dedup, all NocoDB PATCH nodes (they use `$('Filter Unprocessed').item.json.Id`).

### Pitfall 2: NocoDB `updated_at` Field Name Case

**What goes wrong:** The stuck-processing cleanup query uses `UpdatedAt` or `updated_at` — the exact field name in NocoDB determines which filter syntax works. NocoDB v1 field names are case-sensitive in filter expressions.

**How to avoid:** Check the actual NocoDB column name in the leads table schema before writing the cleanup filter. The filter `(UpdatedAt,lt,...)` requires the exact column name as stored in NocoDB.

**Fallback:** If the column name is unknown, use a Code node that fetches the stuck rows and filters client-side: `rows.filter(r => new Date(r.UpdatedAt || r.updated_at) < tenMinutesAgo)`.

### Pitfall 3: Loop Over Items "Done" vs "Loop" Output Confusion

**What goes wrong:** The enrichment chain's final node must connect back to Loop Over Items input (loop output = continue), not the done output. Connecting to the wrong output means the loop either runs forever or only processes one item.

**How to avoid:** In n8n Loop Over Items wiring: the loop body's last node connects back to Loop Over Items' main input. The "done" output (second output port) fires after all items are exhausted — only connect to an End/NoOp there.

### Pitfall 4: Railway Concurrency Limit Env Var Name

**What goes wrong:** The env var documented in older n8n guides is `EXECUTIONS_CONCURRENCY_PRODUCTION_LIMIT`. More recent n8n versions (v1.x) use `N8N_CONCURRENCY_PRODUCTION_LIMIT`. Using the wrong name has no effect and no error.

**How to avoid:** Use `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` (confirmed in ARCHITECTURE.md as HIGH confidence for n8n v1.x).

**Warning from PITFALLS.md:** An older guide (Pitfall 1 source) also mentions `N8N_CONCURRENCY=1` as a variant — this may be version-specific. Set both if uncertain, or verify n8n version on Railway before committing to one.

### Pitfall 5: No2Bounce Re-submit Idempotency

**What goes wrong:** The No2Bounce retry workflow re-submits emails that are already in a `verification_timeout` state. If a lead was submitted to No2Bounce but never polled (e.g., n8n crashed), re-submitting creates a duplicate job and charges credits twice.

**How to avoid:** Before re-submitting in wf-no2bounce-retry, check if a stored `trackingId` exists in NocoDB for the row. If yes, poll the existing trackingId rather than submitting a new job. Store `n2b_tracking_id` in NocoDB when first submitted.

### Pitfall 6: wf-discovery Dedup is Name-Based, Not URL-Based

**What goes wrong:** The current `Dedup Against Leads` Code node in wf-discovery deduplicates by `company_name` (lowercased). After pagination is added and the leads table grows, name-based dedup misses companies with slightly different name variants. The requirement (FIX-07) adds in-batch URL hash dedup.

**How to avoid:** In-batch dedup in wf-discovery should use `website_url` as the dedup key, not `company_name`. A company discovered from two area/category combos in the same weekly run will have the same URL — the URL is the canonical dedup key.

**Implementation (Claude's Discretion):** Before `Push to Leads`, add a Code node that builds a `Set` of URLs from the current batch and filters duplicates. The existing `Dedup Against Leads` node also needs to be updated to use URL-based dedup from the leads table (the current name-based approach is fragile at scale).

---

## Code Examples

Verified patterns from workflow inspection and ARCHITECTURE.md:

### IF No Contact: AND to OR Change (Exact JSON Diff)

```json
// Before (bug):
"combinator": "and"

// After (fix):
"combinator": "or"
```

Node: `IF No Contact` (id: `f8e0ec97-1d87-46b4-9160-ebebdba9b5c8`)
Change: Single field in `parameters.conditions.combinator`

### Parse Poll 4: Forced Verdict Fix (Exact Code Diff)

```javascript
// Before (bug) — node id: e51b9dfe-196f-4298-baea-2a7e94ff9fd9
const status = isValid ? 'valid' : 'invalid';   // always assigns a verdict

// After (fix):
const status = isReady
  ? (isValid ? 'valid' : 'invalid')
  : 'verification_timeout';
```

### Filter Unprocessed: Current Code (for reference when rewiring)

```javascript
// Current behavior — wf-latest node id: 485fff1d
// Builds batch array but loop structure is missing:
const batch = unique.slice(0, 5);
if (batch.length === 0) return [{ json: { _skip: true, company_name: '' } }];
return batch.map(r => ({ json: { ...r.json, is_duplicate: false } }));
// After this, all enrichment nodes call .first() — only processes one lead
```

### Cleanup Stuck Processing (New Code Node)

```javascript
// Run Once for All Items — placed BEFORE Read All Rows
const baseUrl = 'https://nocodb-production-f802.up.railway.app';
const projectId = 'pb7f1zou786xyqc';
const tableId = 'mey3zgihq7o4at9';
const token = 'SqqM8YcDuzXGijg0oY7PvqTcPX5H-r2sYqbAOWTN';

const tenMinutesAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();

// Get stuck rows
const getUrl = `${baseUrl}/api/v1/db/data/noco/${projectId}/${tableId}` +
  `?where=(status,eq,processing)~and(UpdatedAt,lt,${encodeURIComponent(tenMinutesAgo)})&limit=100`;

const response = await $http.request({ method: 'GET', url: getUrl, headers: { 'xc-token': token } });
const stuckRows = response.list || [];

// Reset each to pending
for (const row of stuckRows) {
  const patchUrl = `${baseUrl}/api/v1/db/data/noco/${projectId}/${tableId}/${row.Id}`;
  await $http.request({
    method: 'PATCH',
    url: patchUrl,
    headers: { 'xc-token': token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: 'pending' })
  });
}

// Pass through — next node handles pending lead fetch
return [{ json: { cleanup_count: stuckRows.length } }];
```

### NocoDB Pagination Code Node (Pending Leads Fetch)

```javascript
// Run Once for All Items — replaces Read All Rows + Parse Read Items
const baseUrl = 'https://nocodb-production-f802.up.railway.app';
const projectId = 'pb7f1zou786xyqc';
const tableId = 'mey3zgihq7o4at9';
const token = 'SqqM8YcDuzXGijg0oY7PvqTcPX5H-r2sYqbAOWTN';
const pageSize = 1000;
const where = encodeURIComponent('(status,eq,pending)');

let page = 1;
let allRecords = [];
let isLastPage = false;

while (!isLastPage) {
  const url = `${baseUrl}/api/v1/db/data/noco/${projectId}/${tableId}` +
    `?where=${where}&limit=${pageSize}&page=${page}`;
  const response = await $http.request({
    method: 'GET', url,
    headers: { 'xc-token': token }
  });
  allRecords = allRecords.concat(response.list || []);
  isLastPage = response.pageInfo?.isLastPage ?? true;
  page += 1;
}

// Filter to unique pending, take 5
const seen = new Set();
const unique = [];
for (const row of allRecords) {
  const name = String(row.company_name || '').toLowerCase().trim();
  if (!name || seen.has(name)) continue;
  seen.add(name);
  unique.push(row);
}
const batch = unique.slice(0, 5);

if (batch.length === 0) return [{ json: { _skip: true } }];
return batch.map(r => ({ json: r }));
```

---

## State of the Art

| Old Approach | Current Approach | Phase | Impact |
|--------------|------------------|-------|--------|
| `.first()` on filtered leads | Loop Over Items, batch 1 | FIX-02 | All 5 leads processed per run |
| AND logic on IF No Contact | OR logic | FIX-04 | Hunter called when email missing but name found |
| Poll 4 forced verdict | `verification_timeout` status | FIX-05 | No false valid/invalid on slow validations |
| Single GET with limit=10000 | Pagination loop on isLastPage | FIX-06/07 | All rows visible as table scales |
| No status lock on lead fetch | Two-step: IDs → PATCH processing → full fetch | FIX-01 | No duplicate enrichment on concurrent runs |
| No cleanup for stuck rows | Cleanup node at trigger start | D-04 | No manual NocoDB intervention needed |

---

## Open Questions

1. **`$http.request()` availability in Code nodes**
   - What we know: ARCHITECTURE.md flags this as LOW confidence. The pattern is documented and commonly used, but exact availability depends on n8n version.
   - What's unclear: The n8n version currently deployed on Railway.
   - Recommendation: Planner should add a pre-flight task in Wave 0 to verify: create a test Code node that runs `return [{ json: { test: typeof $http } }]` — if it returns `"function"`, proceed with Code node approach; if undefined, use chained HTTP Request nodes instead.

2. **NocoDB column name for updated_at**
   - What we know: The column exists (wf-latest references NocoDB row data), but the exact casing (`UpdatedAt`, `updated_at`, or `Updated At`) is not confirmed from workflow file inspection.
   - What's unclear: NocoDB uses different field name conventions depending on version and whether the column was auto-created or manually named.
   - Recommendation: Include a task to inspect the NocoDB table schema (GET /api/v1/db/meta/projects/{id}/tables or inspect a sample row response) and confirm the field name before writing cleanup filter.

3. **No2Bounce trackingId storage for retry idempotency**
   - What we know: The current wf-latest does not store the No2Bounce `trackingId` in NocoDB — it's only held in n8n execution memory.
   - What's unclear: Whether the retry workflow should always re-submit or should poll existing trackingIds if available.
   - Recommendation: Design decision for planner — simplest safe approach is always re-submit (accept small credit cost on retry) rather than building trackingId state management for v1.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Railway CLI / Dashboard | INFRA-01, INFRA-02 env var changes | Manual (UI action) | — | — |
| n8n on Railway | All fixes | Confirmed running | Unknown — check Railway dashboard | — |
| NocoDB on Railway | All fixes | Confirmed running (API calls in workflows succeed) | v1 API confirmed from URL patterns | — |
| No2Bounce API | FIX-05 | Confirmed (credentials in wf-latest) | connect.no2bounce.com/v2 | — |
| OpenRouter API | FIX-03 | Confirmed (credentials in wf-latest) | /api/v1 | — |

**Missing dependencies with no fallback:** None.

**Note:** Railway env var changes for INFRA-01 and INFRA-02 require manual access to the Railway dashboard. These are not automated — they are operator actions that a human must perform before workflow JSON changes are deployed.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Manual execution validation via n8n execution log + NocoDB UI inspection |
| Config file | None — n8n workflows tested by running them in the n8n editor with test data |
| Quick run command | Manually trigger wf-latest in n8n UI → check execution log |
| Full suite command | Run wf-latest + wf-discovery back-to-back; inspect NocoDB leads table |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Verification Method |
|--------|----------|-----------|-------------------|---------------------|
| INFRA-01 | N8N_CONCURRENCY_PRODUCTION_LIMIT=1 active | smoke | `railway variables --service n8n` | Confirm env var set; trigger two overlapping runs, check execution queue |
| INFRA-02 | DB_QUERY_LIMIT_MAX=100000 active on NocoDB | smoke | `railway variables --service nocodb` | Confirm env var set |
| FIX-01 | Two overlapping runs process different leads | manual | Trigger two runs within 10s, compare execution logs | No shared lead IDs in both outputs |
| FIX-02 | Single run produces exactly 5 completions | manual | Trigger with 5+ pending leads, check execution log | 5 NocoDB PATCH success calls visible |
| FIX-03 | No 429 errors on OpenRouter during 5-lead run | smoke | Trigger full run, inspect execution log | No red error nodes on OpenRouter nodes |
| FIX-04 | Hunter called when name exists but email empty | manual | Seed a lead with name only, trigger run | Execution log shows Hunter - Contact node executed |
| FIX-05 | Lead with slow verification written as verification_timeout | manual | Submit email that No2Bounce processes slowly | NocoDB row shows `status=verification_timeout` after 6 retries |
| FIX-06 | wf-latest sees all pending rows > 100 | manual | Insert 150 pending leads, trigger run | All 150 visible in pagination loop output |
| FIX-07 | wf-discovery reads all discovery + leads rows | manual | Confirm Read Discovery/Leads in pagination loop returns count matching NocoDB UI total | Row counts match |

### Sampling Rate

- **Per task commit:** Manual trigger of the specific changed workflow in n8n editor
- **Per wave merge:** Full wf-latest run with 5 pending leads, check NocoDB state matches success criteria
- **Phase gate (before /gsd:verify-work):** All 5 success criteria from phase definition confirmed in NocoDB + n8n execution logs

### Wave 0 Gaps

- [ ] Verify `$http.request()` availability in Code nodes on current n8n Railway version
- [ ] Confirm NocoDB `UpdatedAt` / `updated_at` field name casing from table schema
- [ ] Confirm current n8n version on Railway (for `N8N_CONCURRENCY_PRODUCTION_LIMIT` vs legacy env var name)

*(No test files to create — this is an n8n-only environment; all testing is manual execution validation)*

---

## Sources

### Primary (HIGH confidence)

- `.planning/research/ARCHITECTURE.md` — Loop Over Items pattern, pessimistic status lock, NocoDB pagination, Anymail/Hunter fallback fix, error handling patterns (verified against n8n official docs)
- `.planning/research/PITFALLS.md` — NocoDB row cap, concurrent trigger overlap, payload size limit, 300s task timeout, OpenRouter rate limits (cross-referenced with official sources)
- `wf-latest.json` — Direct workflow inspection; confirmed: IF No Contact AND bug (line 1089), Parse Poll 4 forced verdict (id e51b9dfe), Read All Rows limit=10000 (id 90b8fd61), Read Column E limit=10000 (id 60be1b05), all `.first()` references
- `wf-discovery.json` — Direct workflow inspection; confirmed: Read Discovery limit=10000 (id disc-read-discovery), Read Leads limit=10000 (id disc-read-leads), name-based dedup in Dedup Against Leads

### Secondary (MEDIUM confidence)

- ARCHITECTURE.md cites: [n8n Loop Over Items official docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.splitinbatches/), [n8n Concurrency Control](https://docs.n8n.io/hosting/scaling/concurrency-control/), [n8n Error Handling](https://docs.n8n.io/flow-logic/error-handling/)
- ARCHITECTURE.md cites: [NocoDB REST APIs](https://nocodb.com/docs/product-docs/developer-resources/rest-apis), [NocoDB Pagination discussion](https://github.com/nocodb/nocodb/discussions/1999)

### Tertiary (LOW confidence — flagged)

- `$http.request()` in Code nodes — documented in ARCHITECTURE.md as LOW confidence; needs verification against current Railway n8n version before use in pagination Code node

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all patterns use existing built-in n8n nodes; no new libraries
- Architecture: HIGH — bugs confirmed by direct workflow JSON inspection; patterns from ARCHITECTURE.md (pre-researched with official docs)
- Pitfalls: HIGH — pitfalls confirmed by direct code inspection (AND bug, forced verdict, .first() pattern) or documented in PITFALLS.md with official sources

**Research date:** 2026-03-24
**Valid until:** 2026-06-24 (stable n8n/NocoDB APIs; 90-day validity)
