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
- No2Bounce decision bucket validation passed: `Deliverable`, `Valid`, and `OK` map to `sendable`; high-score named-person `Deliverable/AcceptAll` maps to `risky_sendable`; low-score or undeliverable accept-all results remain `rejected`.

Contact search timeout and fallback hardening:

- OpenSERP timeout handling is now less aggressive: a single timeout is recorded per attempt and the provider cascade continues to the next provider without globally disabling the first provider.
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
- current recommendation remains DuckDuckGo first, Google second, Bing last until repeated polls show Bing recovering.

Contact search provider removal:

- active OpenSERP contact-search order is now `openserp_duckduckgo -> openserp_google`.
- Serper remains disabled by default and is still emergency-only behind `SERPER_FALLBACK_ENABLED=true`.

Full rerun after Bing removal:

- reset 50 rows from URL discovery onward and reran company enrichment from `status = pending`.
- company enrichment finished with 45 completed rows and 5 expected no-official-url skips: 281, 285, 292, 306, and 314.
- fixed public enrichment recovery after the run exposed Crawl4AI navigation failures: normal HTTP/BeautifulSoup fallback now recovers pages where Playwright navigation fails, and same-homepage subpage failures no longer force review when the homepage is usable.
- fixed slow homepage validation by raising the public-web read timeout to 45 seconds; row 313 (`https://aaro.sg/`) now completes instead of being skipped on a 20-second validation timeout.
- restored stable URL webhook IDs after a workflow update left `rayn-url-picker-batch` unregistered; the live batch webhook is active again.
- contact search was not safe to run at the old scale: two 20-row batches saturated the worker, and even a 5-row batch left 4 rows stuck in `processing` while No2Bounce polling waited.
- reduced the contact-search NocoDB batch selector from 20 to 5 and bounded No2Bounce polling with `NO2BOUNCE_POLL_TIMEOUT_SECONDS`, defaulting to 30 seconds.
- contact rerun result after recovery: row 276 found `jayne@amber-pharmacy.com` from cache with zero new No2Bounce spend; rows 273, 274, 275, and 277 are marked retryable failed due contact batch timeout; the remaining 40 completed company rows are left as `contact_search_status = pending`.

Contact search row-runner fix:

- added `/contact-enrich-batch` to the worker so contact-search selection, row claiming, preflight, fallback search, No2Bounce validation, and NocoDB writeback happen inside one row-level worker path.
- rewired the contact-search webhook to call the worker batch runner directly; the old multi-item n8n contact branch remains in the file for reference but is no longer connected from the webhook trigger.
- default contact webhook batch size is one row unless `CONTACT_SEARCH_BATCH_LIMIT` or request `limit` is supplied, which prevents one slow No2Bounce validation from leaving several rows stuck in `processing`.
- the row runner keeps DuckDuckGo then Google as the only active OpenSERP providers, with Serper still disabled by default.
- worker service now requires the NocoDB env vars `NOCO_BASE_URL`, `NOCO_PROJECT_ID`, `NOCO_TABLE_ID`, and `NOCO_API_TOKEN` because contact row selection and writeback moved from n8n into `/contact-enrich-batch`.
- live smoke test after deploy selected row 278 in dry-run mode, then processed rows 278, 279, 280, 282, and 283 with terminal results: 2 `contact_found` total so far including cached row 276, 1 new `contact_not_found`, and 3 new retryable failures caused by No2Bounce poll timeout or search-provider failure.

Dependency update pass:

- updated the worker pins to `crawl4ai==0.8.6`, `fastapi==0.136.1`, `requests==2.33.1`, `beautifulsoup4==4.14.3`, and `uvicorn[standard]==0.46.0`.
- kept `playwright==1.58.0` because it is current, and kept `lxml==5.4.0` because `crawl4ai==0.8.6` requires `lxml~=5.3` and rejects `lxml 6.x`.
- updated the n8n base image pin from `n8nio/n8n:2.12.3` to `n8nio/n8n:2.19.0`; Docker Hub metadata confirms the tag exists.
- dependency resolution was checked with the worker virtualenv's `pip --dry-run`; Docker image build was not checked locally because Docker is not installed on this machine.
- deployed worker service `n8n-rayn-workflows` with Railway deployment `8d5a6af1-f742-479b-a958-ac5d41dab38f`; live `/health` and `/contact-enrich-batch` dry-run passed after deploy.
- deployed primary n8n service with Railway deployment `14873fa5-ede6-44a2-a890-a7d6dd318ad7`; n8n API confirmed workflow `BQEa6M2pKYmuEYMV` is active, and the contact-search webhook accepted a trigger after the upgrade.

