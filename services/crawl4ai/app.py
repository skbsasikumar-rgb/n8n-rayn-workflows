import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel, Field, HttpUrl
from playwright.async_api import Browser, Page, Playwright, async_playwright
import contact_enrichment
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
    "robot challenge",
    "checking the site connection",
    "please make sure you are authorized",
    "forbidden",
    "enable javascript",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "page not found",
    "error 404",
    "error 403",
    "error 500",
)

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
    "team",
    "leadership",
    "management",
    "doctor",
    "doctors",
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
    "/contact",
    "/contact-us",
    "/team",
    "/leadership",
    "/our-story",
    "/who-we-are",
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
    page_limit: int = Field(default=5, ge=1, le=12)
    page_timeout_ms: int = Field(default=20000, ge=5000, le=60000)
    request_delay_seconds: float = Field(default=0.3, ge=0.0, le=5.0)
    scrape_char_limit: int = Field(default=60000, ge=2000, le=120000)


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
    return QualityPayload(
        content_chars=content_chars,
        word_count=word_count,
        has_icp_terms=has_icp_terms,
        looks_like_error_page=looks_like_error_page,
    )


def dedupe_lines(lines: list[str], max_items: int) -> list[str]:
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
    "team_text": ("team", "doctor", "doctors", "physician", "medical director", "leadership", "management"),
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
        "team_text": 1400,
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
scrape_semaphore = asyncio.Semaphore(SCRAPE_CONCURRENCY)


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


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> ScrapeResponse:
    timeout_ms = int(os.getenv("CRAWL4AI_PAGE_TIMEOUT_MS", "45000"))
    total_timeout_ms = int(os.getenv("CRAWL4AI_TOTAL_TIMEOUT_MS", "90000"))
    follow_links_limit = max(0, int(os.getenv("CRAWL4AI_FOLLOW_LINKS_LIMIT", "2")))
    context = None
    page = None

    async def run_scrape() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        nonlocal context, page
        async with scrape_semaphore:
            browser = await ensure_browser(app)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            primary = await extract_page(page, str(request.url), timeout_ms)
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
                    extracted = await extract_page(extra_page, href, min(timeout_ms, 20000))
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


@app.post("/public-enrich")
async def public_enrich(request: PublicEnrichmentRequest) -> dict[str, Any]:
    input_row = public_enrichment.InputRow(
        row_id=request.Id,
        company_name=request.company_name,
        url_picked=request.url_picked,
    )
    session = public_enrichment.build_requests_session()
    browser_config = public_enrichment.BrowserConfig(
        browser_type="chromium",
        headless=os.getenv("CRAWL4AI_HEADLESS", "true").lower() != "false",
        viewport_width=1280,
        viewport_height=1800,
        ignore_https_errors=True,
        verbose=os.getenv("CRAWL4AI_VERBOSE", "false").lower() == "true",
    )
    try:
        async with scrape_semaphore:
            async with public_enrichment.AsyncWebCrawler(config=browser_config) as crawler:
                record = await public_enrichment.enrich_row(
                    row=input_row,
                    crawler=crawler,
                    session=session,
                    page_limit=request.page_limit,
                    page_timeout_ms=request.page_timeout_ms,
                    request_delay_seconds=request.request_delay_seconds,
                    scrape_char_limit=request.scrape_char_limit,
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
            "preflight_action": "fail" if request.site_fast_path_only else "",
            "preflight_reason": "preflight_worker_error" if request.site_fast_path_only else "",
            "patch": patch,
            "record": {},
        }
    finally:
        session.close()

    patch = public_enrichment.build_noco_patch(record)
    return {
        "ok": record.crawl_status in {"crawled", "partial"},
        "row_id": record.row_id,
        "error": " | ".join(record.error_notes[:8]),
        "patch": patch,
        "record": public_enrichment.record_to_json(record),
    }


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
            "email_validation_provider": "no2bounce",
            "email_validation_status": "worker_error",
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

    patch = contact_enrichment.build_patch(result)
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
        "excluded_email_candidates": sorted(
            {
                compact_whitespace(candidate.get("email", "")).lower()
                for candidate in result.email_candidates
                if isinstance(candidate, dict) and compact_whitespace(candidate.get("email", ""))
            }
        ),
        "fallback_reason": "fallback_to_openserp_alternate_contacts" if preflight_action == "fallback" else "",
        "row_id": request.Id,
        "error": "" if result.contact_search_status in {"contact_found", "contact_not_found"} else preflight_reason or result.contact_search_reason,
        "patch": patch,
        "record": {
            "contact_candidates": result.contact_candidates,
            "email_candidates": result.email_candidates,
            "email_validation_evidence": result.email_validation_evidence,
        },
    }
