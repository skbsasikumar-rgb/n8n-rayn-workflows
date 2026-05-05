from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
VERIFIED_CURRENT = "verified_current"


@dataclass
class FundingProgram:
    programme_id: str
    programme_name: str
    framework_or_regime: str
    relevant_entity_types: list[str]
    relevant_industries: list[str]
    benefit_summary: str
    email_safe_claim_template: str
    do_not_claim: list[str]
    official_source_urls: list[str]
    last_checked: str | None = None
    verification_status: str = "needs_refresh"
    exact_claim_allowed_in_email: bool = False
    exact_claim_text: str = ""
    use_in_email_when: str = ""
    do_not_claim_when: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FundingMatch:
    funding_status: str
    funding_relevant: bool
    primary_funding_program: str
    matched: list[dict[str, Any]] = field(default_factory=list)
    possible: list[dict[str, Any]] = field(default_factory=list)
    not_applicable: list[dict[str, Any]] = field(default_factory=list)
    funding_eligibility_basis: str = ""
    funding_claim_line: str = ""
    funding_cta_asset: str = "funding_route_summary"
    funding_confidence: str = "low"
    funding_last_checked_at: str = ""
    funding_source_urls: list[str] = field(default_factory=list)
    funding_human_review_required: bool = True
    reason: str = ""

    def to_patch_fields(self) -> dict[str, Any]:
        return {
            "funding_status": self.funding_status,
            "funding_relevant": self.funding_relevant,
            "primary_funding_program": self.primary_funding_program,
            "funding_eligibility_basis": self.funding_eligibility_basis,
            "funding_claim_line": self.funding_claim_line,
            "funding_cta_asset": self.funding_cta_asset,
            "funding_confidence": self.funding_confidence,
            "funding_last_checked_at": self.funding_last_checked_at,
            "funding_human_review_required": self.funding_human_review_required,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROGRAMMES: list[FundingProgram] = [
    FundingProgram(
        programme_id="csa_cyber_essentials_first_cert_support",
        programme_name="Cyber Essentials first successful certification support",
        framework_or_regime="Cyber Essentials",
        relevant_entity_types=["sme", "npo", "charity", "social_service"],
        relevant_industries=["all"],
        benefit_summary="Support for first successful Cyber Essentials certification via appointed certification route.",
        email_safe_claim_template="Based on the company profile, the Cyber Essentials support route appears worth checking for {{company_name}}, subject to programme confirmation.",
        do_not_claim=["guaranteed funding", "automatic eligibility", "full cost covered"],
        official_source_urls=[
            "https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-essentials/",
            "https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-essentials/certification-for-the-cyber-essentials-mark/",
        ],
        verification_status="needs_refresh",
        use_in_email_when="Entity type is SME, NPO, charity, or social-service with medium/high confidence and source refresh is verified_current.",
        do_not_claim_when="Entity type is unknown, source refresh is stale, or exact eligibility has not been checked.",
    ),
    FundingProgram(
        programme_id="csa_cyber_trust_first_cert_support",
        programme_name="Cyber Trust first successful certification support",
        framework_or_regime="Cyber Trust",
        relevant_entity_types=["sme", "npo", "charity", "social_service"],
        relevant_industries=["all"],
        benefit_summary="Support for first successful Cyber Trust certification via appointed certification route.",
        email_safe_claim_template="Based on the company profile, the Cyber Trust support route appears worth checking for {{company_name}}, subject to programme confirmation.",
        do_not_claim=["guaranteed funding", "automatic eligibility", "full cost covered"],
        official_source_urls=[
            "https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-trust/",
        ],
        verification_status="needs_refresh",
        use_in_email_when="Only when Cyber Trust is the recommended path and source refresh is verified_current.",
        do_not_claim_when="Cyber Essentials is the better first baseline, or source refresh is stale.",
    ),
    FundingProgram(
        programme_id="csa_hia_cisoaas_csds_essentials",
        programme_name="CISO-as-a-Service for HIA Cybersecurity and Data Security Essentials",
        framework_or_regime="HIA readiness",
        relevant_entity_types=["sme", "healthcare_provider", "clinic", "private_company"],
        relevant_industries=[
            "clinic",
            "healthcare",
            "medical",
            "outpatient",
            "dental",
            "pharmacy",
            "diagnostic",
            "hospital",
            "hearing",
            "hims",
            "nehr",
        ],
        benefit_summary="CSA CISOaaS route for HIA entities that need help meeting HIA cybersecurity and data-security essentials.",
        email_safe_claim_template="Based on the healthcare profile, the CISO-as-a-Service route for HIA Cybersecurity and Data Security Essentials appears worth checking for {{company_name}}, subject to programme confirmation.",
        do_not_claim=["guaranteed funding", "automatic eligibility", "full cost covered"],
        official_source_urls=[
            "https://www.healthinfo.gov.sg/funding-support/",
            "https://www.csa.gov.sg/cybersecurityhealthplan/",
        ],
        last_checked="2026-05-05",
        verification_status=VERIFIED_CURRENT,
        exact_claim_allowed_in_email=True,
        exact_claim_text="CSA states eligible SMEs can enjoy up to 70% co-funding support when signing up with CISOaaS consultants.",
        use_in_email_when="HIA relevance is medium/high, entity confidence is medium/high, and the organisation appears to be a Singapore healthcare SME or clinic.",
        do_not_claim_when="HIA scope is weak, entity type is unknown, or SME/funding eligibility has not been checked.",
    ),
    FundingProgram(
        programme_id="cisoaas_readiness_support",
        programme_name="CISO-as-a-Service / readiness support",
        framework_or_regime="CISO-as-a-Service",
        relevant_entity_types=["sme", "npo", "charity", "social_service", "healthcare_provider", "clinic", "private_company"],
        relevant_industries=["all"],
        benefit_summary="Configurable readiness support route for CISO-as-a-Service or implementation help.",
        email_safe_claim_template="Based on the company profile, a CISO-as-a-Service readiness support route appears worth checking for {{company_name}}, subject to programme confirmation.",
        do_not_claim=["up to 70%", "guaranteed funding", "automatic eligibility"],
        official_source_urls=[],
        verification_status="needs_official_source",
        use_in_email_when="Official source refresh verifies the current route and any exact percentage.",
        do_not_claim_when="No official source confirms current support level.",
    ),
    FundingProgram(
        programme_id="hia_nehr_connect_or_implementation_support",
        programme_name="HIA / NEHR Connect and implementation support routes",
        framework_or_regime="HIA readiness",
        relevant_entity_types=["healthcare_provider", "clinic"],
        relevant_industries=["healthcare", "clinic", "dental", "pharmacy", "diagnostic", "allied_health", "hearing_care"],
        benefit_summary="Potential HIA-related support routes including NEHR Connect Grant, PSG cybersecurity solutions, and implementation-readiness help.",
        email_safe_claim_template="For healthcare providers preparing for HIA, the relevant support routes may include HIA implementation and readiness support, subject to programme confirmation.",
        do_not_claim=["guaranteed funding", "automatic eligibility", "full cost covered"],
        official_source_urls=[
            "https://www.synapxe.sg/health-professionals/healthcare-digitalisation/nehr",
            "https://www.gobusiness.gov.sg/productivity-solutions-grant/",
        ],
        verification_status="needs_refresh",
        use_in_email_when="HIA relevance is medium/high and current support route has been verified.",
        do_not_claim_when="HIA scope is low-confidence or support route is not verified_current.",
    ),
    FundingProgram(
        programme_id="dptm_enterprise_singapore_ncss_support",
        programme_name="DPTM support routes via Enterprise Singapore / NCSS",
        framework_or_regime="DPTM",
        relevant_entity_types=["sme", "npo", "charity", "social_service"],
        relevant_industries=["all", "social_service"],
        benefit_summary="Possible support routes for broader data-protection governance when DPTM is the recommended path.",
        email_safe_claim_template="Based on the organisation profile, the DPTM support route appears worth checking, subject to programme confirmation.",
        do_not_claim=["guaranteed funding", "automatic eligibility", "full cost covered"],
        official_source_urls=[
            "https://www.enterprisesg.gov.sg/",
            "https://www.ncss.gov.sg/",
        ],
        verification_status="needs_refresh",
        use_in_email_when="DPTM is specifically recommended and source refresh is verified_current.",
        do_not_claim_when="Cyber Essentials is the recommended first cert or source refresh is stale.",
    ),
    FundingProgram(
        programme_id="dpe_framework_solution_provider_route",
        programme_name="DPE framework / solution-provider route",
        framework_or_regime="DPE",
        relevant_entity_types=["private_company", "sme"],
        relevant_industries=["all"],
        benefit_summary="Current public focus appears to be framework/solution providers; older grant material may exist.",
        email_safe_claim_template="A DPE support route needs human review before being used in outreach for {{company_name}}.",
        do_not_claim=["live fixed grant", "guaranteed funding", "automatic eligibility"],
        official_source_urls=["https://www.imda.gov.sg/"],
        verification_status="needs_refresh",
        use_in_email_when="Only after official refresh confirms current direct support for the row profile.",
        do_not_claim_when="Current source refresh does not verify live fixed-grant support.",
    ),
]


def normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def confidence_at_least(value: str, minimum: str) -> bool:
    return CONFIDENCE_ORDER.get(normalize(value), 0) >= CONFIDENCE_ORDER.get(minimum, 0)


def render_claim(program: FundingProgram, company_name: str) -> str:
    return program.email_safe_claim_template.replace("{{company_name}}", company_name).strip()


def industry_matches(program: FundingProgram, row: dict[str, Any]) -> bool:
    industries = {normalize(item) for item in program.relevant_industries}
    if "all" in industries:
        return True
    haystack = " ".join(
        str(row.get(key, ""))
        for key in (
            "industry_guess",
            "hia_service_type_guess",
            "entity_type_guess",
            "website_content",
            "company_name",
        )
    ).lower()
    return any(industry.replace("_", " ") in haystack or industry in haystack for industry in industries)


def entity_matches(program: FundingProgram, entity_type: str) -> bool:
    allowed = {normalize(item) for item in program.relevant_entity_types}
    normalized = normalize(entity_type)
    if normalized in allowed:
        return True
    if normalized == "clinic" and "healthcare_provider" in allowed:
        return True
    if normalized in {"npo", "charity", "social_service"} and allowed.intersection({"npo", "charity", "social_service"}):
        return True
    return False


def match_programmes(row: dict[str, Any], programmes: list[FundingProgram] | None = None) -> FundingMatch:
    programmes = programmes or PROGRAMMES
    company_name = str(row.get("company_name") or row.get("company_homepage_name") or "this organisation").strip()
    entity_type = normalize(row.get("entity_type_guess", "unknown"))
    entity_confidence = normalize(row.get("entity_type_confidence", "low"))
    hia_relevant = bool(row.get("hia_relevant"))
    hia_confidence = normalize(row.get("hia_confidence", "low"))
    recommended_first_cert = str(row.get("recommended_first_cert") or "Cyber Essentials")

    if entity_type == "unknown" or not confidence_at_least(entity_confidence, "medium"):
        possible = [program.to_dict() for program in programmes if entity_type == "unknown" or entity_matches(program, entity_type)]
        return FundingMatch(
            funding_status="needs_review",
            funding_relevant=bool(possible),
            primary_funding_program=possible[0]["programme_name"] if possible else "",
            possible=possible,
            funding_eligibility_basis="Entity type confidence is low or unknown; funding route needs human review.",
            funding_claim_line="Funding route needs human review before use.",
            funding_confidence="low",
            funding_source_urls=sorted({url for program in possible for url in program.get("official_source_urls", [])}),
            funding_human_review_required=True,
            reason="low_entity_confidence",
        )

    candidates: list[FundingProgram] = []
    for program in programmes:
        if not entity_matches(program, entity_type):
            continue
        if not industry_matches(program, row):
            continue
        if program.framework_or_regime == "HIA readiness" and not (hia_relevant and confidence_at_least(hia_confidence, "medium")):
            continue
        if program.framework_or_regime in {"DPE", "DPTM", "Cyber Trust"} and program.framework_or_regime not in recommended_first_cert:
            continue
        candidates.append(program)

    if not candidates:
        return FundingMatch(
            funding_status="not_applicable",
            funding_relevant=False,
            primary_funding_program="",
            not_applicable=[program.to_dict() for program in programmes],
            funding_eligibility_basis="No funding programme matched the current entity and pressure profile.",
            funding_claim_line="No funding route should be used for this row yet.",
            funding_confidence="low",
            funding_human_review_required=True,
            reason="no_programme_match",
        )

    primary = candidates[0]
    verified = primary.verification_status == VERIFIED_CURRENT
    exact_allowed = primary.exact_claim_allowed_in_email and primary.exact_claim_text
    claim = render_claim(primary, company_name)
    if exact_allowed:
        claim = f"{claim} {primary.exact_claim_text}".strip()
    status = "verified_match" if verified else "possible_match"
    confidence = "high" if verified and confidence_at_least(entity_confidence, "high") else "medium" if verified else "low"
    return FundingMatch(
        funding_status=status,
        funding_relevant=True,
        primary_funding_program=primary.programme_name,
        matched=[primary.to_dict()] if verified else [],
        possible=[] if verified else [program.to_dict() for program in candidates],
        funding_eligibility_basis=(
            f"Entity profile is {entity_type}; programme source status is {primary.verification_status}."
        ),
        funding_claim_line=claim if verified else "Funding route needs human review before use.",
        funding_cta_asset="hia_support_route_summary" if primary.framework_or_regime == "HIA readiness" else "funding_route_summary",
        funding_confidence=confidence,
        funding_last_checked_at=primary.last_checked or "",
        funding_source_urls=primary.official_source_urls,
        funding_human_review_required=not verified,
        reason="verified_programme_match" if verified else "programme_source_needs_refresh",
    )


def catalogue_as_dicts(programmes: list[FundingProgram] | None = None) -> list[dict[str, Any]]:
    return [program.to_dict() for program in (programmes or PROGRAMMES)]