Contact search Serper fallback switch:

- first-20 contact rerun after OpenSERP showed `4` `contact_found`, `3` expected `missing_canonical_domain` skips, `8` `search_provider_failed`, and `5` No2Bounce `poll_timeout` failures.
- switched default fallback provider order to `serper_emergency`; OpenSERP remains available only when explicitly listed in `CONTACT_SEARCH_PROVIDER_ORDER`.
- reduced default paid-search budget to `CONTACT_SEARCH_MAX_QUERIES_PER_ROW=3`.
- reduced default remote validation exposure to `CONTACT_SEARCH_MAX_CANDIDATES_PER_ROW=3` and `CONTACT_SEARCH_MAX_NO2BOUNCE_EMAILS_PER_ROW=16`; `CONTACT_SEARCH_MAX_EMAILS_PER_CANDIDATE` remains `8`.
- No2Bounce issue observed: the bulk endpoint returns a tracking ID, but polling often has no results within `NO2BOUNCE_POLL_TIMEOUT_SECONDS=30`, so rows fail as `email_validation_provider_failed / poll_timeout` even though the POST succeeds.
- added No2Bounce tracking evidence into each candidate attempt so timeout rows preserve `trackingId`, sanitized POST response, sanitized last poll response, and result count for later diagnosis or retry design.
- deployed the Serper fallback patch to Railway worker service `n8n-rayn-workflows`; live `/contact-provider-health` reports provider order `serper_emergency`.
- post-deploy smoke on rows `274`, `275`, and `277` confirmed the worker is using Serper, but all three failed with `serper_api_key_missing`; Railway worker variables currently include NocoDB and No2Bounce keys but not `SERPER_API_KEY`.

No2Bounce poll-timeout fix:

- checked the public No2Bounce bulk API docs: POST returns a `trackingId`, GET polls progress, and final reports can be returned as a signed download URL under `signedUrl`.
- root cause found in the worker: the parser only recognized `downloadFile`, so completed jobs that returned `signedUrl` could be treated as no-results and eventually become `poll_timeout`.
- updated No2Bounce parsing to recognize signed/download/result/report URL fields, parse downloaded CSV or JSON, redact signed URLs in evidence, and store progress counters from the last poll.
- increased the default No2Bounce poll timeout from 30 to 75 seconds while keeping row-level retry behavior for true slow or stuck jobs.
- tightened person-name rejection so title-only noise such as `Group Head` is not sent to No2Bounce as a candidate name.
- live smoke still showed No2Bounce jobs pending after 75 seconds (`87%` complete for row 278), so the worker now defaults to a 120-second poll window and reduces per-candidate remote validation from 8 to 4 emails.
- added `Clinical Director` and `Co-founder` to role matching so Amber Family Clinic can use the official-site Dr Wong evidence instead of noisy public-profile title fragments.
- live tracking checks showed some No2Bounce jobs can remain `Pending` with rejected aggregate counts and no download file; the worker now converts those zero-sendable partial timeouts into rejected candidate emails instead of retryable provider failures.
- added more organization/title noise filters such as `graduate` and `institution` after Serper snippets produced non-person candidates like `Raffles Institution`.
- added a final low-priority `admin_hr` role bucket with admin manager, administration manager, office manager, HR manager, human resources manager, and people manager roles.
- full-table contact rerun exposed false-positive accepted names from company fragments and title concatenation; tightened candidate rejection for company-prefix fragments, organization words such as `home`, `commercial`, `council`, and internal honorific tokens such as `Dr`.
- targeted reruns exposed two more false-positive patterns: company suffix names such as `SINGWEALTH HOLDINGS PTE LTD`, and roles that point to a different organization such as `CEO and Founder of Meet Doctor`; both are now rejected before email validation.
- tightened non-official candidate evidence so the target company must appear after the candidate name in the candidate-specific evidence window, preventing unrelated doctors from being selected because the target company appeared earlier in the same snippet.
- wired admin/HR terms into the existing manager fallback Serper bundle so the final-priority `admin_hr` bucket can be found without raising default query count.

