from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

try:
    import dns.resolver  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional dependency
    dns = None  # type: ignore[assignment]

HONORIFICS_RE = re.compile(r"^(?:dr|doctor|mr|mrs|ms|miss|mdm|prof|professor|assoc\.?\s*prof|a/?prof)\.?\s+", re.I)
NAME_TOKEN_RE = r"[A-Z][a-zA-Z'’-]+"
NAME_CAPTURE_RE = rf"({NAME_TOKEN_RE}(?:[ \t]+{NAME_TOKEN_RE}){{1,4}})"
NAME_RE = re.compile(rf"\b(?:Dr\.?\s+|Mr\.?\s+|Mrs\.?\s+|Ms\.?\s+|Prof\.?\s+)?{NAME_CAPTURE_RE}\b")
EMAIL_SAFE_RE = re.compile(r"[^a-z0-9]")
EMAIL_SYNTAX_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
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
    {"bucket": "c_suite", "seniority": "executive", "priority": 1, "roles": ["CEO", "Chief Executive Officer", "Chief Executive", "Founder", "Co-founder", "Owner", "Managing Director", "Executive Director", "General Manager", "Chairman", "Chairperson", "President", "Vice President", "Board Chair", "Board Member", "Board Director", "Board of Directors", "Trustee", "Honorary Secretary", "Secretary", "Treasurer"]},
    {"bucket": "compliance_privacy_security", "seniority": "senior_manager", "priority": 2, "roles": ["DPO", "Data Protection Officer", "Compliance Manager", "Risk Manager", "CISO", "Chief Information Security Officer", "Head of Security", "Cybersecurity Manager"]},
    {"bucket": "it_technology", "seniority": "manager", "priority": 3, "roles": ["IT Manager", "Head of IT", "CTO", "Chief Technology Officer", "Technology Manager", "Systems Manager"]},
    {"bucket": "operations", "seniority": "manager", "priority": 4, "roles": ["Operations Manager", "Ops Manager", "Chief Operating Officer", "Clinic Operations Manager", "Practice Manager", "Programme Director", "Program Director", "Programme Manager", "Program Manager", "Centre Manager", "Center Manager", "Corporate Services Manager", "Community Partnerships Manager", "Volunteer Manager", "Fundraising Manager", "Social Work Manager", "Head of Social Work", "Care Services Manager"]},
    {"bucket": "clinic_leadership", "seniority": "manager", "priority": 5, "roles": ["Clinic Manager", "Clinical Manager", "Clinical Director", "Medical Director", "Head Doctor", "Principal Doctor", "Doctor in charge", "Doctor-in-Charge", "Senior Doctor", "Senior Consultant", "Consultant Physician", "Consultant Dermatologist", "Dermatologist", "Consultant Cardiologist", "Cardiologist", "Specialist"]},
    {"bucket": "care_clinical", "seniority": "manager", "priority": 6, "roles": ["Head of Nursing", "Nursing Manager", "Clinical Lead", "Care Manager"]},
    {"bucket": "admin_hr", "seniority": "manager", "priority": 7, "roles": ["Admin Manager", "Administration Manager", "Office Manager", "HR Manager", "Human Resources Manager", "People Manager"]},
]
ROLE_TERMS = {role.lower(): group for group in ROLE_BUCKETS for role in group["roles"]}
PROFILE_LINE_ONLY_ROLES = {
    "senior consultant",
    "consultant physician",
    "consultant dermatologist",
    "dermatologist",
    "consultant cardiologist",
    "cardiologist",
    "specialist",
}
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
    "apex",
    "american",
    "appointed",
    "adjunct",
    "active",
    "ageing",
    "audiologist",
    "australasian",
    "bank",
    "body",
    "bova",
    "clinic",
    "centre",
    "center",
    "company",
    "commercial",
    "compounding",
    "contact",
    "chief",
    "council",
    "director",
    "dispute",
    "doctor",
    "doctors",
    "doing",
    "general",
    "graduate",
    "guide",
    "health",
    "hearing",
    "holdings",
    "home",
    "international",
    "institution",
    "laser",
    "learn",
    "lecturer",
    "lifestyle",
    "magazine",
    "manager",
    "managing",
    "medical",
    "more",
    "most",
    "national",
    "novena",
    "org",
    "pharmacy",
    "podcast",
    "practitioner",
    "promising",
    "prep",
    "profile",
    "pte",
    "road",
    "resolution",
    "sales",
    "senior",
    "seminar",
    "service",
    "services",
    "singapore",
    "skin",
    "team",
    "trainer",
    "treatments",
    "ltd",
    "ceo",
    "cto",
    "ciso",
    "executive",
    "founder",
    "group",
    "head",
    "owner",
    "symposium",
    "uk",
    "usa",
    "europe",
    "canada",
}
CANDIDATE_TITLE_WORDS = {
    "past",
    "president",
    "speaker",
    "graduate",
    "lecturer",
    "manager",
    "director",
    "founder",
    "owner",
    "head",
    "chief",
}
WEAK_THIRD_PARTY_SOURCE_HINTS = (
    "conference",
    "conferences",
    "congress",
    "event",
    "events",
    "summit",
    "symposium",
    "webinar",
    "speaker",
)
LLM_VERIFIER_PROMPT_VERSION = "v1"
TARGET_ROLE_BUCKETS = [group["bucket"] for group in ROLE_BUCKETS]
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
    "mbchb",
    "mmed",
    "mrcp",
    "mrcs",
    "md",
    "phd",
    "si",
}
ROLE_ONLY_NAME_WORDS = CANDIDATE_TITLE_WORDS | {
    "admin",
    "administration",
    "board",
    "care",
    "cardiologist",
    "clinical",
    "clinic",
    "consultant",
    "dermatologist",
    "doctor",
    "doctors",
    "executive",
    "general",
    "hr",
    "human",
    "it",
    "lead",
    "management",
    "manager",
    "medical",
    "nursing",
    "office",
    "operations",
    "pain",
    "physician",
    "practice",
    "programme",
    "program",
    "resources",
    "security",
    "senior",
    "specialist",
    "technology",
}
OPENSERP_ROUTE_MAP = {
    "openserp_duckduckgo": "/duck/search",
    "openserp_google": "/google/search",
}
PROVIDER_DISABLE_SECONDS = {
    "circuit_open": 600,
    "timeout": 90,
}
PROVIDER_HEALTH_WINDOW = 20
PROVIDER_TIMEOUT_DISABLE_THRESHOLD = 3
PROVIDER_TIMEOUT_WINDOW_SECONDS = 180
CIRCUIT_OPEN_ERROR_HINTS = ("circuit_open", "circuit open", "circuit breaker is open", "engine temporarily disabled")
PERSISTENT_DISABLE_REASONS = {"circuit_open"}
PROVIDER_LOCK = threading.Lock()


def new_provider_state(existing: dict[str, Any] | None = None, preserve_non_timeout: bool = False) -> dict[str, Any]:
    state = {
        "total_recent_queries": 0,
        "success_count": 0,
        "empty_result_count": 0,
        "circuit_open_count": 0,
        "timeout_count": 0,
        "http_error_count": 0,
        "last_error": "",
        "disabled_until": 0.0,
        "disabled_reason": "",
        "recent_outcomes": deque(maxlen=PROVIDER_HEALTH_WINDOW),
        "recent_timeout_timestamps": deque(maxlen=PROVIDER_HEALTH_WINDOW),
    }
    if preserve_non_timeout and existing:
        now_ts = time.time()
        disabled_until = float(existing.get("disabled_until") or 0.0)
        disabled_reason = compact(existing.get("disabled_reason"), 80)
        if disabled_reason in PERSISTENT_DISABLE_REASONS and disabled_until > now_ts:
            state["disabled_until"] = disabled_until
            state["disabled_reason"] = disabled_reason
            state["last_error"] = compact(existing.get("last_error"), 300)
            state["circuit_open_count"] = int(existing.get("circuit_open_count") or 0)
            state["http_error_count"] = int(existing.get("http_error_count") or 0)
    return state


