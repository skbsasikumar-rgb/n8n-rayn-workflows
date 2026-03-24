---
phase: 01-workflow-reliability
plan: 03
subsystem: workflow
tags: [n8n, openrouter, rate-limit, backoff, wait-node, splitInBatches, loop-back, continueOnFail, first-reference]

# Dependency graph
requires:
  - phase: 01-workflow-reliability
    plan: 02
    provides: "Loop Over Items (splitInBatches, batchSize=1) added; pessimistic lock; no stale Filter Unprocessed .first() refs"
provides:
  - "6 Wait nodes (1-second timeInterval) before each OpenRouter HTTP Request in enrichment loop (FIX-03)"
  - "All 11 terminal status nodes loop back to Loop Over Items input (FIX-02 completion)"
  - "Loop Done NoOp connected to Loop Over Items output[0] (done port)"
  - "All .first() references replaced in 7 Code nodes and 5 HTTP Request nodes inside loop body"
  - "continueOnFail=True on all 22 HTTP Request nodes in the loop body"
affects: [01-04, 01-05]

# Tech tracking
tech-stack:
  added:
    - "n8n-nodes-base.wait (timeInterval, 1 second) — OpenRouter backoff pattern"
  patterns:
    - "Wait node (not Code node sleep) for API rate-limit backoff — avoids task runner timeout"
    - "Fixed-1s delay per OpenRouter call adds 6s per lead, 30s for 5-lead batch (safe below 300s timeout)"
    - "All terminal nodes in loop body must loop back to Loop Over Items input[0]"
    - "continueOnFail=True on all HTTP nodes in loop body — one lead failure cannot stop remaining leads"

key-files:
  created: []
  modified:
    - wf-latest.json

key-decisions:
  - "Used 6 Wait nodes (one before each of 6 OpenRouter calls) rather than the minimum 3 — all 4 main-loop OpenRouter calls plus 2 vendor/enrichment calls get backoff protection"
  - "Fixed .first() in HTTP Request node jsonBody/URL parameters as well as Code nodes — the .first() pattern appears in both node types inside the loop body"
  - "Set continueOnFail=True on all HTTP Request nodes in loop (not just previously-flagged ones) — ensures any network error on any lead does not halt the entire batch run"
  - "Loop-back connection added from all 11 terminal nodes (status nodes + Write Partial & Pending) to Loop Over Items — without this, the loop was effectively single-item only despite batchSize=1"

requirements-completed: [FIX-02, FIX-03]

# Metrics
duration: 4min
completed: 2026-03-24
---

# Phase 01 Plan 03: OpenRouter Backoff and Loop End-to-End Fix Summary

**6 Wait nodes added before each OpenRouter call in the enrichment loop; all 11 terminal nodes now loop back to Loop Over Items, enabling true 5-lead-per-run batch processing**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-24T03:50:37Z
- **Completed:** 2026-03-24T03:54:00Z
- **Tasks:** 2 of 2
- **Files modified:** 1 (wf-latest.json)

## Accomplishments

- Added 6 Wait nodes (1-second timeInterval delay, `n8n-nodes-base.wait`) before each OpenRouter HTTP Request in the main enrichment loop: Clean Name, URL Dedup, URL Validate, HIA Gate, Enrichment, Vendor Enrichment1
- Connected all 11 terminal status nodes (clean failed, serper failed, url duplicate, no url found, url unreachable, url rejected, scrape failed, not HIA relevant, no contact found, enrichment failed, Write Partial & Pending) back to Loop Over Items input — this was the critical missing piece that prevented all 5 leads from being processed
- Added Loop Done NoOp node connected to Loop Over Items output[0] (done port) — fires after all batches exhausted
- Replaced all `.first()` references inside the loop body with `.item` pattern: 7 Code nodes and 5 HTTP Request nodes fixed
- Set `continueOnFail=True` on all 22 HTTP Request nodes inside the loop body

## Task Commits

1. **Task 1: Add Wait nodes before each OpenRouter HTTP Request (FIX-03)** - `b5f26f4` — 6 Wait nodes added and rewired
2. **Task 2: Fix Loop Over Items processes all 5 leads end-to-end (FIX-02)** - `a122804` — loop-back connections, Loop Done, .first() fixes, continueOnFail

## Files Created/Modified

- `/Users/sasikumar/Documents/n8n/wf-latest.json` — enrichment workflow with backoff delays and complete loop wiring

## Wait Node Chain (per lead, per OpenRouter call)

