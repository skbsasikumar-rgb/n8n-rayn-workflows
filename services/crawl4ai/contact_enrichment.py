from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

HONORIFICS_RE = re.compile(r"^(?:dr|doctor|mr|mrs|ms|miss|mdm|prof|professor|assoc\.?\s*prof|a/?prof)\.?\s+", re.I)
NAME_TOKEN_RE = r"[A-Z][a-zA-Z'’-]+"
NAME_CAPTURE_RE = rf"({NAME_TOKEN_RE}(?:[ \t]+{NAME_TOKEN_RE}){{1,4}})"
NAME_RE = re.compile(rf"\b(?:Dr\.?\s+|Mr\.?\s+|Mrs\.?\s+|Ms\.?\s+|Prof\.?\s+)?{NAME_CAPTURE_RE}\b")
EMAIL_SAFE_RE = re.compile(r"[^a-z0-9]")
GENERIC_LOCAL_PARTS = {
    "info",
    "contact",
    "hello",
    "admin",
    "enquiry",
    "enquiries",
    "appointments",
    "clinic",
    "reception",
    "support",
    "sales",
    "marketing",
    "team",
}
ROLE_BUCKETS: list[dict[str, Any]] = [
    {"bucket": "c_suite", "seniority": "executive", "priority": 1, "roles": ["CEO", "Founder", "Owner", "Managing Director", "Executive Director", "General Manager"]},
    {"bucket": "compliance_privacy_security", "seniority": "senior_manager", "priority": 2, "roles": ["DPO", "Data Protection Officer", "Compliance Manager", "Risk Manager", "CISO", "Head of Security", "Cybersecurity Manager"]},
    {"bucket": "it_technology", "seniority": "manager", "priority": 3, "roles": ["IT Manager", "Head of IT", "CTO", "Technology Manager", "Systems Manager"]},
    {"bucket": "operations", "seniority": "manager", "priority": 4, "roles": ["Operations Manager", "Ops Manager", "Clinic Operations Manager", "Practice Manager"]},
    {"bucket": "clinic_leadership", "seniority": "manager", "priority": 5, "roles": ["Clinic Manager", "Clinical Manager", "Medical Director", "Head Doctor", "Principal Doctor", "Doctor in charge", "Senior Doctor"]},
    {"bucket": "care_clinical", "seniority": "manager", "priority": 6, "roles": ["Head of Nursing", "Nursing Manager", "Clinical Lead", "Care Manager"]},
]
ROLE_TERMS = {role.lower(): group for group in ROLE_BUCKETS for role in group["roles"]}
NOISE_NAME_TERMS = {
    "Singapore",
    "Contact Us",
    "About Us",
    "Our Team",
    "Our Doctors",
    "Medical Clinic",
    "Health Clinic",
    "Dental Surgery",
    "Privacy Policy",
    "Terms Conditions",
}
NOISE_NAME_WORDS = {
    "about",
    "aesthetic",
    "aesthetics",
    "american",
    "appointed",
    "active",
    "ageing",
    "audiologist",
    "australasian",
    "body",
    "bova",
    "clinic",
    "compounding",
    "contact",
    "chief",
    "director",
    "dispute",
    "doctor",
    "doctors",
    "doing",
    "general",
    "guide",
    "health",
    "hearing",
    "international",
    "laser",
    "learn",
    "lifestyle",
    "magazine",
    "manager",
    "managing",
    "medical",
    "more",
    "most",
    "novena",
    "org",
    "pharmacy",
    "podcast",
    "practitioner",
    "promising",
    "prep",
    "profile",
    "road",
    "resolution",
    "sales",
    "senior",
    "seminar",
    "service",
    "singapore",
    "skin",
    "team",
    "trainer",
    "treatments",
    "ceo",
    "cto",
    "ciso",
    "founder",
    "owner",
}
CREDENTIAL_WORDS = {
    "bao",
    "bch",
    "bds",
    "fams",
    "fracgp",
    "frcs",
    "gdfm",
    "graduate",
    "lrcp",
    "mb",
    "mbbs",
    "mmed",
    "mrcp",
    "md",
    "phd",
    "si",
}


