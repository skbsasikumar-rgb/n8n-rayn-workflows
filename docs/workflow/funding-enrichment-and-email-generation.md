# Funding Enrichment And Email Generation

This stage creates reviewable outreach drafts only. It must never send email. The worker returns NocoDB patches containing enrichment, funding match evidence, draft sequence fields, and quality flags for human review.

## Pressure-Type Model

`pressure_type` chooses the outreach lead:

| pressure_type | Use when | Email lead | Default asset |
| --- | --- | --- | --- |
| `hia_regulatory` | HIA relevance is medium/high for healthcare, clinic, pharmacy, diagnostic, allied health, hearing care, HIMS or NEHR-type rows. | "With HIA readiness becoming more urgent for healthcare providers..." | segment-specific readiness asset |
| `pdpa_safeguards` | HIA is false/low and the organisation likely handles personal data. | PDPA is the legal responsibility; Cyber Essentials supports the security-safeguards evidence side. | segment-specific safeguards checklist |
| `customer_trust` | B2B, vendor, SaaS, outsourcing, professional services, HR/recruitment with vendor/customer-proof evidence, or enterprise-facing row. | Customers may ask for reusable security evidence before sharing data. | segment-specific security evidence checklist |
| `funding` | Funding is verified, confidence is high, and regulatory/trust pressure is weak. | Funding-specific route. | `funding_route_summary` |
| `not_ready` | Missing trigger, weak evidence, blocked contact, unsubscribed/bounced/complained, or missing email when not in draft-only mode. | No send-ready email. | none |

Cyber Essentials is the default first formal route unless evidence supports HIA readiness first, Cyber Trust, DPE or DPTM. Cyber Essentials supports the cybersecurity safeguards and evidence side; it is not full PDPA or HIA compliance.

## HIA Service Siloing

Use HIA before PDPA when the row has medium/high evidence of an in-scope healthcare service type. PDPA is the default only after HIA is false or low-confidence.

The planner uses a hybrid HIA decision path:

- deterministic rules decide clear cases first;
- high-confidence deterministic HIA results cannot be overridden by the LLM;
- the LLM is called only for ambiguous healthcare-adjacent rows, such as wellness, therapy, care, hearing-care, audiology, medical-device, screening or test language without a clear service type;
- the LLM must return strict JSON with `hia_relevant`, `hia_confidence`, `hia_service_type_guess`, `hia_scope_reason`, and evidence quotes;
- medium/high LLM results can promote or reject HIA on ambiguous rows; low-confidence LLM output is ignored.

Official implementation timeline mapping used by the planner:

| HIA service type guess | Official service examples | Timeline claim |
| --- | --- | --- |
| `GP_OMS` | Outpatient Medical Service (GP) | Batch 1 - Sep 2027 |
| `hospital` | Acute Hospital, Community Hospital | Batch 1 - Sep 2027 |
| `diagnostic` | Clinical Laboratory, Radiology Laboratory, Nuclear Medicine Service | Batch 1 - Sep 2027 |
| `specialist_OMS` | Outpatient Medical Service (Specialist) | Batch 2 - Sep 2028 |
| `long_term_care` | Nursing Home | Batch 2 - Sep 2028 |
| `unknown` with batch evidence | Outpatient Renal Dialysis | Batch 2 - Sep 2028 |
| `dental` | Outpatient Dental | Batch 3 - Mar 2030 |
| `retail_pharmacy` | Retail Pharmacy | Batch 3 - Mar 2030 |
| `unknown` with batch evidence | Ambulatory Surgical Centre | Batch 3 - Mar 2030 |
| `unknown` with batch evidence | Assisted Reproduction | Batch 3 - Mar 2030 |
| `HIMS_provider`, `NEHR_user` | Other HCSA licensees / approved NEHR users not listed in the batch table | Other CS/DS by Sep 2028 |

Example: American International Clinic Singapore should classify as `hia_regulatory` when the row evidence shows a medical clinic, doctors, outpatient appointments, or patient treatment. The likely service type is `GP_OMS`, so the batch guess is `Batch 1 - Sep 2027` when confidence is medium/high.

