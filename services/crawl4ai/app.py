import asyncio
import importlib.util
import json
import multiprocessing as mp
import os
import queue
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel, Field, HttpUrl
from playwright.async_api import Browser, Page, Playwright, async_playwright
import requests
import captcha_solver
import contact_enrichment
import outreach_planner
import public_web_enrichment as public_enrichment


SERVICE_DIR = Path(__file__).resolve().parent
ORIGINAL_HOME = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
DEFAULT_RUNTIME_HOME = SERVICE_DIR / "runtime-home"
if os.name == "posix" and "darwin" in os.sys.platform:
    DEFAULT_PLAYWRIGHT_BROWSERS = ORIGINAL_HOME / "Library" / "Caches" / "ms-playwright"
else:
    DEFAULT_PLAYWRIGHT_BROWSERS = ORIGINAL_HOME / ".cache" / "ms-playwright"

runtime_home = Path(os.environ.get("CRAWL4AI_RUNTIME_HOME", str(DEFAULT_RUNTIME_HOME))).expanduser()
runtime_home.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(runtime_home)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(DEFAULT_PLAYWRIGHT_BROWSERS))

SG_HINTS = (
    "singapore",
    "sg",
    "healthhub",
    "moh",
    "aic",
    "jurong",
    "bishan",
    "toa payoh",
    "bedok",
    "woodlands",
    "ang mo kio",
    "punggol",
    "serangoon",
    "tampines",
    "yishun",
    "novena",
)

OVERSEAS_HINTS = (
    "australia",
    "sydney",
    "melbourne",
    "brisbane",
    "perth",
    "new zealand",
    "nz",
    "malaysia",
    "kuala lumpur",
    "johor",
    "india",
    "dubai",
    "united states",
    "usa",
    "united kingdom",
    "uk",
)

ERROR_HINTS = (
    "access denied",
    "captcha",
    "cf-challenge",
    "cloudflare",
    "complete the security check",
    "robot challenge",
    "unusual traffic",
    "verify you are human",
    "checking the site connection",
    "please make sure you are authorized",
    "forbidden",
    "enable javascript",
    "service unavailable",
    "temporarily unavailable",
    "page not found",
    "error 404",
    "error 403",
    "error 500",
)

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
PUBLIC_ENRICH_FORCE_BROWSER_KEY = "_force_browser_primary"
PUBLIC_ENRICH_BROWSER_RETRY_STATUSES = {"failed_http_status", "failed_redirect_loop"}

ICP_HINTS = (
    "clinic",
    "medical",
    "healthcare",
    "hospital",
    "dental",
    "dentist",
    "pharmacy",
    "laboratory",
    "diagnostic",
    "radiology",
    "dialysis",
    "nursing",
    "eldercare",
    "community care",
    "rehab",
    "tcm",
    "chinese medicine",
    "telehealth",
    "cybersecurity",
    "saas",
    "software",
    "platform",
)

CONTACT_KEYWORDS = (
    "contact",
    "about",
    "people",
    "our people",
    "staff",
    "team",
    "our team",
    "leadership",
    "leaders",
    "management",
    "board",
    "directors",
    "trustees",
    "committee",
    "council",
    "governance",
    "organisation",
    "organization",
    "executive",
    "senior management",
    "profile",
    "profiles",
    "practitioner",
    "practitioners",
    "provider",
    "providers",
    "consultant",
    "consultants",
    "doctor",
    "doctors",
    "specialist",
    "specialists",
    "dermatologist",
    "dermatologists",
    "cardiologist",
    "cardiologists",
    "clinic",
    "clinics",
    "location",
    "locations",
    "find-us",
    "find us",
    "privacy",
    "pdpa",
    "data protection",
    "dpo",
    "compliance",
    "corporate",
    "services",
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

COMMON_FOLLOW_PATHS = (
    "/about",
    "/about-us",
    "/who-we-are",
    "/our-story",
    "/contact",
    "/contact-us",
    "/people",
    "/our-people",
    "/staff",
    "/team",
    "/our-team",
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
    "/doctor",
    "/our-doctors",
    "/our-doctor",
    "/specialists",
    "/consultants",
    "/profiles",
    "/our-dermatologist",
    "/dermatologist",
    "/our-cardiologist",
    "/cardiologist",
)

SKIP_LINK_PREFIXES = ("mailto:", "tel:", "javascript:", "#")


class ScrapeRequest(BaseModel):
    url: HttpUrl
    company_name: str = Field(min_length=1, max_length=300)
    market: str = Field(default="Singapore", max_length=100)


class MetadataPayload(BaseModel):
    description: str = ""
    lang: str = ""


class SignalPayload(BaseModel):
    is_singapore_relevant: bool | None = None
    country_hint: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    company_name_seen: bool = False


class QualityPayload(BaseModel):
    content_chars: int = 0
    word_count: int = 0
    has_icp_terms: bool = False
    looks_like_error_page: bool = False
    looks_like_challenge_page: bool = False
    challenge_hints: list[str] = Field(default_factory=list)


class ScrapeResponse(BaseModel):
    ok: bool
    url: str
    final_url: str = ""
    title: str = ""
    markdown: str = ""
    main_text: str = ""
    website_content: str = ""
    evidence_bundle: dict[str, Any] = Field(default_factory=dict)
    metadata: MetadataPayload = Field(default_factory=MetadataPayload)
    signals: SignalPayload = Field(default_factory=SignalPayload)
    quality: QualityPayload = Field(default_factory=QualityPayload)
    error: str = ""


class PublicEnrichmentRequest(BaseModel):
    Id: int | str
    company_name: str = Field(min_length=1, max_length=300)
    url_picked: str = Field(default="", max_length=2000)
    enrichment_stage: str = Field(default="fast", max_length=40)
    page_limit: int = Field(default=6, ge=1, le=24)
    page_timeout_ms: int = Field(default=20000, ge=5000, le=60000)
    request_delay_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    scrape_char_limit: int = Field(default=120000, ge=2000, le=180000)
    per_row_page_concurrency: int = Field(default=2, ge=1, le=4)
    row_timeout_seconds: int = Field(default=0, ge=0, le=600)
    allow_low_limits: bool = False
    allow_cross_domain_redirect: bool = False


class ContactSearchRequest(BaseModel):
    Id: int | str
    company_name: str = Field(min_length=1, max_length=300)
    company_homepage_name: str = Field(default="", max_length=300)
    canonical_domain: str = Field(default="", max_length=300)
    best_url: str = Field(default="", max_length=2000)
    website_content: str = Field(default="", max_length=120000)
    contact_search_run_id: str = Field(default="", max_length=120)
    search_queries: list[dict[str, Any]] = Field(default_factory=list)
    search_attempts: list[dict[str, Any]] = Field(default_factory=list)
    excluded_candidate_names: list[str] = Field(default_factory=list)
    excluded_email_candidates: list[str] = Field(default_factory=list)
    fallback_reason: str = Field(default="", max_length=160)
    validate_email: bool = True
    site_fast_path_only: bool = False


class ContactBatchRunRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=10)
    ids: list[int | str] = Field(default_factory=list)
    concurrency: int = Field(default=0, ge=0, le=10)
    reset_provider_health: bool = False
    validate_email: bool = True
    dry_run: bool = False


class ContactRowRunRequest(BaseModel):
    id: int | str | None = None
    row_id: int | str | None = None
    reset_provider_health: bool = False
    validate_email: bool = True


class OutreachPlanRequest(BaseModel):
    Id: int | str
    company_name: str = Field(min_length=1, max_length=300)
    company_homepage_name: Any = ""
    parent_company: Any = ""
    best_url: Any = ""
    canonical_domain: Any = ""
    website_content: Any = ""
    source_urls: Any = ""
    pressure_type: Any = ""
    manual_pressure_type: Any = ""
    classification_review_status: Any = ""
    classification_review_reason: Any = ""
    classification_review_notes: Any = ""
    classification_reviewed_at: Any = ""
    status_reason: Any = ""
    last_stage: Any = ""
    services_detected: Any = Field(default_factory=list)
    locations_detected: Any = Field(default_factory=list)
    leadership_or_team_signals: Any = Field(default_factory=list)
    contact_info_detected: Any = Field(default_factory=dict)
    structured_data_detected: Any = Field(default_factory=dict)
    industry_guess: Any = ""
    selected_contact_name: Any = ""
    selected_contact_title: Any = ""
    selected_contact_role: Any = ""
    selected_contact_email: Any = ""
    selected_contact_linkedin_url: Any = ""
    validated_email: Any = ""
    attempt_count: Any = ""
    enrichment_attempt_count: Any = ""
    public_enrichment_attempt_count: Any = ""
    do_not_contact: Any = False
    unsubscribe_status: Any = "active"
    draft_only: bool = False
    copy_qa_mode: bool = False
    use_llm_humaniser: bool = False
    use_llm_humanizer: bool = False
    use_llm_email_1: bool = False
    openrouter_allowed: bool = False
    skip_openrouter: bool = False
    hia_llm_review: Any = Field(default_factory=dict)


class OutreachPlanBatchRequest(BaseModel):
    rows: list[OutreachPlanRequest] = Field(default_factory=list, max_length=100)
    concurrency: int = Field(default=0, ge=0, le=10)
    copy_qa_mode: bool = False


def compact_whitespace(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_dedupe_key(value: str) -> str:
    text = compact_whitespace(value).lower()
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def is_noise_line(value: str) -> bool:
    text = compact_whitespace(value)
    lowered = text.lower()
    if not text:
        return True
    if len(text) < 3:
        return True
    if any(hint in lowered for hint in NOISE_HINTS):
        return True
    if re.fullmatch(r"(?:home|about|contact|services|blog|careers|news|terms|privacy|cookies?)", lowered):
        return True
    if re.fullmatch(r"[a-z0-9/&|,.\- ]{1,22}", lowered):
        # Very short generic nav-like fragments.
        words = lowered.split()
        if len(words) <= 3:
            return True
    return False


def prune_noise_nodes(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "template"]):
        tag.decompose()

    for tag_name in ("header", "nav", "footer", "aside", "form", "button", "input", "select", "textarea"):
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
            compact_whitespace(v)
            for v in (
                attrs_map.get("id", ""),
                class_value,
                attrs_map.get("aria-label", ""),
            )
        ).lower()
        if attrs and any(hint in attrs for hint in NOISE_CLASS_HINTS):
            node.decompose()


