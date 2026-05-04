from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

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
- Email 1 leads with pressure_type.
- Email 2 gives a diagnostic tied to the same problem.
- Email 3 is funding-only and must use funding_claim_line.
- Email 4 closes the loop.
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
    "dental",
    "dentist",
    "pharmacy",
    "diagnostic",
    "hospital",
    "physio",
    "allied health",
    "hearing",
    "audiology",
    "patient",
    "health screening",
    "treatment",
)
NPO_TERMS = ("charity", "society", "mission", "foundation", "volunteer", "donation", "ncss", "ipc", "beneficiary")
SOCIAL_TERMS = ("resident", "beneficiary", "care", "nursing home", "community", "social service", "eldercare")
B2B_TERMS = ("enterprise", "vendor", "outsourcing", "saas", "platform", "managed service", "consulting", "professional services")
SENSITIVE_TERMS = ("patient", "health", "medical", "resident", "beneficiary", "student", "financial")


@dataclass
class OutreachPlan:
    row_id: Any
    classification: dict[str, Any]
    funding: FundingMatch
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


def lower_blob(row: dict[str, Any]) -> str:
    parts = [
        row.get("company_name", ""),
        row.get("company_homepage_name", ""),
        row.get("industry_guess", ""),
        row.get("website_content", ""),
        row.get("notes", ""),
        row.get("selected_contact_title", ""),
        row.get("selected_contact_role", ""),
    ]
    return " ".join(compact(part) for part in parts).lower()


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
    if ("clinic" in text or "dental" in text or company.lower().endswith("clinic")) and not contains_any(text, NPO_TERMS):
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
    for term in HEALTHCARE_TERMS:
        if term in text:
            score += 12
    if "patient" in text or "health information" in text:
        score += 18
    if "dental" in text or "dentist" in text:
        service = "dental"
    elif "pharmacy" in text:
        service = "retail_pharmacy"
    elif "hearing" in text or "audiology" in text:
        service = "hearing_care"
    elif "diagnostic" in text or "radiology" in text:
        service = "diagnostic"
    elif "physio" in text or "therapy" in text:
        service = "allied_health"
    elif "clinic" in text or "doctor" in text or "medical" in text:
        service = "GP_OMS"
    else:
        service = "unknown"
    score = min(score, 100)
    confidence = confidence_from_score(score)
    return {
        "hia_relevant": score >= 45,
        "hia_relevance_score": score,
        "hia_confidence": confidence,
        "hia_scope_reason": "Website evidence indicates healthcare services and possible patient or health-information handling." if score >= 45 else "Healthcare/HIA scope evidence is weak.",
        "hia_service_type_guess": service,
        "hia_timeline_batch_guess": "unknown",
        "hia_deadline_claim_safe": False,
        "hia_disclaimer_needed": True,
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
    if contains_any(text, SENSITIVE_TERMS):
        return "customer_data", "medium", "medium"
    return "customer_data", "medium", "unknown"


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    text = lower_blob(row)
    entity = infer_entity(row, text)
    hia = infer_hia(row, text)
    data_type, personal_intensity, sensitive_likelihood = infer_data_signal(text, hia, entity)

    if hia["hia_relevant"] and hia["hia_confidence"] in {"medium", "high"}:
        pressure_type = "hia_regulatory"
        problem_area = "hia_readiness"
        value_asset = "hia_readiness_map"
        trigger = "HIA timelines start from 2027, and the website indicates healthcare or patient-data activity."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Start with HIA readiness mapping, then use Cyber Essentials as a practical cybersecurity/data-security baseline."
    elif contains_any(text, B2B_TERMS):
        pressure_type = "customer_trust"
        problem_area = "evidence_collection"
        value_asset = "security_evidence_checklist"
        trigger = "Customers and partners may ask for reusable security evidence before sharing business data."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials as the first reusable security-evidence baseline."
    else:
        pressure_type = "pdpa_safeguards"
        problem_area = "pdpa_safeguards" if personal_intensity in {"medium", "high"} else "unknown"
        value_asset = "pdpa_safeguards_checklist"
        trigger = f"The organisation appears to handle {data_type.replace('_', ' ')}."
        recommended_first_cert = "Cyber Essentials"
        recommended_path = "Use Cyber Essentials to support the cybersecurity safeguards and evidence side of PDPA readiness."

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
        "pdpa_relevant": pressure_type != "not_ready",
        "pdpa_reason": "Private-sector or non-HIA organisation likely handles personal data; Cyber Essentials supports safeguard evidence." if not hia["hia_relevant"] else "PDPA may still be relevant, but HIA readiness is the primary pressure.",
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
    return f"The practical gap is likely showing clear safeguards for {data_type.replace('_', ' ')}."


def certification_reason(pressure_type: str) -> str:
    if pressure_type == "hia_regulatory":
        return "Cyber Essentials is a practical first baseline for HIA cybersecurity/data-security readiness; it is not HIA compliance."
    if pressure_type == "customer_trust":
        return "Cyber Essentials gives a reusable baseline for access, assets, malware protection, patching, backup and incident readiness evidence."
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
    if classification["pressure_type"] == "customer_trust":
        return "customer_trust"
    return "pdpa_general"


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def tiny_cta(asset: str) -> str:
    if "map" in asset:
        return "Want the map?"
    if "route" in asset or "funding" in asset:
        return "Should I send the route summary?"
    return "Worth sending the checklist?"


def generate_email_sequence(row: dict[str, Any], classification: dict[str, Any], funding: FundingMatch) -> dict[str, Any]:
    company = compact(row.get("company_name") or "your organisation")
    first_name = first_name_from_contact(row)
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    trigger = classification["outreach_trigger_signal"]
    asset = classification["value_asset_offer"]
    cert = classification["recommended_first_cert"]
    cta = tiny_cta(asset)

    if classification["pressure_type"] == "hia_regulatory":
        lead = "With HIA timelines starting from 2027"
        if classification.get("hia_deadline_claim_safe") and classification.get("hia_timeline_batch_guess") != "unknown":
            lead = f"With the {classification['hia_timeline_batch_guess']} HIA window"
        mechanism = "Cyber Essentials is a practical first baseline for HIA cybersecurity/data-security readiness."
        email1_body = f"{greeting}\n\n{lead}, {company} may need a clear way to map patient-data safeguards into access, patching, backups, incident response and evidence. {mechanism}\n\nI can send a short HIA readiness map for clinics. {cta}"
        email2_body = f"{greeting}\n\nA useful first diagnostic is whether each role that touches patient or health information has a named access owner, backup path and offboarding check. That usually shows where HIA readiness work should start.\n\n{cta}"
    elif classification["pressure_type"] == "customer_trust":
        email1_body = f"{greeting}\n\nWhen customers share data or ask security questions, the slow part is usually evidence. {trigger} {cert} can turn access, assets, patching, backups and incident readiness into a reusable baseline.\n\n{cta}"
        email2_body = f"{greeting}\n\nA practical diagnostic is to list the security questions customers already ask, then map each one to current evidence. Missing items usually point to access control, patching, backup or incident-response gaps.\n\n{cta}"
    else:
        data = classification["data_type_signal"].replace("_", " ")
        email1_body = f"{greeting}\n\nBecause {company} handles {data}, the practical question is whether safeguards can be shown clearly. Cyber Essentials supports the security-safeguards side of PDPA readiness through access, assets, patching, backups and incident readiness evidence.\n\n{cta}"
        email2_body = f"{greeting}\n\nA useful diagnostic is to trace where {data} is collected, who can access it, and how access is removed when roles change. That usually finds the first PDPA safeguard evidence gaps.\n\n{cta}"

    funding_line = funding.funding_claim_line or "Funding route needs human review before use."
    email3_body = f"{greeting}\n\n{funding_line} This is subject to programme confirmation. I can send a short route summary showing what to verify before using the claim internally.\n\nShould I send the route summary?"
    email4_body = f"{greeting}\n\nShould I close this off, or send the one-page checklist for review?"

    emails = {
        "email_1": {
            "subject_options": ["Readiness checklist", f"{company} safeguard map"],
            "chosen_subject": "Readiness checklist",
            "body": email1_body,
        },
        "email_2": {
            "subject_options": ["Quick diagnostic", "Access evidence check"],
            "chosen_subject": "Quick diagnostic",
            "body": email2_body,
        },
        "email_3": {
            "subject_options": ["Funding route check", "Support route summary"],
            "chosen_subject": "Funding route check",
            "body": email3_body,
        },
        "email_4": {
            "subject_options": ["Close loop", "Checklist?"],
            "chosen_subject": "Close loop",
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


def quality_gate(classification: dict[str, Any], funding: FundingMatch, emails: dict[str, Any]) -> tuple[int, list[str], bool]:
    flags: list[str] = []
    blob = "\n".join(emails[key]["body"] for key in ("email_1", "email_2", "email_3", "email_4")).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in blob:
            flags.append(f"forbidden_phrase:{phrase}")

    limits = {"email_1": 85, "email_2": 80, "email_3": 95, "email_4": 55}
    for key, limit in limits.items():
        if emails[key]["word_count"] > limit:
            flags.append(f"{key}_too_long")

    if funding.funding_claim_line not in emails["email_3"]["body"]:
        flags.append("email_3_missing_funding_claim_line")
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
    if funding.funding_status != "verified_match":
        flags.append("funding_not_verified")

    score = 0
    if classification.get("entity_type_guess") != "unknown":
        score += 2
    if classification.get("outreach_trigger_confidence") in {"medium", "high"}:
        score += 2
    if classification.get("problem_hypothesis"):
        score += 2
    if classification.get("recommended_first_cert") != "unknown":
        score += 1
    if funding.funding_status == "verified_match":
        score += 1
    if all(emails[key]["body"].count("?") >= 1 for key in ("email_1", "email_2", "email_3", "email_4")):
        score += 1
    if not any(phrase in blob for phrase in ("hope you are well", "leading provider", "unlock growth")):
        score += 1
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
    emails = generate_email_sequence(row, classification, funding)
    score, flags, send_ready = quality_gate(classification, funding, emails)
    human_review_status = "ready_for_review" if not send_ready else "ready_for_review"
    if classification["pressure_type"] == "not_ready":
        human_review_status = "not_ready"
    return OutreachPlan(
        row_id=row.get("Id") or row.get("id") or "",
        classification=classification,
        funding=funding,
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


def plan_and_patch(row: dict[str, Any], programmes: list[Any] | None = None) -> dict[str, Any]:
    plan = plan_outreach(row, programmes=programmes)
    return {
        "ok": True,
        "row_id": plan.row_id,
        "send_ready": plan.email_send_ready,
        "human_review_status": plan.human_review_status,
        "patch": build_noco_patch(row, plan),
        "record": plan.to_dict(),
    }