## Master Outreach Tracks

The planner now wires outreach around four buying pressures:

| Track | Use when | Core problem | Email 1 lead |
| --- | --- | --- | --- |
| Track A - HIA / healthcare | `hia_relevant = true` with medium/high confidence. | HIA is coming; in-scope providers need regulatory readiness, not a generic cyber pitch. | "HIA readiness becoming more urgent..." |
| Track B - PDPA + Cyber Essentials safeguards | Non-HIA rows with medium/high personal-data intensity. | PDPA is the legal obligation; Cyber Essentials gives a practical way to structure and evidence the cybersecurity safeguards behind it. | "PDPA security safeguards..." |
| Track C - DPO / data-protection owner | Selected contact title suggests DPO, compliance, privacy, operations, admin, HR or IT ownership. | Evidence often sits across operations, HR, IT and vendors; do not claim the person owns compliance unless title evidence is explicit. | "Data protection evidence..." |
| Track D - Customer trust / procurement proof | B2B, SaaS, outsourcing, education, finance, HR, recruitment, professional services, vendor or enterprise-facing evidence. | Customers and partners may ask for reusable security proof before sharing data. | "Security evidence..." |

Decision tree:

```text
IF hia_relevant = true and hia_confidence is medium/high
  -> Track A: HIA regulatory readiness
ELSE IF selected_contact_title contains DPO/compliance/privacy/operations/admin/HR
  -> Track C: PDPA evidence owner
ELSE IF business model indicates B2B/professional services/SaaS/outsourcing/vendor/procurement proof
  -> Track D: customer trust / security evidence
ELSE IF personal_data_intensity is medium/high
  -> Track B: PDPA + Cyber Essentials safeguards
ELSE
  -> not_ready; do not generate a usable sequence
```

Messaging hierarchy:

- HIA rows: HIA timeline / regulatory readiness, then health-information access and security, then Cyber Essentials as a first baseline, then funding support.
- Non-HIA PDPA rows: PDPA personal-data responsibility, then practical safeguards and evidence, then Cyber Essentials as a recognised baseline for the security-safeguards side, then funding support.
- DPO / ops rows: data-protection evidence ownership, then scattered evidence across IT/HR/vendors/operations, then Cyber Essentials as a structure for the security baseline.
- B2B / trust rows: customer security proof, then scattered evidence, then Cyber Essentials as reusable baseline, then funding support.

Greeting rule:

- If `selected_contact_name` is present, Email 1 starts `Hi {{first_name}},` using the existing first-name helper.
- If `selected_contact_name` is blank, Email 1 starts `Hello team,`.
- Do not invent names and do not use the company name as the greeting. The `Noticed...` line still includes the company name.

## Controlled Email Variants

Email variation is deterministic and comes from the approved variant bank in `services/crawl4ai/outreach_planner.py`. The planner does not ask the LLM to rewrite copy randomly, and it does not add visible NocoDB columns for variants.

Variant selection uses a stable SHA-256 seed based on `row_id/Id`, `campaign_id` and `email_step`. If a row has no stable id, variant `A` is used so local fixtures and ad hoc previews stay predictable. The selected track, segment, campaign id, selector and per-email `variant_id` values are stored behind the scenes inside `email_sequence_json.variant_metadata`.

The bank covers the four campaign tracks and segment-specific subject lines:

- `hia_regulatory`: clinic, dental, specialist, pharmacy, hearing-care and care.
- `pdpa_safeguards`: education, HR/recruitment, client data, customer data, care/NPO and general safeguards.
- `dpo_evidence`: data-protection / operations evidence owner copy.
- `customer_trust`: SaaS/customer evidence, vendor/supplier evidence and general B2B evidence.

Body variants keep the same copy brief and compliance rules:

- Email 1 always keeps greeting, `Noticed...`, problem, mechanism and CTA in order.
- Email 2 is funding-only when verified-current funding gates pass; otherwise it uses the non-funding value-fallback asset.
- Email 3 stays diagnostic.
- Email 4 is a short close-loop note.
- No final email body includes signatures or signoffs.
- Every rotated variant must pass the same quality gate: no internal `signals` wording, no HIA batch/date/window wording, no Cyber Essentials equals PDPA/HIA compliance claim, no unsupported funding, no generic copy, and Email 1 must preserve trigger/problem/mechanism/CTA.