Anymail Finder contact validation switch:

- switched default contact email validation from generated permutations plus No2Bounce to Anymail Finder person lookup.
- worker now sends one `{domain, full_name}` lookup per validated candidate and accepts only `email_status = valid` with same-domain `valid_email`.
- candidate progression remains active: if candidate 1 has no valid email, the worker proceeds to candidate 2 and then candidate 3 by default.
- tightened probable-human filtering before paid lookup so organization fragments such as banks, clinics, centres, groups, Pte/Ltd entities, and company-name prefixes are rejected before Anymail Finder spend.
- `email_validation_provider` is now `anymail_finder`; evidence records candidate attempt order, Anymail response, cache hits, and `credits_charged`.

Anymail Finder live smoke:

- deployed worker patch `d96d857` to Railway deployment `83f37241-d7b9-4fc4-ba0d-aaf09840f942` and verified `/health`.
- live smoke on rows `307`, `315`, and `320`: row `315` found `sharon.tan@ahvc.com.sg` with `1` Anymail credit; row `307` had no validated person; row `320` had candidate `Charis Au` but Anymail returned `not_found` with `0` credits.
- targeted rerun of row `289` confirmed the new human-name filter removes the prior non-person candidate `RHB Bank`; the row now has no candidates and used `0` Anymail credits.

Official-site LLM preflight and No2Bounce removal:

- added an official-site LLM preflight fallback in `contact_enrichment.py`; default mode is `CONTACT_PREFLIGHT_LLM_MODE=empty`, so it runs only when deterministic official-site extraction finds no candidates.
- the preflight LLM is constrained to official `website_content`, requires an exact `evidence_quote` containing the candidate name, and rejects candidates whose quote is not present in the scraped text.
- removed the unused No2Bounce validation path from active worker code; contact email validation is now Anymail Finder only.
- deployed commit `895aa7f` to Railway service `n8n-rayn-workflows`; deployment `30bdc075-c437-4f54-ae0f-1e8ed936f8b7` reached `SUCCESS`.
- removed obsolete `NO2BOUNCE_API_TOKEN` from the live `n8n-rayn-workflows` Railway service variables.

Contact candidate verifier tightening:

- added deterministic candidate gates for non-human names such as `Asian Diabetic`, title phrases such as `Past President`, and organization fragments such as `Dental Movies UK`.
- non-official third-party candidates now require the person-role evidence to point to the target company, not merely mention the company elsewhere in the same snippet.
- conference/event/speaker-list sources are blocked for contact selection unless the evidence is official-domain quality.
- fallback exclusion evidence now also writes `preflight_candidate_names_skipped_in_fallback` and `preflight_skip_reason` so operators can distinguish stale skipped names from final candidates.
- future fresh reruns should stop/clear old executions first, then reset stale table output fields, so old No2Bounce/permutation artifacts are not confused with current Anymail Finder results.

Preflight evidence preservation:

- row `311` showed that bad fallback names were fixed, but real official-site preflight doctors could still appear only under excluded/skipped names after fallback overwrote the final candidate list.
- final fallback writeback now preserves official-site preflight candidates, email candidates, and validation evidence alongside fallback evidence so skipped names are auditable rather than unexplained.

Row 311 verifier smoke:

- after deploy `a8ccf238-c235-43ae-b25d-1b6b66cc3a70`, reran row `311` through `/contact-enrich-batch`.
- bad fallback candidates `Dental Movies UK`, `Past President`, and `Asian Diabetic` are no longer present.
- official-site preflight doctors `Arthur Yeah`, `Jimmy Gian`, and `Joshua Loh` are preserved in `contact_candidates_json` with `candidate_stage = official_site_preflight`.
- Anymail Finder returned `not_found` for all three doctors with `0` credits charged, so final status remains `contact_not_found / no_validated_person_found`.

