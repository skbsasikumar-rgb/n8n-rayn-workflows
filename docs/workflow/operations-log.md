# Operations Log

Use this file to record rebuild progress and decisions.

## 2026-04-28

API token-saving setup:

- added a compact API helper for NocoDB, n8n, and Railway operational checks.
- NocoDB table inspection and contact-search summaries should use narrow-field API calls instead of MCP dumps when checking many rows.
- n8n execution polling should use the API helper for compact execution metadata.
- Railway diagnostics should use targeted GraphQL queries rather than broad dashboard/tool payloads.
- local secrets must stay in environment variables; no API keys are stored in repo files.

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
- At that checkpoint, OpenSERP/browser scraping hit Google CAPTCHA and circuit-breaker failures from Railway egress, so the worker temporarily used the existing Serper Google API credential for stable Google SERP candidates.
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
- whether raw search logs should be stored in NocoDB or execution-only.
- whether parent-company extraction should be deterministic first, LLM-assisted second, or LLM-only after scrape.

Contact search plan:

- next enrichment stage will search senior and managerial contacts after company URL enrichment.
- OpenSERP queries will run role bucket by role bucket, starting with the most valuable outreach roles and moving down only if no deliverable email is found.
- email generation will use only person-specific permutations against `canonical_domain`; generic inboxes are explicitly excluded.
- No2Bounce is the validation authority, and the final decision buckets are `sendable`, `risky_sendable`, and `rejected`.
- exhausted contact searches will write `contact_search_status = contact_not_found`; contact search must not output `needs_review`.
- detailed plan added in `docs/workflow/contact-search-design.md`.

Contact search strategy update:

- contact search should be built as a separate post-enrichment stage with its own `contact_search_status`.
- recommended architecture is n8n orchestration plus a Python contact-search worker for role queues, candidate ranking, email permutations, and No2Bounce polling.
- search-provider failures must be recorded as provider failures rather than `contact_not_found`.
- first test slice should generate candidate lists before spending No2Bounce credits.
- detailed strategy added in `docs/workflow/contact-search-strategy.md`.

Contact search provider decision:

- MailScout will not be used.
- email permutations will be implemented directly in our contact-search worker.
- No2Bounce remains the only email validation authority for this stage.

Contact search implementation checkpoint:

- added a separate contact-search webhook branch at `rayn-contact-search-batch`; it runs only after company enrichment is `completed`.
- added contact-search NocoDB columns and a reproducible schema helper in `scripts/ensure_rayn_contact_columns.py`.
- added `/contact-enrich` to the Crawl4AI worker for candidate extraction, person-specific email permutations, and No2Bounce polling.
- This initial checkpoint used the existing Serper Google credential in n8n for role-driven public search results; later entries document the OpenSERP-primary switch.
- extraction is intentionally conservative: only official-domain pages, LinkedIn snippets, and professional public pages can create email permutations.
- 5-row live dry test: rows 273, 274, and 276 found plausible person candidates; rows 275 and 277 ended `contact_not_found`.
- No2Bounce is not configured in Railway yet, so candidate rows currently stop as `failed` with `email_validation_not_configured`; no `validated_email` is selected until `NO2BOUNCE_API_TOKEN` is added.

Contact search 10-row validation:

- `NO2BOUNCE_API_TOKEN` is configured in Railway as an environment variable, not in repo files.
- deployed Crawl4AI worker now exposes `/contact-enrich` and `/public-enrich`; earlier deploys were serving only `/health` and `/scrape`.
- No2Bounce completion can return per-email results through a signed CSV `downloadFile`; the worker now downloads and parses that CSV and redacts the signed URL before storing evidence.
- rows 278, 279, 280, 282, 283, 284, 286, 287, 288, and 289 all ended `contact_not_found` with `no_validated_person_found`.
- this 10-row run did not spend No2Bounce validation on table rows because no contact candidate survived extraction.
- next contact-quality fix should store search attempts for `contact_not_found` rows or pull raw Serper results during debugging, otherwise misses are hard to explain after the run.

Contact search evidence update:

- added `contact_search_evidence_json` as a long-text audit field for role queries, top Serper results, provider errors, and candidate counts.
- worker writeback now records compact search evidence even when the final status is `contact_not_found`.
- the April 27 control rerun showed Serper returning `400 Not enough credits` for every role query; those rows should be treated as `failed` with `search_provider_failed`, not as true `contact_not_found`.

Contact search deliverability normalization:

- Serper credit top-up restored search results: the 15-row control slice returned zero search-provider errors and normal result counts.
- No2Bounce CSV rows use `finalScoreValue` such as `Deliverable`, `UnDeliverable`, and `Deliverable/AcceptAll`; the worker now normalizes that field directly.
- catch-all rejection now checks explicit catch-all/accept-all status instead of rejecting every result containing the `catchall` field name.
- expected effect: person-specific `Deliverable` results with `catchall=false` can be accepted, while accept-all/catch-all/risky/unknown/undeliverable results remain rejected.