Copy style guardrails: avoid internal words such as `signals`, avoid HIA batch/date wording in final bodies, avoid inflated promotional language, avoid common AI filler words, and keep the phrasing practical and human.

Recommended value framing:

- RAYN helps Singapore organisations prepare for Cyber Essentials and related cyber/data readiness requirements by identifying gaps, implementing controls, organising evidence, and keeping certification readiness current through consulting plus SaaS.
- For healthcare providers, RAYN helps map Cyber Essentials into the wider HIA readiness journey.
- For non-healthcare organisations, RAYN helps turn PDPA security-safeguard expectations into practical Cyber Essentials controls and evidence.

## Funding Enrichment Model

Funding is matched by `services/crawl4ai/funding_programs.py`:

- deterministic entity and industry match first.
- low entity confidence forces `funding_status = needs_review`.
- source status other than `verified_current` blocks `verified_match`.
- `funding_claim_line` is the only source for Email 2 funding language.
- exact percentages are blocked unless the programme entry explicitly allows them after official refresh.

Statuses:

- `verified_match`: source current, entity confidence medium/high, programme applies.
- `possible_match`: profile may fit but source needs refresh.
- `needs_review`: entity confidence low/unknown or route needs human confirmation.
- `not_applicable`: no route fits.
- `not_checked`: reserved for rows before enrichment.

## HIA vs PDPA vs Trust Messaging

HIA:

- HIA is not a certification.
- HIA is a healthcare information legal regime covering contribution, access, sharing, cybersecurity and data-security duties.
- HIA timelines phase in from 2027 onward.
- For HIA rows, use regulatory readiness, not fear.
- Say Cyber Essentials is a practical first baseline for HIA cybersecurity/data-security readiness.
- Do not say Cyber Essentials equals HIA compliance.
- Email 3 should diagnose access, data mapping, vendors, backups and incident reporting.
- Final email bodies must not mention HIA batch labels, HIA batch dates or "HIA window" wording.
- Specialist subtypes now use more specific profile and record language for heart/cardiology, pain management, surgical, dermatology, eye/ophthalmology and home-care/caregiver rows.

PDPA:

- Private-sector organisations handling personal data need reasonable protection/security arrangements.
- PDPA says the organisation needs to protect personal data; Cyber Essentials helps prove the security side is actually in place.
- Cyber Essentials supports the security-safeguards side of PDPA readiness by turning reasonable protection into practical controls and evidence across assets, access, malware protection, patching, backups and incident response.
- The benefit angle is evidence, not only intention: access lists, asset inventory, backup evidence, update process, malware controls, incident plan and staff/security evidence.
- Do not say Cyber Essentials makes an organisation PDPA compliant.
- DPE/DPTM are mentioned only when the row recommends that path.
- Better wording: "Cyber Essentials supports the security-safeguards side of PDPA readiness."
- For broader PDPA governance, DPE/DPTM may be more directly data-protection focused, but only mention them when the enrichment supports that path.
- PDPA variants use industry-specific examples for education/training, HR/recruitment, non-clinical lab/testing, NPO/social service, accounting/finance/admin and retail/e-commerce rows.

DPO / data-protection owner:

- Email 1 leads with the data-protection / operations contact route, then the evidence problem: owners, access, vendors, backups and incident contacts.
- Use "often sits across operations, HR, IT and vendors" language.
- Do not say the person is responsible for compliance unless the title clearly proves that.

Customer trust / procurement proof:

- SaaS/platform rows use customer security evidence around user data, admin access and backups.
- Professional services rows use reusable security evidence before customers share data.
- HR/recruitment B2B rows use candidate/employee data proof.
- Outsourcing/vendor rows use supplier security evidence.
- Education/training B2B rows use learner-data evidence.

