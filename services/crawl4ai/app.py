import asyncio
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from fastapi import FastAPI
from pydantic import BaseModel, Field, HttpUrl
from playwright.async_api import Browser, Page, Playwright, async_playwright


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
    metadata: MetadataPayload = Field(default_factory=MetadataPayload)
    signals: SignalPayload = Field(default_factory=SignalPayload)
    quality: QualityPayload = Field(default_factory=QualityPayload)
    error: str = ""


def compact_whitespace(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


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
        key = cleaned.lower()
        if not cleaned or key in seen:
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

    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "template"]):
        tag.decompose()

    headings = dedupe_lines(
        [node.get_text(" ", strip=True) for node in soup.select("h1, h2, h3")],
        20,
    )

    blocks: list[str] = []
    for node in soup.select("main p, main li, main address, article p, article li, section p, section li, p, li, address"):
        text = compact_whitespace(node.get_text(" ", strip=True))
        if len(text) < 30:
            continue
        blocks.append(text)
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
    }


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

    for link in links:
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
    lines: list[str] = []
    title = compact_whitespace(page_data.get("title", ""))
    url = compact_whitespace(page_data.get("url", ""))
    metadata: MetadataPayload = page_data.get("metadata") or MetadataPayload()
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
    context = None
    page = None

    try:
        async with scrape_semaphore:
            browser = await ensure_browser(app)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            primary = await extract_page(page, str(request.url), timeout_ms)
            follow_links = pick_follow_links(primary["url"], primary["links"])

            extra_pages: list[dict[str, Any]] = []
            for href in follow_links:
                if href.rstrip("/") == primary["url"].rstrip("/"):
                    continue
                extra_page = await context.new_page()
                try:
                    extra_pages.append(await extract_page(extra_page, href, min(timeout_ms, 20000)))
                except Exception:
                    pass
                finally:
                    await extra_page.close()

    except Exception as exc:
        if page is not None:
            await page.close()
        if context is not None:
            await context.close()
        try:
            app.state.browser = await new_browser(app)
        except Exception:
            pass
        return ScrapeResponse(
            ok=False,
            url=str(request.url),
            error=f"scrape_error: {compact_whitespace(str(exc))}",
        )

    if page is not None:
        await page.close()
    if context is not None:
        await context.close()

    combined_main_text = limit_text(
        "\n\n".join(
            [primary.get("visible_text", "")]
            + [item.get("visible_text", "") for item in extra_pages]
        ),
        15000,
    )

    markdown_sections = [render_page_section(primary, 20)]
    markdown_sections.extend(render_page_section(item, 12) for item in extra_pages)
    markdown = limit_text("\n\n".join(section for section in markdown_sections if section), 15000)

    # Use the richer rendered artifact instead of preferring markdown when it is sparse.
    website_content = markdown if len(markdown) >= len(combined_main_text) else combined_main_text
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
        metadata=metadata,
        signals=signals,
        quality=quality,
        error="",
    )