@dataclass
class ContactCandidate:
    name: str
    role: str
    seniority: str
    role_bucket: str
    role_priority: int
    source_url: str
    source_type: str
    evidence_text: str
    confidence: str
    confidence_score: float
    company_match: bool
    first_name: str = ""
    last_name: str = ""
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ContactResult:
    row_id: int | str
    contact_search_status: str
    contact_search_reason: str
    contact_candidates: list[dict[str, Any]] = field(default_factory=list)
    contact_search_evidence: dict[str, Any] = field(default_factory=dict)
    email_candidates: list[dict[str, Any]] = field(default_factory=list)
    selected_contact_name: str = ""
    selected_contact_role: str = ""
    selected_contact_seniority: str = ""
    selected_contact_source_url: str = ""
    selected_contact_confidence: str = ""
    validated_email: str = ""
    email_validation_status: str = ""
    email_validation_provider: str = "no2bounce"
    email_validation_evidence: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact(value: Any, limit: int = 2000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def domain_from_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    return urlparse(raw).netloc.lower().removeprefix("www.")


def normalize_company(value: str) -> str:
    text = compact(value).lower()
    text = re.sub(r"\b(?:pte\.?\s*ltd\.?|ltd\.?|llp|llc|inc\.?|clinic|medical|dental|surgery|centre|center|singapore)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def company_match(text: str, company_name: str, homepage_name: str, canonical_domain: str) -> bool:
    haystack = compact(text, 5000).lower()
    domain_root = canonical_domain.split(".")[0].replace("-", " ") if canonical_domain else ""
    options = [normalize_company(company_name), normalize_company(homepage_name), normalize_company(domain_root)]
    return any(option and len(option) >= 4 and option in re.sub(r"[^a-z0-9]+", " ", haystack) for option in options)


def company_near_name(evidence: str, name_start: int, name_end: int, company_name: str, homepage_name: str, canonical_domain: str) -> bool:
    window = evidence[max(0, name_start - 140) : min(len(evidence), name_end + 140)]
    return company_match(window, company_name, homepage_name, canonical_domain)


def role_match(text: str, query_role: str = "") -> tuple[str, dict[str, Any] | None]:
    haystack = compact(text).lower()
    if query_role and query_role.lower() in haystack:
        return query_role, ROLE_TERMS.get(query_role.lower())
    for role, group in ROLE_TERMS.items():
        if role in haystack:
            canonical_role = next((r for r in group["roles"] if r.lower() == role), role.title())
            return canonical_role, group
    return "", None


def clean_name(name: str) -> str:
    text = compact(name, 120)
    while True:
        new_text = HONORIFICS_RE.sub("", text).strip()
        if new_text == text:
            break
        text = new_text
    text = re.sub(r"[^A-Za-z'’\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -'’")
    parts = [part for part in text.split() if part]
    while parts and parts[-1].lower().strip(".-'’") in CREDENTIAL_WORDS:
        parts.pop()
    return " ".join(parts)


def parse_name(name: str) -> tuple[str, str] | None:
    cleaned = clean_name(name)
    parts = [p for p in cleaned.replace("’", "'").split() if p]
    if len(parts) < 2 or len(parts) > 5:
        return None
    lowered = [part.lower().strip("-'") for part in parts]
    if any(part in {"and", "the", "our"} for part in lowered):
        return None
    if any(part in NOISE_NAME_WORDS for part in lowered):
        return None
    if len(parts) == 2 and all(len(part) <= 2 for part in parts):
        return None
    return parts[0], parts[-1]


def name_parts(name: str) -> list[str]:
    cleaned = clean_name(name)
    return [part for part in cleaned.replace("’", "'").split() if part]


def role_near_name(evidence: str, name_start: int, name_end: int, role: str) -> bool:
    window = evidence[max(0, name_start - 90) : min(len(evidence), name_end + 90)].lower()
    role_text = role.lower()
    if role_text and role_text in window:
        return True
    role_parts = [part for part in re.split(r"[^a-z]+", role_text) if len(part) >= 4]
    return any(part in window for part in role_parts)


def name_matches_for_role(evidence: str, role: str) -> list[tuple[str, int, int]]:
    role_pattern = f"(?i:{re.escape(role)}s?)"
    honorific = r"(?:Dr\.?\s+|Mr\.?\s+|Mrs\.?\s+|Ms\.?\s+|Prof\.?\s+)?"
    patterns = [
        rf"{honorific}{NAME_CAPTURE_RE}(?:,\s*(?:[A-Z][A-Za-z.]{{1,10}}|MBBS|AuD|MD|PhD))*\s*,\s*\b{role_pattern}\b",
        rf"\b{role_pattern}\b(?:\s*[:,-]|\s+)(?!at\b|of\b|for\b)[^.|\n]{{0,50}}?{honorific}{NAME_CAPTURE_RE}",
        rf"{honorific}{NAME_CAPTURE_RE}[^.|\n]{{0,100}}?\b{role_pattern}\b",
        rf"^\\s*{honorific}{NAME_CAPTURE_RE}\\s+-\\s+[^|\n]{{0,160}}?\\b{role_pattern}\\b",
        rf"{honorific}{NAME_CAPTURE_RE}\\s*\\.\\s*\\b{role_pattern}\\b",
    ]
    matches: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, evidence):
            candidate = clean_name(match.group(1))
            key = candidate.lower()
            if key and key not in seen:
                seen.add(key)
                matches.append((candidate, match.start(1), match.end(1)))
    return matches


def extract_candidates_from_website_content(
    website_content: str,
    company_name: str,
    homepage_name: str,
    canonical_domain: str,
    best_url: str,
) -> list[ContactCandidate]:
    raw_content = str(website_content or "")[:50000]
    normalized_content = compact(raw_content, 50000)
    if not normalized_content or not company_match(normalized_content, company_name, homepage_name, canonical_domain):
        return []

    candidates: list[ContactCandidate] = []
    seen: set[tuple[str, str]] = set()
    for group in ROLE_BUCKETS:
        for role in group["roles"]:
            for name, name_start, name_end in name_matches_for_role(raw_content, role):
                if not name or name in NOISE_NAME_TERMS or company_match(name, company_name, homepage_name, canonical_domain):
                    continue
                if re.search(r"[’']s$", name):
                    continue
                if not role_near_name(raw_content, name_start, name_end, role):
                    continue
                parsed = parse_name(name)
                if not parsed:
                    continue
                key = (name.lower(), role.lower())
                if key in seen:
                    continue
                seen.add(key)
                first_name, last_name = parsed
                candidates.append(
                    ContactCandidate(
                        name=name,
                        role=role,
                        seniority=group["seniority"],
                        role_bucket=group["bucket"],
                        role_priority=int(group["priority"]),
                        source_url=best_url or f"https://{canonical_domain}/",
                        source_type="official_domain",
                        evidence_text=raw_content[max(0, name_start - 160) : min(len(raw_content), name_end + 200)],
                        confidence="High",
                        confidence_score=0.92,
                        company_match=True,
                        first_name=first_name,
                        last_name=last_name,
                    )
                )
    clinical_fallback_group = next((group for group in ROLE_BUCKETS if group["bucket"] == "clinic_leadership"), None)
    if clinical_fallback_group:
        for match in re.finditer(rf"\bDr\.?\s+{NAME_CAPTURE_RE}\b", raw_content):
            name = clean_name(match.group(1))
            if not name or name in NOISE_NAME_TERMS or company_match(name, company_name, homepage_name, canonical_domain):
                continue
            if re.search(r"[’']s$", name):
                continue
            key = (name.lower(), "clinical lead")
            if key in seen:
                continue
            parsed = parse_name(name)
            if not parsed:
                continue
            seen.add(key)
            first_name, last_name = parsed
            candidates.append(
                    ContactCandidate(
                        name=name,
                        role="Senior Doctor",
                        seniority=clinical_fallback_group["seniority"],
                        role_bucket=clinical_fallback_group["bucket"],
                        role_priority=int(clinical_fallback_group["priority"]),
                    source_url=best_url or f"https://{canonical_domain}/",
                    source_type="official_domain",
                    evidence_text=raw_content[max(0, match.start(1) - 120) : min(len(raw_content), match.end(1) + 200)],
                    confidence="High",
                    confidence_score=0.85,
                    company_match=True,
                    first_name=first_name,
                    last_name=last_name,
                )
            )
    operations_fallback_group = next((group for group in ROLE_BUCKETS if group["bucket"] == "operations"), None)
    if operations_fallback_group:
        manager_patterns = [
            r"\bManager\b\s*[:\-]\s*([A-Z][a-zA-Z'’-]+[ \t]+[A-Z][a-zA-Z'’-]+)",
            r"([A-Z][a-zA-Z'’-]+[ \t]+[A-Z][a-zA-Z'’-]+)\s*,\s*Manager\b",
            r"\bManaging (?!Director\b)[A-Z][a-zA-Z]+\b,\s*([A-Z][a-zA-Z'’-]+[ \t]+[A-Z][a-zA-Z'’-]+)",
        ]
        for pattern in manager_patterns:
            for match in re.finditer(pattern, raw_content):
                name = clean_name(match.group(1))
                if not name or name in NOISE_NAME_TERMS or company_match(name, company_name, homepage_name, canonical_domain):
                    continue
                if re.search(r"[’']s$", name):
                    continue
                key = (name.lower(), "practice manager")
                if key in seen:
                    continue
                parsed = parse_name(name)
                if not parsed:
                    continue
                seen.add(key)
                first_name, last_name = parsed
                candidates.append(
                    ContactCandidate(
                        name=name,
                        role="Practice Manager",
                        seniority=operations_fallback_group["seniority"],
                        role_bucket=operations_fallback_group["bucket"],
                        role_priority=int(operations_fallback_group["priority"]),
                        source_url=best_url or f"https://{canonical_domain}/",
                        source_type="official_domain",
                        evidence_text=raw_content[max(0, match.start(1) - 120) : min(len(raw_content), match.end(1) + 200)],
                        confidence="High",
                        confidence_score=0.88,
                        company_match=True,
                        first_name=first_name,
                        last_name=last_name,
                    )
                )
    candidates.sort(key=lambda item: (item.role_priority, -item.confidence_score, item.name.lower()))
    return candidates


def source_type(url: str, canonical_domain: str) -> str:
    domain = domain_from_url(url)
    if canonical_domain and domain.endswith(canonical_domain):
        return "official_domain"
    if "linkedin.com" in domain:
        return "public_linkedin_snippet"
    if any(label in domain for label in ("doctor", "health", "clinic", "medical", "dental")):
        return "professional_public_page"
    return "public_search_result"


def is_search_asset(url: str) -> bool:
    path = urlparse(url if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I) else "https://" + url).path.lower()
    return path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".zip"))