LLM candidate verifier rollout:

- added a worker-side LLM verifier between raw candidate extraction and Anymail Finder lookup.
- fallback candidates now fail closed when the verifier is unavailable, writing `failed / candidate_verifier_failed` instead of spending Anymail credits on unverified names.
- raw false positives are stored under `raw_candidates` and `rejected_candidates`; `candidate_names` and `candidate_count` now mean verified accepted human candidates only.
- configured the Railway worker with `CONTACT_LLM_VERIFIER_ENABLED=true` and `CONTACT_LLM_VERIFIER_REQUIRED_FOR_FALLBACK=true`; local OpenRouter verification currently returns `401`, so a valid worker OpenRouter key is required before broad live fallback reruns.

OpenRouter verifier key rotation:

- updated the Railway worker `OPENROUTER_API_KEY` secret from the user-provided key without committing it.
- redeployed worker deployment `4594a4a3-a328-4e8d-8d3a-4f1d90f0a79b`; `/health` passed.
- LLM verifier smoke using the `Asian Diabetic` fixture now succeeds: `candidate_names=[]`, `raw_candidate_count=1`, `verified_candidate_count=0`, `rejected_candidate_names=["Asian Diabetic"]`, `candidate_verifier=llm`, and no verifier error.

Contact batch speed and skip-status fix:

- `/contact-enrich-batch` now supports conservative row-level concurrency via request `concurrency` or `CONTACT_BATCH_CONCURRENCY`; the default remains serial unless configured.
- contact row claims now clear stale email validation fields before processing so live rows do not show old validation state while processing.
- no-verified-candidate outcomes now write explicit `email_validation_status` values such as `skipped_no_verified_candidate` or `skipped_no_email_candidate` instead of leaving the field blank.
- Anymail Finder person lookup timeout default is reduced from `180` seconds to `45` seconds, still overrideable with `ANYMAILFINDER_TIMEOUT_SECONDS`.

Preflight email outcome preservation:

- if official-site preflight tries one or more verified people and Anymail Finder returns no deliverable email, fallback search may still run for alternate contacts.
- when fallback finds no verified alternate, final `email_validation_status` now preserves the preflight outcome as `no_deliverable_email` instead of overwriting it with `skipped_no_verified_candidate`.
- `skipped_no_verified_candidate` now means no verified person was ever attempted for email lookup.

Industry-general official-site people discovery:

- widened website scrape follow-link discovery beyond clinic pages to include people, staff, board, trustees, governance, committee, council, management, directors, and nonprofit/social-service leadership pages.
- increased default official-site follow links from `2` to `4` and expanded the structured `team_text` evidence cap so names from people/board pages are more likely to reach contact extraction before paid search.
- added official-site profile-line extraction for generic industries: adjacent name/title blocks such as `Jane Tan` followed by `Executive Director`, or `Muhammad Faisal Rahman` followed by `Programme Manager`, can now become verified official-domain candidates.
- kept healthcare extraction intact, but it is no longer the dominant assumption; NCSS, SSA, charities, nonprofits, and general SME/enterprise leadership roles are handled in the same path.

Official-site specialist page follow-up:

- added generic profile/provider/consultant/practitioner link hints plus specialist healthcare page hints such as dermatologist and cardiologist so official pages like `/our-dermatologist/` are more likely to be crawled before paid search.
- added clinical specialist titles such as Dermatologist, Cardiologist, Consultant Dermatologist, Consultant Cardiologist, and Senior Consultant as official-site contact roles.
- de-duplicated same-name official candidates so a specialist found with a specific title is not also emitted as a generic Senior Doctor fallback.

Specialist-role false-positive guard:

- fixed role matching to use token boundaries so short roles like CTO no longer match inside unrelated words such as doctors.
- limited broad clinical specialist roles to profile-line evidence with explicit doctor/professor honorifics, preventing package names, hospitals, addresses, and headings from becoming official-site people candidates.
- changed same-name official-site de-duplication to prefer higher-confidence profile-line evidence before role priority, so adjacent name/title blocks keep their nearest title.

Public scrape fallback and candidate quality tightening:

- added an internal timeout guard around `/public-enrich`; full scrapes now retry once with a small fallback crawl instead of letting n8n hit the 300s HTTP timeout.
- fallback public enrichment marks recovered rows as `partial` and records the fallback page limit in `error_notes` / enrichment notes for auditability.
- expanded public-web high-value paths for general industries: people, staff, senior management, executive team, board, directors, governance, organisation/organization, committee, council, trustees, specialists, consultants, and profiles.
- tightened deterministic person-name filtering so qualifications and role-only phrases such as `MBChB Glasgow`, `Pain Specialist`, `Clinical Director`, and `Clinic Operations Manager` cannot become accepted contact candidates.
- focused candidate-verifier tests and Python compile checks passed locally before deploy.

Email validation summary column:

- added `email_validation_summary` as a long-text NocoDB column for plain-English email validation results beside the structured `email_validation_status` / evidence fields.
- worker patches now populate the summary from Anymail candidate attempts, showing accepted emails and rejected/not-found person-domain lookups in readable lines.
- backfilled existing rows from stored `email_candidates_json` / `email_validation_evidence_json` so the table is immediately readable without opening JSON evidence.

Budgeted role-bucket search coverage:

- updated Serper fallback query planning so all seven target role buckets remain covered without issuing one search per bucket.
- rows with `website_content` use four bundled company-name queries covering: c-suite/operations/clinic leadership, clinic leadership/care clinical, compliance/privacy/security/IT, and operations/admin/HR.
- rows without `website_content` may still use up to six queries, adding site-domain queries only after the seven buckets have been covered once.
- added a regression test proving a four-query budget covers all `TARGET_ROLE_BUCKETS` in priority order.

Budgeted query order correction:

- first budgeted rerun reduced Serper events from 246 to 120, but found emails dropped from 19 to 15 because the default three-query budget no longer included the high-signal `site:{canonical_domain}` people-page query.
- corrected query order to keep a precise c-suite query first, then a broad official-domain people-page query, followed by clinic/ops/admin/care and compliance/IT company queries.
- intent is to keep Serper lower than the previous 246-event run while preserving the 19-email baseline.

Parent-company relationship classifier:

- added structured parent-company candidates with relationship pattern, source URL, evidence quote, context, and confidence hint.
- split strong parent/operator/group relationships from weak affiliations and rejected parent candidates.
- added strict relationship classes: only parent, owner, operator, managed_by, subsidiary_of, branch_of, brand_group, and clinic_network may populate `parent_company`.
- weak memberships, accreditations, licensing bodies, training institutions, doctor/hospital appointments, vendors, landlords/locations, and partners are preserved as affiliations or rejected candidates instead of being written as parent companies.
- added an optional OpenRouter-backed LLM verifier for classification only; post-verifier guards reject invented parent names, quotes not present in official crawl text, person names, target-company overlaps, bad relationship types, and weak biography/accreditation/location contexts.
- deterministic fallback still accepts high-confidence schema.org parentOrganization/branchOf and explicit owned/operated/managed/subsidiary/branch/group evidence when the verifier is disabled or unavailable.

Parent-company rerun smoke test:

- live `/public-enrich` health was OK, but browser-backed public enrichment remains slow for all-row parent-only testing: homepage-only calls took roughly 60-96s per row.
- local static official-homepage parent classifier smoke-tested all 47 eligible rows in 5.9s with deterministic verifier enabled and no NocoDB writeback.
- result after tightening guards: 0 accepted parent companies, 4 affiliation rows, 1 rejected-candidate row, 0 errors.
- fixed two false-positive parent paths found during the smoke test: CHAS/subsidy/accreditation scheme text and generic `part of medical examinations` phrases no longer populate `parent_company`.
- changed unknown/noisy parent candidates to rejected evidence instead of affiliation evidence; professional memberships, training institutions, and accreditations remain affiliation evidence only.

OpenSERP-only search routing:

- URL discovery now calls the configured `OPENSERP_BASE_URL` route directly instead of posting to the Serper Google API.
- Contact-search fallback defaults to `openserp_duckduckgo -> openserp_google`.
- Serper remains present as `serper_emergency`, but it is disabled unless `SERPER_FALLBACK_ENABLED=true` and it is explicitly listed in `CONTACT_SEARCH_PROVIDER_ORDER`.

