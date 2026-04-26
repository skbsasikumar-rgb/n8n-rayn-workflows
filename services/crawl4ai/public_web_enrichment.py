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
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
except ImportError as exc:  # pragma: no cover - surfaced as runtime guidance
    raise SystemExit(
        "Missing crawl4ai. Install with "
        "`python3.11 -m pip install -r services/crawl4ai/requirements-public-web-enrichment.txt`."
    ) from exc


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
VALID_FINAL_STATUSES = {200, 203}
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
    "leadership",
    "doctor",
    "doctors",
    "provider",
    "providers",
    "clinic",
    "clinics",
    "service",
    "services",
    "specialty",
    "specialties",
    "treatment",
    "location",
    "locations",
    "contact",
    "faq",
    "news",
    "careers",
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
    headings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    text: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    social_links: list[str] = field(default_factory=list)
    logo_alt_texts: list[str] = field(default_factory=list)
    footer_legal_names: list[str] = field(default_factory=list)
    structured_data: list[dict[str, Any]] = field(default_factory=list)
    open_graph: dict[str, str] = field(default_factory=dict)
    status_code: int = 0
    content_hash: str = ""


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
    website_scrape: str = ""
    raw_pages: list[dict[str, Any]] = field(default_factory=list)
    crawl_context: dict[str, Any] = field(default_factory=dict)
    timing_ms: dict[str, float] = field(default_factory=dict)


def require_python_311() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("This workflow requires Python 3.11+.")


def compact_whitespace(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


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
            response = session.get(current_url, allow_redirects=False, timeout=(10, 20), stream=True)
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


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-SG,en;q=0.9",
        }
    )
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
            if any(keyword in lowered for keyword in HIGH_VALUE_KEYWORDS):
                candidate_urls.append(candidate)
            if len(candidate_urls) >= limit:
                break

    return dedupe_strings(candidate_urls, limit=limit)


def candidate_page_score(homepage_url: str, page_url: str, anchor_text: str = "") -> int:
    if not same_registered_domain(homepage_url, page_url):
        return -100
    if not is_html_like_url(page_url):
        return -100

    path = urlsplit(page_url).path.lower()
    text = f"{path} {anchor_text.lower()}"
    if any(term in text for term in ("login", "signin", "sign-in", "cart", "checkout", "wp-admin")):
        return -20

    score = 0
    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword in text:
            score += 4
    if "/about" in path:
        score += 3
    if any(term in text for term in ("doctor", "team", "leadership", "provider")):
        score += 2
    score -= max(path.count("/") - 2, 0)
    return score


def choose_candidate_pages(
    homepage_url: str,
    homepage_links: list[dict[str, str]],
    sitemap_urls: list[str],
    page_limit: int,
) -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen_urls: set[str] = {homepage_url}

    for link in homepage_links:
        href = compact_whitespace(link.get("href", ""))
        text = compact_whitespace(link.get("text", ""))
        if not href or href in seen_urls:
            continue
        score = candidate_page_score(homepage_url, href, text)
        if score <= 0:
            continue
        ranked.append((score, href))
        seen_urls.add(href)

    for sitemap_url in sitemap_urls:
        if sitemap_url in seen_urls:
            continue
        score = candidate_page_score(homepage_url, sitemap_url, "")
        if score <= 0:
            continue
        ranked.append((score, sitemap_url))
        seen_urls.add(sitemap_url)

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [homepage_url]
    selected.extend(href for _, href in ranked[: max(page_limit - 1, 0)])
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
    title = compact_whitespace(
        result_data.get("metadata", {}).get("title")
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
    )[:300]
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    return PageArtifact(
        url=final_url,
        title=title,
        meta_description=meta_description,
        headings=headings,
        blocks=blocks,
        text=text,
        emails=emails,
        phones=phones,
        addresses=addresses,
        internal_links=dedupe_strings(internal_links, limit=60),
        social_links=social_links,
        logo_alt_texts=logo_alt_texts,
        footer_legal_names=footer_legal_names,
        structured_data=structured_data,
        open_graph=open_graph,
        status_code=int(result_data.get("status_code") or 0),
        content_hash=content_hash,
    )


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