def extract_candidates(payload: dict[str, Any]) -> list[ContactCandidate]:
    company_name = compact(payload.get("company_name"))
    homepage_name = compact(payload.get("company_homepage_name"))
    canonical_domain = compact(payload.get("canonical_domain")).lower().removeprefix("www.")
    best_url = compact(payload.get("best_url"), 500)
    website_content = payload.get("website_content") if isinstance(payload.get("website_content"), str) else ""
    attempts = payload.get("search_attempts") if isinstance(payload.get("search_attempts"), list) else []
    candidates = extract_candidates_from_website_content(website_content, company_name, homepage_name, canonical_domain, best_url)
    seen: set[tuple[str, str]] = {(candidate.name.lower(), candidate.role.lower()) for candidate in candidates}

    for attempt in attempts:
        query_role = compact(attempt.get("role"))
        results = attempt.get("results") if isinstance(attempt.get("results"), list) else []
        for result in results[:10]:
            title = compact(result.get("title"), 400)
            snippet = compact(result.get("snippet") or result.get("content") or result.get("description"), 1200)
            url = compact(result.get("url") or result.get("link"), 1000)
            if is_search_asset(url):
                continue
            stype = source_type(url, canonical_domain)
            evidence = compact(" | ".join(part for part in (title, snippet) if part), 1600)
            matched_role, group = role_match(evidence, query_role=query_role)
            if not group:
                continue
            if not company_match(evidence + " " + url, company_name, homepage_name, canonical_domain):
                continue
            for name, name_start, name_end in name_matches_for_role(evidence, matched_role):
                if not name or name in NOISE_NAME_TERMS or company_match(name, company_name, homepage_name, canonical_domain):
                    continue
                if not role_near_name(evidence, name_start, name_end, matched_role):
                    continue
                if stype != "official_domain" and not company_near_name(evidence, name_start, name_end, company_name, homepage_name, canonical_domain):
                    continue
                parsed = parse_name(name)
                if not parsed:
                    continue
                first_name, last_name = parsed
                if stype == "public_search_result":
                    continue
                key = (name.lower(), matched_role.lower())
                if key in seen:
                    continue
                seen.add(key)
                confidence = "High" if stype == "official_domain" else "Medium"
                score = 0.9 if confidence == "High" else 0.7
                candidates.append(
                    ContactCandidate(
                        name=name,
                        role=matched_role,
                        seniority=group["seniority"],
                        role_bucket=group["bucket"],
                        role_priority=int(group["priority"]),
                        source_url=url,
                        source_type=stype,
                        evidence_text=evidence,
                        confidence=confidence,
                        confidence_score=score,
                        company_match=True,
                        first_name=first_name,
                        last_name=last_name,
                    )
                )

    candidates.sort(key=lambda item: (item.role_priority, -item.confidence_score, item.name.lower()))
    return candidates