```
GET Full Record
  |
Wait Before OpenRouter - Clean Name (1s)
  |
OpenRouter - Clean Name
  |
...
Prep URL Data
  |
Wait Before OpenRouter - URL Dedup (1s)
  |
OpenRouter - URL Dedup
  |
... (4 more Wait->OpenRouter pairs)
  |
Write Partial & Pending
  |
Loop Over Items (loop back: process next lead)
```

## Loop Structure (after fixes)

```
IF No Pending Leads
  |-- true (_skip) --> No Pending - Stop (NoOp)
  |-- false ---------> Loop Over Items (splitInBatches, batchSize=1)
                           |
                           output[0] (done) --> Loop Done (NoOp)
                           output[1] (batch) -> PATCH Status Processing
                                                     |
                                                     [enrichment chain: 6x Wait->OpenRouter]
                                                     |
                                                All terminal nodes (11)
                                                     |
                                                Loop Over Items (loop back)
```

## Decisions Made

- Used all 6 OpenRouter nodes for Wait node coverage (not the minimum 3 from acceptance criteria) — the Vendor Enrichment1 path and Enrichment path are both active depending on HIA classification, so both need backoff
- Fixed `.first()` in HTTP Request node `jsonBody` and URL parameters as well as Code nodes — the pattern appeared in Serper - Search, OpenRouter - URL Dedup, OpenRouter - URL Validate, Serper - Scrape, Hunter - Contact
- Added `continueOnFail=True` to all HTTP nodes in the loop (beyond the original plan scope) as a correctness requirement — Rule 2 auto-fix applied

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Fixed .first() in HTTP Request node parameters**
- **Found during:** Task 2
- **Issue:** The `.first()` audit revealed 5 HTTP Request nodes (Serper - Search, OpenRouter - URL Dedup/Validate, Serper - Scrape, Hunter - Contact) also had `.first()` references in their `jsonBody` and URL expression parameters — not just in Code nodes as the plan anticipated
- **Fix:** Applied the same `.item` replacement to HTTP Request node parameter strings
- **Files modified:** wf-latest.json
- **Commit:** a122804

**2. [Rule 2 - Missing critical functionality] Set continueOnFail=True on 22 HTTP Request nodes**
- **Found during:** Task 2
- **Issue:** Only HTTP Status Check, Anymail - Contact, and Hunter - Contact had `continueOnFail=True`. All other HTTP nodes in the loop (PATCH Status Processing, GET Full Record, all 6 OpenRouter nodes, all status PATCH nodes, Write Partial & Pending) lacked this setting. Without it, any network error on any node stops the entire batch run
- **Fix:** Set `continueOnFail=True` on all 22 HTTP Request nodes inside the loop body
- **Files modified:** wf-latest.json
- **Commit:** a122804

---

**Total deviations:** 2 auto-fixed (both Rule 2 - Missing critical functionality)
**Impact on plan:** Both fixes are correctness requirements. Without them, the loop would still fail on network errors and Code nodes would still break on multi-item batches if batchSize is ever changed.

## Issues Encountered

None — the plan was clear and wf-latest.json structure was well-understood from Plan 02.

## Known Stubs

None — all new nodes are fully functional. Wait nodes have real 1-second delays. Loop Done NoOp is a correct terminal node. All loop-back connections are real n8n wiring.

## Next Phase Readiness

- wf-latest.json ready for Plan 04: Contact fallback OR fix (FIX-04) — IF No Contact combinator change from AND to OR
- FIX-02 (batch processing) and FIX-03 (backoff) are both complete — the loop will now process all 5 pending leads per trigger run with 1-second delays between OpenRouter calls
- Total delay per 5-lead run: 6 Wait nodes × 1s × 5 leads = 30 seconds additional delay (well within 300s task timeout)

---
*Phase: 01-workflow-reliability*
*Completed: 2026-03-24*

## Self-Check: PASSED

- FOUND: wf-latest.json
- FOUND: 01-03-SUMMARY.md
- FOUND: commit b5f26f4 (feat(01-03): add Wait nodes before each OpenRouter HTTP Request)
- FOUND: commit a122804 (feat(01-03): fix Loop Over Items to process all 5 leads end-to-end)
- FOUND: wf-latest.json is valid JSON
- FOUND: 6 Wait nodes before OpenRouter calls
- FOUND: Loop Over Items output[0] -> Loop Done
- FOUND: All 11 terminal nodes -> Loop Over Items (loop back)
- FOUND: No .first() references in main loop nodes
