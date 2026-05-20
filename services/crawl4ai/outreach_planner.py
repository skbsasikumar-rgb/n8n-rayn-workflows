from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

try:
    from .funding_programs import FundingMatch, match_programmes
except ImportError:  # pragma: no cover - service runtime imports modules from cwd
    from funding_programs import FundingMatch, match_programmes


PROVIDER_ACCOUNT_ERROR_PATTERNS = (
    "provider account error",
    "provider_account_error",
    "insufficient balance",
    "zero balance",
    "balance not enough",
    "no funds",
    "out of funds",
    "insufficient funds",
    "credit",
    "quota",
    "billing",
    "payment required",
    "invalid api key",
    "invalid key",
    "wrong api key",
    "api key",
    "unauthorized",
    "too many requests",
    "rate limit",
)


class ProviderAccountError(RuntimeError):
    """Raised when an LLM provider account/key/credit problem needs operator action."""


def is_provider_account_error(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    normalized = re.sub(r"[_-]+", " ", text.lower())
    return any(pattern.replace("_", " ") in normalized for pattern in PROVIDER_ACCOUNT_ERROR_PATTERNS)


def openrouter_error_text(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return compact(error.get("message") or error.get("code") or payload)
            return compact(payload.get("message") or error or payload)
    except Exception:
        pass
    return compact(response.text)[:500] or f"HTTP {response.status_code}"


def raise_for_openrouter_account_error(response: requests.Response, context: str) -> None:
    if response.status_code < 400:
        return
    message = openrouter_error_text(response)
    if response.status_code in {401, 402, 429} or is_provider_account_error(message):
        raise ProviderAccountError(f"provider_account_error: {context}: {message}")


LLM_CLASSIFICATION_PROMPT = """System:
You classify Singapore organisations for cyber/data certification outreach. Use only provided evidence. Return strict JSON only. Do not invent facts.

User input:
- company_name
- website_url
- website_scrape
- page_sources
- services_detected
- locations_detected
- leadership_or_team_signals
- contact_info_detected
- structured_data_detected
- industry_guess
- company_homepage_name
- parent_company
- selected_contact_title
- existing enrichment fields

First decide the pressure type:
- HIA regulatory pressure
- PDPA personal-data safeguard pressure
- Customer/procurement trust pressure
- Funding/budget pressure

Use HIA regulatory pressure when HIA evidence is medium/high. Use PDPA personal-data safeguard pressure when the organisation handles personal data and HIA is not the primary trigger. Use customer/procurement trust pressure when B2B, SaaS, outsourcing, education, finance, HR/recruitment, professional-services, vendor or enterprise-facing evidence is present. Use not_ready when the evidence does not support any outreach track.

Return strict JSON:
{
  "entity_type_guess": "sme|npo|charity|social_service|healthcare_provider|clinic|private_company|sole_proprietor|partnership|foreign_entity_sg_ops|unknown",
  "entity_type_confidence": "low|medium|high",
  "singapore_registered_guess": true,
  "sme_likelihood": "likely|possible|unlikely|unknown",
  "npo_likelihood": "likely|possible|unlikely|unknown",
  "charity_or_social_service_likelihood": "likely|possible|unlikely|unknown",
  "pressure_type": "hia_regulatory|pdpa_safeguards|customer_trust|funding|not_ready",
  "pressure_reason": "",
  "outreach_trigger_signal": "",
  "outreach_trigger_source_url": "",
  "outreach_trigger_confidence": "low|medium|high",
  "data_type_signal": "patient_data|health_information|resident_data|beneficiary_data|customer_data|employee_data|student_data|financial_data|business_partner_data|unknown",
  "problem_area": "access_control|data_mapping|offboarding|backup|patching|malware_protection|incident_response|vendor_management|staff_awareness|evidence_collection|hia_readiness|pdpa_safeguards|unknown",
  "problem_hypothesis": "",
  "value_asset_offer": "hia_readiness_map|clinic_access_checklist|solo_gp_checklist|pdpa_safeguards_checklist|data_access_map|offboarding_checklist|cyber_essentials_readiness_checklist|funding_route_summary|security_evidence_checklist",
  "hia_relevant": false,
  "hia_relevance_score": 0,
  "hia_confidence": "low|medium|high",
  "hia_scope_reason": "",
  "hia_service_type_guess": "GP_OMS|specialist_OMS|dental|retail_pharmacy|diagnostic|hospital|allied_health|hearing_care|long_term_care|HIMS_provider|NEHR_user|unknown",
  "hia_timeline_batch_guess": "Batch 1 - Sep 2027|Batch 2 - Sep 2028|Batch 3 - Mar 2030|Other CS/DS by Sep 2028|unknown",
  "hia_deadline_claim_safe": false,
  "hia_disclaimer_needed": true,
  "pdpa_relevant": true,
  "pdpa_reason": "",
  "personal_data_intensity": "low|medium|high|unknown",
  "sensitive_data_likelihood": "low|medium|high|unknown",
  "pdpa_safeguard_angle": "access_control|data_inventory|vendor_management|breach_response|staff_training|cyber_essentials_baseline|unknown",
  "recommended_first_cert": "Cyber Essentials|DPE|DPTM|Cyber Trust|HIA readiness|unknown",
  "recommended_cert_path": "",
  "certification_reason": "",
  "certification_fit_score": 0,
  "evidence": [{"field": "", "quote": "", "source_url": "", "reason": ""}],
  "confidence": "low|medium|high"
}
"""

LLM_EMAIL_PROMPT = """System:
You write short, evidence-based cold email drafts for RAYN Secure. Use only enriched fields provided. Return strict JSON only.

User input:
- company_name
- first_name
- selected_contact_title
- entity_type_guess
- pressure_type
- outreach_variant
- outreach_trigger_signal
- data_type_signal
- problem_area
- problem_hypothesis
- value_asset_offer
- recommended_first_cert
- hia_relevant
- hia_timeline_batch_guess
- hia_deadline_claim_safe
- pdpa_relevant
- funding_status
- primary_funding_program
- funding_claim_line
- funding_cta_asset
- funding_confidence

Rules:
- First decide the pressure type: HIA regulatory pressure, PDPA personal-data safeguard pressure, customer/procurement trust pressure, or funding/budget pressure.
- Email 1 leads with pressure_type, not with RAYN's services.
- Email 2 is funding-only when funding is verified-safe; otherwise it gives a non-funding value-fallback asset.
- Email 3 gives a diagnostic tied to the same problem.
- Email 4 closes the loop.
- For HIA rows, lead with HIA timeline / regulatory readiness. Mention Cyber Essentials only as a practical first baseline. Do not say Cyber Essentials completes HIA compliance.
- For non-HIA rows, lead with PDPA / personal-data safeguards. Say Cyber Essentials supports the security-safeguards side of PDPA readiness. Do not say Cyber Essentials alone equals PDPA compliance.
- For DPO, compliance, privacy, operations, admin, or HR contacts, lead with data-protection evidence ownership across IT, HR, vendors and operations.
- For B2B rows, lead with customer security evidence and trust. Position Cyber Essentials as reusable proof.
- Do not invent eligibility.
- Do not use generic wording.
- Do not mention "if you are an SME/NPO".
- Do not mention Cyber Trust, DPE or DPTM unless recommended_first_cert or recommended_cert_path includes them.
- Do not ask for a meeting in email 1.
- CTA must be tiny: "Worth sending the checklist?", "Want the map?", "Should I send the route summary?"
- Keep emails plain text.

Return strict JSON:
{
  "email_1": {"subject_options": [], "chosen_subject": "", "body": "", "word_count": 0},
  "email_2": {"subject_options": [], "chosen_subject": "", "body": "", "word_count": 0},
  "email_3": {"subject_options": [], "chosen_subject": "", "body": "", "word_count": 0},
  "email_4": {"subject_options": [], "chosen_subject": "", "body": "", "word_count": 0},
  "evidence_used": [],
  "claims_avoided": [],
  "quality_notes": []
}
"""

FORBIDDEN_PHRASES = (
    "if you are an sme",
    "if you are an npo",
    "eligible smes and npos may",
    "you qualify",
    "you are eligible",
    "all clinics qualify for funding",
    "companies with higher assurance needs",
    "you are non-compliant",
    "guaranteed funding",
    "you will be hacked",
    "hia = cem",
    "cyber essentials makes you pdpa compliant",
    "fully hia compliant with cyber essentials",
    "transform your security",
    "unlock growth",
    "leading provider",
    "hope you are well",
    "i came across your company",
)

STYLE_BANNED_PHRASES = (
    "comprehensive",
    "robust",
    "tailored",
    "leverage",
    "landscape",
    "readiness journey",
    "certification work",
    "value proposition",
    "stakeholders",
    "end-to-end",
    "unlock",
    "empower",
    "delve",
    "furthermore",
    "moreover",
    "additionally",
    "practical question is whether",
)

AI_GIVEAWAY_PHRASES = (
    "dive into",
    "unleash",
    "game-changing",
    "revolutionary",
    "transformative",
    "leverage",
    "optimize",
    "unlock potential",
    "unlock the secrets",
)

EMAIL_1_REWRITE_PROMPT = """You rewrite two approved cold emails as one steady sequence.
Return strict JSON only. Do not add facts, claims, pricing, eligibility, locations, services, names, or vendor details.

Rules:
- Rewrite Email 1 and Email 2 only.
- Keep Email 1 and Email 2 linked: Email 1 opens the pain. Email 2 follows naturally into cost/support route.
- Keep the same recipient addressing style from each deterministic email.
- Keep every approved fact: company hook, problem, mechanism, CTA, asset, HIA/PDPA/customer-trust track, and support-route caution.
- You may improve flow and make it sound human. You may not change the meaning.
- Use "We", not "RAYN".
- Use simple words and short sentences.
- No marketing copy. No hype. No meeting ask.
- No "from the site".
- Avoid: dive into, unleash, game-changing, revolutionary, transformative, leverage, optimize, unlock potential, unlock the secrets.

Email 1 rules:
- Use 4 short paragraphs separated by blank lines.
- Paragraph 1: greeting plus a specific company hook, preferably a question if the approved context is concrete.
- Paragraph 2: problem / why now. Link it back to paragraph 1 with "that data", "that proof", "that trail", or similar plain wording.
- Paragraph 3: Cyber Essentials as a practical path, baseline, evidence map, or route.
- Paragraph 4: tiny CTA only.
- For HIA, mention HIA before Cyber Essentials.
- Keep Email 1 under 95 words.

Email 2 rules:
- This is the second and final touch.
- Keep the same first-name dash prefix if the deterministic email uses one, for example "Samuel - ".
- Do not restart with a new greeting unless the deterministic email does.
- Move from "if the asset/checklist/map is useful" to cost/support/funding route.
- For HIA tracks, mention HIA in the CTA or support-route line.
- For PDPA tracks, do not say Cyber Essentials replaces PDPA obligations. Say it can help structure evidence for security safeguards.
- Do not mention exact funding percentages, grants, or eligibility unless the deterministic email already does and funding_claim_safe is true.
- Do not mention exact prices. Do not say "second cheapest".
- Use 4 short paragraphs separated by blank lines.
- Keep the main body to 3 short paragraphs before the P.S.
- Keep this P.S. exactly as written:
  P.S. We are usually priced near the lower end, and the scope is heavier: evidence prep, certification support, and a SaaS tool to help the team stay certified.
- Keep Email 2 under 95 words. Aim for 85-92 words so it does not fail QA.
- If you cannot keep Email 2 under 95 words, stay close to the deterministic Email 2 structure and cut extra explanation.

Return:
{
  "email_1": {"subject": "", "body": ""},
  "email_2": {"subject": "", "body": ""},
  "notes": []
}
"""

CISOAAS_HIA_PRICING = {
    "package_name": "CISOaaS HIA / HIB / HIMS Vendor",
    "endpoint_band": "1_5",
    "starting_price_before_funding": 4300,
    "currency": "SGD",
    "price_text": "S$4,300",
    "source": "StaySecure CONTINUITY Suite Pricing.xlsx",
    "source_sheet": "CISOaaS (HIB & HIMS Vendor)",
    "funding_caveat": "subject to programme confirmation",
}

HEALTHCARE_TERMS = (
    "clinic",
    "doctor",
    "medical",
    "outpatient",
    "general practitioner",
    "gp",
    "specialist",
    "dental",
    "dentist",
    "pharmacy",
    "diagnostic",
    "hospital",
    "clinical laboratory",
    "laboratory",
    "radiology",
    "nuclear medicine",
    "renal dialysis",
    "ambulatory surgical",
    "assisted reproduction",
    "physio",
    "physiotherapy",
    "allied health",
    "psychology",
    "psychologist",
    "mental health",
    "counselling",
    "counseling",
    "hearing",
    "audiology",
    "hospice",
    "palliative",
    "nursing home",
    "long-term care",
    "long term care",
    "patient",
    "health screening",
    "treatment",
    "fertility",
    "ivf",
)
AMBIGUOUS_HIA_TERMS = (
    "aesthetic",
    "aesthetics",
    "wellness",
    "therapy",
    "therapist",
    "care",
    "healthcare",
    "health care",
    "hearing",
    "audiology",
    "medical device",
    "medical devices",
    "rehabilitation",
    "screening",
    "test",
    "tests",
)
HIA_OFFICIAL_SERVICE_LABELS = {
    "outpatient_medical_gp": "Outpatient Medical Service (GP)",
    "outpatient_medical_specialist": "Outpatient Medical Service (Specialist)",
    "outpatient_dental": "Outpatient Dental",
    "acute_hospital": "Acute Hospital",
    "nursing_home": "Nursing Home",
    "ambulatory_surgical_centre": "Ambulatory Surgical Centre",
    "community_hospital": "Community Hospital",
    "contingency_care_service": "Contingency Care Service",
    "assisted_reproduction": "Assisted Reproduction",
    "clinical_laboratory": "Clinical Laboratory",
    "outpatient_renal_dialysis": "Outpatient Renal Dialysis",
    "retail_pharmacy": "Retail Pharmacy",
    "radiology_laboratory": "Radiology Laboratory",
    "nuclear_medicine_service": "Nuclear Medicine Service",
}
HIA_BATCH_BY_OFFICIAL_SERVICE = {
    "outpatient_medical_gp": "Batch 1 - Sep 2027",
    "acute_hospital": "Batch 1 - Sep 2027",
    "clinical_laboratory": "Batch 1 - Sep 2027",
    "radiology_laboratory": "Batch 1 - Sep 2027",
    "nuclear_medicine_service": "Batch 1 - Sep 2027",
    "outpatient_medical_specialist": "Batch 2 - Sep 2028",
    "nursing_home": "Batch 2 - Sep 2028",
    "community_hospital": "Batch 2 - Sep 2028",
    "assisted_reproduction": "Batch 2 - Sep 2028",
    "outpatient_renal_dialysis": "Batch 2 - Sep 2028",
    "outpatient_dental": "Batch 3 - Mar 2030",
    "ambulatory_surgical_centre": "Batch 3 - Mar 2030",
    "contingency_care_service": "Batch 3 - Mar 2030",
    "retail_pharmacy": "Batch 3 - Mar 2030",
}
HIA_BATCH_BY_SERVICE = {
    "GP_OMS": "Batch 1 - Sep 2027",
    "hospital": "Batch 1 - Sep 2027",
    "diagnostic": "Batch 1 - Sep 2027",
    "specialist_OMS": "Batch 2 - Sep 2028",
    "long_term_care": "Batch 2 - Sep 2028",
    "dental": "Batch 3 - Mar 2030",
    "retail_pharmacy": "Batch 3 - Mar 2030",
}
NPO_TERMS = ("charity", "society", "mission", "foundation", "volunteer", "donation", "ncss", "ipc", "beneficiary")
SOCIAL_TERMS = ("resident", "beneficiary", "care", "nursing home", "community", "social service", "eldercare")
STRONG_NPO_TERMS = ("charity", "ipc", "ncss", "social service", "beneficiary", "beneficiaries", "volunteer", "donation")
STRONG_SOCIAL_SERVICE_TERMS = (
    "social service",
    "ncss",
    "ipc",
    "beneficiary",
    "beneficiaries",
    "casework",
    "eldercare",
    "elder care",
    "nursing home",
    "residential care",
    "resident care",
    "welfare",
)
CLINICAL_ENTITY_NAME_TERMS = (
    "clinic",
    "medical",
    "dental",
    "hospital",
    "pharmacy",
    "hearing",
    "physio",
    "podiatry",
    "podiatrist",
    "visioncare",
    "optometry",
    "surgery",
    "surgical",
    "laboratory",
    "lab",
    "dialysis",
    "healthcare",
    "cardiology",
    "gastroenterology",
    "colorectal",
    "oncology",
    "cancer",
    "fertility",
    "ivf",
    "psychology",
    "physiotherapy",
    "kidney",
    "renal",
)
CLINICAL_CARE_EVIDENCE_TERMS = (
    "patient",
    "patients",
    "appointment",
    "appointments",
    "assessment",
    "assessments",
    "treatment",
    "treatments",
    "consultation",
    "consultations",
    "doctor",
    "doctors",
    "clinician",
    "clinical",
    "outpatient",
    "case-note",
    "case note",
    "medical record",
    "medical records",
    "health record",
    "health records",
)
WEAK_SPECIALIST_HIA_TERMS = (
    "optometry",
    "optometrist",
    "optometrists",
    "visioncare",
    "vision care",
    "eye care",
    "aesthetic",
    "aesthetics",
    "wellness",
)
STRONG_EYE_CLINICAL_TERMS = (
    "ophthalmology clinic",
    "ophthalmology centre",
    "ophthalmology center",
    "ophthalmologist clinic",
    "eye specialist",
    "eye centre",
    "eye center",
    "cataract surgery",
    "retina specialist",
    "retina clinic",
    "lasik surgery",
    "eye surgery",
    "eye surgeon",
    "medical eye clinic",
    "specialist eye clinic",
)
SPECIALIST_SERVICE_TERMS = (
    "cancer centre",
    "cancer center",
    "cancer care",
    "fertility",
    "ivf",
    "assisted reproduction",
    "reproductive medicine",
    "oncology",
    "radiation",
    "endocrinology",
    "orthopaedic",
    "orthopedic",
    "digestive",
    "gastroenterology",
    "rheumatology",
    "rheumatologist",
    "arthritis",
    "lupus",
    "cardiology",
    "heart clinic",
    "heart centre",
    "heart center",
    "heart & vascular",
    "cardiac",
    "cardiovascular",
    "ecg",
    "echocardiogram",
    "dermatology",
    "dermatologist",
    "pain management",
    "anaesthesia",
    "spine pain",
    "injections",
    "ophthalmology",
    "ophthalmologist",
    "cataract",
    "retina",
    "lasik",
    "optometry",
    "plastic surgery",
    "aesthetic",
    "surgery",
    "surgeon",
    "surgical",
    "specialist",
)
SPECIFIC_SPECIALIST_SERVICE_TERMS = tuple(
    term for term in SPECIALIST_SERVICE_TERMS if term != "specialist" and term not in WEAK_SPECIALIST_HIA_TERMS
)
DIAGNOSTIC_SERVICE_TERMS = (
    "diagnostic",
    "diagnostics",
    "molecular diagnostic",
    "molecular diagnostics",
    "radiology",
    "clinical laboratory",
    "laboratory",
    "nuclear medicine",
    "health screening",
    "screening centre",
    "screening center",
)
LONG_TERM_CARE_TERMS = (
    "hospice",
    "palliative",
    "nursing home",
    "long term care",
    "long-term care",
    "eldercare",
    "caregiver",
    "home care",
    "home nursing",
    "patient care at home",
    "lodge",
)
B2B_TERMS = (
    "enterprise",
    "vendor",
    "outsourcing",
    "saas",
    "software",
    "platform",
    "managed service",
    "consulting",
    "professional services",
    "recruitment",
    "hr",
    "finance",
    "financial",
    "education",
    "clients",
    "partners",
    "procurement",
)
DPO_TITLE_TERMS = ("dpo", "data protection", "privacy", "compliance", "operations", "admin", "administrator", "hr", "human resource")
PERSONAL_DATA_TERMS = (
    "personal data",
    "customer data",
    "customer enquiries",
    "employee data",
    "staff data",
    "partner data",
    "client data",
    "contact form",
    "newsletter",
    "registration",
    "course",
    "courses",
    "class",
    "classes",
    "parenting",
    "parents",
    "families",
    "payment",
)
SENSITIVE_TERMS = ("patient", "health", "medical", "resident", "beneficiary", "student", "financial")

STRONG_CUSTOMER_TRUST_TERMS = (
    "enterprise",
    "vendor",
    "outsourcing",
    "saas",
    "software",
    "platform",
    "managed service",
    "consulting",
    "professional services",
    "partners",
    "procurement",
    "customer review",
    "security questionnaire",
    "corporate customer",
    "business customer",
)


@dataclass
class OutreachPlan:
    row_id: Any
    classification: dict[str, Any]
    funding: FundingMatch
    copy_brief: dict[str, Any]
    emails: dict[str, Any]
    quality_score: int
    quality_flags: list[str] = field(default_factory=list)
    email_send_ready: bool = False
    human_review_status: str = "ready_for_review"
    automation_decision: str = "draft_only_review"
    automation_decision_reason: str = ""
    automation_blockers: list[str] = field(default_factory=list)
    automation_advisory_flags: list[str] = field(default_factory=list)
    contact_send_mode: str = "generic_team"
    contact_identity_confidence: str = "none"
    email_2_mode: str = "value_fallback"
    funding_followup_mode: str = "value_fallback"
    email_3_mode: str = "value_fallback"
    enrichment_quality_score: int = 0
    enrichment_quality_flags: list[str] = field(default_factory=list)
    copy_brief_quality_score: int = 0
    copy_brief_quality_flags: list[str] = field(default_factory=list)
    severe_email_flags: list[str] = field(default_factory=list)
    final_send_gate_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["funding"] = self.funding.to_dict()
        return data


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


LOCATION_HINTS = {
    "ang mo kio",
    "bedok",
    "bishan",
    "bukit batok",
    "bukit merah",
    "bukit timah",
    "changi",
    "choa chu kang",
    "clementi",
    "geylang",
    "hougang",
    "jurong",
    "kallang",
    "marine parade",
    "novena",
    "orchard",
    "pasir ris",
    "punggol",
    "queenstown",
    "raffles",
    "sengkang",
    "serangoon",
    "sin ming",
    "tampines",
    "toa payoh",
    "woodlands",
    "yishun",
}


def email_display_company_name(row: dict[str, Any] | str) -> str:
    raw = row if isinstance(row, str) else row.get("company_name") or row.get("company_homepage_name")
    name = compact(raw)
    if not name:
        return "your organisation"
    name = re.sub(r"\b(?:pte\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|llp|llc|inc\.?)\b\.?", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" ,-")

    def strip_location_parentheses(match: re.Match[str]) -> str:
        inner = compact(match.group(1)).lower()
        if inner in LOCATION_HINTS or (len(inner.split()) <= 3 and not re.search(r"\b(?:group|clinic|medical|health|care)\b", inner)):
            return " "
        return match.group(0)

    name = re.sub(r"\(([^)]{2,40})\)", strip_location_parentheses, name)
    name = re.sub(r"\s+@\s+[A-Za-z][A-Za-z .'-]{1,40}$", "", name)
    name = re.sub(r"\s+-\s+[A-Za-z][A-Za-z .'-]{1,40}$", "", name)
    name = re.sub(r"\s+", " ", name).strip(" ,-")
    return name or compact(raw) or "your organisation"


TRAILING_SIGNATURE_RE = re.compile(
    r"(?:\n\s*){2,}(?:best|regards|thanks|thank you),?\s*(?:\n\s*(?:sk|sasikumar))?\s*(?:\n\s*rayn secure)?\s*$",
    re.IGNORECASE,
)


def strip_trailing_signature(body: str) -> str:
    return TRAILING_SIGNATURE_RE.sub("", str(body or "")).rstrip()


def sendable_email(row: dict[str, Any]) -> str:
    return compact(row.get("validated_email"))


GENERIC_EMAIL_LOCAL_PARTS = {
    "admin",
    "appointment",
    "appointments",
    "clinic",
    "contact",
    "contactus",
    "enquiries",
    "enquiry",
    "general",
    "hello",
    "info",
    "mail",
    "reception",
    "sales",
    "service",
    "support",
    "team",
}


def selected_email(row: dict[str, Any]) -> str:
    return compact(row.get("validated_email") or row.get("selected_contact_email")).lower()


def is_generic_or_company_inbox(row: dict[str, Any]) -> bool:
    email = selected_email(row)
    if not email or "@" not in email:
        return False
    local_part = email.partition("@")[0].lower()
    return local_part in GENERIC_EMAIL_LOCAL_PARTS


def can_contact(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("do_not_contact") is True or compact(row.get("do_not_contact")).lower() == "true":
        return False, "suppressed_do_not_contact"
    status = compact(row.get("unsubscribe_status") or "active").lower()
    if status in {"unsubscribed", "bounced", "complained"}:
        return False, f"suppressed_{status}"
    if not sendable_email(row) and not row.get("copy_qa_mode"):
        return False, "suppressed_missing_validated_email"
    return True, ""


def contact_identity_confidence(row: dict[str, Any]) -> str:
    email = selected_email(row)
    name = compact(row.get("selected_contact_name"))
    if not email or is_generic_or_company_inbox(row) or not valid_person_contact_name(name):
        return "none"
    first = first_name_from_contact(name).lower()
    name_parts = [part.lower() for part in re.findall(r"[a-z0-9]+", name) if part.lower() not in {"dr", "mr", "mrs", "ms", "miss", "mdm", "prof"}]
    local = email.partition("@")[0].lower()
    evidence_blob = " ".join(
        compact(row.get(field)).lower()
        for field in (
            "contact_search_reason",
            "contact_search_status",
            "email_validation_provider",
            "email_validation_status",
            "email_validation_summary",
            "contact_candidates_json",
            "email_candidates_json",
            "email_validation_evidence_json",
            "email_source",
            "selected_contact_title",
            "selected_contact_role",
        )
    )
    if any(term in evidence_blob for term in ("inferred_name_partially_proved", "identity_partially_proved", "personal_company_email_identity_unresolved")):
        return "low"
    if any(term in evidence_blob for term in ("linkedin", "anymail person", "person match", "matched person", "identity confirmed", "accepted person", "decision maker")):
        return "high"
    if first and first in local:
        return "high" if any(term in evidence_blob for term in ("deliverable", "valid", "accepted", "no2bounce", "anymail")) else "medium"
    if any(part for part in name_parts if len(part) >= 4 and part in local):
        return "medium"
    if any(term in evidence_blob for term in ("deliverable", "valid", "accepted")):
        return "low"
    return "low"


def contact_send_mode(row: dict[str, Any]) -> str:
    ok, _ = can_contact(row)
    if not ok:
        return "suppressed"
    if is_generic_or_company_inbox(row):
        return "generic_team"
    if contact_identity_confidence(row) in {"medium", "high"}:
        return "named_person"
    return "generic_team"


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = compact(value)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def host_from_url(value: Any) -> str:
    text = compact(value).lower()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    text = re.sub(r"^[a-z]+://", "", text, flags=re.I).split("/", 1)[0]
    text = text.split("@")[-1].split(":", 1)[0]
    return re.sub(r"^www\.", "", text)


def domain_from_email(value: Any) -> str:
    email = compact(value).lower()
    if "@" not in email:
        return ""
    return host_from_url(email.rsplit("@", 1)[1])


def company_domain(row: dict[str, Any]) -> str:
    for field in ("canonical_domain", "best_url", "company_url", "website_url"):
        host = host_from_url(row.get(field))
        if host:
            return host
    return ""


def domain_country_suffix(domain: str) -> str:
    parts = domain.split(".")
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return parts[-1]
    return ""


def json_blob(value: Any) -> str:
    parsed = parse_jsonish(value)
    if parsed is None:
        return compact(value)
    try:
        return json.dumps(parsed, sort_keys=True)
    except Exception:
        return compact(value)


def selected_contact_was_rejected(row: dict[str, Any]) -> bool:
    name = compact(row.get("selected_contact_name")).lower()
    email = selected_email(row)
    if not name and not email:
        return False
    evidence = parse_jsonish(row.get("contact_search_evidence_json"))
    if not isinstance(evidence, dict):
        return False
    rejected = evidence.get("rejected_candidates") or evidence.get("rejected") or []
    if not isinstance(rejected, list):
        return False
    email_local = email.partition("@")[0].replace(".", " ").replace("_", " ")
    for candidate in rejected:
        if not isinstance(candidate, dict):
            continue
        reason = compact(candidate.get("reason_code") or candidate.get("reason")).lower()
        if "not_target_company" not in reason and "not target" not in reason:
            continue
        raw = compact(candidate.get("raw_name") or candidate.get("name") or candidate.get("contact_name")).lower()
        candidate_email = compact(candidate.get("email")).lower()
        if (name and raw and (name in raw or raw in name)) or (candidate_email and candidate_email == email):
            return True
        if raw and email_local and raw.replace(".", " ") in email_local:
            return True
    return False


def validation_evidence_supports_alternate_domain(row: dict[str, Any], email_domain: str, site_domain: str) -> bool:
    evidence = " ".join(
        json_blob(row.get(field)).lower()
        for field in (
            "email_validation_evidence_json",
            "email_candidates_json",
            "email_validation_summary",
            "email_source",
        )
    )
    if not evidence or email_domain not in evidence or site_domain not in evidence:
        return False
    return any(term in evidence for term in ("accepted", "valid", "deliverable", "person_domain", "anymail"))


def website_mentions_email_domain(row: dict[str, Any], email_domain: str) -> bool:
    if not email_domain:
        return False
    haystack = " ".join(
        compact(row.get(field)).lower()
        for field in (
            "website_content",
            "source_urls",
            "contact_info_detected",
            "structured_data_detected",
            "selected_contact_source_url",
        )
    )
    return email_domain in haystack


def contact_provenance_review_reason(row: dict[str, Any], mode: str) -> str:
    if mode not in {"named_person", "generic_team"}:
        return ""
    email_domain = domain_from_email(selected_email(row))
    site_domain = company_domain(row)
    if not email_domain or not site_domain or email_domain == site_domain:
        return ""
    if selected_contact_was_rejected(row):
        return "rejected_contact_reused_by_fallback"
    email_country = domain_country_suffix(email_domain)
    site_country = domain_country_suffix(site_domain)
    if email_country and site_country and email_country != site_country:
        return "cross_domain_contact_review"
    if website_mentions_email_domain(row, email_domain):
        return ""
    if validation_evidence_supports_alternate_domain(row, email_domain, site_domain):
        return ""
    if mode == "generic_team":
        return "cross_domain_contact_review"
    evidence = " ".join(
        json_blob(row.get(field)).lower()
        for field in ("email_validation_evidence_json", "email_candidates_json", "selected_contact_linkedin_url", "email_source")
    )
    fallback_terms = ("decision_maker_fallback", "decision maker fallback", "anymail_finder_decision_maker")
    if any(term in evidence for term in fallback_terms):
        return "cross_domain_contact_review"
    return ""


NON_PERSON_CONTACT_NAME_TERMS = {
    "admin",
    "admissions",
    "appointment",
    "appointments",
    "centre",
    "center",
    "clinic",
    "committee",
    "contact",
    "department",
    "enquiry",
    "enquiries",
    "group",
    "info",
    "membership",
    "memberships",
    "office",
    "reception",
    "secretariat",
    "service",
    "support",
    "team",
}


def valid_person_contact_name(name: Any) -> bool:
    text = compact(name)
    if not text or "@" in text or "/" in text:
        return False
    parts = [part.lower() for part in re.findall(r"[a-z]+", text.lower()) if part]
    parts = [part for part in parts if part not in {"dr", "mr", "mrs", "ms", "miss", "mdm", "prof"}]
    if not parts or len(parts) > 5:
        return False
    if any(part in NON_PERSON_CONTACT_NAME_TERMS for part in parts):
        return False
    return any(len(part) >= 2 for part in parts)


def funding_claim_send_safe(funding: FundingMatch, copy_brief: dict[str, Any], classification: dict[str, Any]) -> bool:
    if funding.funding_status != "verified_match":
        return False
    if not copy_brief.get("funding_claim_safe"):
        return False
    if not compact(funding.funding_claim_line) or "needs human review" in funding.funding_claim_line.lower():
        return False
    if classification.get("entity_type_confidence") not in {"medium", "high"}:
        return False
    matched = funding.matched or []
    if not matched:
        return False
    if not any(item.get("verification_status") == "verified_current" for item in matched):
        return False
    if re.search(r"\b\d{1,3}%\b", funding.funding_claim_line) and not any(item.get("exact_claim_allowed_in_email") for item in matched):
        return False
    return True


def value_fallback_email_2(
    row: dict[str, Any],
    emails: dict[str, Any],
    asset: str | None = None,
    classification: dict[str, Any] | None = None,
    copy_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prefix = followup_name_prefix(row, "-")
    asset_name = compact(asset) or "checklist"
    subject = "readiness evidence"
    subject_options = ["readiness evidence", "checklist"]
    if classification is not None and copy_brief is not None:
        fallback_subjects = {"A": "readiness evidence", "B": "checklist", "C": "evidence map"}
        available = list(fallback_subjects.keys())
        subject_key = deterministic_option_key_for(row, classification, 2, available)
        subject = fallback_subjects[subject_key]
        subject_options = list(fallback_subjects.values())
    sentence_slots: dict[str, dict[str, str]] = {}
    slots = non_hia_email_2_sentence_slots(row, classification or {}, sentence_slots, asset_name) if classification is not None else {}
    body = value_fallback_body_fixed(prefix, asset_name, slots)
    emails = {**emails}
    emails["email_2"] = {
        "subject_options": subject_options,
        "chosen_subject": subject,
        "body": body,
        "word_count": word_count(body),
    }
    return emails


def value_fallback_email_3(row: dict[str, Any], emails: dict[str, Any], asset: str | None = None) -> dict[str, Any]:
    return value_fallback_email_2(row, emails, asset)


def email_3_mode_for(funding: FundingMatch, copy_brief: dict[str, Any], classification: dict[str, Any]) -> str:
    return "funding" if funding_claim_send_safe(funding, copy_brief, classification) else "value_fallback"


def funding_followup_mode_for(funding: FundingMatch, copy_brief: dict[str, Any], classification: dict[str, Any]) -> str:
    return str(
        copy_brief.get("funding_followup_mode")
        or copy_brief.get("email_2_mode")
        or copy_brief.get("email_3_mode")
        or email_3_mode_for(funding, copy_brief, classification)
    )


def hia_pricing_active(classification: dict[str, Any], copy_brief: dict[str, Any]) -> bool:
    return (
        classification.get("pressure_type") == "hia_regulatory"
        and compact(copy_brief.get("pricing_email_2_mode")) not in {"", "no_price_claim"}
    )


def infer_hia_clinic_size(row: dict[str, Any], classification: dict[str, Any], clinic_profile: dict[str, Any]) -> dict[str, Any]:
    if classification.get("pressure_type") != "hia_regulatory":
        return {
            "clinic_size_guess": "unknown",
            "clinic_size_confidence": "low",
            "endpoint_band_guess": "unknown",
            "endpoint_band_confidence": "low",
            "pricing_email_2_mode": "no_price_claim",
            "pricing_claim_safe": False,
            "pricing_claim_line": "",
            "pricing_evidence_json": {},
        }

    text = lower_blob(row)
    locations = listish_items(row.get("locations_detected"), limit=12)
    services = listish_items(row.get("services_detected"), limit=12) or listish_items(row.get("primary_services_summary"), limit=12)
    team = listish_items(row.get("leadership_or_team_signals"), limit=20) or listish_items(row.get("contact_info_detected"), limit=20)
    parent = compact(row.get("parent_company"))
    profile_guess = compact(clinic_profile.get("clinic_profile_guess"))
    service_type = compact(classification.get("hia_service_type_guess"))

    location_terms = sorted({term for term in ("locations", "branches", "outlets", "our clinics", "islandwide") if term in text})
    group_terms = sorted({term for term in ("group", "network", "multi-location", "multilocation", "multi clinic", "multi-clinic") if term in text})
    practitioner_names = sorted(set(re.findall(r"\b(?:dr|doctor|dentist|specialist)\.?\s+[a-z][a-z]+", text)))[:12]
    team_terms = sorted({term for term in ("our doctors", "our specialists", "our dentists", "medical team", "clinical team") if term in text})
    department_terms = sorted(
        {
            term
            for term in (
                "cardiology",
                "dermatology",
                "ophthalmology",
                "surgery",
                "gastroenterology",
                "physiotherapy",
                "psychology",
                "pharmacy",
                "dental",
                "radiology",
                "laboratory",
            )
            if term in text
        }
    )
    address_count = len(set(re.findall(r"\bsingapore\s+\d{6}\b", text)))
    explicit_location_count = max(len(locations), address_count)
    practitioner_count = max(len(practitioner_names), len(team))

    size_guess = "unknown"
    size_confidence = "low"
    endpoint_band = "unknown"
    endpoint_confidence = "low"

    group_evidence = bool(parent or group_terms or explicit_location_count >= 2 or "our clinics" in text or "islandwide" in text)
    larger_team_evidence = practitioner_count >= 6 or len(department_terms) >= 4
    if group_evidence:
        size_guess = "multi_location_provider" if explicit_location_count >= 2 or "our clinics" in text or "islandwide" in text else "group_clinic"
        size_confidence = "high" if explicit_location_count >= 2 or parent else "medium"
        endpoint_band = "11_20" if larger_team_evidence or explicit_location_count >= 2 else "6_10"
        endpoint_confidence = "medium"
    elif larger_team_evidence:
        size_guess = "group_clinic"
        size_confidence = "medium"
        endpoint_band = "11_20"
        endpoint_confidence = "medium"
    elif profile_guess == "solo_gp" or "solo gp" in text or "family clinic" in text or "single clinic" in text:
        size_guess = "solo_gp" if profile_guess == "solo_gp" or "solo gp" in text else "small_single_clinic"
        size_confidence = "high" if ("solo gp" in text or "family clinic" in text or practitioner_count <= 2) else "medium"
        endpoint_band = "1_5"
        endpoint_confidence = "medium"
    elif profile_guess == "dental" or service_type == "dental":
        size_guess = "dental_single_clinic"
        size_confidence = "medium"
        endpoint_band = "1_5"
        endpoint_confidence = "medium"
    elif profile_guess == "pharmacy" or service_type == "retail_pharmacy":
        size_guess = "pharmacy_single_site"
        size_confidence = "medium"
        endpoint_band = "1_5"
        endpoint_confidence = "medium"
    elif service_type == "allied_health" or profile_guess in {"allied_health", "psychology", "hearing_care"}:
        size_guess = "allied_health_single_site"
        size_confidence = "medium"
        endpoint_band = "1_5"
        endpoint_confidence = "medium"
    elif profile_guess == "specialist_led" or service_type == "specialist_OMS":
        size_guess = "specialist_single_clinic"
        size_confidence = "medium"
        endpoint_band = "6_10" if practitioner_count >= 3 else "unknown"
        endpoint_confidence = "low" if endpoint_band == "unknown" else "medium"
    elif classification.get("entity_type_guess") in {"clinic", "healthcare_provider"}:
        size_guess = "small_single_clinic"
        size_confidence = "low"
        endpoint_band = "unknown"
        endpoint_confidence = "low"

    if size_guess in {"group_clinic", "multi_location_provider"}:
        pricing_mode = "group_or_larger_sizing_needed"
        claim = "CISOaaS pricing is endpoint-based; group or multi-location setups should be sized properly before quoting a final number."
    elif endpoint_band in {"1_5", "6_10"} and size_confidence in {"medium", "high"}:
        pricing_mode = "small_clinic_starting_price"
        claim = f"For smaller clinics, the starting CISOaaS package is around {CISOAAS_HIA_PRICING['price_text']} before funding."
    else:
        pricing_mode = "endpoint_sizing_needed"
        claim = "CISOaaS pricing is endpoint-based, so the final number should be checked against endpoint count."

    evidence = {
        "locations_found": locations,
        "address_count": address_count,
        "branch_group_wording_found": location_terms + group_terms,
        "practitioner_team_count_evidence": {"count": practitioner_count, "examples": practitioner_names or team[:8], "team_terms": team_terms},
        "parent_group_evidence": parent,
        "service_departments_evidence": department_terms or services[:8],
        "endpoint_proxy_reasoning": f"{size_guess} with endpoint band {endpoint_band}; endpoint count is inferred conservatively from public website evidence only.",
        "confidence_explanation": f"clinic_size_confidence={size_confidence}; endpoint_band_confidence={endpoint_confidence}",
        "pricing_source": CISOAAS_HIA_PRICING,
    }
    return {
        "clinic_size_guess": size_guess,
        "clinic_size_confidence": size_confidence,
        "endpoint_band_guess": endpoint_band,
        "endpoint_band_confidence": endpoint_confidence,
        "pricing_email_2_mode": pricing_mode,
        "pricing_claim_safe": True,
        "pricing_claim_line": claim,
        "pricing_evidence_json": evidence,
    }


def enrichment_quality(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> tuple[int, list[str]]:
    flags: list[str] = []
    score = 0
    if classification.get("pressure_type") in {"hia_regulatory", "pdpa_safeguards", "customer_trust"}:
        score += 2
    else:
        flags.append("no_supported_pressure")
    if compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal")):
        score += 3
    else:
        flags.append("no_concrete_company_observation")
    if compact(copy_brief.get("email_problem_statement")):
        score += 2
    else:
        flags.append("missing_problem")
    if compact(copy_brief.get("data_systems_likely")):
        score += 1
    else:
        flags.append("missing_data_systems")
    if classification.get("outreach_trigger_confidence") in {"medium", "high"}:
        score += 2
    else:
        flags.append("low_trigger_confidence")
    return min(score, 10), flags


def copy_brief_quality(classification: dict[str, Any], copy_brief: dict[str, Any]) -> tuple[int, list[str]]:
    flags: list[str] = []
    required = ("email_personalisation_signal", "email_problem_statement", "email_mechanism_statement", "email_cta")
    missing = [field for field in required if not compact(copy_brief.get(field))]
    flags.extend(f"missing_copy_brief:{field}" for field in missing)
    if generic_personalisation_signal(copy_brief.get("email_personalisation_signal", "")):
        flags.append("generic_personalisation_signal")
    if classification.get("pressure_type") == "hia_regulatory" and not compact(copy_brief.get("clinic_profile_phrase")):
        flags.append("clinic_profile_missing_for_hia")
    return max(0, 10 - len(flags) * 2), list(dict.fromkeys(flags))


def blocking_enrichment_flags(flags: list[str], classification: dict[str, Any], score: int) -> list[str]:
    blocking = {"no_supported_pressure", "no_concrete_company_observation", "missing_problem", "weak_hia_and_pdpa_evidence", "no_personal_data_or_b2b_evidence"}
    result = [flag for flag in flags if flag in blocking]
    if "missing_data_systems" in flags and (classification.get("pressure_type") in {"hia_regulatory", "pdpa_safeguards", "customer_trust"} and score < 7):
        result.append("missing_data_systems")
    if classification.get("pressure_type") == "hia_regulatory" and classification.get("hia_service_type_guess") == "unknown":
        result.append("no_hia_service_evidence")
    return list(dict.fromkeys(result))


def advisory_enrichment_flags(flags: list[str], classification: dict[str, Any], score: int) -> list[str]:
    blocking = set(blocking_enrichment_flags(flags, classification, score))
    advisory = [flag for flag in flags if flag not in blocking]
    return list(dict.fromkeys(advisory))


def blocking_copy_brief_flags(flags: list[str], classification: dict[str, Any], copy_brief: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for flag in flags:
        if flag.startswith("missing_copy_brief:") or flag == "generic_personalisation_signal":
            result.append(flag)
        elif flag == "clinic_profile_missing_for_hia" and classification.get("pressure_type") == "hia_regulatory" and not compact(copy_brief.get("clinic_profile_phrase")):
            result.append(flag)
    return list(dict.fromkeys(result))


def advisory_copy_brief_flags(flags: list[str], classification: dict[str, Any], copy_brief: dict[str, Any]) -> list[str]:
    blocking = set(blocking_copy_brief_flags(flags, classification, copy_brief))
    advisory = [flag for flag in flags if flag not in blocking]
    if (copy_brief.get("funding_followup_mode") or copy_brief.get("email_2_mode") or copy_brief.get("email_3_mode")) == "value_fallback" and compact(copy_brief.get("funding_next_check_needed")):
        advisory.append("funding_next_check_needed")
    return list(dict.fromkeys(advisory))


def email_greeting(row: dict[str, Any], company: str | None = None) -> str:
    name = compact(row.get("selected_contact_name"))
    if valid_person_contact_name(name):
        return f"Hi {first_name_from_contact(name)},"
    return "Hello team,"


def first_name_from_contact(name: str) -> str:
    parts = [part for part in compact(name).replace(".", " ").split() if part]
    while parts and parts[0].lower() in {"dr", "mr", "mrs", "ms", "miss", "mdm", "prof"}:
        parts.pop(0)
    return parts[0] if parts else "there"


def email_1_greeting(row: dict[str, Any], company: str | None = None) -> str:
    name = compact(row.get("selected_contact_name"))
    if valid_person_contact_name(name):
        return f"Hi {first_name_from_contact(name)},"
    return "Hello team,"


def email_greeting_type(row: dict[str, Any]) -> str:
    if contact_send_mode(row) == "named_person":
        return "named_person"
    return "generic_team"


def email_comma_greeting(row: dict[str, Any], company: str | None = None) -> str:
    name = compact(row.get("selected_contact_name"))
    if valid_person_contact_name(name):
        return f"Hi {first_name_from_contact(name)},"
    return "Hello team,"


def followup_name_prefix(row: dict[str, Any], separator: str = "-") -> str:
    name = compact(row.get("selected_contact_name"))
    if not valid_person_contact_name(name):
        return ""
    first = first_name_from_contact(name)
    if separator == ",":
        return f"{first}, "
    return f"{first} {separator} "


def followup_sentence(prefix: str, sentence: str) -> str:
    text = compact(sentence)
    if prefix.endswith("- ") and text:
        text = text[:1].lower() + text[1:]
    elif not prefix and text:
        text = text[:1].upper() + text[1:]
    return f"{prefix}{text}"


def company_team_greeting(company: str | None = None) -> str:
    company_name = compact(company)
    if company_name and company_name != "your organisation":
        return f"Hi {company_name} team,"
    return "Hi team,"


def hia_window_label(classification: dict[str, Any]) -> str:
    batch = compact(classification.get("hia_timeline_batch_guess"))
    if classification.get("hia_deadline_claim_safe") and batch and batch != "unknown":
        return batch.replace(" - ", " ")
    return "HIA timelines starting from 2027"


def hia_problem_prefix(classification: dict[str, Any]) -> str:
    return "With HIA readiness becoming more urgent for healthcare providers,"


def trim_text(value: Any) -> str:
    return str(value or "").strip()


def lower_blob(row: dict[str, Any]) -> str:
    parts = [
        row.get("company_name", ""),
        row.get("company_homepage_name", ""),
        row.get("website_content", ""),
        row.get("services_detected", ""),
        row.get("locations_detected", ""),
        row.get("leadership_or_team_signals", ""),
        row.get("contact_info_detected", ""),
        row.get("notes", ""),
        row.get("_serper_context_text", ""),
        row.get("selected_contact_title", ""),
        row.get("selected_contact_role", ""),
    ]
    return " ".join(compact(part) for part in parts).lower()


def contact_title_blob(row: dict[str, Any]) -> str:
    return " ".join(
        compact(row.get(key))
        for key in ("selected_contact_title", "selected_contact_role", "decision_maker_role_guess")
    ).lower()


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def evidence_count(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def has_clinic_word(text: str) -> bool:
    return bool(re.search(r"\bclinics?\b", text))


def confidence_from_score(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def explicit_social_org_identity(company_l: str, text: str) -> bool:
    if "sree narayana mission" in text:
        return True
    if contains_any(company_l, ("children's home", "childrens home", "charity", "society", "social service")):
        return True
    if "mission" in company_l and contains_any(text, ("nursing home", "resident care", "eldercare", "palliative")):
        return True
    if "foundation" in company_l and not contains_any(company_l, ("healthcare", "medical", "clinic", "dental", "hospital")):
        return True
    return False


def infer_entity(row: dict[str, Any], text: str) -> dict[str, Any]:
    company = compact(row.get("company_name"))
    company_l = company.lower()
    npo_score = evidence_count(text, NPO_TERMS)
    social_score = evidence_count(text, SOCIAL_TERMS)
    healthcare_score = evidence_count(text, HEALTHCARE_TERMS)
    clinical_name = any(term in company_l for term in CLINICAL_ENTITY_NAME_TERMS)
    strong_npo = contains_any(text, STRONG_NPO_TERMS) or contains_any(company_l, ("charity", "mission", "society"))
    strong_social = contains_any(text, STRONG_SOCIAL_SERVICE_TERMS) or (
        "mission" in company_l and contains_any(text, ("nursing home", "resident care", "eldercare", "palliative"))
    )
    explicit_social = explicit_social_org_identity(company_l, text)
    healthcare_group = contains_any(company_l, ("holdings", "holding", "group")) and contains_any(
        text, ("healthcare", "health care", "clinic", "medical", "specialist", "hospital", "patient")
    )

    # Entity type describes the organisation model. Keep it separate from pressure_type.
    if contains_any(company_l, ("holdings", "holding")) and not explicit_social:
        return {
            "entity_type_guess": "healthcare_provider" if healthcare_group or clinical_name else "private_company",
            "entity_type_confidence": "medium",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if ("clinic" in company_l or company_l.endswith("clinic")) and not explicit_social:
        return {
            "entity_type_guess": "clinic",
            "entity_type_confidence": "high",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if (has_clinic_word(text) or "dental" in text) and not explicit_social:
        return {
            "entity_type_guess": "clinic",
            "entity_type_confidence": "high",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if (clinical_name or healthcare_score >= 2 or healthcare_group) and not explicit_social:
        return {
            "entity_type_guess": "healthcare_provider",
            "entity_type_confidence": "medium",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if explicit_social or strong_npo or strong_social or (
        npo_score >= 2 and social_score >= 1 and not clinical_name
    ):
        if "charity" in text or "ipc" in text:
            entity = "charity"
        elif strong_social or social_score >= 1:
            entity = "social_service"
        else:
            entity = "npo"
        return {
            "entity_type_guess": entity,
            "entity_type_confidence": "high" if contains_any(text, ("charity", "ipc", "ncss", "social service")) else "medium",
            "sme_likelihood": "unlikely",
            "npo_likelihood": "likely",
            "charity_or_social_service_likelihood": "likely",
        }
    if contains_any(company_l, ("holdings", "holding", "group")) and healthcare_score < 2 and not has_clinic_word(text):
        return {
            "entity_type_guess": "private_company",
            "entity_type_confidence": "medium",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if "clinic" in company_l or company_l.endswith("clinic"):
        return {
            "entity_type_guess": "clinic",
            "entity_type_confidence": "high",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if (has_clinic_word(text) or "dental" in text) and not contains_any(text, NPO_TERMS):
        return {
            "entity_type_guess": "clinic",
            "entity_type_confidence": "high",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if (clinical_name or healthcare_score >= 2) and not strong_npo:
        return {
            "entity_type_guess": "healthcare_provider",
            "entity_type_confidence": "medium",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if "pte ltd" in text or "private limited" in text or ".com.sg" in text:
        return {
            "entity_type_guess": "private_company",
            "entity_type_confidence": "medium",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    return {
        "entity_type_guess": "unknown",
        "entity_type_confidence": "low",
        "sme_likelihood": "unknown",
        "npo_likelihood": "unknown",
        "charity_or_social_service_likelihood": "unknown",
    }


def has_concrete_hia_evidence(row: dict[str, Any], text: str, service: str) -> bool:
    company = compact(row.get("company_name")).lower()
    care_evidence = contains_any(text, CLINICAL_CARE_EVIDENCE_TERMS)
    clinical_name = contains_any(company, CLINICAL_ENTITY_NAME_TERMS)
    if service == "GP_OMS":
        return has_family_clinic_evidence(row, text) or (
            (has_clinic_word(text) or contains_any(company, ("clinic", "medical")))
            and contains_any(text, ("doctor", "doctors", "consultation", "appointment", "patient", "outpatient", "medical clinic"))
        )
    if service == "specialist_OMS":
        return contains_any(text, SPECIFIC_SPECIALIST_SERVICE_TERMS) and (
            care_evidence or clinical_name or contains_any(text, ("specialist clinic", "specialist centre", "surgeon", "doctor"))
        )
    if service == "dental":
        return has_dental_service_evidence(company) or has_dental_service_evidence(text)
    if service == "hospital":
        return "hospital" in company or "hospital" in text
    if service == "diagnostic":
        return has_clinical_lab_evidence(text) or has_strong_diagnostic_lab_evidence(text)
    if service == "retail_pharmacy":
        return "pharmacy" in company or "pharmacy" in text or "pharmacist" in text
    if service == "long_term_care":
        return contains_any(text, ("nursing home", "community hospital", "home care", "caregiver", "palliative", "hospice", "resident care"))
    if service == "outpatient_renal_dialysis":
        return "dialysis" in text or "kidney care" in text or "renal" in text
    if service == "ambulatory_surgical_centre":
        return "ambulatory surgical" in text or "day surgery" in text or ("surgery" in text and care_evidence)
    if service == "hearing_care":
        return has_hearing_care_evidence(text) and care_evidence
    if service == "allied_health":
        return contains_any(
            text,
            (
                "physiotherapist",
                "physiotherapy",
                "podiatrist",
                "podiatry",
                "clinical psychologist",
                "psychology",
                "psychologist",
                "psychotherapy",
                "counselling",
                "counseling",
                "mental-health clinic",
                "mental health clinic",
                "audiologist",
                "rehabilitation",
            ),
        ) and care_evidence
    return False


def optometry_without_strong_clinical_evidence(text: str) -> bool:
    return contains_any(text, ("optometry", "optometrist", "optometrists", "visioncare", "vision care", "eye care")) and not contains_any(
        text,
        STRONG_EYE_CLINICAL_TERMS,
    )


def official_hia_service_type(service: str, text: str) -> str:
    service = compact(service)
    if service == "GP_OMS":
        return "outpatient_medical_gp"
    if service == "specialist_OMS":
        if "fertility" in text or "ivf" in text or "assisted reproduction" in text:
            return "assisted_reproduction"
        return "outpatient_medical_specialist"
    if service == "dental":
        return "outpatient_dental"
    if service == "retail_pharmacy":
        return "retail_pharmacy"
    if service == "hospital":
        if "community hospital" in text:
            return "community_hospital"
        return "acute_hospital"
    if service == "diagnostic":
        if "nuclear medicine" in text:
            return "nuclear_medicine_service"
        if "radiology" in text or "imaging" in text:
            return "radiology_laboratory"
        return "clinical_laboratory"
    if service == "long_term_care":
        if "nursing home" in text:
            return "nursing_home"
        if "community hospital" in text:
            return "community_hospital"
        if "contingency care" in text or "home care" in text or "caregiver" in text:
            return "contingency_care_service"
        return ""
    if service in {"allied_health", "hearing_care"}:
        clinical_allied = any(
            term in text
            for term in (
                "patient",
                "appointment",
                "assessment",
                "treatment",
                "case-note",
                "case note",
                "clinical",
                "consultation",
                "rehabilitation",
                "audiology",
                "audiologist",
                "hearing test",
                "hearing assessment",
                "physiotherapy",
                "psychologist",
            )
        )
        if clinical_allied:
            return "outpatient_medical_specialist"
        return ""
    if service == "outpatient_renal_dialysis":
        return "outpatient_renal_dialysis"
    if service == "ambulatory_surgical_centre":
        return "ambulatory_surgical_centre"
    if service in HIA_OFFICIAL_SERVICE_LABELS:
        return service
    return ""


def infer_hia(row: dict[str, Any], text: str) -> dict[str, Any]:
    score = 0
    batch_override = ""
    for term in HEALTHCARE_TERMS:
        if term in text:
            score += 12
    if "patient" in text or "health information" in text:
        score += 18
    company = compact(row.get("company_name")).lower()
    if any(term in company for term in ("clinic", "physio", "psychology", "hospice", "hearing", "dental", "medical", "medic")):
        score += 24
    if has_hearing_care_evidence(text):
        score += 18
    if has_clinical_lab_evidence(text):
        score += 18
    if has_strong_diagnostic_lab_evidence(text):
        service = "diagnostic"
    primary_text = " ".join(
        compact(value)
        for value in (
            row.get("company_name"),
            row.get("company_homepage_name"),
            compact(row.get("website_content"))[:1800],
            compact(row.get("_serper_context_text"))[:1200],
            compact(row.get("services_detected"))[:900],
        )
        if value
    ).lower()
    primary_gp = has_family_clinic_evidence(row, primary_text) or any(
        term in primary_text
        for term in (
            "gp clinic",
            "gp clinics",
            "general practitioner",
            "medical check-up",
            "medical checkup",
            "outpatient medical clinic",
            "medical clinic",
            "doctor-led",
        )
    )
    primary_dental = has_dental_service_evidence(company) or (has_dental_service_evidence(primary_text) and not primary_gp)
    primary_allied = any(
        term in primary_text
        for term in (
            "physio",
            "physiotherapy",
            "podiatry",
            "podiatrist",
            "clinical psychologist",
            "psychology",
            "psychologist",
            "psychotherapy",
            "counselling",
            "counseling",
            "mental-health clinic",
            "mental health clinic",
            "counselling clinic",
            "counseling clinic",
            "rehabilitation",
        )
    )
    primary_specialist = contains_any(primary_text, SPECIFIC_SPECIALIST_SERVICE_TERMS) or any(
        term in primary_text
        for term in (
            "thoracic surgeon",
            "lung surgery",
            "cardiology",
            "gastroenterology",
            "ophthalmology",
            "dermatology",
            "rheumatology",
            "cancer centre",
            "cancer center",
            "cancer care",
            "fertility",
            "ivf",
            "assisted reproduction",
            "reproductive medicine",
            "oncology",
            "orthopaedic",
            "endocrinology",
            "neurology",
            "neurosurgery",
            "neuroscience",
        )
    )
    weak_specialist_only = contains_any(primary_text, WEAK_SPECIALIST_HIA_TERMS) and not contains_any(
        primary_text,
        (
            "ophthalmologist",
            "ophthalmology",
            "cataract",
            "retina",
            "doctor",
            "medical clinic",
            "specialist clinic",
            "patient",
            "appointment",
            "consultation",
            "treatment",
            "surgery",
            "surgeon",
        ),
    )
    if weak_specialist_only:
        primary_specialist = False
    primary_diagnostic = has_strong_diagnostic_lab_evidence(primary_text) or any(
        term in primary_text for term in ("clinical laboratory", "diagnostic lab", "diagnostic laboratory", "medical laboratory", "genetic test", "genetic testing", "dna test", "pharmacogen")
    )
    primary_hospital = "hospital" in company or (
        not primary_specialist
        and not primary_allied
        and any(term in primary_text for term in ("acute hospital", "community hospital", "hospital services", "inpatient"))
    )
    primary_renal = "renal dialysis" in primary_text or "dialysis" in primary_text
    primary_ambulatory_surgical = "ambulatory surgical" in primary_text or "day surgery" in primary_text
    primary_hearing = has_hearing_care_evidence(primary_text) or contains_any(
        primary_text,
        ("audiology", "audiologist", "hearing test", "hearing tests", "hearing assessment", "hearing assessments"),
    )
    specialist_name_evidence = any(
        term in " ".join((company, compact(row.get("company_homepage_name")).lower()))
        for term in (
            "cardiology",
            "gastroenterology",
            "endocrinology",
            "rheumatology",
            "cancer centre",
            "cancer center",
            "cancer",
            "fertility",
            "ivf",
            "reproductive",
            "oncology",
            "dermatology",
            "orthopaedic",
            "ophthalmology",
            "thoracic",
            "lung",
            "surgery",
            "surgeon",
            "neurology",
            "neurosurgery",
            "neuroscience",
        )
    )
    if primary_dental:
        service = "dental"
    elif primary_diagnostic and not primary_specialist:
        service = "diagnostic"
    elif primary_hospital:
        service = "hospital"
    elif primary_renal:
        service = "outpatient_renal_dialysis"
    elif primary_ambulatory_surgical:
        service = "ambulatory_surgical_centre"
    elif primary_hearing:
        service = "hearing_care"
    elif primary_gp:
        service = "GP_OMS"
    elif primary_specialist and specialist_name_evidence:
        service = "specialist_OMS"
    elif primary_allied:
        service = "allied_health"
    elif primary_specialist:
        service = "specialist_OMS"
    elif "ambulatory surgical" in text or "day surgery" in text:
        service = "ambulatory_surgical_centre"
    elif "assisted reproduction" in text or "ivf" in text or ("fertility" in text and not has_family_clinic_evidence(row, text)):
        service = "specialist_OMS"
    elif any(term in text for term in ("cancer centre", "cancer center", "cancer care", "oncology", "radiation")):
        service = "specialist_OMS"
    elif any(term in text for term in ("national neuroscience institute", "neuroscience institute", "neurology", "neurosurgery", "neuroscience")):
        service = "specialist_OMS"
    elif "pharmacy" in text:
        service = "retail_pharmacy"
    elif has_hearing_care_evidence(text) or "audiology" in text:
        service = "hearing_care"
    elif "renal dialysis" in text or "dialysis" in text:
        service = "outpatient_renal_dialysis"
    elif has_family_clinic_evidence(row, text) and not has_strong_diagnostic_lab_evidence(text):
        service = "GP_OMS"
    elif contains_any(text, LONG_TERM_CARE_TERMS):
        service = "long_term_care"
    elif "aesthetic" in text and has_clinic_word(text) and ("doctor" in text or "medical" in text):
        service = "GP_OMS"
    elif primary_specialist:
        service = "specialist_OMS"
    elif contains_any(
        text,
        (
            "physio",
            "physiotherapy",
            "podiatry",
            "podiatrist",
            "clinical psychologist",
            "psychology",
            "psychologist",
            "psychotherapy",
            "counselling",
            "counseling",
            "mental-health clinic",
            "mental health clinic",
            "mental-health",
            "counselling clinic",
            "counseling clinic",
            "rehabilitation",
        ),
    ):
        service = "allied_health"
    elif contains_any(text, SPECIFIC_SPECIALIST_SERVICE_TERMS):
        service = "specialist_OMS"
    elif has_clinical_lab_evidence(text) or contains_any(text, DIAGNOSTIC_SERVICE_TERMS):
        service = "diagnostic"
    elif "hims" in text or "health information management system" in text or "nehr" in text:
        service = "unknown"
    elif has_clinic_word(text) or "doctor" in text:
        service = "GP_OMS"
    else:
        service = "unknown"
    if optometry_without_strong_clinical_evidence(primary_text):
        service = "unknown"
    official_service = official_hia_service_type(service, text)
    concrete_hia_evidence = bool(official_service) and (has_concrete_hia_evidence(row, text, service) or bool(batch_override))
    if official_service or service in HIA_BATCH_BY_SERVICE or batch_override:
        score = max(score + 24, 45)
    name_blob = " ".join((company, compact(row.get("company_homepage_name")).lower()))
    if official_service and any(
        term in name_blob
        for term in (
            "clinic",
            "medical",
            "dental",
            "hospital",
            "centre",
            "center",
            "surgery",
            "surgeon",
            "heart",
            "cancer",
            "neuro",
            "rheumat",
            "arthritis",
            "ivf",
            "fertility",
        )
    ):
        score = max(score, 75)
    if not concrete_hia_evidence:
        score = min(score, 36)
        batch_override = ""
    score = min(score, 100)
    confidence = confidence_from_score(score)
    batch = batch_override or HIA_BATCH_BY_OFFICIAL_SERVICE.get(official_service) or HIA_BATCH_BY_SERVICE.get(service, "unknown")
    hia_relevant = concrete_hia_evidence and (
        score >= 45 or (official_service in HIA_BATCH_BY_OFFICIAL_SERVICE and score >= 36)
    )
    if not hia_relevant:
        official_service = ""
        batch = "unknown"
    return {
        "hia_relevant": hia_relevant,
        "hia_relevance_score": score,
        "hia_confidence": confidence,
        "hia_scope_reason": (
            "Website evidence indicates a healthcare service type that may fall under HIA health-information, cybersecurity and data-security duties."
            if hia_relevant
            else "Healthcare/HIA scope evidence is weak."
        ),
        "hia_service_type_guess": service,
        "hia_official_service_type": official_service,
        "hia_official_service_label": HIA_OFFICIAL_SERVICE_LABELS.get(official_service, ""),
        "hia_timeline_batch_guess": batch,
        "hia_deadline_claim_safe": batch != "unknown" and confidence in {"medium", "high"},
        "hia_disclaimer_needed": True,
    }


def hia_llm_enabled() -> bool:
    if os.getenv("OUTREACH_HIA_LLM_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def should_review_hia_with_llm(row: dict[str, Any], text: str, hia: dict[str, Any]) -> bool:
    review = row.get("hia_llm_review")
    if review and hia.get("hia_confidence") == "high" and hia.get("hia_relevant") and not review.get("hia_relevant"):
        return False
    if review:
        return True
    if hia.get("hia_confidence") == "high":
        return False
    if hia.get("hia_relevant") and hia.get("hia_service_type_guess") in HIA_BATCH_BY_SERVICE:
        return False
    return contains_any(text, AMBIGUOUS_HIA_TERMS)


def hia_review_payload(row: dict[str, Any], hia: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_name": row.get("company_name", ""),
        "website_url": row.get("best_url") or row.get("url_picked") or "",
        "company_homepage_name": row.get("company_homepage_name", ""),
        "industry_guess": row.get("industry_guess", ""),
        "website_content": compact(row.get("website_content"))[:7000],
        "services_detected": row.get("services_detected", ""),
        "locations_detected": row.get("locations_detected", ""),
        "leadership_or_team_signals": row.get("leadership_or_team_signals", ""),
        "contact_info_detected": row.get("contact_info_detected", ""),
        "structured_data_detected": row.get("structured_data_detected", ""),
        "selected_contact_title": row.get("selected_contact_title", ""),
        "deterministic_hia": hia,
    }


HIA_LLM_REVIEW_PROMPT = """You classify ambiguous Singapore healthcare scope for HIA outreach.
Use only provided evidence. Return strict JSON only. Do not invent facts.

Rules:
- If it clearly matches one official HIA service type, set hia_relevant true.
- Official HIA service types are: Outpatient Medical Service (GP), Outpatient Medical Service (Specialist), Outpatient Dental, Acute Hospital, Nursing Home, Ambulatory Surgical Centre, Community Hospital, Contingency Care Service, Assisted Reproduction, Clinical Laboratory, Outpatient Renal Dialysis, Retail Pharmacy, Radiology Laboratory, Nuclear Medicine Service.
- If it is only wellness, beauty, aesthetics, optometry retail, product retail, training, media, holdings/group activity, or generic care language without clinical patient-care evidence, set hia_relevant false.
- For hearing-care, audiology, physiotherapy, podiatry, psychology, optometry, or other allied-health evidence, set hia_relevant true only when evidence shows clinical patient care such as appointments, assessments, treatment, patient records or case notes.
- Return a service type only when evidence supports it.
- Use medium/high confidence only when evidence quotes are concrete.

Return:
{
  "hia_relevant": false,
  "hia_confidence": "low|medium|high",
  "hia_service_type_guess": "GP_OMS|specialist_OMS|dental|retail_pharmacy|diagnostic|hospital|allied_health|hearing_care|long_term_care|outpatient_renal_dialysis|ambulatory_surgical_centre|unknown",
  "hia_scope_reason": "",
  "evidence": [{"quote": "", "source_field": "", "reason": ""}],
  "human_review_required": true
}
"""


def call_hia_llm_review(row: dict[str, Any], hia: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        response = requests.post(
            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions").strip(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("OUTREACH_HIA_LLM_MODEL", "deepseek/deepseek-v4-flash").strip(),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": HIA_LLM_REVIEW_PROMPT},
                    {"role": "user", "content": json.dumps(hia_review_payload(row, hia), ensure_ascii=False)},
                ],
            },
            timeout=float(os.getenv("OUTREACH_HIA_LLM_TIMEOUT_SECONDS", "20")),
        )
        raise_for_openrouter_account_error(response, "HIA LLM review")
        response.raise_for_status()
        choices = response.json().get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(content).strip(), flags=re.IGNORECASE)
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except ProviderAccountError:
        raise
    except Exception:
        return None


def apply_hia_llm_review(hia: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(review, dict):
        return hia
    confidence = str(review.get("hia_confidence") or "low").strip().lower()
    if confidence not in {"medium", "high"}:
        return {**hia, "hia_llm_review_status": "low_confidence"}
    service = str(review.get("hia_service_type_guess") or "unknown").strip()
    valid_services = {
        "GP_OMS",
        "specialist_OMS",
        "dental",
        "retail_pharmacy",
        "diagnostic",
        "hospital",
        "allied_health",
        "hearing_care",
        "long_term_care",
        "HIMS_provider",
        "NEHR_user",
        "unknown",
    }
    if service not in valid_services:
        service = "unknown"
    official_service = official_hia_service_type(service, f"{hia.get('hia_scope_reason', '')} {compact(review.get('hia_scope_reason'))}".lower())
    relevant = bool(review.get("hia_relevant")) and bool(official_service)
    batch = HIA_BATCH_BY_OFFICIAL_SERVICE.get(official_service) or HIA_BATCH_BY_SERVICE.get(service, "unknown")
    reason = compact(review.get("hia_scope_reason")) or hia.get("hia_scope_reason", "")
    return {
        **hia,
        "hia_relevant": relevant,
        "hia_relevance_score": max(int(hia.get("hia_relevance_score") or 0), 80 if confidence == "high" and relevant else 55 if relevant else 20),
        "hia_confidence": confidence,
        "hia_scope_reason": f"LLM ambiguous-HIA review: {reason}",
        "hia_service_type_guess": service,
        "hia_official_service_type": official_service,
        "hia_official_service_label": HIA_OFFICIAL_SERVICE_LABELS.get(official_service, ""),
        "hia_timeline_batch_guess": batch,
        "hia_deadline_claim_safe": relevant and batch != "unknown" and confidence in {"medium", "high"},
        "hia_disclaimer_needed": True,
        "hia_llm_review_status": "applied",
        "hia_llm_review_json": review,
    }


def infer_data_signal(text: str, hia: dict[str, Any], entity: dict[str, Any]) -> tuple[str, str, str]:
    if hia["hia_relevant"] and "health" in text:
        return "health_information", "high", "high"
    if hia["hia_relevant"]:
        return "patient_data", "high", "high"
    if entity["entity_type_guess"] in {"charity", "social_service", "npo"}:
        if "resident" in text:
            return "resident_data", "high", "medium"
        return "beneficiary_data", "medium", "medium"
    if "student" in text:
        return "student_data", "medium", "medium"
    if "finance" in text or "payment" in text:
        return "financial_data", "high", "medium"
    if contains_any(text, B2B_TERMS):
        return "business_partner_data", "medium", "low"
    if "employee" in text or "staff" in text:
        return "employee_data", "medium", "medium"
    if contains_any(text, PERSONAL_DATA_TERMS):
        return "customer_data", "medium", "unknown"
    if contains_any(text, SENSITIVE_TERMS):
        return "customer_data", "medium", "medium"
    return "unknown", "low", "unknown"


def is_data_protection_owner(row: dict[str, Any]) -> bool:
    return contains_any(contact_title_blob(row), DPO_TITLE_TERMS)


def has_customer_trust_pressure(text: str) -> bool:
    if contains_any(text, STRONG_CUSTOMER_TRUST_TERMS):
        return True
    return any(term in text for term in ("recruitment", "hr", "education", "training")) and any(
        term in text for term in ("corporate", "business customer", "procurement", "enterprise", "vendor")
    )


def business_model_trust_signal(text: str) -> str:
    for term in STRONG_CUSTOMER_TRUST_TERMS + B2B_TERMS:
        if term in text:
            return term
    return "clients or business partners"


def score_email_tracks(
    row: dict[str, Any],
    text: str,
    entity: dict[str, Any],
    hia: dict[str, Any],
    data_type: str,
    personal_intensity: str,
    dpo_owner: bool,
    trust_signal: str,
) -> dict[str, dict[str, Any]]:
    official_service = compact(hia.get("hia_official_service_type"))
    hia_score = 0
    hia_reasons: list[str] = []
    if official_service and hia.get("hia_relevant"):
        hia_score = max(int(hia.get("hia_relevance_score") or 0), 70)
        hia_reasons.append(f"official_hia_service:{official_service}")
        if hia.get("hia_confidence") == "high":
            hia_score += 10
        elif hia.get("hia_confidence") == "medium":
            hia_score += 5
    elif hia.get("hia_service_type_guess") not in {"", "unknown"}:
        hia_reasons.append(f"non_official_or_weak_hia_service:{hia.get('hia_service_type_guess')}")

    personal_score = {"high": 70, "medium": 55, "low": 20}.get(personal_intensity, 0)
    if data_type != "unknown":
        personal_score += 8
    if entity.get("entity_type_guess") in {"charity", "social_service", "npo"} and data_type in {"beneficiary_data", "resident_data"}:
        personal_score += 7
    pdpa_reasons = [f"personal_intensity:{personal_intensity}", f"data_type:{data_type}"]

    dpo_score = personal_score + (22 if dpo_owner else 0)
    dpo_reasons = pdpa_reasons + (["contact_or_role_owner"] if dpo_owner else ["no_dpo_ops_owner_signal"])

    trust_score = 0
    trust_reasons: list[str] = []
    if has_customer_trust_pressure(text):
        trust_score = 68
        trust_reasons.append(f"trust_signal:{trust_signal}")
    if contains_any(text, B2B_TERMS):
        trust_score = max(trust_score, 55)
        trust_reasons.append("b2b_terms")
    if personal_intensity in {"medium", "high"} and trust_score:
        trust_score += 8

    return {
        "hia_regulatory": {
            "score": min(hia_score, 100),
            "eligible": bool(official_service and hia.get("hia_relevant") and hia.get("hia_confidence") in {"medium", "high"}),
            "reason": "; ".join(hia_reasons) or "no_official_hia_service_evidence",
        },
        "dpo_evidence": {
            "score": min(dpo_score, 100),
            "eligible": bool(dpo_owner and personal_intensity in {"medium", "high"}),
            "reason": "; ".join(dpo_reasons),
        },
        "customer_trust": {
            "score": min(trust_score, 100),
            "eligible": bool(trust_score >= 65),
            "reason": "; ".join(trust_reasons) or "no_customer_or_partner_trust_signal",
        },
        "pdpa_safeguards": {
            "score": min(personal_score, 100),
            "eligible": personal_intensity in {"medium", "high"},
            "reason": "; ".join(pdpa_reasons),
        },
    }


def choose_email_track(track_scores: dict[str, dict[str, Any]]) -> tuple[str, str, list[dict[str, Any]]]:
    thresholds = {
        "hia_regulatory": 70,
        "dpo_evidence": 70,
        "customer_trust": 65,
        "pdpa_safeguards": 50,
    }
    candidates = [
        (track, int(data.get("score") or 0))
        for track, data in track_scores.items()
        if data.get("eligible") and int(data.get("score") or 0) >= thresholds[track]
    ]
    if not candidates:
        rejected = [
            {"track": track, "score": int(data.get("score") or 0), "reason": data.get("reason", ""), "eligible": bool(data.get("eligible"))}
            for track, data in sorted(track_scores.items())
        ]
        return "not_ready", "", rejected
    hia_candidate = next((item for item in candidates if item[0] == "hia_regulatory"), None)
    if hia_candidate and hia_candidate[1] >= thresholds["hia_regulatory"]:
        primary = "hia_regulatory"
        secondary = next((track for track, _score in sorted(candidates, key=lambda item: item[1], reverse=True) if track != primary), "")
        rejected = [
            {"track": track, "score": int(data.get("score") or 0), "reason": data.get("reason", ""), "eligible": bool(data.get("eligible"))}
            for track, data in sorted(track_scores.items())
            if track != primary
        ]
        return primary, secondary, rejected
    priority = {"hia_regulatory": 4, "dpo_evidence": 3, "customer_trust": 2, "pdpa_safeguards": 1}
    candidates.sort(key=lambda item: (item[1], priority[item[0]]), reverse=True)
    primary = candidates[0][0]
    secondary = next((track for track, _score in candidates[1:] if track != primary), "")
    rejected = [
        {"track": track, "score": int(data.get("score") or 0), "reason": data.get("reason", ""), "eligible": bool(data.get("eligible"))}
        for track, data in sorted(track_scores.items())
        if track != primary
    ]
    return primary, secondary, rejected


def healthcare_segment(classification: dict[str, Any]) -> str:
    service = compact(classification.get("hia_service_type_guess")).replace("_", " ")
    entity = compact(classification.get("entity_type_guess")).replace("_", " ")
    if service and service != "unknown":
        return service
    if entity and entity != "unknown":
        return entity
    return "healthcare provider"


def has_hearing_care_evidence(text: str) -> bool:
    return "hearing" in text and any(
        term in text
        for term in (
            "hearing care",
            "audiology",
            "hearing test",
            "hearing tests",
            "hearing aid",
            "hearing aids",
            "hearing assessment",
            "device fitting",
            "appointment",
            "patient",
            "audiologist",
        )
    )


def has_dental_service_evidence(text: str) -> bool:
    if any(term in text for term in ("dental", "dentist", "orthodont", "orthodontic")):
        return True
    return "braces" in text and any(term in text for term in ("teeth", "tooth", "aligner", "dental", "orthodont"))


def has_clinical_lab_evidence(text: str) -> bool:
    return any(
        term in text
        for term in (
            "clinical laboratory",
            "diagnostic lab",
            "diagnostic laboratory",
            "medical laboratory",
            "molecular diagnostic",
            "molecular diagnostics",
            "laboratory diagnostic",
            "lab test",
            "lab tests",
            "patient test",
            "health screening",
            "radiology",
            "nuclear medicine",
        )
    )


def has_strong_diagnostic_lab_evidence(text: str) -> bool:
    return any(
        term in text
        for term in (
            "clinical laboratory",
            "diagnostic lab",
            "diagnostic laboratory",
            "medical laboratory",
            "molecular diagnostic",
            "molecular diagnostics",
            "radiology",
            "nuclear medicine",
            "test reports",
            "lab test",
            "lab tests",
        )
    )


def has_family_clinic_evidence(row: dict[str, Any], text: str) -> bool:
    company = compact(row.get("company_name")).lower()
    return "family clinic" in company or "family clinic" in text or "family medicine" in text


def should_use_serper_for_hia_adjudication(
    row: dict[str, Any],
    text: str,
    entity: dict[str, Any],
    hia: dict[str, Any],
) -> bool:
    if row.get("_serper_context_text") or not serper_context_enabled():
        return False
    service = compact(hia.get("hia_service_type_guess"))
    confidence = compact(hia.get("hia_confidence"))
    entity_type = compact(entity.get("entity_type_guess"))
    if hia.get("hia_relevant") and confidence == "high" and service in {
        "GP_OMS",
        "dental",
        "hospital",
        "diagnostic",
        "retail_pharmacy",
        "long_term_care",
        "outpatient_renal_dialysis",
        "ambulatory_surgical_centre",
    }:
        return False
    if service in {"unknown", "allied_health", "hearing_care", "specialist_OMS"}:
        return True
    if confidence in {"", "low", "medium"} and contains_any(text, AMBIGUOUS_HIA_TERMS):
        return True
    if entity_type in {"social_service", "npo", "charity"} and hia.get("hia_relevant"):
        return True
    return False


def add_hia_serper_context_if_needed(
    row: dict[str, Any],
    text: str,
    entity: dict[str, Any],
    hia: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    if not should_use_serper_for_hia_adjudication(row, text, entity, hia):
        return row, text, entity, hia
    search_context = fetch_serper_company_context(row, {"pressure_type": "hia_regulatory"})
    context_text = serper_context_text(search_context)
    if not search_context.get("used") or not context_text:
        return row, text, entity, hia
    augmented = dict(row)
    augmented["_hia_serper_context"] = search_context
    augmented["_serper_context_text"] = context_text
    refreshed_text = lower_blob(augmented)
    return augmented, refreshed_text, infer_entity(augmented, refreshed_text), infer_hia(augmented, refreshed_text)


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    text = lower_blob(row)
    entity = infer_entity(row, text)
    hia = infer_hia(row, text)
    row, text, entity, hia = add_hia_serper_context_if_needed(row, text, entity, hia)
    hia_review = row.get("hia_llm_review")
    if not hia_review and hia_llm_enabled() and should_review_hia_with_llm(row, text, hia):
        hia_review = call_hia_llm_review(row, hia)
    if should_review_hia_with_llm(row, text, hia):
        hia = apply_hia_llm_review(hia, hia_review)
    if optometry_without_strong_clinical_evidence(text):
        hia = {
            **hia,
            "hia_relevant": False,
            "hia_relevance_score": min(int(hia.get("hia_relevance_score") or 0), 36),
            "hia_confidence": "low",
            "hia_scope_reason": "Optometry/visioncare evidence without ophthalmology, surgical, patient-treatment or referral evidence is not treated as HIA scope.",
            "hia_service_type_guess": "unknown",
            "hia_official_service_type": "",
            "hia_official_service_label": "",
            "hia_timeline_batch_guess": "unknown",
            "hia_deadline_claim_safe": False,
        }
    data_type, personal_intensity, sensitive_likelihood = infer_data_signal(text, hia, entity)
    dpo_owner = is_data_protection_owner(row)
    trust_signal = business_model_trust_signal(text)
    track_scores = score_email_tracks(row, text, entity, hia, data_type, personal_intensity, dpo_owner, trust_signal)
    primary_track, secondary_track, rejected_tracks = choose_email_track(track_scores)

    if primary_track == "hia_regulatory":
        pressure_type = "hia_regulatory"
        problem_area = "hia_readiness"
        value_asset = "hia_readiness_map"
        trigger = "HIA timelines start from 2027, and the website indicates healthcare or patient-data activity."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Start with HIA readiness mapping, then use Cyber Essentials as a practical cybersecurity/data-security baseline."
    elif primary_track == "dpo_evidence":
        pressure_type = "pdpa_safeguards"
        problem_area = "evidence_collection"
        value_asset = "security_evidence_checklist"
        trigger = "The selected contact appears to own data-protection, compliance, operations, admin or HR evidence across teams."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials to structure security evidence across IT, HR, vendors and operations; consider DPE/DPTM only when broader data-protection governance evidence supports it."
    elif primary_track == "customer_trust":
        pressure_type = "customer_trust"
        problem_area = "evidence_collection"
        value_asset = "security_evidence_checklist"
        trigger = f"Customers and partners may ask for reusable security evidence because the website indicates {trust_signal} activity."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials as the first reusable security-evidence baseline."
    elif primary_track == "pdpa_safeguards":
        pressure_type = "pdpa_safeguards"
        problem_area = "pdpa_safeguards" if personal_intensity in {"medium", "high"} else "unknown"
        value_asset = "pdpa_safeguards_checklist"
        trigger = f"The organisation appears to handle {data_type.replace('_', ' ')}."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials to support the cybersecurity safeguards and evidence side of PDPA readiness."
    else:
        pressure_type = "not_ready"
        problem_area = "unknown"
        value_asset = "cyber_essentials_readiness_checklist"
        trigger = ""
        recommended_first_cert = "unknown"
        recommended_path = "Do not generate outreach until stronger HIA, personal-data, DPO/ops, or customer-trust evidence is available."

    trigger_confidence = "medium" if entity["entity_type_confidence"] in {"medium", "high"} else "low"
    if pressure_type == "hia_regulatory" and hia["hia_confidence"] == "high":
        trigger_confidence = "high"
    elif primary_track in {"dpo_evidence", "pdpa_safeguards", "customer_trust"} and personal_intensity in {"medium", "high"}:
        trigger_confidence = "medium"

    certification_score = 82 if recommended_first_cert == "Cyber Essentials" and pressure_type != "not_ready" else 40
    return {
        **entity,
        "singapore_registered_guess": ".sg" in text or "singapore" in text,
        "uen_guess": "",
        "uen_source_url": "",
        "employee_count_guess": None,
        "entity_evidence_json": {
            "terms": sorted({term for term in (*HEALTHCARE_TERMS, *NPO_TERMS, *SOCIAL_TERMS, *B2B_TERMS) if term in text})[:20],
        },
        "campaign_track": "dpo_evidence" if primary_track == "dpo_evidence" else pressure_type,
        "primary_email_track": primary_track,
        "secondary_email_track": secondary_track,
        "regulatory_applicability": (
            ["HIA", "PDPA"] if hia.get("hia_relevant") and hia.get("hia_official_service_type") else ["PDPA"] if personal_intensity in {"medium", "high"} else []
        ),
        "classification_confidence": trigger_confidence,
        "classification_evidence_json": {
            "track_scores": track_scores,
            "selected_track": primary_track,
            "secondary_track": secondary_track,
            "official_hia_service_type": hia.get("hia_official_service_type", ""),
            "official_hia_service_label": hia.get("hia_official_service_label", ""),
            "data_type_signal": data_type,
            "hia_serper_context": row.get("_hia_serper_context") or row.get("_preclassification_company_context") or {},
            "personal_data_intensity": personal_intensity,
            "dpo_owner_signal": dpo_owner,
            "trust_signal": trust_signal if has_customer_trust_pressure(text) else "",
        },
        "classification_rejected_tracks_json": rejected_tracks,
        "pressure_type": pressure_type,
        "pressure_reason": trigger,
        "outreach_trigger_signal": trigger,
        "outreach_trigger_source_url": compact(row.get("best_url") or row.get("url_picked")),
        "outreach_trigger_confidence": trigger_confidence,
        "data_type_signal": data_type,
        "problem_area": problem_area,
        "problem_hypothesis": build_problem_hypothesis(pressure_type, data_type, problem_area),
        "value_asset_offer": value_asset,
        **hia,
        "pdpa_relevant": pressure_type in {"pdpa_safeguards", "customer_trust"},
        "pdpa_reason": (
            "No strong personal-data pressure evidence found."
            if pressure_type == "not_ready"
            else "Private-sector or non-HIA organisation likely handles personal data; Cyber Essentials supports safeguard evidence."
            if not hia["hia_relevant"]
            else "PDPA may still be relevant, but HIA readiness is the primary pressure."
        ),
        "personal_data_intensity": personal_intensity,
        "sensitive_data_likelihood": sensitive_likelihood,
        "pdpa_safeguard_angle": "cyber_essentials_baseline" if pressure_type != "hia_regulatory" else "access_control",
        "recommended_first_cert": recommended_first_cert,
        "recommended_cert_path": recommended_path,
        "certification_reason": certification_reason(pressure_type),
        "certification_fit_score": certification_score,
        "certification_evidence_json": {
            "pressure_type": pressure_type,
            "primary_email_track": primary_track,
            "secondary_email_track": secondary_track,
            "data_type_signal": data_type,
            "track_scores": track_scores,
            "rejected_tracks": rejected_tracks,
        },
        "evidence": [
            {
                "field": "website_content",
                "quote": compact(row.get("website_content", ""))[:240],
                "source_url": compact(row.get("best_url") or row.get("url_picked")),
                "reason": "Used for deterministic outreach classification.",
            }
        ],
        "confidence": trigger_confidence,
    }


def build_problem_hypothesis(pressure_type: str, data_type: str, problem_area: str) -> str:
    if pressure_type == "hia_regulatory":
        return "The practical gap is likely mapping HIA cybersecurity/data-security duties into access, backup, patching, incident and evidence checks."
    if pressure_type == "customer_trust":
        return "The practical gap is likely reusable security evidence for customer or partner reviews."
    if pressure_type == "not_ready":
        return ""
    if problem_area == "evidence_collection":
        return "The practical gap is likely proving safeguards across IT, HR, vendors and operations."
    return f"The practical gap is likely showing clear safeguards for {data_type.replace('_', ' ')}."


def certification_reason(pressure_type: str) -> str:
    if pressure_type == "hia_regulatory":
        return "Cyber Essentials is a practical first baseline for HIA cybersecurity/data-security readiness; it is not HIA compliance."
    if pressure_type == "customer_trust":
        return "Cyber Essentials gives a reusable baseline for access, assets, malware protection, patching, backup and incident readiness evidence."
    if pressure_type == "not_ready":
        return "No certification path should be pitched until stronger evidence is available."
    return "Cyber Essentials supports the security-safeguards side of PDPA readiness; it does not make the organisation PDPA compliant."


def first_name_from_contact(row: dict[str, Any] | str) -> str:
    name = compact(row.get("selected_contact_name") if isinstance(row, dict) else row)
    if not name:
        return ""
    parts = [part for part in name.replace(".", " ").split() if part]
    while parts and parts[0].lower() in {"dr", "mr", "mrs", "ms", "miss", "mdm", "prof"}:
        parts.pop(0)
    return parts[0] if parts else ""


def choose_variant(classification: dict[str, Any]) -> str:
    service = classification.get("hia_service_type_guess", "")
    if classification["pressure_type"] == "hia_regulatory":
        if service == "dental":
            return "dental_clinic"
        if classification["entity_type_guess"] == "clinic":
            return "hia_clinic"
        return "hia_healthcare"
    if classification["entity_type_guess"] in {"npo", "charity", "social_service"}:
        return "npo_social_service"
    if classification.get("campaign_track") == "dpo_evidence":
        return "dpo_evidence"
    if classification["pressure_type"] == "customer_trust":
        return "customer_trust"
    if classification["pressure_type"] == "not_ready":
        return "not_ready"
    return "pdpa_general"


TRACK_SEGMENT_SUBJECT_VARIANTS: dict[str, dict[str, dict[int, dict[str, str]]]] = {
    "hia_regulatory": {
        "clinic": {
            1: {"A": "clinic readiness", "B": "clinic checklist", "C": "readiness map"},
            2: {"A": "HIA / cyber funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: clinic readiness", "B": "clinic evidence check", "C": "readiness question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "dental": {
            1: {"A": "dental readiness", "B": "dental checklist", "C": "dental evidence"},
            2: {"A": "HIA / cyber funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: dental readiness", "B": "dental records check", "C": "dental readiness map"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "specialist": {
            1: {"A": "specialist clinic readiness", "B": "specialist checklist", "C": "clinic evidence map"},
            2: {"A": "HIA / cyber funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: specialist clinic readiness", "B": "specialist records check", "C": "readiness question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "pharmacy": {
            1: {"A": "pharmacy HIA checklist", "B": "pharmacy readiness", "C": "pharmacy records"},
            2: {"A": "HIA / cyber funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: pharmacy HIA checklist", "B": "pharmacy records check", "C": "readiness question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "hearing_care": {
            1: {"A": "hearing-care readiness", "B": "hearing-care checklist", "C": "audiology records"},
            2: {"A": "HIA / cyber funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: hearing-care readiness", "B": "hearing records check", "C": "readiness question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "care": {
            1: {"A": "care readiness", "B": "care records map", "C": "care checklist"},
            2: {"A": "HIA / cyber funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: care readiness", "B": "care records check", "C": "readiness question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
    },
    "pdpa_safeguards": {
        "education": {
            1: {"A": "education data safeguards", "B": "student data checklist", "C": "data safeguards"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: education data safeguards", "B": "student data check", "C": "safeguards question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "hr_recruitment": {
            1: {"A": "HR data safeguards", "B": "candidate data checklist", "C": "client data safeguards"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: HR data safeguards", "B": "candidate data check", "C": "safeguards question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "client_data": {
            1: {"A": "client data safeguards", "B": "client records checklist", "C": "data safeguards"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: client data safeguards", "B": "client records check", "C": "safeguards question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "customer_data": {
            1: {"A": "customer data safeguards", "B": "customer data checklist", "C": "data safeguards"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: customer data safeguards", "B": "customer data check", "C": "safeguards question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "care": {
            1: {"A": "data safeguards", "B": "care data checklist", "C": "care records"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: data safeguards", "B": "care records check", "C": "safeguards question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "general": {
            1: {"A": "data safeguards", "B": "safeguards checklist", "C": "data evidence"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: data safeguards", "B": "personal data check", "C": "safeguards question"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
    },
    "dpo_evidence": {
        "general": {
            1: {"A": "data protection evidence", "B": "evidence checklist", "C": "data evidence"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: data protection evidence", "B": "evidence check", "C": "owner evidence"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
    },
    "customer_trust": {
        "saas": {
            1: {"A": "customer security evidence", "B": "security evidence", "C": "customer checklist"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: customer security evidence", "B": "customer evidence check", "C": "security questions"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "vendor": {
            1: {"A": "vendor security evidence", "B": "supplier evidence", "C": "security evidence"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: vendor security evidence", "B": "vendor evidence check", "C": "security questions"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
        "general": {
            1: {"A": "security evidence", "B": "customer security evidence", "C": "evidence checklist"},
            2: {"A": "Cyber Essentials funding", "B": "funding route check", "C": "support route"},
            3: {"A": "Re: security evidence", "B": "evidence check", "C": "security questions"},
            4: {"A": "close the loop?", "B": "still useful?", "C": "last note"},
        },
    },
}


def email_variant_track(classification: dict[str, Any]) -> str:
    if classification.get("campaign_track") == "dpo_evidence":
        return "dpo_evidence"
    pressure = compact(classification.get("pressure_type"))
    if pressure in {"hia_regulatory", "pdpa_safeguards", "customer_trust"}:
        return pressure
    return "not_ready"


def email_variant_segment(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> str:
    track = email_variant_track(classification)
    asset = compact(copy_brief.get("email_asset_offer")).lower()
    profile = compact(copy_brief.get("clinic_profile_guess"))
    service = compact(classification.get("hia_service_type_guess"))
    text = lower_blob(row)
    if track == "hia_regulatory":
        if profile == "dental" or service == "dental":
            return "dental"
        if profile == "pharmacy" or service == "retail_pharmacy":
            return "pharmacy"
        if profile == "hearing_care" or service == "hearing_care":
            return "hearing_care"
        if profile in {"hospice_long_term_care", "home_care", "nursing_home", "community_hospital"} or service == "long_term_care":
            return "care"
        if profile == "specialist_led" or service == "specialist_OMS":
            return "specialist"
        return "clinic"
    if track == "pdpa_safeguards":
        if "education" in asset:
            return "education"
        if "hr" in asset or "candidate" in asset:
            return "hr_recruitment"
        if "client" in asset:
            return "client_data"
        if "customer" in asset:
            return "customer_data"
        if "care" in asset or classification.get("entity_type_guess") in {"npo", "charity", "social_service"}:
            return "care"
        return "general"
    if track == "customer_trust":
        if "vendor" in asset or "supplier" in text or "outsourcing" in text:
            return "vendor"
        if "customer" in asset or any(term in text for term in ("saas", "software", "platform", "dashboard")):
            return "saas"
        return "general"
    return "general"


def campaign_id_for(row: dict[str, Any], classification: dict[str, Any]) -> str:
    return compact(row.get("campaign_id") or row.get("campaign") or classification.get("campaign_track") or classification.get("pressure_type") or "cold_email")


def row_id_for_variant(row: dict[str, Any]) -> str:
    return compact(row.get("row_id") or row.get("Id") or row.get("id") or "")


def deterministic_option_key_for(row: dict[str, Any], classification: dict[str, Any], email_step: int, available: list[str]) -> str:
    if not available:
        return "A"
    row_id = row_id_for_variant(row)
    if not row_id:
        return available[0]
    seed = f"{row_id}:{campaign_id_for(row, classification)}:{email_step}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return available[int(digest[:12], 16) % len(available)]


def sentence_slot_choice(
    row: dict[str, Any],
    classification: dict[str, Any],
    email_step: int,
    slot_name: str,
    options: dict[str, str],
) -> tuple[str, str]:
    if not options:
        return "", ""
    keys = list(options.keys())
    seed = "|".join(
        (
            row_id_for_variant(row),
            campaign_id_for(row, classification),
            email_variant_track(classification),
            str(classification.get("pressure_type") or ""),
            f"email_{email_step}",
            slot_name,
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    key = keys[int(digest[:12], 16) % len(keys)]
    return key, options[key]


def subject_variants_for(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any], email_step: int) -> dict[str, str]:
    track = email_variant_track(classification)
    segment = email_variant_segment(row, classification, copy_brief)
    track_bank = TRACK_SEGMENT_SUBJECT_VARIANTS.get(track) or {}
    segment_bank = track_bank.get(segment) or track_bank.get("general") or {}
    return segment_bank.get(email_step) or {}


def chosen_subject_variant(
    row: dict[str, Any],
    classification: dict[str, Any],
    copy_brief: dict[str, Any],
    email_step: int,
    fallback: str,
) -> tuple[str, str, list[str]]:
    variants = subject_variants_for(row, classification, copy_brief, email_step)
    if not variants:
        return "A", fallback, [fallback]
    available = list(variants.keys())
    subject_key = deterministic_option_key_for(row, classification, email_step, available)
    subject = variants.get(subject_key) or fallback
    options = list(dict.fromkeys([subject, *variants.values(), fallback]))
    return subject_key, subject, options[:4]


def observation_description(noticed: str, company: str) -> tuple[str, str]:
    text = compact(noticed).rstrip(".")
    company_name = compact(company)
    if company_name and text.lower().startswith(company_name.lower()):
        text = text[len(company_name):].strip(" ,.-")
    patterns = [
        (r"^appears to be\s+", "be"),
        (r"^seems to be\s+", "be"),
        (r"^looks like\s+", "be"),
        (r"^looks to be\s+", "be"),
        (r"^is listed as\s+", "be"),
        (r"^appears to provide\s+", "provides"),
        (r"^appears to handle\s+", "handles"),
    ]
    for pattern, kind in patterns:
        if re.match(pattern, text, re.I):
            return kind, compact(re.sub(pattern, "", text, flags=re.I))
    return "verb", text


def company_observation_bridge(company: str, noticed: str, bridge: str) -> str:
    company_name = compact(company) or "the organisation"
    kind, description = observation_description(noticed, company_name)
    if kind == "be":
        templates = {
            "looks_like": "{company} looks like {description}.",
            "seems_to_be": "{company} seems to be {description}.",
            "listed_as": "{company} is listed as {description}.",
            "looks_to_be": "{company} looks to be {description}.",
        }
        return (templates.get(bridge) or templates["looks_like"]).format(company=company_name, description=description)
    if kind in {"provides", "handles"}:
        return f"{company_name} {kind} {description}."
    if description.lower().startswith(("works with ", "handles ", "provides ", "offers ", "operates ")):
        return f"{company_name} {description}."
    return f"{company_name} looks like {description}."


def observation_after_greeting(observation: str) -> str:
    text = compact(observation)
    if text.startswith("I "):
        return text
    return text[:1].lower() + text[1:] if text else text


def short_record_list(records: str, limit: int = 4) -> str:
    parts = [compact(part) for part in re.split(r",| and ", records) if compact(part)]
    return sentence_join(parts[:limit]) if parts else "records and systems"


def hia_record_spread_list(records: str) -> str:
    parts = [compact(part) for part in re.split(r",| and ", records) if compact(part)]
    filtered = [part for part in parts if part.lower() not in {"patient records", "records"}]
    return sentence_join((filtered or parts)[:4]) if (filtered or parts) else "clinic systems"


def email_1_hook_context_strength(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> str:
    search_context = copy_brief.get("company_context_search") if isinstance(copy_brief.get("company_context_search"), dict) else {}
    signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal"))
    if search_context.get("used") and not generic_personalisation_signal(signal):
        return "strong"
    if email_context_website_weak(row, copy_brief, classification):
        return "weak"
    if generic_personalisation_signal(signal):
        return "weak"
    return "strong"


def email_1_signal_description(copy_brief: dict[str, Any], fallback: str = "") -> str:
    signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal"))
    signal = re.sub(
        r"^[^.]{1,120}\s+(appears to be|appears to provide|appears to handle|operates|handles|provides|works with|has)\s+",
        r"\1 ",
        signal,
        flags=re.I,
    )
    kind, description = observation_description(signal, "the organisation")
    if kind == "provides":
        return compact(f"a provider that provides {description}")
    if kind == "handles":
        return compact(f"an organisation handling {description}")
    if description.lower().startswith("operates "):
        return compact(description[9:])
    if description.lower().startswith("handles "):
        return compact(f"an organisation handling {description[8:]}")
    if description.lower().startswith("provides "):
        return compact(f"a provider that provides {description[9:]}")
    if description.lower().startswith("works with "):
        return compact(f"a company that {description}")
    if description.lower().startswith("has "):
        return compact(description[4:])
    return compact(description) or compact(fallback)


def non_hia_operating_profile(copy_brief: dict[str, Any]) -> str:
    profile = compact(copy_brief.get("clinic_profile_phrase"))
    if not profile:
        return ""
    profile_l = profile.lower()
    if any(term in profile_l for term in ("holding", "group organisation", "day-care", "day care", "nursing home", "social service")):
        return profile
    return ""


def email_1_question_hook(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any], company: str) -> str:
    pressure = compact(classification.get("pressure_type"))
    track = email_variant_track(classification)
    company_name = compact(company) or "your organisation"
    if pressure == "hia_regulatory":
        records = hia_record_spread_list(hia_email_1_records(row, classification, copy_brief))
        profile = email_1_signal_description(copy_brief, compact(copy_brief.get("clinic_profile_phrase")) or "healthcare provider")
        return f"For {profile} like {company_name}, are patient records spread across {records}?"
    if track == "customer_trust":
        profile = email_1_signal_description(copy_brief, "a business with customer security reviews")
        return f"For {profile} like {company_name}, do customer security reviews keep asking for the same proof around access, backups, updates and incidents?"
    systems = compact(copy_brief.get("data_systems_likely"))
    system_list = short_record_list(systems, 4) if systems else "email, shared folders, vendor tools and backups"
    data_label = "personal data"
    if track == "dpo_evidence":
        data_label = "employee, vendor and operations data"
    profile = non_hia_operating_profile(copy_brief) or email_1_signal_description(copy_brief)
    if profile:
        return f"For {profile} like {company_name}, is {data_label} spread across {system_list}?"
    return f"Is {data_label} at {company_name} spread across {system_list}?"


def email_1_careful_hook(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any], company: str) -> str:
    company_name = compact(company) or "your organisation"
    pressure = compact(classification.get("pressure_type"))
    if pressure == "hia_regulatory":
        profile = email_1_signal_description(copy_brief, compact(copy_brief.get("clinic_profile_phrase")) or "healthcare provider")
        return f"For {profile} like {company_name}, patient data may sit in more than one place."
    if email_variant_track(classification) == "customer_trust":
        profile = email_1_signal_description(copy_brief, "a business with customer security reviews")
        return f"For {profile} like {company_name}, the practical issue may be keeping security proof ready before customers ask."
    profile = non_hia_operating_profile(copy_brief) or email_1_signal_description(copy_brief, "an organisation handling personal data")
    return f"For {profile} like {company_name}, the practical issue may be where personal data sits and who can show the proof."


def email_1_first_sentence_override(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any], company: str) -> tuple[str, str]:
    strength = email_1_hook_context_strength(row, classification, copy_brief)
    if strength == "strong":
        return email_1_question_hook(row, classification, copy_brief, company), "question_strong_context"
    return email_1_careful_hook(row, classification, copy_brief, company), "careful_weak_context"


def build_email_1_chain(
    row: dict[str, Any],
    classification: dict[str, Any],
    copy_brief: dict[str, Any],
    observation: str,
    problem: str,
    mechanism: str,
    cta: str,
) -> dict[str, Any]:
    source = compact(copy_brief.get("email_hook_source")) or "website_content"
    search_context = copy_brief.get("company_context_search") if isinstance(copy_brief.get("company_context_search"), dict) else {}
    source_url = compact(copy_brief.get("email_personalisation_source_url") or first_source_url(row))
    confidence = "medium"
    if source == "serper" and search_context.get("used"):
        confidence = "medium"
    elif classification.get("outreach_trigger_confidence") in {"medium", "high"}:
        confidence = str(classification.get("outreach_trigger_confidence"))
    elif email_context_website_weak(row, copy_brief, classification):
        confidence = "low"
    context = {
        "operational_complexity": compact(copy_brief.get("data_flow_complexity") or "unknown"),
        "data_pressure": compact(copy_brief.get("personal_data_handled_guess") or classification.get("data_type_signal") or "unknown"),
        "evidence_gap": compact(copy_brief.get("data_systems_likely") or copy_brief.get("data_risk_reason")),
        "why_now": compact(copy_brief.get("deadline_or_timeline_angle") or copy_brief.get("regulatory_pressure_summary")),
        "specific_hook": compact(problem),
        "source": source,
        "confidence": confidence,
    }
    first_sentence_context = {
        "observation": compact(observation),
        "source": source,
        "source_url": source_url,
        "confidence": confidence,
        "safe_to_use": bool(compact(observation)) and source in {"website_content", "serper"},
    }
    return {
        "observation": compact(observation),
        "pressure_bridge": compact(problem),
        "mechanism": compact(mechanism),
        "cta": compact(cta),
        "source": source,
        "source_url": source_url,
        "confidence": confidence,
        "first_sentence_context": first_sentence_context,
        "email_hook_context": context,
    }


def email_1_body_fixed(greeting: str, company: str, noticed: str, slots: dict[str, str], problem: str, mechanism: str, cta: str) -> str:
    opener = slots.get("observation_opener") or "I noticed"
    bridge = company_observation_bridge(company, noticed, slots.get("company_type_bridge") or "looks_like")
    company_name = compact(company) or "the organisation"
    kind, description = observation_description(noticed, company_name)
    if compact(slots.get("first_sentence_override")):
        observation = compact(slots.get("first_sentence_override"))
    elif opener.lower() == "looks like":
        if kind == "be":
            observation = f"Looks like {company_name} is {description}."
        elif kind in {"provides", "handles"}:
            observation = f"Looks like {company_name} {kind} {description}."
        else:
            observation = f"Looks like {company_name} {description}."
    elif opener.lower() == "had a quick look at":
        if kind == "be":
            observation = f"Had a quick look at {company_name} - looks like {description}."
        elif kind in {"provides", "handles"}:
            observation = f"Had a quick look at {company_name} - looks like it {kind} {description}."
        else:
            observation = f"Had a quick look at {company_name} - looks like it {description}."
    elif opener.lower() == "from the site, it looks like":
        if kind == "be":
            observation = f"Looks like {company_name} is {description}."
        elif kind in {"provides", "handles"}:
            observation = f"Looks like {company_name} {kind} {description}."
        else:
            observation = f"Looks like {company_name} {description}."
    else:
        observation = f"{opener} {bridge}"
    return f"{greeting} {observation_after_greeting(observation)}\n\n{problem}\n\n{mechanism}\n\n{cta}"


EMAIL_2_VALUE_PS = (
    "P.S. We are usually priced near the lower end, and the scope is heavier: "
    "evidence prep, certification support, and a SaaS tool to help the team stay certified."
)


def funding_email_2_body_fixed(prefix: str, funding_line: str, caveat: str) -> str:
    first_line = followup_sentence(prefix, "if the route summary is useful, the next question is usually cost.")
    claim_line = compact(f"{funding_line}{caveat}")
    second_line = (
        f"{claim_line} The useful step is a quick fit check before anyone spends time on a full quote."
        if claim_line
        else "The useful step is a quick fit check before anyone spends time on a full quote."
    )
    return (
        f"{first_line}\n\n"
        f"{second_line}\n\n"
        "Worth checking the support route?\n\n"
        f"{EMAIL_2_VALUE_PS}"
    )


def hia_pricing_email_2_body(
    prefix: str,
    pricing_mode: str,
    funding_safe: bool,
    slots: dict[str, str] | None = None,
) -> str:
    slots = slots or {}
    first_line = followup_sentence(prefix, "if the HIA readiness map is relevant, the next question is usually cost.")
    route_line = slots.get("route_line") or (
        "The tricky part is that support depends on the route and the size of the setup."
    )
    if slots.get("sizing_line"):
        sizing_line = slots["sizing_line"]
    elif pricing_mode == "small_clinic_starting_price":
        sizing_line = "For smaller clinics, that usually means endpoint count and which users need to be covered."
    elif pricing_mode == "group_or_larger_sizing_needed":
        sizing_line = "For group or larger setups, that usually means endpoint count and which users need to be covered."
    else:
        sizing_line = "For smaller clinics or larger setups, that usually means endpoint count and which users need to be covered."
    fit_line = slots.get("fit_line") or "We can do a quick fit check before anyone spends time on a full quote."
    cta = slots.get("cta") or "Worth checking the HIA funding route?"
    return (
        f"{first_line}\n\n"
        f"{route_line} {sizing_line}\n\n"
        f"{fit_line} {cta}\n\n"
        f"{EMAIL_2_VALUE_PS}"
    )


def value_fallback_body_fixed(prefix: str, asset_name: str, slots: dict[str, str] | None = None) -> str:
    slots = slots or {}
    first_line = followup_sentence(
        prefix,
        slots.get("opening_line") or f"if the {asset_name} is useful, the next question is whether there is any support route for the work.",
    )
    second_line = slots.get("second_line") or (
        "I would not assume that from the outside. It depends on the company setup, scope, "
        "and whether Cyber Essentials is the right first step."
    )
    fit_line = slots.get("fit_line") or "We can do a quick fit check before anyone spends time on a full quote."
    cta = slots.get("cta") or "Worth checking the support route?"
    return (
        f"{first_line}\n\n"
        f"{second_line}\n\n"
        f"{fit_line} {cta}\n\n"
        f"{EMAIL_2_VALUE_PS}"
    )


def diagnostic_email_3_body_fixed(diagnostic: str, slots: dict[str, str] | None = None, prefix: str = "") -> str:
    slots = slots or {}
    opener = slots.get("diagnostic_opener") or "Simple check:"
    gap_line = slots.get("gap_line") or "If any of those are unclear, that is usually where the cleanup starts."
    cta = slots.get("cta") or "Worth sending the checklist?"
    return f"{prefix}{opener} {diagnostic}\n\n{gap_line}\n\n{cta}"


def close_loop_body_fixed(prefix: str, close_loop_line: str) -> str:
    if prefix.endswith(", ") and close_loop_line:
        close_loop_line = close_loop_line[:1].lower() + close_loop_line[1:]
    return f"{prefix}{close_loop_line}"


def choose_sentence_slot(
    row: dict[str, Any],
    classification: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    email_key: str,
    email_step: int,
    slot_name: str,
    options: dict[str, str],
) -> str:
    key, sentence = sentence_slot_choice(row, classification, email_step, slot_name, options)
    metadata.setdefault(email_key, {})[slot_name] = key
    return sentence


def email_1_sentence_slots(row: dict[str, Any], classification: dict[str, Any], metadata: dict[str, dict[str, str]]) -> dict[str, str]:
    track = email_variant_track(classification)
    observation_opener_options = {
        "i_noticed": "I noticed",
        "saw_that": "Saw that",
        "looks_like": "Looks like",
        "had_quick_look": "Had a quick look at",
    }
    company_type_bridge_options = {
        "looks_like": "looks_like",
        "seems_to_be": "seems_to_be",
        "listed_as": "listed_as",
        "looks_to_be": "looks_to_be",
    }
    if track == "hia_regulatory":
        problem_options = {
            "hia_messy_evidence": "If so, HIA starting from 2027 makes the practical issue proving that trail: who can access it, which vendors touch it, how backups work and who owns incident steps.",
            "hia_getting_closer": "If so, HIA starting from 2027 makes that spread harder to leave informal: access, vendors, backups and incident ownership need evidence.",
            "hia_prep_access_backup": "If so, HIA starting from 2027 means the messy bit is proving who can access those records, where backups sit, which vendors touch them and what happens during an incident.",
            "hia_readiness_evidence": "If so, HIA starting from 2027 makes the messy part evidence around that trail: access, vendors, backups and incident steps.",
            "hia_real_for_providers": "If so, HIA starting from 2027 for healthcare providers makes the cleanup about that data trail: access, vendors, backups and incident ownership.",
        }
        mechanism_options = {
            "decent_cyber_data_baseline": "We help map that trail into a Cyber Essentials route for the HIA cyber/data-security side.",
            "practical_cyber_data_baseline": "We help turn that records map into a practical Cyber Essentials baseline for the HIA cyber/data-security side.",
            "controls_evidence_baseline": "We help build a Cyber Essentials evidence map for that data trail on the HIA cyber/data-security side.",
        }
    elif track == "dpo_evidence":
        problem_options = {
            "proof_across_ops": "The tricky part is usually finding the proof for that data across HR, IT, vendors and operations.",
            "evidence_different_places": "That evidence usually sits in different places, which makes it painful to pull together.",
            "intent_vs_proof": "The issue is usually not intent. It is proving the trail around that data.",
        }
        mechanism_options = {
            "simple_security_baseline": "We help map that into a Cyber Essentials baseline for access, backups, updates, malware controls and incident response.",
            "practical_evidence_set": "We help turn that into a practical Cyber Essentials evidence set.",
            "security_safeguards_baseline": "We help organise that around Cyber Essentials for the security-safeguards side.",
        }
    elif track == "customer_trust":
        problem_options = {
            "rebuilding_security_proof": "The annoying part is usually rebuilding that proof for each customer review.",
            "customer_same_proof": "Customers tend to ask for the same proof around access, backups, updates and incidents.",
            "reusable_security_evidence": "The useful thing is having that proof ready before customers ask.",
        }
        mechanism_options = {
            "simple_security_baseline": "We help turn that into a Cyber Essentials baseline for access, backups, updates, malware controls and incident response.",
            "practical_evidence_set": "We help turn that into a practical Cyber Essentials evidence set.",
            "security_safeguards_baseline": "We help organise that around Cyber Essentials for the security-safeguards side.",
        }
    else:
        problem_options = {
            "safeguards_not_policy": "PDPA is the legal responsibility. The hard part is usually proving safeguards around that data, not writing another policy.",
            "pdpa_evidence_not_policy": "PDPA is the legal responsibility. The useful bit is having evidence for those safeguards, not just a policy.",
            "day_to_day_protection": "PDPA is the legal responsibility. The tricky part is showing how that data is protected day to day.",
        }
        mechanism_options = {
            "simple_security_baseline": "We help map that into a Cyber Essentials baseline for access, backups, updates, malware controls and incident response.",
            "practical_evidence_set": "We help turn that into a practical Cyber Essentials evidence set.",
            "security_safeguards_baseline": "We help organise that around Cyber Essentials for the security-safeguards side.",
        }
    return {
        "observation_opener": choose_sentence_slot(row, classification, metadata, "email_1", 1, "observation_opener", observation_opener_options),
        "company_type_bridge": choose_sentence_slot(row, classification, metadata, "email_1", 1, "company_type_bridge", company_type_bridge_options),
        "problem_line": choose_sentence_slot(row, classification, metadata, "email_1", 1, "problem_line", problem_options),
        "mechanism_line": choose_sentence_slot(row, classification, metadata, "email_1", 1, "mechanism_line", mechanism_options),
    }


def hia_email_2_sentence_slots(
    row: dict[str, Any],
    classification: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    funding_safe: bool,
) -> dict[str, str]:
    price_text = CISOAAS_HIA_PRICING["price_text"]
    slots = {
        "cost_opener": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "cost_opener",
            {
                "straight_up_on_cost": "Straight up on cost:",
                "one_note_on_cost": "One note on cost:",
                "quick_note_on_pricing": "Quick note on pricing:",
                "on_the_cost_side": "On the cost side:",
            },
        ),
        "endpoint_caveat": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "endpoint_caveat",
            {
                "endpoint_based_no_guess": "CISOaaS pricing is endpoint-based, so I would not guess the final number from the outside.",
                "endpoint_count_drives_quote": "CISOaaS pricing depends on endpoint count, so I would check that before quoting.",
                "endpoint_count_drives_price": "Endpoint count drives CISOaaS pricing, so I would not assume the tier from the outside.",
            },
        ),
        "small_clinic_price": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "small_clinic_price",
            {
                "smaller_clinics_starting_package": f"For smaller clinics, CISOaaS starts around {price_text} before funding.",
                "smaller_clinics_usually_start": f"For CISOaaS, smaller clinics start around {price_text} before funding.",
                "small_clinic_setups_starting_package": f"Small clinic CISOaaS setups start around {price_text} before funding.",
            },
        ),
        "group_larger_setup": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "group_larger_setup",
            {
                "quick_endpoint_check": "Bigger or group setups need an endpoint check.",
                "sized_properly": "Larger setups can move tiers as endpoint count changes.",
                "different_tier": "Bigger or group setups can move tiers quickly, so the endpoint check matters.",
            },
        ),
        "rayn_value_line": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "rayn_value_line",
            {
                "messy_evidence_work": "We handle the messy evidence work. The software helps keep training and governance tidy after certification.",
                "pull_evidence_together": "We help pull the evidence together. The software keeps LEARN and GOVERN organised after that.",
                "readiness_heavy_lifting": "We do the readiness heavy lifting, then the software helps the team stay on top of training and governance.",
                "evidence_chase": "We take on the evidence chase. The software keeps training and governance from becoming a one-off scramble.",
                "controls_and_proof": "We help sort the controls and proof. The software helps LEARN and GOVERN stay organised after the initial push.",
            },
        ),
        "cta": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "cta",
            {
                "hia_funding_route": "Worth checking the HIA funding route?",
                "hia_support_route": "Should I check the HIA support route?",
                "hia_cost_route": "Worth checking the HIA cost route first?",
            },
        ),
    }
    if funding_safe:
        slots["conditional_funding"] = choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "conditional_funding",
            {
                "route_applies_70": "If the route applies, 70% support can reduce the outlay.",
                "route_applies_funding": "If the route applies, funding can reduce the outlay.",
                "programme_confirmation_support": "Subject to programme confirmation, support can reduce the upfront cost.",
            },
        )
    return slots


def non_hia_email_2_sentence_slots(
    row: dict[str, Any],
    classification: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    asset_name: str,
) -> dict[str, str]:
    track = email_variant_track(classification)
    if track == "customer_trust":
        evidence_options = {
            "one_security_question": "The annoying part is usually not answering one customer security question.",
            "same_security_proof": "The hard part is rebuilding the same security proof for every customer review.",
            "customer_reviews_same_proof": "Customer reviews tend to ask for the same proof: access, backups, patching, malware protection and incident response.",
        }
        second_options = {
            "evidence_exists": "The useful check is what evidence already exists for access, backups, updates, malware controls and incident contacts.",
            "basics_cleaner_job": "If the basics are already there, Cyber Essentials prep is usually more straightforward.",
            "small_gaps_lighter": "If the gaps are small, the certification prep is usually lighter.",
        }
    elif track == "dpo_evidence":
        evidence_options = {
            "not_policy": "The tricky part is usually not the policy.",
            "proof_across_ops": "The hard part is finding the proof across HR, IT, vendors and day-to-day operations.",
            "different_teams_tools": "Most of the evidence usually sits across different teams and tools.",
        }
        second_options = {
            "evidence_exists": "The useful check is what evidence already exists for access, backups, updates, malware controls and incident contacts.",
            "basics_cleaner_job": "If the basics are already there, Cyber Essentials prep is usually more straightforward.",
            "small_gaps_lighter": "If the gaps are small, the certification prep is usually lighter.",
        }
    else:
        evidence_options = {
            "simple_first_pass": "A simple first pass is to check what proof already exists: access lists, backups, updates, malware controls and incident contacts.",
            "evidence_exists": "The useful check is what evidence already exists for access, backups, updates, malware controls and incident contacts.",
            "existing_proof": "Before making this bigger than it needs to be, I would check the existing proof: access, backups, updates, malware controls and incident contacts.",
        }
        second_options = {
            "decent_shape": "If those are already in decent shape, Cyber Essentials is usually a cleaner job.",
            "basics_straightforward": "If the basics are already there, Cyber Essentials prep is usually more straightforward.",
            "small_gaps_lighter": "If the gaps are small, the certification prep is usually lighter.",
        }
    return {
        "evidence_line": choose_sentence_slot(row, classification, metadata, "email_2", 2, "evidence_line", evidence_options),
        "second_line": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "second_line",
            {
                "depends_on_setup": "I would not assume that from the outside. It depends on the company setup, scope, and whether Cyber Essentials is the right first step.",
                "route_and_scope": "The route depends on the setup, the scope, and what proof the team already has.",
                "first_step_fit": "The useful check is whether Cyber Essentials is the right first step and what scope needs covering.",
            },
        ),
        "cta": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_2",
            2,
            "cta",
            {
                "support_route": "Worth checking the support route?",
                "fit_check": "Should I check the support route?",
                "scope_route": "Worth checking the route and scope first?",
            },
        ),
    }


def email_3_sentence_slots(
    row: dict[str, Any],
    classification: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    company: str,
    records: str,
    asset: str,
) -> dict[str, str]:
    if classification.get("pressure_type") == "hia_regulatory":
        return {
            "diagnostic_opener": choose_sentence_slot(
                row,
                classification,
                metadata,
                "email_3",
                3,
                "diagnostic_opener",
                {
                    "simple_check": "Simple check:",
                    "one_useful_check": "One useful check:",
                    "quick_diagnostic": "Quick diagnostic:",
                    "check_i_would_use": "The check I would use:",
                    "one_practical_test": "One practical test:",
                },
            ),
            "question_shape": choose_sentence_slot(
                row,
                classification,
                metadata,
                "email_3",
                3,
                "question_shape",
                {
                    "where_records_sit": f"can {company} show where {records} sit today, who owns access, how backups work and who handles incidents?",
                    "map_records": f"can {company} map {records} to owners, access lists, backups and incident contacts?",
                    "owns_access": f"can {company} show who owns access to {records}, where backups sit and who handles incidents?",
                },
            ),
            "gap_line": choose_sentence_slot(
                row,
                classification,
                metadata,
                "email_3",
                3,
                "gap_line",
                {
                    "first_gap": "If that is fuzzy, that is usually the first readiness gap to close.",
                    "cleanup_starts": "If that is unclear, that is usually where the cleanup starts.",
                    "ownership_unclear": "If access or backup ownership is unclear, that is usually where readiness work starts.",
                },
            ),
            "cta": choose_sentence_slot(
                row,
                classification,
                metadata,
                "email_3",
                3,
                "cta",
                {
                    "want_asset": f"Want the {asset}?",
                    "worth_asset": f"Worth sending the {asset}?",
                    "send_asset": f"Should I send the {asset}?",
                },
            ),
        }
    return {
        "diagnostic_opener": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_3",
            3,
            "diagnostic_opener",
                {
                    "simple_check": "Simple check:",
                    "one_useful_check": "One useful check:",
                    "quick_diagnostic": "Quick diagnostic:",
                    "check_i_would_use": "The check I would use:",
                    "one_practical_test": "One practical test:",
                },
            ),
        "gap_line": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_3",
            3,
            "gap_line",
            {
                "cleanup_starts": "If any of those are unclear, that is usually where the cleanup starts.",
                "first_gap": "If that is fuzzy, that is usually the first readiness gap to close.",
                "readiness_work": "If access or backup ownership is unclear, that is usually where readiness work starts.",
            },
        ),
        "cta": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_3",
            3,
            "cta",
            {
                "worth_asset": f"Worth sending the {asset}?",
                "send_asset": f"Should I send the {asset}?",
                "want_asset": f"Want the {asset}?",
            },
        ),
    }


def email_4_sentence_slots(row: dict[str, Any], classification: dict[str, Any], metadata: dict[str, dict[str, str]], asset: str) -> dict[str, str]:
    return {
        "close_loop": choose_sentence_slot(
            row,
            classification,
            metadata,
            "email_4",
            4,
            "close_loop",
            {
                "send_or_leave": f"Should I send the {asset}, or leave this here?",
                "last_note": f"Last note from me. Worth sending the {asset}?",
                "close_or_send": f"Should I close the loop, or send the {asset}?",
                "still_useful": f"Still useful for me to send the {asset}?",
                "still_worth": f"Still worth sending the {asset}?",
                "send_or_park": f"Should I send the {asset}, or park this?",
                "no_issue": f"No issue if not. Still worth sending the {asset}?",
            },
        )
    }


def email_sequence_sentence_slot_metadata(
    row: dict[str, Any],
    classification: dict[str, Any],
    copy_brief: dict[str, Any],
    sentence_slots: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "track": email_variant_track(classification),
        "segment": email_variant_segment(row, classification, copy_brief),
        "campaign_id": campaign_id_for(row, classification),
        "row_id": row_id_for_variant(row),
        "selector": "sha256(row_id:campaign_id:track:pressure_type:email_step:slot_name)",
        "email_steps": sentence_slots,
    }


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def tiny_cta(asset: str) -> str:
    if "map" in asset:
        return "Want the map?"
    if "route" in asset or "funding" in asset:
        return "Should I send the route summary?"
    return "Worth sending the checklist?"


def hia_email_1_cta(row: dict[str, Any], classification: dict[str, Any], asset: str) -> str:
    options = {
        "would_it_help": "Would it help if I sent the HIA readiness map?",
        "want_map": "Want me to send the HIA readiness map?",
        "should_send": "Should I send the HIA readiness map?",
        "useful_send": "Useful if I sent the HIA readiness map?",
    }
    _, sentence = sentence_slot_choice(row, classification, 1, "hia_email_1_cta", options)
    return sentence


def listish_items(value: Any, limit: int = 6) -> list[str]:
    if value is None:
        return []
    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = re.split(r"[\n;,]+", text)
    if isinstance(parsed, dict):
        raw_items = list(parsed.values())
    elif isinstance(parsed, (list, tuple, set)):
        raw_items = list(parsed)
    else:
        raw_items = [parsed]
    items: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            text = compact(item.get("name") or item.get("text") or item.get("value") or " ".join(str(v) for v in item.values()))
        else:
            text = compact(item)
        if text and text.lower() not in {existing.lower() for existing in items}:
            items.append(text[:180])
        if len(items) >= limit:
            break
    return items


def sentence_join(items: list[str], fallback: str = "") -> str:
    if not items:
        return fallback
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def first_source_url(row: dict[str, Any]) -> str:
    for url in listish_items(row.get("source_urls"), limit=4):
        if url.startswith("http"):
            return url
    return compact(row.get("best_url") or row.get("url_picked"))


def email_context_website_weak(row: dict[str, Any], copy_brief: dict[str, Any], classification: dict[str, Any]) -> bool:
    if classification.get("pressure_type") == "not_ready":
        return False
    website_text = compact(row.get("website_content") or row.get("website_scrape") or row.get("crawl_text"))
    signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal"))
    generic_markers = (
        "public services described on its website",
        "unknown organisation",
        "appears to be a unknown",
        "appears to handle unknown",
        "data-protection / operations contact route",
    )
    if len(website_text) < 450:
        return True
    if not signal or any(marker in signal.lower() for marker in generic_markers):
        return True
    if classification.get("outreach_trigger_confidence") == "low" and len(website_text) < 900:
        return True
    return False


def serper_context_enabled() -> bool:
    flag = os.getenv("OUTREACH_SERPER_CONTEXT_ENABLED", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"} and bool(os.getenv("SERPER_API_KEY", "").strip())


def serper_company_context_query(row: dict[str, Any], classification: dict[str, Any]) -> str:
    company = compact(row.get("company_name") or row.get("company_homepage_name"))
    site = compact(row.get("best_url") or row.get("url_picked"))
    pressure = compact(classification.get("pressure_type"))
    terms = {
        "hia_regulatory": "Singapore healthcare clinic services locations",
        "pdpa_safeguards": "Singapore services personal data operations",
        "customer_trust": "Singapore company services clients security",
    }.get(pressure, "Singapore company services")
    domain_hint = ""
    if site:
        domain_hint = re.sub(r"^https?://(www\.)?", "", site, flags=re.I).split("/")[0]
    return compact(f'"{company}" {domain_hint} {terms}')


def fetch_serper_company_context(row: dict[str, Any], classification: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    if not serper_context_enabled():
        return {"source": "serper", "used": False, "reason": "serper_disabled_or_key_missing", "evidence": []}
    query = serper_company_context_query(row, classification)
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": os.getenv("SERPER_API_KEY", "").strip(), "Content-Type": "application/json"},
            json={"q": query, "num": limit},
            timeout=max(4, int(os.getenv("OUTREACH_SERPER_TIMEOUT_SECONDS", "8"))),
        )
        payload: Any = response.json()
        if response.status_code >= 400:
            return {
                "source": "serper",
                "used": False,
                "reason": compact(payload.get("message") if isinstance(payload, dict) else "") or f"HTTP {response.status_code}",
                "query": query,
                "evidence": [],
            }
    except requests.Timeout:
        return {"source": "serper", "used": False, "reason": "timeout", "query": query, "evidence": []}
    except (requests.RequestException, ValueError) as exc:
        return {"source": "serper", "used": False, "reason": compact(str(exc), 180), "query": query, "evidence": []}

    organic = payload.get("organic") if isinstance(payload, dict) else []
    evidence: list[dict[str, str]] = []
    for item in organic if isinstance(organic, list) else []:
        if not isinstance(item, dict):
            continue
        title = compact(item.get("title"))
        link = compact(item.get("link"))
        snippet = compact(item.get("snippet"))
        if not title and not snippet:
            continue
        evidence.append({"title": title[:140], "link": link[:220], "snippet": snippet[:260]})
        if len(evidence) >= limit:
            break
    return {"source": "serper", "used": bool(evidence), "reason": "ok" if evidence else "no_results", "query": query, "evidence": evidence}


def preclassification_serper_pressure(row: dict[str, Any]) -> str:
    text = lower_blob(row)
    company = compact(row.get("company_name")).lower()
    if contains_any(
        f"{company} {text}",
        (
            "clinic",
            "medical",
            "health",
            "healthcare",
            "patient",
            "diagnostic",
            "screening",
            "disease",
            "ivf",
            "fertility",
            "kidney",
            "renal",
            "prenatal",
            "postnatal",
            "lactation",
        ),
    ):
        return "hia_regulatory"
    if contains_any(f"{company} {text}", (*NPO_TERMS, *SOCIAL_TERMS, "classes", "courses", "families", "parents")):
        return "pdpa_safeguards"
    return "pdpa_safeguards"


def serper_context_text(search_context: dict[str, Any]) -> str:
    evidence = search_context.get("evidence") if isinstance(search_context, dict) else []
    parts: list[str] = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        line = compact(f"{item.get('title', '')} {item.get('snippet', '')}")
        if line:
            parts.append(line)
    return " ".join(parts)


def add_preclassification_company_context(row: dict[str, Any]) -> dict[str, Any]:
    website_text = compact(row.get("website_content") or row.get("website_scrape") or row.get("crawl_text"))
    if len(website_text) >= 450 or not serper_context_enabled():
        return row
    provisional = {"pressure_type": preclassification_serper_pressure(row)}
    search_context = fetch_serper_company_context(row, provisional)
    if not search_context.get("used"):
        return row
    context_text = serper_context_text(search_context)
    if not context_text:
        return row
    augmented = dict(row)
    augmented["_preclassification_company_context"] = search_context
    augmented["_serper_context_text"] = context_text
    return augmented


def serper_context_observation(row: dict[str, Any], classification: dict[str, Any], search_context: dict[str, Any]) -> str:
    company = email_display_company_name(row)
    evidence = search_context.get("evidence") if isinstance(search_context, dict) else []
    text = " ".join(
        compact(f"{item.get('title', '')} {item.get('snippet', '')}")
        for item in evidence
        if isinstance(item, dict)
    ).lower()
    if not text:
        return ""
    if classification.get("pressure_type") == "hia_regulatory":
        if any(term in text for term in ("group", "locations", "branches", "outlets", "islandwide")):
            return f"{company} operates a multi-location or group healthcare operation."
        if any(term in text for term in ("medical clinic", "gp clinic", "general practitioner", "doctor")):
            return f"{company} provides GP or medical-clinic services."
        if any(term in text for term in ("specialist", "cardiology", "surgery", "dental", "dermatology", "oncology", "orthopaedic", "fertility", "ivf")):
            return f"{company} provides specialist healthcare services."
        if any(term in text for term in ("health screening", "diagnostic", "laboratory", "imaging")):
            return f"{company} handles screening or diagnostic healthcare workflows."
        if "health" in text or "clinic" in text or "patient" in text:
            return f"{company} operates in a healthcare setting."
    if classification.get("pressure_type") == "customer_trust":
        if any(term in text for term in ("saas", "software", "platform", "managed service", "outsourcing", "enterprise")):
            return f"{company} works in a B2B service or platform setting."
    if classification.get("pressure_type") == "pdpa_safeguards":
        if any(term in text for term in ("education", "students", "training", "courses")):
            return f"{company} handles education or training operations."
        if any(term in text for term in ("charity", "social service", "beneficiary", "care", "community")):
            return f"{company} operates care or community-service operations."
    return ""


def apply_company_context_search(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> dict[str, Any]:
    if not email_context_website_weak(row, copy_brief, classification):
        copy_brief["company_context_search"] = {"source": "website_content", "used": False, "reason": "website_context_strong", "evidence": []}
        return copy_brief
    preclassification_context = row.get("_preclassification_company_context")
    if isinstance(preclassification_context, dict) and preclassification_context.get("used"):
        search_context = preclassification_context
    else:
        search_context = fetch_serper_company_context(row, classification)
    copy_brief["company_context_search"] = search_context
    observation = serper_context_observation(row, classification, search_context)
    local_signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal"))
    should_override = bool(observation) and (
        not generic_personalisation_signal(observation)
        or generic_personalisation_signal(local_signal)
        or not local_signal
    )
    if should_override:
        copy_brief["prospect_facing_signal"] = observation
        copy_brief["email_personalisation_signal"] = observation
        copy_brief["email_hook_source"] = "serper"
        copy_brief["email_personalisation_source_url"] = next(
            (item.get("link", "") for item in search_context.get("evidence", []) if isinstance(item, dict) and item.get("link")),
            compact(copy_brief.get("email_personalisation_source_url")),
        )
    return copy_brief


def concrete_service_cues(row: dict[str, Any], text: str) -> list[str]:
    name_text = f"{row.get('company_name') or ''} {row.get('company_homepage_name') or ''}".lower()
    haystack = f"{name_text} {text}"
    cues: list[str] = []

    def add(cue: str) -> None:
        if cue and cue.lower() not in {existing.lower() for existing in cues}:
            cues.append(cue)

    if contains_any(haystack, LONG_TERM_CARE_TERMS):
        if home_care_subtype(haystack):
            add("home-care / caregiver service signals")
            add("client, patient, caregiver, family and staff record signals")
        elif "hospice" in haystack or "palliative" in haystack:
            add("hospice/long-term care service signals")
            add("patient, resident, family and volunteer data signals")
        else:
            add("long-term care and resident/patient-care signals")
    if any(term in haystack for term in ("hearing", "audiology", "hearing aid", "hearing assessment", "hearing test")):
        add("hearing-care services")
        add("appointment, test and device-related record signals")
    if "physio" in haystack or "physiotherapy" in haystack:
        add("physiotherapy/allied-health service signals")
        add("appointment, treatment and exercise-plan record signals")
    if any(term in haystack for term in ("psychology", "psychologist", "mental health", "counselling", "counseling")):
        add("psychology/mental-health service signals")
        add("appointment, assessment and case-note record signals")
    if any(term in haystack for term in ("dental", "dentist", "orthodontic")):
        add("dental service signals")
    if any(term in haystack for term in ("pharmacy", "pharmacist", "compounding")):
        add("pharmacy service signals")
    if contains_any(haystack, DIAGNOSTIC_SERVICE_TERMS):
        add("diagnostic, screening or laboratory service signals")
    if contains_any(haystack, SPECIALIST_SERVICE_TERMS):
        subtype = specialist_subtype(haystack)
        if subtype == "cardiology":
            add("heart/cardiology specialist-care signals")
        elif subtype == "pain":
            add("pain-management specialist-care signals")
        elif subtype == "surgery":
            add("surgical specialist-care signals")
        elif subtype == "dermatology":
            add("dermatology specialist-care signals")
        elif subtype == "eye":
            add("eye/ophthalmology specialist-care signals")
        elif subtype == "endocrinology":
            add("endocrinology specialist-care signals")
        elif "oncology" in haystack or "radiation" in haystack:
            add("radiation/oncology specialist-care signals")
        elif "digestive" in haystack or "gastroenterology" in haystack:
            add("digestive/gastroenterology specialist-care signals")
        elif subtype == "rheumatology":
            add("rheumatology specialist-care signals")
        elif "orthopaedic" in haystack or "orthopedic" in haystack:
            add("orthopaedic specialist-care signals")
        elif "endocrinology" in haystack:
            add("endocrinology specialist-care signals")
        elif "aesthetic" in haystack or "plastic surgery" in haystack:
            add("aesthetic/plastic-surgery specialist-care signals")
        else:
            add("specialist clinic service signals")
    if any(term in haystack for term in ("clinic", "doctor", "consultation", "treatment", "patient", "medical")) and not contains_any(haystack, LONG_TERM_CARE_TERMS):
        add("clinic service and patient-care signals")
    if any(term in haystack for term in ("resident", "beneficiary", "volunteer", "social service", "charity", "community care")) and not cues:
        add("care/community-service signals around residents, beneficiaries, volunteers and staff")
    if any(term in haystack for term in ("enterprise", "b2b", "vendor", "dashboard", "integration", "outsourcing", "saas", "client portal")) and not cues:
        add("B2B/client-service signals around customer security questions and reusable evidence")
    return cues


def public_signal_summary(
    row: dict[str, Any], text: str, services: list[str], locations: list[str], team: list[str]
) -> dict[str, str]:
    service_cues = concrete_service_cues(row, text)
    generic_service_terms = ("clinic service", "specialist clinic", "healthcare activity", "customer data")
    usable_services = [
        service
        for service in services
        if service and not (service_cues and any(term in service.lower() for term in generic_service_terms))
    ]
    service_detail = sentence_join([*service_cues, *usable_services][:3])

    team_detail = sentence_join(team[:2])
    if team_detail and any(term in team_detail.lower() for term in ("doctor", "practitioner", "clinician", "audiologist", "therapist", "psychologist")):
        team_detail = f"{team_detail} team/practitioner signals"
    if not team_detail:
        if any(term in text for term in ("doctor", "practitioner", "clinician", "audiologist", "therapist")):
            team_detail = "team/practitioner signals"
        elif any(term in text for term in ("volunteer", "staff", "care team")):
            team_detail = "staff and volunteer signals"
        else:
            team_detail = ""

    location_detail = sentence_join(locations[:2])
    if not location_detail and "singapore" in text:
        location_detail = "Singapore-facing operations"

    return {"service": service_detail, "team": team_detail, "location": location_detail}


def copy_brief_ready(classification: dict[str, Any], copy_brief: dict[str, Any]) -> bool:
    if classification.get("pressure_type") == "not_ready":
        return False
    required = ("email_personalisation_signal", "email_problem_statement", "email_mechanism_statement", "email_cta")
    if not all(compact(copy_brief.get(field)) for field in required):
        return False
    return not generic_personalisation_signal(copy_brief.get("email_personalisation_signal", ""))


def empty_email_sequence() -> dict[str, Any]:
    emails = {
        "email_1": {"subject_options": ["not ready"], "chosen_subject": "not ready", "body": ""},
        "email_2": {"subject_options": ["not ready"], "chosen_subject": "not ready", "body": ""},
        "email_3": {"subject_options": ["not ready"], "chosen_subject": "not ready", "body": ""},
        "email_4": {"subject_options": ["close the loop?"], "chosen_subject": "close the loop?", "body": ""},
        "evidence_used": [],
        "claims_avoided": [],
        "quality_notes": ["not_ready"],
    }
    for key in ("email_1", "email_2", "email_3", "email_4"):
        emails[key]["word_count"] = 0
    return emails


def prospect_facing_signal(signal: str, row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> str:
    signal_l = compact(signal).lower()
    if not signal_l:
        return ""
    text = lower_blob(row)
    service_type = compact(classification.get("hia_service_type_guess")).lower()
    pressure = compact(classification.get("pressure_type")).lower()
    entity = compact(classification.get("entity_type_guess")).lower()
    company = compact(row.get("company_name"))

    if company and signal_l.startswith(company.lower()) and any(
        marker in signal_l for marker in (" appears ", " works ", " has ", " runs ", " provides ")
    ):
        return compact(signal).rstrip(".") + "."
    if ("appears to be " in signal_l or "appears to provide " in signal_l or "appears to handle " in signal_l) and "signals" not in signal_l:
        return compact(signal).rstrip(".") + "."
    if service_type == "hearing_care" or "hearing-care" in signal_l or "hearing" in text:
        return "your website lists hearing tests, hearing aids and audiology support."
    if service_type == "long_term_care" or "hospice/long-term care" in signal_l or contains_any(text, LONG_TERM_CARE_TERMS):
        if home_care_subtype(text):
            return "your website lists home-care / caregiver services."
        return "your website lists hospice / palliative-care services."
    if service_type == "allied_health" and ("physio" in signal_l or "physio" in text or "exercise-plan" in signal_l):
        return "your website lists physiotherapy services and treatment support."
    if service_type == "allied_health" and (
        "psychology" in signal_l or "mental-health" in signal_l or "psychologist" in text or "case-note" in signal_l
    ):
        return "your website lists psychology / mental-health services and assessment support."
    if service_type == "diagnostic" or "screening/diagnostic" in signal_l:
        return "your website lists laboratory / diagnostic services."
        if service_type == "specialist_oms" and specialist_subtype(text) == "cardiology":
            return "your website lists heart/cardiology consultations and specialist-led care."
    if service_type == "specialist_oms" and specialist_subtype(text) == "fertility":
        return "your website lists fertility / IVF specialist consultations and treatment services."
    if service_type == "specialist_oms" and specialist_subtype(text) == "pain":
        return "your website lists pain management consultations and procedure-related care."
    if service_type == "specialist_oms" and specialist_subtype(text) == "surgery":
        return "your website lists surgical consultations and procedure-related care."
    if service_type == "specialist_oms" and specialist_subtype(text) == "dermatology":
        return "your website lists dermatology consultations and skin treatment services."
    if service_type == "specialist_oms" and specialist_subtype(text) == "eye":
        return "your website lists eye/ophthalmology consultations and specialist-led care."
    if service_type == "specialist_oms" and ("oncology" in signal_l or "radiation" in signal_l or "oncology" in text or "radiation" in text):
        return "your website lists oncology/radiation care and specialist-led treatment services."
    if service_type == "specialist_oms" and (
        "digestive" in signal_l or "gastroenterology" in signal_l or "digestive" in text or "gastroenterology" in text
    ):
        return "your website lists gastroenterology consultations and specialist-led care."
    if service_type == "specialist_oms" and specialist_subtype(text) == "rheumatology":
        return "your website lists rheumatology consultations and specialist-led care."
    if service_type == "specialist_oms" and specialist_subtype(text) == "endocrinology":
        return "your website lists endocrinology consultations and specialist-led care."
    if service_type == "retail_pharmacy":
        return "your website lists pharmacy and compounding services."
    if service_type == "dental":
        return "your website lists dental services and patient appointments."
    if service_type == "specialist_oms":
        return "your website lists specialist-led clinic services."
    if pressure == "customer_trust" or "b2b/client-service" in signal_l:
        return "your company works with business customers who may ask for reusable security evidence."
    if entity in {"npo", "charity", "social_service"} or "care/community-service" in signal_l:
        return "your organisation works in a care/community-service setting handling resident, beneficiary, volunteer and staff data."
    if service_type == "gp_oms" or "medical clinic, doctor and outpatient appointment signals" in signal_l:
        if "family" in text:
            return "your website lists family clinic services and doctor-led consultations."
        if "aesthetic" in text:
            return "your website lists medical/aesthetic clinic services and doctor-led consultations."
        return "your website lists outpatient medical consultations and doctor-led services."
    if "clinic service and team/practitioner signals" in signal_l:
        return "your website lists clinic services and practitioner-led care."
    if signal_l.startswith("shows ") and signal_l.endswith("signals."):
        detail = compact(signal[6:-1]).replace(" signals", "")
        if detail:
            return f"your website lists {detail}."
    if signal_l.startswith("shows "):
        return f"your website lists {compact(signal[6:])}"
    if signal_l.startswith("appears to handle "):
        detail = compact(signal[18:])
        return f"you appear to handle {detail}"
    if signal_l.startswith("appears to operate in "):
        detail = compact(signal[21:])
        return f"you operate in {detail}"
    if company:
        signal = re.sub(rf"^{re.escape(company)}\s+", "", compact(signal), flags=re.IGNORECASE)
    signal = re.sub(r"\bshows\b", "lists", signal, count=1, flags=re.IGNORECASE)
    signal = re.sub(r"\bsignals\b", "", signal, flags=re.IGNORECASE)
    signal = re.sub(r"\s+", " ", signal).strip(" .")
    if signal.lower().startswith("appears to "):
        signal = signal[11:]
    if signal.lower().startswith("handle "):
        company_name = compact(row.get("company_name"))
        signal = f"{company_name} appears to {signal}" if company_name else "you " + signal
    elif signal.lower().startswith("provide "):
        signal = "you " + signal
    elif signal.lower().startswith("provides "):
        signal = "you provide " + signal[9:]
    elif signal.lower().startswith(("lists ", "provide ", "provides ", "work ", "works ")):
        signal = "your website " + signal
    elif not signal.lower().startswith(("you ", "your website ")):
        signal = "your website " + signal
    return signal.rstrip(".") + "."


def email_contains_internal_signal_language(body: str) -> bool:
    body_l = compact(body).lower()
    forbidden_patterns = (
        r"\bsignals\b",
        r"\bshows\s+.+?\bsignals\b",
        r"\bpublic signals\b",
        r"\bservice signals\b",
        r"\bteam/practitioner signals\b",
        r"\brecord signals\b",
    )
    return any(re.search(pattern, body_l) for pattern in forbidden_patterns)


HIA_BATCH_EMAIL_PATTERNS = (
    r"\bbatch\s+[123]\b",
    r"\bsep\s+2027\b",
    r"\bsep\s+2028\b",
    r"\bmar\s+2030\b",
    r"\bhia window\b",
)


def email_contains_hia_batch_wording(body: str) -> bool:
    body_l = compact(body).lower()
    return any(re.search(pattern, body_l) for pattern in HIA_BATCH_EMAIL_PATTERNS)


SPECIALIST_SERVICE_SUMMARIES = (
    (("heart clinic", "heart centre", "heart center", "heart & vascular", "cardiology", "cardiac", "cardiovascular", "ecg", "echocardiogram"), "heart/cardiology care"),
    (("pain management", "spine pain", "pain clinic", "anaesthesia", "injections"), "pain management care"),
    (("fertility", "ivf", "assisted reproduction", "reproductive medicine"), "fertility / IVF care"),
    (("cancer centre", "cancer center", "cancer care", "oncology", "radiation"), "oncology / radiation care"),
    (("ophthalmology", "ophthalmologist", "vision", "cataract", "retina", "lasik", "optometry", "eye clinic"), "eye care"),
    (("digestive", "gastroenterology", "colon", "liver", "gallbladder"), "gastroenterology / digestive care"),
    (("rheumatology", "rheumatologist", "arthritis", "lupus"), "rheumatology care"),
    (("dermatology", "dermatologist", "skin", "acne", "eczema", "mole", "laser"), "dermatology care"),
    (("endocrinology", "diabetes", "thyroid"), "endocrinology care"),
    (("orthopaedic", "orthopedic", "sports"), "orthopaedic / sports medicine"),
    (("urology", "robotic"), "urology care"),
    (("brain", "spine", "nerve", "neurology", "neurosurgery"), "brain, spine and nerve care"),
    (("surgery", "surgeon", "surgical", "operation", "consent", "post-operative"), "surgical care"),
    (("specialist",), "specialist care"),
)


def specialist_subtype(text: str) -> str:
    if any(term in text for term in ("neuroscience", "neurology", "neurosurgery")):
        return "neuroscience"
    if any(term in text for term in ("fertility", "ivf", "assisted reproduction", "reproductive medicine")):
        return "fertility"
    if any(term in text for term in ("digestive", "gastroenterology")):
        return "gastroenterology"
    if any(term in text for term in ("endocrinology", "endocrinologist", "diabetes", "thyroid")):
        return "endocrinology"
    if any(term in text for term in ("rheumatology", "rheumatologist", "arthritis", "lupus")):
        return "rheumatology"
    if any(term in text[:700] for term in ("surgery", "surgeon", "surgical", "thoracic")):
        return "surgery"
    if any(term in text for term in ("cancer centre", "cancer center", "cancer care", "oncology", "radiation")):
        return "oncology"
    if has_cardiology_subtype(text):
        return "cardiology"
    if any(term in text for term in ("orthopaedic", "orthopedic", "orthopaedics", "orthopedics", "sports medicine")):
        return "orthopaedic"
    if any(term in text for term in ("pain management", "spine pain", "pain clinic", "anaesthesia", "injections")) or (
        "pain" in text and "clinic" in text
    ):
        return "pain"
    if any(term in text for term in ("ophthalmology", "ophthalmologist", "vision", "cataract", "retina", "lasik", "optometry", "eye clinic")):
        return "eye"
    if any(term in text for term in ("dermatology", "dermatologist", "skin", "acne", "eczema", "mole", "laser")):
        return "dermatology"
    if any(term in text for term in ("surgery", "surgeon", "surgical", "operation", "consent", "post-operative")):
        return "surgery"
    return ""


def has_cardiology_subtype(text: str) -> bool:
    return any(
        term in text
        for term in (
            "cardiology",
            "cardiac",
            "cardiovascular",
            "ecg",
            "echocardiogram",
            "heart clinic",
            "heart centre",
            "heart center",
            "heart & vascular",
        )
    )


def primary_profile_source_text(row: dict[str, Any]) -> str:
    return " ".join(
        compact(value)
        for value in (
            row.get("company_name"),
            row.get("company_homepage_name"),
            compact(row.get("website_content"))[:1800],
            compact(row.get("services_detected"))[:900],
        )
        if value
    ).lower()


def home_care_subtype(text: str) -> bool:
    return any(term in text for term in ("caregiver", "home care", "home nursing", "patient care at home"))


def primary_service_summary_for_profile(row: dict[str, Any], text: str, service_type: str) -> str:
    if service_type == "allied_health" and ("psychology" in text or "psychologist" in text or "mental health" in text):
        return "psychology / mental-health services"
    if service_type == "allied_health":
        return "physiotherapy or treatment support"
    for terms, summary in SPECIALIST_SERVICE_SUMMARIES:
        if any(term in text for term in terms):
            return summary
    if service_type == "diagnostic":
        return "screening or diagnostic services"
    if service_type == "hearing_care":
        return "hearing tests, hearing aids and audiology support"
    if service_type == "retail_pharmacy":
        return "pharmacy and compounding services"
    if service_type == "dental":
        return "dental services"
    service_terms = listish_items(row.get("services_detected"))
    return sentence_join(service_terms[:2]) or ""


def infer_clinic_profile(row: dict[str, Any], classification: dict[str, Any], text: str) -> dict[str, Any]:
    service_type = str(classification.get("hia_service_type_guess") or "")
    official_service = str(classification.get("hia_official_service_type") or "")
    company = compact(row.get("company_name"))
    parent = compact(row.get("parent_company"))
    locations = listish_items(row.get("locations_detected"))
    team = listish_items(row.get("leadership_or_team_signals")) or listish_items(row.get("contact_info_detected"))
    source_terms = " ".join(
        compact(value)
        for value in (
            company,
            row.get("company_homepage_name"),
            row.get("services_detected"),
            row.get("locations_detected"),
            row.get("leadership_or_team_signals"),
            row.get("website_content"),
        )
        if value
    )
    source_l = source_terms.lower()
    primary_source_l = " ".join(
        compact(value)
        for value in (
            company,
            row.get("company_homepage_name"),
            compact(row.get("website_content"))[:1800],
            compact(row.get("services_detected"))[:900],
        )
        if value
    ).lower()
    evidence: list[str] = []

    def add_evidence(label: str) -> None:
        if label and label not in evidence:
            evidence.append(label)

    location_count = len(locations)
    if not location_count:
        location_count = len(set(re.findall(r"\b(?:bedok|jurong|novena|chinatown|orchard|tampines|woodlands|toa payoh|ang mo kio|bukit|nex)\b", source_l)))
    doctor_terms = len(re.findall(r"\b(?:dr\.?|doctor|physician|dentist|audiologist|physiotherapist|psychologist|consultant)\b", source_l))
    named_doctors = len(set(re.findall(r"\bdr\.?\s+[a-z][a-z]+", source_l)))
    has_group = bool(parent) or any(term in source_l for term in (" group", "branches", "multiple locations", "our clinics", "clinic group", "medical group"))
    if has_group or location_count >= 2 or named_doctors >= 4:
        add_evidence("group, parent, multi-location or many-practitioner evidence")
        structure = "clinic_group"
    elif "solo gp" in source_l or (named_doctors == 1 and location_count == 1 and any(term in source_l for term in ("gp", "family clinic", "general practitioner"))):
        add_evidence("one named doctor or solo GP-style evidence")
        structure = "solo_gp"
    elif doctor_terms >= 3 or named_doctors >= 2 or len(team) >= 2:
        add_evidence("multiple practitioner/team evidence")
        structure = "multi_practitioner"
    else:
        structure = "single_site_or_unknown"

    has_aesthetic = any(term in source_l for term in ("aesthetic", "medical aesthetics", "injectable"))
    primary_aesthetic = "aesthetic" in company.lower() or any(term in primary_source_l[:700] for term in ("aesthetic", "medical aesthetics", "injectable"))
    has_cancer_centre = any(term in source_l for term in ("cancer centre", "cancer center", "cancer care", "oncology", "radiation"))
    has_specialist = has_cardiology_subtype(primary_source_l) or any(
        term in primary_source_l
        for term in (
            "gastroenterology",
            "cancer centre",
            "cancer center",
            "cancer care",
            "oncology",
            "dermatology",
            "dermatologist",
            "pain management",
            "anaesthesia",
            "spine pain",
            "injections",
            "ophthalmology",
            "ophthalmologist",
            "vision",
            "cataract",
            "retina",
            "lasik",
            "optometry",
            "endocrinology",
            "orthopaedic",
            "radiation",
            "digestive",
            "surgery",
            "surgeon",
            "surgical",
            "specialist",
        )
    )
    has_gp = any(term in source_l for term in ("family clinic", "family medicine", "general practitioner", " gp ", "outpatient", "doctor-led", "medical clinic"))
    primary_has_gp = any(
        term in primary_source_l
        for term in ("family clinic", "family medicine", "general practitioner", " gp ", "outpatient", "doctor-led", "medical clinic")
    )
    has_diagnostic = any(term in source_l for term in ("diagnostic", "screening", "laboratory", " lab ", "radiology", "nuclear medicine", "test reports"))
    has_strong_lab = any(term in source_l for term in ("clinical laboratory", "diagnostic lab", "diagnostic laboratory", "medical laboratory", "radiology", "nuclear medicine", "test reports", "lab test"))
    has_neuro_institute = any(
        term in source_l
        for term in (
            "national neuroscience institute",
            "neuroscience institute",
            "neuroscience",
            "neurology",
            "neurosurgery",
            "brain, spine and nerve",
        )
    )

    if service_type == "diagnostic":
        guess = "diagnostic_lab"
        add_evidence("diagnostic, screening or lab terms")
    elif service_type == "hospital" or official_service == "acute_hospital" or "hospital" in company.lower():
        guess = "hospital"
        add_evidence("hospital service terms")
    elif service_type == "dental" or (has_dental_service_evidence(primary_source_l) and not has_gp):
        guess = "dental"
        add_evidence("dental terms")
    elif primary_aesthetic:
        guess = "aesthetic_medical"
        add_evidence("medical/aesthetic terms")
    elif any(term in primary_source_l for term in ("holding company", "holdings", "public healthcare institutions", "healthcare institutions")):
        guess = "healthcare_group"
        add_evidence("healthcare holding or group terms")
    elif any(term in primary_source_l for term in ("daycare", "day care", "elderly", "elders", "senior care")):
        guess = "elder_daycare"
        add_evidence("elder day-care or senior-care terms")
    elif service_type == "allied_health" and any(
        term in primary_source_l for term in ("psychotherapy", "counselling", "counseling", "mental health", "wellbeing", "wellness journey")
    ):
        guess = "mental_health"
        add_evidence("psychology or mental-health terms")
    elif structure == "solo_gp" and (service_type == "GP_OMS" or primary_has_gp or has_gp):
        guess = "solo_gp"
        add_evidence("solo GP/outpatient evidence")
    elif has_family_clinic_evidence(row, primary_source_l) or primary_has_gp:
        guess = "multi_doctor_gp" if structure == "multi_practitioner" else "family_gp"
        add_evidence("family clinic, GP or outpatient terms")
    elif has_neuro_institute:
        guess = "specialist_led"
        add_evidence("neuroscience or neurology specialist terms")
    elif has_cancer_centre:
        guess = "specialist_led"
        add_evidence("cancer, oncology or radiation specialist terms")
    elif service_type == "allied_health" and any(term in source_l for term in ("psychology", "psychologist", "counselling", "counseling", "mental health", "case-note")):
        guess = "mental_health"
        add_evidence("psychology or mental-health terms")
    elif service_type == "allied_health" or (
        service_type != "specialist_OMS" and any(term in source_l for term in ("physiotherapy", "physio", "rehab", "exercise-plan", "treatment support", "podiatry", "podiatrist"))
    ):
        guess = "allied_health"
        add_evidence("allied-health or physiotherapy terms")
    elif service_type == "specialist_OMS" or (has_specialist and not has_gp):
        guess = "specialist_led"
        add_evidence("specialist-led care terms")
    elif service_type == "retail_pharmacy" or any(term in source_l for term in ("pharmacy", "pharmacist", "compounding", "dispensing")):
        guess = "pharmacy"
        add_evidence("pharmacy or compounding terms")
    elif service_type == "hearing_care" or any(term in source_l for term in ("hearing care", "hearing aid", "audiology", "hearing test", "device fitting")):
        guess = "hearing_care"
        add_evidence("hearing-care terms")
    elif structure == "solo_gp" and (service_type == "GP_OMS" or has_gp):
        guess = "solo_gp"
        add_evidence("solo GP/outpatient evidence")
    elif service_type == "GP_OMS" and has_family_clinic_evidence(row, source_l):
        guess = "family_gp"
        add_evidence("family clinic, GP or outpatient terms")
    elif service_type == "GP_OMS" and has_gp:
        guess = "multi_doctor_gp" if structure == "multi_practitioner" else "family_gp"
        add_evidence("GP/outpatient evidence")
    elif official_service == "nursing_home":
        guess = "nursing_home"
        add_evidence("nursing-home service terms")
    elif official_service == "community_hospital":
        guess = "community_hospital"
        add_evidence("community-hospital service terms")
    elif official_service == "contingency_care_service" or home_care_subtype(primary_source_l):
        guess = "home_care"
        add_evidence("home-care or caregiver terms")
    elif service_type == "long_term_care" and any(
        term in primary_source_l for term in ("home care", "caregiver", "hospice", "palliative", "nursing home", "senior care", "long-term care")
    ):
        guess = "hospice_long_term_care"
        add_evidence("hospice or long-term care terms")
    elif service_type == "long_term_care":
        guess = "hospice_long_term_care"
        add_evidence("long-term care service type")
    elif has_aesthetic and service_type not in {"GP_OMS", "allied_health", "diagnostic"}:
        guess = "aesthetic_medical"
        add_evidence("medical/aesthetic terms")
    elif structure == "solo_gp" and (service_type == "GP_OMS" or has_gp):
        guess = "solo_gp"
        add_evidence("solo GP/outpatient evidence")
    elif service_type == "GP_OMS" and has_family_clinic_evidence(row, source_l):
        guess = "family_gp"
        add_evidence("family clinic, GP or outpatient terms")
    elif service_type == "GP_OMS" and has_gp:
        guess = "multi_doctor_gp" if structure == "multi_practitioner" else "family_gp"
        add_evidence("GP/outpatient evidence")
    elif structure == "solo_gp" and (
        service_type == "GP_OMS"
        or has_gp
    ):
        guess = "solo_gp"
        add_evidence("solo GP/outpatient evidence")
    elif has_gp:
        guess = "family_gp"
        add_evidence("family clinic, GP or outpatient terms")
    elif service_type == "diagnostic" and (has_strong_lab or not has_gp):
        guess = "diagnostic_lab"
        add_evidence("diagnostic, screening or lab terms")
    elif has_diagnostic and has_strong_lab:
        guess = "diagnostic_lab"
        add_evidence("diagnostic, screening or lab terms")
    elif service_type == "GP_OMS":
        guess = "solo_gp" if structure == "solo_gp" else "multi_doctor_gp" if structure == "multi_practitioner" else "family_gp"
        add_evidence("GP/outpatient service type")
    elif structure == "clinic_group":
        guess = "clinic_group"
    else:
        guess = "healthcare_provider"

    if structure == "clinic_group" and guess in {"family_gp", "multi_doctor_gp", "healthcare_provider"}:
        guess = "clinic_group"

    confidence = "high" if len(evidence) >= 2 or service_type not in {"", "unknown"} else "medium" if evidence else "low"
    primary = primary_service_summary_for_profile(row, primary_source_l, service_type)
    profile = {
        "clinic_profile_guess": guess,
        "clinic_profile_phrase": "",
        "clinic_structure_guess": structure,
        "clinic_structure_confidence": confidence,
        "umbrella_or_group_guess": "yes" if structure == "clinic_group" else "no" if structure != "single_site_or_unknown" else "unknown",
        "solo_gp_likelihood": "likely" if structure == "solo_gp" else "possible" if named_doctors == 1 and guess in {"family_gp", "multi_doctor_gp"} else "unlikely",
        "specialist_led_likelihood": "likely" if guess == "specialist_led" else "possible" if service_type == "specialist_OMS" else "unlikely",
        "multi_practitioner_likelihood": "likely" if structure in {"multi_practitioner", "clinic_group"} else "possible" if doctor_terms >= 2 else "unknown",
        "primary_service_summary": primary,
        "clinic_structure_evidence": evidence[:6],
    }
    profile["clinic_profile_phrase"] = prospect_facing_profile_phrase(profile, row, classification, {})
    return profile


def prospect_facing_profile_phrase(
    profile: dict[str, Any],
    row: dict[str, Any],
    classification: dict[str, Any],
    copy_brief: dict[str, Any],
) -> str:
    guess = compact(profile.get("clinic_profile_guess"))
    primary = compact(profile.get("primary_service_summary"))
    if guess == "solo_gp":
        return "a solo GP-style clinic"
    if guess == "family_gp":
        text = lower_blob(row)
        company = compact(row.get("company_name")).lower()
        if "family clinic" not in company and ("outpatient" in text or "medical clinic" in text or "international clinic" in company):
            return "an outpatient medical clinic offering doctor-led consultations"
        return "a family clinic offering GP-style consultations"
    if guess == "multi_doctor_gp":
        return "a multi-doctor clinic offering outpatient consultations"
    if guess == "specialist_led":
        subtype = specialist_subtype(primary_profile_source_text(row))
        subtype_phrases = {
            "cardiology": "a specialist-led heart/cardiology clinic",
            "fertility": "a fertility / IVF specialist clinic",
            "pain": "a specialist-led pain management clinic",
            "surgery": "a specialist-led surgical clinic",
            "dermatology": "a specialist-led dermatology clinic",
            "eye": "a specialist-led eye clinic",
            "rheumatology": "a specialist-led rheumatology clinic",
            "endocrinology": "a specialist-led endocrinology clinic",
            "orthopaedic": "a specialist-led orthopaedic / sports medicine clinic",
            "neuroscience": "a specialist-led neuroscience provider",
        }
        if subtype in subtype_phrases:
            return subtype_phrases[subtype]
        if subtype == "oncology":
            return "an oncology/radiation provider"
        return f"a specialist-led clinic focused on {(primary or 'specialist care').replace(' / ', ' and ')}"
    if guess == "aesthetic_medical":
        return "a medical/aesthetic clinic with doctor-led consultations"
    if guess == "dental":
        return "a dental clinic"
    if guess == "pharmacy":
        return "a pharmacy / compounding provider"
    if guess == "diagnostic_lab":
        return "a diagnostic / laboratory provider"
    if guess == "hospital":
        return "a hospital"
    if guess == "healthcare_group":
        return "a healthcare holding or group organisation"
    if guess == "elder_daycare":
        return "a health and day-care provider"
    if guess == "hearing_care":
        return "a hearing-care provider offering hearing tests, hearing aids and audiology support"
    if guess == "allied_health":
        return "an allied-health provider offering physiotherapy or treatment support"
    if guess == "mental_health":
        return "a psychology / mental-health provider"
    if guess == "nursing_home":
        return "a nursing home"
    if guess == "community_hospital":
        return "a community hospital"
    if guess == "hospice_long_term_care":
        return "a hospice / long-term care provider"
    if guess == "home_care":
        return "a home-care / caregiver provider"
    if guess == "clinic_group":
        return "a multi-location clinic group"
    return "a healthcare provider"


def hia_email_1_records(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any] | None = None) -> str:
    text = primary_profile_source_text(row)
    profile_guess = compact((copy_brief or {}).get("clinic_profile_guess"))
    service_type = classification.get("hia_service_type_guess")
    if profile_guess in {"solo_gp", "family_gp", "multi_doctor_gp"}:
        return "patient records, appointment details, consultation notes, clinic email, vendor systems"
    if profile_guess == "aesthetic_medical" or (service_type == "GP_OMS" and "aesthetic" in text):
        return "consultation records, treatment notes, appointment details, clinic email, vendor systems"
    if profile_guess == "hospital" or service_type == "hospital":
        return "patient records, clinical service records, referrals, vendor systems"
    if profile_guess == "healthcare_group":
        return "institutional systems, vendor systems, staff access and governance workflows"
    if profile_guess == "elder_daycare":
        return "care notes, client details, family contact details, staff and vendor systems"
    if profile_guess == "specialist_led" or service_type == "specialist_OMS":
        subtype = specialist_subtype(text)
        if subtype == "cardiology":
            return "consultation notes, cardiac test reports, referrals, appointment details and vendor systems"
        if subtype == "fertility":
            return "fertility treatment records, appointment details, lab/report data, consent forms and vendor systems"
        if subtype == "pain":
            return "assessment notes, treatment plans, procedure-related records, appointment details and vendor systems"
        if subtype == "surgery":
            return "consultation notes, consent forms, procedure records, follow-up notes and vendor systems"
        if subtype == "dermatology":
            return "skin consultation notes, treatment records, appointment details, clinical images where used and vendor systems"
        if subtype == "eye":
            return "eye examination records, imaging, prescriptions, referrals and vendor systems"
        if subtype == "gastroenterology":
            return "consultation notes, patient reports, procedure-related records, vendor systems"
        if subtype == "rheumatology":
            return "consultation notes, treatment records, referrals, appointment details and vendor systems"
        if subtype == "oncology":
            return "oncology/radiation treatment records, patient reports, vendor systems"
        if subtype == "endocrinology":
            return "endocrinology consultation notes, diabetes/thyroid care records, referrals, appointment details and vendor systems"
        if subtype == "orthopaedic":
            return "orthopaedic consultation notes, imaging/referral records, treatment plans, appointment details and vendor systems"
        return "consultation notes, patient reports, treatment records, vendor systems"
    if profile_guess == "dental" or service_type == "dental":
        return "patient records, imaging files, appointment details, dental software"
    if profile_guess == "pharmacy" or service_type == "retail_pharmacy":
        return "prescription, dispensing, compounding, customer and supplier records"
    if profile_guess == "diagnostic_lab" or service_type == "diagnostic":
        return "screening records, diagnostic reports, patient details, lab systems, vendor systems"
    if profile_guess == "hearing_care" or service_type == "hearing_care":
        return "hearing test records, appointment details, device-related records, vendor systems"
    if profile_guess == "allied_health":
        return "appointment, treatment and exercise-plan records"
    if profile_guess == "mental_health":
        return "appointment, assessment and case-note records"
    if profile_guess in {"nursing_home", "community_hospital"}:
        return "resident, patient, family, staff and care records"
    if profile_guess == "hospice_long_term_care" or service_type == "long_term_care":
        if profile_guess == "home_care" or home_care_subtype(text):
            return "client, patient, caregiver, family and staff records"
        return "patient, resident, family, volunteer and staff data"
    if "family" in text or service_type == "GP_OMS":
        return "patient records, appointment details, consultation notes, clinic email, vendor systems"
    return "patient records, appointment details, consultation notes, clinic email, vendor systems"


def hia_records_with_backups(records: str) -> str:
    text = compact(records)
    if "backup" in text.lower():
        return text
    if text.endswith(" and vendor systems"):
        return text[: -len(" and vendor systems")] + ", vendor systems and backups"
    return f"{text} and backups"


def segment_asset(row: dict[str, Any], classification: dict[str, Any], clinic_profile: dict[str, Any] | None = None) -> str:
    text = lower_blob(row)
    service_type = classification.get("hia_service_type_guess")
    entity = classification.get("entity_type_guess")
    profile_guess = compact((clinic_profile or {}).get("clinic_profile_guess"))
    if profile_guess in {"solo_gp", "family_gp", "multi_doctor_gp", "aesthetic_medical"}:
        return "clinic readiness map"
    if profile_guess == "diagnostic_lab":
        return "diagnostic readiness map"
    if profile_guess == "hospital":
        return "hospital readiness map"
    if profile_guess in {"healthcare_group", "elder_daycare"}:
        return "healthcare readiness map"
    if profile_guess == "specialist_led":
        return "specialist clinic readiness map"
    if profile_guess == "dental":
        return "dental readiness map"
    if profile_guess == "pharmacy":
        return "pharmacy HIA checklist"
    if profile_guess == "hearing_care":
        return "hearing-care readiness map"
    if profile_guess == "allied_health":
        return "allied-health readiness map"
    if profile_guess == "mental_health":
        return "psychology readiness map"
    if profile_guess in {"hospice_long_term_care", "nursing_home", "community_hospital"}:
        return "long-term care readiness map"
    if profile_guess == "home_care":
        return "care readiness map"
    if classification.get("pressure_type") == "customer_trust":
        return "security evidence checklist"
    if classification.get("campaign_track") == "dpo_evidence":
        return "evidence checklist"
    if classification.get("pressure_type") == "pdpa_safeguards":
        return "safeguards checklist"
    if service_type == "dental":
        return "dental readiness map"
    if service_type == "retail_pharmacy":
        return "pharmacy HIA checklist"
    if service_type == "diagnostic":
        return "diagnostic readiness map"
    if service_type == "specialist_OMS":
        return "specialist clinic readiness map"
    if service_type == "hearing_care":
        return "hearing-care readiness map"
    if service_type == "allied_health" and ("psychology" in text or "psychologist" in text or "mental health" in text):
        return "psychology readiness map"
    if service_type == "allied_health":
        return "allied-health readiness map"
    if service_type == "long_term_care":
        return "long-term care readiness map"
    if service_type == "GP_OMS" or entity == "clinic":
        return "clinic readiness map"
    if entity in {"npo", "charity", "social_service"}:
        return "care-organisation checklist"
    return "HIA readiness map"


def hia_problem_statement(row: dict[str, Any], classification: dict[str, Any], clinic_profile: dict[str, Any] | None = None) -> str:
    return "With HIA coming in, the messy part is usually evidence: access, vendors, backups and incident steps."


def hia_email_2_diagnostic(
    row: dict[str, Any],
    classification: dict[str, Any],
    asset: str,
    copy_brief: dict[str, Any] | None = None,
    slots: dict[str, str] | str | None = None,
    prefix: str = "",
) -> str:
    company = compact(row.get("company_name") or "the organisation")
    records = hia_email_1_records(row, classification, copy_brief)
    if isinstance(slots, str):
        legacy = {
            "A": {
                "diagnostic_opener": "A practical diagnostic:",
                "question_shape": f"can {company} show where {records} sit today, who owns access, how backups work and who handles incidents?",
                "gap_line": "If that is fuzzy, that is usually the first readiness gap to close.",
                "cta": f"Want the {asset}?",
            },
            "B": {
                "diagnostic_opener": "One useful check:",
                "question_shape": f"can {company} map {records} to owners, access lists, backups and incident contacts?",
                "gap_line": "If access or backup ownership is unclear, that is usually where readiness work starts.",
                "cta": f"Should I send the {asset}?",
            },
            "C": {
                "diagnostic_opener": "Simple check:",
                "question_shape": f"can {company} show who owns access to {records}, where backups sit and who handles incidents?",
                "gap_line": "If that is unclear, that is usually where the cleanup starts.",
                "cta": f"Worth sending the {asset}?",
            },
        }
        slots = legacy.get(slots, legacy["A"])
    slots = slots or {}
    opener = slots.get("diagnostic_opener") or "Simple check:"
    question = slots.get("question_shape") or f"can {company} show where {records} sit today, who owns access, how backups work and who handles incidents?"
    gap_line = slots.get("gap_line") or "If that is fuzzy, that is usually the first readiness gap to close."
    cta = slots.get("cta") or f"Want the {asset}?"
    return f"{prefix}{opener} {question}\n\n{gap_line}\n\n{cta}"


def pdpa_variant_context(company: str, text: str, entity: str, data_type: str) -> dict[str, str]:
    if entity in {"clinic", "healthcare_provider"} or contains_any(
        text,
        ("optometry", "optometrist", "visioncare", "vision care", "eye care", "tcm", "healthcare", "health care"),
    ):
        return {
            "signal": f"{company} appears to handle appointment, enquiry, customer and staff records through its healthcare-facing operations.",
            "personal_data": "appointment, enquiry, customer and staff records handled through healthcare-facing operations.",
            "sensitive_examples": "appointment details, customer contact data, enquiry records, staff access records and vendor records.",
            "systems": "appointments/enquiries, email, CRM/POS or spreadsheets, file shares, vendor tools, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for those records, not writing another policy.",
            "asset": "healthcare data safeguards checklist",
        }
    if any(term in text for term in ("student", "parent", "enrolment", "enrollment", "education", "training", "tuition", "course")):
        return {
            "signal": f"{company} appears to provide education/training services handling student, parent, staff or enrolment records.",
            "personal_data": "student, parent, staff and enrolment records handled through education/training operations.",
            "sensitive_examples": "student records, parent contacts, staff data, enrolment details and attendance or course records.",
            "systems": "student/enrolment systems, email, spreadsheets, learning tools, vendor tools, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for student, parent, staff and enrolment records.",
            "asset": "education data checklist",
        }
    if any(term in text for term in ("recruitment", "candidate", "payroll", "hr ", "human resource")) and not any(
        term in text for term in ("accounting", "bookkeeping", "finance", "financial", "admin services", "administrative services", "tax")
    ):
        return {
            "signal": f"{company} appears to provide HR/recruitment services handling candidate, employee and client records.",
            "personal_data": "candidate, employee and client records handled through HR/recruitment workflows.",
            "sensitive_examples": "candidate profiles, employee records, payroll-related records, client contacts and access logs.",
            "systems": "ATS/HR systems, email, file shares, payroll or admin tools, vendor tools, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for candidate, employee, payroll or client records.",
            "asset": "HR data safeguards checklist",
        }
    if entity in {"npo", "charity", "social_service"} or contains_any(text, STRONG_NPO_TERMS + STRONG_SOCIAL_SERVICE_TERMS):
        return {
            "signal": f"{company} appears to operate in a care/community-service setting handling beneficiary, volunteer, donor and staff data.",
            "personal_data": "beneficiary, volunteer, donor and staff data handled through care and community operations.",
            "sensitive_examples": "beneficiary records, volunteer data, donor contacts, staff records and care-service notes.",
            "systems": "case records, volunteer lists, donor/contact databases, email, file shares, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for beneficiary, volunteer, donor and staff data.",
            "asset": "care-organisation checklist",
        }
    if any(term in text for term in ("accounting", "bookkeeping", "finance", "financial", "admin services", "administrative services", "tax", "payroll")):
        return {
            "signal": f"{company} appears to provide admin/accounting/finance services handling client financial or business records.",
            "personal_data": "client financial, business-contact, employee and admin records handled through service operations.",
            "sensitive_examples": "client financial records, business records, payroll or tax records, contact data and access records.",
            "systems": "accounting/admin systems, email, file shares, client portals, vendor tools, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for client financial or business records.",
            "asset": "client data safeguards checklist",
        }
    if any(term in text for term in ("retail", "e-commerce", "ecommerce", "online store", "customer service", "orders", "payment", "support")):
        return {
            "signal": f"{company} appears to run customer-facing operations handling customer, order, support and payment-related records.",
            "personal_data": "customer, order, support and payment-related records handled through customer-facing operations.",
            "sensitive_examples": "customer contact data, order history, support records, payment-related records and staff access logs.",
            "systems": "e-commerce, POS, CRM/support, email, payment-related tools, vendor tools, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for customer, order, support and payment-related records.",
            "asset": "customer data checklist",
        }
    if any(term in text for term in (" lab ", "laboratory", "testing", "test services")) and not has_clinical_lab_evidence(text):
        return {
            "signal": f"{company} appears to provide lab/testing services where customer, employee and project records may sit across operations and vendor tools.",
            "personal_data": "customer, employee and project records handled through lab/testing operations and vendor tools.",
            "sensitive_examples": "customer records, employee data, project records, test administration records and access logs.",
            "systems": "testing/project systems, email, file shares, vendor tools, backups and incident contacts.",
            "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards for customer, employee and project records.",
            "asset": "safeguards checklist",
        }
    return {
        "signal": f"{company} appears to handle customer and employee records through its operations.",
        "personal_data": f"{data_type} handled through enquiries, service delivery, staff operations and vendor tools.",
        "sensitive_examples": f"{data_type}, employee data, contact records and service history.",
        "systems": "web forms, email, CRM or spreadsheets, file shares, vendor tools, backups and incident contacts.",
        "problem": "PDPA is the legal responsibility. The hard part is usually proving safeguards, not writing another policy.",
        "asset": "safeguards checklist",
    }


def customer_trust_variant_context(company: str, text: str) -> dict[str, str]:
    if contains_any(text, ("cord blood", "healthcare", "health care", "clinic", "diagnostic", "laboratory")):
        return {
            "signal": f"{company} works in a healthcare-adjacent setting where customers may ask how sensitive records and access are protected.",
            "asset": "healthcare security evidence checklist",
            "systems": "customer records, consent or service records, staff access, backups, patching, malware protection and incident response evidence.",
            "diagnostic": "Can customer security questions be mapped to evidence for sensitive-record access, backups, patching, malware protection and incident response?",
        }
    if any(term in text for term in ("saas", "software", "platform", "dashboard", "user data", "admin access")):
        return {
            "signal": f"{company} works with customers who may ask how user data, admin access and backups are controlled.",
            "asset": "customer security evidence checklist",
            "systems": "user access, admin roles, backups, patching, malware protection and incident response evidence.",
            "diagnostic": "Can common customer security questions be mapped to evidence for user access, admin roles, backups, patching, malware protection and incident response?",
        }
    if any(term in text for term in ("recruitment", "candidate", "hr ", "human resource")):
        return {
            "signal": f"{company} works with clients who may ask how candidate and employee data is protected.",
            "asset": "client security evidence checklist",
            "systems": "candidate records, employee data, client access, backups, patching, malware protection and incident response evidence.",
            "diagnostic": "Can client security questions be mapped to evidence for candidate and employee data access, backups, patching, malware protection and incident response?",
        }
    if any(term in text for term in ("outsourcing", "vendor", "supplier", "managed service")):
        return {
            "signal": f"{company} works as a vendor where customers may ask for supplier security evidence.",
            "asset": "vendor security evidence checklist",
            "systems": "supplier access, customer data handling, backups, patching, malware protection and incident response evidence.",
            "diagnostic": "Can supplier security questions be mapped to evidence for access control, backups, patching, malware protection and incident response?",
        }
    if any(term in text for term in ("education", "training", "learner", "corporate learning")):
        return {
            "signal": f"{company} works with corporate customers who may ask how learner and staff data is handled.",
            "asset": "learner-data evidence checklist",
            "systems": "learner data, staff records, customer access, backups, patching, malware protection and incident response evidence.",
            "diagnostic": "Can customer security questions be mapped to evidence for learner data, staff data, access, backups, patching, malware protection and incident response?",
        }
    return {
        "signal": f"{company} works with business customers who may ask for reusable security evidence before sharing data.",
        "asset": "security evidence checklist",
        "systems": "access control, backups, patching, malware protection and incident response evidence.",
        "diagnostic": "Can each common customer security question be mapped to current evidence for access, backups, patching, malware protection and incident response?",
    }


def subject_pair(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> tuple[str, str]:
    pressure = classification.get("pressure_type")
    asset = compact(copy_brief.get("email_asset_offer")).lower()
    text = lower_blob(row)
    if pressure == "hia_regulatory":
        profile_guess = compact(copy_brief.get("clinic_profile_guess"))
        service = classification.get("hia_service_type_guess")
        if profile_guess == "dental" or service == "dental":
            subject = "dental readiness"
        elif profile_guess == "pharmacy" or service == "retail_pharmacy":
            subject = "pharmacy HIA checklist"
        elif profile_guess == "hearing_care" or service == "hearing_care":
            subject = "hearing-care readiness"
        elif profile_guess in {"hospice_long_term_care", "home_care"} or service == "long_term_care":
            subject = "care readiness"
        elif profile_guess == "specialist_led" or service == "specialist_OMS":
            subject = "specialist clinic readiness"
        else:
            subject = "clinic readiness"
        return subject, f"Re: {subject}"
    if classification.get("campaign_track") == "dpo_evidence":
        return "data protection evidence", "Re: data protection evidence"
    if pressure == "customer_trust":
        if "customer" in asset:
            subject = "customer security evidence"
        elif "vendor" in asset or "supplier" in text or "outsourcing" in text:
            subject = "vendor security evidence"
        else:
            subject = "security evidence"
        return subject, f"Re: {subject}"
    if pressure == "pdpa_safeguards":
        if "hr" in asset:
            subject = "HR data safeguards"
        elif "education" in asset:
            subject = "education data safeguards"
        elif "client" in asset:
            subject = "client data safeguards"
        elif "customer" in asset:
            subject = "customer data safeguards"
        else:
            subject = "data safeguards"
        return subject, f"Re: {subject}"
    return "not ready", "not ready"


def build_copy_brief(row: dict[str, Any], classification: dict[str, Any], funding: FundingMatch) -> dict[str, Any]:
    company = compact(row.get("company_name") or "the organisation")
    text = lower_blob(row)
    services = listish_items(row.get("services_detected")) or listish_items(row.get("primary_services_summary"))
    locations = listish_items(row.get("locations_detected"))
    team = listish_items(row.get("leadership_or_team_signals")) or listish_items(row.get("contact_info_detected"))
    public_signals = public_signal_summary(row, text, services, locations, team)
    source_url = first_source_url(row)
    pressure = classification.get("pressure_type", "not_ready")
    entity = classification.get("entity_type_guess", "unknown")
    data_type = str(classification.get("data_type_signal") or "unknown").replace("_", " ")
    healthcare_profile_signal = (
        entity in {"clinic", "healthcare_provider"}
        or contains_any(
            text,
            (
                "holding company",
                "healthcare institutions",
                "public healthcare institutions",
                "daycare",
                "day care",
                "elderly",
                "elder care",
                "psychotherapy",
                "counselling",
                "counseling",
                "mental health",
            ),
        )
    )
    clinic_profile = infer_clinic_profile(row, classification, text) if pressure == "hia_regulatory" or healthcare_profile_signal else {}
    email_2_diagnostic = ""

    if entity == "clinic":
        business_model = "clinic"
    elif entity == "healthcare_provider":
        business_model = "healthcare_provider"
    elif entity in {"npo", "charity", "social_service"}:
        business_model = "social_service"
    elif pressure == "customer_trust":
        business_model = "b2b_services"
    elif any(term in text for term in ("saas", "software", "platform")):
        business_model = "saas"
    elif any(term in text for term in ("consulting", "professional", "outsourcing", "recruitment")):
        business_model = "professional_services"
    else:
        business_model = "unknown"

    primary_services = sentence_join(services, public_signals["service"]) or "the public services described on its website"
    location_summary = sentence_join(locations, "Singapore-facing operations")
    team_summary = sentence_join(team, "Public site does not give a clear team structure.")
    if clinic_profile:
        profile = f"{company} appears to be {clinic_profile['clinic_profile_phrase']} in {location_summary}."
    else:
        profile = f"{company} appears to be a {business_model.replace('_', ' ')} organisation with public signals around {primary_services} in {location_summary}."

    if pressure == "hia_regulatory":
        service_type = classification.get("hia_service_type_guess")
        personal_data = "patient and health information handled through enquiries, appointments, care records and clinic operations."
        sensitive_examples = "patient identity details, appointment information, health information, treatment notes and staff access records."
        if service_type == "hearing_care" or "hearing" in text:
            systems = "appointments, hearing tests, device-related records, staff access, vendor systems, backups and incident-reporting steps."
        elif home_care_subtype(text):
            personal_data = "client, patient, caregiver, family and staff records handled through home-care operations."
            sensitive_examples = "client and patient details, caregiver records, family contacts, staff access records and incident evidence."
            systems = "client, patient, caregiver, family and staff records, vendor systems, backups and incident-reporting steps."
        elif service_type == "long_term_care" or contains_any(text, LONG_TERM_CARE_TERMS):
            personal_data = "patient, resident, family, volunteer and staff data handled through care operations and support workflows."
            sensitive_examples = "patient and resident details, care notes, family contacts, volunteer data, staff access records and incident evidence."
            systems = "patient/resident care records, family contacts, volunteer lists, staff access, vendor systems, backups and incident-reporting steps."
        elif service_type == "allied_health" and ("physio" in text or "physiotherapy" in text):
            systems = "appointments, treatment notes, exercise-plan records, staff access, vendor systems, backups and incident-reporting steps."
        elif service_type == "allied_health" and ("psychology" in text or "psychologist" in text or "mental health" in text):
            systems = "appointments, assessment notes, case-note records, staff access, vendor systems, backups and incident-reporting steps."
        elif service_type == "diagnostic":
            systems = "screening appointments, diagnostic reports, patient records, vendor systems, backups and incident-reporting steps."
        elif service_type == "specialist_OMS":
            subtype_systems = {
                "cardiology": "consultation notes, cardiac test reports, referrals, appointment details, vendor systems, backups and incident-reporting steps.",
                "fertility": "fertility treatment records, appointment details, lab/report data, consent forms, vendor systems, backups and incident-reporting steps.",
                "pain": "assessment notes, treatment plans, procedure-related records, appointment details, vendor systems, backups and incident-reporting steps.",
                "surgery": "consultation notes, consent forms, procedure records, follow-up notes, vendor systems, backups and incident-reporting steps.",
                "dermatology": "skin consultation notes, treatment records, appointment details, clinical images where used, vendor systems, backups and incident-reporting steps.",
                "eye": "eye examination records, imaging, prescriptions, referrals, vendor systems, backups and incident-reporting steps.",
                "gastroenterology": "specialist appointments, digestive/gastroenterology records, patient reports, vendor systems, backups and incident-reporting steps.",
                "rheumatology": "specialist consultation notes, arthritis/rheumatology records, referrals, appointment details, vendor systems, backups and incident-reporting steps.",
                "oncology": "specialist appointments, oncology/radiation treatment records, patient reports, vendor systems, backups and incident-reporting steps.",
                "endocrinology": "endocrinology consultation notes, diabetes/thyroid care records, referrals, appointment details, vendor systems, backups and incident-reporting steps.",
                "orthopaedic": "orthopaedic consultation notes, imaging/referral records, treatment plans, appointment details, vendor systems, backups and incident-reporting steps.",
            }
            systems = subtype_systems.get(specialist_subtype(text), "appointment forms, patient records, clinic email, vendor systems, backups and incident-reporting steps.")
        else:
            systems = "appointment forms, patient records, clinic email, vendor systems, backups and incident-reporting steps."
        complexity = "medium" if entity == "clinic" else "high"
        regulatory = "HIA creates an external healthcare regulatory-readiness pressure, with phased timelines starting from 2027."
        hia_angle = "Map health information access, cybersecurity, data-security, vendor, backup and incident-response duties before the HIA window."
        pdpa_angle = "PDPA safeguards still matter, but the primary outreach angle is HIA readiness for health information."
        trust_angle = "Patients and partners expect clear evidence that clinic systems and health information access are controlled."
        timeline = "HIA implementation is being phased in; do not use batch labels in prospect-facing email bodies."
        asset = segment_asset(row, classification, clinic_profile)
        cta = hia_email_1_cta(row, classification, asset)
        problem = hia_problem_statement(row, classification, clinic_profile)
        mechanism = "Cyber Essentials is a decent first baseline for that cyber/data side."
        profile_phrase = clinic_profile.get("clinic_profile_phrase") or prospect_facing_profile_phrase(clinic_profile, row, classification, {})
        if clinic_profile.get("clinic_profile_guess") == "specialist_led" and "gastroenterology and digestive care" in profile_phrase:
            signal = f"{company} appears to provide specialist-led gastroenterology and digestive care."
        else:
            signal = f"{company} appears to be {profile_phrase}."
    elif pressure == "customer_trust":
        trust_context = customer_trust_variant_context(company, text)
        personal_data = "customer, partner, employee and business-contact data handled through service delivery and client operations."
        sensitive_examples = "customer contact data, business partner data, employee access records and client security-questionnaire evidence."
        systems = trust_context["systems"]
        complexity = "medium"
        regulatory = "PDPA creates the personal-data protection responsibility, but customer/procurement proof is the stronger buying pressure."
        hia_angle = "No HIA angle should be used unless healthcare evidence appears."
        pdpa_angle = "Cyber Essentials supports the security-safeguards side of PDPA readiness without claiming PDPA compliance."
        trust_angle = "Customers may ask for reusable security evidence around access control, patching, backups, malware protection and incident response."
        timeline = "No external HIA deadline was identified; urgency comes from customer evidence and procurement reviews."
        asset = trust_context["asset"]
        cta = f"Worth sending the {asset}?"
        problem = "The annoying part is usually rebuilding the same proof for each customer review: access, backups, patching, malware protection and incident response."
        mechanism = "Cyber Essentials gives a simple reusable evidence baseline."
        signal = trust_context["signal"]
        email_2_diagnostic = trust_context["diagnostic"]
    elif pressure == "pdpa_safeguards":
        email_2_diagnostic = ""
        if classification.get("campaign_track") == "dpo_evidence":
            personal_data = f"{data_type} handled across IT, HR, vendors and operations."
            sensitive_examples = f"{data_type}, employee data, access records, vendor records and incident evidence."
            systems = "HR/admin systems, email, file shares, vendor tools, access lists, backups and incident contacts."
            asset = "evidence checklist"
            cta = "Worth sending the evidence checklist?"
            signal = f"{company} has a data-protection / operations contact route."
            problem = "The tricky part is usually not the policy. It is finding the proof across HR, IT, vendors and day-to-day operations."
        elif entity in {"npo", "charity", "social_service"}:
            personal_data = "beneficiary, volunteer, donor and staff data handled through care and community operations."
            sensitive_examples = "beneficiary records, volunteer data, donor contacts, staff records and care-service notes."
            systems = "case or resident records, volunteer lists, donor/contact databases, email, file shares, backups and incident contacts."
            asset = "care-organisation checklist"
            cta = "Worth sending the care-organisation checklist?"
            signal = f"{company} appears to operate in a care/community-service setting handling beneficiary, volunteer, donor and staff data."
            problem = "PDPA is the legal responsibility. The hard part is usually proving safeguards for beneficiary, volunteer, donor and staff data."
        else:
            pdpa_context = pdpa_variant_context(company, text, entity, data_type)
            personal_data = pdpa_context["personal_data"]
            sensitive_examples = pdpa_context["sensitive_examples"]
            systems = pdpa_context["systems"]
            asset = pdpa_context["asset"]
            cta = f"Worth sending the {asset}?"
            signal = pdpa_context["signal"]
            problem = pdpa_context["problem"]
        complexity = "medium" if classification.get("personal_data_intensity") in {"medium", "high"} else "unknown"
        regulatory = "PDPA is the legal obligation to protect personal data with reasonable security arrangements."
        hia_angle = "Do not lead with HIA unless healthcare evidence is medium or high confidence."
        pdpa_angle = "Cyber Essentials supports the security-safeguards side of PDPA readiness by turning reasonable protection into practical controls and evidence across assets, access, malware protection, patching, backups and incident response."
        trust_angle = "Clear safeguard evidence also helps customers, partners, donors, insurers and internal teams trust how data is handled."
        timeline = "No specific external deadline was identified; urgency comes from being able to evidence reasonable safeguards before a customer, partner or incident review asks for proof."
        if classification.get("campaign_track") == "dpo_evidence":
            mechanism = "Cyber Essentials helps turn that into a simple security baseline and evidence set."
        else:
            mechanism = "Cyber Essentials gives a simple baseline for access, backups, updates, malware controls and incident response."
    else:
        profile = ""
        business_model = "unknown"
        primary_services = ""
        location_summary = ""
        team_summary = ""
        personal_data = ""
        sensitive_examples = ""
        systems = ""
        complexity = "unknown"
        regulatory = ""
        hia_angle = ""
        pdpa_angle = ""
        trust_angle = ""
        timeline = ""
        asset = ""
        cta = ""
        problem = ""
        mechanism = ""
        signal = ""

    funding_safe = (
        funding.funding_status == "verified_match"
        and funding.funding_confidence == "high"
        and compact(funding.funding_claim_line)
        and classification.get("entity_type_confidence") in {"medium", "high"}
        and (not funding.matched or any(item.get("verification_status") == "verified_current" for item in funding.matched))
    )
    pricing = infer_hia_clinic_size(row, classification, clinic_profile)
    funding_level = "high" if funding_safe else "medium" if funding.funding_status == "possible_match" else "low"
    plain_company_type = profile_phrase if pressure == "hia_regulatory" else business_model.replace("_", " ")
    pain_line = problem
    why_now_line = ""
    cost_line = ""
    proof_line = mechanism
    cta_line = cta
    if pressure == "hia_regulatory":
        why_now_line = "HIA makes that worth sorting out earlier."
        price_text = CISOAAS_HIA_PRICING["price_text"]
        cost_line = f"Smaller clinics start around {price_text} before funding, but endpoint count decides the final number."
        proof_line = "We handle the messy evidence work. LEARN and GOVERN software helps keep training and governance tidy after certification."
    elif pressure == "pdpa_safeguards" and classification.get("campaign_track") == "dpo_evidence":
        why_now_line = "Data-protection evidence usually sits across more than one team."
        proof_line = "Cyber Essentials helps turn that into a simple security baseline and evidence set."
    elif pressure == "pdpa_safeguards":
        why_now_line = "PDPA makes those safeguards worth having in evidence, not just in intention."
        proof_line = "Cyber Essentials gives a simple baseline for access, backups, updates, malware controls and incident response."
    elif pressure == "customer_trust":
        why_now_line = "Customer reviews are easier when the proof is already organised."
        proof_line = "Cyber Essentials gives a simple reusable evidence baseline."
    copy_brief = {
        "company_profile_summary": profile,
        "business_model_guess": business_model,
        "primary_services_summary": primary_services,
        "locations_summary": location_summary,
        "team_structure_summary": team_summary,
        "personal_data_handled_guess": personal_data,
        "sensitive_data_examples": sensitive_examples,
        "data_systems_likely": systems,
        "data_flow_complexity": complexity,
        "data_risk_reason": problem,
        "regulatory_pressure_summary": regulatory,
        "hia_obligation_angle": hia_angle,
        "pdpa_obligation_angle": pdpa_angle,
        "customer_trust_angle": trust_angle,
        "deadline_or_timeline_angle": timeline,
        "funding_entity_basis": funding.funding_eligibility_basis,
        "funding_route_summary": funding.funding_claim_line or "Funding route needs human review before use.",
        "funding_specificity_level": funding_level if pressure != "not_ready" else "unknown",
        "funding_claim_safe": funding_safe,
        "funding_next_check_needed": "" if funding_safe else "Verify programme status, entity type, scope and timing before using funding as a send-ready claim.",
        "clinic_size_guess": pricing["clinic_size_guess"],
        "clinic_size_confidence": pricing["clinic_size_confidence"],
        "endpoint_band_guess": pricing["endpoint_band_guess"],
        "endpoint_band_confidence": pricing["endpoint_band_confidence"],
        "pricing_email_2_mode": pricing["pricing_email_2_mode"],
        "pricing_claim_safe": pricing["pricing_claim_safe"],
        "pricing_claim_line": pricing["pricing_claim_line"],
        "pricing_evidence_json": pricing["pricing_evidence_json"],
        "plain_company_type": plain_company_type,
        "pain_line": pain_line,
        "why_now_line": why_now_line,
        "cost_line": cost_line,
        "proof_line": proof_line,
        "cta_line": cta_line,
        "human_email_style": "short_plain_low_cta",
        "email_2_mode": "funding" if funding_safe else "value_fallback",
        "funding_followup_mode": "funding" if funding_safe else "value_fallback",
        "email_3_mode": "funding" if funding_safe else "value_fallback",
        "email_personalisation_signal": signal,
        "email_personalisation_quote": compact(row.get("company_homepage_name") or row.get("website_content"))[:220],
        "email_personalisation_source_url": source_url,
        "email_hook": problem,
        "email_hook_source": "website_content",
        "email_problem_statement": problem,
        "email_mechanism_statement": mechanism,
        "email_asset_offer": asset,
        "email_cta": cta,
        "email_2_diagnostic": email_2_diagnostic,
        "email_angle_reason": classification.get("pressure_reason") or classification.get("problem_hypothesis") or "",
    }
    copy_brief.update(
        {
            "clinic_profile_guess": clinic_profile.get("clinic_profile_guess", ""),
            "clinic_profile_phrase": clinic_profile.get("clinic_profile_phrase", ""),
            "clinic_structure_guess": clinic_profile.get("clinic_structure_guess", ""),
            "clinic_structure_confidence": clinic_profile.get("clinic_structure_confidence", ""),
            "umbrella_or_group_guess": clinic_profile.get("umbrella_or_group_guess", ""),
            "solo_gp_likelihood": clinic_profile.get("solo_gp_likelihood", ""),
            "specialist_led_likelihood": clinic_profile.get("specialist_led_likelihood", ""),
            "multi_practitioner_likelihood": clinic_profile.get("multi_practitioner_likelihood", ""),
            "primary_service_summary": clinic_profile.get("primary_service_summary", ""),
            "clinic_structure_evidence": clinic_profile.get("clinic_structure_evidence", []),
        }
    )
    copy_brief["prospect_facing_signal"] = prospect_facing_signal(signal, row, classification, copy_brief)
    return copy_brief


def generate_email_sequence(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    copy_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    copy_brief = copy_brief or build_copy_brief(row, classification, funding)
    company = email_display_company_name(row)
    greeting = email_greeting(row, company)
    email1_greeting = email_1_greeting(row, company)
    comma_greeting = email_comma_greeting(row, company)
    followup_prefix = followup_name_prefix(row, "-")
    close_loop_prefix = followup_name_prefix(row, ",")
    if not copy_brief_ready(classification, copy_brief):
        return empty_email_sequence()
    trigger = compact(copy_brief.get("prospect_facing_signal")) or prospect_facing_signal(
        copy_brief["email_personalisation_signal"], row, classification, copy_brief
    )
    raw_company = compact(row.get("company_name"))
    if raw_company and company != raw_company:
        trigger = re.sub(re.escape(raw_company), company, trigger)
    asset = compact(copy_brief["email_asset_offer"]) or "checklist"
    cta = compact(copy_brief["email_cta"])
    problem = compact(copy_brief["email_problem_statement"])
    mechanism = compact(copy_brief["email_mechanism_statement"])
    systems = compact(copy_brief.get("data_systems_likely"))

    if classification["pressure_type"] == "not_ready":
        email1_subject = "not ready"
        email2_subject = "not ready"
        email1_body = ""
        email2_body = ""
        email3_body = ""
        email4_body = ""
    elif classification["pressure_type"] == "hia_regulatory":
        lead = "With HIA readiness becoming more urgent for healthcare providers"
        segment = healthcare_segment(classification)
        email1_subject = "HIA readiness"
        email2_subject = "Re: HIA readiness"
        email1_body = f"{greeting} noticed {company} appears to be a {segment}.\n\n{lead}, healthcare providers may need to show stronger readiness around health information access, cybersecurity, data security and incident response.\n\nCyber Essentials is a practical first baseline before deeper HIA work.\n\nWorth sending a simple HIA readiness checklist?"
        email2_body = f"One useful check: can {company} clearly show where health information sits, who can access it, which vendors touch it, how backups work, and who reports an incident?\n\nThose are the areas that usually become messy before HIA deadlines.\n\nWant the quick readiness map?"
    elif classification["pressure_type"] == "customer_trust":
        signal = business_model_trust_signal(lower_blob(row))
        email1_subject = "security evidence"
        email2_subject = "Re: security evidence"
        email1_body = f"{greeting} noticed {company} works with {signal}.\n\nThe practical issue is usually proving access control, backups, patching, malware protection and incident response without rebuilding answers for every customer review.\n\nCyber Essentials gives a recognised baseline for that evidence.\n\nWorth sending the evidence checklist?"
        email2_body = f"A practical diagnostic: can each common customer security question be mapped to current evidence for access, backups, patching, malware protection and incident response?\n\nIf not, that is usually where reusable evidence work starts.\n\nWant the simple evidence checklist?"
    elif classification.get("campaign_track") == "dpo_evidence":
        data = classification["data_type_signal"].replace("_", " ")
        email1_subject = "data protection evidence"
        email2_subject = "Re: data protection evidence"
        email1_body = f"{greeting} noticed {company} appears to handle {data}.\n\nFor DPOs and ops teams, the hard part is often not the policy. It is proving the safeguards: who has access, where data sits, how vendors are managed, and what happens during an incident.\n\nCyber Essentials helps structure the security baseline.\n\nWorth sending the evidence checklist?"
        email2_body = f"A quick self-check: can each system holding personal data be mapped to an owner, access list, vendor, backup process and incident contact?\n\nIf not, that is usually where the evidence work starts.\n\nWant the simple data-safeguards template?"
    else:
        data = classification["data_type_signal"].replace("_", " ")
        email1_subject = "PDPA security safeguards"
        email2_subject = "Re: PDPA security safeguards"
        email1_body = f"{greeting} noticed {company} appears to handle {data}.\n\nFor organisations handling personal data, the practical PDPA question is whether safeguards can be shown clearly: who has access, where data sits, how backups work, how updates are managed and who responds to incidents.\n\nCyber Essentials helps turn that into a practical security baseline and evidence set.\n\nWorth sending a short safeguards checklist?"
        email2_body = f"A quick self-check: can every system holding customer, employee or partner data be mapped to an owner, access list, backup, update process and incident contact?\n\nIf not, that is usually where Cyber Essentials prep starts.\n\nWant the simple data-safeguards template?"

    if classification["pressure_type"] != "not_ready":
        sentence_slots: dict[str, dict[str, str]] = {}
        base_email1_subject, base_thread_subject = subject_pair(row, classification, copy_brief)
        _, email1_subject, email1_subject_options = chosen_subject_variant(row, classification, copy_brief, 1, base_email1_subject)
        _, diagnostic_subject, email3_subject_options = chosen_subject_variant(row, classification, copy_brief, 3, base_thread_subject)
        noticed = trigger
        if noticed.lower().startswith("noticed "):
            noticed = noticed[8:].strip()
        email1_slots = email_1_sentence_slots(row, classification, sentence_slots)
        problem = email1_slots["problem_line"]
        mechanism = email1_slots["mechanism_line"]
        email1_chain = build_email_1_chain(row, classification, copy_brief, noticed, problem, mechanism, cta)
        noticed = email1_chain["observation"]
        problem = email1_chain["pressure_bridge"]
        mechanism = email1_chain["mechanism"]
        cta = email1_chain["cta"]
        copy_brief["email_1_chain"] = email1_chain
        copy_brief["first_sentence_context"] = email1_chain["first_sentence_context"]
        copy_brief["email_hook_context"] = email1_chain["email_hook_context"]
        copy_brief["email_hook"] = problem
        copy_brief["email_problem_statement"] = problem
        copy_brief["email_mechanism_statement"] = mechanism
        hook_override, hook_style = email_1_first_sentence_override(row, classification, copy_brief, company)
        email1_slots["first_sentence_override"] = hook_override
        copy_brief["email_1_hook_style"] = hook_style
        email1_body = email_1_body_fixed(email1_greeting, company, noticed, email1_slots, problem, mechanism, cta)
        if classification["pressure_type"] == "hia_regulatory" and word_count(email1_body) > 85 and len(company) > 45:
            short_noticed = noticed.replace(company, "your clinic", 1)
            email1_body = email_1_body_fixed(email1_greeting, "your clinic", short_noticed, email1_slots, problem, mechanism, cta)
        if classification["pressure_type"] == "hia_regulatory":
            records = hia_email_1_records(row, classification, copy_brief)
            email3_slots = email_3_sentence_slots(row, classification, sentence_slots, company, records, asset)
            email3_body = hia_email_2_diagnostic(row, classification, asset, copy_brief, email3_slots, followup_prefix)
        elif classification.get("entity_type_guess") in {"npo", "charity", "social_service"}:
            diagnostic = f"Can {company} map resident, beneficiary, volunteer and staff data to an owner, access list, backup and incident contact?"
        elif classification["pressure_type"] == "customer_trust":
            diagnostic = compact(copy_brief.get("email_2_diagnostic")) or "Can each common customer security question be mapped to current evidence for access, backups, patching, malware protection and incident response?"
        else:
            diagnostic = "Can each system holding personal data be mapped to an owner, access list, backup, update process and incident contact?"
        if classification["pressure_type"] != "hia_regulatory":
            email3_slots = email_3_sentence_slots(row, classification, sentence_slots, company, "", asset)
            email3_body = diagnostic_email_3_body_fixed(diagnostic, email3_slots, followup_prefix)
        if classification["pressure_type"] == "hia_regulatory" and compact(copy_brief.get("pricing_email_2_mode")) != "no_price_claim":
            hia_pricing_subjects = {"A": "HIA funding route", "B": "support route", "C": "cost check"}
            email2_subject_key = deterministic_option_key_for(row, classification, 2, list(hia_pricing_subjects.keys()))
            email2_subject = hia_pricing_subjects[email2_subject_key]
            email2_subject_options = list(hia_pricing_subjects.values())
            email2_slots = hia_email_2_sentence_slots(
                row,
                classification,
                sentence_slots,
                funding_claim_send_safe(funding, copy_brief, classification),
            )
            email2_body = hia_pricing_email_2_body(
                followup_prefix,
                compact(copy_brief.get("pricing_email_2_mode")) or "endpoint_sizing_needed",
                funding_claim_send_safe(funding, copy_brief, classification),
                email2_slots,
            )
        elif funding_claim_send_safe(funding, copy_brief, classification):
            subject_key, email2_subject, email2_subject_options = chosen_subject_variant(row, classification, copy_brief, 2, "Cyber Essentials funding")
            funding_line = funding.funding_claim_line
            if classification["pressure_type"] == "hia_regulatory" and subject_key == "A":
                email2_subject = "HIA / cyber funding"
                email2_subject_options = list(dict.fromkeys([email2_subject, *email2_subject_options]))
            caveat = "" if "subject to programme confirmation" in funding_line.lower() else "\n\nThis is subject to programme confirmation."
            email2_body = funding_email_2_body_fixed(followup_prefix, funding_line, caveat)
        else:
            fallback_subjects = {"A": "support route", "B": "funding fit", "C": "cost check"}
            subject_key = deterministic_option_key_for(row, classification, 2, list(fallback_subjects.keys()))
            email2_subject = fallback_subjects[subject_key]
            email2_subject_options = list(fallback_subjects.values())
            email2_slots = non_hia_email_2_sentence_slots(row, classification, sentence_slots, asset)
            email2_body = value_fallback_body_fixed(followup_prefix, asset, email2_slots)
            fallback_email2 = {"chosen_subject": email2_subject, "subject_options": email2_subject_options, "body": email2_body}
            email2_subject = fallback_email2["chosen_subject"]
            email2_subject_options = fallback_email2["subject_options"]
        email3_subject = diagnostic_subject
        _, email4_subject, email4_subject_options = chosen_subject_variant(row, classification, copy_brief, 4, "close the loop?")
        email4_slots = email_4_sentence_slots(row, classification, sentence_slots, asset)
        email4_body = close_loop_body_fixed(close_loop_prefix, email4_slots["close_loop"])
    else:
        sentence_slots = {}
        email1_subject_options = [email1_subject, "readiness checklist"]
        email2_subject_options = [email2_subject, "quick diagnostic"]
        email4_subject = "close the loop?"
        email4_subject_options = ["close the loop?", "checklist?"]
        email3_subject = "not ready"
        email3_subject_options = [email3_subject, "funding route"]

    emails = {
        "email_1": {
            "subject_options": email1_subject_options,
            "chosen_subject": email1_subject,
            "body": email1_body,
        },
        "email_2": {
            "subject_options": email2_subject_options,
            "chosen_subject": email2_subject,
            "body": email2_body,
        },
        "email_3": {
            "subject_options": email3_subject_options,
            "chosen_subject": email3_subject,
            "body": email3_body,
        },
        "email_4": {
            "subject_options": email4_subject_options,
            "chosen_subject": email4_subject,
            "body": email4_body,
        },
        "context_email_1": copy_brief.get("email_1_chain", {}),
        "company_context_search": copy_brief.get("company_context_search", {}),
        "evidence_used": [compact(copy_brief.get("first_sentence_context", {}).get("observation") if isinstance(copy_brief.get("first_sentence_context"), dict) else trigger)],
        "claims_avoided": [
            "No guaranteed funding.",
            "No claim that Cyber Essentials equals PDPA compliance.",
            "No claim that Cyber Essentials equals HIA compliance.",
        ],
        "quality_notes": [],
    }
    for key in ALL_EMAIL_KEYS:
        emails[key]["word_count"] = word_count(emails[key]["body"])
    emails["sentence_slot_metadata"] = email_sequence_sentence_slot_metadata(row, classification, copy_brief, sentence_slots)
    emails["style_metadata"] = {
        "human_email_style": compact(copy_brief.get("human_email_style")) or "short_plain_low_cta",
        "plain_company_type": compact(copy_brief.get("plain_company_type")),
        "pain_line": compact(copy_brief.get("pain_line")),
        "why_now_line": compact(copy_brief.get("why_now_line")),
        "cost_line": compact(copy_brief.get("cost_line")),
        "proof_line": compact(copy_brief.get("proof_line")),
        "cta_line": compact(copy_brief.get("cta_line")),
    }
    return emails


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def email_1_llm_rewrite_enabled(row: dict[str, Any]) -> bool:
    if truthy(row.get("disable_llm_humaniser")) or truthy(row.get("disable_llm_humanizer")) or truthy(row.get("disable_llm_rewrite")):
        return False
    if truthy(row.get("skip_openrouter")):
        return False
    if not sendable_email(row) and not row.get("copy_qa_mode"):
        return False
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def email_1_rewrite_payload(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    copy_brief: dict[str, Any],
    emails: dict[str, Any],
) -> dict[str, Any]:
    email1 = emails.get("email_1") or {}
    email2 = emails.get("email_2") or {}
    funding_safe = funding_claim_send_safe(funding, copy_brief, classification)
    return {
        "company_name": email_display_company_name(row),
        "first_name": first_name_from_contact(compact(row.get("selected_contact_name"))),
        "selected_contact_title": compact(row.get("selected_contact_title") or row.get("selected_contact_role")),
        "track": email_variant_track(classification),
        "pressure_type": classification.get("pressure_type", ""),
        "deterministic_subject": compact(email1.get("chosen_subject")),
        "deterministic_body": compact(email1.get("body")),
        "deterministic_email_1": {
            "subject": compact(email1.get("chosen_subject")),
            "body": strip_trailing_signature(email1.get("body") or ""),
        },
        "deterministic_email_2": {
            "subject": compact(email2.get("chosen_subject")),
            "body": strip_trailing_signature(email2.get("body") or ""),
        },
        "approved_company_hook": compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal")),
        "approved_problem": compact(copy_brief.get("email_problem_statement")),
        "approved_mechanism": compact(copy_brief.get("email_mechanism_statement")),
        "approved_cta": compact(copy_brief.get("email_cta")),
        "clinic_profile_phrase": compact(copy_brief.get("clinic_profile_phrase")),
        "asset": compact(copy_brief.get("email_asset_offer")),
        "email_2_required_ps": EMAIL_2_VALUE_PS,
        "email_2_target_words": "85-92",
        "email_2_hard_max_words": 95,
        "email_2_required_shape": "4 short paragraphs: opener, support route, CTA, exact P.S.",
        "email_2_mode": compact(copy_brief.get("email_2_mode") or copy_brief.get("funding_followup_mode")),
        "funding_claim_line": compact(funding.funding_claim_line),
        "funding_claim_safe": funding_safe,
        "pricing_email_2_mode": compact(copy_brief.get("pricing_email_2_mode")),
        "pricing_claim_safe": bool(copy_brief.get("pricing_claim_safe")),
        "pricing_claim_line": compact(copy_brief.get("pricing_claim_line")),
        "forbidden_claims": [
            "Do not say Cyber Essentials equals HIA compliance.",
            "Do not say Cyber Essentials equals PDPA compliance.",
            "Do not mention funding unless funding_claim_safe is true.",
            "Do not invent company facts, locations, headcount, pricing, or eligibility.",
        ],
    }


def call_email_1_rewrite_llm(payload: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        response = requests.post(
            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions").strip(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OUTREACH_EMAIL_1_REWRITE_MODEL", os.getenv("OUTREACH_HIA_LLM_MODEL", "deepseek/deepseek-v4-flash")).strip(),
                "temperature": float(os.getenv("OUTREACH_EMAIL_1_REWRITE_TEMPERATURE", "0.35")),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": EMAIL_1_REWRITE_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            },
            timeout=float(os.getenv("OUTREACH_EMAIL_1_REWRITE_TIMEOUT_SECONDS", "20")),
        )
        raise_for_openrouter_account_error(response, "email 1 rewrite")
        response.raise_for_status()
        choices = response.json().get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(content).strip(), flags=re.IGNORECASE)
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except ProviderAccountError:
        raise
    except Exception:
        return None


def email_1_rewrite_static_flags(body: str, deterministic_body: str, classification: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    body_l = compact(body).lower()
    deterministic_lines = [line for line in deterministic_body.splitlines() if compact(line)]
    greeting_match = re.match(r"^(Hi [^,]{1,60},|Hello team,)", deterministic_lines[0]) if deterministic_lines else None
    greeting = greeting_match.group(1) if greeting_match else ""
    if greeting and not body.startswith(greeting):
        flags.append("llm_email_1_rewrite_changed_greeting")
    if not body or word_count(body) > 95:
        flags.append("llm_email_1_rewrite_length")
    if len([part for part in body.split("\n\n") if compact(part)]) < 4:
        flags.append("llm_email_1_rewrite_paragraph_shape")
    if "from the site" in body_l:
        flags.append("llm_email_1_rewrite_from_site")
    if "rayn" in body_l:
        flags.append("llm_email_1_rewrite_mentions_rayn")
    if any(phrase in body_l for phrase in AI_GIVEAWAY_PHRASES):
        flags.append("llm_email_1_rewrite_ai_phrase")
    if classification.get("pressure_type") == "hia_regulatory":
        hia_pos = body_l.find("hia")
        ce_pos = body_l.find("cyber essentials")
        if hia_pos < 0 or hia_pos > 400 or (ce_pos >= 0 and hia_pos > ce_pos):
            flags.append("llm_email_1_rewrite_hia_not_early")
    if re.search(r"cyber essentials (?:makes|gets|keeps|ensures).{0,40}(?:compliant|compliance)", body_l):
        flags.append("llm_email_1_rewrite_forbidden_compliance_claim")
    return flags


def email_2_rewrite_static_flags(body: str, deterministic_body: str, classification: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    body_l = compact(body).lower()
    if not body or word_count(body) > 105:
        flags.append("llm_email_2_rewrite_length")
    if len([part for part in body.split("\n\n") if compact(part)]) < 4:
        flags.append("llm_email_2_rewrite_paragraph_shape")
    if EMAIL_2_VALUE_PS not in body:
        flags.append("llm_email_2_rewrite_missing_value_ps")
    ps_lines = [compact(line) for line in body.splitlines() if compact(line).lower().startswith("p.s.")]
    if re.search(r"\bP\.S\.\s*\d", body):
        flags.append("llm_email_2_rewrite_broken_ps")
    if body.count(EMAIL_2_VALUE_PS) != 1 or ps_lines != [EMAIL_2_VALUE_PS]:
        flags.append("llm_email_2_rewrite_changed_value_ps")
    if "from the site" in body_l:
        flags.append("llm_email_2_rewrite_from_site")
    if "rayn" in body_l:
        flags.append("llm_email_2_rewrite_mentions_rayn")
    if any(phrase in body_l for phrase in AI_GIVEAWAY_PHRASES):
        flags.append("llm_email_2_rewrite_ai_phrase")
    prefix_match = re.match(r"^([A-Z][A-Za-z.'-]{1,40} - )", deterministic_body)
    if prefix_match:
        prefix = prefix_match.group(1)
        if not body.startswith(prefix):
            flags.append("llm_email_2_rewrite_changed_prefix")
        after_prefix = body[len(prefix) : len(prefix) + 1]
        if after_prefix and after_prefix.isalpha() and after_prefix != after_prefix.lower():
            flags.append("llm_email_2_rewrite_prefix_not_lowercase")
    else:
        greeting_match = re.match(r"^(Hi [^,]{1,60},|Hello team,)", deterministic_body)
        if greeting_match and not body.startswith(greeting_match.group(1)):
            flags.append("llm_email_2_rewrite_changed_greeting")
    if classification.get("pressure_type") == "hia_regulatory" and "hia" not in body_l:
        flags.append("llm_email_2_rewrite_missing_hia")
    if classification.get("pressure_type") != "hia_regulatory" and re.search(r"\b(?:s\$|sgd)\s*\d|\bcisoaas pricing\b", body_l):
        flags.append("llm_email_2_rewrite_non_hia_pricing_claim")
    if re.search(r"cyber essentials (?:makes|gets|keeps|ensures).{0,40}(?:compliant|compliance)", body_l):
        flags.append("llm_email_2_rewrite_forbidden_compliance_claim")
    return flags


def normalize_email_2_opening_case(body: str, deterministic_body: str) -> str:
    if re.match(r"^[A-Z][A-Za-z.'-]{1,40} - ", deterministic_body):
        return body
    if body and body[0].isalpha() and body[0].islower():
        return body[0].upper() + body[1:]
    return body


def _email_rewrite_disabled_metadata(reason: str) -> dict[str, Any]:
    return {"attempted": False, "used": False, "reason": reason}


def _email_rewrite_subject_options(subject: str, original: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([subject, *((original or {}).get("subject_options") or [])]))


def _email_rewrite_candidate_snapshot(subject: str, body: str) -> dict[str, Any]:
    return {
        "subject": compact(subject),
        "body": body,
        "word_count": word_count(body),
    }


def _email_rewrite_candidate_from_result(
    result: dict[str, Any],
    original: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    result_email1 = result.get("email_1") if isinstance(result.get("email_1"), dict) else result
    result_email2 = result.get("email_2") if isinstance(result.get("email_2"), dict) else None
    subject1 = compact(result_email1.get("subject") or original["email_1"].get("chosen_subject"))
    body1 = strip_trailing_signature(result_email1.get("body") or "")
    subject2 = compact((result_email2 or {}).get("subject") or original["email_2"].get("chosen_subject"))
    body2 = strip_trailing_signature((result_email2 or {}).get("body") or original["email_2"].get("body") or "")
    body2 = normalize_email_2_opening_case(body2, original["email_2"].get("body", ""))
    candidate = {
        **original,
        "email_1": {
            **(original.get("email_1") or {}),
            "chosen_subject": subject1,
            "subject_options": _email_rewrite_subject_options(subject1, original.get("email_1") or {}),
            "body": body1,
            "word_count": word_count(body1),
        },
        "email_2": {
            **(original.get("email_2") or {}),
            "chosen_subject": subject2,
            "subject_options": _email_rewrite_subject_options(subject2, original.get("email_2") or {}),
            "body": body2,
            "word_count": word_count(body2),
        },
    }
    return candidate, bool(result_email2)


def _email_rewrite_reject_flags(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    copy_brief: dict[str, Any],
    original: dict[str, Any],
    candidate: dict[str, Any],
    has_email_2: bool,
) -> tuple[int, list[str]]:
    body1 = candidate["email_1"].get("body", "")
    body2 = candidate["email_2"].get("body", "")
    static_flags = email_1_rewrite_static_flags(body1, original["email_1"].get("body", ""), classification)
    if has_email_2:
        static_flags += email_2_rewrite_static_flags(body2, original["email_2"].get("body", ""), classification)
    score, gate_flags, _ = quality_gate(row, classification, funding, candidate, copy_brief)
    reject_flags = list(
        dict.fromkeys(
            static_flags
            + severe_flags(gate_flags)
            + [flag for flag in gate_flags if flag.startswith("email_1_") or flag.startswith("email_2_")]
        )
    )
    return score, reject_flags


def _email_rewrite_rejected_metadata(
    candidate: dict[str, Any],
    reject_flags: list[str],
    has_email_2: bool,
    attempt_number: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    model = os.getenv("OUTREACH_EMAIL_1_REWRITE_MODEL", os.getenv("OUTREACH_HIA_LLM_MODEL", "deepseek/deepseek-v4-flash")).strip()
    body1 = candidate["email_1"].get("body", "")
    body2 = candidate["email_2"].get("body", "")
    metadata = {
        "attempted": True,
        "used": False,
        "reason": "qa_rejected",
        "attempt_number": attempt_number,
        "flags": reject_flags,
        "model": model,
        "rejected_candidate_word_counts": {
            "email_1": word_count(body1),
            "email_2": word_count(body2) if has_email_2 else None,
        },
    }
    email1_metadata = {
        **metadata,
        "rejected_candidate": _email_rewrite_candidate_snapshot(candidate["email_1"].get("chosen_subject", ""), body1),
    }
    email2_metadata = {
        **metadata,
        "attempted": has_email_2,
        "rejected_candidate": _email_rewrite_candidate_snapshot(candidate["email_2"].get("chosen_subject", ""), body2) if has_email_2 else {},
    }
    return metadata, email1_metadata, email2_metadata


def _email_rewrite_retry_feedback(
    payload: dict[str, Any],
    reject_flags: list[str],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        **payload,
        "retry_instruction": {
            "attempt": 2,
            "reason": "first_rewrite_failed_qa",
            "qa_flags": reject_flags,
            "fix_only_these_issues": True,
            "rules": [
                "Return a fresh rewrite, not an explanation.",
                "Keep Email 2 under 95 words. Aim for 85-92 words.",
                "Keep the required P.S. exactly as provided.",
                "Use 4 short paragraphs for Email 1 and Email 2. Email 2 must be opener, support route, CTA, exact P.S.",
                "Cut extra explanation before the P.S.; the P.S. already carries the scope/value point.",
                "Make Email 1 specific; do not weaken the company hook.",
                "Do not add funding percentages, grants, exact prices, or eligibility unless already present in the deterministic email and marked safe.",
            ],
            "rejected_candidate": {
                "email_1": _email_rewrite_candidate_snapshot(
                    candidate["email_1"].get("chosen_subject", ""),
                    candidate["email_1"].get("body", ""),
                ),
                "email_2": _email_rewrite_candidate_snapshot(
                    candidate["email_2"].get("chosen_subject", ""),
                    candidate["email_2"].get("body", ""),
                ),
            },
        },
    }


def maybe_rewrite_email_1_with_llm(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    copy_brief: dict[str, Any],
    emails: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    if not email_1_llm_rewrite_enabled(row):
        reason = "missing_api_key" if not os.getenv("OPENROUTER_API_KEY", "").strip() else "disabled"
        emails["llm_email_1_rewrite"] = _email_rewrite_disabled_metadata(reason)
        emails["llm_email_2_rewrite"] = _email_rewrite_disabled_metadata(reason)
        emails["llm_email_rewrite"] = _email_rewrite_disabled_metadata(reason)
        return emails, []
    original = sanitize_email_sequence(emails)
    payload = email_1_rewrite_payload(row, classification, funding, copy_brief, original)
    result = call_email_1_rewrite_llm(payload)
    if not isinstance(result, dict):
        metadata = {"attempted": True, "used": False, "reason": "llm_error_or_empty"}
        original["llm_email_1_rewrite"] = metadata
        original["llm_email_2_rewrite"] = metadata
        original["llm_email_rewrite"] = metadata
        return original, []
    candidate, has_email_2 = _email_rewrite_candidate_from_result(result, original)
    used_result = result
    score, reject_flags = _email_rewrite_reject_flags(row, classification, funding, copy_brief, original, candidate, has_email_2)
    retry_metadata = None
    if score < 7 or reject_flags:
        first_metadata, first_email1_metadata, first_email2_metadata = _email_rewrite_rejected_metadata(candidate, reject_flags, has_email_2, 1)
        retry_result = call_email_1_rewrite_llm(_email_rewrite_retry_feedback(payload, reject_flags, candidate))
        if isinstance(retry_result, dict):
            retry_candidate, retry_has_email_2 = _email_rewrite_candidate_from_result(retry_result, original)
            retry_score, retry_reject_flags = _email_rewrite_reject_flags(row, classification, funding, copy_brief, original, retry_candidate, retry_has_email_2)
            if retry_score >= 7 and not retry_reject_flags:
                candidate = retry_candidate
                has_email_2 = retry_has_email_2
                used_result = retry_result
                retry_metadata = {
                    "attempted": True,
                    "used": True,
                    "reason": "qa_passed",
                    "attempt_number": 2,
                    "first_attempt": first_metadata,
                }
            else:
                retry_metadata, retry_email1_metadata, retry_email2_metadata = _email_rewrite_rejected_metadata(
                    retry_candidate,
                    retry_reject_flags,
                    retry_has_email_2,
                    2,
                )
                retry_metadata["first_attempt"] = first_metadata
                retry_email1_metadata["first_attempt"] = first_email1_metadata
                retry_email2_metadata["first_attempt"] = first_email2_metadata
                original["llm_email_1_rewrite"] = retry_email1_metadata
                original["llm_email_2_rewrite"] = retry_email2_metadata
                original["llm_email_rewrite"] = retry_metadata
                return original, []
        else:
            first_metadata["retry_attempted"] = True
            first_metadata["retry_used"] = False
            first_metadata["retry_reason"] = "llm_error_or_empty"
            first_email1_metadata["retry_attempted"] = True
            first_email1_metadata["retry_used"] = False
            first_email1_metadata["retry_reason"] = "llm_error_or_empty"
            first_email2_metadata["retry_attempted"] = True
            first_email2_metadata["retry_used"] = False
            first_email2_metadata["retry_reason"] = "llm_error_or_empty"
            original["llm_email_1_rewrite"] = first_email1_metadata
            original["llm_email_2_rewrite"] = first_email2_metadata
            original["llm_email_rewrite"] = first_metadata
            return original, []
    candidate["llm_email_1_rewrite"] = {
        "attempted": True,
        "used": True,
        "reason": "qa_passed",
        "attempt_number": retry_metadata["attempt_number"] if retry_metadata else 1,
        "model": os.getenv("OUTREACH_EMAIL_1_REWRITE_MODEL", os.getenv("OUTREACH_HIA_LLM_MODEL", "deepseek/deepseek-v4-flash")).strip(),
        "notes": used_result.get("notes") if isinstance(used_result.get("notes"), list) else [],
    }
    if retry_metadata:
        candidate["llm_email_1_rewrite"]["first_attempt"] = retry_metadata["first_attempt"]
    candidate["llm_email_2_rewrite"] = {
        **candidate["llm_email_1_rewrite"],
        "attempted": has_email_2,
        "used": has_email_2,
    }
    candidate["llm_email_rewrite"] = {
        "attempted": True,
        "used": True,
        "reason": "qa_passed",
        "attempt_number": candidate["llm_email_1_rewrite"]["attempt_number"],
        "model": candidate["llm_email_1_rewrite"]["model"],
        "emails_rewritten": ["email_1", *([] if not has_email_2 else ["email_2"])],
        "notes": candidate["llm_email_1_rewrite"]["notes"],
    }
    if retry_metadata:
        candidate["llm_email_rewrite"]["first_attempt"] = retry_metadata["first_attempt"]
    return candidate, []


def normalize_llm_email_sequence(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("llm_email_json_not_object")
    emails: dict[str, Any] = {
        "evidence_used": candidate.get("evidence_used", []),
        "claims_avoided": candidate.get("claims_avoided", []),
        "quality_notes": candidate.get("quality_notes", []),
    }
    for index in range(1, 5):
        key = f"email_{index}"
        item = candidate.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"missing_{key}")
        subject = compact(item.get("chosen_subject") or item.get("subject") or "")
        body = trim_text(item.get("body") or "")
        subject_options = item.get("subject_options")
        if not isinstance(subject_options, list):
            subject_options = [subject] if subject else []
        body = strip_trailing_signature(body)
        emails[key] = {
            "subject_options": [compact(option) for option in subject_options if compact(option)],
            "chosen_subject": subject,
            "body": body,
            "word_count": word_count(body),
        }
    return emails


def sanitize_email_sequence(emails: dict[str, Any]) -> dict[str, Any]:
    sanitized = {**emails}
    for key in ("email_1", "email_2", "email_3", "email_4"):
        item = dict(sanitized.get(key) or {})
        body = strip_trailing_signature(item.get("body", ""))
        item["body"] = body
        item["word_count"] = word_count(body)
        sanitized[key] = item
    return sanitized


def enforce_funding_claim_email(
    row: dict[str, Any],
    funding: FundingMatch,
    emails: dict[str, Any],
    classification: dict[str, Any] | None = None,
    copy_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if classification is not None and copy_brief is not None and not funding_claim_send_safe(funding, copy_brief, classification):
        return value_fallback_email_2(row, emails, (copy_brief or {}).get("email_asset_offer"), classification, copy_brief)
    claim = trim_text(funding.funding_claim_line)
    if not claim:
        return value_fallback_email_2(row, emails, (copy_brief or {}).get("email_asset_offer"), classification, copy_brief)
    email2 = emails.get("email_2") or {}
    existing_body = trim_text(email2.get("body"))
    caveat_count = existing_body.lower().count("subject to programme confirmation")
    useful_line = "The useful first step is to check the route before lining up readiness work."
    if claim.lower() in existing_body.lower() and funding_only_email(existing_body, claim) and caveat_count <= 1 and useful_line.lower() in existing_body.lower():
        return emails
    prefix = followup_name_prefix(row, "-")
    subject = "HIA / cyber funding" if classification and classification.get("pressure_type") == "hia_regulatory" else compact(email2.get("chosen_subject")) or "Cyber Essentials funding"
    caveat = "" if "subject to programme confirmation" in claim.lower() else "\n\nThis is subject to programme confirmation."
    body = funding_email_2_body_fixed(prefix, claim, caveat)
    emails = {**emails}
    emails["email_2"] = {
        "subject_options": list(email2.get("subject_options") or [subject]),
        "chosen_subject": subject,
        "body": body,
        "word_count": word_count(body),
    }
    return emails


def reflects(text: str, phrase: str) -> bool:
    text_l = text.lower()
    phrase_l = phrase.lower()
    if not phrase_l:
        return False
    if phrase_l in text_l:
        return True
    words = [word for word in re.findall(r"[a-z0-9]+", phrase_l) if len(word) > 3]
    return bool(words) and sum(1 for word in words[:8] if word in text_l) >= min(3, len(words))


def email_1_reflects_signal(body: str, signal: str, copy_brief: dict[str, Any]) -> bool:
    if reflects(body, signal):
        return True
    if compact(copy_brief.get("email_1_hook_style")) in {"question_strong_context", "careful_weak_context"}:
        first = compact(body.split("\n\n", 1)[0])
        first = re.sub(r"^(hi [^,]{1,60},|hello team,)\s*", "", first, flags=re.I)
        return bool((first and "?" in first) or first.lower().startswith(("looks like", "for ")))
    return False


def generic_personalisation_signal(signal: str) -> bool:
    signal_l = compact(signal).lower()
    if not signal_l:
        return True
    generic_phrases = (
        "appears to operate in healthcare",
        "appears to handle customer data",
        "website indicates healthcare activity",
        "organisation appears to handle personal data",
        "organisation appears to",
        "healthcare provider",
        "healthcare setting",
        "private company",
        "handles customer data",
    )
    concrete_terms = (
        "clinic service",
        "clinic group",
        "group healthcare",
        "multi-location",
        "medical-clinic",
        "outpatient",
        "surgical clinic",
        "dental clinic",
        "home-care",
        "caregiver",
        "long-term care",
        "team",
        "practitioner",
        "doctor",
        "hearing-care",
        "appointment",
        "test",
        "device",
        "resident",
        "beneficiary",
        "volunteer",
        "staff",
        "community-service",
        "care/community",
        "customer security questions",
        "reusable security evidence",
        "vendor",
        "dashboard",
        "integration",
        "singapore-facing",
    )
    has_generic = any(phrase in signal_l for phrase in generic_phrases)
    has_concrete = any(term in signal_l for term in concrete_terms)
    return has_generic and not has_concrete


def clinic_profile_too_generic(copy_brief: dict[str, Any]) -> bool:
    phrase = compact(copy_brief.get("clinic_profile_phrase")).lower()
    if not phrase:
        return True
    generic = {"a healthcare provider", "a clinic", "a healthcare organisation", "a medical clinic"}
    return phrase in generic


def email_1_missing_clinic_profile(body: str, copy_brief: dict[str, Any]) -> bool:
    phrase = compact(copy_brief.get("clinic_profile_phrase"))
    body_l = compact(body).lower()
    if re.search(r"\bfor\s+.{4,120}\s+like\s+.{2,80},\s+are patient records spread across\b", body_l):
        return False
    if not phrase:
        return True
    if reflects(body, phrase):
        return False
    profile_guess = compact(copy_brief.get("clinic_profile_guess")).lower()
    equivalents = {
        "solo_gp": ("gp", "family clinic", "medical-clinic", "medical clinic", "doctor-led", "outpatient"),
        "family_gp": ("gp", "family clinic", "medical-clinic", "medical clinic", "doctor-led", "outpatient"),
        "multi_doctor_gp": ("multi-doctor", "doctor", "medical-clinic", "medical clinic", "outpatient", "clinic"),
        "clinic_group": ("clinic group", "multi-location", "group healthcare", "our clinics", "clinic"),
        "hospice_long_term_care": ("long-term care", "hospice", "resident", "caregiver", "care provider"),
        "home_care": ("home-care", "caregiver", "care provider", "patient"),
        "specialist_led": ("specialist", "surgical clinic", "surgery", "clinic"),
        "dental": ("dental", "braces", "orthodont"),
        "pharmacy": ("pharmacy", "compounding"),
        "diagnostic_lab": ("diagnostic", "laboratory", "screening"),
        "hospital": ("hospital", "patient", "clinical records"),
        "healthcare_group": ("healthcare holding", "group organisation", "institutional healthcare"),
        "elder_daycare": ("day-care provider", "elder/client care", "elder care"),
        "allied_health": ("allied-health", "physiotherapy", "treatment support"),
        "mental_health": ("psychology", "mental-health", "assessment"),
        "hearing_care": ("hearing-care", "hearing test", "audiology"),
        "nursing_home": ("nursing home", "resident", "patient care", "care records"),
        "community_hospital": ("community hospital", "patient", "discharge records"),
    }
    return not any(term in body_l for term in equivalents.get(profile_guess, ()))


def hia_record_terms(records: str) -> list[str]:
    normalized = compact(records)
    terms = [compact(part) for part in re.split(r",|\band\b", normalized) if compact(part)]
    return [term for term in terms if len(term) > 3 and term.lower() not in {"where used"}]


def funding_only_email(body: str, claim: str) -> bool:
    body_l = compact(body).lower()
    if claim and claim.lower() not in body_l:
        return False
    non_funding_markers = (
        "hia timelines",
        "health information sits",
        "who can access",
        "which vendors touch",
        "how backups work",
        "pdpa safeguards",
        "security safeguards can be shown",
        "customer security questions",
        "incident response readiness",
    )
    return not any(marker in body_l for marker in non_funding_markers)


def funding_only_email_3(body: str, claim: str) -> bool:
    return funding_only_email(body, claim)


def pricing_email_quality_flags(body: str, classification: dict[str, Any], copy_brief: dict[str, Any]) -> list[str]:
    body_l = compact(body).lower()
    flags: list[str] = []
    price_present = "s$4,300" in body_l or "s$4300" in body_l
    cisaas_pricing_present = "cisaas pricing" in body_l or "endpoint-based" in body_l
    if classification.get("pressure_type") != "hia_regulatory":
        if price_present or cisaas_pricing_present:
            flags.append("non_hia_pricing_claim")
        return flags

    pricing_mode = compact(copy_brief.get("pricing_email_2_mode"))
    if pricing_mode in {"", "no_price_claim"}:
        return flags
    has_endpoint_caveat = "endpoint-based" in body_l or "endpoint count" in body_l
    if pricing_mode in {"endpoint_sizing_needed", "group_or_larger_sizing_needed"} and not has_endpoint_caveat:
        flags.append("hia_pricing_missing_endpoint_caveat")
    if price_present and not any(term in body_l for term in ("smaller clinics", "small clinics", "smaller clinic", "small clinic")):
        flags.append("hia_pricing_exact_price_without_small_clinic_context")
    if "70%" in body_l and not any(term in body_l for term in ("if the route applies", "subject to programme confirmation")):
        flags.append("hia_pricing_percentage_missing_caveat")
    if pricing_mode == "group_or_larger_sizing_needed" and price_present and not any(
        term in body_l for term in ("larger setups depend on endpoint count", "larger setups move differently", "group clinics can move into a different tier", "bigger or group setups can move", "larger setups can move tiers", "endpoint count changes the price", "check that before quoting", "endpoint count drives")
    ):
        flags.append("hia_pricing_group_exact_price_claim")
    if any(term in body_l for term in ("you qualify", "you are eligible", "guaranteed funding", "all clinics qualify for funding")):
        flags.append("hia_pricing_forbidden_funding_claim")
    return flags


def email_2_generic_hia_diagnostic(body: str, classification: dict[str, Any]) -> bool:
    if classification.get("pressure_type") != "hia_regulatory":
        return False
    body_l = compact(body).lower()
    generic_markers = (
        "where health information sits",
        "which vendors touch it",
        "how backups work",
        "who reports an incident",
    )
    segment_terms = (
        "patient records",
        "appointment details",
        "consultation notes",
        "clinic email",
        "imaging files",
        "dental software",
        "prescription",
        "dispensing",
        "compounding",
        "diagnostic reports",
        "lab systems",
        "cardiac test reports",
        "referrals",
        "procedure-related records",
        "consent forms",
        "procedure records",
        "follow-up notes",
        "skin consultation notes",
        "clinical images",
        "eye examination records",
        "imaging",
        "prescriptions",
        "hearing test records",
        "device-related records",
        "exercise-plan records",
        "case-note records",
        "resident",
        "caregiver",
    )
    return all(marker in body_l for marker in generic_markers) and not any(term in body_l for term in segment_terms)


def email_2_missing_hia_segment_terms(body: str, row: dict[str, Any], classification: dict[str, Any]) -> bool:
    if classification.get("pressure_type") != "hia_regulatory":
        return False
    body_l = compact(body).lower()
    clinic_profile = infer_clinic_profile(row, classification, lower_blob(row))
    records = hia_email_1_records(row, classification, clinic_profile)
    required = hia_record_terms(records)
    if not required:
        return False
    required_hits = sum(1 for term in required if term.lower() in body_l)
    return required_hits < min(3, len(required))


def email_3_missing_hia_segment_terms(body: str, row: dict[str, Any], classification: dict[str, Any]) -> bool:
    return email_2_missing_hia_segment_terms(body, row, classification)


def email_2_not_hia_segment_diagnostic_shape(
    body: str,
    row: dict[str, Any],
    classification: dict[str, Any],
) -> bool:
    if classification.get("pressure_type") != "hia_regulatory":
        return False
    body_l = compact(body).lower()
    body_l = re.sub(r"^[a-z][a-z'’-]{1,40}\s+-\s+", "", body_l)
    approved_openers = (
        "simple check: can ",
        "one useful check: can ",
        "a practical diagnostic: can ",
        "quick diagnostic: can ",
        "the check i would use: can ",
        "one practical test: can ",
    )
    if not body_l.startswith(approved_openers):
        return True
    clinic_profile = infer_clinic_profile(row, classification, lower_blob(row))
    expected_asset = segment_asset(row, classification, clinic_profile).lower()
    if expected_asset and expected_asset not in body_l:
        return True
    if "show where" in body_l:
        required = ("sit today", "who owns access", "backups", "handles incidents")
        if not all(term in body_l for term in required):
            return True
    elif "show who owns access" in body_l:
        required = ("who owns access", "where backups sit", "handles incidents")
        if not all(term in body_l for term in required):
            return True
    else:
        required = ("map", "access", "backups", "incident contacts")
        if not all(term in body_l for term in required):
            return True
    wrong_segment_terms = {
        "retail_pharmacy": ("clinic email", "appointment forms", "dental software", "consultation notes"),
        "dental": ("clinic email", "prescription", "dispensing", "compounding"),
        "hearing_care": ("clinic email", "prescription", "dental software", "consultation notes"),
        "diagnostic": ("clinic email", "dental software", "prescription", "dispensing"),
    }
    service_type = classification.get("hia_service_type_guess")
    profile_guess = clinic_profile.get("clinic_profile_guess", "")
    if profile_guess in {"aesthetic_medical", "solo_gp", "family_gp", "multi_doctor_gp"}:
        return False
    return any(term in body_l for term in wrong_segment_terms.get(str(service_type), ()))


def email_3_not_hia_segment_diagnostic_shape(
    body: str,
    row: dict[str, Any],
    classification: dict[str, Any],
) -> bool:
    return email_2_not_hia_segment_diagnostic_shape(body, row, classification)


def asset_offer_too_generic_for_segment(row: dict[str, Any], classification: dict[str, Any], copy_brief: dict[str, Any]) -> bool:
    if classification.get("pressure_type") != "hia_regulatory":
        return False
    expected = segment_asset(row, classification, copy_brief).lower()
    actual = compact(copy_brief.get("email_asset_offer")).lower()
    return bool(expected and actual) and actual != expected


def email_2_is_diagnostic(body: str, copy_brief: dict[str, Any], classification: dict[str, Any]) -> bool:
    body_l = compact(body).lower()
    if "?" not in body_l:
        return False
    if "cyber essentials is" in body_l and "can " not in body_l:
        return False
    if email_2_generic_hia_diagnostic(body, classification):
        return False
    systems = compact(copy_brief.get("data_systems_likely")).lower()
    system_terms = [word for word in re.findall(r"[a-z0-9]+", systems) if len(word) > 4]
    if system_terms and sum(1 for word in system_terms[:10] if word in body_l) >= 2:
        return True
    if classification.get("pressure_type") == "hia_regulatory":
        return all(term in body_l for term in ("health information", "access")) and "incident" in body_l
    if classification.get("entity_type_guess") in {"npo", "charity", "social_service"}:
        return "beneficiary" in body_l and "incident" in body_l
    if classification.get("pressure_type") == "customer_trust":
        return "customer security question" in body_l and "evidence" in body_l
    return "personal data" in body_l and "access" in body_l and "incident" in body_l


def email_3_is_diagnostic(body: str, copy_brief: dict[str, Any], classification: dict[str, Any]) -> bool:
    return email_2_is_diagnostic(body, copy_brief, classification)


def email_1_starts_with_target_structure(body: str, copy_brief: dict[str, Any]) -> bool:
    body_l = compact(body).lower()
    signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal")).lower()
    problem = compact(copy_brief.get("email_problem_statement")).lower()
    mechanism = compact(copy_brief.get("email_mechanism_statement")).lower()
    cta = compact(copy_brief.get("email_cta")).lower()
    positions = []
    for index, phrase in enumerate((signal, problem, mechanism, cta)):
        if not phrase:
            positions.append(-1)
            continue
        position = body_l.find(phrase[: min(len(phrase), 80)])
        if index == 0 and position < 0:
            profile_phrase = compact(copy_brief.get("clinic_profile_phrase")).lower()
            if profile_phrase:
                position = body_l.find(profile_phrase)
            if position < 0 and email_1_reflects_signal(body, signal, copy_brief):
                position = 0
        positions.append(position)
    if any(pos < 0 for pos in positions):
        return False
    return positions == sorted(positions)


def generic_inbox_greeting_ok(row: dict[str, Any], emails: dict[str, Any]) -> bool:
    if compact(row.get("selected_contact_name")):
        return True
    company = compact(row.get("company_name")).lower()
    email1_prefixes = ["hi team,", "hello team,"]
    if company:
        email1_prefixes.append(f"hi {company} team,")
    email1 = trim_text((emails.get("email_1") or {}).get("body")).lower()
    if email1 and not any(email1.startswith(prefix) for prefix in email1_prefixes):
        return False
    for key in ("email_2", "email_3", "email_4"):
        body = trim_text((emails.get(key) or {}).get("body")).lower()
        if body and re.match(r"^(?:hi|hello)\s+", body):
            return False
    return True


ACTIVE_EMAIL_KEYS = ("email_1", "email_2")
ALL_EMAIL_KEYS = ("email_1", "email_2", "email_3", "email_4")
DISABLED_FOLLOWUP_EMAIL = {"subject_options": [], "chosen_subject": "", "body": "", "word_count": 0}


def active_email_body_blob(emails: dict[str, Any]) -> str:
    return "\n".join((emails.get(key) or {}).get("body", "") for key in ACTIVE_EMAIL_KEYS)


def suppress_followup_emails(emails: dict[str, Any]) -> dict[str, Any]:
    emails = {**emails}
    emails["email_3"] = dict(DISABLED_FOLLOWUP_EMAIL)
    emails["email_4"] = dict(DISABLED_FOLLOWUP_EMAIL)
    emails["sequence_metadata"] = {"sequence_length": 2, "disabled_emails": ["email_3", "email_4"]}
    return emails


def evaluate_email_strategy(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    emails: dict[str, Any],
    copy_brief: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if classification.get("pressure_type") == "not_ready":
        return flags
    email1 = emails["email_1"]["body"]
    email2 = emails["email_2"]["body"]
    signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal"))

    if not signal or not email_1_reflects_signal(email1, signal, copy_brief):
        flags.append("email_1_missing_specific_signal")
    if not compact(copy_brief.get("email_problem_statement")) or not reflects(email1, copy_brief["email_problem_statement"]):
        flags.append("email_1_missing_problem_statement")
    if not compact(copy_brief.get("email_mechanism_statement")) or not reflects(email1, copy_brief["email_mechanism_statement"]):
        flags.append("email_1_missing_mechanism_statement")
    if not compact(copy_brief.get("email_cta")) or not reflects(email1, copy_brief["email_cta"]) or "?" not in email1:
        flags.append("email_1_missing_tiny_cta")
    if email_contains_internal_signal_language(email1):
        flags.append("email_1_contains_internal_signal_language")
    active_blob = active_email_body_blob(emails)
    if email_contains_internal_signal_language(active_blob):
        flags.append("email_contains_internal_signal_language")
    if email_contains_hia_batch_wording(active_blob):
        flags.append("email_contains_hia_batch_wording")
    if classification.get("pressure_type") == "hia_regulatory":
        if not compact(copy_brief.get("clinic_profile_phrase")):
            flags.append("clinic_profile_missing_for_hia")
        if clinic_profile_too_generic(copy_brief):
            flags.append("clinic_profile_too_generic")
        if email_1_missing_clinic_profile(email1, copy_brief):
            flags.append("email_1_missing_clinic_profile")
    if generic_personalisation_signal(copy_brief.get("email_personalisation_signal", "")) or not email_1_starts_with_target_structure(email1, copy_brief):
        flags.append("email_1_too_generic")
    if asset_offer_too_generic_for_segment(row, classification, copy_brief):
        flags.append("asset_offer_too_generic_for_segment")
    if classification.get("hia_service_type_guess") == "hearing_care" and not compact(copy_brief.get("prospect_facing_signal")):
        flags.append("hearing_care_missing_trigger")
    if classification.get("hia_service_type_guess") == "diagnostic" and classification.get("hia_confidence") == "low":
        flags.append("lab_classification_ambiguous")
    funding_followup_mode = funding_followup_mode_for(funding, copy_brief, classification)
    hia_pricing = hia_pricing_active(classification, copy_brief)
    if funding_followup_mode == "funding" and not hia_pricing and not funding_only_email(email2, funding.funding_claim_line):
        flags.append("email_2_not_funding_only")
    elif not hia_pricing and funding.funding_claim_line and funding.funding_claim_line in email2 and not funding_only_email(email2, funding.funding_claim_line):
        flags.append("email_2_not_funding_only")
    flags.extend(pricing_email_quality_flags(email2, classification, copy_brief))
    if not generic_inbox_greeting_ok(row, emails):
        flags.append("generic_inbox_wrong_greeting")
    return flags


def quality_gate(
    row: dict[str, Any],
    classification: dict[str, Any] | FundingMatch,
    funding: FundingMatch | dict[str, Any],
    emails: dict[str, Any] | None = None,
    copy_brief: dict[str, Any] | None = None,
) -> tuple[int, list[str], bool]:
    if emails is None:
        # Backwards-compatible call shape: quality_gate(classification, funding, emails, copy_brief)
        row, classification, funding, emails, copy_brief = {}, row, classification, funding, copy_brief
    assert isinstance(classification, dict)
    assert isinstance(emails, dict)
    if isinstance(funding, dict):
        funding = FundingMatch(
            funding_status=str(funding.get("funding_status") or "not_checked"),
            funding_relevant=bool(funding.get("funding_relevant", False)),
            primary_funding_program=str(funding.get("primary_funding_program") or ""),
            matched=list(funding.get("matched") or []),
            possible=list(funding.get("possible") or []),
            not_applicable=list(funding.get("not_applicable") or []),
            funding_eligibility_basis=str(funding.get("funding_eligibility_basis") or ""),
            funding_claim_line=str(funding.get("funding_claim_line") or ""),
            funding_cta_asset=str(funding.get("funding_cta_asset") or "funding_route_summary"),
            funding_confidence=str(funding.get("funding_confidence") or "low"),
            funding_last_checked_at=str(funding.get("funding_last_checked_at") or ""),
            funding_source_urls=list(funding.get("funding_source_urls") or []),
            funding_human_review_required=bool(funding.get("funding_human_review_required", True)),
            reason=str(funding.get("reason") or ""),
        )
    flags: list[str] = []
    blob = active_email_body_blob(emails).lower()
    has_copy_brief = copy_brief is not None
    copy_brief = copy_brief or {}
    for phrase in FORBIDDEN_PHRASES:
        if phrase in blob:
            flags.append(f"forbidden_phrase:{phrase}")
    for phrase in STYLE_BANNED_PHRASES:
        if phrase in blob:
            flags.append(f"style_banned_phrase:{phrase}")

    limits = {"email_1": 85, "email_2": 105}
    for key, limit in limits.items():
        if emails[key]["word_count"] > limit:
            flags.append(f"{key}_too_long")

    funding_followup_mode = funding_followup_mode_for(funding, copy_brief, classification)
    hia_pricing = hia_pricing_active(classification, copy_brief)
    if funding_followup_mode == "funding" and not hia_pricing and classification.get("pressure_type") != "not_ready" and funding.funding_claim_line not in emails["email_2"]["body"]:
        flags.append("email_2_missing_funding_claim_line")
    if has_copy_brief and funding_followup_mode == "funding" and not hia_pricing and not copy_brief.get("funding_claim_safe") and classification.get("pressure_type") != "not_ready":
        flags.append("funding_needs_review")
    if re.search(r"\b\d{1,3}%\b", emails["email_2"]["body"]) and not any(
        item.get("exact_claim_allowed_in_email") for item in funding.matched
    ):
        flags.append("unverified_exact_percentage")
    if not classification.get("hia_deadline_claim_safe") and re.search(r"\b(sep|mar)\s+20(27|28|30)\b", blob):
        flags.append("unsafe_hia_deadline_claim")
    if email_contains_hia_batch_wording(blob):
        flags.append("email_contains_hia_batch_wording")
    if email_contains_internal_signal_language(blob):
        flags.append("email_contains_internal_signal_language")
    if "pdpa compliant" in blob and "does not make" not in blob:
        flags.append("cyber_essentials_equals_pdpa_compliance")
    if "hia compliant" in blob or "full hia compliance" in blob:
        flags.append("cyber_essentials_equals_hia_compliance")
    if not classification.get("outreach_trigger_signal"):
        flags.append("missing_outreach_trigger")
    if classification.get("outreach_trigger_confidence") == "low":
        flags.append("low_trigger_confidence")
    if funding_followup_mode == "funding" and classification.get("pressure_type") != "not_ready" and funding.funding_status != "verified_match":
        flags.append("funding_not_verified")
    if classification.get("pressure_type") == "not_ready" and any(emails[key]["body"] for key in ALL_EMAIL_KEYS):
        flags.append("not_ready_has_email_body")
    if has_copy_brief and classification.get("pressure_type") != "not_ready":
        for field in ("email_personalisation_signal", "email_problem_statement", "email_mechanism_statement", "email_cta"):
            if not compact(copy_brief.get(field)):
                flags.append(f"missing_copy_brief:{field}")
        email1_body = emails["email_1"]["body"]
        prospect_signal = compact(copy_brief.get("prospect_facing_signal") or copy_brief.get("email_personalisation_signal"))
        if prospect_signal and not email_1_reflects_signal(email1_body, prospect_signal, copy_brief):
            flags.append("email_1_missing_specific_signal")
        if generic_personalisation_signal(copy_brief.get("email_personalisation_signal", "")):
            flags.append("generic_personalisation_signal")
        if compact(copy_brief.get("email_problem_statement")) and not reflects(email1_body, copy_brief["email_problem_statement"]):
            flags.append("email_1_missing_problem_statement")
        if compact(copy_brief.get("email_mechanism_statement")) and not reflects(email1_body, copy_brief["email_mechanism_statement"]):
            flags.append("email_1_missing_mechanism_statement")
        if compact(copy_brief.get("email_cta")) and (not reflects(email1_body, copy_brief["email_cta"]) or "?" not in email1_body):
            flags.append("email_1_missing_tiny_cta")
        if email_contains_internal_signal_language(email1_body):
            flags.append("email_1_contains_internal_signal_language")
        if email_contains_hia_batch_wording(email1_body):
            flags.append("email_contains_hia_batch_wording")
        if classification.get("pressure_type") == "hia_regulatory":
            if not compact(copy_brief.get("clinic_profile_phrase")):
                flags.append("clinic_profile_missing_for_hia")
            if clinic_profile_too_generic(copy_brief):
                flags.append("clinic_profile_too_generic")
            if email_1_missing_clinic_profile(email1_body, copy_brief):
                flags.append("email_1_missing_clinic_profile")
        email1_start = email1_body.strip().lower()
        if email1_start.startswith(("i came across your company", "noticed your company", "i noticed your company")):
            flags.append("email_1_too_generic")
        if asset_offer_too_generic_for_segment(row, classification, copy_brief):
            flags.append("asset_offer_too_generic_for_segment")
        if classification.get("hia_service_type_guess") == "hearing_care" and not compact(copy_brief.get("prospect_facing_signal")):
            flags.append("hearing_care_missing_trigger")
        if classification.get("hia_service_type_guess") == "diagnostic" and classification.get("hia_confidence") == "low":
            flags.append("lab_classification_ambiguous")
        flags.extend(evaluate_email_strategy(row, classification, funding, emails, copy_brief))

    score = 0
    if classification.get("entity_type_guess") != "unknown":
        score += 2
    if classification.get("outreach_trigger_confidence") in {"medium", "high"}:
        score += 2
    if classification.get("problem_hypothesis") or copy_brief.get("email_problem_statement"):
        score += 2
    if classification.get("recommended_first_cert") != "unknown":
        score += 1
    if funding.funding_status == "verified_match":
        score += 1
    if all(emails[key]["body"].count("?") >= 1 for key in ("email_1", "email_2", "email_3", "email_4")):
        score += 1
    if not any(phrase in blob for phrase in ("hope you are well", "leading provider", "unlock growth")):
        score += 1
    flags = list(dict.fromkeys(flags))
    score = min(score, 10)
    send_ready = score >= 7 and not flags
    return score, flags, send_ready


SEVERE_EMAIL_FLAGS = {
    "email_1_missing_specific_signal",
    "email_1_missing_problem_statement",
    "email_1_missing_mechanism_statement",
    "email_1_missing_tiny_cta",
    "email_1_contains_internal_signal_language",
    "email_contains_internal_signal_language",
    "email_contains_hia_batch_wording",
    "email_1_too_generic",
    "email_1_missing_clinic_profile",
    "email_2_missing_funding_claim_line",
    "email_2_not_funding_only",
    "hia_pricing_missing_endpoint_caveat",
    "hia_pricing_exact_price_without_small_clinic_context",
    "hia_pricing_percentage_missing_caveat",
    "hia_pricing_group_exact_price_claim",
    "hia_pricing_forbidden_funding_claim",
    "non_hia_pricing_claim",
    "generic_inbox_wrong_greeting",
    "cyber_essentials_equals_pdpa_compliance",
    "cyber_essentials_equals_hia_compliance",
    "not_ready_has_email_body",
}


def severe_flags(flags: list[str]) -> list[str]:
    return [
        flag
        for flag in flags
        if flag in SEVERE_EMAIL_FLAGS
        or flag.startswith("forbidden_phrase:")
        or flag.startswith("style_banned_phrase:")
        or flag in {"unverified_exact_percentage", "unsafe_hia_deadline_claim"}
    ]


def automation_decision_for(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    copy_brief: dict[str, Any],
    emails: dict[str, Any],
    score: int,
    flags: list[str],
    enrichment_score: int,
    enrichment_flags: list[str],
    copy_score: int,
    copy_flags: list[str],
) -> tuple[str, str, list[str], bool]:
    can_send, suppress_reason = can_contact(row)
    if not can_send:
        return "suppressed", suppress_reason, [suppress_reason], False
    mode = contact_send_mode(row)
    identity_confidence = contact_identity_confidence(row)
    if row.get("copy_qa_mode"):
        return "draft_only_review", "copy_qa_mode", ["copy_qa_mode"], False
    if classification.get("pressure_type") == "not_ready":
        attempt_count = int(
            row.get("enrichment_attempt_count")
            or row.get("public_enrichment_attempt_count")
            or row.get("attempt_count")
            or 0
        )
        healthcare_hint = (
            classification.get("entity_type_guess") in {"clinic", "healthcare_provider"}
            or classification.get("hia_service_type_guess") not in {"", "unknown", None}
            or classification.get("data_type_signal") in {"patient_data", "health_information"}
        )
        if attempt_count <= 1:
            blockers = ["pressure_type_not_ready", "retry_deeper_healthcare_pages"] if healthcare_hint else ["pressure_type_not_ready"]
            reason = "healthcare_evidence_retry_once" if healthcare_hint else "weak_enrichment_retry_once"
            return "retry_enrichment_once", reason, blockers, False
        return "auto_skipped", "weak_hia_and_pdpa_evidence", ["pressure_type_not_ready"], False
    blocking_enrichment = blocking_enrichment_flags(enrichment_flags, classification, enrichment_score)
    blocking_copy = blocking_copy_brief_flags(copy_flags, classification, copy_brief)
    blockers = list(dict.fromkeys(severe_flags(flags) + blocking_enrichment + blocking_copy))
    if "no_concrete_company_observation" in blockers:
        return "auto_skipped", "no_concrete_company_observation", blockers, False
    if enrichment_score < 7:
        attempt_count = int(row.get("enrichment_attempt_count") or row.get("public_enrichment_attempt_count") or 0)
        if attempt_count <= 0:
            return "retry_enrichment_once", "weak_enrichment_retry_once", blockers or ["weak_enrichment"], False
        return "auto_skipped", "weak_enrichment_after_retry", blockers or ["weak_enrichment"], False
    if copy_score < 7:
        return "auto_skipped", "copy_brief_not_safe", blockers or ["weak_copy_brief"], False
    if blockers:
        return "auto_skipped", "copy_failed_after_llm_and_deterministic_fallback", blockers, False
    source_urls_text = compact(row.get("source_urls"))
    contact_review_reason = contact_provenance_review_reason(row, mode)
    if contact_review_reason:
        return "draft_only_review", contact_review_reason, [contact_review_reason], False
    thin_content = bool(source_urls_text) and len(compact(row.get("website_content"))) < 500
    thin_sources = bool(source_urls_text) and len(source_urls_text) < 60
    if (thin_content or thin_sources) and classification.get("classification_confidence") != "high":
        return "draft_only_review", "thin_classification_evidence", ["thin_classification_evidence"], False
    if any(not compact((emails.get(key) or {}).get("body")) for key in ACTIVE_EMAIL_KEYS):
        return "auto_skipped", "missing_email_body", ["missing_email_body"], False
    if score < 7:
        return "auto_skipped", "email_quality_gate_failed", flags or ["email_quality_gate_failed"], False
    if (copy_brief.get("funding_followup_mode") or copy_brief.get("email_2_mode") or copy_brief.get("email_3_mode")) == "value_fallback":
        reason = "funding_claim_not_safe_used_value_fallback"
    else:
        reason = "auto_send_all_gates_passed"
    return "auto_send_eligible", reason, [], score >= 7


def infer_decision_maker_role(row: dict[str, Any]) -> str:
    title = compact(row.get("selected_contact_title") or row.get("selected_contact_role")).lower()
    if "founder" in title:
        return "founder"
    if "owner" in title:
        return "owner"
    if "doctor" in title or "dr " in title:
        return "doctor"
    if "clinic manager" in title:
        return "clinic_manager"
    if "operation" in title:
        return "operations"
    if "dpo" in title or "data protection" in title:
        return "dpo"
    if "compliance" in title:
        return "compliance"
    if "it" in title or "technology" in title:
        return "it"
    if "hr" in title or "human resource" in title:
        return "hr"
    if "director" in title:
        return "director"
    if "executive director" in title:
        return "executive_director"
    return "unknown"


def plan_outreach(row: dict[str, Any], programmes: list[Any] | None = None) -> OutreachPlan:
    row = add_preclassification_company_context(row)
    classification = classify_row(row)
    funding = match_programmes({**row, **classification}, programmes=programmes)
    copy_brief = build_copy_brief(row, classification, funding)
    copy_brief = apply_company_context_search(row, classification, copy_brief)
    mode = email_3_mode_for(funding, copy_brief, classification)
    copy_brief["email_2_mode"] = mode
    copy_brief["funding_followup_mode"] = mode
    copy_brief["email_3_mode"] = mode
    emails = generate_email_sequence(row, classification, funding, copy_brief)
    emails, rewrite_flags = maybe_rewrite_email_1_with_llm(row, classification, funding, copy_brief, emails)
    score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
    flags = list(dict.fromkeys(flags + rewrite_flags))
    enrichment_score, enrichment_flags = enrichment_quality(row, classification, copy_brief)
    copy_score, copy_flags = copy_brief_quality(classification, copy_brief)
    advisory_flags = list(
        dict.fromkeys(
            advisory_enrichment_flags(enrichment_flags, classification, enrichment_score)
            + advisory_copy_brief_flags(copy_flags, classification, copy_brief)
            + (
                ["generic_or_low_identity_contact"]
                if contact_send_mode(row) == "generic_team" and contact_identity_confidence(row) in {"none", "low"}
                else []
            )
        )
    )
    decision, decision_reason, blockers, final_gate = automation_decision_for(
        row,
        classification,
        funding,
        copy_brief,
        emails,
        score,
        flags,
        enrichment_score,
        enrichment_flags,
        copy_score,
        copy_flags,
    )
    if row.get("enforce_contact_gates") and decision in {"suppressed", "auto_skipped", "retry_enrichment_once"}:
        previous_flags = list(flags)
        emails = empty_email_sequence()
        score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
        flags = list(dict.fromkeys(flags + rewrite_flags))
        for flag in previous_flags:
            if flag not in flags:
                flags.append(flag)
    send_ready = decision == "auto_send_eligible" and final_gate and not row.get("draft_only")
    if row.get("copy_qa_mode"):
        send_ready = False
        if "copy_qa_mode" not in flags:
            flags.append("copy_qa_mode")
    if decision == "auto_send_eligible":
        human_review_status = "not_required"
    elif decision == "draft_only_review":
        human_review_status = "ready_for_review"
    else:
        human_review_status = "not_ready"
    if classification["pressure_type"] == "not_ready" or not copy_brief_ready(classification, copy_brief):
        human_review_status = "not_ready"
    return OutreachPlan(
        row_id=row.get("Id") or row.get("id") or "",
        classification=classification,
        funding=funding,
        copy_brief=copy_brief,
        emails=emails,
        quality_score=score,
        quality_flags=flags,
        email_send_ready=send_ready,
        human_review_status=human_review_status,
        automation_decision=decision,
        automation_decision_reason=decision_reason,
        automation_blockers=blockers,
        automation_advisory_flags=advisory_flags,
        contact_send_mode=contact_send_mode(row),
        contact_identity_confidence=contact_identity_confidence(row),
        email_2_mode=copy_brief.get("email_2_mode", copy_brief.get("email_3_mode", "value_fallback")),
        funding_followup_mode=copy_brief.get("funding_followup_mode", copy_brief.get("email_2_mode", copy_brief.get("email_3_mode", "value_fallback"))),
        email_3_mode=copy_brief.get("email_3_mode", copy_brief.get("email_2_mode", "value_fallback")),
        enrichment_quality_score=enrichment_score,
        enrichment_quality_flags=enrichment_flags,
        copy_brief_quality_score=copy_score,
        copy_brief_quality_flags=copy_flags,
        severe_email_flags=severe_flags(flags),
        final_send_gate_passed=final_gate,
    )


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def email_rewrite_used(emails: dict[str, Any], key: str) -> bool:
    metadata = emails.get(f"llm_{key}_rewrite")
    return isinstance(metadata, dict) and bool(metadata.get("used"))


def build_noco_patch(row: dict[str, Any], plan: OutreachPlan) -> dict[str, Any]:
    c = plan.classification
    f = plan.funding
    b = plan.copy_brief
    e = plan.emails
    patch_emails = suppress_followup_emails(e)
    visible_quality_flags = plan.quality_flags
    visible_severe_flags = plan.severe_email_flags
    if (
        plan.automation_decision == "suppressed"
        and plan.automation_decision_reason == "suppressed_missing_validated_email"
    ):
        visible_quality_flags = []
        visible_severe_flags = []
    patch = {
        "Id": row.get("Id") or row.get("id"),
        "entity_type_guess": c["entity_type_guess"],
        "entity_type_confidence": c["entity_type_confidence"],
        "singapore_registered_guess": c["singapore_registered_guess"],
        "uen_guess": c["uen_guess"],
        "uen_source_url": c["uen_source_url"],
        "employee_count_guess": c["employee_count_guess"],
        "sme_likelihood": c["sme_likelihood"],
        "npo_likelihood": c["npo_likelihood"],
        "charity_or_social_service_likelihood": c["charity_or_social_service_likelihood"],
        "entity_evidence_json": json_dumps(c["entity_evidence_json"]),
        "pressure_type": c["pressure_type"],
        "primary_email_track": c.get("primary_email_track", ""),
        "secondary_email_track": c.get("secondary_email_track", ""),
        "regulatory_applicability": json_dumps(c.get("regulatory_applicability", [])),
        "classification_confidence": c.get("classification_confidence", ""),
        "classification_evidence_json": json_dumps(c.get("classification_evidence_json", {})),
        "classification_rejected_tracks_json": json_dumps(c.get("classification_rejected_tracks_json", [])),
        "pressure_reason": c["pressure_reason"],
        "outreach_trigger_signal": c["outreach_trigger_signal"],
        "outreach_trigger_source_url": c["outreach_trigger_source_url"],
        "outreach_trigger_confidence": c["outreach_trigger_confidence"],
        "data_type_signal": c["data_type_signal"],
        "problem_area": c["problem_area"],
        "problem_hypothesis": c["problem_hypothesis"],
        "value_asset_offer": c["value_asset_offer"],
        "hia_relevant": c["hia_relevant"],
        "hia_relevance_score": c["hia_relevance_score"],
        "hia_confidence": c["hia_confidence"],
        "hia_scope_reason": c["hia_scope_reason"],
        "hia_service_type_guess": c["hia_service_type_guess"],
        "hia_official_service_type": c.get("hia_official_service_type", ""),
        "hia_official_service_label": c.get("hia_official_service_label", ""),
        "hia_timeline_batch_guess": c["hia_timeline_batch_guess"],
        "hia_deadline_claim_safe": c["hia_deadline_claim_safe"],
        "hia_disclaimer_needed": c["hia_disclaimer_needed"],
        "hia_evidence_json": json_dumps({
            "evidence": c["evidence"],
            "scope_reason": c["hia_scope_reason"],
            "official_service_type": c.get("hia_official_service_type", ""),
            "official_service_label": c.get("hia_official_service_label", ""),
        }),
        "pdpa_relevant": c["pdpa_relevant"],
        "pdpa_reason": c["pdpa_reason"],
        "personal_data_intensity": c["personal_data_intensity"],
        "sensitive_data_likelihood": c["sensitive_data_likelihood"],
        "pdpa_safeguard_angle": c["pdpa_safeguard_angle"],
        "recommended_first_cert": c["recommended_first_cert"],
        "recommended_cert_path": c["recommended_cert_path"],
        "certification_reason": c["certification_reason"],
        "certification_fit_score": c["certification_fit_score"],
        "certification_evidence_json": json_dumps(c["certification_evidence_json"]),
        **f.to_patch_fields(),
        "funding_programs_matched_json": json_dumps(f.matched),
        "funding_programs_possible_json": json_dumps(f.possible),
        "funding_programs_not_applicable_json": json_dumps(f.not_applicable),
        "funding_source_urls_json": json_dumps(f.funding_source_urls),
        "company_profile_summary": b["company_profile_summary"],
        "business_model_guess": b["business_model_guess"],
        "primary_services_summary": b["primary_services_summary"],
        "locations_summary": b["locations_summary"],
        "team_structure_summary": b["team_structure_summary"],
        "personal_data_handled_guess": b["personal_data_handled_guess"],
        "sensitive_data_examples": b["sensitive_data_examples"],
        "data_systems_likely": b["data_systems_likely"],
        "data_flow_complexity": b["data_flow_complexity"],
        "data_risk_reason": b["data_risk_reason"],
        "regulatory_pressure_summary": b["regulatory_pressure_summary"],
        "hia_obligation_angle": b["hia_obligation_angle"],
        "pdpa_obligation_angle": b["pdpa_obligation_angle"],
        "customer_trust_angle": b["customer_trust_angle"],
        "deadline_or_timeline_angle": b["deadline_or_timeline_angle"],
        "funding_entity_basis": b["funding_entity_basis"],
        "funding_route_summary": b["funding_route_summary"],
        "funding_specificity_level": b["funding_specificity_level"],
        "funding_claim_safe": b["funding_claim_safe"],
        "funding_next_check_needed": b["funding_next_check_needed"],
        "clinic_size_guess": b.get("clinic_size_guess", ""),
        "clinic_size_confidence": b.get("clinic_size_confidence", ""),
        "endpoint_band_guess": b.get("endpoint_band_guess", ""),
        "endpoint_band_confidence": b.get("endpoint_band_confidence", ""),
        "pricing_email_2_mode": b.get("pricing_email_2_mode", ""),
        "pricing_claim_safe": b.get("pricing_claim_safe", False),
        "pricing_claim_line": b.get("pricing_claim_line", ""),
        "pricing_evidence_json": json_dumps(b.get("pricing_evidence_json", {})),
        "email_personalisation_signal": b["email_personalisation_signal"],
        "email_personalisation_quote": b["email_personalisation_quote"],
        "email_personalisation_source_url": b["email_personalisation_source_url"],
        "email_problem_statement": b["email_problem_statement"],
        "email_mechanism_statement": b["email_mechanism_statement"],
        "email_asset_offer": b["email_asset_offer"],
        "email_cta": b["email_cta"],
        "email_angle_reason": b["email_angle_reason"],
        "decision_maker_role_guess": infer_decision_maker_role(row),
        "outreach_variant": choose_variant(c),
        "email_1_subject": patch_emails["email_1"]["chosen_subject"],
        "email_1_body": patch_emails["email_1"]["body"],
        "email_1_llm_rewritten": email_rewrite_used(patch_emails, "email_1"),
        "email_2_subject": patch_emails["email_2"]["chosen_subject"],
        "email_2_body": patch_emails["email_2"]["body"],
        "email_2_llm_rewritten": email_rewrite_used(patch_emails, "email_2"),
        "email_3_subject": patch_emails["email_3"]["chosen_subject"],
        "email_3_body": patch_emails["email_3"]["body"],
        "email_4_subject": patch_emails["email_4"]["chosen_subject"],
        "email_4_body": patch_emails["email_4"]["body"],
        "email_sequence_json": json_dumps(patch_emails),
        "email_quality_score": plan.quality_score,
        "email_quality_flags": json_dumps(visible_quality_flags),
        "email_send_ready": plan.email_send_ready,
        "unsubscribe_status": compact(row.get("unsubscribe_status")) or "active",
        "sequence_status": "not_queued" if plan.email_send_ready else compact(row.get("sequence_status")),
        "send_status": "not_ready" if plan.email_send_ready else compact(row.get("send_status")),
        "instantly_sync_status": "not_synced" if plan.email_send_ready else compact(row.get("instantly_sync_status")),
        "human_review_status": plan.human_review_status,
        "automation_decision": plan.automation_decision,
        "automation_decision_reason": plan.automation_decision_reason,
        "automation_blockers_json": json_dumps(plan.automation_blockers),
        "automation_advisory_flags_json": json_dumps(plan.automation_advisory_flags),
        "contact_send_mode": plan.contact_send_mode,
        "contact_identity_confidence": plan.contact_identity_confidence,
        "email_2_mode": plan.email_2_mode,
        "funding_followup_mode": plan.funding_followup_mode,
        "email_3_mode": plan.email_3_mode,
        "enrichment_quality_score": plan.enrichment_quality_score,
        "enrichment_quality_flags": json_dumps(plan.enrichment_quality_flags),
        "copy_brief_quality_score": plan.copy_brief_quality_score,
        "copy_brief_quality_flags": json_dumps(plan.copy_brief_quality_flags),
        "severe_email_flags": json_dumps(visible_severe_flags),
        "final_send_gate_passed": plan.final_send_gate_passed,
    }
    return patch


def build_audit_report(row: dict[str, Any], plan: OutreachPlan | None = None, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    if plan is not None:
        classification = plan.classification
        funding = plan.funding
        emails = suppress_followup_emails(plan.emails)
        flags = plan.quality_flags
        email_blob = active_email_body_blob(emails)
        return {
            "row_id": plan.row_id,
            "company_name": compact(row.get("company_name")),
            "pressure_type": classification.get("pressure_type", ""),
            "hia_service_type_guess": classification.get("hia_service_type_guess", ""),
            "hia_timeline_batch_guess": classification.get("hia_timeline_batch_guess", ""),
            "funding_status": funding.funding_status,
            "automation_decision": plan.automation_decision,
            "automation_decision_reason": plan.automation_decision_reason,
            "automation_blockers_json": plan.automation_blockers,
            "automation_advisory_flags_json": plan.automation_advisory_flags,
            "contact_send_mode": plan.contact_send_mode,
            "contact_identity_confidence": plan.contact_identity_confidence,
            "email_2_mode": plan.email_2_mode,
            "funding_followup_mode": plan.funding_followup_mode,
            "email_3_mode": plan.email_3_mode,
            "clinic_size_guess": plan.copy_brief.get("clinic_size_guess", ""),
            "clinic_size_confidence": plan.copy_brief.get("clinic_size_confidence", ""),
            "endpoint_band_guess": plan.copy_brief.get("endpoint_band_guess", ""),
            "endpoint_band_confidence": plan.copy_brief.get("endpoint_band_confidence", ""),
            "pricing_email_2_mode": plan.copy_brief.get("pricing_email_2_mode", ""),
            "pricing_claim_safe": plan.copy_brief.get("pricing_claim_safe", False),
            "pricing_claim_line": plan.copy_brief.get("pricing_claim_line", ""),
            "pricing_evidence_json": plan.copy_brief.get("pricing_evidence_json", {}),
            "enrichment_quality_score": plan.enrichment_quality_score,
            "enrichment_quality_flags": plan.enrichment_quality_flags,
            "copy_brief_quality_score": plan.copy_brief_quality_score,
            "copy_brief_quality_flags": plan.copy_brief_quality_flags,
            "severe_email_flags": plan.severe_email_flags,
            "final_send_gate_passed": plan.final_send_gate_passed,
            "clinic_profile_guess": plan.copy_brief.get("clinic_profile_guess", ""),
            "clinic_profile_phrase": plan.copy_brief.get("clinic_profile_phrase", ""),
            "clinic_structure_guess": plan.copy_brief.get("clinic_structure_guess", ""),
            "clinic_structure_confidence": plan.copy_brief.get("clinic_structure_confidence", ""),
            "umbrella_or_group_guess": plan.copy_brief.get("umbrella_or_group_guess", ""),
            "primary_service_summary": plan.copy_brief.get("primary_service_summary", ""),
            "clinic_structure_evidence": plan.copy_brief.get("clinic_structure_evidence", []),
            "email_quality_flags": flags,
            "contains_hia_batch_wording": email_contains_hia_batch_wording(email_blob),
            "asset_offer_too_generic_for_segment": asset_offer_too_generic_for_segment(row, classification, plan.copy_brief),
            "email_3_generic_hia_diagnostic": email_2_generic_hia_diagnostic((emails.get("email_3") or {}).get("body", ""), classification),
            "email_1_subject": (emails.get("email_1") or {}).get("chosen_subject", ""),
            "email_1_body": (emails.get("email_1") or {}).get("body", ""),
            "email_1_llm_rewritten": email_rewrite_used(emails, "email_1"),
            "email_2_subject": (emails.get("email_2") or {}).get("chosen_subject", ""),
            "email_2_body": (emails.get("email_2") or {}).get("body", ""),
            "email_2_llm_rewritten": email_rewrite_used(emails, "email_2"),
            "email_3_subject": (emails.get("email_3") or {}).get("chosen_subject", ""),
            "email_3_body": (emails.get("email_3") or {}).get("body", ""),
            "email_4_subject": (emails.get("email_4") or {}).get("chosen_subject", ""),
            "email_4_body": (emails.get("email_4") or {}).get("body", ""),
        }
    patch = patch or {}
    flags_raw = patch.get("email_quality_flags") or "[]"
    try:
        flags = json.loads(flags_raw) if isinstance(flags_raw, str) else flags_raw
    except json.JSONDecodeError:
        flags = [str(flags_raw)]
    email_blob = "\n".join(str(patch.get(f"{key}_body", "")) for key in ACTIVE_EMAIL_KEYS)
    return {
        "row_id": patch.get("Id") or row.get("Id") or row.get("id"),
        "company_name": compact(row.get("company_name") or patch.get("company_name")),
        "pressure_type": patch.get("pressure_type", ""),
        "hia_service_type_guess": patch.get("hia_service_type_guess", ""),
        "hia_timeline_batch_guess": patch.get("hia_timeline_batch_guess", ""),
        "funding_status": patch.get("funding_status", ""),
        "automation_decision": patch.get("automation_decision", ""),
        "automation_decision_reason": patch.get("automation_decision_reason", ""),
        "automation_blockers_json": patch.get("automation_blockers_json", "[]"),
        "automation_advisory_flags_json": patch.get("automation_advisory_flags_json", "[]"),
        "contact_send_mode": patch.get("contact_send_mode", ""),
        "contact_identity_confidence": patch.get("contact_identity_confidence", ""),
        "email_2_mode": patch.get("email_2_mode", patch.get("email_3_mode", "")),
        "funding_followup_mode": patch.get("funding_followup_mode", patch.get("email_2_mode", patch.get("email_3_mode", ""))),
        "email_3_mode": patch.get("email_3_mode", ""),
        "clinic_size_guess": patch.get("clinic_size_guess", ""),
        "clinic_size_confidence": patch.get("clinic_size_confidence", ""),
        "endpoint_band_guess": patch.get("endpoint_band_guess", ""),
        "endpoint_band_confidence": patch.get("endpoint_band_confidence", ""),
        "pricing_email_2_mode": patch.get("pricing_email_2_mode", ""),
        "pricing_claim_safe": patch.get("pricing_claim_safe", False),
        "pricing_claim_line": patch.get("pricing_claim_line", ""),
        "pricing_evidence_json": patch.get("pricing_evidence_json", "{}"),
        "enrichment_quality_score": patch.get("enrichment_quality_score", 0),
        "enrichment_quality_flags": patch.get("enrichment_quality_flags", "[]"),
        "copy_brief_quality_score": patch.get("copy_brief_quality_score", 0),
        "copy_brief_quality_flags": patch.get("copy_brief_quality_flags", "[]"),
        "severe_email_flags": patch.get("severe_email_flags", "[]"),
        "final_send_gate_passed": patch.get("final_send_gate_passed", False),
        "clinic_profile_guess": patch.get("clinic_profile_guess", ""),
        "clinic_profile_phrase": patch.get("clinic_profile_phrase", ""),
        "clinic_structure_guess": patch.get("clinic_structure_guess", ""),
        "clinic_structure_confidence": patch.get("clinic_structure_confidence", ""),
        "umbrella_or_group_guess": patch.get("umbrella_or_group_guess", ""),
        "primary_service_summary": patch.get("primary_service_summary", ""),
        "clinic_structure_evidence": patch.get("clinic_structure_evidence", []),
        "email_quality_flags": flags,
        "contains_hia_batch_wording": email_contains_hia_batch_wording(email_blob),
        "asset_offer_too_generic_for_segment": "asset_offer_too_generic_for_segment" in flags,
        "email_3_generic_hia_diagnostic": "email_3_generic_hia_diagnostic" in flags,
        "email_1_subject": patch.get("email_1_subject", ""),
        "email_1_body": patch.get("email_1_body", ""),
        "email_1_llm_rewritten": patch.get("email_1_llm_rewritten", False),
        "email_2_subject": patch.get("email_2_subject", ""),
        "email_2_body": patch.get("email_2_body", ""),
        "email_2_llm_rewritten": patch.get("email_2_llm_rewritten", False),
        "email_3_subject": patch.get("email_3_subject", ""),
        "email_3_body": patch.get("email_3_body", ""),
        "email_4_subject": patch.get("email_4_subject", ""),
        "email_4_body": patch.get("email_4_body", ""),
    }


def plan_and_patch(row: dict[str, Any], programmes: list[Any] | None = None, copy_qa_mode: bool = False) -> dict[str, Any]:
    row = {
        **row,
        "copy_qa_mode": bool(copy_qa_mode or row.get("copy_qa_mode")),
        "enforce_contact_gates": True,
    }
    plan = plan_outreach(row, programmes=programmes)
    patch = build_noco_patch(row, plan)
    return {
        "ok": True,
        "row_id": plan.row_id,
        "send_ready": plan.email_send_ready,
        "human_review_status": plan.human_review_status,
        "automation_decision": plan.automation_decision,
        "automation_decision_reason": plan.automation_decision_reason,
        "automation_blockers": plan.automation_blockers,
        "automation_advisory_flags": plan.automation_advisory_flags,
        "openrouter_allowed": bool(row.get("openrouter_allowed")),
        "skip_openrouter": bool(row.get("skip_openrouter", False) or not sendable_email(row)),
        "audit_report": build_audit_report(row, plan=plan),
        "patch": patch,
        "record": plan.to_dict(),
    }


def patch_with_email_sequence(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch | dict[str, Any],
    emails: dict[str, Any],
    copy_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(funding, dict):
        funding = FundingMatch(
            funding_status=str(funding.get("funding_status") or "not_checked"),
            funding_relevant=bool(funding.get("funding_relevant", False)),
            primary_funding_program=str(funding.get("primary_funding_program") or ""),
            matched=list(funding.get("matched") or []),
            possible=list(funding.get("possible") or []),
            not_applicable=list(funding.get("not_applicable") or []),
            funding_eligibility_basis=str(funding.get("funding_eligibility_basis") or ""),
            funding_claim_line=str(funding.get("funding_claim_line") or ""),
            funding_cta_asset=str(funding.get("funding_cta_asset") or "funding_route_summary"),
            funding_confidence=str(funding.get("funding_confidence") or "low"),
            funding_last_checked_at=str(funding.get("funding_last_checked_at") or ""),
            funding_source_urls=list(funding.get("funding_source_urls") or []),
            funding_human_review_required=bool(funding.get("funding_human_review_required", True)),
            reason=str(funding.get("reason") or ""),
        )
    copy_brief = copy_brief or build_copy_brief(row, classification, funding)
    mode = email_3_mode_for(funding, copy_brief, classification)
    copy_brief["email_2_mode"] = mode
    copy_brief["funding_followup_mode"] = mode
    copy_brief["email_3_mode"] = mode
    emails = sanitize_email_sequence(emails)
    if classification.get("pressure_type") == "not_ready" or not copy_brief_ready(classification, copy_brief):
        emails = generate_email_sequence(row, classification, funding, copy_brief)
    if classification.get("pressure_type") != "not_ready":
        emails = enforce_funding_claim_email(row, funding, emails, classification, copy_brief)
    score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
    strategy_reject_flags = {
        "email_1_missing_specific_signal",
        "email_1_missing_problem_statement",
        "email_1_missing_mechanism_statement",
        "email_1_missing_tiny_cta",
        "email_1_contains_internal_signal_language",
        "email_contains_internal_signal_language",
        "email_contains_hia_batch_wording",
        "email_1_too_generic",
        "clinic_profile_missing_for_hia",
        "clinic_profile_too_generic",
        "email_1_missing_clinic_profile",
        "asset_offer_too_generic_for_segment",
        "hearing_care_missing_trigger",
        "lab_classification_ambiguous",
        "email_2_not_funding_only",
        "generic_inbox_wrong_greeting",
    }
    rejected_strategy_flags = [flag for flag in flags if flag in strategy_reject_flags]
    rejected_strategy_flags.extend(severe_flags(flags))
    rejected_strategy_flags = list(dict.fromkeys(rejected_strategy_flags))
    if rejected_strategy_flags and classification.get("pressure_type") != "not_ready":
        original_flags = list(flags)
        emails = generate_email_sequence(row, classification, funding, copy_brief)
        emails = enforce_funding_claim_email(row, funding, emails, classification, copy_brief)
        score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
        for flag in original_flags:
            if not flag.startswith("forbidden_phrase:"):
                continue
            if flag not in flags:
                flags.append(flag)
        if "llm_drift_fallback_used" not in flags:
            flags.append("llm_drift_fallback_used")
        for flag in rejected_strategy_flags:
            rejected = f"llm_email_strategy_rejected:{flag}"
            if rejected not in flags:
                flags.append(rejected)
    enrichment_score, enrichment_flags = enrichment_quality(row, classification, copy_brief)
    copy_score, copy_flags = copy_brief_quality(classification, copy_brief)
    advisory_flags = list(
        dict.fromkeys(
            advisory_enrichment_flags(enrichment_flags, classification, enrichment_score)
            + advisory_copy_brief_flags(copy_flags, classification, copy_brief)
        )
    )
    decision, decision_reason, blockers, final_gate = automation_decision_for(
        row,
        classification,
        funding,
        copy_brief,
        emails,
        score,
        flags,
        enrichment_score,
        enrichment_flags,
        copy_score,
        copy_flags,
    )
    if row.get("enforce_contact_gates") and decision in {"suppressed", "auto_skipped", "retry_enrichment_once"}:
        previous_flags = list(flags)
        emails = empty_email_sequence()
        score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
        for flag in previous_flags:
            if flag not in flags:
                flags.append(flag)
    send_ready = decision == "auto_send_eligible" and bool(row.get("send_mode")) and not row.get("draft_only")
    if row.get("copy_qa_mode"):
        send_ready = False
        if "copy_qa_mode" not in flags:
            flags.append("copy_qa_mode")
    plan = OutreachPlan(
        row_id=row.get("Id") or row.get("id") or "",
        classification=classification,
        funding=funding,
        copy_brief=copy_brief,
        emails=emails,
        quality_score=score,
        quality_flags=flags,
        email_send_ready=send_ready,
        human_review_status=(
            "not_required"
            if decision == "auto_send_eligible" and classification.get("pressure_type") != "not_ready"
            else "ready_for_review"
            if decision == "draft_only_review" and classification.get("pressure_type") != "not_ready"
            else "not_ready"
        ),
        automation_decision=decision,
        automation_decision_reason=decision_reason,
        automation_blockers=blockers,
        automation_advisory_flags=advisory_flags,
        contact_send_mode=contact_send_mode(row),
        contact_identity_confidence=contact_identity_confidence(row),
        email_2_mode=copy_brief.get("email_2_mode", copy_brief.get("email_3_mode", "value_fallback")),
        funding_followup_mode=copy_brief.get("funding_followup_mode", copy_brief.get("email_2_mode", copy_brief.get("email_3_mode", "value_fallback"))),
        email_3_mode=copy_brief.get("email_3_mode", copy_brief.get("email_2_mode", "value_fallback")),
        enrichment_quality_score=enrichment_score,
        enrichment_quality_flags=enrichment_flags,
        copy_brief_quality_score=copy_score,
        copy_brief_quality_flags=copy_flags,
        severe_email_flags=severe_flags(flags),
        final_send_gate_passed=final_gate,
    )
    return build_noco_patch(row, plan)
