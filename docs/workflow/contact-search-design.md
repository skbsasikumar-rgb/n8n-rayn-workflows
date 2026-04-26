# Contact Search Design

This stage finds one validated person-specific outreach email for each enriched company.

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
- accept catch-all, invalid, risky, unknown, spam, bounce, or timeout validation results.
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
2. Build role-specific OpenSERP Google queries from the priority order.
3. Store the first-page public results for each attempted role bucket.
4. Extract candidate names, titles, source URLs, and snippets.
5. Validate company association using official-domain evidence, public profile text, search snippets, and fuzzy company-name matching.
6. Generate email permutations only for validated people.
7. Send generated emails to No2Bounce in small batches.
8. Poll No2Bounce until completion or timeout.
9. Accept the first candidate with a deliverable, non-catch-all result.
10. Stop searching once an accepted contact is found.
11. If all role buckets are exhausted, write `contact_search_status = contact_not_found`.

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

Generate person-specific patterns in this order:

1. `first.last@domain`
2. `first@domain`
3. `flast@domain`
4. `firstl@domain`
5. `first_last@domain`
6. `first-last@domain`
7. `last.first@domain`
8. `last@domain`
9. `f.last@domain`
10. `first.middle.last@domain`
11. `firstlast@domain`
12. `firstinitiallastname@domain`
13. `firstname_lastname@domain`

Normalize names by lowercasing, removing punctuation, stripping honorifics, and transliterating diacritics. Do not generate role or generic mailbox addresses.

## Validation Rules

No2Bounce is the validation authority.

Accept only:

- deliverable person-specific emails.
- validation evidence that does not identify the address as catch-all, invalid, bounce, spam, risky, or unknown.

Reject:

- catch-all results.
- invalid results.
- bounce/spam results.
- unknown, timeout, or provider-error results.
- generic inbox addresses.
- emails on domains that do not match `canonical_domain` unless explicitly approved later.

Use MX lookup only as a cheap precheck. Do not perform direct SMTP probing unless separately approved.

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

## Status Contract

The main enrichment `status` remains the row-level processing source of truth. Contact search should use `contact_search_status` for contact-stage outcomes so company enrichment results are not overwritten.

Contact terminal statuses:

- `contact_found`: selected person and deliverable email saved.
- `contact_not_found`: all approved role buckets were attempted and no deliverable person-specific email was found.
- `failed`: provider, parsing, or workflow error prevented a reliable result.
- `skipped`: row is not eligible, such as missing `canonical_domain` or duplicate row.

Do not output `needs_review` from contact search.

## Implementation Plan

1. Add contact-search columns to NocoDB.
2. Create a standalone contact-search branch or workflow after website enrichment is stable.
3. Select rows where company enrichment is complete, `canonical_domain` is present, and `contact_search_status = pending`.
4. Claim each row with `contact_search_status = processing` and contact run metadata.
5. Run role-priority OpenSERP searches with conservative rate limits.
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
