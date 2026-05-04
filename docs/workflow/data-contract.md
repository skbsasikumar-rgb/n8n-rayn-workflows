# Data Contract

This document defines the rebuild contract for the lead enrichment table.

## Required Input Fields

- `company_name`: company or organisation name to enrich.

## Worker Output Fields

- `url_picked`: first-pass LLM-selected URL from the first 10 Google SERP results.
- `status`: queue-control source of truth. Only `pending` rows are normally eligible to run.
- `best_url`: clean official homepage root URL.
- `homepage_root_url`: same canonical homepage root used by downstream steps.
- `canonical_domain`: domain used for dedupe.
- `duplicate_of_id`: existing record ID when this row duplicates another canonical domain.
- `company_homepage_name`: company name found on the official site.
- `parent_company`: parent, owner, operator, manager, subsidiary parent, branch parent, brand group, or clinic network only when strong official-site evidence supports it.
- `parent_company_relationship`: relationship class when available; only `parent`, `owner`, `operator`, `managed_by`, `subsidiary_of`, `branch_of`, `brand_group`, and `clinic_network` may populate `parent_company`.
- `parent_company_confidence`: `High`, `Medium`, or `Low` confidence from strict parent-company verification.
- `parent_company_evidence`: official-site quote or schema evidence supporting the accepted parent.
- `affiliations_detected`: weak/non-parent affiliations such as memberships, accreditations, licensing bodies, training institutions, hospital appointments, partners, vendors, and locations.
- `rejected_parent_candidates`: extracted parent-like candidates rejected with reason codes.
- `parent_company_candidates_json`: extracted candidates considered by the parent-company verifier.
- `website_scrape`: compact website content for later extraction.
- `source_urls`: evidence URLs separated by ` | `.
- `search_evidence_json`: JSON evidence for search query, first 10 Google results, selected URL, and LLM reason.
- `confidence`: `High`, `Medium`, or `Low`.
- `notes`: concise explanation.
- `last_stage`: last completed stage.
- `last_error`: actionable error if any.

## Contact Search Fields

Contact search must use separate fields so company enrichment state is not overwritten.

- `contact_search_status`: one of `pending`, `processing`, `contact_found`, `contact_not_found`, `failed`, or `skipped`.
- `contact_search_reason`: concise reason for the current or terminal contact-search state.
- `contact_search_started_at`: timestamp when contact search was claimed.
- `contact_search_finished_at`: timestamp when contact search reached a terminal state.
- `contact_search_run_id`: contact-search execution identifier.
- `contact_candidates_json`: ranked public person candidates and evidence.
- `contact_search_evidence_json`: optional future field for attempted role buckets, search results, extraction notes, and stop reason.
- `selected_contact_name`: accepted contact full name.
- `selected_contact_role`: accepted role/title.
- `selected_contact_seniority`: accepted seniority bucket.
- `selected_contact_source_url`: strongest evidence URL.
- `selected_contact_linkedin_url`: accepted contact LinkedIn profile URL when the provider or public evidence supplies one.
- `selected_contact_confidence`: confidence for person-company match and role relevance.
- `email_candidates_json`: generated person-specific permutations and validation outcomes.
- `validated_email`: accepted deliverable person-specific email.
- `email_validation_status`: No2Bounce status for the accepted email.
- `email_validation_provider`: `no2bounce`.
- `email_validation_evidence_json`: No2Bounce tracking and response summary.

Do not create or accept generic inboxes for this stage. Do not output `needs_review`; use `contact_not_found` when no deliverable person-specific contact is found.

## Outreach Planning Fields

Create the cold-email planning columns with `scripts/ensure_rayn_outreach_columns.py`. The script updates the physical Postgres table, NocoDB column metadata, and the first grid view.

The outreach planner only creates drafts and review patches. It must not send email.

Core field groups:

- entity enrichment: `entity_type_guess`, `entity_type_confidence`, `singapore_registered_guess`, `uen_guess`, `employee_count_guess`, `sme_likelihood`, `npo_likelihood`, `charity_or_social_service_likelihood`, `entity_evidence_json`.
- pressure classification: `pressure_type`, `pressure_reason`, `outreach_trigger_signal`, `outreach_trigger_source_url`, `outreach_trigger_confidence`, `data_type_signal`, `problem_area`, `problem_hypothesis`, `value_asset_offer`.
- HIA enrichment: `hia_relevant`, `hia_relevance_score`, `hia_confidence`, `hia_scope_reason`, `hia_service_type_guess`, `hia_timeline_batch_guess`, `hia_deadline_claim_safe`, `hia_disclaimer_needed`, `hia_evidence_json`.
- PDPA / certification enrichment: `pdpa_relevant`, `pdpa_reason`, `personal_data_intensity`, `sensitive_data_likelihood`, `pdpa_safeguard_angle`, `recommended_first_cert`, `recommended_cert_path`, `certification_reason`, `certification_fit_score`, `certification_evidence_json`.
- funding enrichment: `funding_status`, `funding_relevant`, `primary_funding_program`, `funding_programs_matched_json`, `funding_programs_possible_json`, `funding_programs_not_applicable_json`, `funding_eligibility_basis`, `funding_claim_line`, `funding_cta_asset`, `funding_confidence`, `funding_last_checked_at`, `funding_source_urls_json`, `funding_human_review_required`.
- draft fields: `outreach_variant`, `email_1_subject`, `email_1_body`, `email_2_subject`, `email_2_body`, `email_3_subject`, `email_3_body`, `email_4_subject`, `email_4_body`, `email_sequence_json`, `email_quality_score`, `email_quality_flags`, `email_send_ready`, `human_review_status`.

Funding claims must come from `funding_claim_line`. `funding_status` must not become `verified_match` unless the programme catalogue source status is `verified_current`.

## Workflow Control Fields

Current supported fields:

- `status`: one of `pending`, `processing`, `completed`, `skipped`, `failed`, or `needs_review`.
- `status_reason`: stable row outcome or claim reason such as `processing:crawl`, `url_picked`, `duplicate_canonical_domain`, `enrichment_completed`, or `partial_crawl`.
- `run_id`: workflow execution identifier for the current or latest run.
- `processing_started_at`: timestamp when the row was claimed.
- `processing_finished_at`: timestamp when the row reached a terminal status.
- `last_attempted_at`: timestamp of the latest attempt.
- `attempt_count`: number of attempts recorded by the worker.
- `error_type`: stable technical or business error category.
- `error_message`: technical or business error detail.
- `retry_eligible`: `true` or `false` flag written by the worker.
- `source_row_created_at`: snapshot of the row `CreatedAt` at claim time.
- `source_row_updated_at`: snapshot of the row `UpdatedAt` at claim time.
- `last_stage`: technical pipeline stage such as `url_discovery`, `url_pick`, `dedupe`, `crawl`, `crawled`, `partial`, or `enrichment_error`.
- `last_error`: short actionable error or final skip reason.
- `notes`: human-readable evidence and status detail.

## Status Values

- `pending`: ready for worker.
- `processing`: claimed by worker.
- `completed`: completed with sufficient official evidence.
- `skipped`: intentionally not processed further, such as no official URL, duplicate domain, invalid URL, excluded category, or robots restriction.
- `failed`: attempted but failed because of a technical or provider error.
- `needs_review`: useful output exists but the result is ambiguous, partial, low confidence, or requires human review.

Do not write stage values such as `url picked`, `partial`, `skipped_url_validation_failed`, or `url duplicate` into `status`. Put those details in `last_stage`, `last_error`, and `notes`.

## URL Rules

- `best_url` must be a homepage root URL.
- Remove tracking parameters and fragments.
- Prefer registrable root domain when `www` or marketing subdomains are not essential.
- Keep a subdomain only when it is the official product or brand homepage.
- Never set `best_url` to a directory, social page, donation page, job page, marketplace, map page, or article.

## Duplicate Rules

If `canonical_domain` already exists on another row:

- set `status` to `skipped`.
- set `duplicate_of_id` to the existing row ID.
- skip website scraping and parent-company inference.
- keep enough notes to explain the duplicate match.

`canonical_domain` is derived from the selected URL, not from the raw company name. It removes protocol, path, query, fragment, port, credentials, and leading `www`, then stores the registrable root domain. Singapore suffixes such as `com.sg`, `org.sg`, and `net.sg` remain intact.

## Rerun Boundaries

URL discovery reruns may update `url_picked`, `canonical_domain`, `duplicate_of_id`, `search_evidence_json`, `status`, `status_reason`, `run_id`, processing timestamps, retry fields, `last_stage`, and `last_error`.

Enrichment reruns must preserve `url_picked` and must not call the Google SERP provider. They may update only downstream website fields such as `best_url`, `homepage_root_url`, `website_content`, `website_scrape`, `company_homepage_name`, `parent_company`, `source_urls`, `notes`, `confidence`, `status`, `status_reason`, `run_id`, processing timestamps, retry fields, `last_stage`, and `last_error`.

Contact-search reruns must preserve URL and company enrichment fields. They may update only contact-search fields, including candidates, selected contact, generated email candidates, No2Bounce validation evidence, and contact-search status fields.