- Use when the contact appears to own DPO, privacy, compliance, operations, admin or HR responsibilities.
- Lead with evidence ownership, not cybersecurity.
- The diagnostic should ask whether personal-data systems can be mapped to an owner, access list, vendor, backup process and incident contact.

Customer trust:

- Use when buyers, partners or enterprise customers likely ask security questions.
- Position Cyber Essentials as reusable proof around assets, access control, malware protection, patching, backup and incident readiness.
- Lead with customer security evidence and trust, not PDPA compliance.

## Copy Brief Layer

The planner now builds a deterministic copy brief before OpenRouter writes emails. The LLM should write from the brief, not from generic labels such as `pressure_type` or `problem_area`.

The copy brief converts public enrichment into company-level messaging ingredients:

- `company_profile_summary`: what the organisation appears to do.
- `primary_services_summary`, `locations_summary`, `team_structure_summary`: concrete public signals for specificity.
- `personal_data_handled_guess`, `sensitive_data_examples`, `data_systems_likely`: likely data surfaces to anchor the diagnostic.
- `regulatory_pressure_summary`, `hia_obligation_angle`, `pdpa_obligation_angle`, `customer_trust_angle`, `deadline_or_timeline_angle`: the buying pressure in plain language.
- `funding_entity_basis`, `funding_route_summary`, `funding_specificity_level`, `funding_claim_safe`, `funding_next_check_needed`: funding language safety controls.
- `email_personalisation_signal`, `email_problem_statement`, `email_mechanism_statement`, `email_asset_offer`, `email_cta`, `email_angle_reason`: the exact email ingredients.

For HIA/healthcare rows, the copy brief also computes clinic/company profile fields for audit and preview review. These are computed by the planner today and are not required NocoDB columns unless the table installer is extended later:

- `clinic_profile_guess`: profile bucket such as `solo_gp`, `family_gp`, `multi_doctor_gp`, `specialist_led`, `aesthetic_medical`, `dental`, `pharmacy`, `diagnostic_lab`, `hearing_care`, `allied_health`, `mental_health`, `hospice_long_term_care`, `home_care`, or `clinic_group`.
- `clinic_profile_phrase`: prospect-facing phrase used in Email 1, for example "a family clinic offering GP-style consultations" or "a hearing-care provider offering hearing tests, hearing aids and audiology support".
- `clinic_structure_guess`, `clinic_structure_confidence`, `umbrella_or_group_guess`: whether the row looks solo, multi-practitioner, grouped, or unclear.
- `solo_gp_likelihood`, `specialist_led_likelihood`, `multi_practitioner_likelihood`, `primary_service_summary`, `clinic_structure_evidence`: audit helpers explaining why the phrase was chosen.

HIA Email 1 should now open with a prospect-facing profile observation:

```text
Noticed {{company_name}} appears to be {{clinic_profile_phrase}}.

With HIA readiness becoming more urgent for healthcare providers, the practical question is whether {{segment_specific_records}}, access, backups, patching, vendors and incident steps are already mapped clearly.

Cyber Essentials is often a useful first baseline for the cybersecurity/data-security side.

Worth sending a short {{segment_specific_asset}}?
```

Final email bodies must not contain internal audit wording such as "signals", and must not expose HIA batch labels, dates, or "HIA window" wording.

Hard not-ready rules:

- If `email_personalisation_signal`, `email_problem_statement`, `email_mechanism_statement`, or `email_cta` is blank, the row is `not_ready`.
- If `pressure_type = not_ready`, all email bodies stay empty.
- If `funding_claim_safe = false`, funding can be drafted for review but `email_send_ready` must remain false and the row gets `funding_needs_review`.

## Email Sequence

Generate exactly four emails:

| Email | Purpose | Rules |
| --- | --- | --- |
| 1 | Researched note from copy brief. | Start with `email_personalisation_signal`, then `email_problem_statement`, then `email_mechanism_statement`, then `email_cta`. |
| 2 | Funding or value fallback. | Funding-only when `email_2_mode = funding`; otherwise use the non-funding checklist/evidence fallback. Funding copy must use `funding_claim_line` and include "subject to programme confirmation" or equivalent. `funding_followup_mode` is the canonical mode field. |
| 3 | Diagnostic tied to the same problem. | Use `email_problem_statement` and `data_systems_likely`. Not a generic certification explainer. No greeting or signature; it is a reply-style diagnostic follow-up. Tiny CTA. |
| 4 | Respectful close loop. | 20-55 words. Reference `email_asset_offer`. One easy reply. |

