import os
import sys
import types
import unittest
from unittest.mock import patch
import asyncio

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
            self.assertEqual(diagnostics["provider_order"], ["2captcha", "capsolver", "capmonster"])
            self.assertIn("providers", diagnostics)
            self.assertTrue(diagnostics["providers"]["2captcha"]["selected"])

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

    def test_recaptcha_solver_uses_configured_timeouts(self):
        fake_module = types.ModuleType("twocaptcha")

        class FakeTwoCaptcha:
            init_kwargs = None

            def __init__(self, api_key, **kwargs):
                self.api_key = api_key
                FakeTwoCaptcha.init_kwargs = kwargs

            def recaptcha(self, **kwargs):
                return {"code": "token-123"}

        fake_module.TwoCaptcha = FakeTwoCaptcha
        with patch.dict(sys.modules, {"twocaptcha": fake_module}):
            with patch.dict(os.environ, {"TWOCAPTCHA_API_KEY": "test-key"}, clear=False):
                with patch.object(captcha_solver, "SOLVER_TIMEOUT_SECONDS", 77), patch.object(
                    captcha_solver, "SOLVER_RECAPTCHA_TIMEOUT_SECONDS", 88
                ), patch.object(captcha_solver, "SOLVER_POLL_INTERVAL", 6.0):
                    token = asyncio.run(
                        captcha_solver._solve_recaptcha_v2(None, "site-key", "https://example.com/")
                    )
        self.assertEqual(token, "token-123")
        self.assertEqual(
            FakeTwoCaptcha.init_kwargs,
            {"defaultTimeout": 77, "recaptchaTimeout": 88, "pollingInterval": 6},
        )

    def test_provider_diagnostics_include_capsolver_and_capmonster(self):
        with patch.dict(
            os.environ,
            {
                "TWOCAPTCHA_API_KEY": "",
                "CAPSOLVER_API_KEY": "capsolver-key",
                "CAPMONSTER_API_KEY": "capmonster-key",
                "CAPTCHA_SOLVER_PROVIDER_ORDER": "capsolver,capmonster,2captcha",
            },
            clear=False,
        ):
            diagnostics = captcha_solver.solver_diagnostics()
        self.assertEqual(diagnostics["provider_order"], ["capsolver", "capmonster", "2captcha"])
        self.assertTrue(diagnostics["providers"]["capsolver"]["configured"])
        self.assertTrue(diagnostics["providers"]["capmonster"]["configured"])
        self.assertFalse(diagnostics["providers"]["capsolver"]["selected"])
        self.assertFalse(diagnostics["enabled"])


if __name__ == "__main__":
    unittest.main()