def safe_local_part(value: str) -> str:
    return EMAIL_SAFE_RE.sub("", value.lower())


def email_permutations(candidate: ContactCandidate, domain: str) -> list[dict[str, str]]:
    parts = name_parts(candidate.name)
    if len(parts) < 2:
        return []
    family = safe_local_part(parts[0])
    western_first = safe_local_part(candidate.first_name)
    western_last = safe_local_part(candidate.last_name)
    given = safe_local_part(parts[-1])
    middle = "".join(safe_local_part(part) for part in parts[1:-1])
    all_parts = "".join(safe_local_part(part) for part in parts)

    identity_pairs = []
    if len(parts) >= 3 and given and family:
        identity_pairs.append((given, family))
    identity_pairs.append((western_first, western_last))

    patterns: list[tuple[str, str]] = []
    for index, (first, last) in enumerate(identity_pairs):
        if not first or not last:
            continue
        suffix = "" if index == 0 else "_given_family"
        patterns.extend(
            [
                (f"first.last{suffix}", f"{first}.{last}"),
                (f"first{suffix}", first),
                (f"firstlast{suffix}", f"{first}{last}"),
                (f"f.last{suffix}", f"{first[0]}.{last}"),
                (f"firstl{suffix}", f"{first}{last[0]}"),
                (f"flast{suffix}", f"{first[0]}{last}"),
                (f"last.first{suffix}", f"{last}.{first}"),
                (f"first_last{suffix}", f"{first}_{last}"),
                (f"first-last{suffix}", f"{first}-{last}"),
            ]
        )
    if len(parts) >= 3 and all_parts:
        patterns.append(("full_name_compact", all_parts))
    if len(parts) >= 4 and family and middle and given:
        patterns.append(("family_middle_given", f"{family}{middle}{given}"))

    output = []
    seen = set()
    for pattern, local in patterns:
        if local in GENERIC_LOCAL_PARTS or local in seen:
            continue
        seen.add(local)
        output.append({"email": f"{local}@{domain}", "pattern": pattern, "status": "not_validated"})
    return output