PROVIDER_STATE = {provider: new_provider_state() for provider in (*OPENSERP_ROUTE_MAP.keys(), "serper_emergency")}
PROVIDER_RESET_TOKEN = ""
VALIDATION_CACHE: dict[str, dict[str, Any]] = {}
MX_CACHE: dict[str, bool | None] = {}


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
class CandidateVerification:
    accepted: list[ContactCandidate] = field(default_factory=list)
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    needs_more_evidence_candidates: list[dict[str, Any]] = field(default_factory=list)
    previously_tried_candidate_details: list[dict[str, Any]] = field(default_factory=list)
    raw_candidates: list[dict[str, Any]] = field(default_factory=list)
    verifier: str = "deterministic"
    prompt_version: str = LLM_VERIFIER_PROMPT_VERSION
    error: str = ""


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
    email_validation_provider: str = "anymail_finder"
    email_validation_evidence: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact(value: Any, limit: int = 2000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def provider_cooldown_seconds(disabled_until: float, now_ts: float | None = None) -> int:
    current = time.time() if now_ts is None else now_ts
    return max(0, int(math.ceil(max(0.0, float(disabled_until) - current))))


def reset_provider_state(reset_token: str = "", preserve_non_timeout: bool = False) -> None:
    global PROVIDER_RESET_TOKEN
    normalized = compact(reset_token, 160)
    with PROVIDER_LOCK:
        for provider in list(PROVIDER_STATE):
            PROVIDER_STATE[provider] = new_provider_state(
                existing=PROVIDER_STATE.get(provider),
                preserve_non_timeout=preserve_non_timeout,
            )
        PROVIDER_RESET_TOKEN = normalized


def ensure_provider_state(reset_token: str) -> None:
    normalized = compact(reset_token, 160)
    if not normalized:
        return
    with PROVIDER_LOCK:
        if normalized == PROVIDER_RESET_TOKEN:
            return
    reset_provider_state(normalized, preserve_non_timeout=True)


def trim_recent_timeouts(state: dict[str, Any], now_ts: float) -> list[float]:
    timestamps = state["recent_timeout_timestamps"]
    while timestamps and now_ts - float(timestamps[0]) > PROVIDER_TIMEOUT_WINDOW_SECONDS:
        timestamps.popleft()
    return list(timestamps)


def detect_provider_flags(error_text: str) -> bool:
    lowered = compact(error_text, 300).lower()
    return any(hint in lowered for hint in CIRCUIT_OPEN_ERROR_HINTS)


def provider_health_snapshot() -> dict[str, dict[str, Any]]:
    return {provider: provider_health(provider) for provider in (*OPENSERP_ROUTE_MAP.keys(), "serper_emergency")}


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


def company_fragment_match(name: str, company_name: str, homepage_name: str, canonical_domain: str) -> bool:
    candidate = normalize_company(name)
    if not candidate:
        return False
    candidate_tokens = candidate.split()
    if len(candidate_tokens) < 2:
        return False
    domain_root = canonical_domain.split(".")[0].replace("-", " ") if canonical_domain else ""
    for option in (normalize_company(company_name), normalize_company(homepage_name), normalize_company(domain_root)):
        option_tokens = option.split()
        if len(option_tokens) >= len(candidate_tokens) and option_tokens[: len(candidate_tokens)] == candidate_tokens:
            return True
    return False


def reject_candidate_name(name: str, company_name: str, homepage_name: str, canonical_domain: str) -> bool:
    return (
        not name
        or name in NOISE_NAME_TERMS
        or company_match(name, company_name, homepage_name, canonical_domain)
        or company_fragment_match(name, company_name, homepage_name, canonical_domain)
    )


def company_near_name(evidence: str, name_start: int, name_end: int, company_name: str, homepage_name: str, canonical_domain: str) -> bool:
    window = evidence[max(0, name_start - 140) : min(len(evidence), name_end + 140)]
    return company_match(window, company_name, homepage_name, canonical_domain)


def role_points_to_other_org(evidence: str, name_start: int, name_end: int, company_name: str, homepage_name: str, canonical_domain: str) -> bool:
    window = evidence[name_end : min(len(evidence), name_end + 140)]
    match = re.search(
        r"\b(?:as\s+well\s+as\s+)?(?:CEO|Founder|Owner|Managing Director|Executive Director|General Manager|Medical Director)"
        r"(?:\s+and\s+(?:CEO|Founder|Owner|Managing Director|Executive Director|General Manager|Medical Director))*"
        r"(?:\s+of)?\s+([^,|.]{2,90})",
        window,
        re.I,
    )
    if not match:
        return False
    org = clean_name(match.group(1))
    if not org or parse_name(org):
        return False
    return not (
        company_match(org, company_name, homepage_name, canonical_domain)
        or company_fragment_match(org, company_name, homepage_name, canonical_domain)
    )


def role_match(text: str, query_role: str = "") -> tuple[str, dict[str, Any] | None]:
    haystack = compact(text).lower()
    if query_role and re.search(rf"(?<![a-z0-9]){re.escape(query_role.lower())}s?(?![a-z0-9])", haystack):
        return query_role, ROLE_TERMS.get(query_role.lower())
    for role, group in ROLE_TERMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(role)}s?(?![a-z0-9])", haystack):
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
    if any(part in {"and", "the", "our", "of", "in", "for", "to", "with", "from"} for part in lowered):
        return None
    if any(part in {"dr", "doctor", "mr", "mrs", "ms", "miss", "mdm", "prof", "professor"} for part in lowered):
        return None
    if any(part in NOISE_NAME_WORDS for part in lowered):
        return None
    if any(part in CREDENTIAL_WORDS for part in lowered):
        return None
    if len(parts) <= 2 and all(part in CANDIDATE_TITLE_WORDS for part in lowered):
        return None
    if all(part in ROLE_ONLY_NAME_WORDS for part in lowered):
        return None
    if sum(1 for part in lowered if len(part) == 1) > 1:
        return None
    if len(parts) == 2 and all(len(part) <= 2 for part in parts):
        return None
    return parts[0], parts[-1]


def probable_human_name(name: str) -> bool:
    cleaned = clean_name(name)
    parts = [part for part in cleaned.replace("’", "'").split() if part]
    if not parse_name(cleaned):
        return False
    lowered = [part.lower().strip("-'") for part in parts]
    if any(part in NOISE_NAME_WORDS for part in lowered):
        return False
    if len(parts) <= 2 and all(part in CANDIDATE_TITLE_WORDS for part in lowered):
        return False
    if any(re.search(r"(?:pte|ltd|llp|inc|bank|clinic|centre|center|group|services?)$", part, re.I) for part in parts):
        return False
    if len(parts) <= 2 and any(part in {"bank", "clinic", "group", "centre", "center"} for part in lowered):
        return False
    return True


def weak_third_party_source(url: str) -> bool:
    domain = domain_from_url(url)
    path = urlparse(url if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I) else "https://" + url).path.lower()
    haystack = f"{domain} {path}"
    return any(hint in haystack for hint in WEAK_THIRD_PARTY_SOURCE_HINTS)


def non_official_candidate_company_link(
    evidence: str,
    name_start: int,
    name_end: int,
    role: str,
    company_name: str,
    homepage_name: str,
    canonical_domain: str,
) -> bool:
    after_name = evidence[name_end : min(len(evidence), name_end + 220)]
    if role_points_to_other_org(evidence, name_start, name_end, company_name, homepage_name, canonical_domain):
        return False
    if company_match(after_name, company_name, homepage_name, canonical_domain):
        return True
    before_name = evidence[max(0, name_start - 120) : name_start]
    return company_match(before_name, company_name, homepage_name, canonical_domain) and role_near_name(evidence, name_start, name_end, role)


def name_parts(name: str) -> list[str]:
    cleaned = clean_name(name)
    return [part for part in cleaned.replace("’", "'").split() if part]


def normalize_person_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_name(name).lower()).strip()


def normalized_name_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {normalized for normalized in (normalize_person_name(value) for value in values) if normalized}


def normalized_email_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    output: set[str] = set()
    for value in values:
        normalized = compact(value, 320).lower()
        if normalized:
            output.add(normalized)
    return output


def email_syntax_valid(value: str) -> bool:
    return bool(EMAIL_SYNTAX_RE.fullmatch(compact(value, 320).lower()))


def domain_has_mx_record(domain: str) -> bool | None:
    normalized = compact(domain, 320).lower().removeprefix("www.")
    if not normalized:
        return None
    if normalized in MX_CACHE:
        return MX_CACHE[normalized]
    if dns is None:
        MX_CACHE[normalized] = None
        return None
    try:
        answers = dns.resolver.resolve(normalized, "MX")
        MX_CACHE[normalized] = bool(answers)
    except Exception:
        MX_CACHE[normalized] = False
    return MX_CACHE[normalized]


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


def profile_line_candidates(
    raw_content: str,
    company_name: str,
    homepage_name: str,
    canonical_domain: str,
    best_url: str,
    blocked_names: set[str],
    seen: set[tuple[str, str]],
) -> list[ContactCandidate]:
    lines = [compact(line, 240) for line in str(raw_content or "").splitlines()]
    lines = [line for line in lines if line]
    candidates: list[ContactCandidate] = []
    for index, line in enumerate(lines):
        if len(line) > 90:
            continue
        possible_names: list[tuple[str, int, int]] = []
        if probable_human_name(line):
            possible_names.append((clean_name(line), 0, len(line)))
        else:
            for match in NAME_RE.finditer(line):
                name = clean_name(match.group(1))
                if probable_human_name(name):
                    possible_names.append((name, match.start(1), match.end(1)))
        if not possible_names:
            continue

        context_lines = lines[max(0, index - 2) : min(len(lines), index + 3)]
        context = " | ".join(context_lines)
        role = ""
        group = None
        for candidate_context in (
            line,
            lines[index + 1] if index + 1 < len(lines) else "",
            lines[index - 1] if index > 0 else "",
            " | ".join(lines[index + 1 : min(len(lines), index + 3)]),
            " | ".join(lines[max(0, index - 2) : index]),
            context,
        ):
            role, group = role_match(candidate_context)
            if group:
                break
        if not group:
            continue
        if role.lower() in PROFILE_LINE_ONLY_ROLES and not re.search(r"\b(?:Dr|Doctor|Prof|Professor)\.?\s+", line):
            continue
        if not company_match(raw_content, company_name, homepage_name, canonical_domain):
            continue

        for name, _, _ in possible_names:
            if reject_candidate_name(name, company_name, homepage_name, canonical_domain):
                continue
            if normalize_person_name(name) in blocked_names:
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
                    evidence_text=context,
                    confidence="High",
                    confidence_score=0.95,
                    company_match=True,
                    first_name=first_name,
                    last_name=last_name,
                )
            )
    return candidates


def extract_candidates_from_website_content(
    website_content: str,
    company_name: str,
    homepage_name: str,
    canonical_domain: str,
    best_url: str,
    excluded_names: set[str] | None = None,
) -> list[ContactCandidate]:
    raw_content = str(website_content or "")[:50000]
    normalized_content = compact(raw_content, 50000)
    if not normalized_content or not company_match(normalized_content, company_name, homepage_name, canonical_domain):
        return []

    candidates: list[ContactCandidate] = []
    seen: set[tuple[str, str]] = set()
    blocked_names = excluded_names or set()
    for group in ROLE_BUCKETS:
        for role in group["roles"]:
            if role.lower() in PROFILE_LINE_ONLY_ROLES:
                continue
            for name, name_start, name_end in name_matches_for_role(raw_content, role):
                if reject_candidate_name(name, company_name, homepage_name, canonical_domain):
                    continue
                if re.search(r"[’']s$", name):
                    continue
                if normalize_person_name(name) in blocked_names:
                    continue
                if role_points_to_other_org(raw_content, name_start, name_end, company_name, homepage_name, canonical_domain):
                    continue
                if not role_near_name(raw_content, name_start, name_end, role):
                    continue
                if not probable_human_name(name):
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
            if reject_candidate_name(name, company_name, homepage_name, canonical_domain):
                continue
            if re.search(r"[’']s$", name):
                continue
            if normalize_person_name(name) in blocked_names:
                continue
            if any(normalize_person_name(candidate.name) == normalize_person_name(name) for candidate in candidates):
                continue
            key = (name.lower(), "clinical lead")
            if key in seen:
                continue
            if not probable_human_name(name):
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
                if reject_candidate_name(name, company_name, homepage_name, canonical_domain):
                    continue
                if re.search(r"[’']s$", name):
                    continue
                if normalize_person_name(name) in blocked_names:
                    continue
                key = (name.lower(), "practice manager")
                if key in seen:
                    continue
                if not probable_human_name(name):
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
    candidates.extend(
        profile_line_candidates(
            raw_content,
            company_name,
            homepage_name,
            canonical_domain,
            best_url,
            blocked_names,
            set(),
        )
    )
    by_name: dict[str, ContactCandidate] = {}
    for candidate in candidates:
        normalized_name = normalize_person_name(candidate.name)
        existing = by_name.get(normalized_name)
        if not existing or (-candidate.confidence_score, candidate.role_priority) < (-existing.confidence_score, existing.role_priority):
            by_name[normalized_name] = candidate
    deduped = list(by_name.values())
    deduped.sort(key=lambda item: (item.role_priority, -item.confidence_score, item.name.lower()))
    return deduped


