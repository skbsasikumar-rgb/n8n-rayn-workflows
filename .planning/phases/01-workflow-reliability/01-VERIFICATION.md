---
phase: 01-workflow-reliability
verified: 2026-03-24T06:00:00Z
status: human_needed
score: 7/9 must-haves verified (2 require human confirmation — Railway env vars)
re_verification: false
human_verification:
  - test: "Open Railway Dashboard -> n8n service -> Variables tab and confirm N8N_CONCURRENCY_PRODUCTION_LIMIT=1, N8N_PAYLOAD_SIZE_MAX=128, N8N_RUNNERS_TASK_TIMEOUT=600 are set and service is Active"
    expected: "All three variables present with exact values; n8n service status = Active"
    why_human: "Railway environment variables are infrastructure config with no codebase artifact. INFRA-01 requires N8N_CONCURRENCY_PRODUCTION_LIMIT=1 as secondary race condition defense."
  - test: "Open Railway Dashboard -> NocoDB service -> Variables tab and confirm DB_QUERY_LIMIT_MAX=100000 and DB_QUERY_LIMIT_DEFAULT=1000 are set and service is Active; optionally run: curl -s -H 'xc-token: SqqM8YcDuzXGijg0oY7PvqTcPX5H-r2sYqbAOWTN' 'https://nocodb-production-f802.up.railway.app/api/v1/db/data/noco/pb7f1zou786xyqc/mey3zgihq7o4at9?limit=1' | jq '.pageInfo'"
    expected: "Both variables present with exact values; NocoDB API responds with pageInfo object"
    why_human: "Railway environment variables for NocoDB are infrastructure config. INFRA-02 removes the silent row cap that makes FIX-06 and FIX-07 effective."
---

# Phase 1: Workflow Reliability Verification Report

**Phase Goal:** The enrichment pipeline runs continuously, processes all 5 leads per trigger, never races on the same lead, paginates across the full NocoDB table, and handles verification timeouts without manual intervention.
**Verified:** 2026-03-24T06:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Stuck leads (status=processing for >10 min) are automatically reset to pending on every trigger run | VERIFIED | `Cleanup Stuck Processing` Code node is first after Schedule Trigger; uses 10-min threshold; PATCH to pending |
| 2 | Two overlapping 3-minute trigger runs cannot grab the same lead | VERIFIED | `Get Pending IDs` (limit=5, fields=Id only) -> `PATCH Status Processing` (status=processing) fires before any enrichment API call; pessimistic lock confirmed in connections |
| 3 | Lead status is set to processing BEFORE any enrichment API call | VERIFIED | Schedule Trigger -> Cleanup -> Get Pending IDs -> Parse Pending IDs -> IF No Pending Leads -> Loop Over Items -> `PATCH Status Processing` -> `GET Full Record` -> enrichment chain |
| 4 | A single trigger run processes all 5 filtered leads (not just the first one) | VERIFIED | Loop Over Items (splitInBatches, batchSize=1) wraps full enrichment chain; all 11 terminal status nodes have loop-back connection to Loop Over Items; `IF No Pending Leads [false]` -> Loop Over Items |
| 5 | There is a 1-second delay before each OpenRouter API call (prevents 429 errors at 5× throughput) | VERIFIED | 6 Wait nodes confirmed: Wait Before OpenRouter - Clean Name, URL Dedup, URL Validate, HIA Gate, Enrichment, Vendor Enrichment1; each has `resume=timeInterval, interval=1, unit=seconds` |
| 6 | Hunter is called when a lead has a name but no email (OR logic, not AND) | VERIFIED | `IF No Contact` and `IF Still No Contact` both confirmed `"or"` combinator in parameters; no stale AND combinator |
| 7 | A lead whose No2Bounce validation is still processing after retries is written as verification_timeout, not forced to valid/invalid | VERIFIED | `Parse Poll 4` contains `isReady` guard: `const status = isReady ? (isValid ? 'valid' : 'invalid') : 'verification_timeout'`; `IF Ready 4` node routes to dedicated `Status - verification timeout` PATCH node |
| 8 | wf-latest paginates all NocoDB GET requests using pageInfo.isLastPage loop | VERIFIED | Three pagination Code nodes confirmed: `Paginate Read All Rows`, `Paginate Read Column E`, `Paginate Read All Rows WF2`; all have isLastPage loop, pageSize=1000, page += 1; zero `limit=10000` strings remain |
| 9 | A separate scheduled workflow retries verification_timeout leads every 30 minutes | VERIFIED | `wf-no2bounce-retry.json` exists; Schedule Trigger `minutesInterval=30`; GET with `where=(status,eq,verification_timeout)`; Loop Over Items (batchSize=1); Wait 15s; PATCH result back to NocoDB |
| 10 | wf-discovery paginates all NocoDB GET requests using pageInfo.isLastPage loop | VERIFIED | `Paginate Read Discovery` (table mp36f8mgk115qse) and `Paginate Read Leads` (table mey3zgihq7o4at9) both confirmed with isLastPage loop, pageSize=1000; zero `limit=10000` strings remain |
| 11 | wf-discovery deduplicates leads by website URL before writing to NocoDB | VERIFIED | `Dedup Against Leads` uses `website_url || url` as dedup key; `existingUrls` Set for cross-batch dedup; `batchUrls` Set for in-batch dedup |
| 12 | Railway n8n env vars are set (N8N_CONCURRENCY_PRODUCTION_LIMIT=1, N8N_PAYLOAD_SIZE_MAX=128, N8N_RUNNERS_TASK_TIMEOUT=600) | NEEDS HUMAN | Infrastructure — no codebase artifact; confirmed by user in SUMMARY but not machine-verifiable |
| 13 | Railway NocoDB env vars are set (DB_QUERY_LIMIT_MAX=100000, DB_QUERY_LIMIT_DEFAULT=1000) | NEEDS HUMAN | Infrastructure — no codebase artifact; confirmed by user in SUMMARY but not machine-verifiable |