URL discovery DuckDuckGo switch:

- full-table scratch rerun showed OpenSERP Google URL discovery timing out under parallel webhook pressure; `37` rows failed with `timeout of 60000ms exceeded` before candidate selection.
- URL discovery now uses `/duck/search` for the first-pass `company_name Singapore` lookup because live probes returned official homepage results reliably and faster than the overloaded Google route.
- Follow-up reruns should trigger URL discovery conservatively instead of firing the whole table in parallel, because the workflow claims rows before the search node finishes.

Public enrichment timeout cleanup:

- rerun after the DuckDuckGo switch showed URL discovery was healthy, but public enrichment timed out on `13` rows at the n8n HTTP node's `300000ms` limit.
- enrichment row selection is now limited to `1` row per workflow trigger, and the `/public-enrich` HTTP timeout is raised to `600000ms` for cleaner low-concurrency runs.
- fixed the enrichment item filter to accept rows already in `status = processing`, matching the upstream `Get Enrichment Rows` query.

Runtime challenge diagnostics:

- `2captcha-python==2.0.6` remains installed in the Crawl4AI worker requirements.
- added `/runtime-diagnostics` and contact provider health metadata to report whether the `twocaptcha` package is importable and whether solver env vars are configured.
- public enrichment now detects challenge-style pages and records `skipped_challenge_detected` with challenge hints instead of treating the page as normal business content.
- solver mode is diagnostic-only; no public-web CAPTCHA solving is called by the worker.

Active 2captcha integration:

- disabled OpenSERP's built-in broken 2captcha solver (`google.captcha: false`) because the Go binary
  has an open bug where it receives the solved token from 2captcha but fails to inject it back into the
  page (`TypeError: Cannot read properties of undefined (reading 'apply')` — karust/openserp#9).
- created `services/crawl4ai/captcha_solver.py` with Playwright-based captcha detection and solving.
  supports reCAPTCHA v2, hCaptcha, and generic challenge pages via `2captcha-python`.
- `captcha_solver.is_configured()` checks for `TWOCAPTCHA_API_KEY` env var.
- `CAPTCHA_SOLVER_ALLOWED_DOMAINS` restricts solving to trusted domains (empty = allow all).
- env vars: `TWOCAPTCHA_API_KEY`, `CAPTCHA_SOLVER_ALLOWED_DOMAINS`,
  `CAPTCHA_SOLVER_TIMEOUT_SECONDS` (default 120), `CAPTCHA_SOLVER_HEADLESS` (default true).

Contact search captcha fallback:

- `contact_enrichment.py` now detects captcha errors from OpenSERP responses via `detect_captcha_flags()`.
- on captcha detection, falls back to `direct_search_with_captcha_solver()` which uses Playwright +
  DuckDuckGo HTML search + 2captcha to solve any challenges.
- the direct search result is returned with `provider = "{original}_captcha_retry"` for traceability.
- captcha errors no longer trip the OpenSERP circuit breaker since they're handled at the worker level.

Scrape endpoint captcha handling:

- `app.py` `/scrape` now uses `extract_page_with_captcha_retry()` which detects challenge pages after
  the initial load and attempts to solve them via 2captcha before extracting content.
- applied to both primary URL and followed links.

Public enrichment captcha handling:

- `public_web_enrichment.py` `enrich_row()` now attempts Playwright-based captcha solving when a
  challenge page is detected on the homepage, instead of immediately returning `skipped_challenge_detected`.
- the crawl context in enrichment records now includes `captcha_solver` diagnostics.

Serper provider switch live rerun:

- committed and pushed `bbcab26` (`Switch workflow search providers to Serper`) to `codex/n8n-workflow-checkpoint`.
- deployed Crawl4AI worker to Railway service `n8n-rayn-workflows`; final successful deployment `bf1c1b40-6867-40c9-ad2a-f26dd4bdc0ed`.
- updated live n8n workflow `BQEa6M2pKYmuEYMV` from `wf-worker.json`; workflow remained active.
- set `CONTACT_SEARCH_PROVIDER_ORDER=serper` on the Crawl4AI worker and added `SERPER_API_KEY` to n8n `Primary`; initial URL rerun before the n8n env fix failed with Serper `403 Unauthorized`.
- URL rerun slice after env fix: rows `281`, `285`, `292`, and `314`. Results: `292` completed with `https://appletreemedicalgroup.com/`; `314` completed with `https://aamgdoctors.net/`; `281` and `285` stayed skipped with `no_official_url_found`.
- contact rerun slice: rows `275` and `278`. Results: both terminal `contact_not_found` with `candidates_found_but_no_sendable_email`; No2Bounce rejected `Wong Siu Kwan @ amberfamilyclinic.com`, `Tan Chin Beng Melvyn @ amkclinic.com.sg`, and `Tan Chin Beng @ amkclinic.com.sg`.
- cost/usage observed: `4` successful Serper URL-discovery responses, `3` Serper contact-search provider queries, and `4` earlier unauthorized Serper URL attempts before the n8n env fix. At Serper starter pricing of `$1.00/1k` successful queries, the `7` successful Serper queries are approximately `$0.007`; unauthorized failures should not deduct credits per Serper's successful-response credit rule.

Contact search all-row rerun after LLM preflight and No2Bounce removal:

- reset all `48` eligible completed, non-duplicate rows with canonical domains and best URLs to `pending` using reason `full_contact_updated_search_rerun`.
- drained live `/contact-enrich-batch` on Railway worker `n8n-rayn-workflows` with provider order `serper`; final state: `17` `contact_found`, `31` `contact_not_found`, `0` failed, `0` pending, `0` processing.
- validated-email rows: `273`, `274`, `276`, `280`, `286`, `288`, `291`, `295`, `296`, `299`, `302`, `312`, `313`, `316`, `317`, `318`, `319`.
- final reasons: `17` `sendable_person_specific_email_found`, `24` `candidates_found_but_no_sendable_email`, `7` `no_validated_person_found`.
- usage proxies from contact evidence: `120` Serper provider/query attempts, `1010` total search results stored, `544` raw candidates, `73` verified candidates, `85` candidate objects written, `17` official-site preflight candidates across `10` rows, `0` search errors, `0` provider timeouts.
- rows `304` and `305` initially hit Anymail validation timeouts during batch processing; targeted retries completed both as `contact_not_found` with `no_deliverable_email`.

Contact search improvement patch and targeted rerun:

- committed and pushed `a3b5eaf` (`Improve contact search email fallback`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `eb236892-f973-4125-825f-331deeae440c` reached `SUCCESS` and `/health` returned OK.
- implemented candidate-specific published-email fallback after Anymail Finder misses, raised default `CONTACT_SEARCH_MAX_CANDIDATES_PER_ROW` from `3` to `5`, changed official-site LLM preflight default mode to `sparse`, and preserved the best selected person even when email lookup fails.
- reset and reran the `24` rows that previously ended `candidates_found_but_no_sendable_email`.
- targeted rerun result: `1` new `contact_found` (`305`, `nabilah@ashforddentalcentre.com.sg`), `23` `contact_not_found`, `0` failed/pending/processing.
- final full eligible-table state after targeted rerun: `18` `contact_found`, `30` `contact_not_found`.
- targeted usage proxies: `72` normal Serper provider/query attempts, `64` published-email Serper attempts, `631` total search results stored, `343` raw candidates, `33` verified candidates, `26` Anymail requests, `1` Anymail credit charged.

Decision-maker fallback patch:

- committed and pushed `58633f3` (`Add Anymail decision maker fallback`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `3fc5adae-2a23-4106-ba61-b165273efde1` reached `SUCCESS` and `/health` returned OK.
- added Anymail Finder `/v5.1/find-email/decision-maker` as the only fallback after no verified candidates or exhausted person lookups; no Serper/OpenSERP email fallback is used.
- default decision-maker category order is `ceo`, `it`, `operations`, `hr`, `marketing`; override is available with `ANYMAILFINDER_DECISION_MAKER_CATEGORIES`.
- default decision-maker timeout is `180` seconds via `ANYMAILFINDER_DECISION_MAKER_TIMEOUT_SECONDS`; the fallback can be disabled with `ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED=false`.
