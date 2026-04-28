# Contact Search Design

This stage finds one validated person-specific outreach email for each enriched company.

Detailed implementation strategy: `docs/workflow/contact-search-strategy.md`.

## Goal

For each company with a usable `canonical_domain`, find the best senior or managerial contact who is publicly associated with the company, generate person-specific email permutations, validate them through No2Bounce, and store the first clearly deliverable email.

A contact-search success is not just a found name. It requires:

- a public person candidate.
- a relevant senior or managerial role.
- evidence that the person is associated with the company.
- a person-specific email at the company canonical domain.
- No2Bounce validation status accepted as deliverable.

If no deliverable person-specific email is found, write `contact_search_status = contact_not_found`.

## Non-Goals

Do not:

- use generic inboxes such as `info@`, `contact@`, `hello@`, `admin@`, `enquiry@`, `appointments@`, `clinic@`, or `reception@`.
- accept low-score accept-all, invalid, risky, unknown, spam, bounce, or timeout validation results.
- infer employment from weak mentions alone.
- scrape login-only pages, bypass access controls, submit forms, or run security probes.
- overwrite company URL enrichment fields.

## Candidate Priority Order

Search highest-value roles first and move down only when no deliverable email is found.

1. C-suite and owner roles: CEO, founder, owner, managing director, executive director, general manager.
2. Privacy, compliance, and security roles: DPO, data protection officer, compliance manager, risk manager, CISO, head of security, cybersecurity manager.
3. IT and technology roles: IT manager, head of IT, CTO, technology manager, systems manager.
4. Operations roles: operations manager, ops manager, clinic operations manager, practice manager.
5. Clinic leadership roles: clinic manager, clinical manager, medical director, head doctor, principal doctor.
6. Care and clinical management roles: head of nursing, nursing manager, clinical lead, care manager.

## Search Flow

For each eligible company:

1. Read `company_name`, `company_homepage_name`, `canonical_domain`, `best_url`, and `website_content`.
2. Run official-site preflight first against `website_content`.
3. If preflight finds a deliverable contact, stop and write the result immediately.
4. If preflight finds no usable person candidate, or the preflight candidate's emails are all rejected, run bundled OpenSERP queries with provider order `bing -> duckduckgo -> google`.
5. Store the normalized results for each attempted provider and query.
6. Extract candidate names, titles, source URLs, and snippets.
7. Validate company association using official-domain evidence, public profile text, search snippets, and fuzzy company-name matching.
8. Generate email permutations only for validated people.
9. Exclude preflight candidate names and already-rejected email permutations before fallback validation.
10. Progress candidate-by-candidate when emails are rejected: continue from candidate 1 to candidate 2 and onward until a capped search budget is exhausted.
11. Send generated emails to No2Bounce in small batches only after local person/domain checks pass.
12. Poll No2Bounce until completion or timeout.
13. Accept the first candidate with a `sendable` or `risky_sendable` result.
14. Stop searching once an accepted contact is found.
15. If validated candidates were found but every person-specific permutation was rejected, write `contact_search_reason = candidates_found_but_no_sendable_email`.
16. If all role buckets are exhausted with no validated person candidate, write `contact_search_status = contact_not_found`.

## Query Shape

Queries should stay simple and auditable. Examples:

- `{company_name} Singapore CEO`
- `{company_name} Singapore founder`
- `{company_name} Singapore DPO`
- `{company_name} Singapore data protection officer`
- `{company_name} Singapore IT manager`
- `{company_name} Singapore clinic manager`
- `{company_homepage_name} operations manager`
- `site:{canonical_domain} "data protection officer"`
- `site:{canonical_domain} "clinic manager"`

Do not require LinkedIn. Public LinkedIn snippets can be used as evidence, but login-gated pages must not be scraped.

## Email Permutations

Generate person-specific patterns in a bounded order:

1. For 2-token Western names, keep the standard sequence headed by `first.last`, `first`, `firstlast`, `f.last`, `firstl`, `flast`, `last.first`, and underscore or hyphen variants.
2. For 3- and 4-token source-order names, try source-order family-name patterns first, such as `family.givenall`, `family.giventail`, `familygivenall`, and `familygiventail`.
3. After the source-order pass, try Westernized tail-first variants such as `melvyn.tan` and `melvyntan` when the evidence supports that reading.
4. Cap generation at `8` permutations per candidate, `5` candidates per row, and `24` No2Bounce validations per row by default.

Normalize names by lowercasing, removing punctuation, stripping honorifics, and transliterating diacritics. Do not generate role or generic mailbox addresses.

## Validation Rules

No2Bounce is the validation authority.

Accept only:

- `sendable` person-specific emails.
- `risky_sendable` person-specific emails when No2Bounce reports `Deliverable/AcceptAll` with `finalScore >= 90` for a named person.