**Score:** 11/11 automated truths verified; 2/2 human truths pending confirmation

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `wf-latest.json` | Enrichment workflow with cleanup, pessimistic lock, loop, backoff, OR contact, verification_timeout, pagination | VERIFIED | 110 nodes; valid JSON; all structural patterns confirmed |
| `wf-no2bounce-retry.json` | Standalone No2Bounce retry workflow on 30-min schedule | VERIFIED | 12 nodes; valid JSON; scheduleTrigger, Loop Over Items, Wait 15s, PATCH NocoDB Status all confirmed |
| `wf-discovery.json` | Discovery workflow with isLastPage pagination and URL-based dedup | VERIFIED | 15 nodes; valid JSON; Paginate Read Discovery + Paginate Read Leads + Dedup Against Leads confirmed |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Schedule Trigger | Cleanup Stuck Processing | First node in connections array | WIRED | Confirmed: `conns['Schedule Trigger']['main'][0][0]['node'] == 'Cleanup Stuck Processing'` |
| Get Pending IDs | PATCH Status Processing | Loop Over Items batch output | WIRED | Get Pending IDs -> Parse Pending IDs -> IF No Pending Leads -> Loop Over Items [output 1] -> PATCH Status Processing |
| IF No Contact | Hunter HTTP Request | OR combinator (name OR email empty) | WIRED | `IF No Contact [output 0]` -> `Hunter - Contact`; combinator confirmed `"or"` |
| Parse Poll 4 | Status - verification timeout | IF Ready 4 false output | WIRED | Parse Poll 4 -> IF Ready 4 -> [false] -> Status - verification timeout; verification_timeout code confirmed |
| Paginate Read All Rows WF2 | Filter WF2 | Direct connection | WIRED | Bypasses orphaned Parse Read Items WF2; Paginate node feeds Filter WF2 directly |
| wf-no2bounce-retry Schedule Trigger | GET verification_timeout rows | First node after trigger | WIRED | Schedule Trigger -> GET Timeout Leads with `where=(status,eq,verification_timeout)` |
| PATCH NocoDB Status (retry) | Loop Over Items (retry) | Loop-back after each lead | WIRED | `PATCH NocoDB Status [output 0]` -> `Loop Over Items` confirmed in connections |
| Paginate Read Discovery | Dedup Against Leads | `$('Paginate Read Discovery').all()` | WIRED | Dedup node references updated node names; `existingUrls` from Paginate Read Leads |