def status_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in (
            "finalScoreValue",
            "status",
            "result",
            "state",
            "deliverability",
            "email_status",
            "verification_status",
            "validation result",
        ):
            matched = dict_get_case_insensitive(value, key)
            if matched:
                return compact(matched, 80).lower()
    return compact(value, 80).lower()


def dict_get_case_insensitive(value: dict[str, Any], key: str) -> Any:
    lowered = key.lower()
    for candidate_key, candidate_value in value.items():
        if str(candidate_key).lower() == lowered:
            return candidate_value
    return None


def final_score(result: Any) -> float:
    if not isinstance(result, dict):
        return 0.0
    value = dict_get_case_insensitive(result, "finalScore")
    if value is None:
        value = dict_get_case_insensitive(result, "score")
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def email_decision(result: Any, has_named_person: bool) -> str:
    status = status_text(result)
    score = final_score(result)
    catchall = False
    if isinstance(result, dict):
        catchall = str(dict_get_case_insensitive(result, "catchall")).strip().lower() == "true"

    hard_reject_terms = ("undeliver", "invalid", "bad", "bounce", "spam", "disposable", "unknown", "blocked", "incomplete")
    if any(term in status for term in hard_reject_terms):
        return "rejected"

    is_accept_all = "acceptall" in status or "accept all" in status
    is_deliverable_accept_all = "deliverable" in status and is_accept_all
    if is_deliverable_accept_all:
        if score >= 90 and has_named_person:
            return "risky_sendable"
        return "rejected"

    if catchall and score < 90:
        return "rejected"

    if "deliverable" in status or status in {"valid", "ok"}:
        return "sendable"

    return "rejected"


def find_no2bounce_download_url(payload: Any) -> str:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() == "downloadfile" and isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            nested = find_no2bounce_download_url(value)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = find_no2bounce_download_url(item)
            if nested:
                return nested
    return ""


def sanitize_no2bounce_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        output: dict[str, Any] = {}
        for key, value in payload.items():
            if str(key).lower() == "downloadfile":
                output[key] = "[redacted_download_url]" if value else ""
            else:
                output[key] = sanitize_no2bounce_payload(value)
        return output
    if isinstance(payload, list):
        return [sanitize_no2bounce_payload(item) for item in payload]
    return payload


def download_no2bounce_results(payload: Any) -> list[dict[str, Any]]:
    download_url = find_no2bounce_download_url(payload)
    if not download_url:
        return []
    response = requests.get(download_url, timeout=30)
    if response.status_code >= 400:
        return []
    csv_text = response.text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(csv_text))
    return [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in reader
        if any(str(value or "").strip() for value in row.values())
    ]