Contact search post-top-up run:

- continued the contact-search run after Serper credit top-up across 48 eligible rows; rows 281 and 285 remained untouched because no URL is available.
- actual Serper usage was 576 searches for 48 processed rows, which is exactly 12 role queries per row.
- actual No2Bounce usage was 171 email validations across 19 rows with validated contact candidates; rows without safe candidates did not spend No2Bounce validations.
- final contact status summary: 8 `contact_found`, 40 `contact_not_found`, 2 blank/not eligible.
- no Serper provider errors were observed after top-up.

Contact search query reduction:

- the contact-search query builder now uses three bundled search families instead of exploding into one query per role label.
- each row now emits at most six queries by default: leadership, clinic or operations, and compliance or IT, each in one company-name form and one site-domain form.
- the candidate extractor is unchanged, so evidence still maps back to the concrete matched role found in the result title or snippet.

Contact search site-first pass:

- official-site candidate extraction now runs before search-result-only matching and can recover named contacts directly from `website_content`.
- rows with usable `website_content` now cap at four Serper queries instead of six, because official-domain evidence is treated as the first pass.
- April 27 smoke rerun on rows 273, 274, 276, 280, and 286 finished with 4 queries per row and recovered row 276 (`Jayne Wee`) from homepage content while keeping row 274 as `contact_not_found`.
- smoke result summary: 4 `contact_found` (`273`, `276`, `280`, `286`) and 1 `contact_not_found` (`274`).

Contact search official-site preflight:

- added a zero-Serper preflight branch after contact row claim: n8n calls `/contact-enrich` with `site_fast_path_only=true`, `search_attempts=[]`, and `validate_email=true`.
- if preflight returns `contact_found`, the workflow writes the result immediately and skips Serper entirely.
- at this checkpoint, if preflight could not produce a deliverable person-specific email, the workflow fell back to the then-current bundled Serper query path. Later entries supersede this with OpenSERP-primary routing.
- April 27 validation: row 280 returned `Etienne Ding` / `etienne@amplab.sg` with `query_attempts_count=0`.
- April 27 five-row smoke: rows 276, 280, and 286 completed with zero Serper queries; row 273 used fallback and completed; row 274 used fallback and ended `contact_not_found`.

Contact name-pattern update:

- expanded official-site extraction for Singapore naming patterns: 3-4 token names, doctor-in-charge labels, senior-doctor fallback, and credential trimming.
- email permutations now prioritize given-name/family-name order for multi-token names while still testing Western first/last patterns.
- n8n preflight now treats a high-confidence official-site contact as decisive even when No2Bounce rejects all generated emails, reducing Serper fallback spend.
- public-web crawling now probes common team, doctor, provider, leadership, management, board, about, and contact paths in addition to homepage links and sitemap candidates.
- April 27 row 278 validation: `Tan Chin Beng Melvyn` was extracted from `website_content`; No2Bounce rejected generated emails; n8n wrote `contact_not_found` with `query_attempts_count=0`.

Contact email decision buckets:

- replaced the boolean No2Bounce accept/reject gate with `sendable`, `risky_sendable`, and `rejected`.
- `Deliverable`, `Valid`, and `OK` are `sendable`.
- `Deliverable/AcceptAll` with `finalScore >= 90` and a named person is `risky_sendable`, even when `catchall=true`.
- low-score accept-all, undeliverable, invalid, bad, bounce, spam, disposable, unknown, blocked, and incomplete results remain rejected.

Contact search OpenSERP-primary routing:

- contact-search fallback is now executed inside the Python worker with provider order `openserp_bing -> openserp_duckduckgo -> openserp_google`.
- Serper is now disabled by default for contact search and only remains as an explicit emergency fallback behind `SERPER_FALLBACK_ENABLED=true`.
- official-site preflight now falls through to alternate-contact OpenSERP search when a named person is found but every generated email is rejected.
- preflight now passes `excluded_candidate_names`, `excluded_email_candidates`, and `fallback_reason` into fallback so the same person and rejected permutations are not retried.
- provider failures now end rows as `failed/search_provider_failed` instead of false `contact_not_found`, and contact-search rows remain limited to `contact_found`, `contact_not_found`, `failed`, or `skipped`.
- expanded fallback title recognition now includes long-form executive/security/technology titles such as `Chief Executive Officer`, `Chief Information Security Officer`, and `Chief Technology Officer`.

Contact search OpenSERP acceptance checks:

