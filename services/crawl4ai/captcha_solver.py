from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import Browser, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)

ORIGINAL_HOME = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
if os.name == "posix" and "darwin" in __import__("sys").platform:
    DEFAULT_PLAYWRIGHT_BROWSERS = ORIGINAL_HOME / "Library" / "Caches" / "ms-playwright"
else:
    DEFAULT_PLAYWRIGHT_BROWSERS = ORIGINAL_HOME / ".cache" / "ms-playwright"

SOLVER_TIMEOUT_SECONDS = int(os.environ.get("CAPTCHA_SOLVER_TIMEOUT_SECONDS", "120"))
SOLVER_RECAPTCHA_TIMEOUT_SECONDS = int(
    os.environ.get("CAPTCHA_SOLVER_RECAPTCHA_TIMEOUT_SECONDS", str(SOLVER_TIMEOUT_SECONDS))
)
SOLVER_POLL_INTERVAL = float(os.environ.get("CAPTCHA_SOLVER_POLL_INTERVAL", "5.0"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _api_key() -> str:
    return (
        os.getenv("TWOCAPTCHA_API_KEY", "").strip()
        or os.getenv("TWO_CAPTCHA_API_KEY", "").strip()
    )


def _capsolver_api_key() -> str:
    return os.getenv("CAPSOLVER_API_KEY", "").strip()


def _capmonster_api_key() -> str:
    return (
        os.getenv("CAPMONSTER_API_KEY", "").strip()
        or os.getenv("CAPMONSTER_CLOUD_API_KEY", "").strip()
    )


def _provider_order() -> list[str]:
    raw = os.getenv("CAPTCHA_SOLVER_PROVIDER_ORDER", "2captcha,capsolver,capmonster")
    allowed = {"2captcha", "capsolver", "capmonster"}
    ordered = [
        item.strip().lower()
        for item in raw.split(",")
        if item.strip().lower() in allowed
    ]
    for fallback in ("2captcha", "capsolver", "capmonster"):
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered


def is_configured() -> bool:
    return bool(_api_key())


def _allowed_domains() -> list[str]:
    return [
        item.strip().lower().strip(".")
        for item in os.getenv("CAPTCHA_SOLVER_ALLOWED_DOMAINS", "").split(",")
        if item.strip()
    ]


def _hostname_matches(hostname: str, domain: str) -> bool:
    host = hostname.strip().lower().strip(".")
    candidate = domain.strip().lower().strip(".")
    return bool(host and candidate and (host == candidate or host.endswith(f".{candidate}")))


def solver_diagnostics() -> dict[str, Any]:
    import importlib.util

    providers = {
        "2captcha": {
            "package": "2captcha-python",
            "import_name": "twocaptcha",
            "installed": importlib.util.find_spec("twocaptcha") is not None,
            "configured": bool(_api_key()),
            "selected": True,
        },
        "capsolver": {
            "package": "capsolver",
            "import_name": "capsolver",
            "installed": importlib.util.find_spec("capsolver") is not None,
            "configured": bool(_capsolver_api_key()),
            "selected": False,
        },
        "capmonster": {
            "package": "capmonstercloudclient",
            "import_name": "capmonstercloudclient",
            "installed": importlib.util.find_spec("capmonstercloudclient") is not None,
            "configured": bool(_capmonster_api_key()),
            "selected": False,
        },
    }
    configured = is_configured()
    allowed_domains = _allowed_domains()
    provider_order = _provider_order()
    return {
        "package": "2captcha-python",
        "import_name": "twocaptcha",
        "installed": providers["2captcha"]["installed"],
        "configured": configured,
        "enabled": configured,
        "scope_mode": "scoped" if allowed_domains else "all",
        "allowed_domains": allowed_domains,
        "provider_order": provider_order,
        "providers": providers,
    }


def _domain_allowed(hostname: str) -> bool:
    allowed = _allowed_domains()
    if not allowed:
        return True
    return any(_hostname_matches(hostname, domain) for domain in allowed)


async def _solve_recaptcha_v2(page: Page, sitekey: str, page_url: str) -> str | None:
    from twocaptcha import TwoCaptcha

    solver = TwoCaptcha(
        _api_key(),
        defaultTimeout=SOLVER_TIMEOUT_SECONDS,
        recaptchaTimeout=SOLVER_RECAPTCHA_TIMEOUT_SECONDS,
        pollingInterval=max(5, int(round(SOLVER_POLL_INTERVAL))),
    )
    try:
        result = solver.recaptcha(sitekey=sitekey, url=page_url)
        token = result.get("code") if isinstance(result, dict) else str(result)
        if token:
            return token
    except Exception as exc:
        logger.error("recaptcha solve failed: %s", exc)
    return None


async def _solve_hcaptcha(page: Page, sitekey: str, page_url: str) -> str | None:
    from twocaptcha import TwoCaptcha

    solver = TwoCaptcha(
        _api_key(),
        defaultTimeout=SOLVER_TIMEOUT_SECONDS,
        recaptchaTimeout=SOLVER_RECAPTCHA_TIMEOUT_SECONDS,
        pollingInterval=max(5, int(round(SOLVER_POLL_INTERVAL))),
    )
    try:
        result = solver.hcaptcha(sitekey=sitekey, url=page_url)
        token = result.get("code") if isinstance(result, dict) else str(result)
        if token:
            return token
    except Exception as exc:
        logger.error("hcaptcha solve failed: %s", exc)
    return None


def _extract_sitekey(html: str, captcha_type: str = "recaptcha") -> str | None:
    if captcha_type == "recaptcha":
        patterns = [
            r"""data-sitekey=["']([^"']+)""",
            r'grecaptcha\.render[^}]*sitekey\s*:\s*["\']([^"\']+)',
            r'["\']sitekey["\']\s*:\s*["\']([^"\']+)',
        ]
    elif captcha_type == "hcaptcha":
        patterns = [
            r"""data-sitekey=["']([^"']+)""",
            r"""h-captcha[^>]+sitekey=["']([^"']+)""",
            r'sitekey\s*:\s*["\']([^"\']+)',
        ]
    else:
        return None
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    return None


def _detect_captcha_type(html: str) -> str | None:
    lowered = html.lower()
    if "hcaptcha" in lowered:
        return "hcaptcha"
    if "recaptcha" in lowered or "grecaptcha" in lowered or "/sorry/index" in lowered:
        return "recaptcha"
    if any(hint in lowered for hint in ("challenge-platform", "cf-challenge", "challenge-form")):
        return "recaptcha"
    return None


async def solve_page_captcha(page: Page, html: str) -> bool:
    if not is_configured():
        return False

    captcha_type = _detect_captcha_type(html)
    if not captcha_type:
        return False

    sitekey = _extract_sitekey(html, captcha_type)
    if not sitekey:
        logger.warning("captcha detected (%s) but no sitekey found", captcha_type)
        return False

    page_url = page.url
    hostname = ""
    try:
        from urllib.parse import urlparse
        hostname = urlparse(page_url).hostname or ""
    except Exception:
        pass

    if hostname and not _domain_allowed(hostname):
        logger.warning("captcha solver: domain %s not in allowed list, skipping", hostname)
        return False

    logger.info("solving %s captcha, sitekey=%s, url=%s", captcha_type, sitekey[:20], page_url)

    if captcha_type == "hcaptcha":
        token = await _solve_hcaptcha(page, sitekey, page_url)
    else:
        token = await _solve_recaptcha_v2(page, sitekey, page_url)

    if not token:
        return False

    injected = await page.evaluate(
        """({token, captchaType}) => {
            const el = captchaType === 'hcaptcha'
                ? document.querySelector('[name="h-captcha-response"]')
                : document.querySelector('[name="g-recaptcha-response"]');
            if (el) {
                el.value = token;
                el.textContent = token;
            }
            if (typeof grecaptcha !== 'undefined' && grecaptcha.getResponse) {
                const widgets = document.querySelectorAll('.g-recaptcha');
                if (widgets.length > 0) {
                    try { grecaptcha.getResponse(); } catch(e) {}
                }
            }
            if (window.captchaCallback) { window.captchaCallback(token); }
            const forms = document.querySelectorAll('form');
            return {found: !!el, forms: forms.length};
        }""",
        {"token": token, "captchaType": captcha_type},
    )
    logger.info("token injected: %s", injected)
    return True


async def navigate_and_solve(
    playwright: Playwright,
    url: str,
    wait_selector: str | None = None,
    wait_timeout_ms: int = 15000,
    solve_captchas: bool = True,
) -> tuple[str, str]:
    browser = await playwright.chromium.launch(
        headless=os.getenv("CAPTCHA_SOLVER_HEADLESS", "true").lower() != "false",
        args=["--disable-dev-shm-usage", "--no-sandbox"],
    )
    try:
        context = await browser.new_context(
            user_agent=USER_AGENT,
            ignore_https_errors=True,
        )
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        html = await page.content()

        if solve_captchas and _detect_captcha_type(html):
            solved = await solve_page_captcha(page, html)
            if solved:
                await page.wait_for_timeout(3000)
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=wait_timeout_ms)
                    except Exception:
                        pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                html = await page.content()
            else:
                logger.warning("failed to solve captcha on %s", url)

        return page.url, html
    finally:
        await browser.close()


def navigate_and_solve_sync(
    url: str,
    wait_selector: str | None = None,
    wait_timeout_ms: int = 15000,
    solve_captchas: bool = True,
) -> tuple[str, str]:
    return asyncio.get_event_loop().run_until_complete(
        _navigate_and_solve_async(url, wait_selector, wait_timeout_ms, solve_captchas)
    )


async def _navigate_and_solve_async(
    url: str,
    wait_selector: str | None,
    wait_timeout_ms: int,
    solve_captchas: bool,
) -> tuple[str, str]:
    async with async_playwright() as playwright:
        return await navigate_and_solve(playwright, url, wait_selector, wait_timeout_ms, solve_captchas)
