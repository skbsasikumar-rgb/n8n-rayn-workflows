# Workflow Runbook

This runbook starts from the clean rebuild state.

## Before Rebuilding

Verify:

- NocoDB table is empty or contains only intentional test rows.
- live n8n worker and orchestrator workflows are not running old logic.
- credentials remain available.
- worker docs match the intended build scope.

## Worker Build Loop

0. Build first-pass URL picker.
   Verify: OpenSERP Google query is `company_name Singapore`, first 10 results are stored, `url_picked` is updated, and the webhook returns on receipt for long runs.

1. Create the minimal worker workflow.
   Verify: webhook accepts `{ "company_name": "..." }`.

2. Add homepage search.
   Verify: raw search candidates are logged before scoring.

3. Add candidate rejection.
   Verify: directories and social pages are excluded from final candidates.

4. Add homepage picker.
   Verify: `best_url` is a clean homepage root for the test set.

5. Add canonical-domain dedupe.
   Verify: duplicate rows set `duplicate_of_id` and stop enrichment.

6. Add website scrape.
   Verify: scrape failures do not remove verified homepage data.

7. Add parent-company extraction.
   Verify: parent is populated only with clear evidence.

## Rerun Process

1. Clear stale executions.
2. Reset target rows to `pending`.
3. Run a small test set first.
4. Inspect raw search, selected URL, scrape result, and final writeback.
5. Scale only after the small set passes.

## Scale Rule

Do not increase concurrency until:

- the small fixed test set passes.
- no rows are stuck in `processing`.
- failures have clear `last_stage` and `last_error`.