Reject:

- invalid, bad, bounce, spam, disposable, unknown, blocked, incomplete, and undeliverable results.
- low-score accept-all results.
- generic inbox addresses.
- emails on domains that do not match `canonical_domain`.

Use MX lookup only as a cheap precheck when DNS support is available. Do not perform direct SMTP probing.

OpenSERP timeout handling is deliberately conservative:

- a single provider timeout is recorded as an attempt-level failure only.
- timeout does not disable a provider on the first miss.
- a provider is temporarily disabled for timeout only after `3` recent timeouts inside a `180` second window.
- timeout cooldown is short (`90` seconds by default), while explicit CAPTCHA and circuit-open signals use longer cooldowns.
- provider health resets on a new `contact_search_run_id` so one poisoned batch does not suppress later runs indefinitely.

## Output Fields

Recommended contact-search fields:

- `contact_search_status`: `pending`, `processing`, `contact_found`, `contact_not_found`, `failed`, or `skipped`.
- `contact_search_reason`: concise terminal reason.
- `contact_search_started_at`: timestamp when contact search started.
- `contact_search_finished_at`: timestamp when contact search finished.
- `contact_search_run_id`: execution identifier.
- `contact_candidates_json`: ranked candidates and evidence.
- `contact_search_evidence_json`: queries, results, attempted role buckets, and extraction notes.
- `selected_contact_name`: accepted contact full name.
- `selected_contact_first_name`: accepted contact first name.
- `selected_contact_last_name`: accepted contact last name.
- `selected_contact_title`: accepted contact title.
- `selected_contact_role_bucket`: accepted role bucket.
- `selected_contact_role_priority`: accepted role priority number.
- `selected_contact_source_url`: strongest public source URL.
- `selected_contact_confidence`: numeric or High/Medium/Low confidence.
- `person_company_match_status`: `validated`, `weak`, or `rejected`.
- `email_candidates_json`: generated emails and validation outcomes.
- `validated_email`: accepted deliverable person-specific email.
- `email_validation_status`: accepted provider result.
- `email_validation_provider`: `no2bounce`.
- `email_validation_evidence_json`: No2Bounce request tracking, response summary, and accepted result.
- `permutation_pattern`: pattern that produced the accepted email.
- `discovered_at`: accepted contact timestamp.

Execution-level batch reconciliation lives in the n8n run output, not in the lead row. Each contact batch emits:

- `rows_selected`
- `rows_terminal_first_pass`
- `rows_stuck`
- `rows_recovered`
- `rows_terminal_final`
- `rows_non_terminal_final`

## Status Contract

The main enrichment `status` remains the row-level processing source of truth. Contact search should use `contact_search_status` for contact-stage outcomes so company enrichment results are not overwritten.

Contact terminal statuses:

- `contact_found`: selected person and deliverable email saved.
- `contact_not_found`: all approved role buckets were attempted and no deliverable person-specific email was found.
- `failed`: provider, parsing, or workflow error prevented a reliable result.
- `skipped`: row is not eligible, such as missing `canonical_domain` or duplicate row.

Do not output `needs_review` from contact search.

Current terminal reason split:

- `candidates_found_but_no_sendable_email`: validated candidates existed, but all person-specific permutations were rejected.
- `no_deliverable_person_specific_email_found`: no accepted email was found and no validated candidate reached a successful validation outcome.
- `search_provider_failed`: provider failures prevented a reliable search result and the row should stay retryable.

## Implementation Plan

1. Add contact-search columns to NocoDB.
2. Create a standalone contact-search branch or workflow after website enrichment is stable.
3. Select rows where company enrichment is complete, `canonical_domain` is present, and `contact_search_status = pending`.
4. Claim each row with `contact_search_status = processing` and contact run metadata.
5. Run role-priority OpenSERP searches with conservative rate limits and provider order `bing -> duckduckgo -> google`.
6. Extract and rank person candidates deterministically first.
7. Generate person-specific permutations.
8. Validate with No2Bounce.
9. Write one accepted contact or `contact_not_found` with full evidence.
10. Rerun a small fixed test set before scaling.

## Suggested Python Stack

Use a standalone Python worker if n8n nodes become hard to maintain:

- Python 3.11+.
- `httpx` for async HTTP.
- `tenacity` for retries.
- `selectolax` for fast HTML parsing.
- `rapidfuzz` for company-name matching.
- `pydantic` v2 for models.
- `typer` for CLI commands.
- `loguru` for structured logs.
- `aiolimiter` for rate limiting.
- `python-dotenv` for secrets.
- `pyyaml` for config.
- `uv` for dependency management.

Defer heavy dependencies such as `spaCy en_core_web_trf` until deterministic extraction fails on real samples. Use `dnspython` for MX prechecks only.
