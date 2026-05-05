from __future__ import annotations

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
- Email 2 gives a diagnostic tied to the same problem.
- Email 3 is funding-only and must use funding_claim_line.
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
HIA_BATCH_BY_SERVICE = {
    "GP_OMS": "Batch 1 - Sep 2027",
    "hospital": "Batch 1 - Sep 2027",
    "diagnostic": "Batch 1 - Sep 2027",
    "specialist_OMS": "Batch 2 - Sep 2028",
    "long_term_care": "Batch 2 - Sep 2028",
    "dental": "Batch 3 - Mar 2030",
    "retail_pharmacy": "Batch 3 - Mar 2030",
    "HIMS_provider": "Other CS/DS by Sep 2028",
    "NEHR_user": "Other CS/DS by Sep 2028",
}
NPO_TERMS = ("charity", "society", "mission", "foundation", "volunteer", "donation", "ncss", "ipc", "beneficiary")
SOCIAL_TERMS = ("resident", "beneficiary", "care", "nursing home", "community", "social service", "eldercare")
SPECIALIST_SERVICE_TERMS = (
    "oncology",
    "radiation",
    "endocrinology",
    "orthopaedic",
    "orthopedic",
    "digestive",
    "gastroenterology",
    "cardiology",
    "dermatology",
    "plastic surgery",
    "aesthetic",
    "surgery",
    "specialist",
)
DIAGNOSTIC_SERVICE_TERMS = (
    "diagnostic",
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
    "payment",
)
SENSITIVE_TERMS = ("patient", "health", "medical", "resident", "beneficiary", "student", "financial")


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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["funding"] = self.funding.to_dict()
        return data


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
    "hello",
    "info",
    "mail",
    "reception",
    "sales",
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


def email_greeting(row: dict[str, Any], company: str | None = None) -> str:
    name = compact(row.get("selected_contact_name"))
    if name and not is_generic_or_company_inbox(row):
        return f"Hi {name.split()[0]} -"
    company_name = compact(company or row.get("company_name"))
    if company_name:
        return f"Hi {company_name} team,"
    return "Hi team,"


def email_comma_greeting(row: dict[str, Any], company: str | None = None) -> str:
    name = compact(row.get("selected_contact_name"))
    if name and not is_generic_or_company_inbox(row):
        return f"Hi {name.split()[0]},"
    company_name = compact(company or row.get("company_name"))
    if company_name:
        return f"Hi {company_name} team,"
    return "Hi team,"


def trim_text(value: Any) -> str:
    return str(value or "").strip()


