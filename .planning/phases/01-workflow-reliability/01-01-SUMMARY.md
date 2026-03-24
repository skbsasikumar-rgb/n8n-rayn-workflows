---
phase: 01-workflow-reliability
plan: "01"
subsystem: infra
tags: [railway, n8n, nocodb, env-vars, concurrency, row-limit]

# Dependency graph
requires: []
provides:
  - N8N_CONCURRENCY_PRODUCTION_LIMIT=1 active on n8n worker service (secondary race condition defense)
  - N8N_PAYLOAD_SIZE_MAX=128 active on n8n worker and primary services (large NocoDB response support)
  - N8N_RUNNERS_TASK_TIMEOUT=600 active on n8n worker service (No2Bounce polling and batch run headroom)
  - DB_QUERY_LIMIT_MAX=100000 active on NocoDB service (silent row cap removed)
  - DB_QUERY_LIMIT_DEFAULT=1000 active on NocoDB service (pagination loop page size established)
affects:
  - 01-02-PLAN (race condition fix relies on concurrency limit as secondary defense)
  - 01-04-PLAN (pagination fix relies on NocoDB row cap being removed)
  - 01-05-PLAN (NocoDB discovery pagination relies on row cap removal)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Railway env vars for service-level config: applied via Dashboard -> Variables tab -> Redeploy"

key-files:
  created: []
  modified: []

key-decisions:
  - "N8N_CONCURRENCY_PRODUCTION_LIMIT=1 set on worker service only (primary services handle UI/API, not executions)"
  - "N8N_PAYLOAD_SIZE_MAX=128 set on both worker and primary to cover all data-path components"
  - "DB_QUERY_LIMIT_DEFAULT=1000 chosen as pagination page size for wf-latest and wf-discovery loops"

patterns-established:
  - "Railway env var changes: always redeploy and confirm Active status before proceeding"

requirements-completed: [INFRA-01, INFRA-02]

# Metrics
duration: human-action (no automation time)
completed: 2026-03-24
---

# Phase 01 Plan 01: Railway Env Var Hardening Summary

**N8N concurrency cap (limit=1), 128MB payload limit, 600s task timeout, and NocoDB 100k row cap all activated on Railway — pipeline foundation for all Phase 1 workflow fixes**

## Performance

- **Duration:** Human-action tasks (no automation clock)
- **Started:** 2026-03-24
- **Completed:** 2026-03-24
- **Tasks:** 2 (both checkpoint:human-action)
- **Files modified:** 0 (infrastructure only — no codebase changes)

## Accomplishments

- n8n worker service: N8N_CONCURRENCY_PRODUCTION_LIMIT=1 prevents overlapping production executions (secondary defense for FIX-01 race condition fix)
- n8n services: N8N_PAYLOAD_SIZE_MAX=128 raises max payload to 128MB; N8N_RUNNERS_TASK_TIMEOUT=600 extends runner timeout to 10 minutes for No2Bounce polling and large batches
- NocoDB service: DB_QUERY_LIMIT_MAX=100000 removes the silent row cap (default ~25-100 rows) that silently truncated GET responses; DB_QUERY_LIMIT_DEFAULT=1000 sets page size for pagination loops in FIX-06/FIX-07
- Both services redeployed and confirmed Active after variable changes; NocoDB API verified responsive post-redeploy

## Task Commits

No per-task commits — both tasks were checkpoint:human-action (manual Railway Dashboard configuration).

**Plan metadata commit:** see final docs commit hash

## Files Created/Modified

None — this plan is infrastructure-only. All changes are Railway service environment variables applied via the Railway Dashboard.

## Decisions Made

- N8N_CONCURRENCY_PRODUCTION_LIMIT=1 applied to the worker service (the service that executes production workflows) rather than the primary/UI service
- N8N_PAYLOAD_SIZE_MAX=128 applied to both worker and primary services to cover all data path components
- DB_QUERY_LIMIT_DEFAULT=1000 chosen as the pagination page size — large enough to minimize loop iterations across a typical leads table, small enough to stay within NocoDB response size limits

## Deviations from Plan

None — plan executed exactly as written. Both env vars sets confirmed by user.

## Issues Encountered

None. Both Railway services redeployed cleanly. NocoDB API responded to test GET request post-redeploy (totalRows: 0 — table currently empty, which is expected).

## User Setup Required

All tasks in this plan were human-action checkpoints completed by Sasikumar directly in the Railway Dashboard:

**n8n service (https://primary-production-a6441.up.railway.app):**
- N8N_CONCURRENCY_PRODUCTION_LIMIT = 1 (set)
- N8N_PAYLOAD_SIZE_MAX = 128 (set)
- N8N_RUNNERS_TASK_TIMEOUT = 600 (set)
- Service redeployed and Active

**NocoDB service (https://nocodb-production-f802.up.railway.app):**
- DB_QUERY_LIMIT_MAX = 100000 (set)
- DB_QUERY_LIMIT_DEFAULT = 1000 (set)
- Service redeployed and Active; API verified responsive

## Next Phase Readiness

- Plan 01-02 (race condition status lock) can now proceed — N8N_CONCURRENCY_PRODUCTION_LIMIT=1 is active as secondary defense
- Plans 01-04 and 01-05 (pagination fixes) will be effective — NocoDB row cap is removed
- No blockers for Phase 1 continuation

---
*Phase: 01-workflow-reliability*
*Completed: 2026-03-24*
