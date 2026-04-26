# Operations Log

Use this file to record rebuild progress and decisions.

## 2026-04-25

State after reset:

- local workflow JSON exports deleted.
- live worker and orchestrator workflows deleted.
- enrichment table cleared.
- markdown docs recreated from scratch.

First rebuild slice:

- created live n8n workflow `RAYN URL Picker Worker v1`.
- workflow reads rows where `company_name` is present and `url_picked` is blank.
- workflow queries OpenSERP Google with `company_name Singapore`.
- workflow sends the first 10 results to OpenRouter using `deepseek/deepseek-v4-flash`.
- workflow writes `url_picked`, `search_evidence_json`, `status`, `last_stage`, and `last_error`.
- webhook returns on receipt so 20-row test runs do not block on the full execution.
- search backend URL is now configurable via `OPENSERP_BASE_URL`.

First 20-row rerun:

- corrected query from quoted company name to unquoted `company_name Singapore`.
- picked 4 URLs and rejected 16 rows from the first 20.
- observed noisy results from the old search backend; next tuning should focus on search quality before picker complexity.

OpenSERP deployment fix:

- Railway deploy was slow because the service was being rebuilt from a pinned OpenSERP source checkout instead of pulling the old prebuilt image.
- raw OpenSERP mode returned `null` results, so the service now runs browser mode with Railway-safe Chromium sandbox flags.
- OpenSERP responses are wrapped as `{ "results": [...] }` so n8n keeps one search response per company.
- first 20-row OpenSERP rerun picked 6 URLs and left 14 as no-url-picked for review/tuning.

Canonical-domain dedupe:

- worker now derives `canonical_domain` immediately after `url_picked`.
- worker writes `canonical_domain` and `duplicate_of_id` back to NocoDB with the URL-pick result.
- worker checks existing rows for the same canonical domain before later enrichment stages are added.
- duplicate rows are marked `url duplicate`, receive `duplicate_of_id`, and must not continue into scraping or parent-company inference.
- row 274 smoke test confirmed live canonical-domain write: `https://www.amazinghearing.com/` -> `amazinghearing.com`.
- rows that were URL-picked before this patch were backfilled at the column level; their old `search_evidence_json` may still show earlier evidence until rerun.

OpenSERP candidate outage:

- first 25-row rerun exposed that missing URLs were caused by empty candidate sets before LLM picking.
- OpenSERP health showed Google as `circuit_open`; logs showed Google CAPTCHA responses from the Railway egress path.
- worker now runs smaller 4-row batches, skips rows already marked `no url picked`, and records OpenSERP backend failures as retryable `search error` instead of false `no url picked`.
- OpenSERP config now disables endpoint fallback, reduces retry pressure, extends cache TTL, and slows Google direct requests.

## 2026-04-26

Enrichment rerun fix:

- full-table rerun exposed that the batch webhook was still entering the OpenSERP search branch.
- rows with existing `url_picked` were being searched again instead of going straight to website enrichment.
- live workflow now has a separate enrichment branch: `Webhook Batch Trigger` -> `Get Enrichment Rows` -> `Rows To Enrichment Items` -> `Prepare Public Enrichment`.
- URL discovery is restored to the small `url_picked` blank-row slice and OpenSERP is no longer called during enrichment-only reruns.
- Primary now has explicit `OPENSERP_BASE_URL` so the worker does not depend on the hardcoded fallback.
- deterministic cleanup now rejects common website-vendor/service-title text from `company_homepage_name` and rejects doctor-background or professional-body phrases such as taskforces, residency programmes, federations, teams, hospitals, nutrition/dietetics memberships, and bare acronyms from `parent_company`.

Status control-plane update:

- `status` is now treated as the queue-control source of truth.
- batch selectors read only rows with `status = pending`.
- selected rows are claimed with `status = processing` before URL discovery or website enrichment.
- terminal writeback maps outcomes to `completed`, `skipped`, `failed`, or `needs_review`.
- tracking columns now store `run_id`, processing timestamps, attempt counts, retry eligibility, status reasons, and error details.
- OpenSERP/browser scraping hit Google CAPTCHA and circuit-breaker failures from Railway egress, so the worker now uses the existing Serper Google API credential for stable Google SERP candidates.
- URL-pick preparation now preserves claim metadata through the LLM picker so terminal rows keep audit controls.
- terminal URL-pick skips and canonical-domain duplicates now stamp `processing_finished_at`, not just enrichment outcomes.
- homepage validation now accepts final HTTP `202`, and same-domain subpage `404`s are treated as non-fatal crawl warnings instead of `needs_review`.

Rebuild direction:

- worker first.
- discovery second.
- orchestrator last.

Principles adopted:

- think before coding.
- simplicity first.
- surgical changes.
- goal-driven execution.

## Open Decisions

- exact worker test set.
- search provider order.
- whether raw search logs should be stored in NocoDB or execution-only.
- whether parent-company extraction should be deterministic first, LLM-assisted second, or LLM-only after scrape.

Contact search plan:

- next enrichment stage will search senior and managerial contacts after company URL enrichment.
- OpenSERP queries will run role bucket by role bucket, starting with the most valuable outreach roles and moving down only if no deliverable email is found.
- email generation will use only person-specific permutations against `canonical_domain`; generic inboxes are explicitly excluded.
- No2Bounce is the validation authority, and only non-catch-all deliverable emails are accepted.
- exhausted contact searches will write `contact_search_status = contact_not_found`; contact search must not output `needs_review`.
- detailed plan added in `docs/workflow/contact-search-design.md`.
