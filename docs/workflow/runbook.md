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

1. Disable the live workflow.
2. Stop or wait for any in-flight executions to finish.
3. Clear old execution history for the workflow under test.
4. Reset only the target rows for the rerun.
5. For URL discovery reruns, clear stale URL-pick fields such as `status`, `last_stage`, `last_error`, `url_picked`, `canonical_domain`, `duplicate_of_id`, and `search_evidence_json`.
6. For enrichment reruns, preserve `url_picked` and clear only downstream fields such as `best_url`, `homepage_root_url`, `website_content`, `website_scrape`, `company_homepage_name`, `parent_company`, `source_urls`, `notes`, `confidence`, `last_stage`, and `last_error`.
7. Add a fresh rerun batch marker when possible.
8. Re-enable the workflow.
9. Run a small test set first.
10. Inspect raw search, selected URL, scrape result, and final writeback.
11. Scale only after the small set passes.

For enrichment reruns, keep the n8n Crawl4AI HTTP timeout higher than the per-page timeout budget. The current worker uses a 300s n8n request timeout because five-page public crawls can exceed 120s on heavier sites.

## Webhook Paths

- `rayn-url-picker-v1`: single-row URL discovery path; may call OpenSERP and OpenRouter.
- `rayn-url-picker-batch`: enrichment rerun path for rows with existing `url_picked`; must not call OpenSERP.

## Restart Rule

Restart `primary` only when:

- executions are stuck.
- the workflow was changed and n8n state appears inconsistent.
- webhooks or credentials behave differently from the saved workflow definition.

Do not restart NocoDB just to clear stale executions. Old execution state lives in n8n, not in the table service.

## Scale Rule

Do not increase concurrency until:

- the small fixed test set passes.
- no rows are stuck in `processing`.
- failures have clear `last_stage` and `last_error`.
