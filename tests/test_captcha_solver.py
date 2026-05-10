import os
import sys
import types
import unittest
import json
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

    def test_recaptcha_solver_uses_capsolver_when_configured(self):
        calls = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode("utf-8"))
            calls.append((request.full_url, body, timeout))
            if request.full_url.endswith("/createTask"):
                return FakeResponse({"errorId": 0, "taskId": "task-1"})
            return FakeResponse(
                {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": "capsolver-token"},
                }
            )

        with patch.dict(
            os.environ,
            {
                "TWOCAPTCHA_API_KEY": "",
                "CAPSOLVER_API_KEY": "capsolver-key",
                "CAPTCHA_SOLVER_PROVIDER_ORDER": "capsolver,2captcha",
            },
            clear=False,
        ):
            with patch.object(captcha_solver, "urlopen", side_effect=fake_urlopen), patch.object(
                captcha_solver, "SOLVER_POLL_INTERVAL", 0.01
            ), patch.object(captcha_solver, "SOLVER_RECAPTCHA_TIMEOUT_SECONDS", 3):
                token = asyncio.run(
                    captcha_solver._solve_recaptcha_v2(None, "site-key", "https://example.com/")
                )

        self.assertEqual(token, "capsolver-token")
        self.assertEqual(calls[0][1]["task"]["type"], "ReCaptchaV2TaskProxyLess")
        self.assertEqual(calls[0][1]["task"]["websiteKey"], "site-key")

    def test_cloudflare_solver_uses_capsolver_proxy_format(self):
        calls = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            if request.full_url.endswith("/createTask"):
                return FakeResponse({"errorId": 0, "taskId": "cf-task"})
            return FakeResponse(
                {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {
                        "cookies": {"cf_clearance": "clearance-token"},
                        "userAgent": "Mozilla/5.0 Chrome/141 Safari/537.36",
                    },
                }
            )

        with patch.dict(os.environ, {"CAPSOLVER_API_KEY": "capsolver-key"}, clear=False):
            with patch.object(captcha_solver, "urlopen", side_effect=fake_urlopen), patch.object(
                captcha_solver, "SOLVER_POLL_INTERVAL", 0.01
            ):
                solution = asyncio.run(
                    captcha_solver.solve_cloudflare_challenge(
                        "https://example.com/",
                        html="<title>Just a moment...</title>",
                        proxy_url="http://user:pass@127.0.0.1:8080",
                        user_agent="Mozilla/5.0 Chrome/141 Safari/537.36",
                    )
                )

        self.assertEqual(solution["cookies"]["cf_clearance"], "clearance-token")
        self.assertEqual(calls[0]["task"]["type"], "AntiCloudflareTask")
        self.assertEqual(calls[0]["task"]["proxy"], "127.0.0.1:8080:user:pass")

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
        self.assertTrue(diagnostics["enabled"])
        self.assertEqual(diagnostics["active_providers"], ["capsolver"])
        self.assertTrue(diagnostics["providers"]["capsolver"]["configured"])
        self.assertTrue(diagnostics["providers"]["capmonster"]["configured"])
        self.assertTrue(diagnostics["providers"]["capsolver"]["selected"])
        self.assertFalse(diagnostics["providers"]["capmonster"]["supported"])
        self.assertFalse(diagnostics["providers"]["capmonster"]["selected"])


if __name__ == "__main__":
    unittest.main()
