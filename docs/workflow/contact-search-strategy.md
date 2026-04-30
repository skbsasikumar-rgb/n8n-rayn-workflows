# Contact Search Strategy

This document turns the contact-search design into a build strategy for the next enrichment stage.

## Strategy Summary

Build contact search as a separate stage after company URL enrichment. Keep company enrichment stable and treat contact search as its own queue with its own status fields.

Target result per company:

- one best senior or managerial contact.
- one person-specific valid email.
- public evidence that the person is associated with the company.
- Anymail Finder person-lookup evidence.
- `contact_search_status = contact_found` or `contact_search_status = contact_not_found`.

Do not use generic inboxes. Do not write `needs_review` for contact search.

## Recommended Architecture

Use n8n for orchestration and a Python contact-search worker for the hard logic.

Reasoning:

- n8n is good for table selection, row claiming, provider credentials, and writeback.
- contact search needs ranking, retry control, candidate queues, person lookup, provider handling, and evidence normalization.
- those rules will become difficult to maintain as large JavaScript code blocks inside `wf-worker.json`.
- a Python worker lets us test the extraction and validation logic without constantly importing n8n workflow JSON.

Recommended flow:

```text
NocoDB pending contact rows
  -> n8n contact-search webhook trigger
  -> Python /contact-enrich-batch runner selects and claims one small batch
  -> worker claims each row as contact_search_status=processing
  -> worker runs official-site-only preflight
  -> write immediately if a deliverable official-site contact is found
  -> if preflight candidate emails are rejected, fall through to alternate-contact search
  -> worker executes OpenSERP provider cascade
  -> candidate extraction and ranking
  -> person-company validation
  -> Anymail Finder person lookup
  -> worker writes the terminal NocoDB contact result per row
```

The contact webhook now calls the Python batch runner directly instead of holding a multi-item n8n branch open. This keeps row claiming, fallback search, Anymail Finder lookup, and final writeback inside one row-level worker transaction.

## Eligibility Rules

A row is eligible for contact search only when:

- company enrichment `status = completed`.
- `canonical_domain` is present.
- `best_url` is present.
- `duplicate_of_id` is blank.
- `contact_search_status = pending`.

Rows should be skipped when:

- `canonical_domain` is blank.
- the row is a duplicate.
- company enrichment did not complete.
- the canonical domain is an excluded domain.

Skipped rows should write `contact_search_status = skipped` with `contact_search_reason`.

## Contact Status Lifecycle

Use a separate contact status lifecycle:

- `pending`: eligible for contact search.
- `processing`: claimed by the contact worker.
- `contact_found`: deliverable person-specific email found.
- `contact_not_found`: role buckets exhausted without a deliverable person-specific email.
- `failed`: provider or worker error prevented reliable completion.
- `skipped`: row is not eligible for contact search.

Contact search must not output `needs_review`.

## Provider Strategy

### Search

Primary implemented interface: worker-side `/contact-enrich-batch` row runner. It performs official-site preflight first, then Serper fallback inside the Python worker when public search is needed.

Provider adapter behavior:

1. n8n calls `/contact-enrich-batch` with a small `limit` and the worker selects eligible `pending` rows.
2. If preflight returns `preflight_contact_found`, write the contact result directly and spend zero search-provider queries for that row.
3. If preflight returns `preflight_no_person_candidate`, build bundled role queries and run Serper first.
4. If preflight returns `preflight_candidate_email_rejected`, run the same Serper fallback but exclude the preflight candidate names and rejected email candidates.
5. If preflight returns a validation provider failure or worker error, stop the row as `failed` and make it retryable. Do not call Serper.
6. Default fallback is `serper_emergency`; OpenSERP remains available only if explicitly listed in `CONTACT_SEARCH_PROVIDER_ORDER`.
7. Default paid-search budget is `3` role queries per row after preflight. Rows with official-site contacts spend zero Serper queries.
8. Do not convert provider failures into `contact_not_found`.
9. Stop the row as `failed` with `search_provider_failed` if every provider attempt fails.
10. Treat a single timeout as an attempt-level miss only. Do not disable a provider on the first timeout.
11. Timeout disable is threshold-based: temporarily disable only after `3` recent timeouts inside a `180` second window, using a short `90` second cooldown.
12. Explicit circuit-breaker signals disable only that provider immediately. The worker matches both `circuit_open` and messages such as `circuit breaker is open - engine temporarily disabled`.
13. Timeout-only provider state resets on a new row-level `contact_search_run_id`, while active circuit-breaker cooldowns survive the reset until they expire.
14. Every provider attempt stores `provider`, `query`, `result_count`, `provider_error`, `circuit_open`, `timeout`, `provider_disabled`, `provider_disabled_reason`, and `cooldown_seconds`.