def extract_no2bounce_results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "data", "emails", "emailList", "validations", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_no2bounce_results(value)
            if nested:
                return nested
    downloaded = download_no2bounce_results(payload)
    if downloaded:
        return downloaded
    return []


def validate_no2bounce(emails: list[str], timeout_seconds: int = 90) -> dict[str, Any]:
    token = os.getenv("NO2BOUNCE_API_TOKEN", "").strip()
    if not token:
        return {"configured": False, "error": "NO2BOUNCE_API_TOKEN is not configured", "results": []}
    if not emails:
        return {"configured": True, "error": "", "results": []}

    base_url = os.getenv("NO2BOUNCE_BASE_URL", "https://connect.no2bounce.com/v2/n2b_validate_bulk").strip()
    headers = {"apitoken": token, "Content-Type": "application/json"}
    post = requests.post(base_url, headers=headers, json={"emailList": emails}, timeout=30)
    post_payload: Any
    try:
        post_payload = post.json()
    except ValueError:
        post_payload = {"raw": post.text}
    if post.status_code >= 400:
        return {"configured": True, "error": f"POST HTTP {post.status_code}", "post_response": post_payload, "results": []}

    tracking_id = ""
    if isinstance(post_payload, dict):
        nested = post_payload.get("data") if isinstance(post_payload.get("data"), dict) else {}
        tracking_id = compact(
            post_payload.get("trackingId")
            or post_payload.get("tracking_id")
            or post_payload.get("id")
            or nested.get("trackingId")
            or nested.get("tracking_id")
            or nested.get("id"),
            200,
        )
    if not tracking_id:
        return {"configured": True, "error": "missing_tracking_id", "post_response": post_payload, "results": extract_no2bounce_results(post_payload)}

    deadline = time.time() + timeout_seconds
    poll_payload: Any = {}
    while time.time() < deadline:
        poll = requests.get(base_url, headers=headers, params={"trackingId": tracking_id}, timeout=30)
        try:
            poll_payload = poll.json()
        except ValueError:
            poll_payload = {"raw": poll.text}
        results = extract_no2bounce_results(poll_payload)
        if results:
            return {
                "configured": True,
                "error": "",
                "trackingId": tracking_id,
                "post_response": sanitize_no2bounce_payload(post_payload),
                "poll_response": sanitize_no2bounce_payload(poll_payload),
                "results": results,
            }
        time.sleep(3)
    return {
        "configured": True,
        "error": "poll_timeout",
        "trackingId": tracking_id,
        "post_response": sanitize_no2bounce_payload(post_payload),
        "poll_response": sanitize_no2bounce_payload(poll_payload),
        "results": [],
    }


def result_email(result: dict[str, Any]) -> str:
    for key in ("email", "email address", "email_address", "address", "emailAddress", "mail"):
        matched = dict_get_case_insensitive(result, key)
        if matched:
            return compact(matched, 320).lower()
    return ""


