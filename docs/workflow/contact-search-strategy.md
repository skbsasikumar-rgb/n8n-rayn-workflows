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
  -> n8n contact-search batch workflow
  -> claim row as contact_search_status=processing
  -> Python contact-search endpoint in official-site-only preflight mode
  -> write immediately if a deliverable official-site contact is found
  -> Serper Google role search only when preflight cannot select a deliverable email
  -> candidate extraction and ranking
  -> person-company validation
  -> email permutation generation
  -> No2Bounce validation
  -> NocoDB contact writeback
```

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

Primary implemented interface: official-site preflight first, then Serper Google endpoint via the existing n8n `serper` credential only when needed.

Reasoning: Railway-hosted browser SERP has previously hit Google CAPTCHA and circuit-breaker failures. Serper is already wired into the workflow and gives stable Google SERP candidates for this stage.

Provider adapter behavior:

1. Call `/contact-enrich` with `site_fast_path_only = true`, `search_attempts = []`, and `validate_email = true`.
2. If preflight returns `contact_found`, write the contact result directly and spend zero Serper queries for that row.
3. If preflight returns no deliverable official-site contact, call Serper with a small set of bundled Google queries instead of one query per role label.
4. If Serper returns an empty result set, provider error, or timeout, mark the role attempt as `search_provider_failed`.
5. Do not convert provider failures into `contact_not_found`.
6. Stop the row as `failed` if all attempted queries fail due to provider errors.
7. Add a fallback provider later only with explicit approval.

### Email Validation

Validation authority: No2Bounce.

No2Bounce flow:

1. Send generated emails to `POST /v2/n2b_validate_bulk` with `emailList`.
2. Store the returned `trackingId`.
3. Poll `GET /v2/n2b_validate_bulk?trackingId=...`.
4. Accept only a clearly deliverable, non-catch-all result.
5. Reject catch-all, invalid, bounce, spam, unknown, timeout, and provider-error outcomes.

### Email Discovery Libraries

Do not use third-party SMTP probing libraries for this stage. Implement deterministic name normalization and email permutations inside our own worker, then validate only through No2Bounce.

Do not perform direct SMTP probing without explicit approval. Outbound port 25 is often blocked in cloud environments, and SMTP probing can create operational and reputation risk.

## Role Queue Strategy

Process official-site content before spending search queries. If no deliverable email is found, process role bundles in priority order. Each bundle carries multiple role labels so the row can usually be decided in six searches or fewer, and rows with useful `website_content` should stay at four searches or fewer.

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
6. Care and clinical management
   - Head of Nursing
   - Nursing Manager
   - Clinical Lead
   - Care Manager

Stop once an accepted contact is found. Do not keep spending validation credits after success.

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

If `website_content` exists, cap the row at four total queries. If `website_content` is missing, allow up to six. Do not over-normalize company names before querying. Use the table value first, then the homepage-derived name only when it adds a genuinely different brand string.

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

- parse `website_content` before spending search queries and treat official-domain people mentions as highest-value evidence.
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

1. `first.last`
2. `first`
3. `flast`
4. `firstl`
5. `first_last`
6. `first-last`
7. `last.first`
8. `last`
9. `f.last`
10. `first.middle.last`
11. `firstlast`
12. `firstinitiallastname`
13. `firstname_lastname`

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
5. only move to the next candidate when the current candidate has no deliverable non-catch-all email.
6. cap candidates per row during tests.

Suggested first-test caps:

- max role buckets per row: 3.
- max queries per role bucket: 3.
- max candidates per row: 5.
- max emails per candidate: 8.
- max No2Bounce emails per row: 24.

Scale caps only after measuring hit rate and cost.

## Output Strategy

Write both accepted contact fields and full evidence.

When found:

- `contact_search_status = contact_found`
- `contact_search_reason = deliverable_person_specific_email_found`
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
- `contact_search_reason = no_deliverable_person_specific_email_found`
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
- catch-all and non-deliverable results are rejected.
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