def lower_blob(row: dict[str, Any]) -> str:
    parts = [
        row.get("company_name", ""),
        row.get("company_homepage_name", ""),
        row.get("industry_guess", ""),
        row.get("website_content", ""),
        row.get("services_detected", ""),
        row.get("locations_detected", ""),
        row.get("leadership_or_team_signals", ""),
        row.get("contact_info_detected", ""),
        row.get("structured_data_detected", ""),
        row.get("notes", ""),
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


def confidence_from_score(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def infer_entity(row: dict[str, Any], text: str) -> dict[str, Any]:
    company = compact(row.get("company_name"))
    if "clinic" in company.lower() or company.lower().endswith("clinic"):
        return {
            "entity_type_guess": "clinic",
            "entity_type_confidence": "high",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if ("clinic" in text or "dental" in text) and not contains_any(text, NPO_TERMS):
        return {
            "entity_type_guess": "clinic",
            "entity_type_confidence": "high",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if contains_any(text, HEALTHCARE_TERMS) and not contains_any(text, NPO_TERMS):
        return {
            "entity_type_guess": "healthcare_provider",
            "entity_type_confidence": "medium",
            "sme_likelihood": "possible",
            "npo_likelihood": "unlikely",
            "charity_or_social_service_likelihood": "unlikely",
        }
    if "sree narayana mission" in text or contains_any(text, NPO_TERMS + SOCIAL_TERMS):
        if "charity" in text or "ipc" in text:
            entity = "charity"
        elif contains_any(text, SOCIAL_TERMS):
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
    if "dental" in text or "dentist" in text:
        service = "dental"
    elif "ambulatory surgical" in text or "day surgery" in text:
        service = "unknown"
        batch_override = "Batch 3 - Mar 2030"
    elif "assisted reproduction" in text or "ivf" in text or "fertility" in text:
        service = "unknown"
        batch_override = "Batch 3 - Mar 2030"
    elif "pharmacy" in text:
        service = "retail_pharmacy"
    elif "hearing" in text or "audiology" in text:
        service = "hearing_care"
    elif "renal dialysis" in text or "dialysis" in text:
        service = "unknown"
        batch_override = "Batch 2 - Sep 2028"
    elif contains_any(text, LONG_TERM_CARE_TERMS):
        service = "long_term_care"
    elif contains_any(text, DIAGNOSTIC_SERVICE_TERMS):
        service = "diagnostic"
    elif contains_any(text, SPECIALIST_SERVICE_TERMS):
        service = "specialist_OMS"
    elif "hims" in text or "health information management system" in text:
        service = "HIMS_provider"
    elif "nehr" in text:
        service = "NEHR_user"
    elif "physio" in text or "physiotherapy" in text or "psychology" in text or "psychologist" in text or "mental health" in text or "therapy" in text:
        service = "allied_health"
    elif "clinic" in text or "doctor" in text or "medical" in text:
        service = "GP_OMS"
    else:
        service = "unknown"
    if service in HIA_BATCH_BY_SERVICE or batch_override:
        score = max(score + 24, 45)
    score = min(score, 100)
    confidence = confidence_from_score(score)
    batch = batch_override or HIA_BATCH_BY_SERVICE.get(service, "unknown")
    hia_relevant = score >= 45 or (service in HIA_BATCH_BY_SERVICE and score >= 36)
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
        "hia_timeline_batch_guess": batch,
        "hia_deadline_claim_safe": batch != "unknown" and confidence in {"medium", "high"},
        "hia_disclaimer_needed": True,
    }


def hia_llm_enabled() -> bool:
    if os.getenv("OUTREACH_HIA_LLM_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def should_review_hia_with_llm(row: dict[str, Any], text: str, hia: dict[str, Any]) -> bool:
    if hia.get("hia_confidence") == "high":
        return False
    if row.get("hia_llm_review"):
        return True
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
- If it is clearly a clinic, GP, outpatient medical provider, dental clinic, retail pharmacy, diagnostic/lab/radiology provider, hospital, nursing home, renal dialysis provider, HIMS provider, or NEHR user, set hia_relevant true.
- If it is only wellness, beauty, product retail, training, media, or generic care language without healthcare service evidence, set hia_relevant false.
- For hearing-care or audiology, set hia_relevant true only when the evidence shows hearing tests, appointments, clinical care, audiologists, or patient/customer health records.
- Return a service type only when evidence supports it.
- Use medium/high confidence only when evidence quotes are concrete.

Return:
{
  "hia_relevant": false,
  "hia_confidence": "low|medium|high",
  "hia_service_type_guess": "GP_OMS|specialist_OMS|dental|retail_pharmacy|diagnostic|hospital|allied_health|hearing_care|long_term_care|HIMS_provider|NEHR_user|unknown",
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
        response.raise_for_status()
        choices = response.json().get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(content).strip(), flags=re.IGNORECASE)
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
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
    relevant = bool(review.get("hia_relevant"))
    batch = HIA_BATCH_BY_SERVICE.get(service, "unknown")
    reason = compact(review.get("hia_scope_reason")) or hia.get("hia_scope_reason", "")
    return {
        **hia,
        "hia_relevant": relevant,
        "hia_relevance_score": max(int(hia.get("hia_relevance_score") or 0), 80 if confidence == "high" and relevant else 55 if relevant else 20),
        "hia_confidence": confidence,
        "hia_scope_reason": f"LLM ambiguous-HIA review: {reason}",
        "hia_service_type_guess": service,
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


def business_model_trust_signal(text: str) -> str:
    for term in B2B_TERMS:
        if term in text:
            return term
    return "clients or business partners"


def healthcare_segment(classification: dict[str, Any]) -> str:
    service = compact(classification.get("hia_service_type_guess")).replace("_", " ")
    entity = compact(classification.get("entity_type_guess")).replace("_", " ")
    if service and service != "unknown":
        return service
    if entity and entity != "unknown":
        return entity
    return "healthcare provider"


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    text = lower_blob(row)
    entity = infer_entity(row, text)
    hia = infer_hia(row, text)
    hia_review = row.get("hia_llm_review")
    if not hia_review and hia_llm_enabled() and should_review_hia_with_llm(row, text, hia):
        hia_review = call_hia_llm_review(row, hia)
    if should_review_hia_with_llm(row, text, hia):
        hia = apply_hia_llm_review(hia, hia_review)
    data_type, personal_intensity, sensitive_likelihood = infer_data_signal(text, hia, entity)
    dpo_owner = is_data_protection_owner(row)
    trust_signal = business_model_trust_signal(text)

    if hia["hia_relevant"] and hia["hia_confidence"] in {"medium", "high"}:
        pressure_type = "hia_regulatory"
        problem_area = "hia_readiness"
        value_asset = "hia_readiness_map"
        trigger = "HIA timelines start from 2027, and the website indicates healthcare or patient-data activity."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Start with HIA readiness mapping, then use Cyber Essentials as a practical cybersecurity/data-security baseline."
    elif dpo_owner and personal_intensity in {"medium", "high"}:
        pressure_type = "pdpa_safeguards"
        problem_area = "evidence_collection"
        value_asset = "security_evidence_checklist"
        trigger = "The selected contact appears to own data-protection, compliance, operations, admin or HR evidence across teams."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials to structure security evidence across IT, HR, vendors and operations; consider DPE/DPTM only when broader data-protection governance evidence supports it."
    elif contains_any(text, B2B_TERMS):
        pressure_type = "customer_trust"
        problem_area = "evidence_collection"
        value_asset = "security_evidence_checklist"
        trigger = f"Customers and partners may ask for reusable security evidence because the website indicates {trust_signal} activity."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials as the first reusable security-evidence baseline."
    elif personal_intensity in {"medium", "high"}:
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
    if hia["hia_confidence"] == "high":
        trigger_confidence = "high"

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
        "campaign_track": "dpo_evidence" if dpo_owner and pressure_type == "pdpa_safeguards" else pressure_type,
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
        "certification_evidence_json": {"pressure_type": pressure_type, "data_type_signal": data_type},
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


def first_name_from_contact(row: dict[str, Any]) -> str:
    name = compact(row.get("selected_contact_name"))
    if not name:
        return ""
    return name.split()[0]


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


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def tiny_cta(asset: str) -> str:
    if "map" in asset:
        return "Want the map?"
    if "route" in asset or "funding" in asset:
        return "Should I send the route summary?"
    return "Worth sending the checklist?"


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


def concrete_service_cues(row: dict[str, Any], text: str) -> list[str]:
    name_text = f"{row.get('company_name') or ''} {row.get('company_homepage_name') or ''}".lower()
    haystack = f"{name_text} {text}"
    cues: list[str] = []

    def add(cue: str) -> None:
        if cue and cue.lower() not in {existing.lower() for existing in cues}:
            cues.append(cue)

    if contains_any(haystack, LONG_TERM_CARE_TERMS):
        if "hospice" in haystack or "palliative" in haystack:
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
        if "oncology" in haystack or "radiation" in haystack:
            add("radiation/oncology specialist-care signals")
        elif "digestive" in haystack or "gastroenterology" in haystack:
            add("digestive/gastroenterology specialist-care signals")
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
    profile = f"{company} appears to be a {business_model.replace('_', ' ')} organisation with public signals around {primary_services} in {location_summary}."

    if pressure == "hia_regulatory":
        service_type = classification.get("hia_service_type_guess")
        personal_data = "patient and health information handled through enquiries, appointments, care records and clinic operations."
        sensitive_examples = "patient identity details, appointment information, health information, treatment notes and staff access records."
        if service_type == "hearing_care" or "hearing" in text:
            systems = "appointments, hearing tests, device-related records, staff access, vendor systems, backups and incident-reporting steps."
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
        elif service_type == "specialist_OMS" and ("oncology" in text or "radiation" in text):
            systems = "specialist appointments, oncology/radiation treatment records, patient reports, vendor systems, backups and incident-reporting steps."
        elif service_type == "specialist_OMS" and ("digestive" in text or "gastroenterology" in text):
            systems = "specialist appointments, digestive/gastroenterology records, patient reports, vendor systems, backups and incident-reporting steps."
        else:
            systems = "appointment forms, patient records, clinic email, vendor systems, backups and incident-reporting steps."
        complexity = "medium" if entity == "clinic" else "high"
        regulatory = "HIA creates an external healthcare regulatory-readiness pressure, with phased timelines starting from 2027."
        hia_angle = "Map health information access, cybersecurity, data-security, vendor, backup and incident-response duties before the HIA window."
        pdpa_angle = "PDPA safeguards still matter, but the primary outreach angle is HIA readiness for health information."
        trust_angle = "Patients and partners expect clear evidence that clinic systems and health information access are controlled."
        timeline = "HIA timelines start from 2027; use specific batch dates only when the row has safe deadline evidence."
        asset = "HIA readiness map"
        cta = "Want the HIA readiness map?"
        if service_type == "hearing_care" or "hearing" in text:
            problem = f"{company} needs to show where appointment, test and device-related records sit, who can access them, which vendors touch them, how backups work and who reports an incident."
        elif service_type == "long_term_care" or contains_any(text, LONG_TERM_CARE_TERMS):
            problem = f"{company} needs to show where patient, resident, family, volunteer and staff data sits, who can access it, which vendors touch it, how backups work and who reports an incident."
        elif service_type == "allied_health" and ("physio" in text or "physiotherapy" in text):
            problem = f"{company} needs to show where appointment, treatment and exercise-plan records sit, who can access them, which vendors touch them, how backups work and who reports an incident."
        elif service_type == "allied_health" and ("psychology" in text or "psychologist" in text or "mental health" in text):
            problem = f"{company} needs to show where appointment, assessment and case-note records sit, who can access them, which vendors touch them, how backups work and who reports an incident."
        elif service_type == "diagnostic":
            problem = f"{company} needs to show where screening, diagnostic and patient-report records sit, who can access them, which vendors touch them, how backups work and who reports an incident."
        elif service_type == "specialist_OMS" and ("oncology" in text or "radiation" in text):
            problem = f"{company} needs to show where oncology/radiation treatment records sit, who can access them, which vendors touch them, how backups work and who reports an incident."
        elif service_type == "specialist_OMS" and ("digestive" in text or "gastroenterology" in text):
            problem = f"{company} needs to show where digestive/gastroenterology patient records sit, who can access them, which vendors touch them, how backups work and who reports an incident."
        else:
            problem = f"{company} needs to show where health information sits, who can access it, which vendors touch it, how backups work and who reports an incident."
        mechanism = "Cyber Essentials is a practical first baseline before deeper HIA work."
        signal_parts = [public_signals["service"]]
        if public_signals["team"]:
            signal_parts.append(public_signals["team"])
        if not any(compact(part) for part in signal_parts):
            if classification.get("hia_service_type_guess") == "hearing_care" or "hearing" in text:
                signal_parts.append("hearing-care and appointment/test/device record signals")
            else:
                signal_parts.append("clinic service and patient-care signals")
        signal = f"{company} shows {sentence_join(signal_parts)}; HIA timelines starting from 2027 make health-information readiness the clearest pressure."
    elif pressure == "customer_trust":
        personal_data = "customer, partner, employee and business-contact data handled through service delivery and client operations."
        sensitive_examples = "customer contact data, business partner data, employee access records and client security-questionnaire evidence."
        systems = "CRM, email, file shares, access lists, vendor tools, backups and incident contacts."
        complexity = "medium"
        regulatory = "PDPA safeguards matter, but customer/procurement proof is the stronger buying pressure."
        hia_angle = "No HIA angle should be used unless healthcare evidence appears."
        pdpa_angle = "Cyber Essentials supports the security-safeguards side of PDPA readiness without claiming full PDPA compliance."
        trust_angle = "Customers may ask for reusable security evidence around access control, patching, backups, malware protection and incident response."
        timeline = "No external HIA deadline was identified; urgency comes from customer evidence and procurement reviews."
        asset = "security evidence checklist"
        cta = "Worth sending the evidence checklist?"
        problem = f"{company} likely needs reusable answers when customers ask how their data and systems are protected; security questions usually come down to proof."
        mechanism = "Cyber Essentials creates a recognised baseline for access, updates, backups, malware protection and incident-response evidence."
        signal = f"{company} shows {public_signals['service']} where customer security questions and reusable security evidence can reduce sales or procurement friction."
    elif pressure == "pdpa_safeguards":
        if classification.get("campaign_track") == "dpo_evidence":
            personal_data = f"{data_type} handled across IT, HR, vendors and operations."
            sensitive_examples = f"{data_type}, employee data, access records, vendor records and incident evidence."
            systems = "HR/admin systems, email, file shares, vendor tools, access lists, backups and incident contacts."
            asset = "evidence checklist"
            cta = "Worth sending the evidence checklist?"
            signal = f"{company} has a data-protection or operations contact and likely data spread across HR/admin systems, vendors and staff workflows."
            problem = f"For DPOs and ops teams at {company}, the hard part is often proving who has access, where data sits, how vendors are managed, and what happens during an incident."
        elif entity in {"npo", "charity", "social_service"}:
            personal_data = "resident, beneficiary, volunteer, donor and staff data handled through care and community operations."
            sensitive_examples = "resident details, beneficiary records, volunteer data, donor contacts, staff records and care-service notes."
            systems = "case or resident records, volunteer lists, donor/contact databases, email, file shares, backups and incident contacts."
            asset = "care-organisation checklist"
            cta = "Worth sending the care-organisation checklist?"
            signal = f"{company} appears to operate in a care/community-service setting handling resident, beneficiary, volunteer and staff data."
            problem = f"{company} likely needs to show who owns resident, beneficiary, volunteer and staff data systems, who can access them, how backups work, and what happens during an incident."
        else:
            personal_data = f"{data_type} handled through enquiries, service delivery, staff operations and vendor tools."
            sensitive_examples = f"{data_type}, employee data, contact records and service history."
            systems = "web forms, email, CRM or spreadsheets, file shares, vendor tools, backups and incident contacts."
            asset = "PDPA safeguards checklist"
            cta = "Worth sending the safeguards checklist?"
            signal = f"{company} shows {public_signals['service']} where {data_type} may sit across staff, vendors and operational systems."
            problem = f"{company} likely needs to show who owns personal-data systems, who can access them, how backups and updates work, and what happens during an incident."
        complexity = "medium" if classification.get("personal_data_intensity") in {"medium", "high"} else "unknown"
        regulatory = "PDPA requires reasonable protection/security arrangements for personal data."
        hia_angle = "Do not lead with HIA unless healthcare evidence is medium or high confidence."
        pdpa_angle = "Cyber Essentials supports the security-safeguards side of PDPA readiness by organising evidence around assets, access, malware protection, patching, backups and incident response."
        trust_angle = "Clear safeguard evidence also helps customers, donors, partners or staff trust how data is handled."
        timeline = "No specific external deadline was identified; urgency comes from being able to evidence reasonable safeguards."
        mechanism = "Cyber Essentials supports the security-safeguards side of PDPA readiness by turning those questions into a practical baseline and evidence set."
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

    funding_safe = funding.funding_status == "verified_match" and funding.funding_confidence == "high"
    funding_level = "high" if funding_safe else "medium" if funding.funding_status == "possible_match" else "low"
    return {
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
        "email_personalisation_signal": signal,
        "email_personalisation_quote": compact(row.get("company_homepage_name") or row.get("website_content"))[:220],
        "email_personalisation_source_url": source_url,
        "email_problem_statement": problem,
        "email_mechanism_statement": mechanism,
        "email_asset_offer": asset,
        "email_cta": cta,
        "email_angle_reason": classification.get("pressure_reason") or classification.get("problem_hypothesis") or "",
    }


def generate_email_sequence(
    row: dict[str, Any],
    classification: dict[str, Any],
    funding: FundingMatch,
    copy_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    copy_brief = copy_brief or build_copy_brief(row, classification, funding)
    company = compact(row.get("company_name") or "your organisation")
    greeting = email_greeting(row, company)
    comma_greeting = email_comma_greeting(row, company)
    if not copy_brief_ready(classification, copy_brief):
        return empty_email_sequence()
    trigger = compact(copy_brief["email_personalisation_signal"])
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
        lead = "With HIA timelines starting from 2027"
        if classification.get("hia_deadline_claim_safe") and classification.get("hia_timeline_batch_guess") != "unknown":
            lead = f"With the {classification['hia_timeline_batch_guess']} HIA window"
        segment = healthcare_segment(classification)
        email1_subject = "HIA readiness"
        email2_subject = "Re: HIA readiness"
        email1_body = f"{greeting} noticed {company} appears to be a {segment}.\n\n{lead}, healthcare providers may need to show stronger readiness around health information access, cybersecurity, data security and incident response.\n\nCyber Essentials is a practical first baseline before deeper HIA work.\n\nWorth sending a simple HIA readiness checklist?\n\nBest,\nSK\nRAYN Secure"
        email2_body = f"One useful check: can {company} clearly show where health information sits, who can access it, which vendors touch it, how backups work, and who reports an incident?\n\nThose are the areas that usually become messy before HIA deadlines.\n\nWant the quick readiness map?"
    elif classification["pressure_type"] == "customer_trust":
        signal = business_model_trust_signal(lower_blob(row))
        email1_subject = "security evidence"
        email2_subject = "Re: security evidence"
        email1_body = f"{greeting} noticed {company} works with {signal}.\n\nWhen clients share personal or business data, security questions usually come down to proof: access control, backups, patching, malware protection and incident response.\n\nCyber Essentials gives a recognised baseline for that evidence.\n\nWorth sending a sample evidence checklist?\n\nBest,\nSK\nRAYN Secure"
        email2_body = f"A practical diagnostic is to list the security questions clients already ask, then map each one to current evidence. Missing items usually point to access control, patching, backup or incident-response gaps.\n\nWant the simple evidence checklist?"
    elif classification.get("campaign_track") == "dpo_evidence":
        data = classification["data_type_signal"].replace("_", " ")
        email1_subject = "data protection evidence"
        email2_subject = "Re: data protection evidence"
        email1_body = f"{greeting} noticed {company} appears to handle {data}.\n\nFor DPOs and ops teams, the hard part is often not the policy. It is proving the safeguards: who has access, where data sits, how vendors are managed, and what happens during an incident.\n\nCyber Essentials helps structure the security baseline.\n\nWorth sending the evidence checklist?\n\nBest,\nSK\nRAYN Secure"
        email2_body = f"A quick self-check: can each system holding personal data be mapped to an owner, access list, vendor, backup process and incident contact?\n\nIf not, that is usually where the evidence work starts.\n\nWant the simple data-safeguards template?"
    else:
        data = classification["data_type_signal"].replace("_", " ")
        email1_subject = "PDPA security safeguards"
        email2_subject = "Re: PDPA security safeguards"
        email1_body = f"{greeting} noticed {company} appears to handle {data}.\n\nFor organisations collecting, using or disclosing personal data, the practical question is whether security safeguards can be shown clearly: access, updates, backups, malware protection and incident response.\n\nCyber Essentials supports the security-safeguards side of PDPA readiness.\n\nWorth sending the 5-point readiness checklist?\n\nBest,\nSK\nRAYN Secure"
        email2_body = f"A quick self-check: can every system holding customer, employee or partner data be mapped to an owner, access list, backup, update process and incident contact?\n\nIf not, that is usually where Cyber Essentials prep starts.\n\nWant the simple data-safeguards template?"

    if classification["pressure_type"] != "not_ready":
        email1_body = f"{greeting} {trigger}\n\n{problem}\n\n{mechanism}\n\n{cta}\n\nBest,\nSK\nRAYN Secure"
        if classification["pressure_type"] == "hia_regulatory":
            service_type = classification.get("hia_service_type_guess")
            if service_type == "hearing_care":
                diagnostic = f"Can {company} show where appointment, test and device-related records sit, who can access them, which vendors touch them, how backups work, and who reports an incident?"
            elif service_type == "long_term_care":
                diagnostic = f"Can {company} map patient, resident, family, volunteer and staff data to an owner, access list, vendor, backup and incident contact?"
            elif service_type == "allied_health" and ("physio" in systems.lower() or "exercise-plan" in systems.lower()):
                diagnostic = f"Can {company} show where appointment, treatment and exercise-plan records sit, who can access them, which vendors touch them, how backups work, and who reports an incident?"
            elif service_type == "allied_health" and ("psychology" in trigger.lower() or "case-note" in systems.lower()):
                diagnostic = f"Can {company} show where appointment, assessment and case-note records sit, who can access them, which vendors touch them, how backups work, and who reports an incident?"
            elif service_type == "diagnostic":
                diagnostic = f"Can {company} show where screening, diagnostic and patient-report records sit, who can access them, which vendors touch them, how backups work, and who reports an incident?"
            elif service_type == "specialist_OMS" and ("oncology" in systems.lower() or "radiation" in systems.lower()):
                diagnostic = f"Can {company} show where oncology/radiation treatment records sit, who can access them, which vendors touch them, how backups work, and who reports an incident?"
            elif service_type == "specialist_OMS" and ("digestive" in systems.lower() or "gastroenterology" in systems.lower()):
                diagnostic = f"Can {company} show where digestive/gastroenterology patient records sit, who can access them, which vendors touch them, how backups work, and who reports an incident?"
            else:
                diagnostic = f"Can {company} show where health information sits, who can access it, which vendors touch it, how backups work, and who reports an incident?"
        elif classification.get("entity_type_guess") in {"npo", "charity", "social_service"}:
            diagnostic = f"Can {company} map resident, beneficiary, volunteer and staff data to an owner, access list, backup and incident contact?"
        elif classification["pressure_type"] == "customer_trust":
            diagnostic = "Can each common customer security question be mapped to current evidence for access, backups, patching, malware protection and incident response?"
        else:
            diagnostic = "Can each system holding personal data be mapped to an owner, access list, backup, update process and incident contact?"
        email2_body = f"A practical diagnostic: {diagnostic}\n\nIf any of those are unclear, that is usually where readiness work starts.\n\n{cta}"
        funding_line = funding.funding_claim_line or "Funding route needs human review before use."
        email3_subject = "HIA / cyber funding" if classification["pressure_type"] == "hia_regulatory" else "Cyber Essentials funding"
        caveat = "" if "subject to programme confirmation" in funding_line.lower() else "\n\nThis is subject to programme confirmation."
        email3_body = f"{comma_greeting}\n\n{funding_line}{caveat}\n\nShould I send the route summary?\n\nBest,\nSK\nRAYN Secure"
        email4_body = f"{comma_greeting}\n\nShould I close the loop, or would the {asset} still be useful?\n\nBest,\nSK\nRAYN Secure"
    else:
        email3_subject = "not ready"

    emails = {
        "email_1": {
            "subject_options": [email1_subject, "readiness checklist"],
            "chosen_subject": email1_subject,
            "body": email1_body,
        },
        "email_2": {
            "subject_options": [email2_subject, "quick diagnostic"],
            "chosen_subject": email2_subject,
            "body": email2_body,
        },
        "email_3": {
            "subject_options": [email3_subject, "funding route"],
            "chosen_subject": email3_subject,
            "body": email3_body,
        },
        "email_4": {
            "subject_options": ["close the loop?", "checklist?"],
            "chosen_subject": "close the loop?",
            "body": email4_body,
        },
        "evidence_used": [trigger],
        "claims_avoided": [
            "No guaranteed funding.",
            "No claim that Cyber Essentials equals PDPA compliance.",
            "No claim that Cyber Essentials equals HIA compliance.",
        ],
        "quality_notes": [],
    }
    for key in ("email_1", "email_2", "email_3", "email_4"):
        emails[key]["word_count"] = word_count(emails[key]["body"])
    return emails


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
        emails[key] = {
            "subject_options": [compact(option) for option in subject_options if compact(option)],
            "chosen_subject": subject,
            "body": body,
            "word_count": word_count(body),
        }
    return emails


def enforce_funding_claim_email(row: dict[str, Any], funding: FundingMatch, emails: dict[str, Any]) -> dict[str, Any]:
    claim = trim_text(funding.funding_claim_line)
    if not claim:
        return emails
    email3 = emails.get("email_3") or {}
    existing_body = trim_text(email3.get("body"))
    caveat_count = existing_body.lower().count("subject to programme confirmation")
    if claim.lower() in existing_body.lower() and funding_only_email_3(existing_body, claim) and caveat_count <= 1:
        return emails
    greeting = email_comma_greeting(row)
    subject = compact(email3.get("chosen_subject")) or "funding route"
    caveat = "" if "subject to programme confirmation" in claim.lower() else "\n\nThis is subject to programme confirmation."
    body = f"{greeting}\n\n{claim}{caveat}\n\nShould I send the route summary?\n\nBest,\nSK\nRAYN Secure"
    emails = {**emails}
    emails["email_3"] = {
        "subject_options": list(email3.get("subject_options") or [subject]),
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
        "private company",
        "handles customer data",
    )
    concrete_terms = (
        "clinic service",
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


def funding_only_email_3(body: str, claim: str) -> bool:
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


def email_2_is_diagnostic(body: str, copy_brief: dict[str, Any], classification: dict[str, Any]) -> bool:
    body_l = compact(body).lower()
    if "?" not in body_l:
        return False
    if "cyber essentials is" in body_l and "can " not in body_l:
        return False
    systems = compact(copy_brief.get("data_systems_likely")).lower()
    system_terms = [word for word in re.findall(r"[a-z0-9]+", systems) if len(word) > 4]
    if system_terms and sum(1 for word in system_terms[:10] if word in body_l) >= 2:
        return True
    if classification.get("pressure_type") == "hia_regulatory":
        return all(term in body_l for term in ("health information", "access")) and "incident" in body_l
    if classification.get("entity_type_guess") in {"npo", "charity", "social_service"}:
        return "resident" in body_l and "beneficiary" in body_l and "incident" in body_l
    if classification.get("pressure_type") == "customer_trust":
        return "customer security question" in body_l and "evidence" in body_l
    return "personal data" in body_l and "access" in body_l and "incident" in body_l


def email_1_starts_with_target_structure(body: str, copy_brief: dict[str, Any]) -> bool:
    body_l = compact(body).lower()
    signal = compact(copy_brief.get("email_personalisation_signal")).lower()
    problem = compact(copy_brief.get("email_problem_statement")).lower()
    mechanism = compact(copy_brief.get("email_mechanism_statement")).lower()
    cta = compact(copy_brief.get("email_cta")).lower()
    positions = []
    for phrase in (signal, problem, mechanism, cta):
        if not phrase:
            positions.append(-1)
            continue
        positions.append(body_l.find(phrase[: min(len(phrase), 80)]))
    if any(pos < 0 for pos in positions):
        return False
    return positions == sorted(positions)


def generic_inbox_greeting_ok(row: dict[str, Any], emails: dict[str, Any]) -> bool:
    if compact(row.get("selected_contact_name")) and not is_generic_or_company_inbox(row):
        return True
    company = compact(row.get("company_name")).lower()
    allowed_prefixes = ["hi team,"]
    if company:
        allowed_prefixes.append(f"hi {company} team,")
    for key in ("email_1", "email_3", "email_4"):
        body = trim_text((emails.get(key) or {}).get("body")).lower()
        if body and not any(body.startswith(prefix) for prefix in allowed_prefixes):
            return False
    return True


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
    email3 = emails["email_3"]["body"]
    email4 = emails["email_4"]["body"]

    if not compact(copy_brief.get("email_personalisation_signal")) or not reflects(email1, copy_brief["email_personalisation_signal"]):
        flags.append("email_1_missing_specific_signal")
    if not compact(copy_brief.get("email_problem_statement")) or not reflects(email1, copy_brief["email_problem_statement"]):
        flags.append("email_1_missing_problem_statement")
    if not compact(copy_brief.get("email_mechanism_statement")) or not reflects(email1, copy_brief["email_mechanism_statement"]):
        flags.append("email_1_missing_mechanism_statement")
    if not compact(copy_brief.get("email_cta")) or not reflects(email1, copy_brief["email_cta"]) or "?" not in email1:
        flags.append("email_1_missing_tiny_cta")
    if generic_personalisation_signal(copy_brief.get("email_personalisation_signal", "")) or not email_1_starts_with_target_structure(email1, copy_brief):
        flags.append("email_1_too_generic")
    if not email_2_is_diagnostic(email2, copy_brief, classification):
        flags.append("email_2_not_diagnostic")
    if not funding_only_email_3(email3, funding.funding_claim_line):
        flags.append("email_3_not_funding_only")
    if email4 and compact(copy_brief.get("email_asset_offer")) and not reflects(email4, copy_brief["email_asset_offer"]):
        flags.append("email_4_missing_asset_offer")
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
    blob = "\n".join(emails[key]["body"] for key in ("email_1", "email_2", "email_3", "email_4")).lower()
    has_copy_brief = copy_brief is not None
    copy_brief = copy_brief or {}
    for phrase in FORBIDDEN_PHRASES:
        if phrase in blob:
            flags.append(f"forbidden_phrase:{phrase}")

    limits = {"email_1": 85, "email_2": 80, "email_3": 95, "email_4": 55}
    for key, limit in limits.items():
        if emails[key]["word_count"] > limit:
            flags.append(f"{key}_too_long")

    if classification.get("pressure_type") != "not_ready" and funding.funding_claim_line not in emails["email_3"]["body"]:
        flags.append("email_3_missing_funding_claim_line")
    if has_copy_brief and not copy_brief.get("funding_claim_safe") and classification.get("pressure_type") != "not_ready":
        flags.append("funding_needs_review")
    if re.search(r"\b\d{1,3}%\b", emails["email_3"]["body"]) and not any(
        item.get("exact_claim_allowed_in_email") for item in funding.matched
    ):
        flags.append("unverified_exact_percentage")
    if not classification.get("hia_deadline_claim_safe") and re.search(r"\b(sep|mar)\s+20(27|28|30)\b", blob):
        flags.append("unsafe_hia_deadline_claim")
    if "pdpa compliant" in blob and "does not make" not in blob:
        flags.append("cyber_essentials_equals_pdpa_compliance")
    if "hia compliant" in blob or "full hia compliance" in blob:
        flags.append("cyber_essentials_equals_hia_compliance")
    if not classification.get("outreach_trigger_signal"):
        flags.append("missing_outreach_trigger")
    if classification.get("outreach_trigger_confidence") == "low":
        flags.append("low_trigger_confidence")
    if classification.get("pressure_type") != "not_ready" and funding.funding_status != "verified_match":
        flags.append("funding_not_verified")
    if classification.get("pressure_type") == "not_ready" and any(emails[key]["body"] for key in ("email_1", "email_2", "email_3", "email_4")):
        flags.append("not_ready_has_email_body")
    if has_copy_brief and classification.get("pressure_type") != "not_ready":
        for field in ("email_personalisation_signal", "email_problem_statement", "email_mechanism_statement", "email_cta"):
            if not compact(copy_brief.get(field)):
                flags.append(f"missing_copy_brief:{field}")
        email1_body = emails["email_1"]["body"]
        if compact(copy_brief.get("email_personalisation_signal")) and not reflects(email1_body, copy_brief["email_personalisation_signal"]):
            flags.append("email_1_missing_specific_signal")
        if generic_personalisation_signal(copy_brief.get("email_personalisation_signal", "")):
            flags.append("generic_personalisation_signal")
        if compact(copy_brief.get("email_problem_statement")) and not reflects(email1_body, copy_brief["email_problem_statement"]):
            flags.append("email_1_missing_problem_statement")
        if compact(copy_brief.get("email_mechanism_statement")) and not reflects(email1_body, copy_brief["email_mechanism_statement"]):
            flags.append("email_1_missing_mechanism_statement")
        if compact(copy_brief.get("email_cta")) and (not reflects(email1_body, copy_brief["email_cta"]) or "?" not in email1_body):
            flags.append("email_1_missing_tiny_cta")
        email1_start = email1_body.strip().lower()
        if email1_start.startswith(("i came across your company", "noticed your company", "i noticed your company")):
            flags.append("email_1_too_generic")
        email2_body = emails["email_2"]["body"].lower()
        if "cyber essentials is" in email2_body and "?" not in email2_body:
            flags.append("email_2_not_diagnostic")
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
    classification = classify_row(row)
    funding = match_programmes({**row, **classification}, programmes=programmes)
    copy_brief = build_copy_brief(row, classification, funding)
    emails = generate_email_sequence(row, classification, funding, copy_brief)
    score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
    if row.get("draft_only"):
        send_ready = False
    if row.get("copy_qa_mode"):
        send_ready = False
        if "copy_qa_mode" not in flags:
            flags.append("copy_qa_mode")
    human_review_status = "ready_for_review" if not send_ready else "ready_for_review"
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
    )


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_noco_patch(row: dict[str, Any], plan: OutreachPlan) -> dict[str, Any]:
    c = plan.classification
    f = plan.funding
    b = plan.copy_brief
    e = plan.emails
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
        "hia_timeline_batch_guess": c["hia_timeline_batch_guess"],
        "hia_deadline_claim_safe": c["hia_deadline_claim_safe"],
        "hia_disclaimer_needed": c["hia_disclaimer_needed"],
        "hia_evidence_json": json_dumps({"evidence": c["evidence"], "scope_reason": c["hia_scope_reason"]}),
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
        "email_1_subject": e["email_1"]["chosen_subject"],
        "email_1_body": e["email_1"]["body"],
        "email_2_subject": e["email_2"]["chosen_subject"],
        "email_2_body": e["email_2"]["body"],
        "email_3_subject": e["email_3"]["chosen_subject"],
        "email_3_body": e["email_3"]["body"],
        "email_4_subject": e["email_4"]["chosen_subject"],
        "email_4_body": e["email_4"]["body"],
        "email_sequence_json": json_dumps(e),
        "email_quality_score": plan.quality_score,
        "email_quality_flags": json_dumps(plan.quality_flags),
        "email_send_ready": plan.email_send_ready,
        "human_review_status": plan.human_review_status,
    }
    return patch


def build_audit_report(row: dict[str, Any], plan: OutreachPlan | None = None, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    if plan is not None:
        classification = plan.classification
        funding = plan.funding
        emails = plan.emails
        flags = plan.quality_flags
        return {
            "row_id": plan.row_id,
            "company_name": compact(row.get("company_name")),
            "pressure_type": classification.get("pressure_type", ""),
            "hia_service_type_guess": classification.get("hia_service_type_guess", ""),
            "hia_timeline_batch_guess": classification.get("hia_timeline_batch_guess", ""),
            "funding_status": funding.funding_status,
            "email_quality_flags": flags,
            "email_1_subject": (emails.get("email_1") or {}).get("chosen_subject", ""),
            "email_1_body": (emails.get("email_1") or {}).get("body", ""),
            "email_2_subject": (emails.get("email_2") or {}).get("chosen_subject", ""),
            "email_2_body": (emails.get("email_2") or {}).get("body", ""),
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
    return {
        "row_id": patch.get("Id") or row.get("Id") or row.get("id"),
        "company_name": compact(row.get("company_name") or patch.get("company_name")),
        "pressure_type": patch.get("pressure_type", ""),
        "hia_service_type_guess": patch.get("hia_service_type_guess", ""),
        "hia_timeline_batch_guess": patch.get("hia_timeline_batch_guess", ""),
        "funding_status": patch.get("funding_status", ""),
        "email_quality_flags": flags,
        "email_1_subject": patch.get("email_1_subject", ""),
        "email_1_body": patch.get("email_1_body", ""),
        "email_2_subject": patch.get("email_2_subject", ""),
        "email_2_body": patch.get("email_2_body", ""),
        "email_3_subject": patch.get("email_3_subject", ""),
        "email_3_body": patch.get("email_3_body", ""),
        "email_4_subject": patch.get("email_4_subject", ""),
        "email_4_body": patch.get("email_4_body", ""),
    }


def plan_and_patch(row: dict[str, Any], programmes: list[Any] | None = None, copy_qa_mode: bool = False) -> dict[str, Any]:
    row = {**row, "copy_qa_mode": bool(copy_qa_mode or row.get("copy_qa_mode"))}
    plan = plan_outreach(row, programmes=programmes)
    patch = build_noco_patch(row, plan)
    return {
        "ok": True,
        "row_id": plan.row_id,
        "send_ready": plan.email_send_ready,
        "human_review_status": plan.human_review_status,
        "openrouter_allowed": copy_brief_ready(plan.classification, plan.copy_brief),
        "skip_openrouter": not copy_brief_ready(plan.classification, plan.copy_brief),
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
    if classification.get("pressure_type") == "not_ready" or not copy_brief_ready(classification, copy_brief):
        emails = generate_email_sequence(row, classification, funding, copy_brief)
    if classification.get("pressure_type") != "not_ready":
        emails = enforce_funding_claim_email(row, funding, emails)
    score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
    strategy_reject_flags = {
        "email_1_missing_specific_signal",
        "email_1_missing_problem_statement",
        "email_1_missing_mechanism_statement",
        "email_1_missing_tiny_cta",
        "email_1_too_generic",
        "email_2_not_diagnostic",
        "email_3_not_funding_only",
        "generic_inbox_wrong_greeting",
    }
    rejected_strategy_flags = [flag for flag in flags if flag in strategy_reject_flags]
    if rejected_strategy_flags and classification.get("pressure_type") != "not_ready":
        emails = generate_email_sequence(row, classification, funding, copy_brief)
        emails = enforce_funding_claim_email(row, funding, emails)
        score, flags, send_ready = quality_gate(row, classification, funding, emails, copy_brief)
        for flag in rejected_strategy_flags:
            rejected = f"llm_email_strategy_rejected:{flag}"
            if rejected not in flags:
                flags.append(rejected)
    if row.get("draft_only"):
        send_ready = False
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
        human_review_status="ready_for_review" if classification.get("pressure_type") != "not_ready" else "not_ready",
    )
    return build_noco_patch(row, plan)
