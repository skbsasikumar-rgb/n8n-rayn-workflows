# Operations Log

Use this file to record rebuild progress and decisions.

## 2026-05-08

Public enrichment staging and queue hardening:

- added staged official-site enrichment in [services/crawl4ai/public_web_enrichment.py](/Users/sasikumar/Documents/n8n/services/crawl4ai/public_web_enrichment.py): fast mode is capped to high-value pages, deep-retry mode expands the crawl budget only for weak/recoverable enrichment, and link scoring now prefers healthcare team/service/location/contact pages or non-HIA privacy/security/platform/client pages.
- added page-level artifacts and hidden/debug evidence in `structured_data_detected.enrichment_depth`: page summaries, page types, high-value pages found, homepage content quality, pages crawled, weak-enrichment reason, and derived team/practitioner/location/privacy/security hints.
- updated `/public-enrich` defaults in [services/crawl4ai/app.py](/Users/sasikumar/Documents/n8n/services/crawl4ai/app.py): fast stage defaults to `page_limit=6`, `request_delay_seconds=0.5`, `per_row_page_concurrency=2`, and a bounded row timeout; deep retry can use a larger page limit without forcing every request to crawl deeply.
- updated [wf-worker.json](/Users/sasikumar/Documents/n8n/wf-worker.json) so the public-enrich request sends staged crawl controls, disables n8n HTTP retries, uses a 240s HTTP timeout, and drops transport-timeout outputs instead of patching stale `enrichment_error` rows.
- updated [scripts/export_outreach_audit_markdown.py](/Users/sasikumar/Documents/n8n/scripts/export_outreach_audit_markdown.py) to show enrichment depth, pages crawled, high-value page count, derived team/practitioner/location counts, privacy/security hints, services, locations, and final automation decision.
- local no-write smoke generated: fast-stage probe for `AI Clinic`, `APAX Medical`, `Ashford Healthcare`, and `RAYN Secure`; deep-retry probe for `AI Clinic`, `APAX Medical`, and `RAYN Secure`. No NocoDB writeback was used.
- smoke result: fast mode kept weak/challenge rows bounded, Ashford stayed `skipped_challenge_detected`, and deep retry promoted RAYN Secure to `strong` with `10` crawled pages. The smoke exposed and fixed two classifier edge cases: a single challenge subpage no longer makes an otherwise usable site `challenge_blocked`, and an empty page without challenge hints is treated as `thin_content`.
- Ashford follow-up: direct Playwright capture showed reCAPTCHA markers and sitekey `6Ld5h8IfAAAAAI_Y7mRBtH_VShwSfmOe8E8edKNy`, but the page content was already available. Tightened Cloudflare challenge detection so the word `cloudflare` in normal page/script content no longer blocks a usable page. After the fix, row `306` no-write probe changed from `skipped_challenge_detected` to `crawled`; deep retry still had only the homepage and classified as `weak_skipped / thin_content`.
- tests run: `python3 -m py_compile services/crawl4ai/public_web_enrichment.py services/crawl4ai/app.py scripts/export_outreach_audit_markdown.py`; `jq -e . wf-worker.json`; `python3 -m pytest tests/test_public_web_enrichment.py -q` (`9 passed`); `python3 -m pytest tests/test_outreach_planner.py -q` (`83 passed`); `python3 -m pytest tests/test_outreach_columns.py -q` (`17 passed`); `python3 -m pytest tests/test_workflow_audit_fallback.py tests/test_outreach_audit_export.py -q` (`6 passed`).
- preview generated: local no-write public-enrichment smoke artifacts only; no live preview was generated.
- deployment performed: no.
- live rows patched: no.
- no emails were sent, and Instantly was not used.

Full-table scratch rerun:

- deployed commit `06dd43d` to Railway worker service `n8n-rayn-workflows`; deployment `0128551f-91e7-4803-bfb5-fe2b6ec6c419` reached `SUCCESS`, and `/health` returned OK.
- reset all `50` lead rows from URL discovery onward and reran URL discovery. Result: `47` rows got `url_picked` initially; final enrichment state after recovery was `46 completed`, `4 skipped`.
- the production-style `/public-enrich` worker path clogged on full-table concurrent requests and wrote stale `timeout of 600000ms exceeded` failures. Restarted the worker and recovered enrichment locally with the same deterministic public-enrichment code using low-limit one-page crawls.
- final skipped rows: `281` Anchor Health Family Clinic, `285` Ann Arbor Dental Surgery, and `314` ASIAN AMERICAN MEDICAL GROUP had `no_official_url_found`; `306` Ashford Healthcare had `skipped_challenge_detected`.
- contact search ran for the `46` completed rows in chunks of `10`; final contact state was `38 contact_found`, `8 contact_not_found`, and `4 pending` on rows skipped before contact.
- contact validation provider counts: `anymail_finder_company=28`, `anymail_finder+decision_maker=12`, `anymail_finder=6`, `blank=4`.
- draft-only planner ran for all `46` completed rows with terminal contact status. Final automation state: `auto_send_eligible=30`, `suppressed=8`, `auto_skipped=5`, `retry_enrichment_once=3`, `blank=4`.
- final gate state: `final_send_gate_passed=true` for `30` eligible rows only; `email_send_ready=false` for all `50` rows.
- anomaly checks passed: `eligible_with_flags=[]`, `blocked_with_bodies=[]`, `suppressed_with_bodies=[]`, `send_ready_true=[]`, `gate_true_noneligible=[]`, `eligible_gate_not_true=[]`.
- cleaned stale `status_reason=enrichment_error` from `25` completed rows after the worker-timeout race; those rows now show `status_reason=enrichment_completed`.
- deployment performed: yes, Railway worker service `n8n-rayn-workflows`.
- live rows patched: yes, full-table enrichment/contact/draft fields were reset and repopulated for this scratch test.
- no emails were sent, and Instantly was not used.

## 2026-05-07

Friendly deterministic copy style:

- vetted the 10-row live draft copy and tightened deterministic wording locally: Email 1 now uses lowercase sentence continuation after greeting commas, HIA Email 2 avoids repeated `size it`, CISOaaS small-clinic pricing lines read more naturally, conditional funding language says `reduce the outlay`, and group/unknown-size wording avoids over-specific `Group clinics` phrasing.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py`; `PYTHONPATH=services/crawl4ai:. python3 -m pytest tests/test_outreach_planner.py -q` (`83 passed`).
- deployment performed: no.
- live rows patched: no.
- no emails were sent, and Instantly was not used.
- tightened the latest sentence rotations after live review: Email 1 now always keeps an explicit observation opener after the greeting, and active HIA pricing Email 2 variants always mention `CISOaaS`.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py`; `PYTHONPATH=services/crawl4ai:. python3 -m pytest tests/test_outreach_planner.py -q` (`83 passed`).
- deployment performed: no.
- live rows patched: no.
- no emails were sent, and Instantly was not used.
- added more deterministic sentence-slot rotation for cold-email copy: Email 1 observation opener, Email 1 company-type bridge, expanded HIA pressure lines, expanded HIA Email 2 RAYN value lines, expanded Email 3 diagnostic openers, and additional short Email 4 close-loop lines.
- retired `appears to be` as a fixed Email 1 body phrase; generated copy now rotates human alternatives such as `looks like`, `seems to be`, `is listed as`, and `looks to be` while preserving the underlying copy brief and quality gates.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py`; `PYTHONPATH=services/crawl4ai:. python3 -m pytest tests/test_outreach_planner.py -q` (`83 passed`).
- preview generated: local read-only planner preview only; no live rows were patched.
- deployed commit `8ba66a0` to Railway service `n8n-rayn-workflows`, then ran the live cold-email planner workflow in draft-only mode for `10` rows (`force=true`, `use_llm=false`). Rows patched: `273,274,275,276,277,278,279,280,282,283` at `2026-05-08 05:43:00-05:43:01+00:00`.
- live draft-only audit: `automation_decision={auto_send_eligible:8,suppressed:1,auto_skipped:1}`, `final_send_gate_passed={true:8,false:2}`, `email_send_ready={false:10}`. Auto-send eligible rows had email bodies and blank quality/severe flags. Suppressed/skipped rows had no email bodies. Row `280` was `auto_skipped` for `low_trigger_confidence` / `email_quality_gate_failed`; row `278` was suppressed for `suppressed_missing_validated_email`.
- deployment performed: yes, Railway service `n8n-rayn-workflows`.
- live rows patched: yes, draft fields only for the `10`-row live draft-only test.
- no emails were sent, and Instantly was not used.
- replaced whole-email A/B/C body variants with deterministic sentence-level rotation. The planner now keeps one fixed structure per email step and rotates approved sentence slots inside that structure.
- fixed preview QA anomalies from the 10-row read-only test: family clinic evidence now outranks weak long-term-care wording, endocrinology records no longer get overwritten by incidental oncology/radiation text, orthopaedic/sports-medicine rows use orthopaedic record phrases, and non-person labels such as `Committee Memberships` fall back to generic greeting/contact mode.
- deployed the current branch to Railway service `n8n-rayn-workflows` and reran the live cold-email planner workflow in draft-only mode for `30` rows (`force=true`, `use_llm=false`). The first attempt exposed stale deployed planner code on rows `293` and `301`; after deploying the correct service, the second run patched rows `273,274,275,276,277,278,279,280,282,283,284,286,287,288,289,290,291,292,293,294,295,296,297,298,299,300,301,302,303,304` at `2026-05-08 01:36:50+00:00`.
- live draft-only audit after the corrected deployment: `automation_decision={auto_send_eligible:19,suppressed:8,auto_skipped:2,retry_enrichment_once:1}`, `final_send_gate_passed={true:19,false:11}`, `email_send_ready={false:30}`, `anomaly_count=0`, `blocked_with_bodies=[]`, `eligible_with_flags=[]`.
- kept the cold-email planner deterministic-only; no LLM rewriter, OpenRouter path, send node, or Instantly path was added.
- updated `services/crawl4ai/outreach_planner.py` so final emails use shorter, friendlier template wording while preserving the four track spines: HIA healthcare readiness, PDPA safeguards, DPO/data-protection evidence, and customer-trust/procurement proof.
- added sentence-slot metadata behind the scenes in `email_sequence_json.sentence_slot_metadata`, plus copy-shaping metadata in `email_sequence_json.style_metadata`.
- tightened HIA Email 2 wording to keep endpoint-based pricing, `S$4,300 before funding` only in smaller-clinic context, conditional `70%` wording, messy evidence work, and LEARN/GOVERN software support.
- kept non-HIA Email 2 evidence/checklist focused and blocked clinic pricing leakage.
- updated `scripts/export_outreach_audit_markdown.py` so audit output includes sentence-slot metadata, word counts, final gate status, and a simple style check summary for long paragraphs, banned words, pricing safety, and HIA diagnostic checks.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/app.py scripts/export_outreach_audit_markdown.py`; `jq -e . wf-cold-email-planner.json`; `python3 -m pytest tests/test_outreach_planner.py -q` (`83 passed`); `python3 -m pytest tests/test_outreach_columns.py -q` (`17 passed`); `python3 -m pytest tests/test_workflow_audit_fallback.py tests/test_outreach_audit_export.py -q` (`6 passed`).
- preview generated: local read-only `draft_only=true` planner preview for rows `278`, `293`, and `301`; no live rows were patched.
- deployment performed: yes, Railway service `n8n-rayn-workflows`.
- live rows patched: yes, draft fields only for the `30`-row live draft-only test.
- no emails were sent, and Instantly was not used.

HIA Email 2 commercial-pricing clarity:

- added deterministic HIA clinic-size and endpoint-band enrichment in `services/crawl4ai/outreach_planner.py`: `clinic_size_guess`, `clinic_size_confidence`, `endpoint_band_guess`, `endpoint_band_confidence`, `pricing_email_2_mode`, `pricing_claim_safe`, `pricing_claim_line`, and `pricing_evidence_json`.
- replaced HIA Email 2 with deterministic CISOaaS pricing/sizing copy: endpoint-based caveat, `S$4,300 before funding` only in smaller-clinic context, group/multi-location sizing language, conditional `70%` wording only when funding is safe, and RAYN certification heavy-lifting plus LEARN/GOVERN SaaS support.
- endpoint uncertainty now selects `pricing_email_2_mode=endpoint_sizing_needed`; it does not suppress or auto-skip rows by itself.
- non-HIA Email 2 remains evidence/checklist or funding-route focused and must not mention `S$4,300` or clinic CISOaaS pricing.
- updated `scripts/ensure_rayn_outreach_columns.py`, `scripts/export_outreach_audit_markdown.py`, planner tests, column tests, and funding workflow docs for the new pricing fields.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/app.py scripts/export_outreach_audit_markdown.py`; `jq -e . wf-cold-email-planner.json`; `python3 -m pytest tests/test_outreach_planner.py -q` (`80 passed`); `python3 -m pytest tests/test_outreach_columns.py -q` (`17 passed`); `python3 -m pytest tests/test_workflow_audit_fallback.py tests/test_outreach_audit_export.py -q` (`6 passed`).
- read-only preview generated from 10 completed live NocoDB rows through the local planner only; no patch was sent. Result: `automation_decision={auto_send_eligible:8,suppressed:1,auto_skipped:1}`, `pricing_email_2_mode={endpoint_sizing_needed:3,group_or_larger_sizing_needed:1,small_clinic_starting_price:5,no_price_claim:1}`, `final_send_gate_passed=8`, `suppressed_with_bodies=[]`, `non_hia_price_rows=[]`, `fallback_funding_word_rows=[]`.
- committed and pushed `441ed62` (`Add HIA pricing clarity to email two`) to `origin/codex/n8n-workflow-checkpoint`.
- deployed Railway service `n8n-rayn-workflows`; deployment `3663d498-cb3c-4795-80d9-db72684021a2` reached `SUCCESS`.
- updated live NocoDB outreach columns using the Postgres public URL; created `8` physical columns, `8` metadata columns, `8` grid columns and `24` select options for the pricing fields. NocoDB service was restarted to reload its schema cache.
- updated live workflow `HbTPGELQQr9DRdAb` from `wf-cold-email-planner.json`; it is active with `7` nodes and no OpenRouter/use_llm path.
- ran a forced draft-only live batch for rows `273,274,275,276,277,278,279,280,282,283`; execution `23734` succeeded.
- live batch result: `automation_decision={auto_send_eligible:8,suppressed:1,auto_skipped:1}`, `pricing_email_2_mode={endpoint_sizing_needed:3,group_or_larger_sizing_needed:1,small_clinic_starting_price:5,no_price_claim:1}`, `endpoint_band_guess={unknown:5,1_5:5}`, `final_send_gate_passed=8`, `email_send_ready=0`, `suppressed_with_bodies=[]`, `non_hia_price_rows=[]`, `fallback_funding_word_rows=[]`.
- no emails were sent, and Instantly was not used.

Deterministic cold-email copy polish:

- kept the cold-email planner deterministic-only after removing the OpenRouter humaniser path; no LLM rewrite path was reintroduced.
- tightened `services/crawl4ai/outreach_planner.py` copy variants: HIA Email 3 variants now all use direct segment-specific diagnostic questions, funding Email 2 followups are shorter/less stiff, value-fallback Email 2 avoids funding wording, Email 1 variant C has a more conversational bridge, and Email 4 close-loop notes are shorter.
- updated HIA diagnostic guardrails so the rotated direct diagnostic variants remain accepted only when segment records, access, backups, incidents, and the expected asset are present.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/app.py`; `jq -e . wf-cold-email-planner.json`; `python3 -m pytest tests/test_outreach_planner.py -q` (`75 passed`); `python3 -m pytest tests/test_outreach_columns.py -q` (`17 passed`); `python3 -m pytest tests/test_workflow_audit_fallback.py tests/test_outreach_audit_export.py -q` (`6 passed`).
- no deployment was performed, no live rows were patched, no emails were sent, and Instantly was not used.

Selected rerun recovery guard:

- added `scripts/rayn_selected_rerun.py` so selected rows can be reset and rerun through URL discovery, public enrichment, contact search, and draft-only planner with explicit gating.
- the rerun script refuses to call the planner for upstream failed/skipped rows and only plans rows with `status=completed`, `best_url` present, and terminal contact status.
- added `allow_low_limits` to `/public-enrich` so controlled retry runs can use lower page/scrape limits instead of being forced back to production minimums.
- purpose: prevent mixed-state anomalies where planner output is patched onto rows whose URL/enrichment stage failed.
- deployed commit `8b0b8c7` to Railway worker service `n8n-rayn-workflows`; deployment `bf2457af-0d9c-46a6-8b96-a055f5882915` reached `SUCCESS`.
- used the guarded rerun script on failed/mixed rows `273,274,275,276,277,278,279,313,316`; all 9 recovered to `status=completed`.
- guarded rerun outcome for those 9 rows: `7 auto_send_eligible`, `1 suppressed`, `1 retry_enrichment_once`; planner was not run until rows were completed with `best_url` and terminal contact status.
- final 50-row audit after recovery: `status={completed:48,skipped:2}`, `automation_decision={auto_send_eligible:29,suppressed:15,auto_skipped:2,retry_enrichment_once:2,blank:2}`, `mixed_failed_with_decision=[]`, `suppressed_with_bodies=[]`.
- no emails sent; Instantly not used.

Parent-company cleanup:

- tightened `services/crawl4ai/public_web_enrichment.py` so public programmes, public schemes, subsidies, PCNs, Healthier SG, CHAS, Medisave, MOH, and immunisation programmes cannot populate `parent_company`.
- weak wording such as `part of`, `under`, and `group company` now only becomes a parent/company-network relationship when the candidate matches the known private healthcare group registry; strong ownership/operator/schema evidence still works.
- corrected live NocoDB row `284` by clearing the bad `parent_company=Primary Care Network (PCN)` value and removing the stale PCN parent-evidence note; follow-up count confirmed `0` rows currently have nonblank `parent_company`.
- also restored real HIA Email 3 diagnostic body variants and softened Email 2 funding variant B wording in `services/crawl4ai/outreach_planner.py`.
- tests run: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/public_web_enrichment.py tests/test_outreach_planner.py tests/test_parent_company_extraction.py`; `jq -e . wf-cold-email-planner.json`; `python3 -m pytest -q tests/test_outreach_planner.py tests/test_parent_company_extraction.py tests/test_public_web_proxy.py` (`93 passed`).
- committed and pushed `d6584f2` (`Tighten parent company and email variants`) and follow-up log commit `b81cc5f` to `origin/codex/n8n-workflow-checkpoint`.
- deployed commit `b81cc5fb522f7451143b856f75198457d37b71d1` to Railway worker service `n8n-rayn-workflows`; deployment `fe99fc50-af3e-4129-b41a-464ff3d0fe36` reached `SUCCESS`.
- live verification passed: `/health` returned `{"status":"ok"}`, and `/outreach-plan` returned the expected `422` validation response for an empty body.
- no emails were sent, and Instantly was not used.

Workflow and NocoDB clutter cleanup:

- verified the live active worker workflow `BQEa6M2pKYmuEYMV` before cleanup: the active contact path was already `Webhook Contact Search Trigger -> Run Contact Search Batch`, while the older contact-search branch starting at `Get Contact Search Rows` had no incoming connection.
- removed the disconnected legacy contact-search branch from `wf-worker.json` and updated the live workflow; the live workflow remains active with `27` nodes, the contact path is still `Webhook Contact Search Trigger -> Run Contact Search Batch`, and `OpenRouter URL Pick` was left unchanged.
- backed up the previous live workflow JSON to `/tmp/n8n-workflow-BQEa6M2pKYmuEYMV-before-clutter-cleanup.json`.
- cleaned the live NocoDB main view from `35` shown columns to `30` shown columns: hid `id`, `last_error`, `selected_contact_seniority`, `selected_contact_email`, `outreach_variant`, `human_review_status`, and `contact_identity_confidence`; showed `contact_search_status` and `contact_search_reason`.
- cleared stale timeout error clutter on `47` completed rows by blanking `error_type`, `error_message`, and `last_error`, and setting `retry_eligible=false`; follow-up query found `0` completed rows with stale error metadata.
- updated NocoDB column helper scripts so future reruns preserve the cleaner default visible-column set.
- updated contact-search docs to reflect current Anymail Finder person, decision-maker, and company-email fallback behavior instead of old No2Bounce-only wording.
- validation passed: `jq -e . wf-worker.json`, `jq -e . wf-cold-email-planner.json`, `python3 -m py_compile scripts/ensure_rayn_outreach_columns.py scripts/ensure_rayn_contact_columns.py`, and `python3 -m pytest -q tests/test_outreach_columns.py` (`18 passed`).
- no emails were sent, and Instantly was not used.

## 2026-05-06

Cold email planner suppressed-row re-entry guard:

- updated `wf-cold-email-planner.json` fetch criteria to keep missing-`validated_email` rows eligible for one planner pass, then exclude rows once `automation_decision` is set.
- confirmed `/outreach-plan` planner output for missing `validated_email` remains `automation_decision=suppressed`, `automation_decision_reason=suppressed_missing_validated_email`, `email_send_ready=false`, `final_send_gate_passed=false`, `skip_openrouter=true`, with no email bodies generated.
- deployed the draft-only workflow update to live n8n workflow `HbTPGELQQr9DRdAb`; no worker/Railway service deploy was needed.
- added missing live NocoDB outreach metadata columns required for the new `automation_decision` fetch filter, then changed deterministic status/mode columns to plain text metadata so planner decisions can be patched without select-option rejection.
- first `limit=20` run failed before planning because `automation_decision` did not exist in NocoDB; second run reached patching but exposed that the workflow funding fallback was re-adding Email 3 bodies to suppressed rows.
- fixed `Collect NocoDB Patches` so funding-body repair only applies to `automation_decision=auto_send_eligible`; reran affected row IDs `278,289,290,294,298,303,304,311,314` with `force=true` to clear suppressed-row bodies.
- successful execution `23448`: `9` patches, `9` audits, `automation_decision={suppressed:9}`, `contact_send_mode={suppressed:9}`, `email_3_mode={funding:6,value_fallback:3}`, anomalies `[]`; OpenRouter did not run.
- exported audit markdown to `docs/workflow/cold-email-audit-2026-05-06-limit20.md`.
- tests run: `jq -e . wf-cold-email-planner.json`; `python3 -m pytest tests/test_outreach_planner.py tests/test_outreach_columns.py tests/test_workflow_audit_fallback.py -q` (`72 passed`).
- No emails were sent. Instantly was not used.

## 2026-05-05

Cold email clinic-profile personalisation:

- `2026-05-05 23:34 +08`: added deterministic clinic/company profile inference for HIA rows in `services/crawl4ai/outreach_planner.py`.
- HIA Email 1 now uses prospect-facing profile phrases such as family/outpatient clinic, solo GP-style clinic, specialist-led clinic, medical/aesthetic clinic, dental clinic, pharmacy / compounding provider, diagnostic / laboratory provider, hearing-care provider, allied-health provider, psychology / mental-health provider, hospice / long-term care provider, and clinic group / multi-location operation.
- added computed copy-brief/audit fields for `clinic_profile_guess`, `clinic_profile_phrase`, `clinic_structure_guess`, `clinic_structure_confidence`, `umbrella_or_group_guess`, `solo_gp_likelihood`, `specialist_led_likelihood`, `multi_practitioner_likelihood`, `primary_service_summary`, and `clinic_structure_evidence`; these were not added as NocoDB columns in this pass.
- strengthened HIA quality flags for missing/generic clinic profile copy while keeping final email bodies blocked from internal "signals" language and HIA batch/date/window wording.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and `python3 -m pytest tests/test_outreach_planner.py -q` returned `44 passed`.
- preview was not generated: local `DATABASE_URL` was unavailable, and no `scripts/preview_first_10_cold_emails.py` helper is present in the repo.
- no deployment was performed, no live NocoDB rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-06 09:28 +08`: generated a read-only first-10 eligible-row preview from NocoDB API using Railway worker environment variables; no row rerun, no NocoDB patch, no deployment, no email send, and no Instantly use.
- preview artifacts: `docs/workflow/cold-email-preview-first-10.md` and `docs/workflow/cold-email-preview-first-10-review.md`.
- preview review found `0` final-body HIA batch/date/window hits, `0` final-body internal "signals" hits, and `0` `email_send_ready=true` rows; row `283` still has `email_1_too_long`, and rows `273` / `284` are currently profiled as `diagnostic_lab`.
- `2026-05-06 09:38 +08`: fixed the preview findings by prioritising aesthetic/GP clinic profile evidence above broad diagnostic/screening terms, making HIA Email 2 validation use the resolved clinic profile, and shortening long-name HIA Email 1 observations without dropping the profile phrase.
- regenerated the read-only first-10 preview; current review has `0` final-body HIA batch/date/window hits, `0` final-body internal "signals" hits, `0` `email_send_ready=true` rows, and no strategy flags except row `280` remaining funding/trigger review.
- validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and `python3 -m pytest tests/test_outreach_planner.py -q` returned `44 passed`.
- `2026-05-06 09:55 +08`: polished Email 1 greeting and problem copy before deploy.
- named non-generic recipients now use `Hi {{first_name}},`; generic/company inboxes use `Hello team,`; final Email 1 still keeps the company name in the `Noticed...` line.
- HIA problem sentences now use `access to {{records/systems}}, backups, patching and incident steps` style wording and avoid duplicate `vendor systems` / `vendors` clutter.
- solo GP wording is confidence-gated; American International Clinic Singapore and AN Medical Clinic now use outpatient medical clinic wording unless family/solo evidence is stronger.
- Andrea's Digestive now uses company-specific specialist-led gastroenterology and digestive care wording without `your clinic` or slash-heavy copy.
- AMP Lab non-clinical lab/testing rows now use PDPA wording around lab/testing services and customer, employee and project records.
- regenerated the read-only first-10 preview with greeting/profile QA columns; review shows `0` bad greetings, `0` duplicate vendor wording, `0` cluttered problem sentences, `0` final-body HIA batch/date/window hits, `0` final-body internal "signals" hits, and `0` `email_send_ready=true` rows.
- validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and `python3 -m pytest tests/test_outreach_planner.py -q` returned `47 passed`.
- no deployment was performed, no live NocoDB rows were patched, no emails were sent, and Instantly was not used.