def limit_text(value: str, max_chars: int = 15000) -> str:
    return compact_whitespace(value)[:max_chars]


def normalize_domain(url: str) -> str:
    value = re.sub(r"^https?://", "", url, flags=re.I)
    value = value.split("/")[0].lower()
    return value.removeprefix("www.")


def build_signals(url: str, title: str, website_content: str, company_name: str) -> SignalPayload:
    haystack = " ".join([url, title, website_content]).lower()
    matched_terms = sorted({hint for hint in SG_HINTS if hint in haystack})
    domain = normalize_domain(url)

    company_tokens = [
        token for token in re.split(r"[^a-z0-9]+", company_name.lower()) if len(token) >= 3
    ]
    company_name_seen = bool(company_tokens) and sum(token in haystack for token in company_tokens) >= max(
        1, min(2, len(company_tokens))
    )

    is_sg_domain = domain.endswith(".sg") or domain.endswith(".com.sg") or domain.endswith(".org.sg")
    has_sg_content = any(term in haystack for term in SG_HINTS)
    overseas_hit = next((term for term in OVERSEAS_HINTS if term in haystack), "")

    return SignalPayload(
        is_singapore_relevant=True if (is_sg_domain or has_sg_content) else None,
        country_hint="SG" if (is_sg_domain or has_sg_content) else overseas_hit.upper(),
        matched_terms=matched_terms[:20],
        company_name_seen=company_name_seen,
    )


def build_quality(title: str, website_content: str) -> QualityPayload:
    lowered = f"{title}\n{website_content}".lower()
    content_chars = len(website_content)
    word_count = len(re.findall(r"\b\w+\b", website_content))
    has_icp_terms = any(term in lowered for term in ICP_HINTS)
    looks_like_error_page = any(term in lowered for term in ERROR_HINTS)
    challenge_hints = {
        term
        for term in CHALLENGE_HINTS
        if term != "cloudflare" and term in lowered
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
        challenge_hints.add("cloudflare")
    challenge_hints = sorted(challenge_hints)
    return QualityPayload(
        content_chars=content_chars,
        word_count=word_count,
        has_icp_terms=has_icp_terms,
        looks_like_error_page=looks_like_error_page,
        looks_like_challenge_page=bool(challenge_hints),
        challenge_hints=challenge_hints,
    )


def captcha_solver_diagnostics() -> dict[str, Any]:
    diagnostics = captcha_solver.solver_diagnostics()
    diagnostics["mode"] = "active" if diagnostics.get("enabled") else "diagnostic_only"
    return diagnostics


async def solve_captcha_on_page(page: Page) -> bool:
    if not captcha_solver.is_configured():
        return False
    html = await page.content()
    if not captcha_solver._detect_captcha_type(html):
        return False
    return await captcha_solver.solve_page_captcha(page, html)


async def extract_page_with_captcha_retry(page: Page, url: str, timeout_ms: int) -> dict[str, Any]:
    result = await extract_page(page, url, timeout_ms)
    if result.get("visible_text") and not result.get("title"):
        pass
    html = await page.content()
    if captcha_solver._detect_captcha_type(html):
        solved = await solve_captcha_on_page(page)
        if solved:
            await page.wait_for_timeout(3000)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10000))
            except Exception:
                pass
            result = await extract_page(page, url, timeout_ms)
            result["captcha_solved"] = True
    return result
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        cleaned = compact_whitespace(line)
        key = normalize_dedupe_key(cleaned)
        if not cleaned or not key or is_noise_line(cleaned) or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if len(output) >= max_items:
            break
    return output


def make_absolute_url(base_url: str, href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if not href or href.startswith(SKIP_LINK_PREFIXES):
        return ""
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if not parsed.scheme.startswith("http") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") + ("/" if parsed.path in ("", "/") else "")


def same_site(url_a: str, url_b: str) -> bool:
    return normalize_domain(url_a) == normalize_domain(url_b)


def link_score(base_url: str, href: str, text: str) -> int:
    haystack = f"{href} {text}".lower()
    score = 0
    if not same_site(base_url, href):
        return -1
    for keyword in CONTACT_KEYWORDS:
        if keyword in haystack:
            score += 2
    if any(token in haystack for token in ("privacy", "pdpa", "data-protection", "data protection", "dpo")):
        score += 3
    if "/wp-" in href or "login" in haystack or "cart" in haystack:
        score -= 3
    return score


def extract_contacts(text: str) -> list[str]:
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
    phones = re.findall(r"(?:(?:\+65|65)[ -]?)?(?:\d[ -]?){8,12}", text)
    merged = [*emails, *phones]
    return dedupe_lines(merged, 20)


def extract_metadata(soup: BeautifulSoup) -> MetadataPayload:
    description = ""
    for selector, attr in (
        ({"name": "description"}, "content"),
        ({"property": "og:description"}, "content"),
    ):
        meta = soup.find("meta", attrs=selector)
        if meta and meta.get(attr):
            description = compact_whitespace(meta.get(attr))
            break

    lang = ""
    if soup.html and soup.html.get("lang"):
        lang = compact_whitespace(soup.html.get("lang"))

    return MetadataPayload(description=description[:500], lang=lang[:40])


def extract_html_sections(html: str, page_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    schema_org = extract_schema_org(soup)
    footer_text = extract_footer_text(soup)
    prune_noise_nodes(soup)

    headings = dedupe_lines(
        [node.get_text(" ", strip=True) for node in soup.select("h1, h2, h3")],
        20,
    )

    blocks: list[str] = []
    primary_selectors = (
        "main p, main li, main address, article p, article li, article address, [role='main'] p, [role='main'] li, [role='main'] address"
    )
    secondary_selectors = "section p, section li, section address, .content p, .content li, .entry-content p, .entry-content li"
    fallback_selectors = "p, address"

    for selector in (primary_selectors, secondary_selectors, fallback_selectors):
        for node in soup.select(selector):
            text = compact_whitespace(node.get_text(" ", strip=True))
            if len(text) < 25:
                continue
            if is_noise_line(text):
                continue
            blocks.append(text)
        if len(blocks) >= 30:
            break
    blocks = dedupe_lines(blocks, 60)

    links: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = make_absolute_url(page_url, anchor.get("href", ""))
        text = compact_whitespace(anchor.get_text(" ", strip=True))
        if not href:
            continue
        links.append({"href": href, "text": text})

    contacts = extract_contacts(" ".join(blocks))
    metadata = extract_metadata(soup)

    return {
        "metadata": metadata,
        "headings": headings,
        "blocks": blocks,
        "links": links,
        "contacts": contacts,
        "footer_text": footer_text,
        "schema_org": schema_org,
    }


def extract_footer_text(soup: BeautifulSoup) -> str:
    lines: list[str] = []
    for node in soup.select("footer, [role='contentinfo']"):
        text = compact_whitespace(node.get_text(" ", strip=True))
        if text:
            lines.append(text)
    return limit_text("\n".join(dedupe_lines(lines, 12)), 1200)


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
            if len(output) >= 6:
                return output
    return output


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


def simplify_schema_value(value: Any) -> Any:
    if isinstance(value, str):
        return compact_whitespace(value)[:500]
    if isinstance(value, list):
        simplified = [simplify_schema_value(item) for item in value[:8]]
        return [item for item in simplified if item not in (None, "", [], {})]
    if isinstance(value, dict):
        keys = ("@type", "name", "legalName", "url", "streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")
        output = {key: simplify_schema_value(value.get(key)) for key in keys if value.get(key) not in (None, "", [], {})}
        return output
    return value


async def auto_scroll(page: Page) -> None:
    for _ in range(4):
        await page.evaluate("window.scrollBy(0, Math.max(window.innerHeight, 800));")
        await page.wait_for_timeout(350)
    await page.evaluate("window.scrollTo(0, 0);")
    await page.wait_for_timeout(200)


async def extract_page(page: Page, url: str, timeout_ms: int) -> dict[str, Any]:
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10000))
    except Exception:
        pass

    await auto_scroll(page)
    await page.wait_for_timeout(1200)

    final_url = compact_whitespace(page.url)
    title = compact_whitespace(await page.title())[:300]

    try:
        visible_text = compact_whitespace(await page.locator("body").inner_text(timeout=3000))
    except Exception:
        visible_text = ""

    html = await page.content()
    sections = extract_html_sections(html, final_url or url)

    return {
        "url": final_url or url,
        "title": title,
        "html": html,
        "visible_text": visible_text,
        "metadata": sections["metadata"],
        "headings": sections["headings"],
        "blocks": sections["blocks"],
        "links": sections["links"],
        "contacts": sections["contacts"],
    }


def pick_follow_links(base_url: str, links: list[dict[str, str]], limit: int = 3) -> list[str]:
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    for link in links or []:
        if not isinstance(link, dict):
            continue
        href = link.get("href", "")
        text = link.get("text", "")
        if not href or href in seen:
            continue
        seen.add(href)
        score = link_score(base_url, href, text)
        if score <= 0:
            continue
        scored.append((score, href))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [href for _, href in scored[:limit]]

    if len(selected) < limit:
        for path in COMMON_FOLLOW_PATHS:
            href = make_absolute_url(base_url, path)
            if not href or href in seen or href.rstrip("/") == base_url.rstrip("/"):
                continue
            selected.append(href)
            seen.add(href)
            if len(selected) >= limit:
                break

    return selected[:limit]


