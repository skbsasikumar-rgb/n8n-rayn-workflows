from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.request import Request, urlopen


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
VERIFIED_CURRENT = "verified_current"
NCSS_MEMBER_DIRECTORY_URL = "https://maps.gov.sg/ncss-members"
NCSS_TSS_SOURCE_URL = "https://www.ncss.gov.sg/grants/organisation-development/transformation-sustainability-scheme/"
NCSS_MEMBERSHIP_SOURCE_URL = "https://www.ncss.gov.sg/about-us/ncss-membership/"
NCSS_MEMBER_SNAPSHOT_PATH = Path(__file__).with_name("ncss_members_snapshot.json")
_NCSS_MEMBER_CACHE: dict[str, Any] = {"loaded_at": 0.0, "members": {}}


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
    requires_ncss_member: bool = False

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
        programme_id="ncss_tss_member_digitalisation_support",
        programme_name="NCSS Transformation Sustainability Scheme (TSS)",
        framework_or_regime="NCSS TSS",
        relevant_entity_types=["npo", "charity", "social_service"],
        relevant_industries=["all", "social_service"],
        benefit_summary=(
            "NCSS TSS supports eligible social service agencies for consultancy, digital projects, "
            "and project implementation support."
        ),
        email_safe_claim_template=(
            "The NCSS member directory lists {{company_name}}; the Transformation Sustainability Scheme "
            "appears worth checking for eligible consultancy or digitalisation support, subject to programme requirements."
        ),
        do_not_claim=["guaranteed funding", "automatic eligibility", "full cost covered"],
        official_source_urls=[NCSS_TSS_SOURCE_URL, NCSS_MEMBERSHIP_SOURCE_URL, NCSS_MEMBER_DIRECTORY_URL],
        last_checked="2026-05-31",
        verification_status=VERIFIED_CURRENT,
        exact_claim_allowed_in_email=True,
        exact_claim_text=(
            "NCSS states TSS funding is available to social service agencies across three components, "
            "at up to 80% co-funding."
        ),
        use_in_email_when=(
            "Only when the organisation has an exact or high-confidence normalised match in the NCSS "
            "member directory and appears to be an NPO, charity, or social-service agency."
        ),
        do_not_claim_when=(
            "The organisation is not found in the NCSS member directory, "
            "or membership evidence cannot be fetched."
        ),
        requires_ncss_member=True,
    ),
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