def source_type(url: str, canonical_domain: str) -> str:
    domain = domain_from_url(url)
    if canonical_domain and domain.endswith(canonical_domain):
        return "official_domain"
    if "linkedin.com" in domain:
        return "public_linkedin_snippet"
    if any(label in domain for label in ("doctor", "health", "clinic", "medical", "dental")):
        return "professional_public_page"
    return "public_search_result"


def source_strength(url: str, source_type_value: str, evidence: str, company_name: str, homepage_name: str, canonical_domain: str) -> str:
    domain = domain_from_url(url)
    lowered = compact(evidence, 1200).lower()
    if source_type_value == "official_domain":
        return "official_domain"
    if "linkedin.com" in domain and company_match(evidence, company_name, homepage_name, canonical_domain):
        if any(term in lowered for term in ("comment", "comments", "likes", "activity", "report this")):
            return "very_weak_activity_snippet"
        return "strong_professional_profile"
    if any(site in domain for site in ("facebook.com", "instagram.com", "youtube.com")) and company_match(evidence, company_name, homepage_name, canonical_domain):
        return "official_social"
    if source_type_value == "professional_public_page" and company_match(evidence, company_name, homepage_name, canonical_domain):
        return "professional_directory"
    if weak_third_party_source(url):
        return "very_weak_event_or_speaker_page"
    return "weak_snippet"


def raw_candidate_key(raw_candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        normalize_person_name(raw_candidate.get("raw_name", "")),
        compact(raw_candidate.get("role_detected"), 100).lower(),
        compact(raw_candidate.get("source_url"), 500).lower(),
    )


def raw_candidate_from_match(
    *,
    raw_name: str,
    role: str,
    group: dict[str, Any],
    source_url: str,
    source_type_value: str,
    title: str,
    snippet: str,
    evidence: str,
    query: str,
    company_name: str,
    homepage_name: str,
    canonical_domain: str,
    name_start: int,
    name_end: int,
) -> dict[str, Any]:
    return {
        "raw_name": clean_name(raw_name),
        "role_detected": role,
        "role_bucket": group.get("bucket", ""),
        "role_priority": int(group.get("priority") or 0),
        "seniority": group.get("seniority", ""),
        "source_url": source_url,
        "source_type": source_type_value,
        "source_strength": source_strength(source_url, source_type_value, evidence, company_name, homepage_name, canonical_domain),
        "title": compact(title, 400),
        "snippet": compact(snippet, 1200),
        "evidence_text": compact(evidence, 1600),
        "query": compact(query, 300),
        "name_start": name_start,
        "name_end": name_end,
    }


def extract_raw_candidates_from_search(payload: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = compact(payload.get("company_name"))
    homepage_name = compact(payload.get("company_homepage_name"))
    canonical_domain = compact(payload.get("canonical_domain")).lower().removeprefix("www.")
    attempts = payload.get("search_attempts") if isinstance(payload.get("search_attempts"), list) else []
    raw_candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for attempt in attempts:
        query_role = compact(attempt.get("role"))
        query = compact(attempt.get("query"), 300)
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
            for name, name_start, name_end in name_matches_for_role(evidence, matched_role):
                raw_candidate = raw_candidate_from_match(
                    raw_name=name,
                    role=matched_role,
                    group=group,
                    source_url=url,
                    source_type_value=stype,
                    title=title,
                    snippet=snippet,
                    evidence=evidence,
                    query=query,
                    company_name=company_name,
                    homepage_name=homepage_name,
                    canonical_domain=canonical_domain,
                    name_start=name_start,
                    name_end=name_end,
                )
                key = raw_candidate_key(raw_candidate)
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                raw_candidates.append(raw_candidate)
    raw_candidates.sort(key=lambda item: (int(item.get("role_priority") or 0), item.get("raw_name", "").lower()))
    return raw_candidates[:30]


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
    excluded_names = normalized_name_set(payload.get("excluded_candidate_names"))
    candidates = extract_candidates_from_website_content(
        website_content,
        company_name,
        homepage_name,
        canonical_domain,
        best_url,
        excluded_names=excluded_names,
    )
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
            if stype != "official_domain" and weak_third_party_source(url):
                continue
            evidence = compact(" | ".join(part for part in (title, snippet) if part), 1600)
            matched_role, group = role_match(evidence, query_role=query_role)
            if not group:
                continue
            if not company_match(evidence + " " + url, company_name, homepage_name, canonical_domain):
                continue
            for name, name_start, name_end in name_matches_for_role(evidence, matched_role):
                if reject_candidate_name(name, company_name, homepage_name, canonical_domain):
                    continue
                if normalize_person_name(name) in excluded_names:
                    continue
                if role_points_to_other_org(evidence, name_start, name_end, company_name, homepage_name, canonical_domain):
                    continue
                if not role_near_name(evidence, name_start, name_end, matched_role):
                    continue
                if stype != "official_domain" and not non_official_candidate_company_link(
                    evidence,
                    name_start,
                    name_end,
                    matched_role,
                    company_name,
                    homepage_name,
                    canonical_domain,
                ):
                    continue
                if not probable_human_name(name):
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
    compact_parts = [safe_local_part(part) for part in parts]
    family = compact_parts[0]
    given_tail = compact_parts[-1]
    source_given = "".join(compact_parts[1:])
    western_first = safe_local_part(candidate.first_name)
    western_last = safe_local_part(candidate.last_name)

    output: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(pattern: str, local: str, *, pattern_family: str, name_order: str) -> None:
        if not local or local in GENERIC_LOCAL_PARTS or local in seen:
            return
        seen.add(local)
        output.append(
            {
                "email": f"{local}@{domain}",
                "pattern": pattern,
                "pattern_family": pattern_family,
                "name_order": name_order,
                "status": "not_validated",
            }
        )

    if len(parts) == 2:
        first = compact_parts[0]
        last = compact_parts[-1]
        if western_first and western_last:
            first = western_first
            last = western_last
        add("first.last", f"{first}.{last}", pattern_family="western", name_order="given_family")
        add("first", first, pattern_family="western", name_order="given_family")
        add("firstlast", f"{first}{last}", pattern_family="western", name_order="given_family")
        add("f.last", f"{first[0]}.{last}", pattern_family="western", name_order="given_family")
        add("firstl", f"{first}{last[0]}", pattern_family="western", name_order="given_family")
        add("flast", f"{first[0]}{last}", pattern_family="western", name_order="given_family")
        add("last.first", f"{last}.{first}", pattern_family="western", name_order="family_given")
        add("first_last", f"{first}_{last}", pattern_family="western", name_order="given_family")
        add("first-last", f"{first}-{last}", pattern_family="western", name_order="given_family")
        return output

    add("family.given_source", f"{family}.{source_given}", pattern_family="source_order", name_order="family_given")
    add("family.given_tail_source", f"{family}.{given_tail}", pattern_family="source_order", name_order="family_given")
    add("familygiven_source", f"{family}{source_given}", pattern_family="source_order", name_order="family_given")
    add("familygiven_tail_source", f"{family}{given_tail}", pattern_family="source_order", name_order="family_given")

    western_variants = []
    if given_tail and family:
        western_variants.append((given_tail, family, "western_last_token"))
    if western_first and western_last:
        western_variants.append((western_first, western_last, "western_candidate_fields"))

    for first, last, name_order in western_variants:
        add("first.last", f"{first}.{last}", pattern_family="western", name_order=name_order)
        add("firstlast", f"{first}{last}", pattern_family="western", name_order=name_order)
        add("first_last", f"{first}_{last}", pattern_family="western", name_order=name_order)
        add("first-last", f"{first}-{last}", pattern_family="western", name_order=name_order)
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


NO2BOUNCE_DOWNLOAD_URL_KEYS = {
    "downloadfile",
    "download_file",
    "downloadurl",
    "download_url",
    "resulturl",
    "result_url",
    "reporturl",
    "report_url",
    "signedurl",
    "signed_url",
}


def no2bounce_download_url_candidate(key: Any, value: Any) -> str:
    normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
    if normalized_key not in {re.sub(r"[^a-z0-9]+", "", item) for item in NO2BOUNCE_DOWNLOAD_URL_KEYS}:
        return ""
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return ""


def find_no2bounce_download_url(payload: Any) -> str:
    if isinstance(payload, dict):
        for key, value in payload.items():
            download_url = no2bounce_download_url_candidate(key, value)
            if download_url:
                return download_url
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
            if no2bounce_download_url_candidate(key, value):
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
    raw_text = response.text.lstrip("\ufeff").strip()
    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type or raw_text.startswith(("{", "[")):
        try:
            return extract_no2bounce_results(response.json())
        except ValueError:
            return []
    csv_text = raw_text
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
    for key in ("results", "apiResponse", "api_response", "validationResults", "validation_results", "data", "emails", "emailList", "validations", "records"):
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


def no2bounce_progress(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    output: dict[str, Any] = {}
    for key in (
        "taskId",
        "trackingId",
        "totalEmails",
        "completedEmails",
        "totalRecord",
        "overallStatus",
        "percent",
        "creditDebited",
        "totalCredit",
        "deliverability",
        "catchAll",
        "Deliverable",
        "Undeliverable",
        "Deliverable/AcceptAll",
        "UnDeliverable/AcceptAll",
        "Risky/AcceptAll",
        "invalid",
        "bounce",
        "spam",
    ):
        value = dict_get_case_insensitive(data, key)
        if value is not None:
            output[key] = value
    return output


def no2bounce_count(progress: dict[str, Any], key: str) -> int:
    value = dict_get_case_insensitive(progress, key)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def no2bounce_has_sendable_aggregate(progress: dict[str, Any]) -> bool:
    return (
        no2bounce_count(progress, "Deliverable") > 0
        or no2bounce_count(progress, "Deliverable/AcceptAll") > 0
        or no2bounce_count(progress, "Risky/AcceptAll") > 0
        or no2bounce_count(progress, "deliverability") > 0
    )


def no2bounce_partial_rejected_results(emails: list[str], progress: dict[str, Any]) -> list[dict[str, Any]]:
    if not progress or no2bounce_has_sendable_aggregate(progress):
        return []
    completed = (
        no2bounce_count(progress, "Undeliverable")
        + no2bounce_count(progress, "UnDeliverable/AcceptAll")
        + no2bounce_count(progress, "invalid")
        + no2bounce_count(progress, "bounce")
        + no2bounce_count(progress, "spam")
    )
    if completed <= 0:
        return []
    return [
        {
            "email": email,
            "finalScoreValue": "Incomplete/PendingTimeout",
            "status": "incomplete_pending_timeout",
            "no2bounce_partial_timeout": "true",
            "no2bounce_progress": progress,
        }
        for email in emails
    ]


def validate_no2bounce(emails: list[str], timeout_seconds: int | None = None) -> dict[str, Any]:
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

    if timeout_seconds is None:
        timeout_seconds = max(10, int(os.getenv("NO2BOUNCE_POLL_TIMEOUT_SECONDS", "120")))
    poll_interval_seconds = max(2, int(os.getenv("NO2BOUNCE_POLL_INTERVAL_SECONDS", "3")))
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
                "progress": no2bounce_progress(poll_payload),
                "results": results,
            }
        time.sleep(poll_interval_seconds)
    progress = no2bounce_progress(poll_payload)
    partial_rejected_results = no2bounce_partial_rejected_results(emails, progress)
    if partial_rejected_results:
        return {
            "configured": True,
            "error": "",
            "warning": "partial_timeout_rejected",
            "trackingId": tracking_id,
            "post_response": sanitize_no2bounce_payload(post_payload),
            "poll_response": sanitize_no2bounce_payload(poll_payload),
            "progress": progress,
            "results": partial_rejected_results,
        }
    return {
        "configured": True,
        "error": "poll_timeout",
        "trackingId": tracking_id,
        "post_response": sanitize_no2bounce_payload(post_payload),
        "poll_response": sanitize_no2bounce_payload(poll_payload),
        "progress": progress,
        "results": [],
    }


def result_email(result: dict[str, Any]) -> str:
    for key in ("email", "email address", "email_address", "address", "emailAddress", "mail"):
        matched = dict_get_case_insensitive(result, key)
        if matched:
            return compact(matched, 320).lower()
    return ""


def sanitize_anymail_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): sanitize_anymail_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [sanitize_anymail_payload(item) for item in payload]
    return payload