**Note on Status - verification timeout:** This terminal node has no loop-back to Loop Over Items. However, this is by design — `Status - verification timeout` is in the WF2 sub-chain (triggered by `Schedule Trigger WF2`, not the main Loop Over Items trigger). WF2 processes one lead per run due to blocking No2Bounce polling waits (up to 16 min per lead); no loop-back is needed in that context. The main Loop Over Items chain terminates via `Write Partial & Pending` for leads that complete Stage 1.

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `wf-latest.json` — Get Pending IDs | `list` (NocoDB rows) | HTTP GET `?where=(status,eq,pending)&limit=5&fields=Id` against live NocoDB endpoint | Yes — live API call, no static fallback | FLOWING |
| `wf-latest.json` — Cleanup Stuck Processing | `stuckRows` | HTTP GET with 10-min timestamp filter, PATCH each stuck row | Yes — live API calls | FLOWING |
| `wf-latest.json` — Paginate Read All Rows | `allRecords` | While loop via `$http.request()` until `pageInfo.isLastPage` | Yes — paginated live API read | FLOWING |
| `wf-no2bounce-retry.json` — Parse Poll Result | `email_status` | No2Bounce Poll response (`overallStatus`, `percent`, `Deliverable`) | Yes — live API; falls back to `verification_timeout` if not ready | FLOWING |
| `wf-discovery.json` — Dedup Against Leads | `newLeads` | `Paginate Read Discovery.all()` filtered against `Paginate Read Leads.all()` URL set | Yes — both pagination nodes produce real NocoDB data | FLOWING |

---

### Behavioral Spot-Checks

Skipped for wf-latest.json, wf-no2bounce-retry.json, and wf-discovery.json — these are n8n workflow JSON files. They are not directly runnable from the shell; execution requires the n8n runtime. No entry points exist for static behavioral testing. Testing must be done by importing workflows into n8n and triggering execution manually.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| INFRA-01 | 01-01-PLAN | N8N_CONCURRENCY_PRODUCTION_LIMIT=1 on n8n Railway service | NEEDS HUMAN | No code artifact; user-confirmed in 01-01-SUMMARY but not machine-verifiable |
| INFRA-02 | 01-01-PLAN | DB_QUERY_LIMIT_MAX=100000 on NocoDB Railway service | NEEDS HUMAN | No code artifact; user-confirmed in 01-01-SUMMARY but not machine-verifiable |
| FIX-01 | 01-02-PLAN | Pessimistic status lock — set status=processing before enrichment | SATISFIED | `Cleanup Stuck Processing` + `Get Pending IDs` + `PATCH Status Processing` confirmed in wf-latest.json; Schedule Trigger -> Cleanup connection verified |
| FIX-02 | 01-03-PLAN | Replace .first() with Loop Over Items (batchSize=1) — all 5 leads per run | SATISFIED | Loop Over Items (splitInBatches, batchSize=1) confirmed; 11/11 terminal nodes loop back; zero stale `$('Filter Unprocessed').first()` references |
| FIX-03 | 01-03-PLAN | OpenRouter backoff — 1s delay before each OpenRouter call | SATISFIED | 6 Wait nodes confirmed (timeInterval, 1 second each); all wired before corresponding OpenRouter HTTP Request nodes |
| FIX-04 | 01-04-PLAN | IF No Contact combinator AND -> OR | SATISFIED | Both `IF No Contact` and `IF Still No Contact` nodes confirmed `"or"` combinator in parameters |
| FIX-05 | 01-04-PLAN (Part A) + 01-05-PLAN (Part B) | verification_timeout on slow No2Bounce + standalone retry workflow | SATISFIED | Part A: `Parse Poll 4` isReady guard confirmed; Part B: `wf-no2bounce-retry.json` confirmed with correct structure and loop |
| FIX-06 | 01-04-PLAN | wf-latest NocoDB GET pagination using isLastPage loop | SATISFIED | 3 Paginate Code nodes confirmed; zero `limit=10000` remains; pageSize=1000; page += 1 increments |
| FIX-07 | 01-05-PLAN | wf-discovery NocoDB GET pagination using isLastPage loop | SATISFIED | `Paginate Read Discovery` (mp36f8mgk115qse) and `Paginate Read Leads` (mey3zgihq7o4at9) confirmed; zero `limit=10000`; URL-based dedup with in-batch Set |

**Orphaned requirements:** None. All 9 Phase 1 requirements are claimed by exactly one or two plans. No requirements listed under Phase 1 in REQUIREMENTS.md are unclaimed.

---

