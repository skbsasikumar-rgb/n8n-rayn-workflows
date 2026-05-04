# Funding Programme Catalogue

This catalogue is data for enrichment, not copy for email claims. A programme can influence a send-ready funding email only when `verification_status = verified_current` and the row profile matches with medium/high confidence.

| programme_name | framework_or_regime | relevant_entity_types | relevant_industries | benefit_summary | exact_claim_allowed_in_email | official_source_url | last_checked | verification_status | use_in_email_when | do_not_claim_when |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Cyber Essentials first successful certification support | Cyber Essentials | sme, npo, charity, social_service | all | Support for first successful Cyber Essentials certification via appointed certification route. | false | https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-essentials/ ; https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-essentials/certification-for-the-cyber-essentials-mark/ | null | needs_refresh | Entity type is SME, NPO, charity, or social-service with medium/high confidence and source refresh is verified_current. | Entity type is unknown, source refresh is stale, or eligibility has not been checked. |
| Cyber Trust first successful certification support | Cyber Trust | sme, npo, charity, social_service | all | Support for first successful Cyber Trust certification via appointed certification route. | false | https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-trust/ | null | needs_refresh | Cyber Trust is specifically recommended and source refresh is verified_current. | Cyber Essentials is the better first baseline or source refresh is stale. |
| CISO-as-a-Service / readiness support | CISO-as-a-Service | sme, npo, charity, social_service, healthcare_provider, clinic, private_company | all | Configurable readiness support route for CISO-as-a-Service or implementation help. | false | needs official source | null | needs_official_source | Official source refresh verifies the current route and any exact percentage. | No official source confirms current support level. Do not claim "up to 70%" yet. |
| HIA / NEHR Connect and implementation support routes | HIA readiness | healthcare_provider, clinic | healthcare, clinic, dental, pharmacy, diagnostic, allied_health, hearing_care | Potential HIA-related support routes including NEHR Connect Grant, PSG cybersecurity solutions, and implementation-readiness help. | false | https://www.synapxe.sg/health-professionals/healthcare-digitalisation/nehr ; https://www.gobusiness.gov.sg/productivity-solutions-grant/ | null | needs_refresh | HIA relevance is medium/high and current support route has been verified. | HIA scope is low-confidence or support route is not verified_current. |
| DPTM support routes via Enterprise Singapore / NCSS | DPTM | sme, npo, charity, social_service | all, social_service | Possible support routes for broader data-protection governance when DPTM is the recommended path. | false | https://www.enterprisesg.gov.sg/ ; https://www.ncss.gov.sg/ | null | needs_refresh | DPTM is specifically recommended and source refresh is verified_current. | Cyber Essentials is the recommended first cert or source refresh is stale. |
| DPE framework / solution-provider route | DPE | private_company, sme | all | Current public focus appears to be framework/solution providers; older grant material may exist. | false | https://www.imda.gov.sg/ | null | needs_refresh | Only after official refresh confirms current direct support for the row profile. | Current source refresh does not verify live fixed-grant support. |

## Refresh Rules

- `verification_status = verified_current` is required for `funding_status = verified_match`.
- Exact percentages, including "up to 70%", are blocked unless `exact_claim_allowed_in_email = true`, `exact_claim_text` is set, and the official source was refreshed.
- `last_checked` must be updated by a source refresh job or human reviewer.
- A stale or missing source can still produce `possible_match`, but not a send-ready funding email.

## Claim Rules

Allowed:

- "Based on the company profile, the Cyber Essentials support route appears worth checking for {{company_name}}, subject to programme confirmation."
- "For healthcare providers preparing for HIA, the relevant support routes may include HIA implementation and readiness support, subject to programme confirmation."

Blocked:

- "Guaranteed funding."
- "Automatic eligibility."
- "Full cost covered."
- "Up to 70%" unless source-backed and explicitly allowed.
- "Eligible SMEs and NPOs may..." in send-ready emails.