def normalize_member_key(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"\bwww\.", "", text)
    text = re.sub(r"\.(?:org|com|net|sg)(?:\.sg)?\b", " ", text)
    text = re.sub(r"\b(?:pte|ltd|limited|society|singapore|the|company|co)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def candidate_member_names(row: dict[str, Any]) -> list[str]:
    values = [
        row.get("company_name"),
        row.get("company_homepage_name"),
        row.get("parent_company"),
    ]
    website = str(row.get("website_content") or "")
    heading = re.search(r"^\s*#\s+([^\n#]{2,140})", website, re.M)
    if heading:
        title = heading.group(1).strip()
        values.extend([title, re.split(r"\s*[|\u2013-]\s*", title, maxsplit=1)[0]])
    for key in ("best_url", "url_picked", "manual_url_override"):
        url = str(row.get(key) or "")
        host = re.sub(r"^https?://", "", url).split("/", 1)[0].lower()
        if host:
            values.extend([host, host.split(".")[0]])
    candidates: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text not in candidates:
            candidates.append(text)
    return candidates


def extract_ncss_member_names(html: str) -> list[str]:
    start = html.find('\\"mapMarkers\\"')
    segment = html[start:] if start >= 0 else html
    names: list[str] = []
    for raw in re.findall(r'\\"name\\":\\"(.*?)\\"', segment):
        try:
            name = json.loads(f'"{raw}"')
        except Exception:
            name = raw.encode("utf-8").decode("unicode_escape", errors="ignore")
        if "\\u" in name:
            name = name.encode("utf-8").decode("unicode_escape", errors="ignore")
        name = str(name).strip()
        if name and name not in names:
            names.append(name)
    return names


def fetch_ncss_member_directory(ttl_seconds: int = 24 * 60 * 60) -> dict[str, str]:
    now = time.time()
    cached = _NCSS_MEMBER_CACHE.get("members")
    if cached and now - float(_NCSS_MEMBER_CACHE.get("loaded_at") or 0) < ttl_seconds:
        return dict(cached)
    members: dict[str, str] = {}
    try:
        request = Request(NCSS_MEMBER_DIRECTORY_URL, headers={"User-Agent": "rayn-outreach-planner/1.0"})
        with urlopen(request, timeout=15) as response:
            html = response.read().decode("utf-8", errors="replace")
        members = member_key_map(extract_ncss_member_names(html))
    except Exception:
        members = {}
    if len(members) < 400:
        members = member_key_map(load_ncss_member_snapshot())
    _NCSS_MEMBER_CACHE["loaded_at"] = now
    _NCSS_MEMBER_CACHE["members"] = members
    return dict(members)


def member_key_map(names: list[str]) -> dict[str, str]:
    members: dict[str, str] = {}
    for name in names:
        key = normalize_member_key(name)
        if key:
            members.setdefault(key, name)
    return members


def load_ncss_member_snapshot() -> list[str]:
    try:
        payload = json.loads(NCSS_MEMBER_SNAPSHOT_PATH.read_text())
    except Exception:
        return []
    members = payload.get("members") if isinstance(payload, dict) else []
    if not isinstance(members, list):
        return []
    return [str(name).strip() for name in members if str(name).strip()]


def ncss_member_match(row: dict[str, Any]) -> dict[str, str] | None:
    try:
        members = fetch_ncss_member_directory()
    except Exception:
        return None
    for candidate in candidate_member_names(row):
        key = normalize_member_key(candidate)
        if len(key) < 3 and key != "4s":
            continue
        if key in members:
            return {"name": members[key], "source_url": NCSS_MEMBER_DIRECTORY_URL, "basis": f"directory_match:{candidate}"}
    return None


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
    ncss_lookup_attempted = False
    ncss_match: dict[str, str] | None = None

    def get_ncss_match() -> dict[str, str] | None:
        nonlocal ncss_lookup_attempted, ncss_match
        if not ncss_lookup_attempted:
            ncss_match = ncss_member_match(row)
            ncss_lookup_attempted = True
        return ncss_match

    if entity_type == "unknown" or not confidence_at_least(entity_confidence, "medium"):
        possible = [
            program.to_dict()
            for program in programmes
            if not program.requires_ncss_member and (entity_type == "unknown" or entity_matches(program, entity_type))
        ]
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
        if program.requires_ncss_member and not get_ncss_match():
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
    claim_company_name = ncss_match["name"] if primary.requires_ncss_member and ncss_match else company_name
    claim = render_claim(primary, claim_company_name)
    if exact_allowed:
        claim = f"{claim} {primary.exact_claim_text}".strip()
    status = "verified_match" if verified else "possible_match"
    confidence = "high" if verified and confidence_at_least(entity_confidence, "high") else "medium" if verified else "low"
    return FundingMatch(
        funding_status=status,
        funding_relevant=True,
        primary_funding_program=primary.programme_name,
        matched=[
            {
                **primary.to_dict(),
                **(
                    {
                        "ncss_member_name": ncss_match["name"],
                        "ncss_member_source_url": ncss_match["source_url"],
                        "ncss_member_match_basis": ncss_match["basis"],
                    }
                    if primary.requires_ncss_member and ncss_match
                    else {}
                ),
            }
        ] if verified else [],
        possible=[] if verified else [program.to_dict() for program in candidates],
        funding_eligibility_basis=(
            f"Entity profile is {entity_type}; programme source status is {primary.verification_status}."
            + (f" NCSS member directory match: {ncss_match['name']}." if primary.requires_ncss_member and ncss_match else "")
        ),
        funding_claim_line=claim if verified else "Funding route needs human review before use.",
        funding_cta_asset=(
            "hia_support_route_summary"
            if primary.framework_or_regime == "HIA readiness"
            else "ncss_tss_route_summary"
            if primary.framework_or_regime == "NCSS TSS"
            else "funding_route_summary"
        ),
        funding_confidence=confidence,
        funding_last_checked_at=primary.last_checked or "",
        funding_source_urls=primary.official_source_urls,
        funding_human_review_required=not verified,
        reason="verified_programme_match" if verified else "programme_source_needs_refresh",
    )


def catalogue_as_dicts(programmes: list[FundingProgram] | None = None) -> list[dict[str, Any]]:
    return [program.to_dict() for program in (programmes or PROGRAMMES)]
