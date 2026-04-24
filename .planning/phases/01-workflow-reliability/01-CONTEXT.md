# Phase 1: Workflow Reliability - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix all 6 active bugs in wf-latest and wf-discovery so the enrichment pipeline runs continuously at volume without manual intervention. No new capabilities — reliability and correctness only.

</domain>

<decisions>
## Implementation Decisions

### No2Bounce Verification Timeout
- **D-01:** Redesign as a **separate scheduled workflow** (every 30 min) that checks NocoDB for `status=verification_timeout` leads and re-submits them to No2Bounce. Do NOT use Wait node inline polling.
- **D-02:** Enrichment workflow writes `verification_timeout` status after 6 retries and moves on — it never blocks waiting for No2Bounce to respond.
- **D-03:** Separate retry workflow runs independently: read `verification_timeout` leads → re-submit to No2Bounce → poll once → update status to `valid`/`invalid`/`verification_timeout` (reset counter).

### Stuck Lead Recovery
- **D-04:** Auto-cleanup built into wf-latest — at the **start of each enrichment run**, before fetching pending leads, reset any rows where `status=processing` AND `updated_at` is older than 10 minutes back to `status=pending`.
- **D-05:** This cleanup runs on every trigger, not as a separate workflow. Ensures no manual NocoDB intervention ever needed for stuck leads.

### Race Condition Fix
- **D-06:** Pessimistic status lock pattern: fetch 5 lead IDs only → immediately `UPDATE status=processing` → then fetch full records → begin enrichment chain. Two-step fetch prevents concurrent runs from grabbing the same lead.
- **D-07:** Additionally set `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` on Railway as a secondary defense.

### Batch Processing
- **D-08:** Replace `.first()` with Loop Over Items node (Split in Batches, batch size 1) so all 5 filtered leads are processed per run.
- **D-09:** Add OpenRouter backoff (1s → 2s → 5s → 13s) before enabling 5× throughput to avoid rate limiting.

### Contact Fallback
- **D-10:** Change IF No Contact condition from AND to OR — Hunter is triggered when name **or** email is empty (not both).

### NocoDB Pagination
- **D-11:** Replace hardcoded GET calls with `pageInfo.isLastPage` pagination loops in both wf-latest (pending lead fetches) and wf-discovery (Read Discovery + Read Leads fetches).
- **D-12:** Set `DB_QUERY_LIMIT_MAX=100000` on NocoDB Railway service (env var), and `DB_QUERY_LIMIT_DEFAULT=1000` to cap page size.

### Railway Env Vars
- **D-13:** Set on n8n service: `N8N_CONCURRENCY_PRODUCTION_LIMIT=1`, `N8N_PAYLOAD_SIZE_MAX=128`, `N8N_RUNNERS_TASK_TIMEOUT=600`.
- **D-14:** Set on NocoDB service: `DB_QUERY_LIMIT_MAX=100000`, `DB_QUERY_LIMIT_DEFAULT=1000`.

### Claude's Discretion
- Exact backoff timing implementation (Wait node durations)
- Pagination loop node structure (Code node vs chained HTTP Request nodes)
- In-batch URL hash dedup implementation in wf-discovery

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Workflow files (primary source of truth)
- `wf-latest.json` — Main enrichment workflow; all bug fixes apply here
- `wf-discovery.json` — Lead discovery workflow; pagination and in-batch dedup fixes apply here

### Project context
- `.planning/REQUIREMENTS.md` — Full requirement list (INFRA-01/02, FIX-01 through FIX-07)
- `.planning/PROJECT.md` — Stack details, API budget constraint, platform constraints (n8n only, no code outside nodes)
- `.planning/research/ARCHITECTURE.md` — Implementation patterns for each fix (Loop Over Items, status lock, pagination, backoff)
- `.planning/research/PITFALLS.md` — Critical risks: concurrent trigger overlap, NocoDB row cap, No2Bounce polling timeout ceiling

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Dedup Against Leads` Code node (wf-discovery): existing `$input.all()` pattern — reuse for in-batch dedup
- `Parse Discovery Items` / `Parse Leads Items` nodes: existing NocoDB parse pattern — extend for pagination
- `IF URL Duplicate` / `IF URL None` nodes: existing IF node pattern — same structure for contact fallback fix (AND → OR)

### Established Patterns
- NocoDB interaction: HTTP Request nodes calling NocoDB REST API v2 (not native n8n NocoDB node)
- Status management: `status` field on leads table drives all workflow routing
- LLM calls: OpenRouter HTTP Request nodes with JSON body — backoff nodes insert before these
- Scraping: Serper scrape via HTTP Request node — downstream of URL validation chain

### Integration Points
- **Race condition fix**: Inserts a NocoDB PATCH node between "Get Pending Leads" and "Fetch Full Records" in wf-latest Phase 1
- **Auto-cleanup**: New Code node at very start of wf-latest trigger, before any lead fetching
- **No2Bounce retry**: New standalone workflow (separate from wf-latest) triggered by Schedule node, reads `verification_timeout` rows
- **Batch fix**: Loop Over Items wraps the 5-lead processing chain in wf-latest
- **Pagination**: New loop structure wraps existing NocoDB GET nodes in both workflows

</code_context>

<specifics>
## Specific Ideas

- Separate No2Bounce retry workflow should run every 30 minutes (not too frequent — No2Bounce is metered)
- Auto-cleanup threshold: 10 minutes in `processing` status = stuck (normal enrichment completes in < 2 min)
- DB_QUERY_LIMIT_MAX set to 100000 (not 10000) — user confirmed this for discovery table scale

</specifics>

<deferred>
## Deferred Ideas

- HTTP status check in wf-discovery — noted as low priority; wf-latest already has it; defer to future phase or backlog
- Monitoring/alerting for stuck leads — out of scope for v1 reliability fix

</deferred>

---

*Phase: 01-workflow-reliability*
*Context gathered: 2026-03-24*