def render_page_section(page_data: dict[str, Any], include_blocks: int) -> str:
    if not isinstance(page_data, dict):
        return ""
    lines: list[str] = []
    title = compact_whitespace(page_data.get("title", ""))
    url = compact_whitespace(page_data.get("url", ""))
    metadata_raw = page_data.get("metadata")
    metadata: MetadataPayload
    if isinstance(metadata_raw, MetadataPayload):
        metadata = metadata_raw
    elif isinstance(metadata_raw, dict):
        metadata = MetadataPayload(
            description=compact_whitespace(metadata_raw.get("description", ""))[:500],
            lang=compact_whitespace(metadata_raw.get("lang", ""))[:40],
        )
    else:
        metadata = MetadataPayload()
    headings = dedupe_lines(list(page_data.get("headings", [])), 10)
    contacts = dedupe_lines(list(page_data.get("contacts", [])), 10)
    blocks = dedupe_lines(list(page_data.get("blocks", [])), include_blocks)

    if title:
        lines.append(f"# {title}")
    if url:
        lines.append(url)
    if metadata.description:
        lines.append(metadata.description)
    lines.extend(headings)
    lines.extend(blocks)
    if contacts:
        lines.append("Contacts: " + "; ".join(contacts))

    return "\n".join(lines).strip()


EVIDENCE_BUCKETS: dict[str, tuple[str, ...]] = {
    "about_text": ("about", "who we are", "our story", "mission", "vision", "established", "founded"),
    "services_text": ("service", "services", "treatment", "treatments", "specialty", "specialities", "specialties", "care"),
    "locations_text": ("location", "locations", "branch", "branches", "clinic", "clinics", "address", "postal", "singapore"),
    "team_text": (
        "team",
        "people",
        "staff",
        "doctor",
        "doctors",
        "physician",
        "medical director",
        "leadership",
        "leaders",
        "management",
        "board",
        "directors",
        "trustees",
        "committee",
        "council",
        "governance",
        "executive director",
        "chief executive",
        "chairman",
        "chairperson",
        "president",
        "secretary",
        "treasurer",
        "programme manager",
        "program manager",
        "centre manager",
        "center manager",
        "social work",
        "volunteer manager",
        "fundraising",
        "corporate services",
        "human resources",
    ),
    "company_legal_text": (
        "pte ltd",
        "private limited",
        "limited",
        "ltd",
        "group",
        "holdings",
        "owned by",
        "operated by",
        "managed by",
        "member of",
        "part of",
        "brand of",
        "subsidiary",
        "parent company",
    ),
    "privacy_compliance_text": ("privacy", "pdpa", "personal data", "data protection", "dpo", "security", "compliance"),
}


def build_evidence_bundle(primary: dict[str, Any], extra_pages: list[dict[str, Any]]) -> dict[str, Any]:
    pages = [primary] + [item for item in extra_pages if isinstance(item, dict)]
    bundle: dict[str, Any] = {
        "page_sources": [],
        "about_text": "",
        "services_text": "",
        "locations_text": "",
        "team_text": "",
        "company_legal_text": "",
        "contact_text": "",
        "privacy_compliance_text": "",
        "footer_text": "",
        "schema_org": [],
    }
    bucket_lines: dict[str, list[str]] = {key: [] for key in EVIDENCE_BUCKETS}
    footer_lines: list[str] = []
    contact_lines: list[str] = []
    schema_items: list[dict[str, Any]] = []

    for page_data in pages:
        url = compact_whitespace(page_data.get("url", ""))
        title = compact_whitespace(page_data.get("title", ""))
        if url or title:
            bundle["page_sources"].append({"url": url, "title": title})

        metadata_raw = page_data.get("metadata")
        metadata_description = ""
        if isinstance(metadata_raw, MetadataPayload):
            metadata_description = metadata_raw.description
        elif isinstance(metadata_raw, dict):
            metadata_description = compact_whitespace(metadata_raw.get("description", ""))

        page_context = " ".join(
            [
                url,
                title,
                metadata_description,
                " ".join(str(item) for item in page_data.get("headings", [])),
            ]
        ).lower()
        evidence_lines = [metadata_description, *page_data.get("headings", []), *page_data.get("blocks", [])]

        for line in evidence_lines:
            cleaned = compact_whitespace(line)
            if not cleaned or is_noise_line(cleaned):
                continue
            lowered = f"{page_context} {cleaned.lower()}"
            for bucket, keywords in EVIDENCE_BUCKETS.items():
                if any(keyword in lowered for keyword in keywords):
                    bucket_lines[bucket].append(cleaned)

        footer = compact_whitespace(page_data.get("footer_text", ""))
        if footer:
            footer_lines.append(footer)

        contacts = page_data.get("contacts", [])
        if isinstance(contacts, list):
            contact_lines.extend(str(item) for item in contacts)

        page_schema = page_data.get("schema_org", [])
        if isinstance(page_schema, list):
            schema_items.extend(item for item in page_schema if isinstance(item, dict))

    limits = {
        "about_text": 2200,
        "services_text": 1800,
        "locations_text": 1800,
        "team_text": 2600,
        "company_legal_text": 1800,
        "privacy_compliance_text": 1200,
    }
    for bucket, lines in bucket_lines.items():
        bundle[bucket] = limit_text("\n".join(dedupe_lines(lines, 30)), limits[bucket])

    bundle["contact_text"] = limit_text("\n".join(dedupe_lines(contact_lines, 20)), 1000)
    bundle["footer_text"] = limit_text("\n".join(dedupe_lines(footer_lines, 12)), 1200)
    bundle["schema_org"] = schema_items[:8]
    return bundle


def render_evidence_bundle(bundle: dict[str, Any]) -> str:
    lines: list[str] = ["# Structured Website Evidence"]
    sources = bundle.get("page_sources", [])
    if isinstance(sources, list) and sources:
        lines.append("## Page Sources")
        for source in sources[:6]:
            if not isinstance(source, dict):
                continue
            title = compact_whitespace(source.get("title", ""))
            url = compact_whitespace(source.get("url", ""))
            value = " | ".join(part for part in (title, url) if part)
            if value:
                lines.append(value)

    labels = {
        "about_text": "About",
        "services_text": "Services",
        "locations_text": "Locations",
        "team_text": "Team",
        "company_legal_text": "Legal And Group Signals",
        "contact_text": "Contacts",
        "privacy_compliance_text": "Privacy And Compliance",
        "footer_text": "Footer",
    }
    for key, label in labels.items():
        value = compact_whitespace(bundle.get(key, ""))
        if value:
            lines.extend([f"## {label}", value])

    schema_org = bundle.get("schema_org", [])
    if isinstance(schema_org, list) and schema_org:
        lines.extend(["## Schema Org", limit_text(json.dumps(schema_org[:6], ensure_ascii=True, separators=(",", ":")), 2000)])

    return "\n".join(lines).strip()


def sanitize_website_content(value: str) -> str:
    lines = [compact_whitespace(line) for line in str(value or "").splitlines()]
    cleaned = dedupe_lines(lines, 400)
    return compact_whitespace("\n".join(cleaned))


def extract_visible_text_lines(value: str, min_len: int = 35, max_items: int = 240) -> str:
    lines = [compact_whitespace(line) for line in str(value or "").splitlines()]
    filtered: list[str] = []
    for line in lines:
        if len(line) < min_len:
            continue
        if is_noise_line(line):
            continue
        filtered.append(line)
    return "\n".join(dedupe_lines(filtered, max_items))


async def new_browser(app: FastAPI) -> Browser:
    playwright: Playwright = app.state.playwright
    return await playwright.chromium.launch(
        headless=os.getenv("CRAWL4AI_HEADLESS", "true").lower() != "false",
        args=["--disable-dev-shm-usage", "--no-sandbox"],
    )


async def ensure_browser(app: FastAPI) -> Browser:
    browser: Browser | None = getattr(app.state, "browser", None)
    if browser is None or not browser.is_connected():
        browser = await new_browser(app)
        app.state.browser = browser
    return browser


app = FastAPI(title="Browser Scraper", version="2.0.0")

SCRAPE_CONCURRENCY = max(1, int(os.getenv("CRAWL4AI_MAX_CONCURRENCY", "1")))
PUBLIC_ENRICH_STATIC_CONCURRENCY = max(1, int(os.getenv("PUBLIC_ENRICH_STATIC_CONCURRENCY", "4")))
OUTREACH_PLAN_CONCURRENCY = max(1, int(os.getenv("OUTREACH_PLAN_CONCURRENCY", "2")))
CONTACT_ROW_ASYNC_CONCURRENCY = max(1, int(os.getenv("CONTACT_ROW_ASYNC_CONCURRENCY", "4")))
_loop_semaphores: dict[tuple[str, int], asyncio.Semaphore] = {}
_contact_row_tasks: set[asyncio.Task[Any]] = set()


def loop_semaphore(name: str, limit: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = (name, id(loop))
    semaphore = _loop_semaphores.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, limit))
        _loop_semaphores[key] = semaphore
    return semaphore


def scrape_semaphore() -> asyncio.Semaphore:
    return loop_semaphore("scrape", SCRAPE_CONCURRENCY)


def public_enrich_static_semaphore() -> asyncio.Semaphore:
    return loop_semaphore("public_enrich_static", PUBLIC_ENRICH_STATIC_CONCURRENCY)


def outreach_plan_semaphore() -> asyncio.Semaphore:
    return loop_semaphore("outreach_plan", OUTREACH_PLAN_CONCURRENCY)


def contact_row_async_semaphore() -> asyncio.Semaphore:
    return loop_semaphore("contact_row_async", CONTACT_ROW_ASYNC_CONCURRENCY)


@app.on_event("startup")
async def startup() -> None:
    app.state.playwright = await async_playwright().start()
    app.state.browser = await new_browser(app)