### Email Validation

Validation authority: Anymail Finder person lookup.

Anymail Finder flow:

1. Send one `POST https://api.anymailfinder.com/v5.1/find-email/person` request per validated candidate.
2. Request body: `{ "domain": canonical_domain, "full_name": candidate_name }`.
3. Accept only `email_status = valid` with a populated `valid_email` on the exact `canonical_domain`.
4. Reject risky, blacklisted, not-found, wrong-domain, invalid, unknown, and provider-error outcomes.
5. Continue down the ranked candidate list until a valid email is found or the candidate cap is exhausted.
6. Store provider response, credit count, and candidate attempt order in `email_validation_evidence_json`.

### Email Discovery Libraries

Do not use third-party SMTP probing libraries for this stage. Use deterministic name filtering and Anymail Finder person lookup; do not generate generic inboxes.

Do not perform direct SMTP probing. No direct mailbox verification over ports `25`, `465`, or `587` is part of this workflow.
Keep provider routing simple and auditable.

## Role Queue Strategy

Process official-site content before spending search queries. If the official site yields a deliverable senior contact, finish there. If the official site yields a person but their generated emails are rejected, continue to alternate-contact OpenSERP search while excluding that same person from fallback validation. If no official-site contact is found, process role bundles in priority order.

1. C-suite and owner
   - CEO
   - Founder
   - Owner
   - Managing Director
   - Executive Director
   - General Manager
2. Privacy, compliance, and security
   - DPO
   - Data Protection Officer
   - Compliance Manager
   - Risk Manager
   - CISO
   - Head of Security
   - Cybersecurity Manager
3. IT and technology
   - IT Manager
   - Head of IT
   - CTO
   - Technology Manager
   - Systems Manager
4. Operations
   - Operations Manager
   - Ops Manager
   - Clinic Operations Manager
   - Practice Manager
5. Clinic leadership
   - Clinic Manager
   - Clinical Manager
   - Medical Director
   - Head Doctor
   - Principal Doctor
   - Doctor in charge
   - Senior Doctor
6. Care and clinical management
   - Head of Nursing
   - Nursing Manager
   - Clinical Lead
   - Care Manager
7. Admin and HR
   - Admin Manager
   - Administration Manager
   - Office Manager
   - HR Manager
   - Human Resources Manager
   - People Manager

All seven buckets remain eligible for candidate extraction and ranking. Serper fallback uses budgeted query bundles so the search covers every bucket without issuing one query per bucket. Candidate ranking still treats Admin and HR as the final bucket through `role_priority = 7`.

Stop once an accepted contact is found. Do not keep spending validation credits after success.

Candidate progression is bounded and explicit:

- continue from candidate 1 to candidate 2 and onward when Anymail Finder returns no valid same-domain email.
- cap at `3` validated candidates per row by default.
- run at most one Anymail Finder person lookup per candidate.
- if validated candidates existed but every Anymail lookup was rejected or not found, end as `contact_not_found / candidates_found_but_no_sendable_email`.

## Query Strategy

Keep queries simple and auditable.

Current live query builder uses four default queries in priority order:

1. Precise c-suite company query
   - company query: `("{company_name}" OR "{company_homepage_name}") Singapore ("CEO" OR "Founder" OR "Managing Director" OR "Executive Director" OR "General Manager")`
2. Official-domain people-page query
   - site query: `site:{canonical_domain} ("about us" OR "team" OR "leadership" OR "management" OR "founders" OR "doctors" OR "providers" OR "clinicians" OR "board" OR "trustees" OR "governance" OR "contact" OR "medical director" OR "operations manager" OR "DPO" OR "IT manager" OR "HR manager")`
3. Clinic leadership, operations, care clinical, admin, and HR bundle
   - company query: `("{company_name}" OR "{company_homepage_name}") Singapore ("Medical Director" OR "Principal Doctor" OR "Head Doctor" OR "Doctor in charge" OR "Senior Doctor" OR "Senior Consultant" OR "Clinical Lead" OR "Head of Nursing" OR "Nursing Manager" OR "Care Manager")`
4. Compliance, privacy, security, and IT bundle
   - company query: `("{company_name}" OR "{company_homepage_name}") Singapore ("DPO" OR "Data Protection Officer" OR "Compliance Manager" OR "Risk Manager" OR "CISO" OR "Head of Security" OR "Cybersecurity Manager" OR "IT Manager" OR "Head of IT" OR "CTO" OR "Technology Manager" OR "Systems Manager")`

If `website_content` has no official-site contact, cap the fallback row at four total queries and cover all seven buckets through the precise c-suite query, one official-domain people-page query, and two bundled role queries. If `website_content` is missing, allow up to six total queries so extra compliance/IT and operations/admin site-domain queries can be added. Do not over-normalize company names before querying. Use the table value first, then the homepage-derived name only when it adds a genuinely different brand string.

