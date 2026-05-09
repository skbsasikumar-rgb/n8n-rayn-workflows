import os
import sys
import types
import unittest
from unittest.mock import patch

if "playwright" not in sys.modules:
    playwright = types.ModuleType("playwright")
    sys.modules["playwright"] = playwright

if "playwright.async_api" not in sys.modules:
    async_api = types.ModuleType("playwright.async_api")
    async_api.Browser = object
    async_api.Page = object
    async_api.Playwright = object
    async_api.async_playwright = lambda *args, **kwargs: None
    sys.modules["playwright.async_api"] = async_api

from services.crawl4ai import captcha_solver


class CaptchaSolverTests(unittest.TestCase):
    def test_solver_enabled_without_allowlist(self):
        with patch.dict(os.environ, {"TWOCAPTCHA_API_KEY": "test-key", "CAPTCHA_SOLVER_ALLOWED_DOMAINS": ""}, clear=False):
            diagnostics = captcha_solver.solver_diagnostics()
            self.assertTrue(diagnostics["configured"])
            self.assertTrue(diagnostics["enabled"])
            self.assertEqual(diagnostics["scope_mode"], "all")
            self.assertEqual(diagnostics["allowed_domains"], [])

    def test_domain_allowlist_matches_subdomains(self):
        with patch.dict(
            os.environ,
            {"CAPTCHA_SOLVER_ALLOWED_DOMAINS": "ashfordmedical.com.sg,andental.sg"},
            clear=False,
        ):
            self.assertTrue(captcha_solver._domain_allowed("ashfordmedical.com.sg"))
            self.assertTrue(captcha_solver._domain_allowed("www.ashfordmedical.com.sg"))
            self.assertTrue(captcha_solver._domain_allowed("sub.andental.sg"))
            self.assertFalse(captcha_solver._domain_allowed("otherclinic.sg"))


if __name__ == "__main__":
    unittest.main()