Final email bodies do not include a signature, signoff, sender name, or RAYN Secure signature block.

Forbidden:

- "if you are an SME"
- "if you are an NPO"
- "eligible SMEs and NPOs may" in send-ready emails
- "companies with higher assurance needs"
- "you are non-compliant"
- "guaranteed funding"
- "you will be hacked"
- "Cyber Essentials makes you PDPA compliant"
- "fully HIA compliant with Cyber Essentials"
- "transform your security"
- "unlock growth"
- "leading provider"
- "hope you are well"
- "I came across your company"

## Workflow Modes

`copy_qa_mode`:

- Used only for sample-company copy QA and strategy testing.
- `/outreach-plan` accepts `copy_qa_mode = true` even when `validated_email` is blank.
- The planner always forces `email_send_ready = false`, adds a `copy_qa_mode` quality flag, and keeps `human_review_status = ready_for_review` unless the row is otherwise `not_ready`.
- This mode must not be wired to Instantly or any send path.

`production_draft_mode`:

- Current production mode.
- The workflow fetches completed enrichment rows with a best URL, no duplicate, blank `email_1_subject`, and blank `automation_decision`.
- `/outreach-plan` suppresses rows without `validated_email` unless `copy_qa_mode = true`, sets `skip_openrouter=true`, and does not generate or patch email bodies for suppressed/skipped rows.
- Drafts are patched only for human review. `email_send_ready` remains controlled by deterministic quality gates and funding safety.
- OpenRouter is called only when the copy brief has the required ingredients and the personalisation signal is concrete.

`future send_mode`:

- Not implemented.
- Any future send mode must require `validated_email`, active unsubscribe status, `do_not_contact = false`, human approval, and final quality checks.
- It must not treat `copy_qa_mode` rows as sendable or approved.

## NocoDB Columns

Create or refresh these columns with:

```bash
python3 scripts/ensure_rayn_outreach_columns.py --database-url "$DATABASE_URL"
```

The script updates the physical Postgres table, NocoDB column metadata, and the first grid view. It is idempotent.

Company identity / entity enrichment:

- `entity_type_guess`
- `entity_type_confidence`
- `singapore_registered_guess`
- `uen_guess`
- `uen_source_url`
- `employee_count_guess`
- `sme_likelihood`
- `npo_likelihood`
- `charity_or_social_service_likelihood`
- `entity_evidence_json`

Pressure classification:

- `pressure_type`
- `pressure_reason`
- `outreach_trigger_signal`
- `outreach_trigger_source_url`
- `outreach_trigger_confidence`
- `data_type_signal`
- `problem_area`
- `problem_hypothesis`
- `value_asset_offer`

HIA enrichment:

- `hia_relevant`
- `hia_relevance_score`
- `hia_confidence`
- `hia_scope_reason`
- `hia_service_type_guess`
- `hia_timeline_batch_guess`
- `hia_deadline_claim_safe`
- `hia_disclaimer_needed`
- `hia_evidence_json`

PDPA / data-protection enrichment:

- `pdpa_relevant`
- `pdpa_reason`
- `personal_data_intensity`
- `sensitive_data_likelihood`
- `pdpa_safeguard_angle`
- `recommended_first_cert`
- `recommended_cert_path`
- `certification_reason`
- `certification_fit_score`
- `certification_evidence_json`

Funding enrichment:

- `funding_status`
- `funding_relevant`
- `primary_funding_program`
- `funding_programs_matched_json`
- `funding_programs_possible_json`
- `funding_programs_not_applicable_json`
- `funding_eligibility_basis`
- `funding_claim_line`
- `funding_cta_asset`
- `funding_confidence`
- `funding_last_checked_at`
- `funding_source_urls_json`
- `funding_human_review_required`