## Candidate Extraction Strategy

Create a candidate list from each role bucket.

Candidate record fields:

- `name`
- `first_name`
- `last_name`
- `title`
- `role_bucket`
- `role_priority`
- `source_url`
- `source_domain`
- `snippet`
- `evidence_text`
- `company_match_score`
- `role_match_score`
- `person_confidence`
- `rejection_reason`

Extraction should be deterministic first:

- parse `website_content` before spending search queries and treat official-domain senior doctor, doctor-in-charge, founder, owner, and management mentions as highest-value evidence.
- parse search result titles and snippets.
- parse official-domain pages when public and accessible.
- prefer official website, clinic team pages, about pages, leadership pages, professional directories, and public social snippets.
- de-rank archive/news/category pages that look like site labels rather than people.
- reject candidates without a plausible person name.

LLM use should be optional and narrow:

- only for normalizing ambiguous candidate snippets into structured name/title/evidence JSON.
- never for inventing missing people or emails.
- never for accepting a candidate without source evidence.

## Person-Company Validation

A candidate is validated only when at least one strong signal exists:

- official company domain page names the person.
- public profile snippet/title links the person to the company.
- source title/snippet contains both person name and company/homepage name.
- repeated independent public snippets link the same person to the same company.

Weak signals are not enough:

- person name appears near a similar company name only once.
- the page is an unrelated news/archive/category page.
- the person works in the same industry but company match is unclear.
- source is stale and contradicts newer evidence.

If no validated person is available, continue down the role queue.

## Person Lookup Strategy

Use Anymail Finder person lookup instead of generated permutations by default.

Default behavior:

1. Validate that a candidate is a probable human name, not a company, bank, clinic, group, or company-name fragment.
2. Send `{ "domain": canonical_domain, "full_name": candidate.name }`.
3. Accept only `email_status = valid` with a same-domain `valid_email`.
4. Store rejected `risky`, `blacklisted`, and `not_found` responses in evidence, then continue to the next candidate.

Hard exclusions:

- `info`
- `contact`
- `hello`
- `admin`
- `enquiry`
- `enquiries`
- `appointments`
- `clinic`
- `reception`
- `support`
- `sales`
- `marketing`
- `team`

## Credit-Control Strategy

Anymail Finder credits should be protected.

For each row:

1. validate person-company association before paid lookup.
2. reject non-human organization fragments before paid lookup.
3. look up only the highest-ranked validated candidate first.
4. stop immediately on accepted deliverable email.
5. only move to the next candidate when the current candidate has no `sendable` email.
6. cap candidates per row during tests.

Suggested first-test caps:

- max role buckets per row: 3.
- max queries per role bucket: 3.
- max candidates per row: 3.
- max Anymail Finder lookups per candidate: 1.
- max Anymail Finder lookups per row: 3.

Current worker behavior records candidate attempts, cache hits, Anymail Finder responses, and charged credits in `email_validation_evidence_json`.

Anymail Finder result handling:

- use `POST /v5.1/find-email/person` only after local person/domain filters pass.
- use a bounded request timeout; default worker timeout is `45` seconds and can be changed with `ANYMAILFINDER_TIMEOUT_SECONDS`.
- accept only `email_status = valid` and same-domain `valid_email`.
- treat provider timeout, 401, 402, or HTTP errors as retryable provider failures instead of false no-contact results.

Scale caps only after measuring hit rate and cost.

## Output Strategy

Write both accepted contact fields and full evidence.

When found:

- `contact_search_status = contact_found`
- `contact_search_reason = sendable_person_specific_email_found` or `risky_sendable_person_specific_email_found`
- `selected_contact_name`
- `selected_contact_first_name`
- `selected_contact_last_name`
- `selected_contact_title`
- `selected_contact_role_bucket`
- `selected_contact_role_priority`
- `selected_contact_source_url`
- `selected_contact_confidence`
- `person_company_match_status = validated`
- `validated_email`
- `email_validation_status`
- `email_validation_provider = anymail_finder`
- `discovered_at`
- `contact_candidates_json`
- `email_candidates_json`
- `contact_search_evidence_json`
- `email_validation_evidence_json`

When exhausted:

- `contact_search_status = contact_not_found`
- `contact_search_reason = no_deliverable_person_specific_email_found` when no validated candidate reaches a meaningful validation attempt.
- `contact_search_reason = candidates_found_but_no_sendable_email` when validated candidates existed but Anymail Finder returned no valid same-domain email.
- keep `contact_candidates_json` and `contact_search_evidence_json` for audit.
- leave `validated_email` blank.

When provider failure occurs:

- `contact_search_status = failed`
- `contact_search_reason = search_provider_failed` or `email_validation_provider_failed`.
- `retry_eligible = true` if a future rerun may succeed.

## Data Model Decision

Start with one accepted contact on the lead row. Store all candidates as JSON.

Reasoning:

- the current workflow is row-centric.
- the immediate goal is one best outreach contact per company.
- adding a separate contacts table is useful later, but it adds workflow complexity now.

Future split:

- `leads` table keeps selected/best contact fields.
- `lead_contacts` table stores all people candidates, role evidence, and validation attempts.
- `email_validation_attempts` table stores every Anymail Finder request/result.

Do this only after the first contact-search strategy proves useful.

## First Test Slice

Use a small set of rows with known variety:

- one clinic with obvious doctors/team page.
- one clinic with likely manager names in public search only.
- one larger group practice.
- one nonprofit/care provider.
- one company with no public people found.
- one duplicate/skipped row.

For each test row, report:

- role buckets attempted.
- search queries used.
- candidate count.
- top candidates.
- Anymail Finder lookups attempted.
- Anymail Finder outcomes and credits charged.
- terminal `contact_search_status`.
- reason for stopping.

For batch executions, also capture the reconciliation summary emitted by the workflow:

- `rows_selected`
- `rows_terminal_first_pass`
- `rows_stuck`
- `rows_recovered`
- `rows_terminal_final`
- `rows_non_terminal_final`
- `concurrency`

The Python batch runner processes rows concurrently when `CONTACT_BATCH_CONCURRENCY` or request `concurrency` is greater than `1`. Keep this conservative because each row can call Serper, the LLM verifier, and Anymail Finder.

## Build Phases

### Phase 1: Data Contract and Columns

- confirm NocoDB contact columns exist or create them.
- initialize eligible rows with `contact_search_status = pending`.
- document reset rules.

Verify:

- row selector can find exactly the pending contact rows.
- skipped/duplicate rows are not selected.

### Phase 2: Offline Contact Worker Prototype

- create a Python CLI or endpoint that accepts one row payload.
- implement role queue generation.
- call OpenSERP.
- normalize result objects.
- extract candidate people.
- write JSON output to stdout or a local fixture.

Verify:

- first 5 to 10 rows produce auditable candidate lists before any email validation spend.

### Phase 3: Anymail Finder Person Lookup

- implement name normalization.
- reject organization fragments and non-human names.
- call Anymail Finder with `full_name` and `domain`.
- parse accepted and rejected statuses.

Verify:

- generic inboxes are never selected.
- only Anymail Finder `valid` same-domain results are selected.
- validation evidence is stored.

### Phase 4: n8n Contact Workflow

- add a contact-search batch webhook or separate workflow.
- select `contact_search_status = pending` rows.
- claim rows before processing.
- call the Python contact worker.
- write terminal contact fields back to NocoDB.

Verify:

- claimed rows reconcile with terminal rows.
- reruns do not reprocess `contact_found` or `contact_not_found` rows unless manually reset.

### Phase 5: Scale Controls

- add conservative batch size.
- add provider rate limits.
- add max candidates and max email validations per row.
- add run summary.
- add stale `processing` recovery.

Verify:

- no row silently disappears.
- provider errors are separated from true `contact_not_found` results.

## LLM Candidate Verifier

The worker now verifies fallback raw candidates before Anymail Finder spend. Raw extracted phrases are not written as accepted candidates. They are stored as raw/rejected evidence first, and only verified human candidates are counted in `candidate_count` and `candidate_names`.

Verifier controls:

- `CONTACT_LLM_VERIFIER_ENABLED=true` enables the OpenRouter verifier.
- `CONTACT_LLM_VERIFIER_REQUIRED_FOR_FALLBACK=true` makes fallback fail closed when the verifier fails.
- `CONTACT_LLM_VERIFIER_MODEL` selects the strict verifier model.
- `CONTACT_LLM_VERIFIER_TIMEOUT_SECONDS` bounds verifier latency.

Fail-closed behavior:

- official-domain preflight can continue through deterministic checks when the verifier is unavailable.
- fallback search candidates must pass the LLM verifier before Anymail Finder when required mode is enabled.
- verifier errors write `contact_search_status = failed` and `contact_search_reason = candidate_verifier_failed`.

Evidence contract:

- `raw_candidate_count` counts extracted raw phrases.
- `verified_candidate_count` and `candidate_count` count accepted human candidates only.
- `candidate_names` and `verified_candidate_names` contain accepted human names only.
- `rejected_candidate_names` and `rejected_candidates` contain false positives such as organization names, title-only phrases, weak snippets, and already-tried people.
- `previously_tried_candidate_names` records official-site preflight candidates skipped during fallback.
