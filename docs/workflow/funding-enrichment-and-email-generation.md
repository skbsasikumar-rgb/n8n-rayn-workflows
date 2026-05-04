# Funding Enrichment And Email Generation

This stage creates reviewable outreach drafts only. It must never send email. The worker returns NocoDB patches containing enrichment, funding match evidence, draft sequence fields, and quality flags for human review.

## Pressure-Type Model

`pressure_type` chooses the outreach lead:

| pressure_type | Use when | Email lead | Default asset |
| --- | --- | --- | --- |
| `hia_regulatory` | HIA relevance is medium/high for healthcare, clinic, pharmacy, diagnostic, allied health, hearing care, HIMS or NEHR-type rows. | "With HIA timelines starting from 2027..." | `hia_readiness_map` |
| `pdpa_safeguards` | HIA is false/low and the organisation likely handles personal data. | "Because {{company_name}} handles {{data_type_signal}}..." | `pdpa_safeguards_checklist` |
| `customer_trust` | B2B, vendor, SaaS, outsourcing, professional services, finance, education, HR, recruitment or enterprise-facing row. | "When customers share data or ask security questions..." | `security_evidence_checklist` |
| `funding` | Funding is verified, confidence is high, and regulatory/trust pressure is weak. | Funding-specific route. | `funding_route_summary` |
| `not_ready` | Missing trigger, weak evidence, blocked contact, unsubscribed/bounced/complained, or missing email when not in draft-only mode. | No send-ready email. | none |

Cyber Essentials is the default first formal route unless evidence supports HIA readiness first, Cyber Trust, DPE or DPTM. Cyber Essentials supports the cybersecurity safeguards and evidence side; it is not full PDPA or HIA compliance.

## Master Outreach Tracks

The planner now wires outreach around four buying pressures:

| Track | Use when | Core problem | Email 1 lead |
| --- | --- | --- | --- |
| Track A - HIA / healthcare | `hia_relevant = true` with medium/high confidence. | HIA is coming; in-scope providers need regulatory readiness, not a generic cyber pitch. | "HIA timelines starting from 2027..." |
| Track B - PDPA + Cyber Essentials safeguards | Non-HIA rows with medium/high personal-data intensity. | The organisation handles personal data and needs reasonable security safeguards that can be shown clearly. | "PDPA security safeguards..." |
| Track C - DPO / data-protection owner | Selected contact title suggests DPO, compliance, privacy, operations, admin or HR ownership. | The person owns personal-data responsibility, but evidence sits across IT, HR, vendors and operations. | "Data protection evidence..." |
| Track D - Customer trust / procurement proof | B2B, SaaS, outsourcing, education, finance, HR, recruitment, professional services, vendor or enterprise-facing evidence. | Customers and partners may ask for reusable security proof before sharing data. | "Security evidence..." |

Decision tree:

```text
IF hia_relevant = true and hia_confidence is medium/high
  -> Track A: HIA regulatory readiness
ELSE IF selected_contact_title contains DPO/compliance/privacy/operations/admin/HR
  -> Track C: PDPA evidence owner
ELSE IF business model indicates B2B/professional services/SaaS/outsourcing/education/finance/vendor
  -> Track D: customer trust / security evidence
ELSE IF personal_data_intensity is medium/high
  -> Track B: PDPA + Cyber Essentials safeguards
ELSE
  -> not_ready; do not generate a usable sequence
```

Messaging hierarchy:

- HIA rows: HIA timeline / regulatory readiness, then health-information access and security, then Cyber Essentials as a first baseline, then funding support.
- Non-HIA PDPA rows: personal-data responsibility, then practical safeguards, then Cyber Essentials as recognised baseline, then funding support.
- DPO / ops rows: data-protection evidence ownership, then scattered evidence across IT/HR/vendors/operations, then Cyber Essentials as a structure for the security baseline.
- B2B / trust rows: customer security proof, then scattered evidence, then Cyber Essentials as reusable baseline, then funding support.

Recommended value framing:

- RAYN helps Singapore organisations prepare for Cyber Essentials and related cyber/data readiness requirements by identifying gaps, implementing controls, organising evidence, and keeping certification readiness current through consulting plus SaaS.
- For healthcare providers, RAYN helps map Cyber Essentials into the wider HIA readiness journey.
- For non-healthcare organisations, RAYN helps turn PDPA security-safeguard expectations into practical Cyber Essentials controls and evidence.

## Funding Enrichment Model

Funding is matched by `services/crawl4ai/funding_programs.py`:

- deterministic entity and industry match first.
- low entity confidence forces `funding_status = needs_review`.
- source status other than `verified_current` blocks `verified_match`.
- `funding_claim_line` is the only source for Email 3 funding language.
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
- Email 2 should diagnose access, data mapping, vendors, backups and incident reporting.

PDPA:

- Private-sector organisations handling personal data need reasonable protection/security arrangements.
- Cyber Essentials supports the security-safeguard evidence side of PDPA readiness.
- Do not say Cyber Essentials makes an organisation PDPA compliant.
- DPE/DPTM are mentioned only when the row recommends that path.
- Better wording: "Cyber Essentials supports the security-safeguards side of PDPA readiness."
- For broader PDPA governance, DPE/DPTM may be more directly data-protection focused, but only mention them when the enrichment supports that path.

DPO / data-protection owner:

- Use when the contact appears to own DPO, privacy, compliance, operations, admin or HR responsibilities.
- Lead with evidence ownership, not cybersecurity.
- The diagnostic should ask whether personal-data systems can be mapped to an owner, access list, vendor, backup process and incident contact.

Customer trust:

- Use when buyers, partners or enterprise customers likely ask security questions.
- Position Cyber Essentials as reusable proof around assets, access control, malware protection, patching, backup and incident readiness.
- Lead with customer security evidence and trust, not PDPA compliance.

## Email Sequence

Generate exactly four emails:

| Email | Purpose | Rules |
| --- | --- | --- |
| 1 | Lead with pressure type and one enriched trigger. | 45-85 words. Mention Cyber Essentials only as route/baseline. Tiny CTA. |
| 2 | Diagnostic tied to the same pressure. | 40-80 words. Not a generic certification explainer. Tiny CTA. |
| 3 | Funding only. | 45-95 words. Must use `funding_claim_line`. Must include "subject to programme confirmation" or equivalent. |
| 4 | Respectful close loop. | 20-55 words. One easy reply. |

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
- Email 3 does not use `funding_claim_line`.
- Email 3 uses SME/NPO conditional language.
- exact percentage appears without verified source permission.
- HIA deadline appears when `hia_deadline_claim_safe = false`.
- Cyber Essentials is described as full PDPA or HIA compliance.
- no trigger signal.
- low trigger confidence with send-ready email.
- funding status is not `verified_match` and the row is marked send-ready.

## Examples

Sree Narayana Mission:

- expected entity: `npo`, `charity` or `social_service`, depending on evidence.
- pressure: `pdpa_safeguards` or `customer_trust`, not HIA unless HIA evidence exists.
- data signal: `resident_data` or `beneficiary_data`.
- funding: Cyber Essentials support route only when verified_current.
- safe funding line: "Based on the organisation profile, the Cyber Essentials support route appears worth checking, subject to programme confirmation."

Amaris B. Clinic:

- expected entity: `clinic` / `healthcare_provider`.
- pressure: `hia_regulatory`.
- data signal: `patient_data` or `health_information`.
- problem: `hia_readiness` or `access_control`.
- recommended first route: `Cyber Essentials` as baseline or `HIA readiness` as map.
- if batch/deadline is not high-confidence, say "may be in the HIA readiness window" and keep review required.

Amazing Hearing Group:

- expected entity: `healthcare_provider` or `private_company`, depending on evidence.
- HIA relevance only when hearing-care / healthcare evidence supports scope.
- pressure: `hia_regulatory` if HIA confidence is medium/high, otherwise `pdpa_safeguards`.
- email angle: hearing-care data/access map.
- do not overclaim HIA scope.
