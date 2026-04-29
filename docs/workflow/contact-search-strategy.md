# Contact Search Strategy

This document turns the contact-search design into a build strategy for the next enrichment stage.

## Strategy Summary

Build contact search as a separate stage after company URL enrichment. Keep company enrichment stable and treat contact search as its own queue with its own status fields.

Target result per company:

- one best senior or managerial contact.
- one person-specific deliverable email.
- public evidence that the person is associated with the company.
- No2Bounce validation evidence.
- `contact_search_status = contact_found` or `contact_search_status = contact_not_found`.

Do not use generic inboxes. Do not write `needs_review` for contact search.

## Recommended Architecture

Use n8n for orchestration and a Python contact-search worker for the hard logic.

Reasoning:

- n8n is good for table selection, row claiming, provider credentials, and writeback.
- contact search needs ranking, retry control, candidate queues, email permutations, provider polling, and evidence normalization.
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
  -> email permutation generation
  -> No2Bounce validation
  -> worker writes the terminal NocoDB contact result per row
```

The contact webhook now calls the Python batch runner directly instead of holding a multi-item n8n branch open. This keeps row claiming, No2Bounce polling, fallback search, and final writeback inside one row-level worker transaction, so one slow validation cannot leave the whole n8n branch stuck in `processing`.

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
4. If preflight returns `preflight_candidate_email_rejected`, run the same Serper fallback but exclude the preflight candidate names and rejected email permutations.
5. If preflight returns a validation provider failure or worker error, stop the row as `failed` and make it retryable. Do not call Serper.
6. Default fallback is `serper_emergency`; OpenSERP remains available only if explicitly listed in `CONTACT_SEARCH_PROVIDER_ORDER`.
7. Default paid-search budget is `3` role queries per row after preflight. Rows with official-site contacts spend zero Serper queries.
8. Do not convert provider failures into `contact_not_found`.
9. Stop the row as `failed` with `search_provider_failed` if every provider attempt fails.
10. Treat a single timeout as an attempt-level miss only. Do not disable a provider on the first timeout.
11. Timeout disable is threshold-based: temporarily disable only after `3` recent timeouts inside a `180` second window, using a short `90` second cooldown.
12. Explicit CAPTCHA and circuit-breaker signals disable only that provider immediately. The worker matches both `circuit_open` and messages such as `circuit breaker is open - engine temporarily disabled`.
13. Timeout-only provider state resets on a new row-level `contact_search_run_id`, while active CAPTCHA and circuit-breaker cooldowns survive the reset until they expire.
14. Every provider attempt stores `provider`, `query`, `result_count`, `provider_error`, `captcha_detected`, `circuit_open`, `timeout`, `provider_disabled`, `provider_disabled_reason`, and `cooldown_seconds`.

### Email Validation

Validation authority: No2Bounce.

No2Bounce flow:

1. Send generated emails to `POST /v2/n2b_validate_bulk` with `emailList`.
2. Store the returned `trackingId`.
3. Poll `GET /v2/n2b_validate_bulk?trackingId=...`.
4. Classify every result into `sendable`, `risky_sendable`, or `rejected`.
5. Accept `sendable` and `risky_sendable` person-specific results, but preserve the bucket in `email_validation_status`.
6. Reject invalid, bad, undeliverable, bounce, spam, disposable, unknown, blocked, incomplete, low-score accept-all, timeout, and provider-error outcomes.

No2Bounce decision buckets:

- `Deliverable`, `Valid`, or `OK` -> `sendable`.
- `Deliverable/AcceptAll` with `finalScore >= 90` and a named person -> `risky_sendable`.
- `Deliverable/AcceptAll` with `finalScore < 90` -> `rejected`.
- `UnDeliverable`, `Invalid`, `Bad`, or `UnDeliverable/AcceptAll` -> `rejected`.
- `catchall=true` by itself is not enough to reject.
- `catchall=true` with `finalScore >= 90` and `Deliverable/AcceptAll` -> `risky_sendable`.
- `catchall=true` with `finalScore < 90` -> `rejected`.

### Email Discovery Libraries

Do not use third-party SMTP probing libraries for this stage. Implement deterministic name normalization and email permutations inside our own worker, then validate only through No2Bounce.

Do not perform direct SMTP probing. No direct mailbox verification over ports `25`, `465`, or `587` is part of this workflow.
Do not add CAPTCHA-solving, stealth automation, fingerprint-evasion packages, or proxy rotation for this workflow.

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

Admin and HR terms are included in the manager fallback search bundle to avoid increasing default Serper query count. Candidate ranking still treats them as the final bucket through `role_priority = 7`.

Stop once an accepted contact is found. Do not keep spending validation credits after success.

Candidate progression is bounded and explicit:

- continue from candidate 1 to candidate 2 and onward when the current candidate's emails are all rejected.
- cap at `5` validated candidates per row by default.
- cap at `4` generated person-specific permutations per candidate by default.
- cap at `24` uncached No2Bounce validations per row by default.
- if validated candidates existed but every checked permutation was rejected, end as `contact_not_found / candidates_found_but_no_sendable_email`.

## Query Strategy

Keep queries simple and auditable.

Current live query builder uses three bundled families:

1. C-suite bundle
   - company query: `("{company_name}" OR "{company_homepage_name}") Singapore ("CEO" OR "Founder" OR "Owner" OR "Managing Director" OR "Executive Director" OR "General Manager")`
   - site query: `site:{canonical_domain} ("Founder" OR "Owner" OR "CEO" OR "Managing Director" OR "Executive Director" OR "General Manager")`
2. Clinic leadership bundle
   - company query: `("{company_name}" OR "{company_homepage_name}") Singapore ("Medical Director" OR "Principal Doctor" OR "Head Doctor" OR "Clinic Manager" OR "Clinical Manager" OR "Practice Manager" OR "Operations Manager" OR "Clinic Operations Manager")`
   - site query: `site:{canonical_domain} ("about us" OR "team" OR "leadership" OR "management" OR "founders" OR "doctors" OR "contact")`
3. Compliance or IT bundle
   - company query: `("{company_name}" OR "{company_homepage_name}") Singapore ("DPO" OR "Data Protection Officer" OR "Compliance Manager" OR "Risk Manager" OR "CISO" OR "Head of Security" OR "Cybersecurity Manager" OR "IT Manager" OR "Head of IT" OR "CTO" OR "Technology Manager" OR "Systems Manager")`
   - site query: `site:{canonical_domain} ("DPO" OR "Data Protection Officer" OR "Compliance Manager" OR "Risk Manager" OR "CISO" OR "IT Manager" OR "Head of IT" OR "CTO")`

If `website_content` has no official-site contact, cap the fallback row at four total queries. If `website_content` is missing, allow up to six. Do not over-normalize company names before querying. Use the table value first, then the homepage-derived name only when it adds a genuinely different brand string.

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

## Email Permutation Strategy

Generate only person-specific emails using `canonical_domain`.

Default patterns:

1. Two-token Western names keep the standard set headed by `first.last`, `first`, `firstlast`, `f.last`, `firstl`, `flast`, `last.first`, `first_last`, and `first-last`.
2. Three- and four-token source-order names try family-name-first permutations before Westernized permutations.
3. For `Tan Chin Beng Melvyn`, the source-order pass tries `tan.chinbengmelvyn`, `tan.melvyn`, `tanchinbengmelvyn`, and `tanmelvyn` before `melvyn.tan` and `melvyntan`.
4. Each generated email candidate stores permutation metadata so evidence shows whether the worker used `source_order` or `western` naming.

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

No2Bounce credits should be protected.

For each row:

1. validate person-company association before generating emails.
2. generate permutations only for the highest-ranked validated candidate first.
3. validate a small batch for that candidate.
4. stop immediately on accepted deliverable email.
5. only move to the next candidate when the current candidate has no `sendable` or `risky_sendable` email.
6. cap candidates per row during tests.

Suggested first-test caps:

- max role buckets per row: 3.
- max queries per role bucket: 3.
- max candidates per row: 5.
- max emails per candidate: 4.
- max No2Bounce emails per row: 24.

Current worker behavior matches those contact caps and also records cache hits, requested No2Bounce counts, remaining row budget, and any budget-limited skipped permutations in `email_validation_evidence_json`.

No2Bounce result handling:

- use the bulk endpoint only after local person/domain filters pass.
- treat the POST response `trackingId` as an asynchronous job, not as immediate validation output.
- poll for final output and parse direct result lists when present.
- if the final response contains a signed result download URL, accept both `downloadFile` and `signedUrl` style fields and parse CSV or JSON from the download.
- redact signed result URLs before storing evidence.
- keep the default poll timeout at `120` seconds; rows that still timeout remain retryable provider failures instead of false no-contact results.
- if a poll times out but No2Bounce aggregate progress shows completed records with zero sendable/risky counts, conservatively mark that candidate's emails as rejected with `partial_timeout_rejected` and continue. If aggregate counts show any sendable/risky result but no per-email mapping, keep the row failed rather than guessing which email is usable.

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
- `email_validation_provider = no2bounce`
- `permutation_pattern`
- `discovered_at`
- `contact_candidates_json`
- `email_candidates_json`
- `contact_search_evidence_json`
- `email_validation_evidence_json`

When exhausted:

- `contact_search_status = contact_not_found`
- `contact_search_reason = no_deliverable_person_specific_email_found` when no validated candidate reaches a meaningful validation attempt.
- `contact_search_reason = candidates_found_but_no_sendable_email` when validated candidates existed but every checked permutation was rejected.
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
- `email_validation_attempts` table stores every No2Bounce request/result.

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
- email permutations generated.
- No2Bounce outcomes.
- terminal `contact_search_status`.
- reason for stopping.

For batch executions, also capture the reconciliation summary emitted by the workflow:

- `rows_selected`
- `rows_terminal_first_pass`
- `rows_stuck`
- `rows_recovered`
- `rows_terminal_final`
- `rows_non_terminal_final`

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

### Phase 3: Email Permutation and No2Bounce

- implement name normalization.
- generate person-specific permutations.
- call No2Bounce in small batches.
- poll by `trackingId`.
- parse accepted and rejected statuses.

Verify:

- generic inboxes are never generated.
- high-score `Deliverable/AcceptAll` results tied to a named person are selected as `risky_sendable`; low-score catch-all and non-deliverable results are rejected.
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
