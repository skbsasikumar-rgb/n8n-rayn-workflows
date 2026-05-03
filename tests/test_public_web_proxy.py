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

from services.crawl4ai import public_web_enrichment as p


class PublicWebProxyTests(unittest.TestCase):
    def test_proxy_applies_to_registered_domain_and_subdomains(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_WEB_ENRICHMENT_PROXY_URL": "http://proxy.example:8080",
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
            self.assertTrue(p.proxy_applies_to_url("https://andental.sg/"))
            self.assertEqual(
                p.proxy_config_for_url("https://andental.sg/"),
                {"server": "http://proxy.example:8080"},
            )


if __name__ == "__main__":
    unittest.main()
