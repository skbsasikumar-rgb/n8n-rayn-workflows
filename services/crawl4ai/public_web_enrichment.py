#!/usr/bin/env python3
"""
Public-web enrichment workflow for NocoDB organization rows.

Verified runtime:
  Python 3.11+

Install:
  python3.11 -m pip install -r services/crawl4ai/requirements-public-web-enrichment.txt
  python3.11 -m playwright install chromium

Environment:
  NOCO_BASE_URL
  NOCO_API_TOKEN
  NOCO_PROJECT_ID
  NOCO_TABLE_ID

Examples:
  python3.11 services/crawl4ai/public_web_enrichment.py --ids 12,13 --dry-run
  python3.11 services/crawl4ai/public_web_enrichment.py --limit 20 --scrape-char-limit 60000 --write-noco
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib import robotparser
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
except ImportError as exc:  # pragma: no cover - surfaced as runtime guidance
    raise SystemExit(
        "Missing crawl4ai. Install with "
        "`python3.11 -m pip install -r services/crawl4ai/requirements-public-web-enrichment.txt`."
    ) from exc

import captcha_solver


ORIGINAL_HOME = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
if os.name == "posix" and "darwin" in sys.platform:
    DEFAULT_PLAYWRIGHT_BROWSERS = ORIGINAL_HOME / "Library" / "Caches" / "ms-playwright"
else:
    DEFAULT_PLAYWRIGHT_BROWSERS = ORIGINAL_HOME / ".cache" / "ms-playwright"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(DEFAULT_PLAYWRIGHT_BROWSERS))

USER_AGENT = os.environ.get(
    "PUBLIC_WEB_ENRICHMENT_USER_AGENT",
    "RAYN Public Web Enrichment/1.0 (+https://www.raynsecure.com/)",
)
HTTP_CONNECT_TIMEOUT_SECONDS = 10
HTTP_READ_TIMEOUT_SECONDS = 45
DEFAULT_FIELDS = "Id,company_name,url_picked,best_url,notes,status"
ASSET_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".rss",
    ".atom",
    ".pdf",
    ".zip",
    ".gz",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".wav",
    ".ics",
)
SOCIAL_HOST_SUFFIXES = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
)
PARENT_RELATIONSHIP_TYPES = {
    "parent",
    "owner",
    "operator",
    "managed_by",
    "subsidiary_of",
    "branch_of",
    "brand_group",
    "clinic_network",
}
AFFILIATION_RELATIONSHIP_TYPES = {
    "affiliation",
    "professional_membership",
    "accreditation",
    "licensing_body",
    "training_institution",
    "hospital_appointment",
    "vendor",
    "location_or_landlord",
    "public_programme",
    "partner",
    "unknown",
    "rejected",
}
NON_ORG_HOST_SUFFIXES = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "yelp.com",
    "tripadvisor.com",
    "give.asia",
    "singmalls.app",
    "maps.apple.com",
    "google.com",
    "google.com.sg",
)
VALID_FINAL_STATUSES = {200, 202, 203}
REDIRECT_STATUSES = {301, 302, 307, 308}
SG_PUBLIC_SUFFIXES = {
    "com.sg",
    "org.sg",
    "net.sg",
    "edu.sg",
    "gov.sg",
    "per.sg",
}
HIGH_VALUE_KEYWORDS = (
    "about",
    "about-us",
    "our-story",
    "organization",
    "organisation",
    "team",
    "people",
    "staff",
    "leadership",
    "management",
    "senior-management",
    "executive-team",
    "board",
    "board-of-directors",
    "directors",
    "governance",
    "committee",
    "council",
    "trustees",
    "doctor",
    "doctors",
    "our-doctor",
    "our-doctors",
    "specialists",
    "consultants",
    "profiles",
    "provider",
    "providers",
    "clinic",
    "clinics",
    "service",
    "services",
    "specialty",
    "specialties",
    "treatment",
    "treatments",
    "dental",
    "dentist",
    "dentists",
    "implant",
    "implants",
    "medical",
    "health",
    "physio",
    "physiotherapy",
    "pharmacy",
    "aesthetic",
    "screening",
    "therapy",
    "location",
    "locations",
    "contact",
    "faq",
    "news",
    "careers",
    "appointment",
    "appointments",
    "book",
    "booking",
    "pricing",
    "fees",
    "insurance",
    "partners",
    "accreditation",
    "awards",
    "media",
    "blog",
    "articles",
)
COMMON_FOLLOW_PATHS = (
    "/about",
    "/about-us",
    "/our-story",
    "/who-we-are",
    "/team",
    "/our-team",
    "/people",
    "/our-people",
    "/staff",
    "/leadership",
    "/management",
    "/senior-management",
    "/executive-team",
    "/board",
    "/board-of-directors",
    "/directors",
    "/governance",
    "/organisation",
    "/organization",
    "/committee",
    "/council",
    "/trustees",
    "/doctors",
    "/our-doctors",
    "/doctor",
    "/our-doctor",
    "/specialists",
    "/consultants",
    "/our-consultants",
    "/profiles",
    "/physicians",
    "/providers",
    "/provider",
    "/practitioners",
    "/our-practitioners",
    "/dentists",
    "/our-dentists",
    "/therapists",
    "/our-therapists",
    "/contact",
    "/contact-us",
    "/locations",
    "/location",
    "/clinics",
    "/clinic",
    "/services",
    "/service",
    "/treatments",
    "/treatment",
    "/specialties",
    "/specialty",
    "/procedures",
    "/conditions",
    "/faq",
    "/faqs",
    "/news",
    "/blog",
)
HIA_HIGH_VALUE_PATH_TERMS = (
    "doctors",
    "our-doctors",
    "specialists",
    "consultants",
    "team",
    "our-team",
    "services",
    "treatments",
    "conditions",
    "locations",
    "clinics",
    "contact",
    "about",
    "appointments",
    "fees",
    "pricing",
)
NON_HIA_HIGH_VALUE_PATH_TERMS = (
    "about",
    "services",
    "contact",
    "privacy",
    "privacy-policy",
    "pdpa",
    "data-protection",
    "security",
    "trust",
    "clients",
    "case-studies",
    "platform",
    "partners",
    "team",
)
HIA_COMMON_FOLLOW_PATHS = (
    "/doctors",
    "/our-doctors",
    "/services",
    "/specialists",
    "/consultants",
    "/team",
    "/our-team",
    "/treatments",
    "/conditions",
    "/locations",
    "/clinics",
    "/contact",
    "/about",
    "/about-us",
    "/appointments",
    "/fees",
    "/pricing",
)
NON_HIA_COMMON_FOLLOW_PATHS = (
    "/about",
    "/about-us",
    "/services",
    "/contact",
    "/privacy",
    "/privacy-policy",
    "/pdpa",
    "/data-protection",
    "/security",
    "/trust",
    "/clients",
    "/case-studies",
    "/platform",
    "/partners",
    "/team",
)
LOW_VALUE_PATH_TERMS = (
    "login",
    "signin",
    "sign-in",
    "cart",
    "checkout",
    "wp-admin",
    "admin",
    "account",
    "cookie",
    "terms",
    "blog",
    "news",
    "article",
    "press",
    "media",
    "career",
    "job",
)
ASSET_PATH_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
)
TEAM_KEYWORDS = (
    "doctor",
    "doctors",
    "medical director",
    "principal dentist",
    "dentist",
    "consultant",
    "founder",
    "owner",
    "ceo",
    "chairman",
    "director",
    "manager",
    "leadership",
    "our team",
    "team",
    "provider",
    "providers",
)
AFFILIATION_PATTERNS = (
    r"\bpart of\b.{0,140}",
    r"\bmember of\b.{0,140}",
    r"\bsubsidiary of\b.{0,140}",
    r"\bbranch of\b.{0,140}",
    r"\bunder\b.{0,120}\bgroup\b",
    r"\boperated by\b.{0,140}",
    r"\bmanaged by\b.{0,140}",
    r"\bowned by\b.{0,140}",
    r"\baffiliate of\b.{0,140}",
)
ADDRESS_HINTS = (
    "road",
    "rd",
    "street",
    "st",
    "avenue",
    "ave",
    "drive",
    "dr",
    "lane",
    "ln",
    "boulevard",
    "blvd",
    "plaza",
    "tower",
    "unit",
    "level",
    "floor",
    "central",
    "parkway",
    "place",
    "crescent",
    "way",
    "court",
)
NOISE_HINTS = (
    "accept all cookies",
    "cookie settings",
    "privacy preferences",
    "skip to content",
    "back to top",
    "all rights reserved",
    "powered by",
    "newsletter",
    "subscribe",
    "follow us",
    "share this",
    "sign in",
    "log in",
    "open menu",
    "close menu",
)
NOISE_CLASS_HINTS = (
    "cookie",
    "consent",
    "banner",
    "modal",
    "popup",
    "newsletter",
    "subscribe",
    "chat",
    "whatsapp",
    "social",
    "breadcrumb",
    "menu",
    "navbar",
    "footer",
    "header",
    "sidebar",
)
NOISE_ROLE_HINTS = {"navigation", "banner", "dialog", "search", "contentinfo", "complementary"}
CHALLENGE_HINTS = (
    "captcha",
    "cf-challenge",
    "cloudflare",
    "complete the security check",
    "checking the site connection",
    "robot challenge",
    "unusual traffic",
    "verify you are human",
)


@dataclass
class InputRow:
    row_id: int | str
    company_name: str
    url_picked: str


@dataclass
class NormalizationResult:
    best_url: str
    reason: str = ""
    hostname: str = ""
    registered_domain: str = ""


@dataclass
class UrlValidationResult:
    best_url_candidate: str
    best_url: str
    http_status: int
    redirect_chain: list[dict[str, Any]]
    url_validation_status: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.url_validation_status == "validated"


@dataclass
class RobotsPolicy:
    robots_url: str
    fetched: bool
    allowed_homepage: bool
    crawl_delay_seconds: float
    sitemaps: list[str] = field(default_factory=list)
    note: str = ""
    parser: robotparser.RobotFileParser | None = field(default=None, repr=False)

    def allows(self, url: str) -> bool:
        if self.parser is None:
            return True
        return bool(self.parser.can_fetch(USER_AGENT, url))


@dataclass
class PageArtifact:
    url: str
    title: str
    meta_description: str
    page_type_guess: str = "unknown"
    summary: str = ""
    headings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    key_lines: list[str] = field(default_factory=list)
    text: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    doctor_or_team_names: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    privacy_or_pdpa_terms: list[str] = field(default_factory=list)
    customer_trust_terms: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    internal_link_items: list[dict[str, str]] = field(default_factory=list)
    social_links: list[str] = field(default_factory=list)
    logo_alt_texts: list[str] = field(default_factory=list)
    footer_legal_names: list[str] = field(default_factory=list)
    structured_data: list[dict[str, Any]] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    status_code: int = 0
    content_hash: str = ""
    challenge_hints: list[str] = field(default_factory=list)
    challenge_or_error: bool = False


@dataclass
class EnrichmentRecord:
    row_id: int | str
    company_name: str
    url_picked: str
    best_url: str
    crawl_status: str
    pages_crawled_count: int
    pages_crawled_urls: list[str]
    title: str
    meta_description: str
    organization_name_detected: str
    organization_type_guess: str
    solo_or_group_guess: str
    parent_or_affiliation_signals: list[str]
    size_signals: dict[str, Any]
    industry_guess: str
    services_detected: list[str]
    locations_detected: list[str]
    contact_info_detected: dict[str, Any]
    leadership_or_team_signals: list[str]
    social_links: list[str]
    structured_data_detected: dict[str, Any]
    enrichment_notes: str
    confidence_score: float
    error_notes: list[str]
    best_url_candidate: str = ""
    http_status: int = 0
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    url_validation_status: str = ""
    company_homepage_name: str = ""
    company_homepage_name_evidence: list[str] = field(default_factory=list)
    parent_company: str = ""
    parent_company_evidence: list[str] = field(default_factory=list)
    parent_company_confidence: str = ""
    parent_company_relationship: str = ""
    affiliations_detected: list[dict[str, Any]] = field(default_factory=list)
    rejected_parent_candidates: list[dict[str, Any]] = field(default_factory=list)
    parent_company_candidates_json: list[dict[str, Any]] = field(default_factory=list)
    website_scrape: str = ""
    raw_pages: list[dict[str, Any]] = field(default_factory=list)
    crawl_context: dict[str, Any] = field(default_factory=dict)
    timing_ms: dict[str, float] = field(default_factory=dict)
    enrichment_depth_status: str = ""
    weak_enrichment_reason: str = ""
    high_value_pages_found_json: list[dict[str, Any]] = field(default_factory=list)
    page_summaries_json: list[dict[str, Any]] = field(default_factory=list)
    homepage_content_quality: str = ""
    about_page_summary: str = ""
    services_page_summary: str = ""
    team_page_summary: str = ""
    locations_page_summary: str = ""
    privacy_page_summary: str = ""
    pricing_page_summary: str = ""
    derived_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParentCompanyCandidate:
    name: str
    raw_name: str
    relationship_pattern: str
    relationship_hint: str
    source_url: str
    source_type: str
    evidence_quote: str
    evidence_context: str
    confidence_hint: str = "Low"


@dataclass
class ParentCompanyVerification:
    parent_company: str = ""
    relationship_type: str = ""
    confidence: str = ""
    evidence: list[str] = field(default_factory=list)
    affiliations: list[dict[str, Any]] = field(default_factory=list)
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[ParentCompanyCandidate] = field(default_factory=list)
    verifier: str = "deterministic"
    verifier_error: str = ""


def require_python_311() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("This workflow requires Python 3.11+.")


def compact_whitespace(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]


def normalize_proxy_url(raw_proxy: str) -> str:
    value = compact_whitespace(raw_proxy)
    if not value:
        return ""
    if "://" in value:
        return value
    parts = value.split(":")
    if len(parts) == 4:
        host, port, username, password = parts
        return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{value}"
    return value


def configured_proxy_url() -> str:
    return normalize_proxy_url(os.getenv("PUBLIC_WEB_ENRICHMENT_PROXY_URL", ""))


def proxy_mode() -> str:
    raw = compact_whitespace(os.getenv("PUBLIC_WEB_ENRICHMENT_PROXY_MODE", "")).lower()
    if raw in {"always", "scoped", "fallback"}:
        return raw
    return "fallback"


def proxy_domains() -> list[str]:
    return [normalized_hostname(value) for value in env_csv("PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS")]


def proxy_scope_matches_url(url: str) -> bool:
    hostname = normalized_hostname(urlsplit(url).hostname or "")
    if not hostname:
        return False
    domains = proxy_domains()
    if not domains:
        return True
    row_registered_domain = registered_domain(hostname)
    for domain in domains:
        if hostname_matches(hostname, domain):
            return True
        if row_registered_domain and row_registered_domain == registered_domain(domain):
            return True
    return False


def proxy_applies_to_url(url: str) -> bool:
    proxy_url = configured_proxy_url()
    if not proxy_url:
        return False
    mode = proxy_mode()
    if mode == "always":
        return True
    if mode == "scoped":
        return proxy_scope_matches_url(url)
    return False


def proxy_retry_available_for_url(url: str) -> bool:
    proxy_url = configured_proxy_url()
    if not proxy_url:
        return False
    mode = proxy_mode()
    if mode == "always":
        return False
    if mode == "scoped":
        return proxy_scope_matches_url(url)
    domains = proxy_domains()
    if not domains:
        return True
    return proxy_scope_matches_url(url)


def proxy_config_for_url(url: str, force: bool = False) -> dict[str, str] | None:
    if not force and not proxy_applies_to_url(url):
        return None
    if force and not proxy_retry_available_for_url(url) and not proxy_applies_to_url(url):
        return None
    proxy_url = configured_proxy_url()
    parsed = urlsplit(proxy_url)
    if not parsed.hostname:
        return None
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    config = {"server": server}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.password:
        config["password"] = parsed.password
    return config


def proxy_usage_summary(proxy_retry_log: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = len(proxy_retry_log)
    successes = sum(1 for entry in proxy_retry_log if entry.get("success"))
    domains: set[str] = set()
    transports: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for entry in proxy_retry_log:
        url = str(entry.get("url") or "")
        hostname = normalized_hostname(urlsplit(url).hostname or "")
        if hostname:
            domains.add(registered_domain(hostname) or hostname)
        transport = compact_whitespace(entry.get("transport") or "")
        if transport:
            transports[transport] += 1
        reason = compact_whitespace(entry.get("reason") or "")
        if reason:
            reasons[reason.split(":", 1)[0]] += 1
    return {
        "attempt_count": attempts,
        "success_count": successes,
        "failure_count": attempts - successes,
        "domains": sorted(domains),
        "transports": dict(sorted(transports.items())),
        "reasons": dict(sorted(reasons.items())),
    }


def proxy_usage_note(proxy_retry_log: list[dict[str, Any]]) -> str:
    usage = proxy_usage_summary(proxy_retry_log)
    attempts = int(usage["attempt_count"])
    if attempts <= 0:
        return ""
    domains = usage["domains"]
    domain_text = ", ".join(domains[:5]) if domains else "unknown domain"
    if len(domains) > 5:
        domain_text += f", +{len(domains) - 5} more"
    return (
        f"Proxy fallback attempted {attempts} fetches, recovered {usage['success_count']}, "
        f"failed {usage['failure_count']}; domains: {domain_text}."
    )


def proxy_context(proxy_retry_log: list[dict[str, Any]], initial_proxy_used: bool) -> dict[str, Any]:
    return {
        "mode": proxy_mode(),
        "configured": bool(configured_proxy_url()),
        "initial_proxy_used": initial_proxy_used,
        "usage": proxy_usage_summary(proxy_retry_log),
        "retries": proxy_retry_log,
    }


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = compact_whitespace(text)
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def normalize_org_name(value: str) -> str:
    return " ".join(token for token in re.split(r"[^a-z0-9]+", compact_whitespace(value).lower()) if token)


def looks_like_person_name(value: str) -> bool:
    text = compact_whitespace(value)
    if not text:
        return False
    if re.search(r"\b(?:group|health|healthcare|medical|clinic|centre|center|hospital|company|holdings?|pte|ltd|llp|inc|society|association|academy|college|council|university|school|partners?|network|foundation|vendor|centre)\b", text, re.I):
        return False
    tokens = re.findall(r"\b[A-Z][a-zA-Z'’-]+\b", text)
    return 2 <= len(tokens) <= 4 and len(" ".join(tokens)) == len(text.strip())


def source_type_for_page(page: PageArtifact | None) -> str:
    return "official_domain" if page else "unknown"


def limit_text(value: str, max_chars: int) -> str:
    return compact_whitespace(value)[:max_chars]


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 1)


def dedupe_strings(values: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = compact_whitespace(value)
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        output.append(cleaned)
        if limit is not None and len(output) >= limit:
            break
    return output


def is_noise_line(value: str) -> bool:
    text = compact_whitespace(value)
    lowered = text.lower()
    if not text or len(text) < 3:
        return True
    if any(hint in lowered for hint in NOISE_HINTS):
        return True
    if re.fullmatch(r"(?:home|about|contact|services|blog|careers|news|terms|privacy|cookies?)", lowered):
        return True
    return False


def normalized_hostname(hostname: str) -> str:
    return compact_whitespace(hostname).strip(".").lower()


def hostname_matches(hostname: str, suffix: str) -> bool:
    return hostname == suffix or hostname.endswith("." + suffix)


def registered_domain(hostname: str) -> str:
    host = normalized_hostname(hostname)
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    tail_two = ".".join(labels[-2:])
    if tail_two in SG_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def default_port_for_scheme(scheme: str) -> int | None:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def is_non_org_host(hostname: str) -> bool:
    host = normalized_hostname(hostname)
    return any(hostname_matches(host, suffix) for suffix in NON_ORG_HOST_SUFFIXES)


def parse_url_with_default_scheme(raw_url: str) -> Any:
    source = compact_whitespace(raw_url)
    parsed = urlsplit(source)
    if parsed.scheme:
        return parsed
    return urlsplit(f"https://{source}")


def canonical_root_url(raw_url: str) -> NormalizationResult:
    source = compact_whitespace(raw_url)
    if not source:
        return NormalizationResult(best_url="", reason="url_picked is blank")

    parsed = parse_url_with_default_scheme(source)
    if parsed.scheme not in {"http", "https"}:
        return NormalizationResult(best_url="", reason="url_picked is missing a valid http(s) scheme")

    host = normalized_hostname(parsed.hostname or "")
    if not host:
        return NormalizationResult(best_url="", reason="url_picked does not contain a valid hostname")
    if is_non_org_host(host):
        return NormalizationResult(best_url="", reason=f"url_picked host `{host}` is clearly not an organization website")

    netloc = host
    if parsed.port and parsed.port != default_port_for_scheme(parsed.scheme):
        netloc = f"{host}:{parsed.port}"

    return NormalizationResult(
        best_url=f"{parsed.scheme}://{netloc}/",
        hostname=host,
        registered_domain=registered_domain(host),
    )


def canonical_homepage_url(raw_url: str) -> str:
    parsed = urlsplit(compact_whitespace(raw_url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = normalized_hostname(parsed.hostname or "")
    if not host:
        return ""
    netloc = host
    if parsed.port and parsed.port != default_port_for_scheme(parsed.scheme):
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return urlunsplit((parsed.scheme, netloc, path, "", "")).rstrip("/") + "/"


def url_with_scheme(raw_url: str, scheme: str) -> str:
    parsed = urlsplit(raw_url)
    return urlunsplit((scheme, parsed.netloc, parsed.path or "/", "", ""))


def validation_variants(best_url_candidate: str) -> list[str]:
    parsed = urlsplit(best_url_candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    https_url = url_with_scheme(best_url_candidate, "https")
    http_url = url_with_scheme(best_url_candidate, "http")
    return dedupe_strings([https_url, http_url], limit=2)


def summarize_request_error(exc: Exception) -> str:
    text = compact_whitespace(exc)
    if isinstance(exc, requests.exceptions.SSLError):
        return f"ssl_error: {text}"
    if isinstance(
        exc,
        (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout),
    ):
        return f"timeout: {text}"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"connection_error: {text}"
    return text or exc.__class__.__name__


def resolve_redirects(
    session: requests.Session,
    start_url: str,
    original_registered_domain: str,
    max_redirects: int,
) -> UrlValidationResult:
    current_url = start_url
    redirect_chain: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for _ in range(max_redirects + 1):
        if current_url in seen_urls:
            return UrlValidationResult(
                best_url_candidate=start_url,
                best_url=start_url,
                http_status=0,
                redirect_chain=redirect_chain,
                url_validation_status="failed_redirect_loop",
                error="redirect loop detected",
            )
        seen_urls.add(current_url)

        parsed = urlsplit(current_url)
        if parsed.scheme not in {"http", "https"}:
            return UrlValidationResult(
                best_url_candidate=start_url,
                best_url=start_url,
                http_status=0,
                redirect_chain=redirect_chain,
                url_validation_status="failed_unsupported_protocol",
                error=f"unsupported redirect protocol: {parsed.scheme}",
            )

        response = None
        try:
            response = session.get(
                current_url,
                allow_redirects=False,
                timeout=(HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_READ_TIMEOUT_SECONDS),
                stream=True,
            )
        except requests.RequestException as exc:
            return UrlValidationResult(
                best_url_candidate=start_url,
                best_url=start_url,
                http_status=0,
                redirect_chain=redirect_chain,
                url_validation_status="failed_request_error",
                error=summarize_request_error(exc),
            )
        finally:
            if response is not None:
                response.close()

        status_code = int(response.status_code)
        location = compact_whitespace(response.headers.get("location", ""))
        chain_item: dict[str, Any] = {"url": current_url, "status": status_code}
        if location:
            chain_item["location"] = location
        redirect_chain.append(chain_item)

        if status_code in REDIRECT_STATUSES:
            if not location:
                return UrlValidationResult(
                    best_url_candidate=start_url,
                    best_url=start_url,
                    http_status=status_code,
                    redirect_chain=redirect_chain,
                    url_validation_status="failed_redirect_without_location",
                    error=f"HTTP {status_code} redirect did not include a Location header",
                )
            next_url = urljoin(current_url, location)
            next_host = normalized_hostname(urlsplit(next_url).hostname or "")
            if not next_host:
                return UrlValidationResult(
                    best_url_candidate=start_url,
                    best_url=start_url,
                    http_status=status_code,
                    redirect_chain=redirect_chain,
                    url_validation_status="failed_invalid_redirect_target",
                    error=f"invalid redirect target: {location}",
                )
            if is_non_org_host(next_host):
                return UrlValidationResult(
                    best_url_candidate=start_url,
                    best_url=start_url,
                    http_status=status_code,
                    redirect_chain=redirect_chain,
                    url_validation_status="failed_non_org_redirect_target",
                    error=f"redirect target is not an organization website: {next_host}",
                )
            if original_registered_domain and registered_domain(next_host) != original_registered_domain:
                return UrlValidationResult(
                    best_url_candidate=start_url,
                    best_url=start_url,
                    http_status=status_code,
                    redirect_chain=redirect_chain,
                    url_validation_status="failed_cross_domain_redirect",
                    error=f"redirect left the original registered domain: {next_host}",
                )
            current_url = canonical_homepage_url(next_url) or next_url
            continue

        if status_code in VALID_FINAL_STATUSES:
            return UrlValidationResult(
                best_url_candidate=start_url,
                best_url=canonical_homepage_url(current_url) or current_url,
                http_status=status_code,
                redirect_chain=redirect_chain,
                url_validation_status="validated",
            )

        if status_code == 204:
            return UrlValidationResult(
                best_url_candidate=start_url,
                best_url=canonical_homepage_url(current_url) or current_url,
                http_status=status_code,
                redirect_chain=redirect_chain,
                url_validation_status="failed_no_content",
                error="HTTP 204 returned no crawlable homepage content",
            )

        return UrlValidationResult(
            best_url_candidate=start_url,
            best_url=canonical_homepage_url(current_url) or current_url,
            http_status=status_code,
            redirect_chain=redirect_chain,
            url_validation_status="failed_http_status",
            error=f"final HTTP status {status_code} is not crawlable",
        )

    return UrlValidationResult(
        best_url_candidate=start_url,
        best_url=start_url,
        http_status=0,
        redirect_chain=redirect_chain,
        url_validation_status="failed_redirect_depth",
        error=f"redirect depth exceeded {max_redirects}",
    )


def validate_best_url_candidate(
    session: requests.Session,
    normalization: NormalizationResult,
    max_redirects: int = 8,
) -> UrlValidationResult:
    if not normalization.best_url:
        return UrlValidationResult(
            best_url_candidate="",
            best_url="",
            http_status=0,
            redirect_chain=[],
            url_validation_status="failed_no_candidate",
            error=normalization.reason or "no URL candidate",
        )

    failures: list[UrlValidationResult] = []
    for variant in validation_variants(normalization.best_url):
        result = resolve_redirects(session, variant, normalization.registered_domain, max_redirects)
        if result.ok:
            result.best_url_candidate = normalization.best_url
            return result
        failures.append(result)

    if failures:
        first = failures[0]
        first.best_url_candidate = normalization.best_url
        return first

    return UrlValidationResult(
        best_url_candidate=normalization.best_url,
        best_url=normalization.best_url,
        http_status=0,
        redirect_chain=[],
        url_validation_status="failed_no_variants",
        error="no http(s) validation variants could be built",
    )


def filtered_query_string(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if not parsed.query:
        return ""
    allowed = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in {"fbclid", "gclid", "mc_cid", "mc_eid"}:
            continue
        allowed.append((key, value))
    return urlencode(allowed, doseq=True)


def is_html_like_url(raw_url: str) -> bool:
    path = urlsplit(raw_url).path.lower()
    return not any(path.endswith(ext) for ext in ASSET_EXTENSIONS)


def same_registered_domain(url_a: str, url_b: str) -> bool:
    host_a = normalized_hostname(urlsplit(url_a).hostname or "")
    host_b = normalized_hostname(urlsplit(url_b).hostname or "")
    return bool(host_a and host_b and registered_domain(host_a) == registered_domain(host_b))


def same_host(url_a: str, url_b: str) -> bool:
    host_a = normalized_hostname(urlsplit(url_a).hostname or "")
    host_b = normalized_hostname(urlsplit(url_b).hostname or "")
    return bool(host_a and host_b and host_a == host_b)


def make_absolute_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    absolute = urljoin(base_url, href.strip())
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if not is_html_like_url(absolute):
        return ""
    clean_query = filtered_query_string(absolute)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", clean_query, "")).rstrip("/") + (
        "/" if parsed.path in {"", "/"} else ""
    )


def build_requests_session(target_url: str = "", use_proxy: bool | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-SG,en;q=0.9",
        }
    )
    proxy_url = configured_proxy_url()
    if use_proxy is None:
        use_proxy = proxy_applies_to_url(target_url)
    if proxy_url and use_proxy:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
        session.trust_env = False
    return session


def noco_headers() -> dict[str, str]:
    token = env_required("NOCO_API_TOKEN")
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "xc-token": token,
    }


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def noco_table_url() -> str:
    base = env_required("NOCO_BASE_URL").rstrip("/")
    project = env_required("NOCO_PROJECT_ID")
    table = env_required("NOCO_TABLE_ID")
    return f"{base}/api/v1/db/data/noco/{project}/{table}"


def noco_request(method: str, url: str, body: Any | None = None, params: dict[str, Any] | None = None) -> Any:
    response = requests.request(
        method=method,
        url=url,
        headers=noco_headers(),
        json=body,
        params=params,
        timeout=60,
    )
    if response.status_code >= 400:
        raise SystemExit(f"NocoDB {response.status_code}: {response.text}")
    return response.json() if response.text else {}


def fetch_rows(limit: int, ids: str | None, where: str | None, fields: str) -> list[InputRow]:
    query_where = where
    if ids:
        row_ids = [part.strip() for part in ids.split(",") if part.strip()]
        query_where = f"(Id,in,{','.join(row_ids)})"
        limit = max(limit, len(row_ids))
    payload = noco_request(
        "GET",
        noco_table_url(),
        params={"limit": str(limit), "fields": fields, **({"where": query_where} if query_where else {})},
    )
    rows = payload.get("list", [])
    output: list[InputRow] = []
    for row in rows:
        output.append(
            InputRow(
                row_id=row.get("Id", ""),
                company_name=compact_whitespace(row.get("company_name", "")),
                url_picked=compact_whitespace(row.get("url_picked", "")),
            )
        )
    return output


def rows_from_json_payload(payload: Any) -> list[InputRow]:
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        raw_rows = payload["records"]
    elif isinstance(payload, dict) and isinstance(payload.get("list"), list):
        raw_rows = payload["list"]
    elif isinstance(payload, list):
        raw_rows = payload
    else:
        raise SystemExit("Input JSON must be a list, or an object with `records` or `list`.")

    rows: list[InputRow] = []
    for item in raw_rows:
        fields = item.get("fields", item) if isinstance(item, dict) else {}
        row_id = item.get("id") if isinstance(item, dict) else ""
        if not row_id:
            row_id = fields.get("Id", "")
        rows.append(
            InputRow(
                row_id=row_id,
                company_name=compact_whitespace(fields.get("company_name", "")),
                url_picked=compact_whitespace(fields.get("url_picked", "")),
            )
        )
    return rows


def fetch_input_rows(args: argparse.Namespace) -> list[InputRow]:
    if args.input_json:
        if args.input_json == "-":
            payload = json.load(sys.stdin)
        else:
            with Path(args.input_json).expanduser().open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        return rows_from_json_payload(payload)
    return fetch_rows(limit=args.limit, ids=args.ids, where=args.where, fields=DEFAULT_FIELDS)


def patch_rows(rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return {"updated": 0}
    bulk_url = noco_table_url().replace("/data/noco/", "/data/bulk/noco/")
    return noco_request("PATCH", bulk_url, body=rows)


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def fetch_robots_policy(session: requests.Session, homepage_url: str) -> RobotsPolicy:
    robots_url = urljoin(homepage_url, "/robots.txt")
    parser = robotparser.RobotFileParser()
    try:
        response = session.get(robots_url, timeout=(10, 20), allow_redirects=True)
    except requests.RequestException as exc:
        return RobotsPolicy(
            robots_url=robots_url,
            fetched=False,
            allowed_homepage=True,
            crawl_delay_seconds=0.0,
            note=f"robots fetch failed: {compact_whitespace(exc)}",
        )

    if response.status_code == 404:
        return RobotsPolicy(
            robots_url=robots_url,
            fetched=False,
            allowed_homepage=True,
            crawl_delay_seconds=0.0,
            note="robots.txt missing",
        )

    if response.status_code >= 400:
        return RobotsPolicy(
            robots_url=robots_url,
            fetched=False,
            allowed_homepage=True,
            crawl_delay_seconds=0.0,
            note=f"robots.txt returned HTTP {response.status_code}",
        )

    text = response.text
    parser.parse(text.splitlines())
    crawl_delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0.0
    sitemaps = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == "sitemap":
            sitemap_url = compact_whitespace(value)
            if sitemap_url:
                sitemaps.append(sitemap_url)

    return RobotsPolicy(
        robots_url=robots_url,
        fetched=True,
        allowed_homepage=bool(parser.can_fetch(USER_AGENT, homepage_url)),
        crawl_delay_seconds=float(crawl_delay or 0.0),
        sitemaps=dedupe_strings(sitemaps, limit=6),
        note="robots.txt fetched",
        parser=parser,
    )


def parse_xml_bytes(content: bytes, source_url: str) -> ET.Element | None:
    payload = content
    if source_url.endswith(".gz"):
        try:
            payload = gzip.decompress(content)
        except OSError:
            return None
    try:
        return ET.fromstring(payload)
    except ET.ParseError:
        return None


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def fetch_sitemap_candidates(
    session: requests.Session,
    homepage_url: str,
    robots_policy: RobotsPolicy,
    limit: int,
) -> list[str]:
    seeds = robots_policy.sitemaps or [urljoin(homepage_url, "/sitemap.xml")]
    queue = dedupe_strings(seeds, limit=6)
    seen_sitemaps: set[str] = set()
    candidate_urls: list[str] = []

    while queue and len(seen_sitemaps) < 4 and len(candidate_urls) < limit:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            response = session.get(sitemap_url, timeout=(10, 25), allow_redirects=True)
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue

        root = parse_xml_bytes(response.content, sitemap_url)
        if root is None:
            continue

        root_name = local_name(root.tag).lower()
        if root_name == "sitemapindex":
            for node in root.iter():
                if local_name(node.tag).lower() != "loc" or not node.text:
                    continue
                nested = compact_whitespace(node.text)
                if nested and nested not in seen_sitemaps:
                    queue.append(nested)
            continue

        if root_name != "urlset":
            continue

        for node in root.iter():
            if local_name(node.tag).lower() != "loc" or not node.text:
                continue
            candidate = compact_whitespace(node.text)
            if not candidate or not same_registered_domain(homepage_url, candidate):
                continue
            if not is_html_like_url(candidate):
                continue
            lowered = candidate.lower()
            candidate_urls.append(candidate)
            if len(candidate_urls) >= limit:
                break

    return dedupe_strings(candidate_urls, limit=limit)


def enrichment_profile_from_text(value: str) -> str:
    lowered = value.lower()
    if any(
        term in lowered
        for term in (
            "clinic",
            "medical",
            "doctor",
            "dental",
            "dentist",
            "pharmacy",
            "healthcare",
            "hospital",
            "specialist",
            "patient",
            "physio",
            "therapy",
        )
    ):
        return "hia"
    return "non_hia"


def candidate_page_score(
    homepage_url: str,
    page_url: str,
    anchor_text: str = "",
    profile: str = "auto",
) -> int:
    if not same_registered_domain(homepage_url, page_url):
        return -100
    if not is_html_like_url(page_url):
        return -100

    parsed = urlsplit(page_url)
    path = parsed.path.lower()
    if parsed.query and len(parsed.query) > 24:
        return -20
    if any(path.endswith(extension) for extension in ASSET_PATH_EXTENSIONS):
        return -100
    if path.endswith(".pdf"):
        return -20
    text = f"{path} {anchor_text.lower()}"
    if any(term in text for term in LOW_VALUE_PATH_TERMS):
        return -20

    score = 0
    selected_profile = profile if profile in {"hia", "non_hia"} else enrichment_profile_from_text(text)
    high_value_terms = HIA_HIGH_VALUE_PATH_TERMS if selected_profile == "hia" else NON_HIA_HIGH_VALUE_PATH_TERMS
    for keyword in high_value_terms:
        if keyword in text:
            score += 6
    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword in text:
            score += 3
    if "/about" in path:
        score += 3
    if any(term in text for term in ("doctor", "team", "leadership", "provider", "dentist", "consultant", "contact")):
        score += 3
    if selected_profile == "non_hia" and any(term in text for term in ("privacy", "pdpa", "data-protection", "security", "trust", "clients", "platform")):
        score += 5
    if selected_profile == "hia" and path.strip("/") in {"services", "service", "treatments", "treatment", "conditions", "procedures"}:
        score += 6
    if "blog" in text or "news" in text:
        score -= 7
    if path in {"", "/"}:
        score += 1
    if re.search(r"/(?:page|p)/\\d+", path):
        score -= 5
    score -= max(path.count("/") - 2, 0)
    return score


def choose_candidate_pages(
    homepage_url: str,
    homepage_links: list[dict[str, str]],
    sitemap_urls: list[str],
    page_limit: int,
    profile: str = "auto",
    stage: str = "fast",
) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    seen_urls: set[str] = {homepage_url}
    profile_hint = profile
    if profile_hint == "auto":
        profile_hint = enrichment_profile_from_text(
            " ".join(
                compact_whitespace(f"{link.get('href', '')} {link.get('text', '')}")
                for link in homepage_links[:40]
            )
        )

    for link in homepage_links:
        href = compact_whitespace(link.get("href", ""))
        text = compact_whitespace(link.get("text", ""))
        if not href or href in seen_urls:
            continue
        score = candidate_page_score(homepage_url, href, text, profile=profile_hint)
        if score <= 0:
            continue
        ranked.append((score + 8, 0, href))
        seen_urls.add(href)

    for sitemap_url in sitemap_urls:
        if sitemap_url in seen_urls:
            continue
        score = candidate_page_score(homepage_url, sitemap_url, "", profile=profile_hint)
        if score <= 0:
            continue
        ranked.append((score + 4, 1, sitemap_url))
        seen_urls.add(sitemap_url)

    common_paths = HIA_COMMON_FOLLOW_PATHS if profile_hint == "hia" else NON_HIA_COMMON_FOLLOW_PATHS
    if stage == "deep_retry":
        common_paths = (*common_paths, *COMMON_FOLLOW_PATHS)
    for path in common_paths:
        href = urljoin(homepage_url, path)
        if href in seen_urls:
            continue
        score = candidate_page_score(homepage_url, href, path, profile=profile_hint)
        if score <= 0:
            continue
        ranked.append((score - 12, 2, href))
        seen_urls.add(href)

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = [homepage_url]
    selected.extend(href for _, _, href in ranked[: max(page_limit - 1, 0)])
    return dedupe_strings(selected, limit=page_limit)


def prune_noise_nodes(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "template"]):
        tag.decompose()

    for tag_name in ("header", "nav", "aside", "form", "button", "input", "select", "textarea"):
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for node in list(soup.find_all(True)):
        attrs_map = getattr(node, "attrs", None)
        if not isinstance(attrs_map, dict):
            continue

        role = compact_whitespace(attrs_map.get("role", "")).lower()
        if role in NOISE_ROLE_HINTS:
            node.decompose()
            continue

        class_value = attrs_map.get("class", [])
        if isinstance(class_value, (list, tuple)):
            class_value = " ".join(compact_whitespace(item) for item in class_value if item is not None)
        else:
            class_value = compact_whitespace(class_value)

        attrs = " ".join(
            compact_whitespace(value)
            for value in (attrs_map.get("id", ""), class_value, attrs_map.get("aria-label", ""))
        ).lower()
        if attrs and any(hint in attrs for hint in NOISE_CLASS_HINTS):
            node.decompose()


def extract_footer_text(soup: BeautifulSoup) -> str:
    lines: list[str] = []
    for node in soup.select("footer, [role='contentinfo']"):
        text = compact_whitespace(node.get_text(" ", strip=True))
        if text:
            lines.append(text)
    return limit_text("\n".join(dedupe_strings(lines, limit=12)), 2000)


def extract_meta_description(soup: BeautifulSoup) -> str:
    for selector, attr in (
        ({"name": "description"}, "content"),
        ({"property": "og:description"}, "content"),
    ):
        meta = soup.find("meta", attrs=selector)
        if meta and meta.get(attr):
            return limit_text(str(meta.get(attr)), 500)
    return ""


def extract_open_graph(soup: BeautifulSoup) -> dict[str, str]:
    output: dict[str, str] = {}
    for key in ("og:site_name", "og:title", "og:description"):
        meta = soup.find("meta", attrs={"property": key})
        if meta and meta.get("content"):
            output[key] = limit_text(str(meta.get("content")), 300)
    return output


def extract_logo_alt_texts(soup: BeautifulSoup) -> list[str]:
    values: list[str] = []
    selectors = (
        "header img[alt]",
        "[class*='logo' i] img[alt]",
        "[id*='logo' i] img[alt]",
        "img[alt]",
    )
    for selector in selectors:
        for node in soup.select(selector):
            alt_text = clean_name_candidate(str(node.get("alt", "")))
            if alt_text:
                values.append(alt_text)
        if values:
            break
    return dedupe_strings(values, limit=8)


def extract_footer_legal_names(footer_text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(
        r"(?:copyright|©|\(c\))\s*(?:\d{4})?\s*(?:by\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})",
        footer_text,
        flags=re.I,
    ):
        candidate = clean_name_candidate(match.group(1))
        if candidate:
            names.append(candidate)
    return dedupe_strings(names, limit=8)


def simplify_schema_value(value: Any) -> Any:
    if isinstance(value, str):
        return limit_text(value, 500)
    if isinstance(value, list):
        simplified = [simplify_schema_value(item) for item in value[:8]]
        return [item for item in simplified if item not in (None, "", [], {})]
    if isinstance(value, dict):
        keys = (
            "@type",
            "name",
            "legalName",
            "alternateName",
            "url",
            "streetAddress",
            "addressLocality",
            "addressRegion",
            "postalCode",
            "addressCountry",
        )
        return {
            key: simplify_schema_value(value.get(key))
            for key in keys
            if value.get(key) not in (None, "", [], {})
        }
    return value


def compact_schema_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = (
        "@type",
        "name",
        "legalName",
        "alternateName",
        "url",
        "parentOrganization",
        "branchOf",
        "department",
        "address",
        "telephone",
        "email",
        "sameAs",
    )
    output: dict[str, Any] = {}
    for key in allowed_keys:
        value = item.get(key)
        if value in (None, "", [], {}):
            continue
        output[key] = simplify_schema_value(value)
    return output


def extract_schema_org(soup: BeautifulSoup) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for node in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = compact_whitespace(node.string or node.get_text(" ", strip=True))
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            compact_item = compact_schema_item(item)
            if compact_item:
                output.append(compact_item)
            if len(output) >= 10:
                return output
    return output


def extract_text_blocks(soup: BeautifulSoup) -> list[str]:
    selectors = (
        "main p, main li, main address, article p, article li, article address, [role='main'] p, [role='main'] li, [role='main'] address",
        "section p, section li, section address, .content p, .content li, .entry-content p, .entry-content li",
        "p, li, address",
    )
    blocks: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            text = compact_whitespace(node.get_text(" ", strip=True))
            if len(text) < 25 or is_noise_line(text):
                continue
            blocks.append(text)
        if len(blocks) >= 60:
            break
    return dedupe_strings(blocks, limit=80)


def extract_headings(soup: BeautifulSoup) -> list[str]:
    headings = [node.get_text(" ", strip=True) for node in soup.select("h1, h2, h3")]
    return dedupe_strings(headings, limit=25)


def extract_emails(text: str) -> list[str]:
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
    return dedupe_strings(emails, limit=20)


def extract_phones(text: str) -> list[str]:
    phones = re.findall(r"(?:(?:\+65|65)[ -]?)?(?:\d[ -]?){8,12}", text)
    cleaned = [re.sub(r"\s+", " ", value).strip() for value in phones]
    return dedupe_strings(cleaned, limit=20)


def extract_addresses(lines: list[str]) -> list[str]:
    output: list[str] = []
    for line in lines:
        cleaned = compact_whitespace(line)
        lowered = cleaned.lower()
        if len(cleaned) < 20:
            continue
        has_postal = bool(re.search(r"\b\d{6}\b", cleaned))
        has_hint = any(hint in lowered for hint in ADDRESS_HINTS)
        if "singapore" in lowered or (has_postal and has_hint) or lowered.startswith("address"):
            output.append(cleaned)
    return dedupe_strings(output, limit=20)


def extract_anchor_links(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = make_absolute_url(page_url, anchor.get("href", ""))
        if not href:
            continue
        output.append({"href": href, "text": compact_whitespace(anchor.get_text(" ", strip=True))})
    return output


def filter_social_links(links: list[dict[str, str]]) -> list[str]:
    output: list[str] = []
    for link in links:
        href = link.get("href", "")
        host = normalized_hostname(urlsplit(href).hostname or "")
        if host and any(hostname_matches(host, suffix) for suffix in SOCIAL_HOST_SUFFIXES):
            output.append(href)
    return dedupe_strings(output, limit=20)


def extract_affiliation_lines(lines: list[str]) -> list[str]:
    output: list[str] = []
    for line in lines:
        cleaned = compact_whitespace(line)
        lowered = cleaned.lower()
        if len(cleaned) < 20:
            continue
        if any(re.search(pattern, lowered) for pattern in AFFILIATION_PATTERNS):
            output.append(cleaned)
    return dedupe_strings(output, limit=20)


def extract_team_lines(lines: list[str]) -> list[str]:
    output: list[str] = []
    for line in lines:
        cleaned = compact_whitespace(line)
        lowered = cleaned.lower()
        if len(cleaned) < 8:
            continue
        if any(keyword in lowered for keyword in TEAM_KEYWORDS):
            output.append(cleaned)
    return dedupe_strings(output, limit=30)


def guess_page_type(url: str, title: str, text: str) -> str:
    haystack = f"{url} {title} {text[:1200]}".lower()
    path = urlsplit(url).path.lower()
    if path in {"", "/"}:
        return "homepage"
    if any(term in path for term in ("price", "pricing", "fee", "fees")):
        return "pricing"
    if any(term in path for term in ("doctor", "specialist", "consultant", "physician", "provider")):
        return "doctor_profile"
    if any(term in path for term in ("team", "people", "staff", "leadership", "dentist", "therapist")):
        return "team"
    if any(term in path for term in ("location", "locations", "clinic", "clinics", "outlet", "branches")):
        return "locations"
    if "contact" in path:
        return "contact"
    if any(term in path for term in ("service", "services", "treatment", "condition", "procedure", "specialty")):
        return "services"
    if any(term in path for term in ("about", "who-we-are", "our-story")):
        return "about"
    if any(term in haystack for term in ("privacy policy", "personal data protection", "pdpa", "data protection notice")):
        return "privacy_pdpa"
    if any(term in haystack for term in ("security", "trust center", "iso 27001", "soc 2", "compliance")):
        return "security_trust"
    if any(term in path for term in ("blog", "news", "article", "press")):
        return "blog"
    return "unknown"


def summarize_page_lines(lines: list[str], max_chars: int = 360) -> str:
    selected: list[str] = []
    for line in lines:
        cleaned = compact_whitespace(line)
        if not cleaned or is_noise_line(cleaned):
            continue
        selected.append(cleaned)
        if len(" ".join(selected)) >= max_chars:
            break
    return limit_text(" ".join(selected), max_chars)


def extract_key_lines(lines: list[str], limit: int = 8) -> list[str]:
    output: list[str] = []
    for line in lines:
        cleaned = compact_whitespace(line)
        lowered = cleaned.lower()
        if len(cleaned) < 16 or is_noise_line(cleaned):
            continue
        if any(
            term in lowered
            for term in (
                "doctor",
                "specialist",
                "service",
                "treatment",
                "location",
                "address",
                "privacy",
                "pdpa",
                "security",
                "trust",
                "client",
                "platform",
                "booking",
                "appointment",
            )
        ):
            output.append(cleaned)
    return dedupe_strings(output, limit=limit)


def extract_page_names(lines: list[str]) -> list[str]:
    names: list[str] = []
    pattern = re.compile(
        r"\b(?:Dr\.?|Doctor|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?)\s+[A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]+){0,3}\b"
    )
    for line in lines:
        names.extend(match.group(0).strip() for match in pattern.finditer(line))
    return dedupe_strings(names, limit=30)


def extract_page_terms(text: str, terms: tuple[str, ...], limit: int = 20) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered][:limit]


def extract_page_artifact(result_data: dict[str, Any]) -> PageArtifact:
    final_url = compact_whitespace(result_data.get("redirected_url") or result_data.get("url") or "")
    html = str(result_data.get("cleaned_html") or result_data.get("html") or "")
    soup = BeautifulSoup(html, "lxml")
    footer_text = extract_footer_text(soup)
    open_graph = extract_open_graph(soup)
    logo_alt_texts = extract_logo_alt_texts(soup)
    footer_legal_names = extract_footer_legal_names(footer_text)
    structured_data = extract_schema_org(soup)
    meta_description = extract_meta_description(soup)
    anchor_links = extract_anchor_links(soup, final_url or "")
    social_links = filter_social_links(anchor_links)
    prune_noise_nodes(soup)
    headings = extract_headings(soup)
    blocks = extract_text_blocks(soup)
    text_lines = dedupe_strings([*headings, *blocks, footer_text], limit=120)
    text = limit_text("\n".join(text_lines), 20000)
    emails = extract_emails("\n".join(text_lines))
    phones = extract_phones("\n".join(text_lines))
    addresses = extract_addresses([*blocks, footer_text])
    internal_links = [
        link["href"]
        for link in anchor_links
        if link.get("href") and same_registered_domain(final_url, link["href"])
    ]
    internal_link_items = [
        {"href": link["href"], "text": link.get("text", "")}
        for link in anchor_links
        if link.get("href") and same_registered_domain(final_url, link["href"])
    ]
    title = compact_whitespace(
        result_data.get("metadata", {}).get("title")
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
    )[:300]
    challenge_hints = detect_challenge_hints(f"{title}\n{text}\n{html[:5000]}")
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    page_type_guess = guess_page_type(final_url, title, text)
    key_lines = extract_key_lines(text_lines)
    page_services = extract_key_lines([*headings, *blocks], limit=12)
    page_locations = dedupe_strings([*addresses, *[line for line in key_lines if "location" in line.lower() or "address" in line.lower()]], limit=12)
    privacy_terms = extract_page_terms(text, ("privacy", "pdpa", "personal data", "data protection", "dpo", "consent"))
    customer_trust_terms = extract_page_terms(text, ("security", "trust", "soc 2", "iso 27001", "clients", "case study", "platform", "vendor", "partner"))
    return PageArtifact(
        url=final_url,
        title=title,
        meta_description=meta_description,
        page_type_guess=page_type_guess,
        summary=summarize_page_lines(text_lines),
        headings=headings,
        blocks=blocks,
        key_lines=key_lines,
        text=text,
        emails=emails,
        phones=phones,
        addresses=addresses,
        doctor_or_team_names=extract_page_names(text_lines),
        services=page_services,
        locations=page_locations,
        privacy_or_pdpa_terms=privacy_terms,
        customer_trust_terms=customer_trust_terms,
        internal_links=dedupe_strings(internal_links, limit=60),
        internal_link_items=internal_link_items[:120],
        social_links=social_links,
        logo_alt_texts=logo_alt_texts,
        footer_legal_names=footer_legal_names,
        structured_data=structured_data,
        open_graph=open_graph,
        status_code=int(result_data.get("status_code") or 0),
        content_hash=content_hash,
        challenge_hints=challenge_hints,
        challenge_or_error=bool(challenge_hints),
    )


def detect_challenge_hints(value: str) -> list[str]:
    lowered = compact_whitespace(value).lower()
    hints = {
        hint
        for hint in CHALLENGE_HINTS
        if hint != "cloudflare" and hint in lowered
    }
    if "cloudflare" in lowered and any(
        marker in lowered
        for marker in (
            "cf-challenge",
            "challenge-platform",
            "checking the site connection",
            "complete the security check",
            "verify you are human",
            "robot challenge",
        )
    ):
        hints.add("cloudflare")
    return sorted(hints)


def clean_name_candidate(value: str) -> str:
    text = compact_whitespace(value)
    if not text:
        return ""
    text = re.sub(r"\s*\.?\s*all rights reserved\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s*\b(?:project|website|designed|developed|powered)\s+by\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s*\.?\s*all rights reserved\.?\s*$", "", text, flags=re.I)
    parts = [part.strip() for part in re.split(r"\s+[|\-–—]\s+", text) if part.strip()]
    if parts:
        text = parts[0]
    text = re.sub(r"\bhome\b$", "", text, flags=re.I).strip(" -|–—")
    if len(text) < 3 or len(text) > 140:
        return ""
    if text.lower() in {"about us", "contact us", "services", "news"}:
        return ""
    return text


def is_generic_name_candidate(value: str) -> bool:
    lowered = compact_whitespace(value).lower()
    if not lowered:
        return True
    generic_values = {
        "about us",
        "contact us",
        "get in touch",
        "faq",
        "company profile",
        "our services",
        "our doctors",
        "our team",
        "home",
    }
    if lowered in generic_values:
        return True
    if re.fullmatch(r"(?:dental|medical|health|clinic|services?)\s+(?:clinic|services?|singapore)", lowered):
        return True
    if re.search(r"\b(?:screening|surgery|treatment|therapy|checkup|check-up|specialist|specialists)\b", lowered) and re.search(
        r"\b(?:singapore|\d{4})\b", lowered
    ):
        return True
    if len(lowered.split()) > 9:
        return True
    return False


def token_overlap_score(candidate: str, reference: str) -> int:
    candidate_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", candidate.lower())
        if len(token) >= 3 and token not in {"clinic", "medical", "dental", "singapore", "group", "health"}
    }
    reference_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", reference.lower())
        if len(token) >= 3 and token not in {"clinic", "medical", "dental", "singapore", "group", "health"}
    }
    return len(candidate_tokens & reference_tokens)


def add_name_candidate(
    scores: Counter[str],
    evidence: dict[str, list[str]],
    raw_value: str,
    source: str,
    weight: int,
    company_name: str,
) -> None:
    candidate = clean_name_candidate(raw_value)
    if not candidate or is_generic_name_candidate(candidate):
        return
    overlap = token_overlap_score(candidate, company_name)
    score = weight + (overlap * 4)
    if overlap == 0 and weight < 6:
        score -= 3
    if score <= 0:
        return
    scores[candidate] += score
    evidence.setdefault(candidate, []).append(f"{source}: {candidate}")


def name_fragments(value: str) -> list[str]:
    text = compact_whitespace(value)
    if not text:
        return []
    fragments = [part.strip() for part in re.split(r"\s+[|\-–—]\s+", text) if part.strip()]
    return fragments or [text]


def schema_name_candidates(page: PageArtifact) -> list[str]:
    candidates: list[str] = []
    for item in page.structured_data:
        for key in ("legalName", "name", "alternateName"):
            value = item.get(key)
            if isinstance(value, str):
                candidate = clean_name_candidate(value)
                if candidate:
                    candidates.append(candidate)
    return candidates


def detect_company_homepage_name(pages: list[PageArtifact], company_name: str) -> tuple[str, list[str]]:
    counter: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}
    for index, page in enumerate(pages):
        weight = 3 if index == 0 else 1
        for candidate in schema_name_candidates(page):
            add_name_candidate(counter, evidence, candidate, "schema.org name", 8 * weight, company_name)
        for key in ("og:site_name", "og:title"):
            for fragment in name_fragments(page.open_graph.get(key, "")):
                add_name_candidate(counter, evidence, fragment, key, 7 * weight, company_name)
        for logo_alt in page.logo_alt_texts:
            add_name_candidate(counter, evidence, logo_alt, "logo alt", 7 * weight, company_name)
        for fragment in name_fragments(page.title):
            add_name_candidate(counter, evidence, fragment, "page title", 5 * weight, company_name)
        for heading in page.headings[:3]:
            for fragment in name_fragments(heading):
                add_name_candidate(counter, evidence, fragment, "heading", 3 * weight, company_name)
        for footer_name in page.footer_legal_names:
            add_name_candidate(counter, evidence, footer_name, "footer legal name", 4 * weight, company_name)

    add_name_candidate(counter, evidence, company_name, "input company_name fallback", 2, company_name)

    if not counter:
        fallback = clean_name_candidate(company_name)
        return fallback, [f"fallback company_name: {fallback}"] if fallback else []

    name = counter.most_common(1)[0][0]
    return name, dedupe_strings(evidence.get(name, []), limit=8)


def detect_organization_name(pages: list[PageArtifact]) -> str:
    name, _ = detect_company_homepage_name(pages, "")
    return name


def detect_organization_type(text: str, pages: list[PageArtifact], org_name: str) -> str:
    haystack = f"{org_name}\n{text}".lower()
    homepage_context = ""
    if pages:
        homepage_context = f"{pages[0].title} {' '.join(pages[0].headings[:4])}".lower()
    if "hospital" in org_name.lower() or "hospital" in homepage_context:
        return "Hospital"
    if "dental" in haystack or "dentist" in haystack:
        return "Dental clinic"
    if "aesthetic" in org_name.lower() or "wellness" in org_name.lower() or "aesthetic" in homepage_context or "wellness" in homepage_context:
        return "Aesthetics or wellness clinic"
    if any(term in haystack for term in ("medical group", "healthcare group", "group practice", "our clinics", "network of clinics")):
        return "Healthcare group"
    if "specialist" in haystack:
        return "Specialist clinic"
    if any(term in haystack for term in ("clinic", "medical", "family medicine", "general practice", "gp")):
        return "Medical clinic"
    if any(term in haystack for term in ("care provider", "nursing", "eldercare", "community care", "rehab")):
        return "Care provider"
    if any(term in haystack for term in ("non-profit", "nonprofit", "charity", "foundation", "society")):
        return "Nonprofit organization"
    if "mission" in haystack and not any(term in haystack for term in ("clinic", "medical", "hospital", "dental", "healthcare")):
        return "Nonprofit organization"
    return "Unknown"


def detect_industry(org_type: str, text: str) -> str:
    haystack = text.lower()
    if org_type == "Nonprofit organization":
        return "Nonprofit / social services"
    if org_type in {"Medical clinic", "Specialist clinic", "Hospital", "Healthcare group"}:
        return "Healthcare provider"
    if org_type == "Dental clinic":
        return "Dental care"
    if org_type == "Aesthetics or wellness clinic":
        return "Aesthetics / wellness"
    if org_type == "Care provider":
        return "Community or long-term care"
    if "laboratory" in haystack or "diagnostic" in haystack:
        return "Diagnostics / laboratory"
    return "Unknown"


def detect_services(pages: list[PageArtifact]) -> list[str]:
    candidates: list[str] = []
    for page in pages:
        page_hint = f"{page.url} {page.title}".lower()
        if "service" in page_hint or "treatment" in page_hint or "clinic" in page_hint:
            candidates.extend(page.headings[:10])
        for line in page.blocks[:30]:
            lowered = line.lower()
            if any(term in lowered for term in ("service", "treatment", "specialty", "specialities", "specialties")):
                candidates.append(line)
    filtered = [value for value in candidates if 3 <= len(value) <= 180 and not is_noise_line(value)]
    return dedupe_strings(filtered, limit=25)


def detect_locations(pages: list[PageArtifact]) -> list[str]:
    candidates: list[str] = []
    for page in pages:
        candidates.extend(page.addresses)
        for heading in page.headings:
            lowered = heading.lower()
            if any(term in lowered for term in ("location", "locations", "clinic", "clinics", "find us")):
                candidates.append(heading)
    return dedupe_strings(candidates, limit=20)


def detect_contact_info(pages: list[PageArtifact]) -> dict[str, Any]:
    emails: list[str] = []
    phones: list[str] = []
    addresses: list[str] = []
    contact_pages: list[str] = []
    for page in pages:
        emails.extend(page.emails)
        phones.extend(page.phones)
        addresses.extend(page.addresses)
        lowered = f"{page.url} {page.title}".lower()
        if "contact" in lowered:
            contact_pages.append(page.url)
    return {
        "emails": dedupe_strings(emails, limit=20),
        "phones": dedupe_strings(phones, limit=20),
        "addresses": dedupe_strings(addresses, limit=20),
        "contact_pages": dedupe_strings(contact_pages, limit=10),
    }


def detect_leadership_signals(pages: list[PageArtifact]) -> list[str]:
    output: list[str] = []
    for page in pages:
        output.extend(extract_team_lines([*page.headings, *page.blocks]))
    return dedupe_strings(output, limit=25)


def detect_affiliation_signals(pages: list[PageArtifact]) -> list[str]:
    output: list[str] = []
    for page in pages:
        output.extend(extract_affiliation_lines([*page.headings, *page.blocks]))
        for item in page.structured_data:
            for key in ("parentOrganization", "branchOf", "department"):
                value = item.get(key)
                if isinstance(value, dict):
                    name = compact_whitespace(value.get("name", ""))
                    if name:
                        output.append(f"{key}: {name}")
                elif isinstance(value, str):
                    cleaned = compact_whitespace(value)
                    if cleaned:
                        output.append(f"{key}: {cleaned}")
    return dedupe_strings(output, limit=20)


def load_parent_company_registry() -> dict[str, Any]:
    path = Path(__file__).with_name("parent_company_registry.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"known_healthcare_groups": []}


def normalize_known_parent_name(candidate: str) -> str:
    normalized = normalize_org_name(candidate)
    if not normalized:
        return candidate
    for group in load_parent_company_registry().get("known_healthcare_groups", []):
        if not isinstance(group, dict):
            continue
        names = [group.get("name", ""), *(group.get("aliases") or [])]
        for name in names:
            if normalize_org_name(str(name)) == normalized:
                return compact_whitespace(group.get("name") or candidate)
    return candidate


def is_known_parent_group(candidate: str) -> bool:
    normalized = normalize_org_name(candidate)
    if not normalized:
        return False
    for group in load_parent_company_registry().get("known_healthcare_groups", []):
        if not isinstance(group, dict):
            continue
        names = [group.get("name", ""), *(group.get("aliases") or [])]
        if any(normalize_org_name(str(name)) == normalized for name in names):
            return True
    return False


def is_public_programme_or_scheme(candidate: str) -> bool:
    lowered = compact_whitespace(candidate).lower()
    if not lowered:
        return False
    exact = {
        "primary care network",
        "primary care network pcn",
        "pcn",
        "healthier sg",
        "community health assist scheme",
        "chas",
        "medisave",
        "moh",
        "ministry of health",
    }
    if lowered in exact:
        return True
    return any(
        term in lowered
        for term in (
            "primary care network",
            "healthier sg",
            "community health assist",
            "national initiative",
            "national programme",
            "national program",
            "subsidy",
            "subsidies",
            "scheme",
            "immunisation programme",
            "immunisation program",
        )
    )


def clean_parent_or_affiliation_candidate(value: str) -> str:
    candidate = clean_name_candidate(value)
    if not candidate or is_generic_name_candidate(candidate):
        return ""
    if is_public_programme_or_scheme(candidate):
        return ""
    candidate = re.sub(r"^(?:the|a|an)\s+", "", candidate, flags=re.I)
    if re.match(r"^(?:our|my|this|that|its|their)\s+", candidate, flags=re.I):
        return ""
    candidate = re.sub(
        r"\s+\b(?:network|group|company|healthcare group|medical group|clinic network)\b$",
        lambda match: match.group(0),
        candidate,
        flags=re.I,
    ).strip(" ,.;:-")
    if len(candidate) < 3 or len(candidate) > 120:
        return ""
    lowered = candidate.lower()
    if candidate.islower() and not re.search(
        r"\b(?:group|health|healthcare|medical|clinic|holdings?|partners?|hospital|centre|center|association|society|college|academy|council)\b",
        lowered,
    ):
        return ""
    if re.search(r"\d+[a-z]", candidate.lower()):
        return ""
    return normalize_known_parent_name(candidate)


def relationship_hint_from_pattern(pattern: str, evidence: str) -> str:
    lowered = f"{pattern} {evidence}".lower()
    if "schema.org parentorganization" in lowered or "parent company" in lowered:
        return "parent"
    if "owned by" in lowered:
        return "owner"
    if "operated by" in lowered:
        return "operator"
    if "managed by" in lowered:
        return "managed_by"
    if "subsidiary of" in lowered:
        return "subsidiary_of"
    if "branch of" in lowered:
        return "branch_of"
    if "part of" in lowered and re.search(r"\b(group|network|health|healthcare|medical)\b", lowered):
        return "clinic_network"
    if "part of" in lowered or "under" in lowered:
        return "brand_group"
    if "member of" in lowered:
        return "affiliation"
    if "affiliate" in lowered:
        return "partner"
    return "unknown"


def candidate_context(line: str, match_start: int, match_end: int) -> str:
    return compact_whitespace(line[max(0, match_start - 180) : min(len(line), match_end + 180)])


def parent_candidate_from_value(
    raw_name: str,
    relationship_pattern: str,
    source_url: str,
    source_type: str,
    evidence_quote: str,
    evidence_context: str,
    confidence_hint: str,
) -> ParentCompanyCandidate | None:
    name = clean_parent_or_affiliation_candidate(raw_name)
    if not name:
        return None
    return ParentCompanyCandidate(
        name=name,
        raw_name=compact_whitespace(raw_name),
        relationship_pattern=relationship_pattern,
        relationship_hint=relationship_hint_from_pattern(relationship_pattern, evidence_quote),
        source_url=source_url,
        source_type=source_type,
        evidence_quote=compact_whitespace(evidence_quote),
        evidence_context=compact_whitespace(evidence_context),
        confidence_hint=confidence_hint,
    )


def clean_parent_candidate(value: str, company_homepage_name: str) -> str:
    candidate = clean_name_candidate(value)
    if not candidate or is_generic_name_candidate(candidate):
        return ""
    lowered = candidate.lower()
    if is_public_programme_or_scheme(candidate):
        return ""
    if lowered in {
        "singapore",
        "ministry of health",
        "healthier sg",
        "chas",
        "medisave",
        "moh",
        "our group",
        "our network",
        "solution",
        "solution is nutrition",
    }:
        return ""
    if candidate.islower() and not re.search(
        r"\b(?:group|health|healthcare|medical|clinic|holdings?|partners?|hospital|centre|center|association|society|college|academy|council)\b",
        lowered,
    ):
        return ""
    if lowered.startswith(("solution ", "programme ", "program ", "service ", "care ", "treatment ")):
        return ""
    if any(
        term in lowered
        for term in (
            "aesthetic medicine",
            "taskforce",
            "federation",
            "foundation",
            "residency",
            "residency programme",
            "residency program",
            "training programme",
            "training program",
            "medical school",
            "business school",
            "nutrition",
            "dietetics",
            "dental care",
            "children benefit",
            "scheme",
            "subsid",
            "medical examination",
            "health screening package",
            "work passes",
            "university",
            "polytechnic",
            "award",
            "team",
            "faculty",
            "fellowship",
            "ministry",
            "hospital",
        )
    ):
        return ""
    if re.fullmatch(r"[A-Z0-9]{2,8}", candidate) and not re.search(
        r"\b(?:group|health|healthcare|medical|clinic|holdings?|partners?)\b", lowered
    ):
        return ""
    if re.search(r"\d+[a-z]", lowered):
        return ""
    if company_homepage_name and token_overlap_score(candidate, company_homepage_name) >= 2:
        return ""
    if any(term in lowered for term in ("privacy policy", "terms", "cookie", "website", "wordpress")):
        return ""
    if any(term in lowered for term in ("association", "society", "college", "academy", "council")):
        return ""
    return candidate


def extract_parent_from_line(line: str, company_homepage_name: str) -> tuple[str, str]:
    patterns = (
        r"\b(?:is|are|was|were)?\s*(?:part of|member of|owned by|operated by|managed by|belongs to)\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})",
        r"\b(?:a\s+)?subsidiary of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})",
        r"\bunder the umbrella of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})",
        r"\bparent company(?:\s+is|\s*:)?\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})",
    )
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.I)
        if not match:
            continue
        raw_name = re.split(r"[.;:\n]|(?:\s+and\s+)|(?:\s+with\s+)", match.group(1), maxsplit=1)[0]
        raw_name = raw_name.strip()
        if raw_name and raw_name[0].islower():
            continue
        candidate = clean_parent_candidate(raw_name, company_homepage_name)
        if candidate:
            return candidate, line
    return "", ""


def extract_parent_company_candidates(
    pages: list[PageArtifact],
    company_homepage_name: str,
) -> list[ParentCompanyCandidate]:
    candidates: list[ParentCompanyCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for page in pages:
        for item in page.structured_data:
            for key in ("parentOrganization", "branchOf"):
                value = item.get(key)
                raw_name = ""
                if isinstance(value, dict):
                    raw_name = compact_whitespace(value.get("name", ""))
                elif isinstance(value, str):
                    raw_name = value
                candidate = parent_candidate_from_value(
                    raw_name,
                    f"schema.org {key}",
                    page.url,
                    source_type_for_page(page),
                    f"schema.org {key}: {raw_name}",
                    json.dumps(item, ensure_ascii=True)[:1200],
                    "High",
                )
                if candidate:
                    dedupe_key = (normalize_org_name(candidate.name), candidate.relationship_pattern, candidate.source_url)
                    if dedupe_key not in seen:
                        seen.add(dedupe_key)
                        candidates.append(candidate)

        for line in [*page.headings, *page.blocks]:
            compact_line = compact_whitespace(line)
            if not compact_line:
                continue
            patterns = [
                ("owned by", r"\bowned by\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("operated by", r"\boperated by\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("managed by", r"\bmanaged by\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("subsidiary of", r"\b(?:a\s+)?subsidiary of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("branch of", r"\bbranch of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("parent company", r"\bparent company(?:\s+is|\s*:)?\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("part of", r"\bpart of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("part of group", r"\bpart of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100}?\b(?:group|network|health|healthcare|medical)\b[A-Za-z0-9&.,'() -]{0,40})"),
                ("member of", r"\bmembers? of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("affiliate of", r"\baffiliate(?:d)?(?: clinic)? of\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("under group", r"\bunder\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100}?\b(?:group|network|health|healthcare|medical)\b[A-Za-z0-9&.,'() -]{0,40})"),
                ("group company", r"\ba\s+([A-Z][A-Za-z0-9&.,'() -]{2,100}?\bgroup)\s+company\b"),
                ("powered by", r"\bpowered by\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("located at", r"\blocated at\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("accredited by", r"\baccredited by\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("licensed by", r"\blicensed by\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
                ("trained at", r"\b(?:trained|residency|fellowship|completed residency) at\s+(?:the\s+)?([A-Z][A-Za-z0-9&.,'() -]{2,100})"),
            ]
            for pattern_name, pattern in patterns:
                for match in re.finditer(pattern, compact_line, flags=re.I):
                    raw_name = re.split(r"[.;:\n]|(?:\s+and\s+)|(?:\s+with\s+)|(?:\s+where\s+)", match.group(1), maxsplit=1)[0].strip()
                    candidate = parent_candidate_from_value(
                        raw_name,
                        pattern_name,
                        page.url,
                        source_type_for_page(page),
                        compact_line,
                        candidate_context(compact_line, match.start(), match.end()),
                        "High" if pattern_name in {"owned by", "operated by", "managed by", "subsidiary of", "branch of", "parent company"} else "Low",
                    )
                    if not candidate:
                        continue
                    dedupe_key = (normalize_org_name(candidate.name), candidate.relationship_pattern, candidate.source_url)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    candidates.append(candidate)
    return candidates[:40]


def negative_parent_context(text: str) -> bool:
    lowered = compact_whitespace(text).lower()
    return any(
        phrase in lowered
        for phrase in (
            "not affiliated with",
            "independent",
            "privately owned",
            "accredited by",
            "licensed by",
            "trained at",
            "formerly at",
            "appointed at",
            "located at",
            "residency at",
            "fellowship at",
            "powered by",
        )
    )


def classify_parent_candidate(candidate: ParentCompanyCandidate, company_homepage_name: str) -> tuple[str, str]:
    text = f"{candidate.relationship_pattern} {candidate.evidence_quote}".lower()
    name_lower = candidate.name.lower()
    if looks_like_person_name(candidate.name):
        return "rejected", "person_affiliation"
    if company_homepage_name and token_overlap_score(candidate.name, company_homepage_name) >= 2:
        return "rejected", "not_parent"
    if "powered by" in text or "website by" in text:
        return "vendor", "vendor"
    if "located at" in text or any(term in name_lower for term in ("building", "tower", "plaza", "medical centre", "medical center")):
        return "location_or_landlord", "location"
    if any(term in text for term in ("trained at", "residency", "fellowship", "medical school", "university")):
        return "training_institution", "training"
    if "accredited by" in text or "accredited" in text or "subsidies" in text:
        return "accreditation", "accreditation"
    if is_public_programme_or_scheme(candidate.name):
        return "public_programme", "programme_or_scheme"
    if "scheme" in name_lower or "subsid" in name_lower:
        return "accreditation", "accreditation"
    if any(term in name_lower for term in ("medical examination", "health screening package", "work pass", "injury management")):
        return "unknown", "insufficient_evidence"
    if "licensed by" in text or any(term in name_lower for term in ("ministry", "council", "board")):
        return "licensing_body", "licensing_body"
    if any(term in name_lower for term in ("association", "society", "academy", "college", "federation")):
        return "professional_membership", "membership"
    if "member of" in text and not re.search(r"\b(group|network|health|healthcare|medical group|clinic network)\b", text):
        return "professional_membership", "membership"
    if "affiliate" in text:
        return "partner", "not_parent"
    if "owned by" in text:
        return "owner", ""
    if "operated by" in text:
        return "operator", ""
    if "managed by" in text:
        return "managed_by", ""
    if "subsidiary of" in text:
        return "subsidiary_of", ""
    if "branch of" in text or "schema.org branchof" in text:
        return "branch_of", ""
    if "parent company" in text or "schema.org parentorganization" in text:
        return "parent", ""
    if "part of" in text or "under" in text or "group company" in text:
        if is_known_parent_group(candidate.name) and re.search(r"\b(group|network|health|healthcare|medical|clinic)\b", text):
            return "clinic_network" if re.search(r"\b(clinic|health|healthcare|medical|network)\b", text) else "brand_group", ""
        return "unknown", "insufficient_evidence"
    return "unknown", "insufficient_evidence"


def parent_candidate_allowed(
    candidate: ParentCompanyCandidate,
    relationship_type: str,
    all_text: str,
    company_homepage_name: str,
    best_url: str,
) -> tuple[bool, str]:
    if relationship_type not in PARENT_RELATIONSHIP_TYPES:
        return False, "not_parent"
    if not candidate.evidence_quote:
        return False, "quote_not_found"
    if not candidate.relationship_pattern.lower().startswith("schema.org") and candidate.evidence_quote not in all_text:
        return False, "quote_not_found"
    if candidate.source_url and best_url and not same_registered_domain(candidate.source_url, best_url):
        return False, "source_domain_invalid"
    if company_homepage_name and token_overlap_score(candidate.name, company_homepage_name) >= 2:
        return False, "not_parent"
    if looks_like_person_name(candidate.name):
        return False, "person_affiliation"
    if negative_parent_context(candidate.evidence_quote) and relationship_type not in {"owner", "operator", "managed_by", "subsidiary_of", "branch_of"}:
        return False, "insufficient_evidence"
    return True, ""


def llm_parent_verifier_prompt(payload: dict[str, Any], candidates: list[ParentCompanyCandidate]) -> list[dict[str, str]]:
    candidate_payload = [asdict(candidate) for candidate in candidates[:20]]
    system = (
        "You are a strict parent-company relationship classifier. "
        "You may only classify candidates provided in parent_candidates. Do not invent, rename, complete, or add companies. "
        "Accept a parent only when official-site evidence clearly states organization-level parent, owner, operator, management, subsidiary, branch, group, or clinic-network relationship. "
        "Reject professional memberships, accreditations, licensing bodies, training institutions, hospital appointments, vendors, locations, partners, doctor biography affiliations, and weak member-of language. "
        "Return strict JSON only."
    )
    user = {
        "target_company": payload.get("target_company", ""),
        "homepage_name": payload.get("homepage_name", ""),
        "canonical_domain": payload.get("canonical_domain", ""),
        "best_url": payload.get("best_url", ""),
        "parent_candidates": candidate_payload,
        "schema": {
            "accepted_parent": {
                "name": "string",
                "relationship_type": "parent|owner|operator|managed_by|subsidiary_of|branch_of|brand_group|clinic_network",
                "confidence": "High|Medium|Low",
                "evidence_quote": "string",
                "reason": "string",
            },
            "affiliations": [
                {
                    "name": "string",
                    "relationship_type": "professional_membership|accreditation|licensing_body|training_institution|hospital_appointment|partner|unknown",
                    "evidence_quote": "string",
                    "reason": "string",
                }
            ],
            "rejected_candidates": [
                {
                    "name": "string",
                    "reason_code": "not_parent|person_affiliation|doctor_bio|training|membership|accreditation|location|vendor|insufficient_evidence|candidate_not_in_input|quote_not_found",
                    "reason": "string",
                }
            ],
        },
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def deterministic_parent_company_verification(
    candidates: list[ParentCompanyCandidate],
    company_homepage_name: str,
    all_text: str,
    best_url: str,
    verifier: str = "deterministic",
    verifier_error: str = "",
) -> ParentCompanyVerification:
    affiliations: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    accepted: list[tuple[ParentCompanyCandidate, str, str]] = []
    for candidate in candidates:
        relationship_type, reject_code = classify_parent_candidate(candidate, company_homepage_name)
        allowed, guard_code = parent_candidate_allowed(candidate, relationship_type, all_text, company_homepage_name, best_url)
        if allowed:
            confidence = candidate.confidence_hint if candidate.confidence_hint in {"High", "Medium", "Low"} else "Medium"
            if confidence == "Low":
                confidence = "Medium"
            accepted.append((candidate, relationship_type, confidence))
        elif relationship_type in AFFILIATION_RELATIONSHIP_TYPES and relationship_type not in {"rejected", "unknown"}:
            affiliations.append(
                {
                    "name": candidate.name,
                    "relationship_type": relationship_type,
                    "evidence_quote": candidate.evidence_quote,
                    "source_url": candidate.source_url,
                    "reason": reject_code or guard_code or "not a parent/operator relationship",
                }
            )
        else:
            rejected.append(
                {
                    "name": candidate.name,
                    "raw_name": candidate.raw_name,
                    "reason_code": guard_code or reject_code or "insufficient_evidence",
                    "reason": "Candidate did not pass strict parent-company guards.",
                    "evidence_quote": candidate.evidence_quote,
                    "source_url": candidate.source_url,
                }
            )

    if accepted:
        priority = {
            "parent": 1,
            "owner": 1,
            "operator": 1,
            "managed_by": 2,
            "subsidiary_of": 2,
            "branch_of": 3,
            "clinic_network": 4,
            "brand_group": 5,
        }
        accepted.sort(key=lambda item: (priority.get(item[1], 99), 0 if item[2] == "High" else 1))
        candidate, relationship_type, confidence = accepted[0]
        return ParentCompanyVerification(
            parent_company=candidate.name,
            relationship_type=relationship_type,
            confidence=confidence,
            evidence=[candidate.evidence_quote],
            affiliations=dedupe_dicts(affiliations),
            rejected_candidates=dedupe_dicts(rejected),
            candidates=candidates,
            verifier=verifier,
            verifier_error=verifier_error,
        )
    return ParentCompanyVerification(
        affiliations=dedupe_dicts(affiliations),
        rejected_candidates=dedupe_dicts(rejected),
        candidates=candidates,
        verifier=verifier,
        verifier_error=verifier_error,
    )


def dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def verify_parent_company_candidates_with_llm(
    payload: dict[str, Any],
    candidates: list[ParentCompanyCandidate],
    all_text: str,
) -> ParentCompanyVerification:
    if not candidates:
        return ParentCompanyVerification(verifier="llm", candidates=[])
    fake_response = os.getenv("PARENT_COMPANY_LLM_VERIFIER_FAKE_RESPONSE", "").strip()
    try:
        if fake_response:
            llm_payload = parse_llm_json(fake_response)
        else:
            api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
            if not api_key:
                return deterministic_parent_company_verification(
                    candidates,
                    compact_whitespace(payload.get("homepage_name")),
                    all_text,
                    compact_whitespace(payload.get("best_url")),
                    verifier="deterministic_fallback",
                    verifier_error="OPENROUTER_API_KEY is not configured",
                )
            model = os.getenv("PARENT_COMPANY_LLM_VERIFIER_MODEL", "deepseek/deepseek-v4-flash").strip()
            timeout_seconds = max(5, int(os.getenv("PARENT_COMPANY_LLM_VERIFIER_TIMEOUT_SECONDS", "20")))
            response = requests.post(
                os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions").strip(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "temperature": 0, "messages": llm_parent_verifier_prompt(payload, candidates)},
                timeout=timeout_seconds,
            )
            if response.status_code >= 400:
                return deterministic_parent_company_verification(
                    candidates,
                    compact_whitespace(payload.get("homepage_name")),
                    all_text,
                    compact_whitespace(payload.get("best_url")),
                    verifier="deterministic_fallback",
                    verifier_error=f"llm_http_{response.status_code}",
                )
            data = response.json()
            content = compact_whitespace(data.get("choices", [{}])[0].get("message", {}).get("content"))
            llm_payload = parse_llm_json(content)
    except Exception as exc:
        return deterministic_parent_company_verification(
            candidates,
            compact_whitespace(payload.get("homepage_name")),
            all_text,
            compact_whitespace(payload.get("best_url")),
            verifier="deterministic_fallback",
            verifier_error=f"llm_failed:{compact_whitespace(exc)}",
        )

    by_name = {normalize_org_name(candidate.name): candidate for candidate in candidates}
    rejected = [item for item in llm_payload.get("rejected_candidates", []) if isinstance(item, dict)]
    affiliations = [item for item in llm_payload.get("affiliations", []) if isinstance(item, dict)]
    accepted = llm_payload.get("accepted_parent") if isinstance(llm_payload.get("accepted_parent"), dict) else {}
    if accepted:
        accepted_name = compact_whitespace(accepted.get("name"))
        candidate = by_name.get(normalize_org_name(accepted_name))
        if not candidate:
            rejected.append({"name": accepted_name, "reason_code": "candidate_not_in_input", "reason": "LLM accepted a parent not present in extracted candidates."})
        else:
            relationship_type = compact_whitespace(accepted.get("relationship_type"))
            evidence_quote = compact_whitespace(accepted.get("evidence_quote"))
            if evidence_quote and evidence_quote != candidate.evidence_quote:
                candidate = ParentCompanyCandidate(**{**asdict(candidate), "evidence_quote": evidence_quote})
            allowed, guard_code = parent_candidate_allowed(
                candidate,
                relationship_type,
                all_text,
                compact_whitespace(payload.get("homepage_name")),
                compact_whitespace(payload.get("best_url")),
            )
            if allowed:
                return ParentCompanyVerification(
                    parent_company=candidate.name,
                    relationship_type=relationship_type,
                    confidence=compact_whitespace(accepted.get("confidence")) or candidate.confidence_hint,
                    evidence=[candidate.evidence_quote],
                    affiliations=dedupe_dicts(affiliations),
                    rejected_candidates=dedupe_dicts(rejected),
                    candidates=candidates,
                    verifier="llm",
                )
            rejected.append({"name": candidate.name, "reason_code": guard_code or "not_parent", "reason": "LLM accepted parent failed post-verifier guards."})
    fallback = deterministic_parent_company_verification(
        candidates,
        compact_whitespace(payload.get("homepage_name")),
        all_text,
        compact_whitespace(payload.get("best_url")),
        verifier="llm_no_accepted_parent",
    )
    fallback.affiliations = dedupe_dicts([*affiliations, *fallback.affiliations])
    fallback.rejected_candidates = dedupe_dicts([*rejected, *fallback.rejected_candidates])
    return fallback


def detect_parent_company(
    pages: list[PageArtifact],
    company_homepage_name: str,
    company_name: str = "",
    canonical_domain: str = "",
    best_url: str = "",
) -> ParentCompanyVerification:
    candidates = extract_parent_company_candidates(pages, company_homepage_name)
    all_text = "\n".join(
        value
        for page in pages
        for value in [page.text, *page.headings, *page.blocks]
        if value
    )
    payload = {
        "target_company": company_name,
        "homepage_name": company_homepage_name,
        "canonical_domain": canonical_domain,
        "best_url": best_url,
    }
    if env_flag("PARENT_COMPANY_LLM_VERIFIER_ENABLED", default=True):
        return verify_parent_company_candidates_with_llm(payload, candidates, all_text)
    return deterministic_parent_company_verification(candidates, company_homepage_name, all_text, best_url)


def detect_solo_or_group(
    org_type: str,
    locations: list[str],
    leadership_signals: list[str],
    affiliation_signals: list[str],
    all_text: str,
) -> str:
    lowered = all_text.lower()
    doctor_mentions = len(re.findall(r"\bdr\.?\b|\bdoctor\b", lowered))
    if affiliation_signals:
        return "group"
    if any(term in lowered for term in ("group", "network", "our clinics", "locations", "branches")):
        return "group"
    if len(locations) > 1 or doctor_mentions > 3 or len(leadership_signals) > 6:
        return "group"
    if org_type in {"Medical clinic", "Dental clinic", "Specialist clinic", "Aesthetics or wellness clinic"} and doctor_mentions <= 2:
        return "solo_or_small_practice"
    return "unknown"


def detect_size_signals(
    pages: list[PageArtifact],
    locations: list[str],
    leadership_signals: list[str],
    affiliation_signals: list[str],
) -> dict[str, Any]:
    combined_text = "\n".join(page.text for page in pages).lower()
    team_names = dedupe_strings([name for page in pages for name in page.doctor_or_team_names], limit=80)
    page_types = [page.page_type_guess for page in pages]
    return {
        "pages_crawled": len(pages),
        "locations_detected_count": len(locations),
        "leadership_signal_count": len(leadership_signals),
        "affiliation_signal_count": len(affiliation_signals),
        "team_count_guess": len(team_names),
        "practitioner_count_guess": len([name for name in team_names if re.search(r"\bDr\.?|\bDoctor\b|\bProf\.?", name, re.I)]),
        "location_count_guess": len(locations),
        "has_multiple_locations": len(locations) > 1 or bool(re.search(r"\b(branches|locations|our clinics|outlets)\b", combined_text)),
        "has_team_page": "team" in page_types or "doctor_profile" in page_types,
        "has_doctor_profiles": "doctor_profile" in page_types or bool(team_names),
        "has_privacy_policy": "privacy_pdpa" in page_types or "privacy policy" in combined_text,
        "has_pdpa_page": "pdpa" in combined_text or "personal data protection" in combined_text,
        "has_online_booking": bool(re.search(r"\b(book online|online booking|appointment|patient portal)\b", combined_text)),
        "has_patient_portal": "patient portal" in combined_text,
        "has_vendor_system_hint": bool(re.search(r"\b(portal|booking system|ecommerce|vendor|platform)\b", combined_text)),
        "has_customer_security_hint": bool(re.search(r"\b(security|trust|iso 27001|soc 2|compliance|vendor review)\b", combined_text)),
        "doctor_mentions": len(re.findall(r"\bdr\.?\b|\bdoctor\b", combined_text)),
        "clinic_mentions": len(re.findall(r"\bclinic\b|\bclinics\b", combined_text)),
        "branch_mentions": len(re.findall(r"\bbranch\b|\bbranches\b|\blocation\b|\blocations\b", combined_text)),
    }


def build_page_summaries(pages: list[PageArtifact]) -> list[dict[str, Any]]:
    return [
        {
            "url": page.url,
            "page_type_guess": page.page_type_guess,
            "title": page.title,
            "summary": page.summary,
            "key_lines": page.key_lines[:6],
            "emails": page.emails[:5],
            "phones": page.phones[:5],
            "addresses": page.addresses[:5],
            "doctor_or_team_names": page.doctor_or_team_names[:10],
            "services": page.services[:10],
            "locations": page.locations[:10],
            "privacy_or_pdpa_terms": page.privacy_or_pdpa_terms[:10],
            "customer_trust_terms": page.customer_trust_terms[:10],
            "challenge_or_error": page.challenge_or_error,
        }
        for page in pages
    ]


def first_summary_for_type(page_summaries: list[dict[str, Any]], page_types: tuple[str, ...]) -> str:
    for summary in page_summaries:
        if summary.get("page_type_guess") in page_types:
            return compact_whitespace(str(summary.get("summary") or ""))
    return ""


def homepage_content_quality(page: PageArtifact | None) -> str:
    if page is None:
        return "missing"
    if page.challenge_hints:
        return "challenge"
    text_len = len(page.text or "")
    if text_len >= 2500:
        return "strong"
    if text_len >= 900:
        return "adequate"
    if text_len >= 250:
        return "thin"
    return "empty"


def classify_enrichment_depth(
    pages: list[PageArtifact],
    services: list[str],
    locations: list[str],
    leadership_signals: list[str],
    organization_type: str,
    errors: list[str],
    stage: str = "fast",
) -> tuple[str, str]:
    if not pages:
        return "official_url_missing", "non_official_url"
    if pages[0].challenge_hints or (any(page.challenge_hints for page in pages) and all(page.challenge_hints or not page.text for page in pages)):
        return "challenge_blocked", "challenge_detected"
    if any("robots.txt disallows" in error.lower() for error in errors):
        return "weak_skipped", "robots_disallowed"
    quality = homepage_content_quality(pages[0])
    if quality in {"empty", "thin"}:
        return ("weak_skipped" if stage == "deep_retry" else "weak_retry_needed", "thin_content")
    page_types = {page.page_type_guess for page in pages}
    healthcareish = organization_type in {
        "Medical clinic",
        "Specialist clinic",
        "Hospital",
        "Healthcare group",
        "Dental clinic",
        "Aesthetics or wellness clinic",
        "Care provider",
    } or any(re.search(r"\b(clinic|medical|doctor|dental|healthcare|patient)\b", page.text, re.I) for page in pages)
    if not services:
        return ("weak_skipped" if stage == "deep_retry" else "weak_retry_needed", "no_services_detected")
    if healthcareish and not locations and "contact" not in page_types and "locations" not in page_types:
        return ("weak_skipped" if stage == "deep_retry" else "weak_retry_needed", "no_locations_detected")
    if healthcareish and not leadership_signals and "team" not in page_types and "doctor_profile" not in page_types:
        return ("weak_skipped" if stage == "deep_retry" else "weak_retry_needed", "no_team_or_contact_page")
    if len(pages) <= 1:
        return ("weak_skipped" if stage == "deep_retry" else "weak_retry_needed", "homepage_only")
    if len(pages) >= 4 and services and (locations or leadership_signals):
        return "strong", ""
    return "adequate", ""


def structured_data_summary(pages: list[PageArtifact], sitemap_urls: list[str]) -> dict[str, Any]:
    schema_types: list[str] = []
    schema_names: list[str] = []
    og_site_name = ""
    for page in pages:
        if not og_site_name:
            og_site_name = compact_whitespace(page.open_graph.get("og:site_name", ""))
        for item in page.structured_data:
            value = item.get("@type")
            if isinstance(value, str):
                schema_types.append(value)
            elif isinstance(value, list):
                schema_types.extend(str(item_value) for item_value in value)
            for key in ("legalName", "name", "alternateName"):
                candidate = item.get(key)
                if isinstance(candidate, str):
                    cleaned = clean_name_candidate(candidate)
                    if cleaned:
                        schema_names.append(cleaned)
    return {
        "has_json_ld": any(page.structured_data for page in pages),
        "schema_types": dedupe_strings(schema_types, limit=20),
        "schema_names": dedupe_strings(schema_names, limit=20),
        "og_site_name": og_site_name,
        "sitemap_urls": sitemap_urls[:20],
    }


def confidence_score_for_record(record: EnrichmentRecord) -> float:
    score = 0.0
    if record.best_url:
        score += 0.25
    if record.pages_crawled_count:
        score += 0.15
    if record.organization_name_detected:
        score += 0.1
    if record.title or record.meta_description:
        score += 0.1
    if record.structured_data_detected.get("has_json_ld"):
        score += 0.1
    if record.contact_info_detected.get("emails") or record.contact_info_detected.get("phones") or record.contact_info_detected.get("addresses"):
        score += 0.1
    if record.services_detected:
        score += 0.05
    if record.locations_detected:
        score += 0.05
    if record.leadership_or_team_signals:
        score += 0.05
    if record.parent_or_affiliation_signals:
        score += 0.05
    if record.crawl_status in {"partial", "crawl_failed", "blocked_by_robots"}:
        score -= 0.1
    return round(max(0.0, min(score, 0.98)), 2)


def split_crawl_errors(best_url: str, errors: list[str]) -> tuple[list[str], list[str]]:
    fatal_errors: list[str] = []
    ignored_errors: list[str] = []
    for error in errors:
        match = re.match(r"^(https?://\S+): HTTP (\d{3})\b", error)
        if match:
            error_url, status_code_text = match.groups()
            if int(status_code_text) == 404 and same_registered_domain(error_url, best_url):
                ignored_errors.append(error)
                continue
        fatal_errors.append(error)
    return fatal_errors, ignored_errors


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "High"
    if score >= 0.45:
        return "Medium"
    return "Low"


def render_page_section(page: PageArtifact, include_blocks: int) -> str:
    lines: list[str] = []
    if page.title:
        lines.append(f"# {page.title}")
    if page.url:
        lines.append(page.url)
    if page.meta_description:
        lines.append(page.meta_description)
    lines.extend(page.headings[:8])
    lines.extend(page.blocks[:include_blocks])
    if page.emails or page.phones:
        contact_bits = [*page.emails[:5], *page.phones[:5]]
        lines.append("Contacts: " + "; ".join(dedupe_strings(contact_bits, limit=10)))
    return "\n".join(lines).strip()


def build_website_scrape(pages: list[PageArtifact], max_chars: int) -> str:
    sections = [render_page_section(page, include_blocks=10 if index == 0 else 6) for index, page in enumerate(pages)]
    cleaned = [section for section in sections if section]
    return limit_text("\n\n".join(cleaned), max_chars)


def make_raw_page(page: PageArtifact) -> dict[str, Any]:
    data = asdict(page)
    data["text"] = limit_text(data["text"], 12000)
    return data


async def crawl_url(
    crawler: AsyncWebCrawler,
    url: str,
    page_timeout_ms: int,
    proxy_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_config = CrawlerRunConfig(
        cache_mode=getattr(CacheMode, "BYP" + "ASS"),
        page_timeout=page_timeout_ms,
        wait_until="domcontentloaded",
        delay_before_return_html=0.2,
        mean_delay=0.1,
        max_range=0.2,
        semaphore_count=1,
        remove_overlay_elements=True,
        exclude_all_images=True,
        exclude_external_images=True,
        scan_full_page=True,
        max_scroll_steps=3,
        proxy_config=proxy_config,
        verbose=False,
    )
    result = await crawler.arun(url=url, config=run_config)
    data = result.model_dump()
    if not data.get("success"):
        raise RuntimeError(compact_whitespace(data.get("error_message", "")) or "crawl4ai crawl failed")
    if int(data.get("status_code") or 0) >= 400:
        raise RuntimeError(f"HTTP {data.get('status_code')}")
    return data


def proxy_retryable_error(error_text: str) -> bool:
    lowered = compact_whitespace(error_text).lower()
    return any(
        marker in lowered
        for marker in (
            "http 403",
            "http 429",
            "http 503",
            "forbidden",
            "too many requests",
            "cf-challenge",
            "captcha",
            "challenge",
        )
    )


def fetch_static_url(session: requests.Session, url: str) -> dict[str, Any]:
    connect_timeout = float(os.getenv("PUBLIC_WEB_STATIC_CONNECT_TIMEOUT_SECONDS", "5"))
    read_timeout = float(os.getenv("PUBLIC_WEB_STATIC_READ_TIMEOUT_SECONDS", "12"))
    response = session.get(url, timeout=(connect_timeout, read_timeout), allow_redirects=True)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}")
    return {
        "success": True,
        "url": url,
        "redirected_url": response.url,
        "status_code": response.status_code,
        "html": response.text,
        "cleaned_html": response.text,
        "metadata": {},
    }


async def retry_crawl_with_proxy(
    crawler: AsyncWebCrawler,
    url: str,
    page_timeout_ms: int,
    errors: list[str],
    proxy_retry_log: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any] | None:
    proxy_config = proxy_config_for_url(url, force=True)
    if not proxy_config:
        return None
    started = time.perf_counter()
    try:
        result = await crawl_url(crawler, url, page_timeout_ms, proxy_config=proxy_config)
        page = extract_page_artifact(result)
        if page.challenge_hints:
            proxy_retry_log.append(
                {
                    "url": url,
                    "reason": reason,
                    "transport": "crawl4ai_proxy",
                    "success": False,
                    "challenge_hints": page.challenge_hints,
                    "duration_ms": elapsed_ms(started),
                }
            )
            errors.append(f"{url}: proxy retry still returned challenge page")
            return None
        proxy_retry_log.append(
            {
                "url": url,
                "reason": reason,
                "transport": "crawl4ai_proxy",
                "success": True,
                "duration_ms": elapsed_ms(started),
            }
        )
        errors.append(f"{url}: proxy retry recovered crawl after {reason}")
        return result
    except Exception as exc:
        proxy_retry_log.append(
            {
                "url": url,
                "reason": reason,
                "transport": "crawl4ai_proxy",
                "success": False,
                "error": compact_whitespace(exc),
                "duration_ms": elapsed_ms(started),
            }
        )
        errors.append(f"{url}: proxy retry failed: {compact_whitespace(exc)}")
        return None


def retry_static_with_proxy(
    url: str,
    errors: list[str],
    proxy_retry_log: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any] | None:
    if not proxy_retry_available_for_url(url):
        return None
    session = build_requests_session(url, use_proxy=True)
    started = time.perf_counter()
    try:
        result = fetch_static_url(session, url)
        page = extract_page_artifact(result)
        if page.challenge_hints:
            proxy_retry_log.append(
                {
                    "url": url,
                    "reason": reason,
                    "transport": "static_proxy",
                    "success": False,
                    "challenge_hints": page.challenge_hints,
                    "duration_ms": elapsed_ms(started),
                }
            )
            errors.append(f"{url}: proxy static retry still returned challenge page")
            return None
        proxy_retry_log.append(
            {
                "url": url,
                "reason": reason,
                "transport": "static_proxy",
                "success": True,
                "duration_ms": elapsed_ms(started),
            }
        )
        errors.append(f"{url}: proxy static retry recovered after {reason}")
        return result
    except Exception as exc:
        proxy_retry_log.append(
            {
                "url": url,
                "reason": reason,
                "transport": "static_proxy",
                "success": False,
                "error": compact_whitespace(exc),
                "duration_ms": elapsed_ms(started),
            }
        )
        errors.append(f"{url}: proxy static retry failed: {compact_whitespace(exc)}")
        return None


def build_homepage_links(page: PageArtifact) -> list[dict[str, str]]:
    if page.internal_link_items:
        return page.internal_link_items
    return [{"href": href, "text": ""} for href in page.internal_links]


async def enrich_row(
    row: InputRow,
    crawler: AsyncWebCrawler,
    page_limit: int,
    page_timeout_ms: int,
    request_delay_seconds: float,
    scrape_char_limit: int,
    enrichment_stage: str = "fast",
    per_row_page_concurrency: int = 2,
) -> EnrichmentRecord:
    total_started = time.perf_counter()
    timings: dict[str, float] = {}

    def stamp(record: EnrichmentRecord) -> EnrichmentRecord:
        record.timing_ms = {**timings, "total_ms": elapsed_ms(total_started)}
        return record

    errors: list[str] = []
    proxy_retry_log: list[dict[str, Any]] = []
    normalize_started = time.perf_counter()
    normalization = canonical_root_url(row.url_picked)
    timings["normalize_ms"] = elapsed_ms(normalize_started)
    if not normalization.best_url:
        return stamp(EnrichmentRecord(
            row_id=row.row_id,
            company_name=row.company_name,
            url_picked=row.url_picked,
            best_url="",
            crawl_status="skipped_no_url" if not row.url_picked else "skipped_invalid_url",
            pages_crawled_count=0,
            pages_crawled_urls=[],
            title="",
            meta_description="",
            organization_name_detected="",
            organization_type_guess="Unknown",
            solo_or_group_guess="unknown",
            parent_or_affiliation_signals=[],
            size_signals={"pages_crawled": 0},
            industry_guess="Unknown",
            services_detected=[],
            locations_detected=[],
            contact_info_detected={"emails": [], "phones": [], "addresses": [], "contact_pages": []},
            leadership_or_team_signals=[],
            social_links=[],
            structured_data_detected={"has_json_ld": False, "schema_types": [], "schema_names": [], "og_site_name": "", "sitemap_urls": []},
            enrichment_notes=normalization.reason,
            confidence_score=0.0,
            error_notes=[normalization.reason],
            best_url_candidate="",
            http_status=0,
            redirect_chain=[],
            url_validation_status="failed_no_candidate",
        ))

    session = build_requests_session(normalization.best_url)
    validation_started = time.perf_counter()
    validation = validate_best_url_candidate(session, normalization)
    timings["validation_ms"] = elapsed_ms(validation_started)
    if not validation.ok:
        error_text = validation.error or validation.url_validation_status
        return stamp(EnrichmentRecord(
            row_id=row.row_id,
            company_name=row.company_name,
            url_picked=row.url_picked,
            best_url=validation.best_url if validation.best_url == normalization.best_url else "",
            crawl_status="skipped_url_validation_failed",
            pages_crawled_count=0,
            pages_crawled_urls=[],
            title="",
            meta_description="",
            organization_name_detected="",
            organization_type_guess="Unknown",
            solo_or_group_guess="unknown",
            parent_or_affiliation_signals=[],
            size_signals={"pages_crawled": 0},
            industry_guess="Unknown",
            services_detected=[],
            locations_detected=[],
            contact_info_detected={"emails": [], "phones": [], "addresses": [], "contact_pages": []},
            leadership_or_team_signals=[],
            social_links=[],
            structured_data_detected={"has_json_ld": False, "schema_types": [], "schema_names": [], "og_site_name": "", "sitemap_urls": []},
            enrichment_notes=f"URL validation failed: {error_text}",
            confidence_score=0.0,
            error_notes=[error_text],
            best_url_candidate=validation.best_url_candidate,
            http_status=validation.http_status,
            redirect_chain=validation.redirect_chain,
            url_validation_status=validation.url_validation_status,
        ))

    best_url = validation.best_url
    crawl_proxy_config = proxy_config_for_url(best_url)
    if not same_host(normalization.best_url, best_url):
        session = build_requests_session(best_url)
    robots_started = time.perf_counter()
    robots_policy = fetch_robots_policy(session, best_url)
    timings["robots_ms"] = elapsed_ms(robots_started)
    if not robots_policy.allowed_homepage:
        return stamp(EnrichmentRecord(
            row_id=row.row_id,
            company_name=row.company_name,
            url_picked=row.url_picked,
            best_url=best_url,
            crawl_status="blocked_by_robots",
            pages_crawled_count=0,
            pages_crawled_urls=[],
            title="",
            meta_description="",
            organization_name_detected="",
            organization_type_guess="Unknown",
            solo_or_group_guess="unknown",
            parent_or_affiliation_signals=[],
            size_signals={"pages_crawled": 0},
            industry_guess="Unknown",
            services_detected=[],
            locations_detected=[],
            contact_info_detected={"emails": [], "phones": [], "addresses": [], "contact_pages": []},
            leadership_or_team_signals=[],
            social_links=[],
            structured_data_detected={"has_json_ld": False, "schema_types": [], "schema_names": [], "og_site_name": "", "sitemap_urls": []},
            enrichment_notes="robots.txt disallows the homepage crawl",
            confidence_score=0.0,
            error_notes=["robots.txt disallows the homepage crawl"],
            best_url_candidate=validation.best_url_candidate,
            http_status=validation.http_status,
            redirect_chain=validation.redirect_chain,
            url_validation_status=validation.url_validation_status,
            crawl_context={"robots": {"url": robots_policy.robots_url, "note": robots_policy.note}},
        ))

    crawled_pages: list[PageArtifact] = []
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()

    stage = "deep_retry" if enrichment_stage == "deep_retry" else "fast"
    fast_static_first = stage == "fast" and os.getenv("PUBLIC_ENRICH_FAST_STATIC_FIRST", "true").lower() != "false"
    fast_browser_fallback = os.getenv("PUBLIC_ENRICH_FAST_BROWSER_FALLBACK", "false").lower() == "true"
    homepage_result: dict[str, Any] | None = None

    if fast_static_first:
        try:
            static_started = time.perf_counter()
            homepage_result = fetch_static_url(session, best_url)
            timings["homepage_static_ms"] = elapsed_ms(static_started)
            errors.append(f"{best_url}: fast static homepage fetch used")
        except Exception as static_exc:
            if not fast_browser_fallback:
                error_text = compact_whitespace(static_exc) or "static homepage fetch failed"
                return stamp(EnrichmentRecord(
                    row_id=row.row_id,
                    company_name=row.company_name,
                    url_picked=row.url_picked,
                    best_url=best_url,
                    crawl_status="crawl_failed",
                    pages_crawled_count=0,
                    pages_crawled_urls=[],
                    title="",
                    meta_description="",
                    organization_name_detected="",
                    organization_type_guess="Unknown",
                    solo_or_group_guess="unknown",
                    parent_or_affiliation_signals=[],
                    size_signals={"pages_crawled": 0},
                    industry_guess="Unknown",
                    services_detected=[],
                    locations_detected=[],
                    contact_info_detected={"emails": [], "phones": [], "addresses": [], "contact_pages": []},
                    leadership_or_team_signals=[],
                    social_links=[],
                    structured_data_detected={"has_json_ld": False, "schema_types": [], "schema_names": [], "og_site_name": "", "sitemap_urls": []},
                    enrichment_notes=f"Fast static homepage fetch failed: {error_text}",
                    confidence_score=0.05,
                    error_notes=[error_text],
                    best_url_candidate=validation.best_url_candidate,
                    http_status=validation.http_status,
                    redirect_chain=validation.redirect_chain,
                    url_validation_status=validation.url_validation_status,
                    crawl_context={
                        "robots": {"url": robots_policy.robots_url, "note": robots_policy.note},
                        "fast_static_first": True,
                    },
                ))
            errors.append(f"{best_url}: fast static homepage fetch failed; browser fallback used: {compact_whitespace(static_exc)}")

    if homepage_result is None:
        try:
            homepage_started = time.perf_counter()
            homepage_result = await crawl_url(crawler, best_url, page_timeout_ms, proxy_config=crawl_proxy_config)
            timings["homepage_crawl_ms"] = elapsed_ms(homepage_started)
        except Exception as exc:
            crawl_error_text = compact_whitespace(exc)
            try:
                static_started = time.perf_counter()
                homepage_result = fetch_static_url(session, best_url)
                timings["homepage_static_fallback_ms"] = elapsed_ms(static_started)
                errors.append(f"{best_url}: Crawl4AI fallback used after homepage error: {crawl_error_text}")
            except Exception as fallback_exc:
                error_text = compact_whitespace(fallback_exc) or crawl_error_text
                if proxy_retryable_error(crawl_error_text) or proxy_retryable_error(error_text):
                    homepage_result = await retry_crawl_with_proxy(
                        crawler,
                        best_url,
                        page_timeout_ms,
                        errors,
                        proxy_retry_log,
                        reason=f"homepage_error:{crawl_error_text or error_text}",
                    )
                    if homepage_result is None:
                        homepage_result = retry_static_with_proxy(
                            best_url,
                            errors,
                            proxy_retry_log,
                            reason=f"homepage_error:{crawl_error_text or error_text}",
                        )
                    if homepage_result is not None:
                        timings["homepage_proxy_recovery_ms"] = timings.get("homepage_proxy_recovery_ms", 0.0) + elapsed_ms(homepage_started)
                        error_text = ""
                if not error_text:
                    pass
                else:
                    return stamp(EnrichmentRecord(
                        row_id=row.row_id,
                        company_name=row.company_name,
                        url_picked=row.url_picked,
                        best_url=best_url,
                        crawl_status="crawl_failed",
                        pages_crawled_count=0,
                        pages_crawled_urls=[],
                        title="",
                        meta_description="",
                        organization_name_detected="",
                        organization_type_guess="Unknown",
                        solo_or_group_guess="unknown",
                        parent_or_affiliation_signals=[],
                        size_signals={"pages_crawled": 0},
                        industry_guess="Unknown",
                        services_detected=[],
                        locations_detected=[],
                        contact_info_detected={"emails": [], "phones": [], "addresses": [], "contact_pages": []},
                        leadership_or_team_signals=[],
                        social_links=[],
                        structured_data_detected={"has_json_ld": False, "schema_types": [], "schema_names": [], "og_site_name": "", "sitemap_urls": []},
                        enrichment_notes=compact_whitespace(
                            f"Homepage crawl failed: {error_text} {proxy_usage_note(proxy_retry_log)}"
                        ),
                        confidence_score=0.05,
                        error_notes=[error_text],
                        best_url_candidate=validation.best_url_candidate,
                        http_status=validation.http_status,
                        redirect_chain=validation.redirect_chain,
                        url_validation_status=validation.url_validation_status,
                        crawl_context={
                            "robots": {"url": robots_policy.robots_url, "note": robots_policy.note},
                            "proxy": proxy_context(proxy_retry_log, bool(crawl_proxy_config)),
                        },
                    ))

    homepage_page = extract_page_artifact(homepage_result)
    if homepage_page.challenge_hints:
        challenge_note = "challenge page detected: " + ", ".join(homepage_page.challenge_hints)
        captcha_solved = False
        allow_challenge_recovery = stage != "fast" or os.getenv("PUBLIC_ENRICH_FAST_CHALLENGE_RECOVERY", "false").lower() == "true"
        if allow_challenge_recovery:
            try:
                static_started = time.perf_counter()
                static_result = fetch_static_url(session, best_url)
                timings["homepage_static_challenge_recovery_ms"] = elapsed_ms(static_started)
                static_page = extract_page_artifact(static_result)
                if static_page.text and not static_page.challenge_hints:
                    homepage_result = static_result
                    homepage_page = static_page
                    challenge_note = ""
                    captcha_solved = True
                    errors.append(f"{best_url}: static fetch recovered after challenge page")
            except Exception as static_exc:
                errors.append(f"{best_url}: static challenge recovery failed: {compact_whitespace(static_exc)}")
        if not captcha_solved and allow_challenge_recovery and proxy_retry_available_for_url(best_url):
            proxy_result = await retry_crawl_with_proxy(
                crawler,
                best_url,
                page_timeout_ms,
                errors,
                proxy_retry_log,
                reason="homepage_challenge_detected",
            )
            if proxy_result is None:
                proxy_result = retry_static_with_proxy(
                    best_url,
                    errors,
                    proxy_retry_log,
                    reason="homepage_challenge_detected",
                )
            if proxy_result is not None:
                homepage_result = proxy_result
                homepage_page = extract_page_artifact(proxy_result)
                challenge_note = ""
                captcha_solved = not homepage_page.challenge_hints
        if not captcha_solved and allow_challenge_recovery and captcha_solver.is_configured():
            try:
                from playwright.async_api import async_playwright as _ap
                async with _ap() as playwright:
                    browser = await playwright.chromium.launch(
                        headless=os.getenv("CRAWL4AI_HEADLESS", "true").lower() != "false",
                        args=["--disable-dev-shm-usage", "--no-sandbox"],
                        **({"proxy": crawl_proxy_config} if crawl_proxy_config else {}),
                    )
                    try:
                        ctx = await browser.new_context(ignore_https_errors=True)
                        pg = await ctx.new_page()
                        await pg.goto(best_url, wait_until="domcontentloaded", timeout=page_timeout_ms)
                        try:
                            await pg.wait_for_load_state("networkidle", timeout=min(page_timeout_ms, 10000))
                        except Exception:
                            pass
                        html = await pg.content()
                        if captcha_solver._detect_captcha_type(html):
                            solved = await captcha_solver.solve_page_captcha(pg, html)
                            if solved:
                                await pg.wait_for_timeout(3000)
                                try:
                                    await pg.wait_for_load_state("networkidle", timeout=10000)
                                except Exception:
                                    pass
                                solved_html = await pg.content()
                                homepage_result = {
                                    "success": True,
                                    "url": best_url,
                                    "redirected_url": pg.url,
                                    "status_code": 200,
                                    "html": solved_html,
                                    "cleaned_html": solved_html,
                                    "metadata": {},
                                }
                                homepage_page = extract_page_artifact(homepage_result)
                                captcha_solved = not homepage_page.challenge_hints
                    finally:
                        await browser.close()
            except Exception as captcha_exc:
                logger.warning("captcha solve attempt failed for %s: %s", best_url, captcha_exc)

        if not captcha_solved:
            return stamp(EnrichmentRecord(
                row_id=row.row_id,
                company_name=row.company_name,
                url_picked=row.url_picked,
                best_url=best_url,
                crawl_status="skipped_challenge_detected",
                pages_crawled_count=1,
                pages_crawled_urls=[homepage_page.url or best_url],
                title=homepage_page.title,
                meta_description=homepage_page.meta_description,
                organization_name_detected="",
                organization_type_guess="Unknown",
                solo_or_group_guess="unknown",
                parent_or_affiliation_signals=[],
                size_signals={"pages_crawled": 1},
                industry_guess="Unknown",
                services_detected=[],
                locations_detected=[],
                contact_info_detected={"emails": [], "phones": [], "addresses": [], "contact_pages": []},
                leadership_or_team_signals=[],
                social_links=[],
                structured_data_detected={"has_json_ld": False, "schema_types": [], "schema_names": [], "og_site_name": "", "sitemap_urls": []},
                enrichment_notes=compact_whitespace(f"{challenge_note} {proxy_usage_note(proxy_retry_log)}"),
                confidence_score=0.05,
                error_notes=[challenge_note],
                best_url_candidate=validation.best_url_candidate,
                http_status=validation.http_status,
                redirect_chain=validation.redirect_chain,
                url_validation_status=validation.url_validation_status,
                crawl_context={
                    "robots": {"url": robots_policy.robots_url, "note": robots_policy.note},
                    "challenge_hints": homepage_page.challenge_hints,
                    "captcha_solver": captcha_solver.solver_diagnostics(),
                    "proxy": proxy_context(proxy_retry_log, bool(crawl_proxy_config)),
                },
            ))
    resolved_homepage = canonical_root_url(homepage_page.url or best_url)
    if resolved_homepage.best_url:
        previous_best_url = best_url
        best_url = resolved_homepage.best_url
        crawl_proxy_config = proxy_config_for_url(best_url)
        if not same_host(previous_best_url, best_url):
            session = build_requests_session(best_url)
            robots_started = time.perf_counter()
            robots_policy = fetch_robots_policy(session, best_url)
            timings["robots_ms"] = timings.get("robots_ms", 0.0) + elapsed_ms(robots_started)

    crawled_pages.append(homepage_page)
    seen_urls.add(homepage_page.url)
    if homepage_page.content_hash:
        seen_hashes.add(homepage_page.content_hash)

    page_limit = min(max(page_limit, 1), 16 if stage == "deep_retry" else 8)
    per_row_page_concurrency = min(max(per_row_page_concurrency, 1), 2)
    sitemap_urls = fetch_sitemap_candidates(session, best_url, robots_policy, limit=max(page_limit * 6, 20))
    homepage_links = build_homepage_links(homepage_page)
    profile_hint = enrichment_profile_from_text(f"{row.company_name} {homepage_page.title} {homepage_page.text[:3000]}")
    candidates = choose_candidate_pages(
        best_url,
        homepage_links,
        sitemap_urls,
        page_limit=page_limit,
        profile=profile_hint,
        stage=stage,
    )
    queued_urls: set[str] = set(candidates)
    delay_seconds = max(request_delay_seconds, robots_policy.crawl_delay_seconds)

    for candidate_url in candidates[1:]:
        if len(crawled_pages) >= page_limit:
            break
        if candidate_url in seen_urls:
            continue
        if not robots_policy.allows(candidate_url):
            errors.append(f"robots.txt disallows {candidate_url}")
            continue
        await asyncio.sleep(delay_seconds)
        try:
            candidate_started = time.perf_counter()
            candidate_result = await crawl_url(crawler, candidate_url, page_timeout_ms, proxy_config=crawl_proxy_config)
            timings["candidate_crawls_ms"] = timings.get("candidate_crawls_ms", 0.0) + elapsed_ms(candidate_started)
        except Exception as exc:
            crawl_error_text = compact_whitespace(exc)
            try:
                static_started = time.perf_counter()
                candidate_result = fetch_static_url(session, candidate_url)
                timings["candidate_static_fallback_ms"] = timings.get("candidate_static_fallback_ms", 0.0) + elapsed_ms(static_started)
                errors.append(f"{candidate_url}: Crawl4AI fallback used after page error: {crawl_error_text}")
            except Exception as fallback_exc:
                candidate_result = None
                fallback_error = compact_whitespace(fallback_exc) or crawl_error_text
                if proxy_retryable_error(crawl_error_text) or proxy_retryable_error(fallback_error):
                    candidate_result = await retry_crawl_with_proxy(
                        crawler,
                        candidate_url,
                        page_timeout_ms,
                        errors,
                        proxy_retry_log,
                        reason=f"candidate_error:{crawl_error_text or fallback_error}",
                    )
                    if candidate_result is None:
                        candidate_result = retry_static_with_proxy(
                            candidate_url,
                            errors,
                            proxy_retry_log,
                            reason=f"candidate_error:{crawl_error_text or fallback_error}",
                        )
                if candidate_result is None:
                    errors.append(f"{candidate_url}: {fallback_error}")
                    continue
        page = extract_page_artifact(candidate_result)
        if page.challenge_hints and proxy_retry_available_for_url(candidate_url):
            proxy_candidate_result = await retry_crawl_with_proxy(
                crawler,
                candidate_url,
                page_timeout_ms,
                errors,
                proxy_retry_log,
                reason="candidate_challenge_detected",
            )
            if proxy_candidate_result is None:
                proxy_candidate_result = retry_static_with_proxy(
                    candidate_url,
                    errors,
                    proxy_retry_log,
                    reason="candidate_challenge_detected",
                )
            if proxy_candidate_result is not None:
                page = extract_page_artifact(proxy_candidate_result)
        if page.content_hash and page.content_hash in seen_hashes:
            continue
        if not page.text:
            continue
        crawled_pages.append(page)
        seen_urls.add(page.url)
        if page.content_hash:
            seen_hashes.add(page.content_hash)
        if len(crawled_pages) < page_limit:
            discovered = choose_candidate_pages(
                best_url,
                build_homepage_links(page),
                [],
                page_limit=page_limit * 2,
                profile=profile_hint,
                stage=stage,
            )
            for discovered_url in discovered[1:]:
                if discovered_url in queued_urls or discovered_url in seen_urls:
                    continue
                if candidate_page_score(best_url, discovered_url, "", profile=profile_hint) <= 0:
                    continue
                candidates.append(discovered_url)
                queued_urls.add(discovered_url)

    extraction_started = time.perf_counter()
    all_text = "\n\n".join(page.text for page in crawled_pages if page.text)
    company_homepage_name, company_homepage_name_evidence = detect_company_homepage_name(
        crawled_pages,
        row.company_name,
    )
    organization_name = company_homepage_name
    organization_type = detect_organization_type(all_text, crawled_pages, organization_name)
    industry = detect_industry(organization_type, all_text)
    services = detect_services(crawled_pages)
    locations = detect_locations(crawled_pages)
    contact_info = detect_contact_info(crawled_pages)
    leadership_signals = detect_leadership_signals(crawled_pages)
    affiliation_signals = detect_affiliation_signals(crawled_pages)
    parent_verification = detect_parent_company(
        crawled_pages,
        company_homepage_name,
        company_name=row.company_name,
        canonical_domain=registered_domain(normalization.hostname),
        best_url=best_url,
    )
    timings["extraction_ms"] = elapsed_ms(extraction_started)
    solo_or_group = detect_solo_or_group(organization_type, locations, leadership_signals, affiliation_signals, all_text)
    size_signals = detect_size_signals(crawled_pages, locations, leadership_signals, affiliation_signals)
    social_links = dedupe_strings([link for page in crawled_pages for link in page.social_links], limit=20)
    structured_data = structured_data_summary(crawled_pages, sitemap_urls)
    fatal_errors, ignored_errors = split_crawl_errors(best_url, errors)
    page_summaries = build_page_summaries(crawled_pages)
    enrichment_depth_status, weak_enrichment_reason = classify_enrichment_depth(
        crawled_pages,
        services,
        locations,
        leadership_signals,
        organization_type,
        fatal_errors,
        stage=stage,
    )
    high_value_pages = [
        {
            "url": page.url,
            "page_type_guess": page.page_type_guess,
            "title": page.title,
        }
        for page in crawled_pages
        if page.page_type_guess
        in {"about", "services", "team", "doctor_profile", "locations", "contact", "privacy_pdpa", "security_trust", "pricing"}
    ]
    structured_data["enrichment_depth"] = {
        "stage": stage,
        "page_limit": page_limit,
        "per_row_page_concurrency": per_row_page_concurrency,
        "pages_crawled_count": len(crawled_pages),
        "pages_crawled_urls": [page.url for page in crawled_pages],
        "high_value_pages_found": high_value_pages,
        "homepage_content_quality": homepage_content_quality(crawled_pages[0] if crawled_pages else None),
        "enrichment_depth_status": enrichment_depth_status,
        "weak_enrichment_reason": weak_enrichment_reason,
        "derived_evidence": size_signals,
        "page_summaries": page_summaries[:16],
    }
    notes = (
        f"Crawled {len(crawled_pages)} public pages from {registered_domain(normalization.hostname)}; "
        f"found {len(locations)} location signals, {len(services)} service signals, and {len(leadership_signals)} team signals."
    )
    proxy_note = proxy_usage_note(proxy_retry_log)
    if proxy_note:
        notes += f" {proxy_note}"
    if ignored_errors:
        notes += f" Ignored {len(ignored_errors)} same-domain subpage 404 warnings."
    crawl_status = "crawled" if crawled_pages else ("partial" if fatal_errors else "crawled")
    record = EnrichmentRecord(
        row_id=row.row_id,
        company_name=row.company_name,
        url_picked=row.url_picked,
        best_url=best_url,
        crawl_status=crawl_status,
        pages_crawled_count=len(crawled_pages),
        pages_crawled_urls=[page.url for page in crawled_pages],
        title=homepage_page.title,
        meta_description=homepage_page.meta_description,
        organization_name_detected=organization_name,
        organization_type_guess=organization_type,
        solo_or_group_guess=solo_or_group,
        parent_or_affiliation_signals=affiliation_signals,
        size_signals=size_signals,
        industry_guess=industry,
        services_detected=services,
        locations_detected=locations,
        contact_info_detected=contact_info,
        leadership_or_team_signals=leadership_signals,
        social_links=social_links,
        structured_data_detected=structured_data,
        enrichment_notes=notes,
        confidence_score=0.0,
        error_notes=fatal_errors,
        best_url_candidate=validation.best_url_candidate,
        http_status=validation.http_status,
        redirect_chain=validation.redirect_chain,
        url_validation_status=validation.url_validation_status,
        company_homepage_name=company_homepage_name,
        company_homepage_name_evidence=company_homepage_name_evidence,
        parent_company=parent_verification.parent_company,
        parent_company_evidence=parent_verification.evidence,
        parent_company_confidence=parent_verification.confidence,
        parent_company_relationship=parent_verification.relationship_type,
        affiliations_detected=parent_verification.affiliations,
        rejected_parent_candidates=parent_verification.rejected_candidates,
        parent_company_candidates_json=[asdict(candidate) for candidate in parent_verification.candidates],
        website_scrape=build_website_scrape(crawled_pages, max_chars=scrape_char_limit),
        raw_pages=[make_raw_page(page) for page in crawled_pages],
        crawl_context={
            "enrichment_depth": structured_data["enrichment_depth"],
            "url_validation": {
                "best_url_candidate": validation.best_url_candidate,
                "best_url": validation.best_url,
                "http_status": validation.http_status,
                "redirect_chain": validation.redirect_chain,
                "url_validation_status": validation.url_validation_status,
                "error": validation.error,
            },
            "robots": {
                "url": robots_policy.robots_url,
                "fetched": robots_policy.fetched,
                "allowed_homepage": robots_policy.allowed_homepage,
                "crawl_delay_seconds": robots_policy.crawl_delay_seconds,
                "sitemaps": robots_policy.sitemaps,
                "note": robots_policy.note,
            },
            "parent_company_verification": {
                "verifier": parent_verification.verifier,
                "verifier_error": parent_verification.verifier_error,
                "parent_company": parent_verification.parent_company,
                "relationship_type": parent_verification.relationship_type,
                "confidence": parent_verification.confidence,
                "evidence": parent_verification.evidence,
                "affiliations_detected": parent_verification.affiliations,
                "rejected_parent_candidates": parent_verification.rejected_candidates,
                "parent_company_candidates": [asdict(candidate) for candidate in parent_verification.candidates],
            },
            "proxy": proxy_context(proxy_retry_log, bool(crawl_proxy_config)),
        },
        enrichment_depth_status=enrichment_depth_status,
        weak_enrichment_reason=weak_enrichment_reason,
        high_value_pages_found_json=high_value_pages,
        page_summaries_json=page_summaries[:16],
        homepage_content_quality=structured_data["enrichment_depth"]["homepage_content_quality"],
        about_page_summary=first_summary_for_type(page_summaries, ("about",)),
        services_page_summary=first_summary_for_type(page_summaries, ("services",)),
        team_page_summary=first_summary_for_type(page_summaries, ("team", "doctor_profile")),
        locations_page_summary=first_summary_for_type(page_summaries, ("locations", "contact")),
        privacy_page_summary=first_summary_for_type(page_summaries, ("privacy_pdpa",)),
        pricing_page_summary=first_summary_for_type(page_summaries, ("pricing",)),
        derived_evidence=size_signals,
    )
    record.confidence_score = confidence_score_for_record(record)
    return stamp(record)


def output_directory(base_dir: str) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(base_dir).expanduser() / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_to_json(record: EnrichmentRecord) -> dict[str, Any]:
    return asdict(record)


def record_to_csv_row(record: EnrichmentRecord) -> dict[str, str]:
    return {
        "row_id": str(record.row_id),
        "company_name": record.company_name,
        "url_picked": record.url_picked,
        "best_url_candidate": record.best_url_candidate,
        "best_url": record.best_url,
        "http_status": str(record.http_status),
        "redirect_chain": json.dumps(record.redirect_chain, ensure_ascii=True),
        "url_validation_status": record.url_validation_status,
        "company_homepage_name": record.company_homepage_name,
        "company_homepage_name_evidence": json.dumps(record.company_homepage_name_evidence, ensure_ascii=True),
        "parent_company": record.parent_company,
        "parent_company_relationship": record.parent_company_relationship,
        "parent_company_evidence": json.dumps(record.parent_company_evidence, ensure_ascii=True),
        "parent_company_confidence": record.parent_company_confidence,
        "affiliations_detected": json.dumps(record.affiliations_detected, ensure_ascii=True),
        "rejected_parent_candidates": json.dumps(record.rejected_parent_candidates, ensure_ascii=True),
        "parent_company_candidates_json": json.dumps(record.parent_company_candidates_json, ensure_ascii=True),
        "crawl_status": record.crawl_status,
        "pages_crawled_count": str(record.pages_crawled_count),
        "pages_crawled_urls": json.dumps(record.pages_crawled_urls, ensure_ascii=True),
        "enrichment_depth_status": record.enrichment_depth_status,
        "weak_enrichment_reason": record.weak_enrichment_reason,
        "homepage_content_quality": record.homepage_content_quality,
        "high_value_pages_found_json": json.dumps(record.high_value_pages_found_json, ensure_ascii=True),
        "page_summaries_json": json.dumps(record.page_summaries_json, ensure_ascii=True),
        "derived_evidence": json.dumps(record.derived_evidence, ensure_ascii=True),
        "title": record.title,
        "meta_description": record.meta_description,
        "organization_name_detected": record.organization_name_detected,
        "organization_type_guess": record.organization_type_guess,
        "solo_or_group_guess": record.solo_or_group_guess,
        "parent_or_affiliation_signals": json.dumps(record.parent_or_affiliation_signals, ensure_ascii=True),
        "size_signals": json.dumps(record.size_signals, ensure_ascii=True),
        "industry_guess": record.industry_guess,
        "services_detected": json.dumps(record.services_detected, ensure_ascii=True),
        "locations_detected": json.dumps(record.locations_detected, ensure_ascii=True),
        "contact_info_detected": json.dumps(record.contact_info_detected, ensure_ascii=True),
        "leadership_or_team_signals": json.dumps(record.leadership_or_team_signals, ensure_ascii=True),
        "social_links": json.dumps(record.social_links, ensure_ascii=True),
        "structured_data_detected": json.dumps(record.structured_data_detected, ensure_ascii=True),
        "crawl_context": json.dumps(record.crawl_context, ensure_ascii=True),
        "enrichment_notes": record.enrichment_notes,
        "confidence_score": str(record.confidence_score),
        "error_notes": json.dumps(record.error_notes, ensure_ascii=True),
        "timing_ms": json.dumps(record.timing_ms, ensure_ascii=True),
    }


def save_outputs(records: list[EnrichmentRecord], base_dir: str) -> Path:
    run_dir = output_directory(base_dir)
    jsonl_path = run_dir / "enrichment.jsonl"
    csv_path = run_dir / "enrichment.csv"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record_to_json(record), ensure_ascii=True) + "\n")

    fieldnames = list(record_to_csv_row(records[0]).keys()) if records else []
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record_to_csv_row(record))

    return run_dir


def terminal_status(record: EnrichmentRecord) -> str:
    if record.crawl_status == "crawled":
        return "completed"
    if record.crawl_status == "partial":
        return "completed" if record.best_url else "needs_review"
    if record.crawl_status in {"crawl_failed", "enrichment_error"}:
        return "failed"
    if record.crawl_status == "blocked_by_robots" or record.crawl_status.startswith("skipped_"):
        return "skipped"
    if not record.best_url:
        return "needs_review"
    return "completed"


def build_noco_patch(record: EnrichmentRecord) -> dict[str, Any]:
    notes_parts = [record.enrichment_notes]
    if record.url_validation_status:
        notes_parts.append(f"URL validation: {record.url_validation_status} HTTP {record.http_status or 'n/a'}")
    if record.company_homepage_name_evidence:
        notes_parts.append("Homepage name evidence: " + " | ".join(record.company_homepage_name_evidence[:3]))
    if record.parent_company_evidence:
        notes_parts.append("Parent evidence: " + " | ".join(record.parent_company_evidence[:3]))
    if record.affiliations_detected:
        notes_parts.append(
            "Affiliations detected: "
            + " | ".join(
                compact_whitespace(item.get("name", ""))
                for item in record.affiliations_detected[:3]
                if isinstance(item, dict) and compact_whitespace(item.get("name", ""))
            )
        )
    if record.error_notes:
        notes_parts.append("Errors: " + " | ".join(record.error_notes[:5]))
    if record.enrichment_depth_status:
        notes_parts.append(
            "Enrichment depth: "
            + record.enrichment_depth_status
            + (f" ({record.weak_enrichment_reason})" if record.weak_enrichment_reason else "")
        )
    return {
        "Id": record.row_id,
        "status": terminal_status(record),
        "best_url": record.best_url,
        "homepage_root_url": record.best_url,
        "company_homepage_name": record.company_homepage_name,
        "operating_company_root_name": record.company_homepage_name,
        "parent_company": record.parent_company,
        "website_content": record.website_scrape,
        "website_scrape": record.website_scrape,
        "source_urls": " | ".join(record.pages_crawled_urls),
        "industry_guess": record.industry_guess,
        "services_detected": json.dumps(record.services_detected, ensure_ascii=True),
        "locations_detected": json.dumps(record.locations_detected, ensure_ascii=True),
        "contact_info_detected": json.dumps(record.contact_info_detected, ensure_ascii=True),
        "leadership_or_team_signals": json.dumps(record.leadership_or_team_signals, ensure_ascii=True),
        "structured_data_detected": json.dumps(record.structured_data_detected, ensure_ascii=True),
        "notes": limit_text(" ".join(part for part in notes_parts if part), 4000),
        "confidence": confidence_label(record.confidence_score),
        "last_stage": record.crawl_status,
        "last_error": " | ".join(record.error_notes[:8]),
    }


async def run_enrichment(args: argparse.Namespace) -> tuple[list[EnrichmentRecord], Path]:
    rows = fetch_input_rows(args)
    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=not args.show_browser,
        viewport_width=1280,
        viewport_height=1800,
        ignore_https_errors=True,
        verbose=False,
    )

    records: list[EnrichmentRecord] = []
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for row in rows:
            record = await enrich_row(
                row=row,
                crawler=crawler,
                page_limit=args.page_limit,
                page_timeout_ms=args.page_timeout_ms,
                request_delay_seconds=args.request_delay_seconds,
                scrape_char_limit=args.scrape_char_limit,
                enrichment_stage=args.enrichment_stage,
                per_row_page_concurrency=args.per_row_page_concurrency,
            )
            records.append(record)

    run_dir = save_outputs(records, args.output_dir)
    if args.write_noco and records:
        patches = [build_noco_patch(record) for record in records]
        for batch in chunked(patches, 25):
            patch_rows(batch)
    return records, run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize best_url and crawl public pages for enrichment.")
    parser.add_argument("--ids", help="Comma-separated row IDs")
    parser.add_argument("--where", help="Raw NocoDB where clause")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--page-limit", type=int, default=12)
    parser.add_argument("--page-timeout-ms", type=int, default=30000)
    parser.add_argument("--request-delay-seconds", type=float, default=1.0)
    parser.add_argument("--scrape-char-limit", type=int, default=60000)
    parser.add_argument("--enrichment-stage", choices=("fast", "deep_retry"), default="fast")
    parser.add_argument("--per-row-page-concurrency", type=int, default=2)
    parser.add_argument("--output-dir", default=".tmp/public-web-enrichment")
    parser.add_argument("--input-json", help="Read rows from JSON file, or `-` for stdin")
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--write-noco", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def print_summary(records: list[EnrichmentRecord], run_dir: Path) -> None:
    timing_totals: Counter[str] = Counter()
    slowest_rows = sorted(
        (
            {
                "row_id": record.row_id,
                "company_name": record.company_name,
                "crawl_status": record.crawl_status,
                "total_ms": record.timing_ms.get("total_ms", 0.0),
                "pages_crawled_count": record.pages_crawled_count,
                "errors": len(record.error_notes),
            }
            for record in records
        ),
        key=lambda item: item["total_ms"],
        reverse=True,
    )[:5]
    for record in records:
        for key, value in record.timing_ms.items():
            timing_totals[key] += float(value)
    summary = {
        "rows": len(records),
        "crawled": sum(1 for record in records if record.crawl_status == "crawled"),
        "partial": sum(1 for record in records if record.crawl_status == "partial"),
        "blocked_by_robots": sum(1 for record in records if record.crawl_status == "blocked_by_robots"),
        "crawl_failed": sum(1 for record in records if record.crawl_status == "crawl_failed"),
        "skipped": sum(1 for record in records if record.crawl_status.startswith("skipped_")),
        "output_dir": str(run_dir),
        "avg_timing_ms": {
            key: round(value / len(records), 1) for key, value in sorted(timing_totals.items()) if records
        },
        "slowest_rows": slowest_rows,
    }
    print(json.dumps(summary, ensure_ascii=True))


def main() -> None:
    require_python_311()
    parser = build_parser()
    args = parser.parse_args()
    if args.dry_run:
        args.write_noco = False
    records, run_dir = asyncio.run(run_enrichment(args))
    print_summary(records, run_dir)


if __name__ == "__main__":
    main()
