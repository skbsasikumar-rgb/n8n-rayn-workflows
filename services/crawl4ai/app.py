import asyncio
import os
import re
from pathlib import Path
from typing import Any

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

from fastapi import FastAPI
from pydantic import BaseModel, Field, HttpUrl

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig


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


def extract_markdown(result: Any) -> str:
    markdown = getattr(result, "markdown", "")
    if isinstance(markdown, str):
      return limit_text(markdown)
    if hasattr(markdown, "fit_markdown") and getattr(markdown, "fit_markdown"):
      return limit_text(getattr(markdown, "fit_markdown"))
    if hasattr(markdown, "raw_markdown") and getattr(markdown, "raw_markdown"):
      return limit_text(getattr(markdown, "raw_markdown"))
    if hasattr(markdown, "markdown_with_citations") and getattr(markdown, "markdown_with_citations"):
      return limit_text(getattr(markdown, "markdown_with_citations"))
    return limit_text(markdown)


def extract_main_text(result: Any) -> str:
    for attr in ("fit_html", "cleaned_html", "html", "extracted_content"):
        value = getattr(result, attr, "")
        if value:
            return limit_text(value)
    return ""


def extract_metadata(result: Any) -> MetadataPayload:
    metadata = getattr(result, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return MetadataPayload(
        description=compact_whitespace(metadata.get("description", ""))[:500],
        lang=compact_whitespace(metadata.get("language", "") or metadata.get("lang", ""))[:40],
    )


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
    company_name_seen = bool(company_tokens) and sum(token in haystack for token in company_tokens) >= max(1, min(2, len(company_tokens)))

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


def extract_title(result: Any) -> str:
    metadata = getattr(result, "metadata", {}) or {}
    if isinstance(metadata, dict) and metadata.get("title"):
        return compact_whitespace(metadata.get("title"))[:300]
    return ""


browser_config = BrowserConfig(
    headless=os.getenv("CRAWL4AI_HEADLESS", "true").lower() != "false",
    verbose=os.getenv("CRAWL4AI_VERBOSE", "false").lower() == "true",
)


app = FastAPI(title="Crawl4AI Scraper", version="1.0.1")
SCRAPE_CONCURRENCY = max(1, int(os.getenv("CRAWL4AI_MAX_CONCURRENCY", "1")))
scrape_semaphore = asyncio.Semaphore(SCRAPE_CONCURRENCY)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest) -> ScrapeResponse:
    primary_timeout = int(os.getenv("CRAWL4AI_PAGE_TIMEOUT_MS", "45000"))
    run_attempts = [
        CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=primary_timeout,
            wait_until="networkidle",
            word_count_threshold=1,
            scan_full_page=True,
            remove_overlay_elements=True,
            excluded_tags=["noscript", "svg"],
        ),
        CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            page_timeout=min(primary_timeout, 20000),
            wait_until="domcontentloaded",
            word_count_threshold=1,
            scan_full_page=False,
            remove_overlay_elements=False,
            excluded_tags=["noscript", "svg"],
        ),
    ]

    last_error = ""
    result = None

    async with scrape_semaphore:
        for idx, run_config in enumerate(run_attempts):
            try:
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=str(request.url), config=run_config)
                last_error = ""
                break
            except Exception as exc:
                last_error = str(exc)
                if idx == 0:
                    await asyncio.sleep(1)
                    continue
                return ScrapeResponse(
                    ok=False,
                    url=str(request.url),
                    error=f"crawl_error: {last_error}",
                )

    if not getattr(result, "success", False):
        return ScrapeResponse(
            ok=False,
            url=str(request.url),
            final_url=compact_whitespace(getattr(result, "url", "")),
            error=compact_whitespace(getattr(result, "error_message", "") or last_error or "crawl_failed"),
        )

    title = extract_title(result)
    markdown = extract_markdown(result)
    main_text = extract_main_text(result)
    website_content = markdown or main_text
    metadata = extract_metadata(result)
    final_url = compact_whitespace(getattr(result, "url", "")) or str(request.url)
    signals = build_signals(final_url, title, website_content, request.company_name)
    quality = build_quality(title, website_content)

    return ScrapeResponse(
        ok=bool(website_content),
        url=str(request.url),
        final_url=final_url,
        title=title,
        markdown=markdown,
        main_text=main_text,
        website_content=website_content,
        metadata=metadata,
        signals=signals,
        quality=quality,
        error="",
    )