- synthetic preflight/fallback validation passed: preflight found `Jane Foo`, rejected all generated emails, then fallback excluded `jane foo` and accepted alternate contact `John Bar` with `john.bar@exampleclinic.sg`.
- zero-Serper default validation passed with `SERPER_FALLBACK_ENABLED=false`: provider cascade attempted only `openserp_bing`, `openserp_duckduckgo`, and `openserp_google`, made zero Serper calls, and returned `failed/search_provider_failed` when every provider attempt failed.
- live OpenSERP probe on April 27 for `Amaris B Clinic Singapore`: Bing returned `circuit breaker is open - engine temporarily disabled`, while DuckDuckGo and Google both returned normalized official-site results.
- Google-failure isolation validation passed: a simulated Google CAPTCHA disabled only `openserp_google`, then the same query continued to Bing and still produced usable results.
- No2Bounce decision bucket validation passed: `Deliverable`, `Valid`, and `OK` map to `sendable`; high-score named-person `Deliverable/AcceptAll` maps to `risky_sendable`; low-score or undeliverable accept-all results remain `rejected`.

Contact search timeout and fallback hardening:

- OpenSERP timeout handling is now less aggressive: a single timeout is recorded per attempt and the provider cascade continues to the next provider without globally disabling the first provider.
- timeout-based provider disable now happens only after `3` recent timeouts inside a `180` second window, with a short `90` second cooldown; CAPTCHA and circuit-open still disable immediately with longer cooldowns.
- provider health now resets on a new `contact_search_run_id`, so a poisoned batch no longer suppresses later rows forever.
- fallback candidate progression now continues past a rejected first candidate up to the configured caps of `5` candidates, `8` emails per candidate, and `24` No2Bounce validations per row.
- contact-search misses now distinguish `candidates_found_but_no_sendable_email` from `no_deliverable_person_specific_email_found`.
- multi-token source-order names now generate source-order family-name permutations before Westernized variants; `Tan Chin Beng Melvyn` now yields `tan.chinbengmelvyn`, `tan.melvyn`, `tanchinbengmelvyn`, `tanmelvyn`, and then `melvyn.tan`.
- the contact n8n branch now emits a batch reconciliation summary with `rows_selected`, `rows_terminal_first_pass`, `rows_stuck`, `rows_recovered`, `rows_terminal_final`, and `rows_non_terminal_final`.

Local acceptance checks for this patch:

- timeout isolation passed: Bing timeout did not disable Bing on the first miss, and the cascade continued to DuckDuckGo and Google.
- repeated-timeout disable passed: Bing became temporarily disabled only after the third timeout, with disabled reason `timeout_threshold`.
- alternate-candidate progression passed: a rejected first candidate fell through to candidate 2 and selected the second candidate's deliverable email while staying within the row budget.
- reject-all progression passed: validated candidates with only rejected emails ended as `contact_not_found / candidates_found_but_no_sendable_email`.
- row-278-style name handling passed: source-order permutations are emitted first, and Westernized `melvyn.tan` remains available later in the list.
- zero-Serper default still passed: provider order remained `openserp_bing -> openserp_duckduckgo -> openserp_google` with no Serper default path.

Provider degradation follow-up:

- live failed rows showed OpenSERP returning `circuit breaker is open - engine temporarily disabled`; the worker had not been classifying that phrase as `circuit_open`, so it kept hammering the same engine instead of backing off.
- provider signal detection now recognizes the circuit-breaker phrase directly, applies only provider-local cooldowns, and records `cooldown_seconds` in every attempt.
- timeout-only state is now row-scoped through the contact-search run token, so three timeouts on one row no longer poison later rows in the same batch.
- manual provider diagnostics are now exposed through `/contact-provider-health`, and manual reset is available through `/contact-provider-health/reset`.
- no CAPTCHA-solving, stealth automation, or proxy-rotation bypass tooling was added.

Live OpenSERP provider poll:

- tested five contact-search-style queries across `/bing/search`, `/duck/search`, and `/google/search`.
- DuckDuckGo had `5/5` usable responses, average `10` results, and average latency around `3.8s`.
- Google had `5/5` usable responses, average `9.4` results, and average latency around `8.5s`.
- Bing had `0/5` usable responses: one timeout followed by four `circuit breaker is open - engine temporarily disabled` responses.
- contact-search default provider order is now `openserp_duckduckgo -> openserp_google -> openserp_bing`, with Serper still disabled by default.

Post-deploy OpenSERP provider poll:

- redeployed `searxng-railway` from the GitHub repo as an OpenSERP `v0.7.2` service instead of relying on an opaque CLI-uploaded source.
- reran the same five-query poll after deploy.
- DuckDuckGo stayed strongest: `5/5` usable responses, average `10` results, average latency around `4.4s`.
- Google stayed usable but slower: `5/5` usable responses, average `9.8` results, average latency around `9.5s`, with one slow response around `23.6s`.
- Bing remained unhealthy: `0/5` usable responses, `3` CAPTCHA-class failures and `2` circuit-open responses.
- current recommendation remains DuckDuckGo first, Google second, Bing last until repeated polls show Bing recovering.

Contact search provider removal:

- removed Bing from the active contact-search provider order after repeated live polls showed `0/5` usable Bing responses with CAPTCHA-class and circuit-open failures.
- active OpenSERP contact-search order is now `openserp_duckduckgo -> openserp_google`.
- Serper remains disabled by default and is still emergency-only behind `SERPER_FALLBACK_ENABLED=true`.