@app.on_event("shutdown")
async def shutdown() -> None:
    browser: Browser | None = getattr(app.state, "browser", None)
    if browser is not None:
        await browser.close()
    playwright: Playwright | None = getattr(app.state, "playwright", None)
    if playwright is not None:
        await playwright.stop()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/planner-version")
async def planner_version() -> dict[str, str]:
    return {"planner_version": "strict-placeholder-smoke-20260601"}


@app.get("/runtime-diagnostics")
async def runtime_diagnostics() -> dict[str, Any]:
    return {
        "status": "ok",
        "captcha_solver": captcha_solver_diagnostics(),
    }


@app.get("/contact-provider-health")
async def contact_provider_health() -> dict[str, Any]:
    return {
        "provider_order": contact_enrichment.configured_provider_order(),
        "provider_reset_token": contact_enrichment.PROVIDER_RESET_TOKEN,
        "providers": contact_enrichment.provider_health_snapshot(),
        "captcha_solver": captcha_solver_diagnostics(),
    }


@app.post("/contact-provider-health/reset")
async def contact_provider_reset() -> dict[str, Any]:
    contact_enrichment.reset_provider_state("", preserve_non_timeout=False)
    return {
        "ok": True,
        "provider_reset_token": contact_enrichment.PROVIDER_RESET_TOKEN,
        "providers": contact_enrichment.provider_health_snapshot(),
    }


CONTACT_ROW_FIELDS = ",".join(
    [
        "Id",
        "company_name",
        "company_homepage_name",
        "best_url",
        "canonical_domain",
        "duplicate_of_id",
        "website_content",
        "contact_search_status",
        "contact_search_reason",
        "contact_candidates_json",
        "selected_contact_name",
        "selected_contact_role",
        "selected_contact_seniority",
        "selected_contact_source_url",
        "selected_contact_linkedin_url",
        "selected_contact_confidence",
        "email_candidates_json",
        "validated_email",
        "duplicate_validated_email_of_id",
        "email_validation_status",
        "email_validation_summary",
        "email_validation_provider",
        "email_validation_evidence_json",
        "contact_search_started_at",
        "contact_search_finished_at",
        "contact_search_run_id",
        "CreatedAt",
        "UpdatedAt",
    ]
)


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def noco_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "rayn-contact-runner/1.0",
        "xc-token": env_required("NOCO_API_TOKEN"),
    }


def noco_table_url(bulk: bool = False) -> str:
    base = env_required("NOCO_BASE_URL").rstrip("/")
    project = env_required("NOCO_PROJECT_ID")
    table = env_required("NOCO_TABLE_ID")
    segment = "bulk/noco" if bulk else "noco"
    return f"{base}/api/v1/db/data/{segment}/{project}/{table}"