def anymail_decision(result: dict[str, Any], domain: str) -> tuple[str, str]:
    status = compact(result.get("email_status"), 80).lower()
    email = compact(result.get("valid_email") or result.get("email"), 320).lower()
    if status == "valid" and email_syntax_valid(email) and email.partition("@")[2] == domain:
        return "sendable", email
    return "rejected", ""


def validate_anymail_person(candidate: ContactCandidate, domain: str) -> dict[str, Any]:
    api_key = os.getenv("ANYMAILFINDER_API_KEY", "").strip()
    if not api_key:
        return {"configured": False, "error": "ANYMAILFINDER_API_KEY is not configured", "results": []}
    if not probable_human_name(candidate.name):
        return {"configured": True, "error": "", "results": [], "skipped": "not_probable_human_name"}
    if domain_has_mx_record(domain) is False:
        return {"configured": True, "error": "", "results": [], "mx_exists": False, "skipped": "mx_missing"}

    cache_key = f"anymail:{domain}:{normalize_person_name(candidate.name)}"
    cached = VALIDATION_CACHE.get(cache_key)
    if cached is not None:
        return {
            "configured": True,
            "error": "",
            "provider": "anymail_finder",
            "results": [cached],
            "cache_hit": True,
            "credits_charged": int(cached.get("credits_charged") or 0),
            "mx_exists": domain_has_mx_record(domain),
        }

    base_url = os.getenv("ANYMAILFINDER_BASE_URL", "https://api.anymailfinder.com/v5.1/find-email/person").strip()
    timeout_seconds = max(10, int(os.getenv("ANYMAILFINDER_TIMEOUT_SECONDS", "45")))
    request_body = {"domain": domain, "full_name": candidate.name}
    try:
        response = requests.post(
            base_url,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            json=request_body,
            timeout=timeout_seconds,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"raw": response.text}
    except requests.Timeout:
        return {"configured": True, "error": "timeout", "provider": "anymail_finder", "results": [], "request": request_body}
    except requests.RequestException as exc:
        return {"configured": True, "error": compact(str(exc), 300) or "request_failed", "provider": "anymail_finder", "results": [], "request": request_body}

    if response.status_code >= 400:
        error_text = ""
        if isinstance(payload, dict):
            error_text = compact(payload.get("error") or payload.get("message"), 300)
        return {
            "configured": True,
            "error": error_text or f"HTTP {response.status_code}",
            "provider": "anymail_finder",
            "status_code": response.status_code,
            "request": request_body,
            "response": sanitize_anymail_payload(payload),
            "results": [],
        }

    result = payload if isinstance(payload, dict) else {"raw": payload}
    result = sanitize_anymail_payload(result)
    VALIDATION_CACHE[cache_key] = result
    return {
        "configured": True,
        "error": "",
        "provider": "anymail_finder",
        "status_code": response.status_code,
        "request": request_body,
        "response": result,
        "results": [result],
        "credits_charged": int(result.get("credits_charged") or 0) if isinstance(result, dict) else 0,
        "mx_exists": domain_has_mx_record(domain),
    }


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def configured_provider_order() -> list[str]:
    raw = os.getenv(
        "CONTACT_SEARCH_PROVIDER_ORDER",
        "serper_emergency",
    ).strip()
    output: list[str] = []
    seen: set[str] = set()
    for value in raw.split(","):
        provider = compact(value, 80).lower()
        if provider in OPENSERP_ROUTE_MAP and provider not in seen:
            output.append(provider)
            seen.add(provider)
        if provider == "serper_emergency" and provider not in seen:
            output.append(provider)
            seen.add(provider)
    if env_flag("SERPER_FALLBACK_ENABLED", default=False) and "serper_emergency" not in seen:
        output.append("serper_emergency")
    return output or ["serper_emergency"]


def provider_health(provider: str) -> dict[str, Any]:
    with PROVIDER_LOCK:
        state = PROVIDER_STATE[provider]
        now_ts = time.time()
        recent = list(state["recent_outcomes"])
        recent_timeouts = trim_recent_timeouts(state, now_ts)
        success_rate = (sum(1 for item in recent if item) / len(recent)) if recent else 0.0
        disabled_until = float(state["disabled_until"])
        enabled = now_ts >= disabled_until
        return {
            "provider": provider,
            "total_recent_queries": int(state["total_recent_queries"]),
            "success_count": int(state["success_count"]),
            "empty_result_count": int(state["empty_result_count"]),
            "circuit_open_count": int(state["circuit_open_count"]),
            "timeout_count": int(state["timeout_count"]),
            "http_error_count": int(state["http_error_count"]),
            "last_error": str(state["last_error"]),
            "health_score": round(success_rate, 3),
            "enabled": enabled,
            "disabled_reason": "" if enabled else str(state["disabled_reason"]),
            "disabled_until": disabled_until,
            "cooldown_seconds": provider_cooldown_seconds(disabled_until, now_ts) if not enabled else 0,
            "recent_timeout_count": len(recent_timeouts),
            "timeout_disable_threshold": PROVIDER_TIMEOUT_DISABLE_THRESHOLD,
            "timeout_window_seconds": PROVIDER_TIMEOUT_WINDOW_SECONDS,
            "reset_token": PROVIDER_RESET_TOKEN,
        }


def record_provider_health(
    provider: str,
    *,
    success: bool,
    empty: bool,
    circuit_open: bool,
    timeout: bool,
    http_error: bool,
    error_text: str,
) -> dict[str, Any]:
    with PROVIDER_LOCK:
        state = PROVIDER_STATE[provider]
        now_ts = time.time()
        state["total_recent_queries"] += 1
        state["recent_outcomes"].append(bool(success))
        if success:
            state["success_count"] += 1
        if empty:
            state["empty_result_count"] += 1
        if circuit_open:
            state["circuit_open_count"] += 1
            state["disabled_until"] = now_ts + PROVIDER_DISABLE_SECONDS["circuit_open"]
            state["disabled_reason"] = "circuit_open"
        elif timeout:
            state["timeout_count"] += 1
            state["recent_timeout_timestamps"].append(now_ts)
            recent_timeouts = trim_recent_timeouts(state, now_ts)
            if len(recent_timeouts) >= PROVIDER_TIMEOUT_DISABLE_THRESHOLD:
                state["disabled_until"] = now_ts + PROVIDER_DISABLE_SECONDS["timeout"]
                state["disabled_reason"] = "timeout_threshold"
        elif http_error:
            state["http_error_count"] += 1
        elif success and float(state["disabled_until"]) <= now_ts:
            state["disabled_reason"] = ""
        if error_text:
            state["last_error"] = compact(error_text, 300)
    return provider_health(provider)


