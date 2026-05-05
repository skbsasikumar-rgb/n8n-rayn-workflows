import os
import sys
import types
import unittest
from unittest.mock import patch

if "bs4" not in sys.modules:
    bs4 = types.ModuleType("bs4")
    bs4.BeautifulSoup = object
    sys.modules["bs4"] = bs4

if "crawl4ai" not in sys.modules:
    crawl4ai = types.ModuleType("crawl4ai")
    crawl4ai.AsyncWebCrawler = object
    crawl4ai.BrowserConfig = object
    crawl4ai.CacheMode = object
    crawl4ai.CrawlerRunConfig = object
    sys.modules["crawl4ai"] = crawl4ai

if "captcha_solver" not in sys.modules:
    captcha_solver = types.ModuleType("captcha_solver")
    captcha_solver.solver_diagnostics = lambda: {}
    captcha_solver.solve_challenge = lambda *args, **kwargs: False
    sys.modules["captcha_solver"] = captcha_solver

from services.crawl4ai import public_web_enrichment as p


class PublicWebProxyTests(unittest.TestCase):
    def test_proxy_applies_to_registered_domain_and_subdomains(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_WEB_ENRICHMENT_PROXY_URL": "http://proxy.example:8080",
                "PUBLIC_WEB_ENRICHMENT_PROXY_MODE": "scoped",
                "PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS": "andental.sg",
            },
            clear=False,
        ):
            self.assertTrue(p.proxy_applies_to_url("https://andental.sg/"))
            self.assertTrue(p.proxy_applies_to_url("https://www.andental.sg/about"))
            self.assertFalse(p.proxy_applies_to_url("https://otherclinic.sg/"))

    def test_proxy_config_parses_auth_and_session_uses_proxy(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_WEB_ENRICHMENT_PROXY_URL": "203.0.113.10:8080:proxyuser:proxypass",
                "PUBLIC_WEB_ENRICHMENT_PROXY_MODE": "scoped",
                "PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS": "andental.sg",
            },
            clear=False,
        ):
            proxy_config = p.proxy_config_for_url("https://www.andental.sg/")
            self.assertEqual(
                proxy_config,
                {
                    "server": "http://203.0.113.10:8080",
                    "username": "proxyuser",
                    "password": "proxypass",
                },
            )
            session = p.build_requests_session("https://andental.sg/")
            self.assertEqual(session.proxies["http"], "http://proxyuser:proxypass@203.0.113.10:8080")
            self.assertEqual(session.proxies["https"], "http://proxyuser:proxypass@203.0.113.10:8080")
            self.assertFalse(session.trust_env)

    def test_proxy_defaults_to_all_domains_when_scope_not_set(self):
        with patch.dict(
            os.environ,
            {"PUBLIC_WEB_ENRICHMENT_PROXY_URL": "http://proxy.example:8080"},
            clear=False,
        ):
            self.assertFalse(p.proxy_applies_to_url("https://andental.sg/"))
            self.assertTrue(p.proxy_retry_available_for_url("https://andental.sg/"))
            self.assertEqual(
                p.proxy_config_for_url("https://andental.sg/", force=True),
                {"server": "http://proxy.example:8080"},
            )
            session = p.build_requests_session("https://andental.sg/")
            self.assertFalse(session.proxies)

    def test_proxy_always_mode_stays_global(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_WEB_ENRICHMENT_PROXY_URL": "http://proxy.example:8080",
                "PUBLIC_WEB_ENRICHMENT_PROXY_MODE": "always",
            },
            clear=False,
        ):
            self.assertTrue(p.proxy_applies_to_url("https://andental.sg/"))
            self.assertFalse(p.proxy_retry_available_for_url("https://andental.sg/"))
            session = p.build_requests_session("https://andental.sg/")
            self.assertEqual(session.proxies["http"], "http://proxy.example:8080")

    def test_proxy_scoped_mode_uses_domain_scope(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_WEB_ENRICHMENT_PROXY_URL": "http://proxy.example:8080",
                "PUBLIC_WEB_ENRICHMENT_PROXY_MODE": "scoped",
                "PUBLIC_WEB_ENRICHMENT_PROXY_DOMAINS": "andental.sg",
            },
            clear=False,
        ):
            self.assertTrue(p.proxy_applies_to_url("https://andental.sg/"))
            self.assertFalse(p.proxy_applies_to_url("https://otherclinic.sg/"))
            self.assertTrue(p.proxy_retry_available_for_url("https://andental.sg/"))
            self.assertFalse(p.proxy_retry_available_for_url("https://otherclinic.sg/"))

    def test_proxy_usage_summary_counts_attempts_and_domains(self):
        summary = p.proxy_usage_summary(
            [
                {
                    "url": "https://www.andental.sg/contact",
                    "reason": "homepage_error:HTTP 403",
                    "transport": "crawl4ai",
                    "success": True,
                },
                {
                    "url": "https://sub.andental.sg/team",
                    "reason": "subpage_error:HTTP 429",
                    "transport": "requests",
                    "success": False,
                },
            ]
        )
        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(summary["failure_count"], 1)
        self.assertEqual(summary["domains"], ["andental.sg"])
        self.assertEqual(summary["transports"], {"crawl4ai": 1, "requests": 1})
        self.assertEqual(summary["reasons"], {"homepage_error": 1, "subpage_error": 1})

    def test_proxy_usage_note_reports_attempts_and_recoveries(self):
        note = p.proxy_usage_note(
            [
                {
                    "url": "https://www.andental.sg/contact",
                    "reason": "homepage_error:HTTP 403",
                    "transport": "crawl4ai",
                    "success": True,
                }
            ]
        )
        self.assertIn("Proxy fallback attempted 1 fetches", note)
        self.assertIn("recovered 1", note)
        self.assertIn("failed 0", note)
        self.assertIn("andental.sg", note)


if __name__ == "__main__":
    unittest.main()