def build_contact_search_evidence(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = payload.get("search_attempts") if isinstance(payload.get("search_attempts"), list) else []
    output_attempts: list[dict[str, Any]] = []
    total_results = 0
    error_count = 0
    for attempt in attempts[:20]:
        results = attempt.get("results") if isinstance(attempt, dict) and isinstance(attempt.get("results"), list) else []
        error = compact(attempt.get("error") if isinstance(attempt, dict) else "", 300)
        if error:
            error_count += 1
        total_results += len(results)
        output_attempts.append(
            {
                "query": compact(attempt.get("query") if isinstance(attempt, dict) else "", 300),
                "role": compact(attempt.get("role") if isinstance(attempt, dict) else "", 100),
                "role_bucket": compact(attempt.get("role_bucket") if isinstance(attempt, dict) else "", 100),
                "error": error,
                "results_count": len(results),
                "top_results": [
                    {
                        "rank": result.get("rank"),
                        "title": compact(result.get("title"), 180),
                        "url": compact(result.get("url"), 500),
                        "snippet": compact(result.get("snippet"), 300),
                    }
                    for result in results[:3]
                    if isinstance(result, dict)
                ],
            }
        )
    return {
        "query_attempts_count": len(attempts),
        "stored_attempts_count": len(output_attempts),
        "total_results_count": total_results,
        "search_error_count": error_count,
        "candidate_count": len(candidates),
        "candidate_names": [compact(candidate.get("name"), 120) for candidate in candidates[:10]],
        "attempts": output_attempts,
    }


def enrich_contact(payload: dict[str, Any], validate_email: bool = True) -> ContactResult:
    row_id = payload.get("Id") or payload.get("row_id") or ""
    domain = compact(payload.get("canonical_domain")).lower().removeprefix("www.")
    if not domain:
        return ContactResult(row_id=row_id, contact_search_status="skipped", contact_search_reason="missing_canonical_domain")

    if payload.get("site_fast_path_only"):
        candidates = extract_candidates_from_website_content(
            payload.get("website_content") if isinstance(payload.get("website_content"), str) else "",
            compact(payload.get("company_name")),
            compact(payload.get("company_homepage_name")),
            domain,
            compact(payload.get("best_url"), 500),
        )
    else:
        candidates = extract_candidates(payload)
    candidate_dicts = [candidate.to_dict() for candidate in candidates]
    search_evidence = build_contact_search_evidence(payload, candidate_dicts)
    if not candidates:
        if search_evidence["query_attempts_count"] and search_evidence["search_error_count"] >= search_evidence["query_attempts_count"]:
            return ContactResult(
                row_id=row_id,
                contact_search_status="failed",
                contact_search_reason="search_provider_failed",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_validation_evidence={
                    "configured": bool(os.getenv("NO2BOUNCE_API_TOKEN", "").strip()),
                    "skipped": "search_provider_failed",
                },
            )
        return ContactResult(
            row_id=row_id,
            contact_search_status="contact_not_found",
            contact_search_reason="no_validated_person_found",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_validation_evidence={"configured": bool(os.getenv("NO2BOUNCE_API_TOKEN", "").strip()), "skipped": "no_candidates"},
        )

    email_candidates: list[dict[str, Any]] = []
    for candidate in candidates[:5]:
        if candidate.confidence not in {"High", "Medium"}:
            continue
        generated = email_permutations(candidate, domain)[:14]
        for item in generated:
            item.update({"name": candidate.name, "role": candidate.role, "source_url": candidate.source_url})
        email_candidates.extend(generated)
        if generated:
            break

    if not email_candidates:
        return ContactResult(
            row_id=row_id,
            contact_search_status="contact_not_found",
            contact_search_reason="no_safe_email_permutations",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_candidates=email_candidates,
        )

    validation_evidence: dict[str, Any] = {"configured": bool(os.getenv("NO2BOUNCE_API_TOKEN", "").strip()), "dry_run": not validate_email}
    if not validate_email:
        return ContactResult(
            row_id=row_id,
            contact_search_status="contact_not_found",
            contact_search_reason="dry_run_email_validation_skipped",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_candidates=email_candidates,
            email_validation_evidence=validation_evidence,
        )

    validation = validate_no2bounce([item["email"] for item in email_candidates])
    validation_evidence = validation
    if not validation.get("configured"):
        return ContactResult(
            row_id=row_id,
            contact_search_status="failed",
            contact_search_reason="email_validation_not_configured",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_candidates=email_candidates,
            email_validation_status="not_configured",
            email_validation_evidence=validation_evidence,
        )
    if validation.get("error"):
        return ContactResult(
            row_id=row_id,
            contact_search_status="failed",
            contact_search_reason="email_validation_provider_failed",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_candidates=email_candidates,
            email_validation_status=str(validation.get("error")),
            email_validation_evidence=validation_evidence,
        )

    by_email = {item["email"].lower(): item for item in email_candidates}
    for result in validation.get("results", []):
        email = result_email(result)
        if email in by_email:
            decision = email_decision(result, bool(by_email[email].get("name")))
            by_email[email]["validation_result"] = result
            by_email[email]["status"] = status_text(result) or "validated"
            by_email[email]["decision"] = decision
        if email in by_email and by_email[email].get("decision") in {"sendable", "risky_sendable"}:
            selected_candidate = next((candidate for candidate in candidates if candidate.name == by_email[email]["name"]), candidates[0])
            by_email[email]["accepted"] = True
            decision = str(by_email[email].get("decision") or "sendable")
            return ContactResult(
                row_id=row_id,
                contact_search_status="contact_found",
                contact_search_reason=f"{decision}_person_specific_email_found",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_candidates=list(by_email.values()),
                selected_contact_name=selected_candidate.name,
                selected_contact_role=selected_candidate.role,
                selected_contact_seniority=selected_candidate.seniority,
                selected_contact_source_url=selected_candidate.source_url,
                selected_contact_confidence=selected_candidate.confidence,
                validated_email=email,
                email_validation_status=decision,
                email_validation_evidence=validation_evidence,
            )

    return ContactResult(
        row_id=row_id,
        contact_search_status="contact_not_found",
        contact_search_reason="no_deliverable_person_specific_email_found",
        contact_candidates=candidate_dicts,
        contact_search_evidence=search_evidence,
        email_candidates=list(by_email.values()),
        email_validation_status="no_deliverable_email",
        email_validation_evidence=validation_evidence,
    )


def build_patch(result: ContactResult) -> dict[str, Any]:
    return {
        "Id": result.row_id,
        "contact_search_status": result.contact_search_status,
        "contact_search_reason": result.contact_search_reason,
        "contact_candidates_json": json.dumps(result.contact_candidates, ensure_ascii=False),
        "contact_search_evidence_json": json.dumps(result.contact_search_evidence, ensure_ascii=False),
        "selected_contact_name": result.selected_contact_name,
        "selected_contact_role": result.selected_contact_role,
        "selected_contact_seniority": result.selected_contact_seniority,
        "selected_contact_source_url": result.selected_contact_source_url,
        "selected_contact_confidence": result.selected_contact_confidence,
        "email_candidates_json": json.dumps(result.email_candidates, ensure_ascii=False),
        "validated_email": result.validated_email,
        "email_validation_status": result.email_validation_status,
        "email_validation_provider": result.email_validation_provider,
        "email_validation_evidence_json": json.dumps(result.email_validation_evidence, ensure_ascii=False),
        "contact_search_finished_at": now_iso(),
    }


def build_role_queries(
    company_name: str,
    homepage_name: str,
    canonical_domain: str,
    website_content: str = "",
    max_queries: int = 6,
) -> list[dict[str, Any]]:
    def grouped_terms(values: list[str]) -> str:
        terms = [f'"{compact(value, 120)}"' for value in values if compact(value, 120)]
        return f"({' OR '.join(terms)})" if terms else ""

    cleaned_company = compact(company_name, 160).replace('"', "")
    cleaned_homepage = compact(homepage_name, 160).replace('"', "")
    cleaned_domain = compact(canonical_domain, 160).lower().removeprefix("www.")
    names = [cleaned_company]
    company_lower = cleaned_company.lower()
    homepage_lower = cleaned_homepage.lower()
    if cleaned_homepage and homepage_lower != company_lower and company_lower not in homepage_lower and homepage_lower not in company_lower:
        names.append(cleaned_homepage)
    names_clause = grouped_terms(list(dict.fromkeys(name for name in names if name)))

    bundles = [
        {
            "bucket": "c_suite",
            "seniority": "executive",
            "priority": 1,
            "role": "CEO",
            "company_roles": ["CEO", "Founder", "Owner", "Managing Director", "Executive Director", "General Manager"],
            "domain_terms": ["Founder", "Owner", "CEO", "Managing Director", "Executive Director", "General Manager"],
        },
        {
            "bucket": "clinic_leadership",
            "seniority": "manager",
            "priority": 2,
            "role": "Medical Director",
            "company_roles": ["Medical Director", "Principal Doctor", "Head Doctor", "Clinic Manager", "Clinical Manager", "Practice Manager", "Operations Manager", "Clinic Operations Manager"],
            "domain_terms": ["about us", "team", "leadership", "management", "founders", "doctors", "contact"],
        },
        {
            "bucket": "compliance_privacy_security",
            "seniority": "senior_manager",
            "priority": 3,
            "role": "DPO",
            "company_roles": ["DPO", "Data Protection Officer", "Compliance Manager", "Risk Manager", "CISO", "Head of Security", "Cybersecurity Manager", "IT Manager", "Head of IT", "CTO", "Technology Manager", "Systems Manager"],
            "domain_terms": ["DPO", "Data Protection Officer", "Compliance Manager", "Risk Manager", "CISO", "IT Manager", "Head of IT", "CTO"],
        },
    ]

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    effective_max_queries = min(max_queries, 4) if compact(website_content, 2000) else max_queries
    for bundle in bundles:
        raw_queries: list[str] = []
        if names_clause:
            raw_queries.append(f"{names_clause} Singapore {grouped_terms(bundle['company_roles'])}".strip())
        if cleaned_domain:
            raw_queries.append(f"site:{cleaned_domain} {grouped_terms(bundle['domain_terms'])}".strip())
        for query in raw_queries:
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(
                {
                    "query": query,
                    "role": bundle["role"],
                    "role_bucket": bundle["bucket"],
                    "role_priority": bundle["priority"],
                    "seniority": bundle["seniority"],
                }
            )
            if len(queries) >= effective_max_queries:
                return queries
    return queries