Cold email planner live QA hardening:

- `2026-05-05 23:12 +08`: tightened HIA Email 2 validation so OpenRouter drafts that do not follow the segment-specific diagnostic shape fall back to deterministic planner copy.
- added regression coverage for wrong-segment pharmacy diagnostics and deterministic aesthetic/allied-health diagnostics; local validation passed with `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and `python3 -m pytest tests/test_outreach_planner.py -q` returning `43 passed`.
- committed and pushed `9313036` (`Tighten HIA email diagnostic QA`) and `6dd3f47` (`Refine HIA diagnostic QA flags`).
- deployed worker service `n8n-rayn-workflows`; Railway deployments `b5438cac-7e89-412c-8a48-123dfcfcbeb9` and final `4dcd11f1-a1d8-4e9f-acf3-c050ab31a96d` reached `SUCCESS`.
- reran the cold-email planner against the completed, validated-email rows. Live n8n executions `23383`, `23386`, and `23387` each processed `38` eligible rows; row `291` was then probed again on execution `23389` after the final deploy.
- live NocoDB verification: `38` eligible rows remain draft-only, `0` rows have `email_send_ready=true`, `0` final email bodies contain `signals`, and `0` final email bodies contain prospect-facing HIA batch/date wording.
- cleared three stale false-positive non-prefixed HIA diagnostic QA flags on rows `287`, `299`, and `317` after verifying the deployed `/outreach-plan` checker no longer emits them for the same segment copy.
- no emails were sent and Instantly was not used.

Proxy usage accounting and first-5 rerun:

- `2026-05-05 20:39:49 +08`: added proxy fallback usage accounting to [services/crawl4ai/public_web_enrichment.py](/Users/sasikumar/Documents/n8n/services/crawl4ai/public_web_enrichment.py) so `crawl_context.proxy` now carries a compact `usage` summary and row `notes` include proxy-attempt counts only when fallback actually ran.
- validation passed: `python3.11 -m py_compile services/crawl4ai/public_web_enrichment.py` and `python3 -m pytest -q tests/test_public_web_proxy.py tests/test_outreach_columns.py tests/test_outreach_planner.py` passed with `55 passed`.
- reset rows `273-277` for a small rerun slice, repopulated `url_picked` through the live `rayn-url-picker-batch` webhook, then reran public enrichment locally with NocoDB writeback so the new proxy accounting code was exercised.
- rerun result for the enrichment slice: rows `273-277` all returned to `status=completed`; none of the five rows needed proxy fallback, so no `Proxy fallback attempted ...` note was written for this batch.
- live `/contact-enrich-batch` rerun on rows `273-277` finished with `3` `contact_found` and `2` `contact_not_found`. Validated emails landed for `273` `ivanpuah@amaris-b.com`, `274` `sharad.govil@amazinghearing.com`, and `276` `jayne@amber-pharmacy.com`.
- the first cold-planner rerun exposed a live worker mismatch: active n8n execution `23368` failed because `Generate Outreach Plan` hit `https://n8n-rayn-workflows-production.up.railway.app/outreach-plan` and received `404 Not Found`.
- deployed Railway worker service `n8n-rayn-workflows`; deployment `d93a1b9f-2efc-4c57-a055-9be3d068c4f0` brought `/outreach-plan` back. Direct verification after deploy returned `422` for an empty POST body, confirming the route exists again.
- because the follow-up n8n planner webhook still did not complete a visible new execution/writeback for the three validated rows, finished the draft pass locally with deterministic `outreach_planner.plan_and_patch()` on rows `273`, `274`, and `276`.
- final live smoke after the deploy succeeded: cold-planner execution `23369` completed successfully and row `273` repopulated `email_1_subject` via the live n8n workflow.
- final draft state after the three-stage rerun: rows `273`, `274`, and `276` now have refreshed Email 1-4 subjects/bodies with `human_review_status=ready_for_review` and `email_send_ready=false`; rows `275` and `277` remain undrafted because `validated_email` is blank after contact search.
- no emails were sent and Instantly was not used.

Anymail company fallback hardening:

- `2026-05-05 20:57:42 +08`: made the last-resort Anymail company fallback auditable even when it returns no deliverable email by preserving a `provider=anymail_finder_company` marker in `email_candidates_json`.
- set Railway worker variables `CONTACT_COMPANY_EMAIL_FALLBACK_ENABLED=true` and `ANYMAILFINDER_COMPANY_FALLBACK_ENABLED=true` explicitly, then deployed worker service `n8n-rayn-workflows` with deployment `d4704663-c280-46bd-bc07-a73a7f034fc5`.
- validation passed: `PYTHONPATH=services/crawl4ai:. python3 -m pytest -q tests/test_contact_candidate_verifier.py` returned `27 passed`; `PYTHONPATH=services/crawl4ai:. python3 -m py_compile services/crawl4ai/contact_enrichment.py` passed.
- reran contact search for rows `275` and `277`; both now show `email_validation_provider=anymail_finder_company` and `contact_search_status=contact_found`.
- row `275` accepted `contactus@amberfamilyclinic.com` from Anymail company fallback after person-specific lookup had no sendable email.
- row `277` accepted `zakowich@aiclinic.com.sg` from Anymail company fallback, then identity resolution matched it to `Paul Zakowich`, `Doctor`.
- no emails were sent and Instantly was not used.

Cold email planner fetch hardening and QA:

- `2026-05-05 19:22:14 +08`: updated `wf-cold-email-planner.json` so `Get Outreach Rows` fetches only completed, validated rows with `email_1_subject` blank. This prevents repeated reprocessing of already drafted rows and deterministic `not_ready` rows.
- deployed the updated live n8n workflow `HbTPGELQQr9DRdAb`; workflow remained active and draft-only.
- validation passed: `wf-cold-email-planner.json` parsed as valid JSON, `tests/test_outreach_columns.py` passed with `12 passed`, and `tests/test_outreach_planner.py` passed with `35 passed`.
- live n8n validation still reports the existing `Prepare OpenRouter Email Draft` Code-node expression warning/error, which appears to come from literal `{{company_name}}` prompt text and was not introduced by this filter change.
- NocoDB verification returned `0` rows for the live planner fetch condition after catch-up: completed + validated + `email_1_subject` blank.
- compact QA over the `36` `ready_for_review` drafts found `0` strategy findings. No emails were sent and Instantly was not used.
- `2026-05-05 20:11:11 +08`: switched the cold-email OpenRouter draft model in `wf-cold-email-planner.json` from `anthropic/claude-sonnet-4.6` to `x-ai/grok-4.3` and updated live workflow `HbTPGELQQr9DRdAb`; workflow remained active and draft-only.
- validation passed: `wf-cold-email-planner.json` parsed as valid JSON and `tests/test_outreach_columns.py` passed with `13 passed`. Live n8n validation still reports the existing `Prepare OpenRouter Email Draft` Code-node expression warning/error noted above.

Proxy configuration update:

- `2026-05-05 19:34:01 +08`: updated Railway production variables for `n8n-rayn-workflows` to use the DataImpulse residential default-targeting endpoint, keep `PUBLIC_WEB_ENRICHMENT_PROXY_MODE=fallback`, and restrict `PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS` to known difficult domains: `andental.sg`, `aiclinic.com.sg`, `appletreemedicalgroup.com`, `ashforddentalcentre.com.sg`, `ashfordmedical.com.sg`, and `ahvc.com.sg`.
- Railway started deployment `53d93271-a98d-41b5-8d1f-c4c5ea25d19f` for the environment variable change.
- no emails were sent and Instantly was not used.
- `2026-05-05 19:36:52 +08`: removed the hardcoded proxy domain allowlist by setting `PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS` to a blank value while keeping `PUBLIC_WEB_ENRICHMENT_PROXY_MODE=fallback`; this means the worker should not use proxy for normal crawls and should only try proxy after challenge/anti-bot/timeout-style fallback conditions.
- Railway started deployment `62dc2bab-5bdc-46a3-9ee9-34369485be83` for the corrected proxy-domain setting.

Cold email copy QA and strategy gate:

- `2026-05-05 14:15:35 +08`: reviewed the contact-gating patch from `829febc` and tightened cold-email strategy quality without enabling any send path.
- added `copy_qa_mode` to `/outreach-plan` so sample companies can generate review drafts without `validated_email`; this mode forces `email_send_ready=false` and cannot auto-approve rows.
- kept production draft mode gated by `validated_email`.
- added deterministic email strategy flags for missing specific signal, problem statement, mechanism statement, tiny CTA, generic Email 1, non-diagnostic Email 2, non-funding-only Email 3, and wrong greeting for generic/company inboxes.
- updated generic/company inbox greetings to use `Hi team,` or `Hi {{company_name}} team,` without inventing a person name.
- updated `wf-cold-email-planner.json` so OpenRouter is skipped when the copy brief is incomplete or too generic; those rows use the deterministic `/outreach-plan` patch only.
- local validation passed: Python compile checks for `services/crawl4ai/outreach_planner.py` and `services/crawl4ai/app.py`, `jq -e wf-cold-email-planner.json`, focused outreach tests with `34 passed`, and the full test suite with `76 passed`.
- no deployment was performed, no emails were sent, and Instantly was not used.

Cold email strategy rerun hardening:

- `2026-05-05 14:48:01 +08`: after the first post-deploy rerun showed Claude drafts still drifting into generic structure, meeting CTAs and non-funding Email 3 copy, tightened `/outreach-validate-email`.
- LLM drafts with strategy rejection flags now fall back to the deterministic `/outreach-plan` patch before NocoDB writeback.
- shortened deterministic HIA Email 1 copy-brief ingredients so fallback drafts can stay within the 85-word quality limit while retaining the HIA timeline, access/vendor/backup/incident, and Cyber Essentials baseline points.
- local validation passed: Python compile checks for `services/crawl4ai/app.py` and `services/crawl4ai/outreach_planner.py`, and the full test suite with `76 passed`.
- no emails were sent and Instantly was not used.

## 2026-05-04

Contact fallback and outreach gating:

- added a last-resort generic inbox fallback in `services/crawl4ai/contact_enrichment.py`; it only runs after person-specific and decision-maker paths fail, extracts same-domain generic inboxes from `website_content`, and validates them through No2Bounce before accepting a sendable email.
- generic inbox fallback now returns `contact_found` only on validated generic inboxes and marks rows `failed` when generic fallback is available but `NO2BOUNCE_API_TOKEN` is not configured or No2Bounce errors.
- tightened `/outreach-plan` so rows without `validated_email` are rejected as `missing_sendable_email` even when `draft_only` is set.
- updated `wf-cold-email-planner.json` to fetch only rows with `validated_email` and skip email drafting entirely when no sendable email exists.
- added regression tests for generic-email fallback success, generic-email fallback without named candidates, missing No2Bounce configuration, and the outreach-plan sendable-email gate.
- local validation completed after the patch; no deployment was performed, no Instantly node was used, and no emails were sent.

Copy-brief quality refinement:

- refined `build_copy_brief()` so `email_personalisation_signal` uses concrete service, team/practitioner, location, care/community, hearing-care, customer-security, vendor-dashboard or integration signals rather than generic segment wording.
- made Email 2 diagnostics segment-specific for HIA/clinic, social service, B2B/customer-trust, and general PDPA rows.
- added quality-gate flag `generic_personalisation_signal` for copy briefs that rely on generic phrases without concrete public evidence.
- added tests for Amaris B. Clinic, Sree Narayana Mission, Amazing Hearing Group, B2B customer-trust rows, and diagnostic-specific Email 2 behavior.
- local validation passed with `62 passed`; no deployment was performed and no emails were sent.

Copy-brief email planning:

- added deterministic copy-brief enrichment fields to the outreach installer, including company profile, services, locations, team signals, data handled, data systems, pressure angles, funding safety, and email-specific messaging ingredients.
- updated the cold-email planner to build `copy_brief` before email generation; deterministic drafts and OpenRouter prompts now use `email_personalisation_signal`, `email_problem_statement`, `email_mechanism_statement`, `email_asset_offer`, and `email_cta` instead of only generic classification fields.
- updated `wf-cold-email-planner.json` to fetch richer public-enrichment fields and send copy-brief fields to OpenRouter model `anthropic/claude-sonnet-4.6`; workflow remains `draft_only=true`.
- added hard not-ready handling for missing copy-brief essentials, plus quality-gate checks for researched Email 1, diagnostic Email 2, funding-only Email 3, and `funding_claim_safe=false`.
- local validation passed: compile checks succeeded, `jq -e wf-cold-email-planner.json` succeeded, and `pytest` passed with `61 passed`.
- no deployment was performed for this copy-brief patch, no Instantly node was used, and no emails were sent.

Copy-brief live deployment and first-5 rerun:

- installed copy-brief outreach columns in production via `scripts/ensure_rayn_outreach_columns.py`; summary reported `created_physical=34`, `created_metadata=34`, `created_grid=34`, and `created_select_options=19`.
- restarted `nocodb` to refresh field metadata; verified copy-brief columns were visible through the NocoDB API and physical table `pb7f1zou786xyqc.leads`.
- updated live workflow `RAYN Cold Email Planner v1` to fetch richer enrichment fields and send copy-brief fields to OpenRouter; workflow remained `draft_only=true` and had no Instantly node.
- deployed worker service `n8n-rayn-workflows`; final successful deployment was `193de6bd-110e-4bee-af76-9e2611f3c89a`.
- reran first 5 eligible rows. Rows `273`, `274`, `275`, and `277` received copy-brief email drafts with `email_send_ready=false`; row `276` remained `not_ready` with zero email bodies.
- no emails were sent and no row was marked sent.

First-5 OpenRouter email rerun:

- reran cold-email planner with `limit=5` and `draft_only=true`; no Instantly node was used and no emails were sent.
- after the first rerun exposed unsafe OpenRouter drift in Email 3 and not-ready row output, added safeguards so Email 3 is clamped to `funding_claim_line` and `not_ready` rows keep empty email bodies.
- deployed worker service `n8n-rayn-workflows`; final successful deployment was `6be3c823-ee3b-4c8e-a065-d42f57db36f5`.
- final first-5 verification: rows `273`, `274`, `275`, and `277` had draft sequences with `email_send_ready=false`; row `276` was `not_ready` with zero email bodies; no row was marked sent.

OpenRouter cold-email drafting:

- added the OpenRouter HTTP node to `wf-cold-email-planner.json` using model `anthropic/claude-sonnet-4.6`; workflow still patches draft fields only and does not call Instantly or send email.
- added `/outreach-validate-email` worker validation so OpenRouter JSON is normalized, quality-gated, and safely falls back to deterministic drafts when invalid.
- set the cold-email webhook response mode to `onReceived` so draft patch completion is verified through NocoDB rather than blocking the webhook response.
- deployed worker service `n8n-rayn-workflows`; final successful deployment was `c7e954e0-5d17-4e5a-9955-6136b309b394`.
- live one-row smoke with `draft_only=true` patched row `273` (`Amaris B. Clinic`): `email_send_ready=false`, `human_review_status=ready_for_review`, `funding_status=possible_match`, `email_3_body` contained the deterministic `funding_claim_line`, and quality flags were `["funding_not_verified"]`.
- no deployment was made for an email sender, no Instantly node was used, and no emails were sent.

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

Decision-maker fallback rerun:

- reset and reran the `30` eligible rows that were `contact_not_found`.
- final full eligible-table state: `21` `contact_found`, `27` `contact_not_found`, `0` failed, `0` pending, `0` processing.
- decision-maker fallback found `3` new contacts: row `279` `jamie@amoystdental.com`, row `292` `drtyson@appletreemedicalgroup.com`, and row `310` `monga.amitabh@asiadigestive.sg`.
- targeted rerun result: `3` `contact_found`, `27` `contact_not_found`; final miss reasons are `17` `candidates_found_but_no_sendable_email` and `10` `no_validated_person_found`.
- targeted usage proxies: `22` Anymail person requests, `30` decision-maker fallback rows, `2` non-cached decision-maker requests recorded in row evidence, `12` decision-maker credits recorded, and `0` final decision-maker errors after retrying timeout rows `277`, `293`, and `315`.

Anymail timeout retry patch:

- committed and pushed `eeea4b3` (`Retry Anymail timeout failures`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `58054bde-94f5-4ec9-b8df-49654d35bd22` reached `SUCCESS` and `/health` returned OK.
- added bounded retry handling around Anymail person lookup and decision-maker lookup; timeouts, HTTP `429`, and HTTP `5xx` retry once by default before the row is marked failed.
- retry tuning env vars: `ANYMAILFINDER_PERSON_RETRIES`, `ANYMAILFINDER_PERSON_RETRY_BACKOFF_SECONDS`, `ANYMAILFINDER_DECISION_MAKER_RETRIES`, and `ANYMAILFINDER_DECISION_MAKER_RETRY_BACKOFF_SECONDS`.
- row evidence now records Anymail attempt counts, per-attempt duration/error/status, and whether the lookup retried.

Contact batch timeout cap and full scratch rerun:

- committed and pushed `cad64d9` (`Cap decision maker contact batch size`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `8619da62-dbbc-4a05-bcf4-b7a3100dfa26` reached `SUCCESS` and `/health` returned OK.
- capped pending-row `/contact-enrich-batch` runs to `3` rows by default when decision-maker fallback is enabled via `CONTACT_BATCH_MAX_DECISION_MAKER_ROWS`; explicit ID batches are not capped.
- reset all `48` eligible completed, non-duplicate rows with canonical domains and best URLs to `pending` using reason `full_contact_scratch_rerun_after_timeout_fixes`.
- drained the live worker from scratch in `17` batch calls. Each active batch returned HTTP `200` with `requested=10`, `effective=3`, and `capped_by=CONTACT_BATCH_MAX_DECISION_MAKER_ROWS`; no request-level timeout occurred.
- final full eligible-table state: `22` `contact_found`, `26` `contact_not_found`, `0` failed, `0` pending, `0` processing.
- validated-email rows: `273`, `274`, `276`, `279`, `280`, `286`, `288`, `291`, `292`, `293`, `295`, `296`, `299`, `302`, `305`, `310`, `312`, `313`, `316`, `317`, `318`, `319`.
- final reasons: `12` `sendable_person_specific_email_found`, `10` `sendable_decision_maker_email_found`, `16` `candidates_found_but_no_sendable_email`, and `10` `no_validated_person_found`.
- usage proxies from row evidence: `90` Serper provider/query attempts, `749` total search results stored, `446` raw candidates, `58` verified candidates, `77` candidate objects written, `13` official-site preflight candidates, `0` search errors, `0` provider timeouts, `38` Anymail person requests, `36` decision-maker fallback rows with `26` cache hits and `10` live decision-maker attempts, `5` total Anymail credits charged, and `4` decision-maker credits charged.
- retry evidence: person lookup retried once on row `273` and then succeeded; no decision-maker fallback retries were needed in the final scratch run.

Decision-maker LinkedIn profile column:

- committed and pushed `3d17a8c` (`Capture contact LinkedIn profile`) and `27b4b68` (`Guard decision maker LinkedIn matches`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `da8725c4-e455-4052-8b5b-a00f249a5924` reached `SUCCESS` and `/health` returned OK.
- added NocoDB column `selected_contact_linkedin_url`; NocoDB schema cache required a `nocodb` service restart before the API recognized the new field.
- the worker now maps Anymail decision-maker `person_linkedin_url` into `selected_contact_linkedin_url` only when the LinkedIn `/in/` slug plausibly matches the returned person name.
- backfilled `8` existing rows with matching decision-maker LinkedIn URLs: `276`, `279`, `288`, `292`, `305`, `310`, `312`, and `316`.
- row `280` was not backfilled because Anymail returned a LinkedIn URL whose profile slug did not match the selected contact name.

Deeper public website scrape:

- committed and pushed `bd13e74` (`Deepen public website scrape`) and `eae818a` (`Enforce deep public scrape defaults`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `c5b0c23d-9169-4374-8503-0165f6a66833` reached `SUCCESS` and `/health` returned OK.
- raised public enrichment defaults from `5` pages / `60000` scrape chars to `12` pages / `120000` scrape chars, with server-side minimums `PUBLIC_ENRICH_MIN_PAGE_LIMIT=12` and `PUBLIC_ENRICH_MIN_SCRAPE_CHARS=120000` so older workflow payloads still get deeper crawling.
- expanded high-value crawl targets for team, doctors, dentists, consultants, services, treatments, locations, FAQ, news/blog, appointments, pricing, insurance, partners, accreditation, and related healthcare terms.
- preserved homepage anchor text for internal links and boosted actual discovered links and sitemap URLs ahead of guessed common paths.
- added second-hop high-value link discovery from crawled pages until the page limit is reached; robots rules, crawl delay, duplicate-content skipping, and timeout fallback remain in place.
- live probe for Amaris B. Clinic using an old-style `page_limit=5` request returned `6` crawled pages, `19` location signals, `20` service signals, and `9` team signals; the prior note showed `2` pages, `5` location signals, `12` service signals, and `0` team signals.

Challenge-page static recovery and first-10 rerun:

- committed and pushed `0d8d3f5` (`Recover challenge pages with static fetch`), then deployed worker service `n8n-rayn-workflows`; Railway deployment `d516fc0c-04b3-4780-a4ed-839134d04893` reached `SUCCESS` and `/health` returned OK.
- when Crawl4AI returns a homepage challenge page, the worker now tries a plain requests/static fetch before skipping the row; if the static fetch yields normal page text without challenge hints, the scrape continues and records a recovery note.
- reran the first `10` rows from the earlier completed/eligible slice: `273`, `274`, `275`, `276`, `277`, `278`, `279`, `280`, `282`, `283`.
- improved rows included `273` (`2` -> `6` pages, `0` -> `9` team signals), `274` (`1` -> `3` pages, `2` -> `6` team signals), `275` (`2` -> `11` pages, `6` -> `24` service signals), `276` (`1` -> `2` pages), and `278` (`1` -> `3` pages, `1` -> `2` service signals).
- row `277` initially regressed to `skipped_challenge_detected`; after the static-recovery patch it completed again with `1` crawled page and a recovery note indicating static fetch succeeded after the challenge page.
- rows `279`, `280`, and `283` remained effectively unchanged at `1` crawled page.
- row `282` (`An Dental`) still ends `skipped_challenge_detected` from the Railway environment despite the static-recovery patch; repeated rerun attempts keep returning the SG challenge flow from the scraper side.

Scoped proxy support for public-web challenge domains:

- added env-driven proxy support to the public enrichment worker for both the Crawl4AI browser path and the static `requests` fallback.
- new worker env vars: `PUBLIC_WEB_ENRICHMENT_PROXY_URL` and optional `PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS`; if the domain list is omitted, the proxy applies to all public enrichment crawls.
- proxy selection matches both exact domains and registered domains, so `andental.sg` also covers `www.andental.sg`.
- accepted proxy URL formats now include standard proxy URLs like `http://user:pass@host:port`, `host:port`, and `host:port:user:pass`.
- the Playwright captcha-solver recovery path now reuses the same proxy configuration when one is active.
- focused validation passed locally with `28` tests (`test_public_web_proxy.py`, `test_parent_company_extraction.py`, `test_contact_candidate_verifier.py`) plus Python compile checks.
- Railway production currently has no `PUBLIC_WEB_ENRICHMENT_PROXY_URL` variable on service `n8n-rayn-workflows`, so row `282` cannot be retested through a proxy until real proxy credentials are added.

Cold email planning and funding enrichment workflow:

- added a non-sending cold email planning layer for funding-aware enrichment, HIA/PDPA/trust pressure classification, draft generation, quality flags, and NocoDB patch output for human review.
- created deterministic funding programme matching with source verification gates; funding claims can become `verified_match` only when the programme entry is `verified_current`.
- added deterministic outreach planning with four-email draft generation, forbidden-phrase checks, word-count limits, HIA/PDPA overclaim guards, and funding-only Email 3 from `funding_claim_line`.
- added worker endpoint `/outreach-plan` for draft planning only; it blocks `do_not_contact`, unsubscribed/bounced/complained rows, and rows without email unless `draft_only = true`.
- updated the Crawl4AI Dockerfile so future worker deployments include the new funding and outreach planner modules.
- created separate workflow file `wf-cold-email-planner.json` rather than extending `wf-worker.json`; it reads completed public-enrichment rows, calls `/outreach-plan`, and patches draft fields only.
- no deployment was performed for this stage.

Cold email planning NocoDB column installer:

- added `scripts/ensure_rayn_outreach_columns.py` to create the cold-email planning fields in the physical Postgres table, NocoDB metadata, and the first grid view.
- the script follows the existing `ensure_rayn_contact_columns.py` pattern and is idempotent.
- updated `wf-cold-email-planner.json` so the row fetch requests only established enrichment/contact fields plus fields created by the outreach column installer.
- no deployment was performed.

Cold email planning setup validation:

- `2026-05-04 15:32:21 +08`: validated the cold-email planner setup after adding the NocoDB outreach column installer.
- updated `scripts/ensure_rayn_outreach_columns.py` with a `--dry-run` option and a safe JSON completion summary covering `created_physical`, `existing_physical`, `created_metadata`, `existing_metadata`, `created_grid`, and `existing_grid`.
- added contract tests confirming `OUTREACH_COLUMNS` has unique names, includes every field patched by `outreach_planner.build_noco_patch()`, uses the expected field types for checkbox/number/long-text fields, includes all four email subject/body pairs, and rejects the configured forbidden phrases.
- validated `wf-cold-email-planner.json` requests only established enrichment fields or fields created by the outreach installer; the workflow uses `draft_only = true`, calls `/outreach-plan`, patches draft/review fields only, and has no Instantly or email-sending integration.
- smoke-tested synthetic Sree Narayana Mission, Amaris B. Clinic, and Amazing Hearing Group style rows through `outreach_planner.plan_and_patch()`; all returned draft patches and `email_send_ready = false` while funding remained unverified.
- local validation passed: Python compile checks for `funding_programs.py`, `outreach_planner.py`, and `ensure_rayn_outreach_columns.py`; workflow JSON parse; and `53` pytest tests.
- `DATABASE_URL` was not available in the local environment, so the NocoDB outreach columns were not installed or verified in Postgres during this pass. Operator command remains `python3 scripts/ensure_rayn_outreach_columns.py --database-url "$DATABASE_URL"` after supplying a real database URL.
- no deployment was performed, no emails were sent, no Instantly integration was used, and no row was marked as sent.

Cold email outreach column operator runbook update:

- `2026-05-04 15:34:22 +08`: added a safe operator runbook for running `scripts/ensure_rayn_outreach_columns.py` only in an environment where `DATABASE_URL` is available.
- local validation was completed in the previous pass, but `DATABASE_URL` remains unavailable locally.
- migration was not run locally.
- outreach columns were not verified in Postgres locally.
- no deployment was performed.
- no emails were sent.
- Instantly was not used.

Cold email buying-pressure tracks:

- `2026-05-04 15:41:11 +08`: updated the outreach planner to route drafts through four buying-pressure tracks: HIA regulatory readiness, PDPA/Cyber Essentials safeguards, DPO/data-protection evidence owner, and customer-trust/procurement proof.
- HIA rows now lead with HIA timeline/readiness and position Cyber Essentials only as a practical first baseline for HIA cybersecurity/data-security readiness.
- Non-HIA rows now lead with PDPA personal-data safeguards or security evidence, and say Cyber Essentials supports the security-safeguards side of PDPA readiness rather than implying PDPA compliance.
- DPO, compliance, privacy, operations, admin and HR contacts now use a data-protection evidence angle.
- B2B, SaaS, outsourcing, education, finance, HR/recruitment, professional-services, vendor and enterprise-facing rows now use a customer security evidence angle.
- low-signal rows now become `not_ready` instead of receiving a usable outreach sequence.
- local validation passed: Python compile checks for `outreach_planner.py`, `funding_programs.py`, and `ensure_rayn_outreach_columns.py`; workflow JSON parse; and `56` pytest tests.
- no deployment was performed, no emails were sent, and Instantly was not used.

Cold email planner live setup and smoke:

- `2026-05-04 18:28:33 +08`: committed and pushed the cold-email planner setup patches through `d9b5fbb` on `codex/n8n-workflow-checkpoint`.
- installed the outreach columns against Railway Postgres using `DATABASE_PUBLIC_URL` from the `Postgres` service because `DATABASE_URL` is private-network only from local execution.
- installer result: `75` total outreach columns, `71` newly created physical columns, `71` NocoDB metadata rows, `71` grid entries, and later `152` select-option rows; reruns reported all `75` physical/metadata/grid columns existing.
- verified physical Postgres columns through `information_schema.columns`: `required_count=75`, `existing_required_count=75`, `missing_count=0`.
- restarted NocoDB schema cache so the API recognized newly created fields and select options.
- created and activated live n8n workflow `RAYN Cold Email Planner v1` with ID `HbTPGELQQr9DRdAb`; workflow is webhook/manual only, draft-only, and has no Instantly or email-sending nodes.
- fixed live workflow import issues found during smoke: explicit POST webhook, NocoDB credential references, raw JSON request bodies, and null-to-string/boolean payload normalization before `/outreach-plan`.
- deployed worker service `n8n-rayn-workflows`; Railway deployment `50dcb0d1-3fd0-45c9-acff-d709ee855cf9` reached `SUCCESS`; `/health` and `/outreach-plan` returned HTTP `200`.
- smoke ran `POST /webhook/rayn-cold-email-planner` with `limit=3` and patched rows `273`, `274`, and `275` only for draft/review fields.
- smoke verification: all three rows have email subjects present, `email_send_ready=false`, `human_review_status=ready_for_review`, and `funding_status=possible_match`.
- no emails were sent, Instantly was not used, and no row was marked as sent.

HIA siloing and funding source refresh:

- `2026-05-05 15:43 +08`: researched official HIA implementation timelines and funding support pages, plus CSA CISOaaS guidance.
- encoded deterministic HIA service-type siloing so medium/high-confidence healthcare rows lead with `hia_regulatory`; PDPA remains the non-HIA personal-data fallback.
- added official batch mapping for GP OMS, hospitals, diagnostics, specialist OMS, nursing homes, dialysis, dental, pharmacy, ambulatory surgical, assisted reproduction, and other HCSA/NEHR CS/DS rows.
- added a verified-current HIA CISOaaS funding route with guarded "up to 70% co-funding" wording for eligible SMEs, subject to programme confirmation.
- no deployment was performed, no emails were sent, and no Instantly integration was used.

Ambiguous HIA LLM review:

- `2026-05-05 15:43 +08`: added an optional OpenRouter-backed HIA review layer for ambiguous healthcare-adjacent rows only.
- deterministic high-confidence HIA results remain authoritative and cannot be overridden by the LLM.
- ambiguous rows can be promoted to HIA or rejected from HIA only when the LLM returns medium/high confidence and evidence-backed strict JSON.
- local validation passed: compile checks for `app.py`, `outreach_planner.py`, and `funding_programs.py`; targeted outreach/funding tests `33 passed`; full pytest with service path `84 passed`.
- no deployment was performed by this code patch step, no emails were sent, and no Instantly integration was used.
- fixed live patch rejection by ensuring `hia_service_type_guess` only writes NocoDB-supported select values; official renal dialysis, ambulatory surgical, and assisted reproduction batch claims now keep the select value as `unknown` with the batch stored in `hia_timeline_batch_guess`.
- fixed clinic entity precedence so clinic rows are not misclassified as social-service because of incidental words in scraped content.
- `2026-05-05 16:14 +08`: deployed worker updates to Railway deployment `e096c2f7-0afa-4b90-bd69-ff5d62ecda18` and reran the cold email planner for the first 20 completed rows with validated emails.
- first-20 verification: all 20 rows have `email_1_subject`, all keep `email_send_ready=false`, and no emails were sent.
- HIA routing verification: American International Clinic Singapore now patches `pressure_type=hia_regulatory`, `hia_service_type_guess=GP_OMS`, `hia_timeline_batch_guess=Batch 1 - Sep 2027`, and `funding_status=verified_match`.

Cold email copy QA hardening:

- `2026-05-05 16:28 +08`: tightened deterministic copy fallback after first-20 QA showed LLM drafts could still fail `email_1_too_generic` or drift in funding email 3.
- copy signals now prefer concrete service/team/record cues such as clinic services, practitioner signals, hearing-care appointment/test/device records, care/community-service data, and B2B reusable evidence.
- bad LLM email sequences now fall back to deterministic copy when strategy checks reject Email 1, Email 2, Email 3, or generic-inbox greeting.
- Email 3 is rebuilt when it contains the funding claim plus non-funding HIA/PDPA drift; duplicate programme-confirmation caveats are avoided.
- local validation passed: Python compile checks for `outreach_planner.py`, `funding_programs.py`, and `ensure_rayn_outreach_columns.py`; targeted outreach/funding tests `37 passed`.
- no deployment was performed by this patch step, no emails were sent, and Instantly was not used.
- `2026-05-05 16:33 +08`: added compact planner audit reports to `/outreach-plan`, `/outreach-validate-email`, and the n8n collection step.
- each audit report includes `row_id`, `company_name`, `pressure_type`, `hia_service_type_guess`, `hia_timeline_batch_guess`, `funding_status`, `email_quality_flags`, and email bodies 1-3 for review after each planner run.
- no deployment was performed by this audit-report patch step, no emails were sent, and Instantly was not used.
- `2026-05-05 16:51 +08`: deployed audit/draft-safety updates to Railway deployment `7a791fa1-02b3-477b-aa40-87ee8ed5807a`; `/health` returned HTTP 200.
- updated live n8n workflow `HbTPGELQQr9DRdAb` so the collect step returns `audits`, successful execution data is saved, and production rows are passed with `draft_only=true`.
- reran the first 20 completed, validated-email rows through `rayn-cold-email-planner`; NocoDB verification returned 20 rows patched with email subjects and compact audit fields.
- final first-20 verification: all 20 rows keep `email_send_ready=false`; row `277` American International Clinic Singapore remains `pressure_type=hia_regulatory`, `hia_service_type_guess=GP_OMS`, `hia_timeline_batch_guess=Batch 1 - Sep 2027`, and `funding_status=verified_match`.
- Email 3 caveat duplication was removed in the final rerun; no emails were sent and Instantly was not used.
- `2026-05-05 17:00 +08`: refined the cold-email planner audit and n8n funding fallback after reviewing commit `3ebbbf0`.
- n8n fallback funding email now uses `Hi {{company_name}} team,` when a company name is available, otherwise `Hi team,`; it no longer falls back to `Hi,`.
- n8n fallback avoids duplicating `subject to programme confirmation` when the funding claim already includes it, and still updates `email_sequence_json.email_3.body` plus `word_count`.
- compact audit reports now include all four email subjects and all four email bodies.
- added `scripts/export_outreach_audit_markdown.py` to convert n8n audit JSON into a readable markdown QA report with row metadata, flags, and the full 4-email sequence.
- local validation passed: workflow JSON parse, Python compile checks for `app.py`, `outreach_planner.py`, and the audit export script; focused pytest suite `37 passed`.
- no deployment was performed by this patch step, no emails were sent, and Instantly was not used.
- `2026-05-05 17:19 +08`: deployed the latest audit/fallback patch to Railway deployment `8b434d3a-4da5-48ae-886d-11cb77db0eb0`; `/health` returned HTTP 200.
- updated live n8n workflow `HbTPGELQQr9DRdAb` with the latest collect-step audit and funding fallback code.
- ran the cold-email planner with `limit=50`; the selector found `24` eligible completed rows with validated emails and patched all 24.
- rerun row IDs: `273`, `274`, `275`, `276`, `277`, `279`, `280`, `282`, `288`, `291`, `292`, `293`, `295`, `296`, `299`, `302`, `305`, `310`, `312`, `313`, `316`, `317`, `318`, `319`.
- verification: all 24 rows have `email_send_ready=false`; rows `316` Asia Physio is `not_ready`, `317` Asia Psychology Centre is `hia_regulatory`, `318` AspenHealth Singapore is `pdpa_safeguards`, and `319` Assisi Hospice is `hia_regulatory`.
- no emails were sent and Instantly was not used.
- `2026-05-05 17:30 +08`: fixed the audited copy-brief weaknesses from the 24-row manual QA.
- healthcare service detection now treats company-name and website cues for physio, psychology/mental health, hospice/long-term care, digestive/gastroenterology, diagnostic/screening/lab, oncology/radiation, dental, pharmacy, and hearing care as stronger than generic clinic wording.
- HIA Email 1 and Email 2 now use segment-specific record language for physiotherapy treatment/exercise-plan records, psychology assessment/case-note records, hospice patient/resident/family/volunteer/staff data, diagnostic reports, digestive/gastroenterology records, oncology/radiation treatment records, and hearing appointment/test/device records.
- added regression tests for Asia Physio, Asia Psychology Centre, Assisi Hospice, and Asia Digestive Associates style rows so these no longer collapse to generic clinic wording or `not_ready` when the evidence is present.
- local validation passed: Python compile check for `outreach_planner.py`; focused outreach/audit/funding pytest suite `44 passed`.
- no deployment was performed by this patch step, no emails were sent, and Instantly was not used.
- `2026-05-05 21:22 +08`: tightened Email 1 target style after copy QA showed the copy brief was still merging signal and pressure text.
- Email 1 is now template-controlled as company-team greeting, `Noticed...` concrete signal, practical pressure/problem, Cyber Essentials baseline, and one tiny CTA.
- HIA clinic copy now supports the American International Clinic target shape: medical clinic/doctor/outpatient signal, Batch 1 Sep 2027 HIA window when safe, patient-data access/vendors/backups/patching/incident steps, and HIA readiness map CTA.
- non-HIA PDPA and B2B trust copy now use the requested practical safeguard/proof framing without saying Cyber Essentials equals PDPA or HIA compliance.
- local validation passed: workflow JSON parse, Python compile check for `outreach_planner.py`, and focused outreach/contact/proxy tests `86 passed`.
- no deployment was performed by this patch step, no emails were sent, and Instantly was not used.
- `2026-05-05 21:41 +08`: deployed the updated Crawl4AI worker to Railway service `n8n-rayn-workflows`; deployment `2b20ff36-56a5-4a03-acd9-cc05289c3d25` reached `SUCCESS`.
- updated live workflow `HbTPGELQQr9DRdAb` to match the new copy prompt rules and added `force=true` plus `row_ids` support in `Get Outreach Rows` so exact rerun slices can be targeted without changing the normal blank-only selector.
- reran the first five validated rows explicitly as IDs `273, 274, 275, 276, 277`; live execution `23375` patched all five rows in draft-only mode.
- verification from execution `23375`: `23375` audit payloads show the new Email 1 structure live, including `American International Clinic Singapore` with `medical clinic, doctor and outpatient appointment signals`, `Batch 1 Sep 2027 HIA window`, and `Cyber Essentials is a practical first baseline for the cybersecurity/data-security side.`
- no emails were sent and Instantly was not used.
- `2026-05-05 22:12 +08`: refined prospect-facing cold email wording so internal audit language stays in copy-brief fields but no longer leaks into final email bodies.
- added `prospect_facing_signal(...)` in `services/crawl4ai/outreach_planner.py`, wired deterministic Email 1 and the OpenRouter prep node to use the translated observation, and added the quality flag `email_1_contains_internal_signal_language`.
- updated outreach copy tests for American International Clinic Singapore, Amaris B. Clinic, Amazing Hearing Group, Sree Narayana Mission, Assisi Hospice, and generic B2B rows so final email bodies must not contain `signals`.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, workflow JSON parse, and `python3 -m pytest tests/test_outreach_planner.py -q` with `37 passed`.
- no deployment was performed by this patch step, no emails were sent, and Instantly was not used.
- `2026-05-05 22:27 +08`: refined HIA cold-email copy after first-10 preview QA.
- final email bodies no longer use prospect-facing HIA batch wording (`Batch 1`, `Batch 2`, `Batch 3`, `Sep 2027`, `Sep 2028`, `Mar 2030`, or `HIA window`); internal classification fields still retain batch guesses for audit/use.
- added segment-specific HIA observations, problems, diagnostics, assets and CTAs for GP/family clinics, aesthetic clinics, dental, pharmacy, diagnostic/lab, specialist clinics, hearing care, allied health, psychology and long-term care.
- hearing-care evidence now keeps rows out of `not_ready` when concrete hearing tests/audiology/hearing-aid/appointment evidence exists; generic non-healthcare lab evidence no longer forces HIA diagnostic classification.
- Email 3 funding copy now still uses `funding_claim_line` but adds the funding-only line: `The useful first step is confirming whether the route applies before spending time on readiness work.`
- audit reports now include `contains_hia_batch_wording`, `asset_offer_too_generic_for_segment`, and `email_2_generic_hia_diagnostic` booleans for preview/review.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, workflow JSON parse, and `python3 -m pytest tests/test_outreach_planner.py -q` with `41 passed`.
- generated a local dry preview with representative first-10 rows only; no live rows were patched, no deployment was performed, no emails were sent, and Instantly was not used.
- `2026-05-06 12:38 +08`: refined the non-HIA PDPA safeguards track.
- PDPA copy now leads with the legal responsibility to protect personal data, then positions Cyber Essentials as a practical control/evidence baseline for the security-safeguards side rather than PDPA compliance.
- customer-trust/B2B copy keeps the procurement-proof angle: reusable evidence for access control, backups, patching, malware protection and incident response without rebuilding answers for every customer review.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, workflow JSON parse, and `python3 -m pytest tests/test_outreach_planner.py -q` with `47 passed`.
- docs updated with the PDPA/Cyber Essentials framing; no deployment was performed by this patch step, no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-06 13:18 +08`: added the low/no-human-review automation decision layer for cold-email planning.
- planner now emits `automation_decision`, reason, blockers, contact-send mode, Email 3 mode, enrichment/copy quality scores, severe flags and final send-gate status.
- hard contact suppression, unresolved personal-email skip, funding value fallback, deterministic LLM-drift fallback and draft-only QA decision mapping were added.
- workflow audit output and outreach column installer were updated for the new fields; no send node was added.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, workflow JSON parse, and focused pytest suites `63 passed`.
- no deployment was performed, no live rows were patched, no preview was generated, no emails were sent, and Instantly was not used.
- `2026-05-06 13:47 +08`: hardened the low/no-human-review automation gates before deployment.
- missing `validated_email` now suppresses by default outside `copy_qa_mode`; named-person greetings require medium/high identity confidence; generic inboxes stay team-level.
- funding Email 3 now requires at least one matched `verified_current` programme and exact-percentage permission where exact percentages appear; otherwise Email 3 uses the non-funding value fallback.
- split advisory enrichment/copy flags from true automation blockers, added `automation_advisory_flags_json` and `contact_identity_confidence`, and cleaned duplicate send-mode handling.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/funding_programs.py scripts/ensure_rayn_outreach_columns.py`, workflow JSON parse, focused pytest suites `67 passed`, and audit export test `1 passed`.
- attempted the contact/audit pytest subset; `tests/test_contact_candidate_verifier.py` could not collect locally because `captcha_solver` is not installed in this shell.
- no deployment was performed, no live rows were patched, no preview was generated because local NocoDB/DATABASE credentials were unavailable, no emails were sent, and Instantly was not used.
- `2026-05-06 14:03 +08`: polished fallback Email 3 and HIA problem copy.
- value-fallback Email 3 now reuses the row's selected asset/checklist/map instead of generic checklist wording.
- HIA Email 1 problem sentence now separates records/systems from controls so it reads less like one long list.
- local validation passed: `python3 -m pytest tests/test_outreach_planner.py tests/test_outreach_columns.py tests/test_outreach_audit_export.py -q` with `68 passed`.
- no deployment was performed, no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-06 16:30 +08`: deployed contact fallback order update commit `8e59cde` to Railway service `n8n-rayn-workflows`; deployment `f33397fc-83f5-45bd-9510-2e2348a8538c` reached `SUCCESS`.
- contact search now runs official-site preflight first, then Anymail decision-maker, then Anymail company-email, then Serper role search only if the Anymail fallbacks fail.
- company-email identity proof is capped to one Serper query; row `287` post-deploy dry-run used one unique identity query and partially proved `Jessica Choo` for `jessicachoo@apaxmedical.com`.
- live `/health` returned HTTP 200 and `/contact-provider-health` returned provider order `serper`.
- local validation passed before deploy: compile checks for `contact_enrichment.py`, `outreach_planner.py`, and `app.py`; focused contact/outreach/audit tests `88 passed`.
- post-deploy dry-runs did not patch NocoDB; no emails were sent and Instantly was not used.
- `2026-05-06 16:54 +08`: refined cold-email copy tracks after commit `8e59cde`.
- preserved the simple greeting rule: use `Hi {{first_name}},` when `selected_contact_name` is present, otherwise `Hello team,`; send-mode confidence does not complicate greeting selection.
- updated the local `wf-cold-email-planner.json` OpenRouter prompt rule to match the same simple greeting rule.
- strengthened HIA subtype copy for heart/cardiology, pain management, surgical, dermatology, eye/ophthalmology and home-care/caregiver rows, and kept family-clinic rows on the GP/family-clinic path unless strong lab evidence exists.
- added PDPA variants for education/training, HR/recruitment, accounting/finance/admin, retail/e-commerce, NPO/social service and non-clinical lab/testing; DPO/ops copy now focuses on scattered evidence across operations, HR, IT and vendors.
- added customer-trust variants for SaaS/platform, professional services, HR/recruitment B2B, outsourcing/vendor and education/training B2B rows, plus shorter track-specific subject lines.
- cleaned suppressed-row audit markdown so suppressed rows show the reason, OpenRouter skipped and emails not generated without noisy copy-quality flags unless debug mode is used.
- local validation passed: Python compile for `services/crawl4ai/outreach_planner.py` and `scripts/export_outreach_audit_markdown.py`, `jq -e wf-cold-email-planner.json`, and pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, `tests/test_outreach_audit_export.py` with `81 passed`.
- preview was not generated: local NocoDB credentials were not available in this shell; `railway variables --json` for the linked service exposed only NocoDB service URL metadata, not a NocoDB API token. No fake preview was produced.
- committed as `6349af4` (`Improve cold email track copy`), pushed branch `codex/n8n-workflow-checkpoint`, and deployed Railway service `Primary`; deployment `195599e3-c81d-4c7d-a198-9077f51c7e95` reached `SUCCESS`.
- post-deploy `/health` returned `{"status":"ok"}` and `/contact-provider-health` returned provider order `serper`.
- no live rows were patched, no emails were sent, Instantly was not used, and workflow remains draft-only.
- `2026-05-06 18:28 +08`: deployed cold-email planner fixes to the actual Railway app service `n8n-rayn-workflows`.
- corrected the live target from the linked n8n `Primary` service to `n8n-rayn-workflows`; worker deployments `d63bfa70-aa26-488e-8b8f-ff899695af1f`, `fe001c3b-38a6-4687-b460-a90730b1d243`, and `23fbd56b-f629-4ee7-9239-e367210d04ca` reached `SUCCESS`.
- added healthcare routing fixes for rheumatology, endocrinology, gastroenterology/digestive, psychology/mental-health, family/GP, diagnostic/radiology and broad `heart`/`specialist` false positives.
- final live draft-only run fetched 47 completed rows and patched 47 draft-field rows through `/outreach-plan`; it did not call OpenRouter directly and did not call Instantly.
- final counts: `auto_send_eligible=33`, `suppressed=9`, `auto_skipped=5`; `hia_regulatory=44`, `pdpa_safeguards=2`, `not_ready=1`; `named_person=21`, `generic_team=17`, `suppressed=9`; `email_3_mode`: `funding=25`, `value_fallback=22`.
- final audit checks found no mechanical anomalies: suppressed/skipped rows had empty email bodies and `skip_openrouter=true`, funding wording only appeared where `email_3_mode=funding`, and value-fallback Email 3 included the selected asset.
- audit artifacts exported locally: `/tmp/cold-email-live-draft-all-summary.json` and `/tmp/cold-email-live-draft-all-audit.md`.
- validation passed before deploy: Python compile for changed Python files, `jq -e wf-cold-email-planner.json`, and focused pytest suites with `83 passed`.
- live rows were patched only with draft outreach/audit fields; no emails were sent, Instantly was not used, and no rows were marked sent.
- `2026-05-06 20:28 +08`: moved the funding/value-fallback follow-up from Email 3 into Email 2, and moved the diagnostic follow-up into Email 3.
- funding safety gates remain unchanged: Email 2 uses funding copy only when `email_3_mode=funding`; otherwise Email 2 uses the selected non-funding checklist/evidence asset.
- updated the local n8n OpenRouter prompt and `Collect NocoDB Patches` fallback so any funding repair updates `email_2_body` and `email_sequence_json.email_2`, not Email 3.
- Email 3 now carries the access/data mapping/vendor/backup/incident diagnostic and quality flags were renamed around the new structure (`email_3_not_diagnostic`, `email_2_not_funding_only`, `email_2_missing_funding_claim_line`).
- local validation passed: Python compile for `services/crawl4ai/outreach_planner.py` and `scripts/export_outreach_audit_markdown.py`, `jq -e wf-cold-email-planner.json`, and focused pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, `tests/test_outreach_audit_export.py` with `83 passed`.
- no deployment was performed, no live rows were patched, no preview was generated, no emails were sent, and Instantly was not used.
- `2026-05-06 21:03 +08`: added `email_2_mode` and `funding_followup_mode` while keeping `email_3_mode` as a legacy alias for funding/value-fallback compatibility.
- removed signature/signoff blocks from deterministic email bodies and from the n8n funding fallback repair; LLM drafts are sanitized so trailing `Best` / `SK` / `RAYN Secure` signature blocks are stripped before patch construction.
- Email 3 remains a reply-style diagnostic follow-up with no greeting and no signoff/signature; the preview showed `32` non-empty Email 3 bodies with `no_greeting` and `no_signature`, plus `15` empty Email 3 bodies for suppressed/skipped rows.
- generated read-only draft-only preview artifact `docs/workflow/cold-email-preview-latest-50.md`; only `47` matching completed rows were available from the live NocoDB selector. No rows were patched.
- preview counts: `automation_decision={auto_send_eligible:32,suppressed:9,auto_skipped:6}`, `email_2_mode={funding:25,value_fallback:22}`, `funding_followup_mode={funding:25,value_fallback:22}`, legacy `email_3_mode={funding:25,value_fallback:22}`, anomalies `{}`.
- local validation passed: Python compile for `services/crawl4ai/outreach_planner.py`, `scripts/export_outreach_audit_markdown.py`, and `scripts/ensure_rayn_outreach_columns.py`; `jq -e wf-cold-email-planner.json`; focused pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, `tests/test_outreach_audit_export.py` with `84 passed`.
- no deployment was performed, no live rows were patched, no OpenRouter call was made during preview, no emails were sent, and Instantly was not used.
- `2026-05-07 00:37 +08`: fixed live outreach schema drift after the full draft-only rerun.
- added `human_review_status:not_required` to the outreach column installer and added bounded Postgres connection/query timeouts so production schema checks do not hang indefinitely over the Railway public proxy.
- ran `scripts/ensure_rayn_outreach_columns.py` against production Postgres using the Railway `Postgres` service public URL; it created the missing live columns `email_2_mode`, `funding_followup_mode`, `enrichment_quality_score`, `enrichment_quality_flags`, `copy_brief_quality_score`, `copy_brief_quality_flags`, and `severe_email_flags`, plus missing select options including `human_review_status:not_required`.
- restarted the live `nocodb` service to refresh its schema cache; NocoDB API verification then recognized `email_2_mode`, `funding_followup_mode`, and the quality fields.
- verified the live cold-email workflow path with suppressed row `278`: `POST /webhook/rayn-cold-email-planner` fetched the row, skipped OpenRouter, patched `human_review_status=not_ready`, `email_2_mode=funding`, `funding_followup_mode=funding`, kept email bodies empty, and kept `email_send_ready=false`.
- repaired stale enrichment timeout writebacks from the earlier remote public-enrich attempt by restoring 47 rows to `status=completed` and row `306` to `status=skipped` with `skipped_challenge_detected`.
- backfilled the 47 completed rows with deterministic draft-only planner patches after the schema fix; final live counts: `automation_decision={auto_send_eligible:36,suppressed:9,auto_skipped:2,blank:3}`, `human_review_status={not_required:36,not_ready:11,blank:3}`, `email_2_mode={funding:30,value_fallback:17,blank:3}`, `funding_followup_mode={funding:30,value_fallback:17,blank:3}`.
- final live safety check: `email_send_ready_true=0`, `final_send_gate_passed_true=36`, no auto-send-eligible rows were missing email bodies, and no suppressed rows had email bodies.
- local validation passed: Python compile for `scripts/ensure_rayn_outreach_columns.py` and `services/crawl4ai/outreach_planner.py`; `jq -e wf-cold-email-planner.json`; focused pytest suites `tests/test_outreach_columns.py`, `tests/test_outreach_planner.py`, `tests/test_workflow_audit_fallback.py`, and `tests/test_outreach_audit_export.py` with `85 passed`.
- no emails were sent, Instantly was not used, and no rows were marked sent.
- `2026-05-07 01:12 +08`: added controlled rotating subject/body variants for cold-email drafts.
- added an approved deterministic variant bank in `services/crawl4ai/outreach_planner.py` for `hia_regulatory`, `pdpa_safeguards`, `dpo_evidence`, and `customer_trust`, with segment-specific subjects and Email 1-4 variants.
- selection uses a stable SHA-256 seed from row id, campaign id and email step; rows without a stable id use variant `A` for predictable local previews.
- variant metadata is stored only behind the scenes in `email_sequence_json.variant_metadata`; no new visible NocoDB variant columns were added.
- variation keeps the same copy brief and compliance gates: Email 1 keeps the company observation/problem/mechanism/CTA order, Email 2 remains funding-only only when funding gates pass, Email 3 stays diagnostic, and no signatures/signoffs are added.
- added tests confirming every rotated A/B/C body path passes the same quality gate guardrails and that variant metadata is not exposed as patch-level fields.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and focused pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, and `tests/test_outreach_audit_export.py` with `90 passed`.
- no preview was generated, no deployment was performed, no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-07 01:43 +08`: tightened HIA variant QA after the 47-row read-only preview found generated HIA rows carrying profile/diagnostic flags while still passing `final_send_gate_passed`.
- inspected rows `280,284,292,293,295,296,301,307,308,315,321`; their Email 1 copy already contained the intended clinic profile phrase, so `email_1_missing_clinic_profile` was a false-positive validator for specialist rows.
- changed HIA Email 3 generation to reuse the same segment record phrase as Email 1 and ask who owns access, how backups work, and who handles incidents; aligned HIA diagnostic validation to the same record phrase.
- promoted `email_1_missing_clinic_profile`, `email_3_missing_hia_segment_terms`, and `email_3_not_hia_segment_diagnostic_shape` to severe flags so they block the final send gate if they ever remain after deterministic fallback.
- refreshed a read-only local live preview for the 47 completed rows; generated rows now had `0` email quality flags and no Email 2 subject/body mode mismatches. Suppressed/skipped rows still preserve raw empty-email quality flags for audit/debug.
- generated local fixture previews for missing live tracks: `5` PDPA, `5` customer_trust, and `3` DPO rows; all fixture rows had empty quality flags and passed their final gates.
- artifacts: `/tmp/cold-email-variant-preview-50-after-hia-fix.json`, `/tmp/cold-email-missing-track-fixtures.md`, and `/tmp/cold-email-missing-track-fixtures.json`.
- local validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and focused pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, and `tests/test_outreach_audit_export.py` with `92 passed`.
- no deployment was performed, no live rows were patched, no OpenRouter call was made, no emails were sent, and Instantly was not used.
- `2026-05-07 10:31 +08`: deployed the HIA diagnostic QA gate fix to Railway worker service `n8n-rayn-workflows`.
- worker deployments `c574b368-4c96-49d3-be3c-e6b80a03c02a` and cleanup deployment `65d58d53-ff60-4654-878a-00c3151164b4` reached `SUCCESS`; `/health` returned OK.
- cleaned non-send planner patches so suppressed/auto-skipped rows with no generated bodies keep blockers/severe flags behind the scenes but expose `email_quality_flags=[]` for the visible QA column.
- ran the live completed-row draft-only patch directly through deployed `/outreach-plan` with `draft_only=true` and `enforce_contact_gates=true`; selector returned and patched `47` rows.
- final live audit counts: `automation_decision={auto_send_eligible:36,suppressed:9,auto_skipped:2}`, `automation_decision_reason={auto_send_all_gates_passed:23,funding_claim_not_safe_used_value_fallback:13,suppressed_missing_validated_email:9,weak_hia_and_pdpa_evidence:1,copy_failed_after_llm_and_deterministic_fallback:1}`, `final_send_gate_passed={true:36,false:11}`, `email_2_mode={funding:30,value_fallback:17}`.
- final audit passed: `email_quality_flags` blank for all 47 rows, no final-gate rows had severe flags, suppressed rows had no email bodies, value-fallback Email 2 bodies had no funding wording, funding Email 2 bodies used programme-confirmation wording, and Email 3 bodies were diagnostic and segment-specific.
- artifacts: `/tmp/cold-email-live-direct-draft-patch-47-clean.json` and `/tmp/cold-email-live-draft-audit-47-clean.json`.
- validation passed before deployment: `python3 -m py_compile services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and focused pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, and `tests/test_outreach_audit_export.py` with `92 passed`.
- no emails were sent, Instantly was not used, and no rows were marked sent.
- `2026-05-07 11:45 +08`: made the cold-email OpenRouter path opt-in and removed pre-planner contact suppression filtering locally.
- `wf-cold-email-planner.json` now sends rows through `/outreach-plan` by default and only enters the OpenRouter branch when `use_llm=true` is explicitly present in the webhook payload, while keeping `openrouter_allowed` and `skip_openrouter` as secondary gates.
- `Rows To Items` no longer drops `do_not_contact`, unsubscribed, bounced or complained rows before the planner; those rows can now be deterministically suppressed by `/outreach-plan` and patched with the reason.
- `/outreach-validate-email` now returns the deterministic fallback patch unchanged when LLM validation rejects or fails, avoiding partial mutation of `automation_decision`, `final_send_gate_passed`, severe flags, blockers or send readiness.
- investigated live rows `316` and `320` read-only: row `316` is still a true `auto_skipped` weak-evidence/scrape-depth issue; row `320` was a classifier bug where a bare `fertility` term and aesthetic precedence pushed a family clinic away from GP/HIA copy.
- fixed the row `320` family-clinic route so weak fertility wording does not override family-clinic evidence, while strong aesthetic-clinic rows still use the medical/aesthetic profile and diagnostic copy.
- local validation passed: `python3 -m py_compile services/crawl4ai/app.py services/crawl4ai/outreach_planner.py`, `jq -e wf-cold-email-planner.json`, and focused pytest suites `tests/test_outreach_planner.py`, `tests/test_outreach_columns.py`, `tests/test_workflow_audit_fallback.py`, and `tests/test_outreach_audit_export.py` with `96 passed`.
- no deployment was performed, no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-07 11:38 +08`: committed and pushed `7d08ae7` (`Make cold email LLM opt-in`) to `codex/n8n-workflow-checkpoint`.
- deployed worker service `n8n-rayn-workflows`; Railway deployment `94eed1db-e2ac-457b-832b-3d013fe052b4` reached `SUCCESS`, and live `/health` returned OK.
- updated live n8n workflow `HbTPGELQQr9DRdAb` from `wf-cold-email-planner.json`; workflow stayed active and draft-only. A backup of the previous workflow JSON was saved locally at `/tmp/n8n-workflow-HbTPGELQQr9DRdAb-before-7d08ae7.json`.
- triggered the live cold-email workflow with `force=true` and `limit=50`, without `use_llm`; execution `23581` completed successfully with `47` planner patches, `47` NocoDB patch items, and `0` OpenRouter node runs.
- final live patch counts across the `47` completed rows: `automation_decision={auto_send_eligible:37,suppressed:9,auto_skipped:1}`, `automation_decision_reason={auto_send_all_gates_passed:24,funding_claim_not_safe_used_value_fallback:13,suppressed_missing_validated_email:9,weak_hia_and_pdpa_evidence:1}`, `contact_send_mode={named_person:18,generic_team:20,suppressed:9}`, `email_2_mode={funding:30,value_fallback:17}`, `final_send_gate_passed={true:37,false:10}`, and `email_send_ready={false:47}`.
- row `316` remains correctly blocked as `auto_skipped / weak_hia_and_pdpa_evidence`; row `320` now patches as `auto_send_eligible`, `hia_service_type_guess=GP_OMS`, `final_send_gate_passed=true`, and `email_quality_flags=[]`.
- post-patch anomaly check found no suppressed rows with email bodies, no final-gate rows with severe flags, and no rows with `email_send_ready=true`.
- no emails were sent, Instantly was not used, and no rows were marked sent.
- `2026-05-07 12:08 +08`: hardened the cold-email LLM path and removed workflow-side email body mutation locally.
- `wf-cold-email-planner.json` now requires `use_llm=true`, `openrouter_allowed=true`, `ALLOW_COLD_EMAIL_LLM=true`, and `skip_openrouter!=true` before entering the OpenRouter branch.
- `Collect NocoDB Patches` no longer repairs or rewrites funding Email 2 copy; the planner is the only source of truth for final email bodies and flags.
- the cold-email fetch includes `attempt_count`, and `/outreach-plan` now returns `retry_enrichment_once` for first-pass weak/not-ready enrichment, including healthcare-looking rows that need deeper healthcare pages; after retry it returns `auto_skipped`.
- local validation only; no deployment was performed, no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-07 15:10 +08`: added an opt-in cold-email LLM humaniser layer locally.
- deterministic `/outreach-plan` remains the source of truth for tracks, funding/value fallback, HIA relevance, suppression, `automation_decision`, `final_send_gate_passed`, and `email_send_ready`; OpenRouter can only humanise already-approved deterministic bodies.
- `wf-cold-email-planner.json` now requires `use_llm=true`, `use_llm_humaniser=true`, `ALLOW_COLD_EMAIL_LLM=true`, `openrouter_allowed=true`, `skip_openrouter!=true`, `automation_decision=auto_send_eligible`, `final_send_gate_passed=true`, deterministic bodies, and passing enrichment/copy scores before the OpenRouter branch.
- `/outreach-validate-email` now revalidates humanised JSON through deterministic gates; rejected LLM output falls back to the deterministic patch with rejection metadata stored in `email_sequence_json.metadata`, and a failed deterministic fallback becomes `auto_skipped / copy_failed_after_llm_and_deterministic_fallback`.
- added read-only preview tooling at `scripts/preview_cold_email_humaniser.py` for deterministic vs final accepted body inspection; without a rows export it prints the exact later command instead of faking a live preview.
- validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/app.py scripts/preview_cold_email_humaniser.py`, `jq -e . wf-cold-email-planner.json`, `python3 -m pytest tests/test_outreach_planner.py -q` (`78 passed`), `python3 -m pytest tests/test_outreach_columns.py -q` (`18 passed`), and `python3 -m pytest tests/test_workflow_audit_fallback.py tests/test_outreach_audit_export.py -q` (`6 passed`).
- no deployment was performed, no live rows were patched, no preview was generated from live credentials, no emails were sent, and Instantly was not used.
- `2026-05-07 15:35 +08`: ran a five-row read-only humaniser slice using NocoDB rows `273`, `275`, `276`, `278`, and `288`.
- local planner gates were correct: rows `273`, `275`, `276`, and `288` were `auto_send_eligible` with `openrouter_allowed=true`; row `278` was `suppressed_missing_validated_email` with `openrouter_allowed=false`.
- mock accepted humaniser JSON preserved `auto_send_eligible`, `final_send_gate_passed=true`, and blank quality flags for all four eligible rows.
- mock bad humaniser JSON containing forbidden PDPA-compliance wording was rejected and cleanly fell back to deterministic copy, preserving `auto_send_eligible` and `final_send_gate_passed=true` with rejection metadata in `email_sequence_json.metadata`.
- attempted real OpenRouter calls for the eligible slice returned `HTTP 401 Unauthorized`, so no real humanised copy was accepted in this test; no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-07 16:02 +08`: used the existing live n8n `openrouter` credential via a temporary isolated webhook workflow, not the cold-email patch workflow.
- the temporary workflow called only OpenRouter and had no NocoDB or Instantly nodes; it was deactivated and deleted after testing.
- the credential-backed test confirmed OpenRouter works through n8n. Initial full humaniser prompt calls for rows `273`, `275`, `276`, and `288` all returned JSON but were rejected by the deterministic validator and safely fell back to deterministic copy; row `278` stayed suppressed and did not call OpenRouter.
- tightened the humaniser prompt to require light edits only and explicit preservation of copy-brief personalisation, problem, mechanism, CTA, funding mode, HIA diagnostic shape, and Email 4 asset reference.
- after prompt tightening, credential-backed real LLM output was accepted for rows `275` and `288`; rows `273` and `276` were still rejected and safely fell back to deterministic copy. All final accepted/fallback patches kept blank quality/severe flags and `final_send_gate_passed=true` for eligible rows.
- OpenRouter usage recorded by the provider for the real n8n credential tests was approximately `$0.1257` across `9` calls; no live rows were patched, no emails were sent, and Instantly was not used.
- `2026-05-07 16:20 +08`: switched the cold-email humaniser model in `wf-cold-email-planner.json` from `x-ai/grok-4.3` to `deepseek/deepseek-v4-flash` locally and updated the workflow model test.
- reran the same credential-backed five-row slice through a temporary isolated n8n webhook using the existing `openrouter` credential; the temporary workflow had no NocoDB or Instantly nodes and was deleted after testing.
- DeepSeek result: row `278` stayed suppressed and skipped OpenRouter; rows `275`, `276`, and `288` accepted humanised output; row `273` still rejected on the HIA Email 3 diagnostic-shape gate and safely fell back to deterministic copy.
- final outputs for all eligible rows kept `final_send_gate_passed=true`, blank visible quality flags, and blank severe flags.
- DeepSeek cost for the four-row eligible slice was approximately `$0.00263`, versus approximately `$0.0603` for the comparable tightened Grok slice; no live rows were patched, no emails were sent, and Instantly was not used.
- validation passed after the model switch: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/app.py scripts/preview_cold_email_humaniser.py`, `jq -e . wf-cold-email-planner.json`, `python3 -m pytest tests/test_outreach_columns.py -q` (`18 passed`), and `python3 -m pytest tests/test_outreach_planner.py -q` (`78 passed`).
- `2026-05-07 16:35 +08`: switched the cold-email humaniser model setting back from `deepseek/deepseek-v4-flash` to the previous `x-ai/grok-4.3` local workflow value after review showed little practical copy difference.
- the humaniser remains explicit opt-in only and deterministic output remains the default path; no deployment was performed, no live rows were patched, no emails were sent, and Instantly was not used.
- validation after switching back: `jq -e . wf-cold-email-planner.json` and `python3 -m pytest tests/test_outreach_columns.py -q` (`18 passed`).
- `2026-05-07 16:50 +08`: removed the cold-email OpenRouter rewrite/humaniser path locally.
- `wf-cold-email-planner.json` is deterministic-only again: `Generate Outreach Plan` now connects directly to `Collect NocoDB Patches`, and the `Prepare OpenRouter Email Draft`, `OpenRouter Email Draft`, `Merge OpenRouter Email Draft`, `Validate LLM Email Draft`, and `Copy Brief Ready?` nodes were removed.
- `Rows To Items` no longer reads or passes `use_llm`; `/outreach-plan` now always returns `openrouter_allowed=false` and `skip_openrouter=true`.
- removed the `/outreach-validate-email` app endpoint because the cold-email workflow no longer accepts LLM email drafts.
- validation passed: `python3 -m py_compile services/crawl4ai/outreach_planner.py services/crawl4ai/app.py`, `jq -e . wf-cold-email-planner.json`, `python3 -m pytest tests/test_outreach_columns.py -q` (`17 passed`), `python3 -m pytest tests/test_outreach_planner.py -q` (`75 passed`), and `python3 -m pytest tests/test_workflow_audit_fallback.py tests/test_outreach_audit_export.py -q` (`6 passed`).
- no deployment was performed, no live rows were patched, no OpenRouter call was made, no emails were sent, and Instantly was not used.
- `2026-05-10 13:25 +08`: simplified URL picking and reran a safe 23-row all-stage enrichment test after row `281` exposed a bad deterministic fallback URL.
- removed the URL-pick deterministic fallback override in `wf-worker.json`; the flow is now Serper first results -> LLM official-URL picker -> blank/skip if the LLM finds no official URL. Basic bad-candidate guards remain only to reject obvious listings/social/webmail/PDF-style picks, not to guess replacements.
- added no-maintenance captcha provider diagnostics/fallback support in `services/crawl4ai/captcha_solver.py`: provider order defaults to `2captcha,capsolver,capmonster`, with Capsolver and CapMonster only used when configured and needed. This keeps the normal path unchanged and reserves paid solvers for real challenge rows.
- tightened challenge detection and thin-content handling in `services/crawl4ai/public_web_enrichment.py`: bare `captcha`/`cloudflare` wording is no longer enough by itself, public webmail hosts are treated as non-org hosts, sparse page extraction now uses metadata and internal-link text, and healthcare/domain completion logic was broadened for short but clearly valid clinic/provider sites.
- hardened `scripts/rayn_selected_rerun.py` for live validation by adding `--contact-batch-size` and splitting contact reruns into bounded `/contact-enrich-batch` calls instead of one large batch.
- local validation before live checks passed: `jq -e . wf-worker.json` plus focused pytest suites `tests/test_url_picker_fallback.py`, `tests/test_public_web_enrichment.py`, `tests/test_captcha_solver.py`, and `tests/test_public_web_proxy.py` with `58 passed`.
- deployed the worker to Railway service `n8n-rayn-workflows` and updated live n8n workflow `BQEa6M2pKYmuEYMV` from `wf-worker.json`; the live workflow version after the URL-picker simplification was `3581b094-a69c-4ac8-af42-8d57bdcfc8fc`.
- row `281` proof after the fix: `Anchor Health Family Clinic` now ends as `skipped / no_official_url_found`, with `url_picked`, `homepage_root_url`, `canonical_domain`, and `best_url` blank. The bad `https://www.myfamilyclinic.com.sg/` pick was confirmed to be the removed deterministic fallback, not the LLM decision.
- safe live 23-row all-stage test ran on rows `273-295` with crawl limits `page_limit=8`, `page_timeout_ms=25000`, `enrich_concurrency=2`, `per_row_page_concurrency=2`, `contact_batch_size=5`, and draft-only planner gating.
- final 23-row result: `status={completed:10,url_picked:10,skipped:3}`, `contact_search_status={contact_found:8,pending:13,contact_not_found:2}`, `automation_decision={auto_send_eligible:7,blank:13,suppressed:2,auto_skipped:1}`.
- URL-pick quality result: row `281` stayed blank/skipped, row `285` also stayed blank/skipped, and no wrong replacement homepage was selected. Row `293` was the only real challenge/captcha skip (`https://www.arden.com.sg/`).
- scrape/cost signals from the 23-row run: `90` total recorded source pages, `123328` website-content characters, completed rows averaged `7` pages, thin-content rows averaged `1.9` pages, URL Serper result evidence totaled `192` results, contact provider/query attempts totaled `6`, and candidate-verifier evidence existed for `10` rows.
- remaining blocker: Stage 2 still leaves too many correct URLs at `url_picked / thin_content`, which blocks contact/planner for those rows. Next fix should target Stage 2 completion policy for valid multi-page healthcare sites; Capsolver should stay challenge-only, not normal flow.
- `2026-05-10 14:05 +08`: changed Stage 2 from evidence-gated completion to crawl-success-first completion for official URLs.
- `services/crawl4ai/public_web_enrichment.py` no longer returns `weak_retry_needed` / `weak_skipped` for sparse-but-successful crawls. Thin/weak signals such as `thin_content`, `no_services_detected`, `no_locations_detected`, `no_team_or_contact_page`, and `homepage_only` now stay as enrichment-quality reasons while the row still completes if the crawl succeeded. Hard blockers remain unchanged: no official URL, robots, real challenge/captcha, crawl failure, or enrichment error.
- updated the live workflow patch logic in `wf-worker.json` and `scripts/rayn_selected_rerun.py` so sparse successful crawls no longer map back to `url_picked`; completed sparse crawls now emit `status_reason` values like `enrichment_completed_thin_content`.
- local validation passed after the policy change: `jq -e . wf-worker.json` and focused pytest suites `tests/test_public_web_enrichment.py`, `tests/test_url_picker_fallback.py`, `tests/test_captcha_solver.py`, and `tests/test_public_web_proxy.py` with `58 passed`.
- deployed Railway worker service `n8n-rayn-workflows`; deployment `29778f40-6d2e-42e6-a4a6-828cf18a099b` reached `SUCCESS`, `/health` returned HTTP `200`, and live n8n workflow `BQEa6M2pKYmuEYMV` was updated from `wf-worker.json` to version `909ab817-eba3-4873-9a98-e2cd2130e810`.
- reran only the `10` previously blocked thin-content rows `276,277,279,280,282,283,284,289,290,291` with `--skip-reset --skip-url` so the test isolated Stage 2 behavior.
- before the rerun all `10` rows were `status=url_picked`, `contact_search_status=pending`, and had blank planner decisions.
- after the rerun all `10` rows were `status=completed`; `8` rows completed with `status_reason=enrichment_completed_thin_content`, and `2` rows (`282`, `291`) completed with `status_reason=enrichment_completed`.
- downstream effect after the same rerun: `contact_search_status={contact_found:8,contact_not_found:2}` and `automation_decision={auto_send_eligible:8,suppressed:2}`. No rows remained blocked at `url_picked`.
- contact details from the proof run: validated emails were found for `276,277,279,280,282,283,284,291`; `289` and `290` completed enrichment but stayed `suppressed_missing_validated_email`, which is the expected downstream gate rather than a crawl-stage failure.
- `2026-05-10 14:18 +08`: ran a full safe all-stage rerun across the current 50-row working set `273-322` after the Stage 2 crawl-success-first fix.
- the rerun reset all stages from scratch, triggered URL picking for all `50` rows, then ran public enrichment, contact enrichment in `9` bounded batches (`batch_size=5`), and the draft-only planner workflow.
- post-URL-pick result: `42` rows had official URLs and `8` were skipped immediately for `no_official_url_found` (`281,285,292,296,304,306,314,320`).
- post-public-enrichment result: `41 completed`, `1 skipped_challenge_detected` (`293` / `arden.com.sg`), and no rows remained stuck at `url_picked`. The Stage 2 fix held for sparse sites: thin-content rows now completed with reasons such as `enrichment_completed_thin_content`.
- final live state across the full 50 rows: `status={completed:41,skipped:9}`, `contact_search_status={contact_found:34,contact_not_found:7,pending:9}`, `automation_decision={auto_send_eligible:32,suppressed:7,auto_skipped:2,blank:9}`.
- final skipped rows were `281,285,292,293,296,304,306,314,320`. `293` was the only challenge/captcha skip; the other `8` were URL-pick skips with no official URL selected.
- final suppressed rows were `278,289,290,294,298,303,311`; these completed enrichment but had `contact_not_found` / `suppressed_missing_validated_email`.
- final auto-skipped rows were `288` and `305`.
- key positive outcome: the prior Stage 2 blocker is fixed. Rows that previously stalled at `url_picked / thin_content` now completed, flowed into contact search, and reached planner gating normally.
- key new regression exposed by the full reset: the simplified URL picker is now stricter than the prior live state and lost URLs for `292,296,304,306,320` in addition to the known hard misses `281,285,314`. Next fix should target URL-pick recall on legitimate official domains without reintroducing bad fallback guesses.
- `2026-05-10 14:55 +08`: fixed URL-picker recall with a small prompt-only change, keeping the LLM as the source of truth and not restoring deterministic fallback guessing.
- updated the URL picker prompt to accept close official-name variants when title/snippet confirms the same entity, and to accept hosted official pages such as WordPress only when company name, Singapore context, and contact/address/service evidence are present.
- kept deterministic parser guards unchanged: directories, reviews, profiles, social media, maps, job boards, news/articles, stock pages, PDFs, webmail, and third-party slug/profile pages are still rejected.
- local URL-picker regression tests passed: `python3 -m pytest tests/test_url_picker_fallback.py -q` (`20 passed`).
- updated live n8n workflow `BQEa6M2pKYmuEYMV` from `wf-worker.json`; new workflow version `40229bdf-1c5b-496a-a63b-c94ec9ca6f94`.
- reran URL-only for the five full-reset misses `292,296,304,306,320`; all five recovered to `status=url_picked`.
- picked URLs from the proof: `292=https://appletreemedicalsingapore.wordpress.com/`, `296=https://arise.com.sg/`, `304=https://www.caregivers.com.sg/`, `306=https://ashfordmedical.com.sg/`, `320=https://www.assureclinic.sg/`.
- finished the recovered rows through enrichment/contact/planner to avoid leaving live data half-reset: `292,296,304,320` completed; `306` reached `skipped_challenge_detected` on the Ashford site.
- final 50-row state after URL recall recovery: `status={completed:45,skipped:5}`, `contact_search_status={contact_found:37,contact_not_found:8,pending:5}`, `automation_decision={auto_send_eligible:35,suppressed:8,auto_skipped:2,blank:5}`. Remaining skipped rows: `281,285,293,306,314`.
- downstream note: URL recall is fixed, but the proof exposed separate non-URL issues that should not be mixed into this fix: `292` selected a WordPress system email (`comment-reply@wordpress.com`) during contact search, and `296` is non-healthcare but planner copy still treated it as healthcare/HIA.