Copy brief:

- `company_profile_summary`
- `business_model_guess`
- `primary_services_summary`
- `locations_summary`
- `team_structure_summary`
- `personal_data_handled_guess`
- `sensitive_data_examples`
- `data_systems_likely`
- `data_flow_complexity`
- `data_risk_reason`
- `regulatory_pressure_summary`
- `hia_obligation_angle`
- `pdpa_obligation_angle`
- `customer_trust_angle`
- `deadline_or_timeline_angle`
- `funding_entity_basis`
- `funding_route_summary`
- `funding_specificity_level`
- `funding_claim_safe`
- `funding_next_check_needed`
- `email_personalisation_signal`
- `email_personalisation_quote`
- `email_personalisation_source_url`
- `email_problem_statement`
- `email_mechanism_statement`
- `email_asset_offer`
- `email_cta`
- `email_angle_reason`

Contact / compliance:

- `selected_contact_name`
- `selected_contact_title`
- `selected_contact_email`
- `selected_contact_linkedin_url`
- `decision_maker_role_guess`
- `do_not_contact`
- `unsubscribe_status`
- `email_source`

Email drafts:

- `outreach_variant`
- `email_1_subject`
- `email_1_body`
- `email_2_subject`
- `email_2_body`
- `email_3_subject`
- `email_3_body`
- `email_4_subject`
- `email_4_body`
- `email_sequence_json`
- `email_quality_score`
- `email_quality_flags`
- `email_send_ready`
- `human_review_status`

## Quality Gate

Score 0-10:

- Clear ICP/entity fit: 2
- Strong trigger or regulatory/personal-data reason: 2
- Specific business problem: 2
- Credible mechanism: 1
- Correct funding specificity: 1
- One low-friction CTA: 1
- Sounds human/not templated: 1

Fail conditions:

- score below 7.
- any forbidden phrase appears.
- word limits exceeded.
- Email 2 does not use `funding_claim_line` when `email_2_mode = funding`.
- Email 2 uses SME/NPO conditional language.
- exact percentage appears without verified source permission.
- HIA deadline appears when `hia_deadline_claim_safe = false`.
- Cyber Essentials is described as full PDPA or HIA compliance.
- no trigger signal.
- low trigger confidence with send-ready email.
- funding status is not `verified_match` and the row is marked send-ready.

## Examples

## No-Human-Review Automation Model

The planner now converts uncertainty into deterministic outcomes instead of relying on humans to rescue rows.

Decision values:

- `auto_send_eligible`: contact, enrichment, copy and funding/value-fallback gates passed. In the current workflow this is still draft-only; a future sender should read only this value.
- `suppressed`: hard stop for `do_not_contact`, unsubscribed/bounced/complained, or missing validated email in production planning.
- `retry_enrichment_once`: enrichment is weak but has not been retried.
- `auto_skipped`: unresolved identity, weak evidence after retry, unsafe copy, missing concrete observation or unsupported track.
- `draft_only_review`: QA/testing mode only, such as `copy_qa_mode`.

The patch exposes `automation_decision`, `automation_decision_reason`, `automation_blockers_json`, `automation_advisory_flags_json`, `contact_send_mode`, `contact_identity_confidence`, `email_2_mode`, `funding_followup_mode`, legacy `email_3_mode`, enrichment/copy quality scores, severe email flags and `final_send_gate_passed`.

Contact policy:

- Missing `validated_email` suppresses by default outside `copy_qa_mode`.
- `copy_qa_mode` may preview rows without `validated_email`, but it never sets `email_send_ready`.
- `named_person`: validated non-generic email, usable contact name, and `contact_identity_confidence` of `medium` or `high`.
- `generic_team`: generic/company inbox or low-confidence personal identity. Send mode can stay generic even when a selected contact name exists.
- Greeting is intentionally simple: selected contact name present means first-name greeting; blank selected contact name means `Hello team,`.
- `suppressed`: hard contact/suppression stop.
- `auto_skipped_unresolved_identity`: personal-looking email without a resolved person identity.