def clean_parent_candidate(value: str, company_homepage_name: str) -> str:
    candidate = clean_name_candidate(value)
    if not candidate or is_generic_name_candidate(candidate):
        return ""
    lowered = candidate.lower()
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


def detect_parent_company(
    pages: list[PageArtifact],
    company_homepage_name: str,
) -> tuple[str, list[str], str]:
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}

    for page in pages:
        for item in page.structured_data:
            for key in ("parentOrganization", "branchOf"):
                value = item.get(key)
                raw_name = ""
                if isinstance(value, dict):
                    raw_name = compact_whitespace(value.get("name", ""))
                elif isinstance(value, str):
                    raw_name = value
                candidate = clean_parent_candidate(raw_name, company_homepage_name)
                if candidate:
                    scores[candidate] += 10
                    evidence.setdefault(candidate, []).append(f"schema.org {key}: {candidate}")

        for line in [*page.headings, *page.blocks]:
            candidate, evidence_line = extract_parent_from_line(line, company_homepage_name)
            if candidate:
                scores[candidate] += 8
                evidence.setdefault(candidate, []).append(evidence_line)

    if not scores:
        return "", [], ""

    parent_company = scores.most_common(1)[0][0]
    parent_evidence = dedupe_strings(evidence.get(parent_company, []), limit=8)
    confidence = "High" if scores[parent_company] >= 10 else "Medium"
    return parent_company, parent_evidence, confidence


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
    return {
        "pages_crawled": len(pages),
        "locations_detected_count": len(locations),
        "leadership_signal_count": len(leadership_signals),
        "affiliation_signal_count": len(affiliation_signals),
        "doctor_mentions": len(re.findall(r"\bdr\.?\b|\bdoctor\b", combined_text)),
        "clinic_mentions": len(re.findall(r"\bclinic\b|\bclinics\b", combined_text)),
        "branch_mentions": len(re.findall(r"\bbranch\b|\bbranches\b|\blocation\b|\blocations\b", combined_text)),
    }


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


async def crawl_url(crawler: AsyncWebCrawler, url: str, page_timeout_ms: int) -> dict[str, Any]:
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
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
        verbose=False,
    )
    result = await crawler.arun(url=url, config=run_config)
    data = result.model_dump()
    if not data.get("success"):
        raise RuntimeError(compact_whitespace(data.get("error_message", "")) or "crawl4ai crawl failed")
    if int(data.get("status_code") or 0) >= 400:
        raise RuntimeError(f"HTTP {data.get('status_code')}")
    return data


def build_homepage_links(page: PageArtifact) -> list[dict[str, str]]:
    return [{"href": href, "text": ""} for href in page.internal_links]


