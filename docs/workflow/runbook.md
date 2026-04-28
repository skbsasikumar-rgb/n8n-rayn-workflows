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
   Verify: Google SERP query is `company_name Singapore`, first 10 results are stored, `url_picked` is updated, claim metadata is preserved through the picker, and the webhook returns on receipt for long runs.

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

8. Add contact search after company enrichment.
   Verify: role buckets are attempted in priority order, generic inboxes are not generated, No2Bounce accepts only deliverable person-specific emails, and exhausted rows end as `contact_search_status = contact_not_found`.

## Contact Search Build Loop

1. Confirm contact-search columns exist.
   Verify: eligible completed enrichment rows can be initialized with `contact_search_status = pending`.

2. Run the Python contact worker offline before n8n wiring.
   Verify: OpenSERP role queries produce candidate lists without spending No2Bounce credits.

3. Add email permutation and No2Bounce validation.
   Verify: only person-specific emails are generated and only deliverable non-catch-all emails are accepted.

4. Wire n8n contact orchestration.
   Verify: rows are claimed as `processing`, then finish as `contact_found`, `contact_not_found`, `failed`, or `skipped`.

5. Add scale controls.
   Verify: batch size, provider errors, validation spend, and terminal row counts are reported per run.

## Rerun Process

1. Disable the live workflow.
2. Stop or wait for any in-flight executions to finish.
3. Clear old execution history for the workflow under test.
4. Recover stale `processing` rows before selecting new work.
5. Reset only the target rows for the rerun and set eligible rows to `status = pending`.
6. For URL discovery reruns, clear stale URL-pick fields such as `last_stage`, `last_error`, `url_picked`, `canonical_domain`, `duplicate_of_id`, and `search_evidence_json`.
7. For enrichment reruns, preserve `url_picked` and clear only downstream website fields such as `best_url`, `homepage_root_url`, `website_content`, `website_scrape`, `company_homepage_name`, `parent_company`, `source_urls`, `notes`, `confidence`, `last_stage`, and `last_error`.
8. For contact-search reruns, preserve URL/company enrichment fields and reset only contact fields such as `contact_search_status`, `contact_search_reason`, `contact_candidates_json`, `contact_search_evidence_json`, selected contact fields, email validation fields, and contact timestamps.
9. Do not use blank output fields as the processing selector. The workflow should pick up only `status = pending`, while contact search should use `contact_search_status = pending`.
10. Add a fresh rerun batch marker when possible.
11. Re-enable the workflow.
12. Run a small test set first.
13. Inspect raw search, selected URL, scrape result, contact candidates, No2Bounce result, and final writeback.
14. Confirm every claimed company-enrichment row reached `completed`, `skipped`, `failed`, or `needs_review`, and every claimed contact row reached `contact_found`, `contact_not_found`, `failed`, or `skipped`.
15. Scale only after the small set passes.

For enrichment reruns, keep the n8n Crawl4AI HTTP timeout higher than the per-page timeout budget. The current worker uses a 300s n8n request timeout because five-page public crawls can exceed 120s on heavier sites.

## API Versus MCP Rule

Use direct REST/API helpers for repeated operational work, bulk row reads, resets, execution polling, and provider diagnostics. Use MCP only for small inspection/control tasks where the tool response is naturally compact.

Token-saving defaults:

- NocoDB API is preferred for table scans, row status summaries, targeted resets, and writebacks because it can request only narrow fields and avoid large evidence columns.
- n8n API is preferred for execution polling, cleanup, and workflow status checks because it can return compact execution metadata without loading workflow JSON.
- Railway API is preferred for deployment/service diagnostics where a targeted GraphQL query can return only the needed service, deployment, or variable status.
- MCP remains useful for quick one-off checks, schema discovery, or when the API shape is unknown, but do not use it to dump `website_content`, `website_scrape`, `search_evidence_json`, `contact_search_evidence_json`, `contact_candidates_json`, or `email_candidates_json`.
- Keep API tokens in local environment variables only. Do not commit keys, paste them into docs, or bake them into workflow JSON.

Local helper:

```bash
export NOCO_BASE_URL="https://nocodb-production-f802.up.railway.app"
export NOCO_PROJECT_ID="pb7f1zou786xyqc"
export NOCO_TABLE_ID="mey3zgihq7o4at9"
export NOCO_API_TOKEN="<local-only-token>"
python3 scripts/rayn_api_tools.py noco-contact-summary --where "(contact_search_status,neq,contact_found)" --limit 100
```

Useful compact commands:

- `python3 scripts/rayn_api_tools.py noco-rows --ids 273,274 --fields Id,company_name,status,contact_search_status,contact_search_reason,validated_email`
- `python3 scripts/rayn_api_tools.py noco-contact-summary --limit 100 --include-rows`
- `python3 scripts/rayn_api_tools.py noco-reset-contact --ids 273,274 --reason targeted_contact_rerun --dry-run`
- `python3 scripts/rayn_api_tools.py n8n-executions --workflow-id BQEa6M2pKYmuEYMV --limit 20`
- `python3 scripts/rayn_api_tools.py railway-graphql --query 'query { projectToken { projectId environmentId } }' --rate-headers`

## Webhook Paths

- `rayn-url-picker-v1`: single-row URL discovery path; may call the configured Google SERP provider and OpenRouter.
- `rayn-url-picker-batch`: batch rebuild path; it now fans out to both pending discovery rows and pending enrichment rows.

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
- run reconciliation proves rows claimed equals rows that reached a terminal status plus legitimately active `processing` rows.

## Status Recovery

Before a rerun, inspect rows where `status = processing`. If the claim timestamp field exists and is older than the configured threshold, mark the row `failed`, set `last_stage = stale_processing`, explain the timeout in `last_error`, and leave it eligible for manual reset to `pending`.

Use `processing_started_at`, `processing_finished_at`, `attempt_count`, `status_reason`, `error_type`, and `error_message` for recovery evidence. Keep `last_stage`, `last_error`, and `notes` as operator-facing detail.