def noco_request(method: str, url: str, body: Any | None = None, params: dict[str, Any] | None = None) -> Any:
    response = requests.request(
        method,
        url,
        headers=noco_headers(),
        json=body,
        params=params,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"NocoDB {response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def noco_fetch_contact_rows(limit: int, ids: list[int | str]) -> list[dict[str, Any]]:
    if ids:
        clean_ids = [str(row_id).strip() for row_id in ids if str(row_id).strip()]
        where = f"(Id,in,{','.join(clean_ids)})"
        effective_limit = max(limit, len(clean_ids))
    else:
        where = "(status,eq,completed)~and(canonical_domain,notblank)~and(best_url,notblank)~and(duplicate_of_id,blank)~and(contact_search_status,eq,pending)"
        effective_limit = limit
    payload = noco_request(
        "GET",
        noco_table_url(),
        params={
            "where": where,
            "fields": CONTACT_ROW_FIELDS,
            "limit": str(effective_limit),
            "sort": "Id",
        },
    )
    rows = payload.get("list") if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def noco_patch_rows(rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return {}
    return noco_request("PATCH", noco_table_url(bulk=True), body=rows)


def normalized_validated_email(value: Any) -> str:
    email = compact_whitespace(str(value or "")).lower()
    return email if "@" in email else ""


def noco_find_duplicate_validated_email(row_id: Any, validated_email: Any) -> str:
    email = normalized_validated_email(validated_email)
    if not email:
        return ""
    current_id = str(row_id or "").strip()
    where = f"(validated_email,eq,{email})"
    if current_id:
        where += f"~and(Id,neq,{current_id})"
    try:
        payload = noco_request(
            "GET",
            noco_table_url(),
            params={
                "where": where,
                "fields": "Id,validated_email",
                "limit": "1",
                "sort": "Id",
            },
        )
    except Exception as exc:
        print(f"duplicate_validated_email_lookup_error row_id={current_id}: {compact_whitespace(str(exc))}")
        return ""
    rows = payload.get("list") if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not rows:
        return ""
    return str(rows[0].get("Id") or "")


def annotate_validated_email_duplicate(patch: dict[str, Any]) -> dict[str, Any]:
    duplicate_of_id = noco_find_duplicate_validated_email(
        patch.get("Id"),
        patch.get("validated_email"),
    )
    patch["duplicate_validated_email_of_id"] = duplicate_of_id
    if duplicate_of_id:
        patch.update(
            {
                "automation_decision": "suppressed",
                "automation_decision_reason": "suppressed_duplicate_validated_email",
                "automation_blockers_json": json.dumps(
                    [{"code": "duplicate_validated_email", "duplicate_of_id": duplicate_of_id}],
                    ensure_ascii=False,
                ),
                "email_send_ready": False,
                "final_send_gate_passed": False,
                "send_status": "suppressed",
                "sequence_status": "suppressed",
            }
        )
    return patch


def terminal_contact_patch(row_id: Any, status: str, reason: str, run_id: str, started_at: str, error: str = "") -> dict[str, Any]:
    return {
        "Id": row_id,
        "contact_search_status": status,
        "contact_search_reason": reason,
        "contact_search_started_at": started_at,
        "contact_search_finished_at": contact_enrichment.now_iso(),
        "contact_search_run_id": run_id,
        "contact_candidates_json": "[]",
        "contact_search_evidence_json": json.dumps({"error": error or reason}, ensure_ascii=False),
        "email_candidates_json": "[]",
        "validated_email": "",
        "duplicate_validated_email_of_id": "",
        "email_validation_provider": "anymail_finder",
        "email_validation_status": "worker_error" if status == "failed" else "",
        "email_validation_summary": f"Email validation error: {error or reason}" if status == "failed" else "",
        "email_validation_evidence_json": json.dumps({"error": error or reason}, ensure_ascii=False),
        "retry_eligible": "true" if status == "failed" else "false",
    }


def contact_payload_from_row(row: dict[str, Any], run_id: str, site_fast_path_only: bool, validate_email: bool) -> dict[str, Any]:
    max_queries = max(1, int(os.getenv("CONTACT_SEARCH_MAX_QUERIES_PER_ROW", "6")))
    website_content = compact_whitespace(str(row.get("website_content") or ""))[:50000]
    payload = {
        "Id": row.get("Id", ""),
        "company_name": compact_whitespace(row.get("company_name", "")),
        "company_homepage_name": compact_whitespace(row.get("company_homepage_name", "")),
        "best_url": compact_whitespace(row.get("best_url", "")),
        "canonical_domain": compact_whitespace(row.get("canonical_domain", "")),
        "website_content": website_content,
        "contact_search_run_id": run_id,
        "provider_reset_token": run_id,
        "search_attempts": [],
        "validate_email": validate_email,
        "site_fast_path_only": site_fast_path_only,
    }
    if not site_fast_path_only:
        payload["search_queries"] = contact_enrichment.build_role_queries(
            payload["company_name"],
            payload["company_homepage_name"],
            payload["canonical_domain"],
            website_content=website_content,
            max_queries=max_queries,
        )
    return payload


def exclusion_payload(result: contact_enrichment.ContactResult) -> tuple[list[str], list[str]]:
    names = sorted(
        {
            normalized
            for normalized in (
                contact_enrichment.normalize_person_name(candidate.get("name", ""))
                for candidate in result.contact_candidates
                if isinstance(candidate, dict)
            )
            if normalized
        }
    )
    emails = sorted(
        {
            compact_whitespace(candidate.get("email", "")).lower()
            for candidate in result.email_candidates
            if isinstance(candidate, dict) and compact_whitespace(candidate.get("email", ""))
        }
    )
    return names, emails


def exclusion_names_from_result(result: contact_enrichment.ContactResult) -> list[str]:
    names, _ = exclusion_payload(result)
    return names


def merge_preflight_into_fallback(
    preflight_result: contact_enrichment.ContactResult,
    fallback_result: contact_enrichment.ContactResult,
) -> contact_enrichment.ContactResult:
    seen_candidates: set[tuple[str, str, str]] = set()
    merged_candidates: list[dict[str, Any]] = []
    for stage, candidates in (
        ("official_site_preflight", preflight_result.contact_candidates),
        ("fallback_search", fallback_result.contact_candidates),
    ):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            key = (
                compact_whitespace(candidate.get("name", "")).lower(),
                compact_whitespace(candidate.get("role", "")).lower(),
                compact_whitespace(candidate.get("source_url", "")).lower(),
            )
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            merged = dict(candidate)
            merged.setdefault("candidate_stage", stage)
            merged_candidates.append(merged)

    merged_email_candidates = [
        *(item for item in preflight_result.email_candidates if isinstance(item, dict)),
        *(item for item in fallback_result.email_candidates if isinstance(item, dict)),
    ]
    fallback_result.contact_candidates = merged_candidates
    fallback_result.email_candidates = merged_email_candidates
    fallback_result.contact_search_evidence = {
        **fallback_result.contact_search_evidence,
        "official_site_preflight_candidate_count": len(preflight_result.contact_candidates),
        "official_site_preflight_candidate_names": [
            compact_whitespace(candidate.get("name", ""))
            for candidate in preflight_result.contact_candidates
            if isinstance(candidate, dict) and compact_whitespace(candidate.get("name", ""))
        ],
        "preflight_candidate_names_skipped_in_fallback": exclusion_names_from_result(preflight_result),
        "preflight_skip_reason": "already_checked_by_official_site_preflight" if preflight_result.contact_candidates else "",
    }
    fallback_result.email_validation_evidence = {
        **fallback_result.email_validation_evidence,
        "official_site_preflight_email_validation_evidence": preflight_result.email_validation_evidence,
        "official_site_preflight_email_candidates": preflight_result.email_candidates,
    }
    preflight_tried_email = any(
        isinstance(candidate, dict) and compact_whitespace(candidate.get("status", ""))
        for candidate in preflight_result.email_candidates
    )
    fallback_skipped_without_candidate = (
        fallback_result.contact_search_status == "contact_not_found"
        and fallback_result.email_validation_status in {"", "skipped_no_verified_candidate", "skipped_no_email_candidate"}
    )
    if (
        preflight_tried_email
        and preflight_result.email_validation_status == "no_deliverable_email"
        and fallback_skipped_without_candidate
    ):
        fallback_result.contact_search_reason = preflight_result.contact_search_reason
        fallback_result.email_validation_status = preflight_result.email_validation_status
        fallback_result.email_validation_evidence = {
            **fallback_result.email_validation_evidence,
            "status": preflight_result.email_validation_status,
            "reason": "official_site_preflight_candidates_had_no_deliverable_email",
            "promoted_from_official_site_preflight": True,
        }
    return fallback_result


def run_contact_row(row: dict[str, Any], validate_email: bool) -> dict[str, Any]:
    row_id = row.get("Id")
    started_at = contact_enrichment.now_iso()
    run_id = f"worker:{int(time.time())}:{row_id}"
    claim = {
        "Id": row_id,
        "contact_search_status": "processing",
        "contact_search_reason": "processing:contact_search",
        "contact_search_started_at": started_at,
        "contact_search_finished_at": "",
        "contact_search_run_id": run_id,
        "selected_contact_name": "",
        "selected_contact_role": "",
        "selected_contact_email": "",
        "selected_contact_seniority": "",
        "selected_contact_source_url": "",
        "selected_contact_linkedin_url": "",
        "selected_contact_confidence": "",
        "validated_email": "",
        "duplicate_validated_email_of_id": "",
        "email_candidates_json": "",
        "email_validation_status": "",
        "email_validation_summary": "",
        "email_validation_provider": "",
        "email_validation_evidence_json": "",
    }
    noco_patch_rows([claim])

    try:
        preflight_payload = contact_payload_from_row(row, run_id, site_fast_path_only=True, validate_email=validate_email)
        preflight_result = contact_enrichment.enrich_contact(preflight_payload, validate_email=validate_email)
        if preflight_result.contact_search_status == "contact_found":
            patch = contact_enrichment.build_patch(preflight_result)
            patch.update({"contact_search_started_at": started_at, "contact_search_run_id": run_id})
            annotate_validated_email_duplicate(patch)
            noco_patch_rows([patch])
            return {"Id": row_id, "status": patch["contact_search_status"], "reason": "preflight_contact_found", "patch": patch}

        if preflight_result.contact_search_status == "failed":
            patch = contact_enrichment.build_patch(preflight_result)
            patch.update({"contact_search_started_at": started_at, "contact_search_run_id": run_id})
            annotate_validated_email_duplicate(patch)
            noco_patch_rows([patch])
            return {"Id": row_id, "status": patch["contact_search_status"], "reason": patch["contact_search_reason"], "patch": patch}

        excluded_names, excluded_emails = exclusion_payload(preflight_result)
        fallback_payload = contact_payload_from_row(row, run_id, site_fast_path_only=False, validate_email=validate_email)
        fallback_payload["excluded_candidate_names"] = excluded_names
        fallback_payload["excluded_email_candidates"] = excluded_emails
        fallback_payload["preflight_candidate_names_skipped_in_fallback"] = excluded_names
        fallback_payload["fallback_reason"] = (
            "fallback_to_serper_alternate_contacts"
            if preflight_result.contact_candidates
            else "preflight_no_person_candidate"
        )
        fallback_result = contact_enrichment.enrich_contact(fallback_payload, validate_email=validate_email)
        fallback_result = merge_preflight_into_fallback(preflight_result, fallback_result)
        patch = contact_enrichment.build_patch(fallback_result)
        patch.update({"contact_search_started_at": started_at, "contact_search_run_id": run_id})
        annotate_validated_email_duplicate(patch)
        noco_patch_rows([patch])
        return {"Id": row_id, "status": patch["contact_search_status"], "reason": patch["contact_search_reason"], "patch": patch}
    except Exception as exc:
        error_text = compact_whitespace(str(exc)) or "contact row runner failed"
        patch = terminal_contact_patch(row_id, "failed", "contact_row_runner_error", run_id, started_at, error_text)
        annotate_validated_email_duplicate(patch)
        noco_patch_rows([patch])
        return {"Id": row_id, "status": "failed", "reason": "contact_row_runner_error", "error": error_text, "patch": patch}


async def run_contact_row_background(row: dict[str, Any], validate_email: bool) -> None:
    async with contact_row_async_semaphore():
        await asyncio.to_thread(run_contact_row, row, validate_email)


def discard_contact_row_task(task: asyncio.Task[Any]) -> None:
    _contact_row_tasks.discard(task)
    try:
        task.result()
    except Exception as exc:
        print(f"contact_row_background_error: {compact_whitespace(str(exc))}")


@app.post("/contact-enrich-row")
async def contact_enrich_row(request: ContactRowRunRequest) -> dict[str, Any]:
    row_id = request.row_id if request.row_id not in (None, "") else request.id
    if row_id in (None, ""):
        return {"ok": False, "accepted": False, "reason": "missing_row_id"}
    if request.reset_provider_health:
        contact_enrichment.reset_provider_state(f"contact-row:{int(time.time())}", preserve_non_timeout=True)
    rows = noco_fetch_contact_rows(1, [row_id])
    if not rows:
        return {"ok": False, "accepted": False, "row_id": row_id, "reason": "row_not_found"}
    task = asyncio.create_task(run_contact_row_background(rows[0], request.validate_email))
    _contact_row_tasks.add(task)
    task.add_done_callback(discard_contact_row_task)
    return {
        "ok": True,
        "accepted": True,
        "row_id": row_id,
        "active_tasks": len(_contact_row_tasks),
        "concurrency": CONTACT_ROW_ASYNC_CONCURRENCY,
    }


@app.post("/contact-enrich-batch")
async def contact_enrich_batch(request: ContactBatchRunRequest) -> dict[str, Any]:
    if request.reset_provider_health:
        contact_enrichment.reset_provider_state(f"contact-batch:{int(time.time())}", preserve_non_timeout=True)
    started = time.time()
    effective_limit = request.limit
    capped_by = ""
    if not request.ids and request.validate_email and contact_enrichment.env_flag("ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED", default=True):
        max_rows = max(1, int(os.getenv("CONTACT_BATCH_MAX_DECISION_MAKER_ROWS", "3")))
        if effective_limit > max_rows:
            effective_limit = max_rows
            capped_by = "CONTACT_BATCH_MAX_DECISION_MAKER_ROWS"
    rows = noco_fetch_contact_rows(effective_limit, request.ids)
    if request.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "rows_selected": len(rows),
            "row_ids": [row.get("Id") for row in rows],
        }
    concurrency = request.concurrency or max(1, int(os.getenv("CONTACT_BATCH_CONCURRENCY", "1")))
    concurrency = max(1, min(concurrency, len(rows) or 1, request.limit))
    semaphore = asyncio.Semaphore(concurrency)

    async def run_contact_row_thread(row: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await asyncio.to_thread(run_contact_row, row, request.validate_email)

    results = await asyncio.gather(*(run_contact_row_thread(row) for row in rows))
    status_counts: dict[str, int] = {}
    for result in results:
        status = compact_whitespace(result.get("status", "")) or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "ok": all(result.get("status") != "failed" for result in results),
        "rows_selected": len(rows),
        "rows_processed": len(results),
        "concurrency": concurrency,
        "requested_limit": request.limit,
        "effective_limit": effective_limit,
        "capped_by": capped_by,
        "status_counts": status_counts,
        "elapsed_seconds": round(time.time() - started, 2),
        "provider_order": contact_enrichment.configured_provider_order(),
        "results": [
            {
                "Id": result.get("Id"),
                "status": result.get("status"),
                "reason": result.get("reason"),
                "validated_email": (result.get("patch") or {}).get("validated_email", ""),
                "email_validation_status": (result.get("patch") or {}).get("email_validation_status", ""),
            }
            for result in results
        ],
    }


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> ScrapeResponse:
    timeout_ms = int(os.getenv("CRAWL4AI_PAGE_TIMEOUT_MS", "45000"))
    total_timeout_ms = int(os.getenv("CRAWL4AI_TOTAL_TIMEOUT_MS", "90000"))
    follow_links_limit = max(0, int(os.getenv("CRAWL4AI_FOLLOW_LINKS_LIMIT", "4")))
    context = None
    page = None

    async def run_scrape() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        nonlocal context, page
        async with scrape_semaphore():
            browser = await ensure_browser(app)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            primary = await extract_page_with_captcha_retry(page, str(request.url), timeout_ms)
            follow_links = pick_follow_links(
                primary["url"],
                primary["links"],
                limit=follow_links_limit,
            )

            extra_pages: list[dict[str, Any]] = []
            for href in follow_links:
                if href.rstrip("/") == primary["url"].rstrip("/"):
                    continue
                extra_page = await context.new_page()
                try:
                    extracted = await extract_page_with_captcha_retry(extra_page, href, min(timeout_ms, 20000))
                    if isinstance(extracted, dict):
                        extra_pages.append(extracted)
                except Exception:
                    pass
                finally:
                    await extra_page.close()
            return primary, extra_pages

    try:
        primary, extra_pages = await asyncio.wait_for(
            run_scrape(),
            timeout=total_timeout_ms / 1000,
        )

    except Exception as exc:
        if page is not None:
            await page.close()
        if context is not None:
            await context.close()
        try:
            app.state.browser = await new_browser(app)
        except Exception:
            pass
        if isinstance(exc, TimeoutError) or isinstance(exc, asyncio.TimeoutError):
            error_text = f"scrape_timeout: {total_timeout_ms}ms"
        else:
            error_text = compact_whitespace(str(exc))
        return ScrapeResponse(
            ok=False,
            url=str(request.url),
            error=f"scrape_error: {error_text}",
        )

    if page is not None:
        await page.close()
    if context is not None:
        await context.close()

    combined_main_text = limit_text(
        "\n\n".join(
            [primary.get("visible_text", "")]
            + [item.get("visible_text", "") for item in extra_pages if isinstance(item, dict)]
        ),
        15000,
    )

    markdown_sections = [render_page_section(primary, 20)]
    markdown_sections.extend(render_page_section(item, 12) for item in extra_pages if isinstance(item, dict))
    markdown = limit_text("\n\n".join(section for section in markdown_sections if section), 15000)
    evidence_bundle = build_evidence_bundle(primary, extra_pages)
    structured_evidence = limit_text(render_evidence_bundle(evidence_bundle), 8000)

    # Merge both artifacts, then normalize to remove repeated chrome/noise lines.
    raw_website_content = "\n\n".join(part for part in (structured_evidence, markdown, combined_main_text) if part)
    website_content = limit_text(sanitize_website_content(raw_website_content), 15000)

    # Some sites render sparse semantic HTML but expose meaningful body text.
    # If cleaned content is too short, recover additional signal from visible text lines.
    if len(website_content) < 1200:
        visible_fallback = extract_visible_text_lines(
            "\n".join(
                [primary.get("visible_text", "")]
                + [item.get("visible_text", "") for item in extra_pages if isinstance(item, dict)]
            ),
            min_len=35,
            max_items=260,
        )
        if visible_fallback:
            recovered = sanitize_website_content(
                "\n\n".join(part for part in (website_content, visible_fallback) if part)
            )
            if len(recovered) > len(website_content):
                website_content = limit_text(recovered, 15000)

    final_url = primary.get("url", "") or str(request.url)
    title = compact_whitespace(primary.get("title", ""))[:300]
    metadata: MetadataPayload = primary.get("metadata") or MetadataPayload()
    signals = build_signals(final_url, title, website_content, request.company_name)
    quality = build_quality(title, website_content)

    return ScrapeResponse(
        ok=bool(website_content),
        url=str(request.url),
        final_url=final_url,
        title=title,
        markdown=markdown,
        main_text=combined_main_text,
        website_content=website_content,
        evidence_bundle=evidence_bundle,
        metadata=metadata,
        signals=signals,
        quality=quality,
        error="",
    )


def public_enrich_hard_timeout_seconds(request: PublicEnrichmentRequest) -> float:
    stage = "deep_retry" if request.enrichment_stage == "deep_retry" else "fast"
    default_timeout = 300 if stage == "deep_retry" else 180
    configured = float(os.getenv("PUBLIC_ENRICH_HARD_TIMEOUT_SECONDS", str(default_timeout)))
    if request.row_timeout_seconds:
        fallback_reserve = float(os.getenv("PUBLIC_ENRICH_FALLBACK_RESERVE_SECONDS", "60"))
        configured = max(configured, float(request.row_timeout_seconds) + fallback_reserve)
    return max(30.0, configured)


def public_enrich_timeout_response(request_data: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    row_id = request_data.get("Id") or request_data.get("row_id") or ""
    url_picked = compact_whitespace(request_data.get("url_picked") or "")
    normalized = public_enrichment.canonical_root_url(url_picked)
    error_text = f"public_enrich_timeout_after_{int(timeout_seconds)}s"
    patch = {
        "Id": row_id,
        "best_url": normalized.best_url,
        "best_url_candidate": normalized.best_url,
        "last_stage": "enrichment_error",
        "last_error": error_text,
        "notes": error_text,
        "url_validation_status": "timeout",
    }
    return {
        "ok": False,
        "row_id": row_id,
        "error": error_text,
        "preflight_action": "",
        "preflight_reason": "",
        "patch": patch,
        "record": {},
    }


async def public_enrich_core(
    request: PublicEnrichmentRequest,
    *,
    force_browser_primary: bool = False,
) -> dict[str, Any]:
    input_row = public_enrichment.InputRow(
        row_id=request.Id,
        company_name=request.company_name,
        url_picked=request.url_picked,
        allow_cross_domain_redirect=request.allow_cross_domain_redirect,
    )
    browser_config = public_enrichment.BrowserConfig(
        browser_type="chromium",
        headless=os.getenv("CRAWL4AI_HEADLESS", "true").lower() != "false",
        viewport_width=1280,
        viewport_height=1800,
        ignore_https_errors=True,
        verbose=os.getenv("CRAWL4AI_VERBOSE", "false").lower() == "true",
    )

    stage = "deep_retry" if request.enrichment_stage == "deep_retry" else "fast"

    async def run_attempt(
        page_limit: int,
        page_timeout_ms: int,
        request_delay_seconds: float,
        scrape_char_limit: int,
        *,
        static_only: bool = False,
    ):
        default_timeout_cap = "180" if stage == "fast" else "360"
        timeout_seconds = min(
            float(os.getenv("PUBLIC_ENRICH_ATTEMPT_TIMEOUT_SECONDS", default_timeout_cap)),
            max(45.0, (page_limit * (page_timeout_ms / 1000.0 + request_delay_seconds)) + 45.0),
        )
        if request.row_timeout_seconds:
            fallback_reserve = 0.0 if static_only else float(os.getenv("PUBLIC_ENRICH_FALLBACK_RESERVE_SECONDS", "60"))
            timeout_seconds = min(timeout_seconds, max(45.0, float(request.row_timeout_seconds) - fallback_reserve))
        use_static_transport = (
            static_only
            or (
                not force_browser_primary
                and stage == "fast"
                and os.getenv("PUBLIC_ENRICH_FAST_STATIC_FIRST", "true").lower() != "false"
                and os.getenv("PUBLIC_ENRICH_FAST_BROWSER_PRIMARY", "false").lower() != "true"
            )
            or (
                not force_browser_primary
                and stage == "deep_retry"
                and os.getenv("PUBLIC_ENRICH_DEEP_STATIC_FIRST", "true").lower() != "false"
                and os.getenv("PUBLIC_ENRICH_DEEP_BROWSER_PRIMARY", "false").lower() != "true"
            )
        )
        if use_static_transport:
            return await asyncio.wait_for(
                public_enrichment.enrich_row(
                    row=input_row,
                    crawler=None,
                    page_limit=page_limit,
                    page_timeout_ms=page_timeout_ms,
                    request_delay_seconds=request_delay_seconds,
                    scrape_char_limit=scrape_char_limit,
                    enrichment_stage=stage,
                    per_row_page_concurrency=request.per_row_page_concurrency,
                ),
                timeout=timeout_seconds,
            )
        async with public_enrichment.AsyncWebCrawler(config=browser_config) as crawler:
            return await asyncio.wait_for(
                public_enrichment.enrich_row(
                    row=input_row,
                    crawler=crawler,
                    page_limit=page_limit,
                    page_timeout_ms=page_timeout_ms,
                    request_delay_seconds=request_delay_seconds,
                    scrape_char_limit=scrape_char_limit,
                    enrichment_stage=stage,
                    per_row_page_concurrency=request.per_row_page_concurrency,
                ),
                timeout=timeout_seconds,
            )

    try:
        async with scrape_semaphore():
            if request.allow_low_limits:
                effective_page_limit = min(18 if stage == "deep_retry" else 14, max(1, request.page_limit))
                effective_scrape_char_limit = min(180000, max(2000, request.scrape_char_limit))
            else:
                effective_page_limit = min(
                    18 if stage == "deep_retry" else 14,
                    max(
                        request.page_limit,
                        int(os.getenv("PUBLIC_ENRICH_MIN_PAGE_LIMIT", "14" if stage == "deep_retry" else "6")),
                    ),
                )
                effective_scrape_char_limit = min(
                    180000,
                    max(request.scrape_char_limit, int(os.getenv("PUBLIC_ENRICH_MIN_SCRAPE_CHARS", "120000"))),
                )
            try:
                record = await run_attempt(
                    effective_page_limit,
                    request.page_timeout_ms,
                    request.request_delay_seconds,
                    effective_scrape_char_limit,
                )
            except asyncio.TimeoutError as exc:
                if effective_page_limit <= 1:
                    raise exc
                fallback_limit = min(4, effective_page_limit)
                fallback_timeout_ms = min(request.page_timeout_ms, 12000)
                record = await run_attempt(
                    fallback_limit,
                    fallback_timeout_ms,
                    min(request.request_delay_seconds, 0.1),
                    effective_scrape_char_limit,
                    static_only=True,
                )
                record.crawl_status = "partial"
                record.error_notes.append(
                    f"full public enrichment timed out; recovered with fallback page_limit={fallback_limit}"
                )
                record.enrichment_notes += (
                    f" Full scrape timed out; fallback crawl used {fallback_limit} page(s)."
                )
    except Exception as exc:
        error_text = compact_whitespace(str(exc)) or "public enrichment failed"
        patch = {
            "Id": request.Id,
            "last_stage": "enrichment_error",
            "last_error": error_text,
            "notes": error_text,
        }
        return {
            "ok": False,
            "row_id": request.Id,
            "error": error_text,
            "preflight_action": "",
            "preflight_reason": "",
            "patch": patch,
            "record": {},
        }

    patch = public_enrichment.build_noco_patch(record)
    return {
        "ok": record.crawl_status in {"crawled", "partial"},
        "row_id": record.row_id,
        "error": " | ".join(record.error_notes[:8]),
        "patch": patch,
        "record": public_enrichment.record_to_json(record),
    }


def public_enrich_child_main(request_data: dict[str, Any], result_queue: Any) -> None:
    try:
        request = PublicEnrichmentRequest.model_validate(request_data)
        result_queue.put(
            {
                "ok": True,
                "result": asyncio.run(
                    public_enrich_core(
                        request,
                        force_browser_primary=bool(request_data.get(PUBLIC_ENRICH_FORCE_BROWSER_KEY)),
                    )
                ),
            }
        )
    except Exception as exc:
        result_queue.put({"ok": False, "error": compact_whitespace(str(exc)) or exc.__class__.__name__})


def public_enrich_is_fast_static_only(request_data: dict[str, Any]) -> bool:
    if request_data.get(PUBLIC_ENRICH_FORCE_BROWSER_KEY):
        return False
    stage = "deep_retry" if str(request_data.get("enrichment_stage") or "fast") == "deep_retry" else "fast"
    browser_primary_key = "PUBLIC_ENRICH_DEEP_BROWSER_PRIMARY" if stage == "deep_retry" else "PUBLIC_ENRICH_FAST_BROWSER_PRIMARY"
    static_first_key = "PUBLIC_ENRICH_DEEP_STATIC_FIRST" if stage == "deep_retry" else "PUBLIC_ENRICH_FAST_STATIC_FIRST"
    return (
        os.getenv(static_first_key, "true").lower() != "false"
        and os.getenv(browser_primary_key, "false").lower() != "true"
    )


def public_enrich_needs_browser_retry(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict) or result.get("ok"):
        return False
    record = result.get("record") if isinstance(result.get("record"), dict) else {}
    patch = result.get("patch") if isinstance(result.get("patch"), dict) else {}
    validation_status = str(
        record.get("url_validation_status") or patch.get("url_validation_status") or ""
    ).strip()
    crawl_status = str(record.get("crawl_status") or patch.get("last_stage") or "").strip()
    if crawl_status and crawl_status not in {"crawl_failed", "enrichment_error"}:
        return False
    error_text = " ".join(
        compact_whitespace(value)
        for value in (
            result.get("error"),
            patch.get("last_error"),
            patch.get("notes"),
            " ".join(record.get("error_notes") or []) if isinstance(record.get("error_notes"), list) else "",
        )
        if value
    )
    if public_enrichment.proxy_retryable_error(error_text):
        return True
    if validation_status not in PUBLIC_ENRICH_BROWSER_RETRY_STATUSES:
        return False
    return validation_status == "failed_redirect_loop" or public_enrichment.proxy_retryable_error(error_text)


def public_enrich_needs_low_limit_retry(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict) or result.get("ok"):
        return False
    record = result.get("record") if isinstance(result.get("record"), dict) else {}
    patch = result.get("patch") if isinstance(result.get("patch"), dict) else {}
    error_text = " ".join(
        compact_whitespace(value)
        for value in (
            result.get("error"),
            patch.get("last_error"),
            patch.get("notes"),
            " ".join(record.get("error_notes") or []) if isinstance(record.get("error_notes"), list) else "",
        )
        if value
    ).lower()
    if not error_text:
        return False
    return (
        "aborted" in error_text
        or "timeout" in error_text
        or "timed out" in error_text
        or "public_enrich_timeout_after_" in error_text
    )


def run_public_enrich_fast_static(request_data: dict[str, Any]) -> dict[str, Any]:
    request = PublicEnrichmentRequest.model_validate(request_data)
    stage = "deep_retry" if request.enrichment_stage == "deep_retry" else "fast"
    max_pages = 18 if stage == "deep_retry" else 14
    max_chars = 160000 if stage == "deep_retry" else 120000
    input_row = public_enrichment.InputRow(
        row_id=request.Id,
        company_name=request.company_name,
        url_picked=request.url_picked,
        allow_cross_domain_redirect=request.allow_cross_domain_redirect,
    )
    record = asyncio.run(
        public_enrichment.enrich_row(
            row=input_row,
            crawler=None,
            page_limit=min(max(1, request.page_limit), max_pages),
            page_timeout_ms=min(request.page_timeout_ms, 15000 if stage == "deep_retry" else 12000),
            request_delay_seconds=min(request.request_delay_seconds, 0.1),
            scrape_char_limit=min(max(2000, request.scrape_char_limit), max_chars),
            enrichment_stage=stage,
            per_row_page_concurrency=min(max(1, request.per_row_page_concurrency), 2),
        )
    )
    patch = public_enrichment.build_noco_patch(record)
    return {
        "ok": record.crawl_status in {"crawled", "partial"},
        "row_id": record.row_id,
        "error": " | ".join(record.error_notes[:8]),
        "patch": patch,
        "record": public_enrichment.record_to_json(record),
    }


def public_enrich_low_limit_fallback_data(request_data: dict[str, Any]) -> dict[str, Any]:
    page_limit = min(
        max(1, int(request_data.get("page_limit") or 1)),
        max(1, int(os.getenv("PUBLIC_ENRICH_TIMEOUT_FALLBACK_PAGE_LIMIT", "1"))),
    )
    page_timeout_ms = min(
        max(5000, int(request_data.get("page_timeout_ms") or 8000)),
        max(5000, int(os.getenv("PUBLIC_ENRICH_TIMEOUT_FALLBACK_PAGE_TIMEOUT_MS", "8000"))),
    )
    scrape_char_limit = min(
        max(2000, int(request_data.get("scrape_char_limit") or 60000)),
        max(2000, int(os.getenv("PUBLIC_ENRICH_TIMEOUT_FALLBACK_SCRAPE_CHARS", "60000"))),
    )
    return {
        **request_data,
        "allow_low_limits": True,
        "page_limit": page_limit,
        "page_timeout_ms": page_timeout_ms,
        "request_delay_seconds": min(float(request_data.get("request_delay_seconds") or 0.0), 0.1),
        "scrape_char_limit": scrape_char_limit,
        "per_row_page_concurrency": 1,
    }


def public_enrich_http_first_data(request_data: dict[str, Any]) -> dict[str, Any]:
    page_limit = min(
        max(1, int(request_data.get("page_limit") or 3)),
        max(1, int(os.getenv("PUBLIC_ENRICH_HTTP_FIRST_PAGE_LIMIT", "3"))),
    )
    page_timeout_ms = min(
        max(5000, int(request_data.get("page_timeout_ms") or 12000)),
        max(5000, int(os.getenv("PUBLIC_ENRICH_HTTP_FIRST_PAGE_TIMEOUT_MS", "12000"))),
    )
    scrape_char_limit = min(
        max(2000, int(request_data.get("scrape_char_limit") or 120000)),
        max(2000, int(os.getenv("PUBLIC_ENRICH_HTTP_FIRST_SCRAPE_CHARS", "120000"))),
    )
    return {
        **request_data,
        "enrichment_stage": "fast",
        "allow_low_limits": True,
        "page_limit": page_limit,
        "page_timeout_ms": page_timeout_ms,
        "request_delay_seconds": min(float(request_data.get("request_delay_seconds") or 0.0), 0.1),
        "scrape_char_limit": scrape_char_limit,
        "per_row_page_concurrency": 1,
        "row_timeout_seconds": min(
            max(30, int(request_data.get("row_timeout_seconds") or 75)),
            max(30, int(os.getenv("PUBLIC_ENRICH_HTTP_FIRST_ROW_TIMEOUT_SECONDS", "75"))),
        ),
    }


def public_enrich_short_browser_retry_data(request_data: dict[str, Any]) -> dict[str, Any]:
    page_limit = min(
        max(1, int(request_data.get("page_limit") or 3)),
        max(1, int(os.getenv("PUBLIC_ENRICH_BROWSER_RETRY_PAGE_LIMIT", "3"))),
    )
    page_timeout_ms = min(
        max(5000, int(request_data.get("page_timeout_ms") or 10000)),
        max(5000, int(os.getenv("PUBLIC_ENRICH_BROWSER_RETRY_PAGE_TIMEOUT_MS", "10000"))),
    )
    return {
        **public_enrich_low_limit_fallback_data(request_data),
        PUBLIC_ENRICH_FORCE_BROWSER_KEY: True,
        "page_limit": page_limit,
        "page_timeout_ms": page_timeout_ms,
    }


def annotate_public_enrich_fallback(
    result: dict[str, Any],
    *,
    action: str,
    reason: str,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        return result
    result["preflight_action"] = action
    result["preflight_reason"] = reason
    patch = result.get("patch") if isinstance(result.get("patch"), dict) else {}
    if patch:
        notes = compact_whitespace(patch.get("notes") or patch.get("last_error") or "")
        patch["notes"] = compact_whitespace(f"{notes} {reason}".strip())
    return result


def run_public_enrich_low_limit_fallback(request_data: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    fallback_data = public_enrich_low_limit_fallback_data(request_data)
    fallback_timeout = max(
        30.0,
        min(
            float(os.getenv("PUBLIC_ENRICH_TIMEOUT_FALLBACK_TIMEOUT_SECONDS", "75")),
            max(30.0, timeout_seconds / 2),
        ),
    )
    result = run_public_enrich_isolated(fallback_data, fallback_timeout)
    return annotate_public_enrich_fallback(
        result,
        action="fast_static_timeout_low_limit_fallback",
        reason=f"Primary public enrichment exceeded {int(timeout_seconds)}s; low-limit fallback used.",
    )


def run_public_enrich_isolated(request_data: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    default_start_method = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    fast_static_only = public_enrich_is_fast_static_only(request_data)
    if fast_static_only and "fork" in mp.get_all_start_methods():
        start_method = "fork"
    else:
        start_method = os.getenv("PUBLIC_ENRICH_PROCESS_START_METHOD", default_start_method).strip() or default_start_method
    ctx = mp.get_context(start_method)
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=public_enrich_child_main, args=(request_data, result_queue), daemon=True)
    process.start()
    process.join(timeout_seconds + 5.0)
    if process.is_alive():
        process.terminate()
        process.join(5.0)
        if process.is_alive():
            process.kill()
            process.join(2.0)
        return public_enrich_timeout_response(request_data, timeout_seconds)
    try:
        payload = result_queue.get_nowait()
    except queue.Empty:
        return {
            **public_enrich_timeout_response(request_data, timeout_seconds),
            "error": "public_enrich_worker_exited_without_result",
        }
    if payload.get("ok"):
        return payload["result"]
    response = public_enrich_timeout_response(request_data, timeout_seconds)
    response["error"] = payload.get("error") or "public_enrich_worker_failed"
    response["patch"]["last_error"] = response["error"]
    response["patch"]["notes"] = response["error"]
    return response


@app.post("/public-enrich")
async def public_enrich(request: PublicEnrichmentRequest) -> dict[str, Any]:
    timeout_seconds = public_enrich_hard_timeout_seconds(request)
    request_data = request.model_dump()
    if public_enrich_is_fast_static_only(request_data):
        async with public_enrich_static_semaphore():
            try:
                fast_result = await asyncio.wait_for(
                    asyncio.to_thread(run_public_enrich_fast_static, request_data),
                    timeout=timeout_seconds + 5.0,
                )
            except asyncio.TimeoutError:
                return await asyncio.to_thread(
                    run_public_enrich_low_limit_fallback,
                    request_data,
                    timeout_seconds,
                )
            if public_enrich_needs_low_limit_retry(fast_result):
                return await asyncio.to_thread(
                    run_public_enrich_low_limit_fallback,
                    request_data,
                    timeout_seconds,
                )
            if public_enrich_needs_browser_retry(fast_result):
                retry_data = public_enrich_short_browser_retry_data(request_data)
                retry_timeout = max(
                    30.0,
                    min(
                        timeout_seconds,
                        float(os.getenv("PUBLIC_ENRICH_BROWSER_RETRY_TIMEOUT_SECONDS", "75")),
                    ),
                )
                async with scrape_semaphore():
                    retry_result = await asyncio.to_thread(run_public_enrich_isolated, retry_data, retry_timeout)
                if isinstance(retry_result, dict):
                    annotate_public_enrich_fallback(
                        retry_result,
                        action="browser_retry_after_static_validation_warning",
                        reason="Static validation warning triggered a short bounded browser retry.",
                    )
                return retry_result
            return fast_result
    async with scrape_semaphore():
        return await asyncio.to_thread(run_public_enrich_isolated, request_data, timeout_seconds)


@app.post("/public-enrich-http-first")
async def public_enrich_http_first(request: PublicEnrichmentRequest) -> dict[str, Any]:
    request_data = public_enrich_http_first_data(request.model_dump())
    timeout_seconds = min(
        public_enrich_hard_timeout_seconds(PublicEnrichmentRequest.model_validate(request_data)),
        float(os.getenv("PUBLIC_ENRICH_HTTP_FIRST_ENDPOINT_TIMEOUT_SECONDS", "85")),
    )
    async with public_enrich_static_semaphore():
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(run_public_enrich_fast_static, request_data),
                timeout=timeout_seconds + 5.0,
            )
        except asyncio.TimeoutError:
            result = public_enrich_timeout_response(request_data, timeout_seconds)
        if isinstance(result, dict):
            annotate_public_enrich_fallback(
                result,
                action="http_first_static_only",
                reason="HTTP-first static enrichment endpoint used; Playwright fallback intentionally skipped.",
            )
        return result


@app.post("/contact-enrich")
async def contact_enrich(request: ContactSearchRequest) -> dict[str, Any]:
    payload = request.model_dump()
    try:
        result = contact_enrichment.enrich_contact(
            payload,
            validate_email=request.validate_email,
        )
    except Exception as exc:
        error_text = compact_whitespace(str(exc)) or "contact enrichment failed"
        patch = {
            "Id": request.Id,
            "contact_search_status": "failed",
            "contact_search_reason": "contact_worker_error",
            "contact_candidates_json": "[]",
            "contact_search_evidence_json": json.dumps({"error": error_text}),
            "email_candidates_json": "[]",
            "validated_email": "",
            "duplicate_validated_email_of_id": "",
            "email_validation_provider": "anymail_finder",
            "email_validation_status": "worker_error",
            "email_validation_summary": f"Email validation error: {error_text}",
            "email_validation_evidence_json": json.dumps({"error": error_text}),
            "contact_search_finished_at": contact_enrichment.now_iso(),
        }
        return {
            "ok": False,
            "row_id": request.Id,
            "error": error_text,
            "patch": patch,
            "record": {},
        }

    patch = annotate_validated_email_duplicate(contact_enrichment.build_patch(result))
    preflight_action = ""
    preflight_reason = ""
    if request.site_fast_path_only:
        if result.contact_search_status == "contact_found":
            preflight_action = "stop"
            preflight_reason = "preflight_contact_found"
        elif result.contact_search_status == "failed":
            preflight_action = "fail"
            preflight_reason = "preflight_validation_provider_failed" if result.contact_search_reason in {
                "email_validation_provider_failed",
                "email_validation_not_configured",
            } else "preflight_worker_error"
        elif result.contact_candidates:
            preflight_action = "fallback"
            preflight_reason = "preflight_candidate_email_rejected"
        else:
            preflight_action = "fallback"
            preflight_reason = "preflight_no_person_candidate"
    return {
        "ok": result.contact_search_status == "contact_found",
        "site_preflight_decided": preflight_action == "stop",
        "preflight_action": preflight_action,
        "preflight_reason": preflight_reason,
        "excluded_candidate_names": sorted(
            {
                normalized
                for normalized in (
                    contact_enrichment.normalize_person_name(candidate.get("name", ""))
                    for candidate in result.contact_candidates
                    if isinstance(candidate, dict)
                )
                if normalized
            }
        ),
        "preflight_candidate_names_skipped_in_fallback": exclusion_names_from_result(result),
        "preflight_skip_reason": "already_checked_by_official_site_preflight" if result.contact_candidates else "",
        "excluded_email_candidates": sorted(
            {
                compact_whitespace(candidate.get("email", "")).lower()
                for candidate in result.email_candidates
                if isinstance(candidate, dict) and compact_whitespace(candidate.get("email", ""))
            }
        ),
        "fallback_reason": "fallback_to_serper_alternate_contacts" if preflight_action == "fallback" else "",
        "row_id": request.Id,
        "error": "" if result.contact_search_status in {"contact_found", "contact_not_found"} else preflight_reason or result.contact_search_reason,
        "patch": patch,
        "record": {
            "contact_candidates": result.contact_candidates,
            "email_candidates": result.email_candidates,
            "email_validation_evidence": result.email_validation_evidence,
        },
    }

@app.post("/outreach-plan")
async def outreach_plan(request: OutreachPlanRequest) -> dict[str, Any]:
    payload = request.model_dump()
    try:
        async with outreach_plan_semaphore():
            return await asyncio.to_thread(
                outreach_planner.plan_and_patch,
                payload,
                copy_qa_mode=bool(payload.get("copy_qa_mode")),
            )
    except Exception as exc:
        error_text = compact_whitespace(str(exc)) or "outreach planning failed"
        return {
            "ok": False,
            "row_id": request.Id,
            "error": error_text,
            "patch": {
                "Id": request.Id,
                "email_send_ready": False,
                "human_review_status": "not_ready",
                "email_quality_flags": json.dumps(["outreach_planner_error"], ensure_ascii=False),
            },
            "record": {},
        }


@app.post("/outreach-plan-batch")
async def outreach_plan_batch(request: OutreachPlanBatchRequest) -> dict[str, Any]:
    rows = [row.model_dump() for row in request.rows]
    if not rows:
        return {"ok": True, "count": 0, "patches": [], "audits": [], "errors": [], "results": []}

    requested_concurrency = request.concurrency or OUTREACH_PLAN_CONCURRENCY
    concurrency = max(1, min(requested_concurrency, OUTREACH_PLAN_CONCURRENCY, len(rows)))
    row_semaphore = asyncio.Semaphore(concurrency)

    async def run_row(row: dict[str, Any]) -> dict[str, Any]:
        try:
            async with row_semaphore:
                return await asyncio.to_thread(
                    outreach_planner.plan_and_patch,
                    row,
                    copy_qa_mode=bool(row.get("copy_qa_mode") or request.copy_qa_mode),
                )
        except Exception as exc:
            error_text = compact_whitespace(str(exc)) or "outreach planning failed"
            return {
                "ok": False,
                "row_id": row.get("Id", ""),
                "error": error_text,
                "patch": {
                    "Id": row.get("Id", ""),
                    "email_send_ready": False,
                    "human_review_status": "not_ready",
                    "email_quality_flags": json.dumps(["outreach_planner_error"], ensure_ascii=False),
                },
                "record": {},
            }

    async with outreach_plan_semaphore():
        results = await asyncio.gather(*(run_row(row) for row in rows))

    patches = [
        result.get("patch")
        for result in results
        if isinstance(result.get("patch"), dict) and result["patch"].get("Id")
    ]
    audits = [result.get("audit_report") for result in results if isinstance(result.get("audit_report"), dict)]
    errors = [
        {"row_id": result.get("row_id", ""), "error": result.get("error", "missing_patch")}
        for result in results
        if not (isinstance(result.get("patch"), dict) and result["patch"].get("Id"))
    ]
    return {
        "ok": not errors,
        "count": len(patches),
        "requested": len(rows),
        "concurrency": concurrency,
        "patches": patches,
        "audits": audits,
        "errors": errors,
        "results": results,
    }