async def enrich_row(
    row: InputRow,
    crawler: AsyncWebCrawler,
    session: requests.Session,
    page_limit: int,
    page_timeout_ms: int,
    request_delay_seconds: float,
    scrape_char_limit: int,
) -> EnrichmentRecord:
    total_started = time.perf_counter()
    timings: dict[str, float] = {}

    def stamp(record: EnrichmentRecord) -> EnrichmentRecord:
        record.timing_ms = {**timings, "total_ms": elapsed_ms(total_started)}
        return record

    errors: list[str] = []
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

    try:
        homepage_started = time.perf_counter()
        homepage_result = await crawl_url(crawler, best_url, page_timeout_ms)
        timings["homepage_crawl_ms"] = elapsed_ms(homepage_started)
    except Exception as exc:
        error_text = compact_whitespace(exc)
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
            enrichment_notes=f"Homepage crawl failed: {error_text}",
            confidence_score=0.05,
            error_notes=[error_text],
            best_url_candidate=validation.best_url_candidate,
            http_status=validation.http_status,
            redirect_chain=validation.redirect_chain,
            url_validation_status=validation.url_validation_status,
            crawl_context={"robots": {"url": robots_policy.robots_url, "note": robots_policy.note}},
        ))

    homepage_page = extract_page_artifact(homepage_result)
    resolved_homepage = canonical_root_url(homepage_page.url or best_url)
    if resolved_homepage.best_url:
        best_url = resolved_homepage.best_url
        if not same_host(normalization.best_url, best_url):
            robots_started = time.perf_counter()
            robots_policy = fetch_robots_policy(session, best_url)
            timings["robots_ms"] = timings.get("robots_ms", 0.0) + elapsed_ms(robots_started)

    crawled_pages.append(homepage_page)
    seen_urls.add(homepage_page.url)
    if homepage_page.content_hash:
        seen_hashes.add(homepage_page.content_hash)

    sitemap_urls = fetch_sitemap_candidates(session, best_url, robots_policy, limit=max(page_limit * 6, 20))
    homepage_links = build_homepage_links(homepage_page)
    candidates = choose_candidate_pages(best_url, homepage_links, sitemap_urls, page_limit=page_limit)
    delay_seconds = max(request_delay_seconds, robots_policy.crawl_delay_seconds)

    for candidate_url in candidates[1:]:
        if candidate_url in seen_urls:
            continue
        if not robots_policy.allows(candidate_url):
            errors.append(f"robots.txt disallows {candidate_url}")
            continue
        await asyncio.sleep(delay_seconds)
        try:
            candidate_started = time.perf_counter()
            candidate_result = await crawl_url(crawler, candidate_url, page_timeout_ms)
            timings["candidate_crawls_ms"] = timings.get("candidate_crawls_ms", 0.0) + elapsed_ms(candidate_started)
        except Exception as exc:
            errors.append(f"{candidate_url}: {compact_whitespace(exc)}")
            continue
        page = extract_page_artifact(candidate_result)
        if page.content_hash and page.content_hash in seen_hashes:
            continue
        if not page.text:
            continue
        crawled_pages.append(page)
        seen_urls.add(page.url)
        if page.content_hash:
            seen_hashes.add(page.content_hash)

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
    parent_company, parent_company_evidence, parent_company_confidence = detect_parent_company(
        crawled_pages,
        company_homepage_name,
    )
    timings["extraction_ms"] = elapsed_ms(extraction_started)
    solo_or_group = detect_solo_or_group(organization_type, locations, leadership_signals, affiliation_signals, all_text)
    size_signals = detect_size_signals(crawled_pages, locations, leadership_signals, affiliation_signals)
    social_links = dedupe_strings([link for page in crawled_pages for link in page.social_links], limit=20)
    structured_data = structured_data_summary(crawled_pages, sitemap_urls)
    notes = (
        f"Crawled {len(crawled_pages)} public pages from {registered_domain(normalization.hostname)}; "
        f"found {len(locations)} location signals, {len(services)} service signals, and {len(leadership_signals)} team signals."
    )
    crawl_status = "partial" if errors else "crawled"
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
        error_notes=errors,
        best_url_candidate=validation.best_url_candidate,
        http_status=validation.http_status,
        redirect_chain=validation.redirect_chain,
        url_validation_status=validation.url_validation_status,
        company_homepage_name=company_homepage_name,
        company_homepage_name_evidence=company_homepage_name_evidence,
        parent_company=parent_company,
        parent_company_evidence=parent_company_evidence,
        parent_company_confidence=parent_company_confidence,
        website_scrape=build_website_scrape(crawled_pages, max_chars=scrape_char_limit),
        raw_pages=[make_raw_page(page) for page in crawled_pages],
        crawl_context={
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
            }
        },
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
        "parent_company_evidence": json.dumps(record.parent_company_evidence, ensure_ascii=True),
        "parent_company_confidence": record.parent_company_confidence,
        "crawl_status": record.crawl_status,
        "pages_crawled_count": str(record.pages_crawled_count),
        "pages_crawled_urls": json.dumps(record.pages_crawled_urls, ensure_ascii=True),
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
        return "needs_review"
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
    if record.error_notes:
        notes_parts.append("Errors: " + " | ".join(record.error_notes[:5]))
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
        "notes": limit_text(" ".join(part for part in notes_parts if part), 4000),
        "confidence": confidence_label(record.confidence_score),
        "last_stage": record.crawl_status,
        "last_error": " | ".join(record.error_notes[:8]),
    }


async def run_enrichment(args: argparse.Namespace) -> tuple[list[EnrichmentRecord], Path]:
    rows = fetch_input_rows(args)
    session = build_requests_session()
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
                session=session,
                page_limit=args.page_limit,
                page_timeout_ms=args.page_timeout_ms,
                request_delay_seconds=args.request_delay_seconds,
                scrape_char_limit=args.scrape_char_limit,
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