### Anti-Patterns Found

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `wf-latest.json` — Filter WF2 | `return [{ json: pending[0].json }]` — WF2 processes 1 lead per run | Info | WF2 sub-chain (Schedule Trigger WF2) is a legacy email-validation path with blocking No2Bounce polling waits (up to 16 min per lead). Single-lead-per-run is by design given the polling time budget. Not in FIX-02 scope. |
| `wf-latest.json` — WF2 nodes | Multiple `.first()` references to `$('Filter WF2')` and `$('No2Bounce - Submit')` | Info | All `.first()` references are inside the WF2 sub-chain (triggered by Schedule Trigger WF2, not Loop Over Items). Not stale — these reference the correct predecessor nodes within the WF2 linear execution path. Not in scope of Plan 02/03 fixes. |
| `wf-latest.json` — Parse Read Items WF2 | Node exists but is orphaned (both Paginate Read All Rows WF2 and Parse Read Items WF2 feed Filter WF2) | Warning | `Paginate Read All Rows WF2` correctly bypasses `Parse Read Items WF2` and feeds `Filter WF2` directly. `Parse Read Items WF2` is still connected to Filter WF2 but nothing feeds into it — it is an orphaned node. At runtime n8n ignores orphaned nodes. No functional impact. |
| `wf-latest.json` — Status - verification timeout | No outgoing connection (does not loop back to Loop Over Items) | Info | Confirmed design: this node is in the WF2 chain, not the main Loop Over Items body. WF2 ends after writing the timeout status; the retry workflow (wf-no2bounce-retry.json) picks up these leads on its own 30-min schedule. |

**No blocker anti-patterns found.**

---

### Human Verification Required

#### 1. Railway n8n Environment Variables (INFRA-01)

**Test:** Open Railway Dashboard (https://railway.app) -> n8n service -> Variables tab
**Check all three variables exist with exact values:**
- `N8N_CONCURRENCY_PRODUCTION_LIMIT` = `1`
- `N8N_PAYLOAD_SIZE_MAX` = `128`
- `N8N_RUNNERS_TASK_TIMEOUT` = `600`
**Also check:** n8n service deployment status shows "Active" (green)
**Expected:** All three present; service Active
**Why human:** Railway environment variables have no codebase artifact. These are the infrastructure foundation for the race condition fix (secondary defense) and payload/timeout handling.

#### 2. Railway NocoDB Environment Variables (INFRA-02)

**Test:** Open Railway Dashboard -> NocoDB service -> Variables tab
**Check both variables exist with exact values:**
- `DB_QUERY_LIMIT_MAX` = `100000`
- `DB_QUERY_LIMIT_DEFAULT` = `1000`
**Optionally run API test:**
```
curl -s -H "xc-token: SqqM8YcDuzXGijg0oY7PvqTcPX5H-r2sYqbAOWTN" \
  "https://nocodb-production-f802.up.railway.app/api/v1/db/data/noco/pb7f1zou786xyqc/mey3zgihq7o4at9?limit=1" | jq '.pageInfo'
```
**Expected:** Both variables present; NocoDB API returns pageInfo object; service Active
**Why human:** Railway NocoDB environment variables have no codebase artifact. DB_QUERY_LIMIT_MAX=100000 removes the silent row cap that makes FIX-06 and FIX-07 pagination effective.

---

### Gaps Summary

No gaps found in automated checks. All 7 code-verifiable requirements (FIX-01 through FIX-07) are fully implemented and wired. The 2 infrastructure requirements (INFRA-01, INFRA-02) are user-confirmed in the SUMMARY but cannot be verified programmatically — they require Railway Dashboard confirmation.

**Notable observation:** `wf-no2bounce-retry.json` fetches up to 50 verification_timeout leads per 30-min run. At the current scale (Singapore HIA niche market), this is sufficient. If the backlog exceeds 50, the next 30-min run processes the next batch.

---

## Commit Verification

All commits referenced in SUMMARY files confirmed to exist in git history:

| Commit | Description | Plan |
|--------|-------------|------|
| `d2bafcd` | feat(01-02): add Cleanup Stuck Processing node at trigger start | 01-02 |
| `e6ba086` | feat(01-02): implement pessimistic status lock with two-step fetch pattern | 01-02 |
| `b5f26f4` | feat(01-03): add Wait nodes before each OpenRouter HTTP Request in enrichment loop | 01-03 |
| `a122804` | feat(01-03): fix Loop Over Items to process all 5 leads end-to-end (FIX-02) | 01-03 |
| `737a745` | feat(01-04): fix IF No Contact OR logic and Parse Poll 4 verification_timeout | 01-04 |
| `8198854` | feat(01-04): replace limit=10000 NocoDB GETs with pagination loops (FIX-06) | 01-04 |
| `07682ff` | feat(01-05): create standalone No2Bounce retry workflow (FIX-05 Part B) | 01-05 |
| `b9e3b9e` | feat(01-05): add NocoDB pagination and URL-based dedup to wf-discovery (FIX-07) | 01-05 |

---

_Verified: 2026-03-24T06:00:00Z_
_Verifier: Claude (gsd-verifier)_