def normalize_search_results(results: Any) -> list[dict[str, Any]]:
    if not isinstance(results, list):
        return []
    output: list[dict[str, Any]] = []
    for index, result in enumerate(results[:10], start=1):
        if not isinstance(result, dict):
            continue
        url = compact(result.get("url") or result.get("link"), 1000)
        title = compact(result.get("title"), 400)
        snippet = compact(result.get("snippet") or result.get("content") or result.get("description"), 1200)
        if not url or is_search_asset(url):
            continue
        output.append(
            {
                "rank": int(result.get("rank") or result.get("position") or index),
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )
    return output


def provider_attempt_template(provider: str, query: str, error_text: str = "") -> dict[str, Any]:
    health = provider_health(provider)
    return {
        "provider": provider,
        "query": compact(query, 300),
        "results": [],
        "result_count": 0,
        "provider_error": compact(error_text, 300),
        "circuit_open": False,
        "timeout": False,
        "http_error": False,
        "provider_disabled": not health["enabled"],
        "provider_disabled_reason": str(health["disabled_reason"]) if not health["enabled"] else "",
        "cooldown_seconds": int(health["cooldown_seconds"]) if not health["enabled"] else 0,
        "usable_results_count": 0,
        "provider_health": health,
    }


def search_openserp_provider(provider: str, query: str, limit: int = 10) -> dict[str, Any]:
    base_url = os.getenv("OPENSERP_BASE_URL", "https://searxng-railway-production-518a.up.railway.app").strip().rstrip("/")
    route = OPENSERP_ROUTE_MAP.get(provider)
    if not route:
        return provider_attempt_template(provider, query, "provider_not_supported")

    health = provider_health(provider)
    if not health["enabled"]:
        attempt = provider_attempt_template(provider, query, f"provider_disabled:{health['disabled_reason']}")
        attempt["provider_disabled"] = True
        attempt["provider_disabled_reason"] = str(health["disabled_reason"])
        attempt["cooldown_seconds"] = int(health["cooldown_seconds"])
        attempt["provider_health"] = health
        return attempt

    timeout_seconds = max(4, int(os.getenv("CONTACT_SEARCH_PROVIDER_TIMEOUT_SECONDS", "12")))
    url = f"{base_url}{route}"
    raw_error = ""
    payload: Any = {}
    http_error = False
    timeout_hit = False

    try:
        response = requests.get(url, params={"text": query, "limit": limit}, timeout=timeout_seconds)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            http_error = True
            raw_error = compact(payload.get("message") if isinstance(payload, dict) else "", 300) or f"HTTP {response.status_code}"
    except requests.Timeout:
        timeout_hit = True
        raw_error = "timeout"
    except requests.RequestException as exc:
        raw_error = compact(str(exc), 300) or "request_failed"

    results = normalize_search_results(payload.get("results") if isinstance(payload, dict) else [])
    if not raw_error and isinstance(payload, dict):
        raw_error = compact(payload.get("message") or payload.get("error"), 300)
    circuit_open = detect_provider_flags(raw_error)
    success = bool(results) and not raw_error
    health_after = record_provider_health(
        provider,
        success=success,
        empty=not results and not raw_error,
        circuit_open=circuit_open,
        timeout=timeout_hit,
        http_error=http_error,
        error_text=raw_error,
    )
    return {
        "provider": provider,
        "query": compact(query, 300),
        "results": results,
        "result_count": len(results),
        "provider_error": raw_error,
        "circuit_open": circuit_open,
        "timeout": timeout_hit,
        "http_error": http_error,
        "provider_disabled": not health_after["enabled"],
        "provider_disabled_reason": str(health_after["disabled_reason"]) if not health_after["enabled"] else "",
        "cooldown_seconds": int(health_after["cooldown_seconds"]) if not health_after["enabled"] else 0,
        "usable_results_count": len(results),
        "provider_health": health_after,
    }


def search_serper_emergency(query: str, limit: int = 10) -> dict[str, Any]:
    provider = "serper_emergency"
    if provider not in configured_provider_order() and not env_flag("SERPER_FALLBACK_ENABLED", default=False):
        return provider_attempt_template(provider, query, "serper_fallback_disabled")
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        return provider_attempt_template(provider, query, "serper_api_key_missing")

    health = provider_health(provider)
    if not health["enabled"]:
        attempt = provider_attempt_template(provider, query, f"provider_disabled:{health['disabled_reason']}")
        attempt["provider_disabled"] = True
        attempt["provider_disabled_reason"] = str(health["disabled_reason"])
        attempt["cooldown_seconds"] = int(health["cooldown_seconds"])
        attempt["provider_health"] = health
        return attempt

    raw_error = ""
    payload: Any = {}
    http_error = False
    timeout_hit = False
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": limit},
            timeout=max(4, int(os.getenv("CONTACT_SEARCH_PROVIDER_TIMEOUT_SECONDS", "12"))),
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            http_error = True
            raw_error = compact(payload.get("message") if isinstance(payload, dict) else "", 300) or f"HTTP {response.status_code}"
    except requests.Timeout:
        timeout_hit = True
        raw_error = "timeout"
    except requests.RequestException as exc:
        raw_error = compact(str(exc), 300) or "request_failed"

    results = normalize_search_results(payload.get("organic") if isinstance(payload, dict) else [])
    circuit_open = detect_provider_flags(raw_error)
    health_after = record_provider_health(
        provider,
        success=bool(results) and not raw_error,
        empty=not results and not raw_error,
        circuit_open=circuit_open,
        timeout=timeout_hit,
        http_error=http_error,
        error_text=raw_error,
    )
    return {
        "provider": provider,
        "query": compact(query, 300),
        "results": results,
        "result_count": len(results),
        "provider_error": raw_error,
        "circuit_open": circuit_open,
        "timeout": timeout_hit,
        "http_error": http_error,
        "provider_disabled": not health_after["enabled"],
        "provider_disabled_reason": str(health_after["disabled_reason"]) if not health_after["enabled"] else "",
        "cooldown_seconds": int(health_after["cooldown_seconds"]) if not health_after["enabled"] else 0,
        "usable_results_count": len(results),
        "provider_health": health_after,
    }


def execute_provider_cascade(payload: dict[str, Any]) -> list[dict[str, Any]]:
    query_limit = max(1, int(payload.get("max_queries") or os.getenv("CONTACT_SEARCH_MAX_QUERIES_PER_ROW", "3") or 3))
    raw_queries = payload.get("search_queries") if isinstance(payload.get("search_queries"), list) else []
    queries = raw_queries or build_role_queries(
        compact(payload.get("company_name")),
        compact(payload.get("company_homepage_name")),
        compact(payload.get("canonical_domain")),
        payload.get("website_content") if isinstance(payload.get("website_content"), str) else "",
        max_queries=query_limit,
    )
    attempts: list[dict[str, Any]] = []
    providers = configured_provider_order()
    for query_meta in queries[:query_limit]:
        query = compact(query_meta.get("query"), 300)
        if not query:
            continue
        for provider in providers:
            if provider == "serper_emergency":
                attempt = search_serper_emergency(query)
            else:
                attempt = search_openserp_provider(provider, query)
            attempt.update(
                {
                    "role": compact(query_meta.get("role"), 100),
                    "role_bucket": compact(query_meta.get("role_bucket") or query_meta.get("bucket"), 100),
                    "covered_role_buckets": query_meta.get("covered_role_buckets") if isinstance(query_meta.get("covered_role_buckets"), list) else [],
                    "role_priority": int(query_meta.get("role_priority") or query_meta.get("priority") or 0),
                    "seniority": compact(query_meta.get("seniority"), 100),
                }
            )
            attempts.append(attempt)
            if int(attempt.get("usable_results_count") or 0) >= 5:
                break
    return attempts


def candidate_email_candidates(candidate: ContactCandidate, domain: str, excluded_emails: set[str]) -> list[dict[str, Any]]:
    max_emails = max(1, int(os.getenv("CONTACT_SEARCH_MAX_EMAILS_PER_CANDIDATE", "4")))
    generated = email_permutations(candidate, domain)[: max(max_emails, 1)]
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in generated:
        email = compact(item.get("email"), 320).lower()
        if not email or email in seen or email in excluded_emails:
            continue
        local_part, _, email_domain = email.partition("@")
        if not email_syntax_valid(email):
            continue
        if email_domain != domain:
            continue
        if local_part in GENERIC_LOCAL_PARTS:
            continue
        seen.add(email)
        output.append(
            {
                **item,
                "email": email,
                "name": candidate.name,
                "role": candidate.role,
                "source_url": candidate.source_url,
            }
        )
    return output


def validate_email_candidates(email_candidates: list[dict[str, Any]], domain: str, max_remote_emails: int | None = None) -> dict[str, Any]:
    mx_exists = domain_has_mx_record(domain)
    cache_hits: list[str] = []
    cached_results: list[dict[str, Any]] = []
    missing_emails: list[str] = []
    for item in email_candidates:
        email = compact(item.get("email"), 320).lower()
        cached = VALIDATION_CACHE.get(email)
        if cached is not None:
            cached_results.append(cached)
            cache_hits.append(email)
        else:
            missing_emails.append(email)

    validation = {
        "configured": bool(os.getenv("NO2BOUNCE_API_TOKEN", "").strip()),
        "error": "",
        "results": [],
        "cache_hits": cache_hits,
        "mx_exists": mx_exists,
        "requested_remote_email_count": 0,
        "budget_limited": False,
        "unvalidated_emails": [],
    }
    if mx_exists is False:
        return validation
    if max_remote_emails is not None and max_remote_emails >= 0 and len(missing_emails) > max_remote_emails:
        validation["budget_limited"] = True
        validation["unvalidated_emails"] = missing_emails[max_remote_emails:]
        missing_emails = missing_emails[:max_remote_emails]
    if missing_emails:
        validation["requested_remote_email_count"] = len(missing_emails)
        budget_limited = bool(validation["budget_limited"])
        unvalidated_emails = list(validation["unvalidated_emails"])
        validation = validate_no2bounce(missing_emails)
        validation["cache_hits"] = cache_hits
        validation["mx_exists"] = mx_exists
        validation["requested_remote_email_count"] = len(missing_emails)
        validation["budget_limited"] = budget_limited
        validation["unvalidated_emails"] = unvalidated_emails
        if not validation.get("error"):
            for result in validation.get("results", []):
                email = result_email(result)
                if email:
                    VALIDATION_CACHE[email] = result
    validation["results"] = cached_results + [result for result in validation.get("results", []) if isinstance(result, dict)]
    return validation


def accepted_candidate_from_raw(raw_candidate: dict[str, Any], accepted: dict[str, Any] | None = None) -> ContactCandidate | None:
    accepted = accepted or {}
    name = clean_name(accepted.get("name") or raw_candidate.get("raw_name"))
    if not probable_human_name(name):
        return None
    parsed = parse_name(name)
    if not parsed:
        return None
    role = compact(accepted.get("role") or raw_candidate.get("role_detected"), 120)
    role_bucket = compact(accepted.get("role_bucket") or raw_candidate.get("role_bucket"), 120)
    group = next((item for item in ROLE_BUCKETS if item["bucket"] == role_bucket), None)
    if not group:
        return None
    confidence_value = accepted.get("confidence", 0.0)
    try:
        confidence_score = float(confidence_value)
    except (TypeError, ValueError):
        confidence_score = 0.7
    if confidence_score > 1:
        confidence_score = confidence_score / 100
    first_name, last_name = parsed
    return ContactCandidate(
        name=name,
        role=role,
        seniority=compact(accepted.get("seniority") or group["seniority"], 80),
        role_bucket=role_bucket,
        role_priority=int(group["priority"]),
        source_url=compact(raw_candidate.get("source_url"), 1000),
        source_type=compact(raw_candidate.get("source_type"), 120),
        evidence_text=compact(raw_candidate.get("evidence_text") or raw_candidate.get("snippet"), 1600),
        confidence="High" if confidence_score >= 0.85 else "Medium",
        confidence_score=max(0.0, min(confidence_score or 0.7, 1.0)),
        company_match=True,
        first_name=first_name,
        last_name=last_name,
    )


def deterministic_rejection_reason(raw_candidate: dict[str, Any], company_name: str, homepage_name: str, canonical_domain: str, previously_tried: set[str]) -> str:
    raw_name = clean_name(raw_candidate.get("raw_name"))
    normalized = normalize_person_name(raw_name)
    if not raw_name or len(name_parts(raw_name)) < 2:
        return "not_human"
    if normalized in previously_tried:
        return "already_tried"
    if not probable_human_name(raw_name):
        return "not_human"
    if company_fragment_match(raw_name, company_name, homepage_name, canonical_domain) or company_match(raw_name, company_name, homepage_name, canonical_domain):
        return "organization_name"
    if str(raw_candidate.get("source_strength")) in {"very_weak_activity_snippet", "very_weak_event_or_speaker_page"}:
        return "weak_source"
    if raw_candidate.get("source_type") != "official_domain" and not non_official_candidate_company_link(
        compact(raw_candidate.get("evidence_text"), 1600),
        int(raw_candidate.get("name_start") or 0),
        int(raw_candidate.get("name_end") or 0),
        compact(raw_candidate.get("role_detected"), 120),
        company_name,
        homepage_name,
        canonical_domain,
    ):
        return "not_target_company"
    return ""


def deterministic_verify_contact_candidates(payload: dict[str, Any], raw_candidates: list[dict[str, Any]]) -> CandidateVerification:
    company_name = compact(payload.get("company_name"))
    homepage_name = compact(payload.get("company_homepage_name"))
    canonical_domain = compact(payload.get("canonical_domain")).lower().removeprefix("www.")
    previously_tried = normalized_name_set(payload.get("excluded_candidate_names"))
    accepted: list[ContactCandidate] = []
    rejected: list[dict[str, Any]] = []
    previously_tried_details: list[dict[str, Any]] = []
    for raw_candidate in raw_candidates:
        reason_code = deterministic_rejection_reason(raw_candidate, company_name, homepage_name, canonical_domain, previously_tried)
        if reason_code:
            item = {
                "raw_name": compact(raw_candidate.get("raw_name"), 160),
                "decision": "reject",
                "reason_code": reason_code,
                "reason": f"deterministic verifier rejected candidate as {reason_code}",
                "source_url": raw_candidate.get("source_url", ""),
            }
            rejected.append(item)
            if reason_code == "already_tried":
                previously_tried_details.append(item)
            continue
        candidate = accepted_candidate_from_raw(raw_candidate, {"confidence": 0.85})
        if candidate:
            accepted.append(candidate)
        else:
            rejected.append(
                {
                    "raw_name": compact(raw_candidate.get("raw_name"), 160),
                    "decision": "reject",
                    "reason_code": "insufficient_evidence",
                    "reason": "could not convert raw candidate into a safe contact candidate",
                    "source_url": raw_candidate.get("source_url", ""),
                }
            )
    return CandidateVerification(
        accepted=accepted,
        rejected_candidates=rejected,
        previously_tried_candidate_details=previously_tried_details,
        raw_candidates=raw_candidates,
        verifier="deterministic",
    )


def llm_verifier_prompt(payload: dict[str, Any], raw_candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    previously_tried = [
        {"name": name, "stage": "official_site_preflight", "email_lookup_result": "not_found"}
        for name in sorted(normalized_name_set(payload.get("excluded_candidate_names")))
    ]
    user_payload = {
        "company_name": compact(payload.get("company_name"), 180),
        "company_homepage_name": compact(payload.get("company_homepage_name"), 180),
        "canonical_domain": compact(payload.get("canonical_domain"), 180),
        "target_role_buckets": TARGET_ROLE_BUCKETS,
        "previously_tried_candidates": previously_tried,
        "raw_candidates": raw_candidates[:20],
    }
    system = (
        "You are a strict contact-candidate verifier. Return strict JSON only. "
        "You must only accept or reject candidates that appear in raw_candidates. Do not invent, rename, complete, or add a new person. "
        "Accept candidates only when the name is a real human full name, the evidence links the person to the target company, "
        "the role belongs to the target company, and the role is managerial/senior/executive/clinical/compliance/IT/operations/admin/HR. "
        "Reject organizations, clinics, centres, publications, events, products, departments, locations, role titles, title-only phrases, "
        "comments/activity snippets, people tied to other organizations, already tried candidates, and weak evidence."
    )
    schema = (
        "Return exactly this JSON shape: "
        '{"accepted_candidates":[{"name":"string","role":"string","role_bucket":"string","seniority":"executive|senior_manager|manager","is_human":true,"target_company_match":"direct|probable","source_strength":"official_domain|strong_professional_profile|professional_directory|official_social|weak_snippet","confidence":0.0,"reason":"string"}],'
        '"rejected_candidates":[{"raw_name":"string","decision":"reject","reason_code":"not_human|organization_name|role_title_only|role_belongs_to_other_org|weak_source|not_target_company|already_tried|not_managerial_role|insufficient_evidence","reason":"string"}],'
        '"needs_more_evidence_candidates":[{"raw_name":"string","reason":"string"}]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": schema + "\nInput:\n" + json.dumps(user_payload, ensure_ascii=False)},
    ]


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = compact(text, 20000)
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def verify_contact_candidates_with_llm(payload: dict[str, Any], raw_candidates: list[dict[str, Any]]) -> CandidateVerification:
    if not raw_candidates:
        return CandidateVerification(verifier="llm", raw_candidates=[])
    fake_response = os.getenv("CONTACT_LLM_VERIFIER_FAKE_RESPONSE", "").strip()
    if fake_response:
        llm_payload = parse_llm_json(fake_response)
    else:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return CandidateVerification(verifier="llm", raw_candidates=raw_candidates, error="OPENROUTER_API_KEY is not configured")
        model = os.getenv("CONTACT_LLM_VERIFIER_MODEL", "deepseek/deepseek-v4-flash").strip()
        timeout_seconds = max(5, int(os.getenv("CONTACT_LLM_VERIFIER_TIMEOUT_SECONDS", "20")))
        response = requests.post(
            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions").strip(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "temperature": 0, "messages": llm_verifier_prompt(payload, raw_candidates)},
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            return CandidateVerification(verifier="llm", raw_candidates=raw_candidates, error=f"llm_http_{response.status_code}")
        data = response.json()
        content = compact(data.get("choices", [{}])[0].get("message", {}).get("content"), 20000)
        try:
            llm_payload = parse_llm_json(content)
        except Exception as exc:
            return CandidateVerification(verifier="llm", raw_candidates=raw_candidates, error=f"llm_json_parse_failed:{compact(exc, 120)}")

    accepted_candidates: list[ContactCandidate] = []
    rejected = [item for item in llm_payload.get("rejected_candidates", []) if isinstance(item, dict)]
    needs_more = [item for item in llm_payload.get("needs_more_evidence_candidates", []) if isinstance(item, dict)]
    raw_by_name = {normalize_person_name(item.get("raw_name", "")): item for item in raw_candidates}
    for accepted in llm_payload.get("accepted_candidates", []):
        if not isinstance(accepted, dict):
            continue
        raw = raw_by_name.get(normalize_person_name(accepted.get("name", "")))
        if not raw:
            rejected.append({"raw_name": compact(accepted.get("name"), 160), "decision": "reject", "reason_code": "llm_candidate_not_in_raw_candidates", "reason": "LLM accepted a name that was not in raw candidates"})
            continue
        candidate = accepted_candidate_from_raw(raw, accepted)
        if candidate:
            accepted_candidates.append(candidate)
    return CandidateVerification(
        accepted=accepted_candidates,
        rejected_candidates=rejected,
        needs_more_evidence_candidates=needs_more,
        previously_tried_candidate_details=[item for item in rejected if item.get("reason_code") == "already_tried"],
        raw_candidates=raw_candidates,
        verifier="llm",
    )


def verify_candidates(payload: dict[str, Any], candidates: list[ContactCandidate], raw_candidates: list[dict[str, Any]]) -> CandidateVerification:
    if payload.get("site_fast_path_only"):
        return CandidateVerification(
            accepted=candidates,
            raw_candidates=[candidate.to_dict() for candidate in candidates],
            verifier="deterministic_official_site",
        )
    enabled = env_flag("CONTACT_LLM_VERIFIER_ENABLED", default=True)
    if enabled:
        return verify_contact_candidates_with_llm(payload, raw_candidates)
    return deterministic_verify_contact_candidates(payload, raw_candidates)


def build_contact_search_evidence(payload: dict[str, Any], candidates: list[dict[str, Any]], verification: CandidateVerification | None = None) -> dict[str, Any]:
    attempts = payload.get("search_attempts") if isinstance(payload.get("search_attempts"), list) else []
    output_attempts: list[dict[str, Any]] = []
    total_results = 0
    error_count = 0
    timeout_count = 0
    circuit_open_count = 0
    for attempt in attempts[:20]:
        results = attempt.get("results") if isinstance(attempt, dict) and isinstance(attempt.get("results"), list) else []
        error = compact((attempt.get("provider_error") or attempt.get("error")) if isinstance(attempt, dict) else "", 300)
        if error:
            error_count += 1
        if attempt.get("timeout"):
            timeout_count += 1
        if attempt.get("circuit_open"):
            circuit_open_count += 1
        total_results += len(results)
        output_attempts.append(
            {
                "provider": compact(attempt.get("provider") if isinstance(attempt, dict) else "", 80),
                "query": compact(attempt.get("query") if isinstance(attempt, dict) else "", 300),
                "role": compact(attempt.get("role") if isinstance(attempt, dict) else "", 100),
                "role_bucket": compact(attempt.get("role_bucket") if isinstance(attempt, dict) else "", 100),
                "covered_role_buckets": attempt.get("covered_role_buckets") if isinstance(attempt.get("covered_role_buckets"), list) else [],
                "result_count": len(results),
                "provider_error": error,
                "circuit_open": bool(attempt.get("circuit_open")) if isinstance(attempt, dict) else False,
                "timeout": bool(attempt.get("timeout")) if isinstance(attempt, dict) else False,
                "provider_disabled": bool(attempt.get("provider_disabled")) if isinstance(attempt, dict) else False,
                "provider_disabled_reason": compact(attempt.get("provider_disabled_reason") if isinstance(attempt, dict) else "", 160),
                "cooldown_seconds": int(attempt.get("cooldown_seconds") or 0) if isinstance(attempt, dict) else 0,
                "usable_results_count": int(attempt.get("usable_results_count") or len(results)) if isinstance(attempt, dict) else len(results),
                "provider_health": attempt.get("provider_health") if isinstance(attempt, dict) and isinstance(attempt.get("provider_health"), dict) else {},
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
    verification = verification or CandidateVerification()
    raw_candidates = verification.raw_candidates
    rejected_candidates = verification.rejected_candidates
    previously_tried_names = sorted(normalized_name_set(payload.get("excluded_candidate_names")))
    return {
        "query_attempts_count": len({compact(attempt.get("query"), 300) for attempt in attempts if isinstance(attempt, dict) and compact(attempt.get("query"), 300)}),
        "provider_attempts_count": len(attempts),
        "stored_attempts_count": len(output_attempts),
        "total_results_count": total_results,
        "search_error_count": error_count,
        "timeout_count": timeout_count,
        "circuit_open_count": circuit_open_count,
        "raw_candidate_count": len(raw_candidates),
        "verified_candidate_count": len(candidates),
        "rejected_candidate_count": len(rejected_candidates),
        "candidate_count": len(candidates),
        "candidate_names": [compact(candidate.get("name"), 120) for candidate in candidates[:10]],
        "verified_candidate_names": [compact(candidate.get("name"), 120) for candidate in candidates[:10]],
        "rejected_candidate_names": [compact(candidate.get("raw_name"), 120) for candidate in rejected_candidates[:20]],
        "rejected_candidates": rejected_candidates[:30],
        "needs_more_evidence_candidates": verification.needs_more_evidence_candidates[:20],
        "raw_candidates": raw_candidates[:30],
        "candidate_verifier": verification.verifier,
        "candidate_verifier_prompt_version": verification.prompt_version,
        "candidate_verifier_error": verification.error,
        "previously_tried_candidate_names": previously_tried_names,
        "previously_tried_candidate_details": verification.previously_tried_candidate_details[:20],
        "excluded_candidate_names": sorted(normalized_name_set(payload.get("excluded_candidate_names"))),
        "preflight_candidate_names_skipped_in_fallback": sorted(normalized_name_set(payload.get("excluded_candidate_names"))),
        "preflight_skip_reason": "already_checked_by_official_site_preflight" if normalized_name_set(payload.get("excluded_candidate_names")) else "",
        "excluded_email_candidates": sorted(normalized_email_set(payload.get("excluded_email_candidates"))),
        "fallback_reason": compact(payload.get("fallback_reason"), 160),
        "provider_reset_token": compact(payload.get("contact_search_run_id") or payload.get("provider_reset_token"), 160),
        "provider_order": configured_provider_order(),
        "attempts": output_attempts,
    }


def enrich_contact(payload: dict[str, Any], validate_email: bool = True) -> ContactResult:
    row_id = payload.get("Id") or payload.get("row_id") or ""
    domain = compact(payload.get("canonical_domain")).lower().removeprefix("www.")
    if not domain:
        return ContactResult(row_id=row_id, contact_search_status="skipped", contact_search_reason="missing_canonical_domain")

    payload = dict(payload)
    ensure_provider_state(compact(payload.get("provider_reset_token") or payload.get("contact_search_run_id"), 160))
    excluded_names = normalized_name_set(payload.get("excluded_candidate_names"))
    excluded_emails = normalized_email_set(payload.get("excluded_email_candidates"))
    if not payload.get("site_fast_path_only") and not isinstance(payload.get("search_attempts"), list):
        payload["search_attempts"] = []
    if not payload.get("site_fast_path_only") and not payload.get("search_attempts"):
        payload["search_attempts"] = execute_provider_cascade(payload)

    if payload.get("site_fast_path_only"):
        candidates = extract_candidates_from_website_content(
            payload.get("website_content") if isinstance(payload.get("website_content"), str) else "",
            compact(payload.get("company_name")),
            compact(payload.get("company_homepage_name")),
            domain,
            compact(payload.get("best_url"), 500),
            excluded_names=excluded_names,
        )
    else:
        raw_candidates = extract_raw_candidates_from_search(payload)
        deterministic_candidates = extract_candidates(payload)
        verification = verify_candidates(payload, deterministic_candidates, raw_candidates)
        candidates = verification.accepted
        if verification.error and env_flag("CONTACT_LLM_VERIFIER_REQUIRED_FOR_FALLBACK", default=True):
            candidate_dicts = [candidate.to_dict() for candidate in candidates]
            search_evidence = build_contact_search_evidence(payload, candidate_dicts, verification)
            return ContactResult(
                row_id=row_id,
                contact_search_status="failed",
                contact_search_reason="candidate_verifier_failed",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_validation_provider="anymail_finder",
                email_validation_evidence={
                    "provider": "anymail_finder",
                    "configured": bool(os.getenv("ANYMAILFINDER_API_KEY", "").strip()),
                    "skipped": "candidate_verifier_failed",
                    "candidate_verifier_error": verification.error,
                },
            )
        candidate_dicts = [candidate.to_dict() for candidate in candidates]
        search_evidence = build_contact_search_evidence(payload, candidate_dicts, verification)
        # Continue into the common no-candidate / Anymail path below.
        if not candidates:
            if (
                search_evidence["provider_attempts_count"]
                and search_evidence["search_error_count"] >= search_evidence["provider_attempts_count"]
                and search_evidence["total_results_count"] == 0
            ):
                return ContactResult(
                    row_id=row_id,
                    contact_search_status="failed",
                    contact_search_reason="search_provider_failed",
                    contact_candidates=candidate_dicts,
                    contact_search_evidence=search_evidence,
                    email_validation_evidence={
                        "provider": "anymail_finder",
                        "configured": bool(os.getenv("ANYMAILFINDER_API_KEY", "").strip()),
                        "skipped": "search_provider_failed",
                    },
                )
            return ContactResult(
                row_id=row_id,
                contact_search_status="contact_not_found",
                contact_search_reason="no_validated_person_found",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_validation_status="skipped_no_verified_candidate",
                email_validation_provider="anymail_finder",
                email_validation_evidence={
                    "provider": "anymail_finder",
                    "configured": bool(os.getenv("ANYMAILFINDER_API_KEY", "").strip()),
                    "status": "skipped_no_verified_candidate",
                    "skipped": "no_verified_candidates",
                    "reason": "candidate verifier accepted no fallback candidates",
                },
            )
        # Candidate list has been verified. Skip rebuilding evidence below.
        candidate_dicts = [candidate.to_dict() for candidate in candidates]
        search_evidence = search_evidence
        goto_common = True
    if payload.get("site_fast_path_only"):
        verification = verify_candidates(payload, candidates, [])
        candidate_dicts = [candidate.to_dict() for candidate in candidates]
        search_evidence = build_contact_search_evidence(payload, candidate_dicts, verification)
    elif 'goto_common' not in locals():
        candidate_dicts = [candidate.to_dict() for candidate in candidates]
        search_evidence = build_contact_search_evidence(payload, candidate_dicts)
    if not candidates:
        if (
            search_evidence["provider_attempts_count"]
            and search_evidence["search_error_count"] >= search_evidence["provider_attempts_count"]
            and search_evidence["total_results_count"] == 0
        ):
            return ContactResult(
                row_id=row_id,
                contact_search_status="failed",
                contact_search_reason="search_provider_failed",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_validation_evidence={
                    "provider": "anymail_finder",
                    "configured": bool(os.getenv("ANYMAILFINDER_API_KEY", "").strip()),
                    "skipped": "search_provider_failed",
                },
            )
        return ContactResult(
            row_id=row_id,
            contact_search_status="contact_not_found",
            contact_search_reason="no_validated_person_found",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_validation_status="skipped_no_verified_candidate",
            email_validation_provider="anymail_finder",
            email_validation_evidence={
                "provider": "anymail_finder",
                "configured": bool(os.getenv("ANYMAILFINDER_API_KEY", "").strip()),
                "status": "skipped_no_verified_candidate",
                "skipped": "no_verified_candidates",
                "reason": "no candidates passed verifier/human filters",
            },
        )

    aggregated_email_candidates: list[dict[str, Any]] = []
    generated_any = False
    validated_candidate_attempted = False
    max_candidates = max(1, int(os.getenv("CONTACT_SEARCH_MAX_CANDIDATES_PER_ROW", "3")))
    validation_evidence: dict[str, Any] = {
        "provider": "anymail_finder",
        "configured": bool(os.getenv("ANYMAILFINDER_API_KEY", "").strip()),
        "dry_run": not validate_email,
        "max_candidates_per_row": max_candidates,
        "total_anymail_requests": 0,
        "total_anymail_credits_charged": 0,
        "candidate_attempts": [],
    }
    for candidate in candidates[:max_candidates]:
        if candidate.confidence not in {"High", "Medium"}:
            continue
        if not probable_human_name(candidate.name):
            continue
        email_candidates = [
            {
                "name": candidate.name,
                "role": candidate.role,
                "source_url": candidate.source_url,
                "provider": "anymail_finder",
                "status": "not_validated",
            }
        ]
        generated_any = True
        aggregated_email_candidates.extend(email_candidates)
        candidate_summary = {
            "name": candidate.name,
            "role": candidate.role,
            "source_url": candidate.source_url,
            "provider": "anymail_finder",
            "lookup": "person_domain",
        }
        validation_evidence["candidate_attempts"].append(candidate_summary)
        if not validate_email:
            continue

        validated_candidate_attempted = True
        validation = validate_anymail_person(candidate, domain)
        validation_evidence["total_anymail_requests"] = int(validation_evidence.get("total_anymail_requests") or 0) + (0 if validation.get("cache_hit") else 1)
        validation_evidence["total_anymail_credits_charged"] = int(validation_evidence.get("total_anymail_credits_charged") or 0) + int(validation.get("credits_charged") or 0)
        candidate_summary["cache_hit"] = bool(validation.get("cache_hit"))
        candidate_summary["mx_exists"] = validation.get("mx_exists")
        candidate_summary["validation_error"] = compact(validation.get("error"), 160)
        candidate_summary["credits_charged"] = int(validation.get("credits_charged") or 0)
        if validation.get("response"):
            candidate_summary["validation_response"] = validation.get("response")
        candidate_summary["validation_result_count"] = len(validation.get("results") or [])
        if not validation.get("configured"):
            return ContactResult(
                row_id=row_id,
                contact_search_status="failed",
                contact_search_reason="email_validation_not_configured",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_candidates=aggregated_email_candidates,
                email_validation_status="not_configured",
                email_validation_provider="anymail_finder",
                email_validation_evidence=validation_evidence,
            )
        if validation.get("error"):
            return ContactResult(
                row_id=row_id,
                contact_search_status="failed",
                contact_search_reason="email_validation_provider_failed",
                contact_candidates=candidate_dicts,
                contact_search_evidence=search_evidence,
                email_candidates=aggregated_email_candidates,
                email_validation_status=str(validation.get("error")),
                email_validation_provider="anymail_finder",
                email_validation_evidence=validation_evidence,
            )

        email_candidate = email_candidates[0]
        if validation.get("mx_exists") is False:
            email_candidate["status"] = "mx_missing"
            email_candidate["decision"] = "rejected"
            continue

        for result in validation.get("results", []):
            if not isinstance(result, dict):
                continue
            decision, email = anymail_decision(result, domain)
            email_candidate["email"] = compact(result.get("email") or result.get("valid_email"), 320).lower()
            email_candidate["valid_email"] = email
            email_candidate["validation_result"] = result
            email_candidate["status"] = compact(result.get("email_status"), 80).lower() or "validated"
            email_candidate["decision"] = decision
            if email:
                if decision in {"sendable", "risky_sendable"}:
                    email_candidate["accepted"] = True
                    candidate_summary["accepted_email"] = email
                    candidate_summary["accepted_decision"] = decision
                    return ContactResult(
                        row_id=row_id,
                        contact_search_status="contact_found",
                        contact_search_reason=f"{decision}_person_specific_email_found",
                        contact_candidates=candidate_dicts,
                        contact_search_evidence=search_evidence,
                        email_candidates=aggregated_email_candidates,
                        selected_contact_name=candidate.name,
                        selected_contact_role=candidate.role,
                        selected_contact_seniority=candidate.seniority,
                        selected_contact_source_url=candidate.source_url,
                        selected_contact_confidence=candidate.confidence,
                        validated_email=email,
                        email_validation_status=decision,
                        email_validation_provider="anymail_finder",
                        email_validation_evidence=validation_evidence,
                    )
        found_email = compact(email_candidate.get("email"), 320).lower()
        if found_email:
            excluded_emails.add(found_email)

    if not generated_any:
        return ContactResult(
            row_id=row_id,
            contact_search_status="contact_not_found",
            contact_search_reason="no_probable_human_candidate_for_email_lookup",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_candidates=aggregated_email_candidates,
            email_validation_status="skipped_no_email_candidate",
            email_validation_provider="anymail_finder",
            email_validation_evidence={
                **validation_evidence,
                "status": "skipped_no_email_candidate",
                "skipped": "no_probable_human_candidate_for_email_lookup",
            },
        )
    if not validate_email:
        return ContactResult(
            row_id=row_id,
            contact_search_status="contact_not_found",
            contact_search_reason="dry_run_email_validation_skipped",
            contact_candidates=candidate_dicts,
            contact_search_evidence=search_evidence,
            email_candidates=aggregated_email_candidates,
            email_validation_status="skipped_dry_run",
            email_validation_provider="anymail_finder",
            email_validation_evidence={**validation_evidence, "status": "skipped_dry_run", "skipped": "dry_run"},
        )

    return ContactResult(
        row_id=row_id,
        contact_search_status="contact_not_found",
        contact_search_reason="candidates_found_but_no_sendable_email" if validated_candidate_attempted else "no_deliverable_person_specific_email_found",
        contact_candidates=candidate_dicts,
        contact_search_evidence=search_evidence,
        email_candidates=aggregated_email_candidates,
        email_validation_status="no_deliverable_email",
        email_validation_provider="anymail_finder",
        email_validation_evidence=validation_evidence,
    )


def email_candidate_summary_line(candidate: dict[str, Any]) -> str:
    result = candidate.get("validation_result") if isinstance(candidate.get("validation_result"), dict) else {}
    response = candidate.get("validation_response") if isinstance(candidate.get("validation_response"), dict) else result
    input_payload = response.get("input") if isinstance(response.get("input"), dict) else {}
    name = compact(candidate.get("name") or input_payload.get("full_name"), 120)
    role = compact(candidate.get("role"), 120)
    email = compact(
        candidate.get("valid_email")
        or candidate.get("email")
        or response.get("valid_email")
        or response.get("email"),
        320,
    )
    status = compact(candidate.get("status") or response.get("email_status") or candidate.get("accepted_decision"), 120)
    decision = compact(candidate.get("decision") or candidate.get("accepted_decision"), 120)
    domain = compact(input_payload.get("domain"), 180)
    label = email or (f"{name} @ {domain}" if name and domain else name or "unknown candidate")
    verdict = "valid" if candidate.get("accepted") or decision in {"sendable", "risky_sendable"} else "not valid"
    detail = "; ".join(part for part in (status, decision) if part)
    role_text = f", {role}" if role else ""
    detail_text = f" ({detail})" if detail else ""
    return compact(f"{verdict}: {label}{role_text}{detail_text}", 500)


def iter_email_attempts(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = evidence.get("candidate_attempts") if isinstance(evidence, dict) else []
    output = list(attempts) if isinstance(attempts, list) else []
    preflight = evidence.get("official_site_preflight_email_validation_evidence") if isinstance(evidence, dict) else None
    if isinstance(preflight, dict):
        nested_attempts = preflight.get("candidate_attempts")
        if isinstance(nested_attempts, list):
            output.extend(nested_attempts)
    return [attempt for attempt in output if isinstance(attempt, dict)]


def build_email_validation_summary(result: ContactResult) -> str:
    lines: list[str] = []
    if result.validated_email:
        lines.append(f"Accepted: {result.validated_email} ({result.email_validation_status or 'sendable'})")

    for candidate in result.email_candidates[:12]:
        if isinstance(candidate, dict):
            line = email_candidate_summary_line(candidate)
            if line and line not in lines:
                lines.append(line)

    if not lines:
        for attempt in iter_email_attempts(result.email_validation_evidence)[:12]:
            line = email_candidate_summary_line(attempt)
            if line and line not in lines:
                lines.append(line)

    if not lines:
        skipped = compact(result.email_validation_evidence.get("skipped") if isinstance(result.email_validation_evidence, dict) else "", 120)
        error = compact(result.email_validation_evidence.get("error") if isinstance(result.email_validation_evidence, dict) else "", 200)
        if skipped:
            lines.append(f"No email validation run: {result.email_validation_status or skipped} ({skipped})")
        elif error:
            lines.append(f"Email validation error: {error}")
        elif result.email_validation_status:
            lines.append(f"Email validation status: {result.email_validation_status}")

    return "\n".join(lines[:12])


def build_patch(result: ContactResult) -> dict[str, Any]:
    email_validation_summary = build_email_validation_summary(result)
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
        "email_validation_summary": email_validation_summary,
        "email_validation_provider": result.email_validation_provider,
        "email_validation_evidence_json": json.dumps(result.email_validation_evidence, ensure_ascii=False),
        "retry_eligible": "true" if result.contact_search_status == "failed" else "false",
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

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    effective_max_queries = min(max_queries, 4) if compact(website_content, 2000) else max_queries
    templates = [
        {
            "query": f"{names_clause} Singapore {grouped_terms(['CEO', 'Founder', 'Managing Director', 'Executive Director', 'General Manager'])}".strip() if names_clause else "",
            "role": "CEO",
            "role_bucket": "c_suite",
            "covered_role_buckets": ["c_suite"],
            "role_priority": 1,
            "seniority": "executive",
        },
        {
            "query": f"site:{cleaned_domain} {grouped_terms(['about us', 'team', 'leadership', 'management', 'founders', 'doctors', 'providers', 'clinicians', 'board', 'trustees', 'governance', 'contact', 'medical director', 'operations manager', 'DPO', 'IT manager', 'HR manager'])}".strip() if cleaned_domain else "",
            "role": "Leadership",
            "role_bucket": "c_suite",
            "covered_role_buckets": TARGET_ROLE_BUCKETS,
            "role_priority": 1,
            "seniority": "executive",
        },
        {
            "query": f"{names_clause} Singapore {grouped_terms(['Medical Director', 'Principal Doctor', 'Head Doctor', 'Doctor in charge', 'Senior Doctor', 'Senior Consultant', 'Clinical Lead', 'Head of Nursing', 'Nursing Manager', 'Care Manager', 'Operations Manager', 'Practice Manager', 'Clinic Operations Manager', 'Admin Manager', 'Office Manager', 'HR Manager'])}".strip() if names_clause else "",
            "role": "Medical Director",
            "role_bucket": "clinic_leadership",
            "covered_role_buckets": ["clinic_leadership", "care_clinical", "operations", "admin_hr"],
            "role_priority": 2,
            "seniority": "manager",
        },
        {
            "query": f"{names_clause} Singapore {grouped_terms(['DPO', 'Data Protection Officer', 'Compliance Manager', 'Risk Manager', 'CISO', 'Head of Security', 'Cybersecurity Manager', 'IT Manager', 'Head of IT', 'CTO', 'Technology Manager', 'Systems Manager'])}".strip() if names_clause else "",
            "role": "DPO",
            "role_bucket": "compliance_privacy_security",
            "covered_role_buckets": ["compliance_privacy_security", "it_technology"],
            "role_priority": 3,
            "seniority": "senior_manager",
        },
        {
            "query": f"site:{cleaned_domain} {grouped_terms(['DPO', 'Data Protection Officer', 'Compliance Manager', 'Risk Manager', 'CISO', 'IT Manager', 'Head of IT', 'CTO'])}".strip() if cleaned_domain else "",
            "role": "DPO",
            "role_bucket": "compliance_privacy_security",
            "covered_role_buckets": ["compliance_privacy_security", "it_technology"],
            "role_priority": 3,
            "seniority": "senior_manager",
        },
        {
            "query": f"site:{cleaned_domain} {grouped_terms(['operations manager', 'programme manager', 'program manager', 'centre manager', 'corporate services', 'admin manager', 'office manager', 'HR manager', 'human resources', 'people manager'])}".strip() if cleaned_domain else "",
            "role": "Operations Manager",
            "role_bucket": "operations",
            "covered_role_buckets": ["operations", "admin_hr"],
            "role_priority": 4,
            "seniority": "manager",
        },
    ]
    for item in templates:
        query = compact(item["query"], 300)
        key = query.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        queries.append(item | {"query": query})
        if len(queries) >= effective_max_queries:
            return queries
    return queries