Funding policy:

- Email 2 uses the `funding_followup_mode = funding` path only when the funding match is verified, the claim is safe, entity confidence is medium/high, at least one matched programme exists, and at least one matched programme is `verified_current`.
- Otherwise Email 2 uses the `funding_followup_mode = value_fallback` path, does not mention funding, and the row does not require review solely because of funding uncertainty.
- `email_2_mode` mirrors `funding_followup_mode`; `email_3_mode` is retained as a legacy alias during migration.
- Exact percentage claims are allowed only when the matched programme metadata explicitly permits exact claims.

Blocking vs advisory flags:

- `automation_blockers_json` contains only true blockers: severe email flags, missing concrete observation, unsupported pressure, missing problem, unresolved contact identity, weak enrichment below threshold, and missing required copy-brief fields.
- `automation_advisory_flags_json` can include non-blocking notes such as low trigger confidence, missing optional data-system detail when the score still passes, or funding follow-up notes when Email 2 uses value fallback.

Send-state distinction:

- `final_send_gate_passed = true` means the row passed policy, contact, enrichment and copy gates.
- `email_send_ready = true` means the current run is allowed to hand the row to a sender. In draft-only runs, `final_send_gate_passed` may be true while `email_send_ready` remains false.

HIA uncertainty policy:

- Strong HIA evidence stays `hia_regulatory`.
- Weak healthcare-adjacent evidence routes to `pdpa_safeguards` when personal-data evidence exists.
- Weak scrape / not-ready evidence returns `retry_enrichment_once` on the first pass.
- Obvious healthcare rows without enough HIA evidence use `retry_enrichment_once` with a deeper-healthcare-pages blocker on the first pass.
- After the retry, weak HIA and weak PDPA/trust evidence is `auto_skipped`, not reviewed.

LLM drift policy:

- The deterministic quality gate is authoritative.
- Severe drift falls back once to deterministic copy.
- If deterministic fallback passes, the row can still be `auto_send_eligible`.
- If severe flags remain, the row is `auto_skipped`.

Sree Narayana Mission:

- expected entity: `npo`, `charity` or `social_service`, depending on evidence.
- pressure: `pdpa_safeguards` or `customer_trust`, not HIA unless HIA evidence exists.
- data signal: `resident_data` or `beneficiary_data`.
- copy brief should mention resident, beneficiary, volunteer and staff data; PDPA safeguards; likely case/resident records, volunteer lists, backups and incident contacts; and a care-organisation checklist.
- funding: Cyber Essentials support route only when verified_current.
- safe funding line: "Based on the organisation profile, the Cyber Essentials support route appears worth checking, subject to programme confirmation."

Amaris B. Clinic:

- expected entity: `clinic` / `healthcare_provider`.
- pressure: `hia_regulatory`.
- data signal: `patient_data` or `health_information`.
- problem: `hia_readiness` or `access_control`.
- copy brief should mention HIA timelines from 2027, patient/health information, appointment or patient systems, access, backups, vendors, incident steps, and an HIA readiness map.
- recommended first route: `Cyber Essentials` as baseline or `HIA readiness` as map.
- if HIA evidence is weak, route to PDPA safeguards or skip/retry rather than keeping review required.

Amazing Hearing Group:

- expected entity: `healthcare_provider` or `private_company`, depending on evidence.
- HIA relevance only when hearing-care / healthcare evidence supports scope.
- pressure: `hia_regulatory` if HIA confidence is medium/high, otherwise `pdpa_safeguards`.
- email angle: hearing-care data/access map.
- do not overclaim HIA scope.
- copy brief should mention health information only when hearing-care evidence is strong. If evidence is weak, the HIA angle should explicitly say not to lead with HIA or the row should be `not_ready`.

Generic B2B company:

- expected pressure: `customer_trust`.
- copy brief should mention customer security questions, reusable proof, customer/partner/business-contact data, CRM/email/file-share/vendor systems, and a security evidence checklist.
- email angle: customers ask for evidence; Cyber Essentials creates reusable proof around access, updates, backups, malware protection and incident response.
