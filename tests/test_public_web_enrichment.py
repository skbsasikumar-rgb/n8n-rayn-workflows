import json
import sys
import types
import unittest

try:
    import bs4  # noqa: F401
except ImportError:
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


class PublicWebEnrichmentTests(unittest.TestCase):
    def page(self, url, text, page_type="homepage", title=""):
        return p.PageArtifact(
            url=url,
            title=title or page_type,
            meta_description="",
            page_type_guess=page_type,
            text=text,
            blocks=[text],
            content_hash=str(hash(text)),
        )

    def test_hia_link_scoring_prefers_team_services_contact_over_blog(self):
        homepage = "https://clinic.example/"
        links = [
            {"href": "https://clinic.example/blog/latest-news", "text": "Latest news"},
            {"href": "https://clinic.example/our-doctors", "text": "Our doctors"},
            {"href": "https://clinic.example/services", "text": "Services"},
            {"href": "https://clinic.example/contact", "text": "Contact"},
            {"href": "https://facebook.com/clinic", "text": "Facebook"},
        ]
        selected = p.choose_candidate_pages(homepage, links, [], page_limit=4, profile="hia")
        self.assertEqual(selected[0], homepage)
        self.assertIn("https://clinic.example/our-doctors", selected)
        self.assertIn("https://clinic.example/services", selected)
        self.assertNotIn("https://facebook.com/clinic", selected)
        self.assertNotIn("https://clinic.example/blog/latest-news", selected)

    def test_non_hia_link_scoring_prefers_privacy_security_platform(self):
        homepage = "https://platform.example/"
        links = [
            {"href": "https://platform.example/news/company-update", "text": "News"},
            {"href": "https://platform.example/privacy-policy", "text": "Privacy Policy"},
            {"href": "https://platform.example/security", "text": "Security"},
            {"href": "https://platform.example/platform", "text": "Platform"},
            {"href": "https://platform.example/login", "text": "Login"},
        ]
        selected = p.choose_candidate_pages(homepage, links, [], page_limit=4, profile="non_hia")
        self.assertIn("https://platform.example/privacy-policy", selected)
        self.assertIn("https://platform.example/security", selected)
        self.assertIn("https://platform.example/platform", selected)
        self.assertNotIn("https://platform.example/login", selected)

    def test_deep_retry_adds_common_fallback_paths_when_links_are_thin(self):
        selected = p.choose_candidate_pages(
            "https://clinic.example/",
            [],
            [],
            page_limit=12,
            profile="hia",
            stage="deep_retry",
        )
        self.assertEqual(selected[0], "https://clinic.example/")
        self.assertIn("https://clinic.example/doctors", selected)
        self.assertIn("https://clinic.example/services", selected)

    def test_page_artifact_extracts_type_names_and_terms(self):
        html = """
        <html><head><title>Our Doctors</title></head><body>
        <h1>Our Doctors</h1>
        <p>Dr Jessica Choo provides cardiology consultation and treatment services.</p>
        <p>Contact us at hello@example.com. Our privacy policy explains PDPA handling.</p>
        </body></html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://clinic.example/our-doctors",
                "redirected_url": "https://clinic.example/our-doctors",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Our Doctors"},
                "status_code": 200,
            }
        )
        self.assertEqual(artifact.page_type_guess, "doctor_profile")
        self.assertIn("Dr Jessica Choo", artifact.doctor_or_team_names)
        self.assertIn("pdpa", artifact.privacy_or_pdpa_terms)
        self.assertTrue(artifact.summary)

    def test_cloudflare_word_alone_is_not_challenge(self):
        html = """
        <html><head><title>Home - Ashford Medical</title></head><body>
        <h1>WELCOME TO ASHFORD MEDICAL</h1>
        <p>Medical Services Health Screening Physiotherapy Nutritionist Patients</p>
        <script src="https://example.com/cloudflare-static/app.js"></script>
        </body></html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://ashfordmedical.com.sg/",
                "redirected_url": "https://ashfordmedical.com.sg/",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Home - Ashford Medical"},
                "status_code": 200,
            }
        )
        self.assertEqual(artifact.challenge_hints, [])
        self.assertFalse(artifact.challenge_or_error)

    def test_cloudflare_challenge_markers_still_detect(self):
        hints = p.detect_challenge_hints("Cloudflare checking the site connection verify you are human")
        self.assertIn("cloudflare", hints)
        self.assertIn("checking the site connection", hints)

    def test_static_session_uses_browser_like_headers(self):
        session = p.build_requests_session("https://clinic.example/", use_proxy=False)
        self.assertIn("Mozilla/5.0", session.headers["User-Agent"])
        self.assertIn("text/html", session.headers["Accept"])
        self.assertEqual(session.headers["Sec-Fetch-Mode"], "navigate")
        self.assertEqual(session.headers["Upgrade-Insecure-Requests"], "1")

    def test_weak_homepage_needs_retry_then_skips_after_deep_retry(self):
        pages = [self.page("https://clinic.example/", "Welcome to clinic.", "homepage")]
        status, reason = p.classify_enrichment_depth(
            pages,
            services=[],
            locations=[],
            leadership_signals=[],
            organization_type="Medical clinic",
            errors=[],
            stage="fast",
        )
        self.assertEqual(status, "weak_retry_needed")
        self.assertEqual(reason, "thin_content")
        status, reason = p.classify_enrichment_depth(
            pages,
            services=[],
            locations=[],
            leadership_signals=[],
            organization_type="Medical clinic",
            errors=[],
            stage="deep_retry",
        )
        self.assertEqual(status, "weak_skipped")
        self.assertEqual(reason, "thin_content")

    def test_empty_page_without_challenge_is_thin_not_challenge_blocked(self):
        pages = [self.page("https://clinic.example/", "", "homepage", title="Clinic")]
        status, reason = p.classify_enrichment_depth(
            pages,
            services=[],
            locations=[],
            leadership_signals=[],
            organization_type="Medical clinic",
            errors=[],
            stage="deep_retry",
        )
        self.assertEqual(status, "weak_skipped")
        self.assertEqual(reason, "thin_content")

    def test_strong_multi_page_hia_depth(self):
        pages = [
            self.page("https://clinic.example/", "clinic medical doctor patient services " * 80, "homepage"),
            self.page("https://clinic.example/services", "cardiology consultation treatment services " * 40, "services"),
            self.page("https://clinic.example/our-doctors", "Dr Jessica Choo Dr Paul Tan medical team", "doctor_profile"),
            self.page("https://clinic.example/contact", "Location 1 Orchard Road Singapore", "contact"),
        ]
        status, reason = p.classify_enrichment_depth(
            pages,
            services=["cardiology consultation"],
            locations=["1 Orchard Road Singapore"],
            leadership_signals=["Dr Jessica Choo"],
            organization_type="Specialist clinic",
            errors=[],
            stage="fast",
        )
        self.assertEqual(status, "strong")
        self.assertEqual(reason, "")

    def test_single_challenge_subpage_does_not_block_usable_site(self):
        pages = [
            self.page("https://platform.example/", "security trust platform services clients " * 80, "homepage"),
            self.page("https://platform.example/about", "about services security team clients", "about"),
            self.page("https://platform.example/contact", "", "contact"),
        ]
        pages[2].challenge_hints = ["cloudflare"]
        status, reason = p.classify_enrichment_depth(
            pages,
            services=["security platform"],
            locations=[],
            leadership_signals=[],
            organization_type="Unknown",
            errors=[],
            stage="fast",
        )
        self.assertEqual(status, "adequate")
        self.assertEqual(reason, "")

    def test_workflow_public_enrich_controls_are_bounded(self):
        workflow = json.loads(open("wf-worker.json", encoding="utf-8").read())
        nodes = {node["name"]: node for node in workflow["nodes"]}
        prepare_code = nodes["Prepare Public Enrichment"]["parameters"]["jsCode"]
        self.assertIn("enrichment_stage", prepare_code)
        self.assertIn("weak_retry", prepare_code)
        self.assertIn("page_limit: stage === 'deep_retry' ? 14 : 8", prepare_code)
        self.assertIn("page_timeout_ms: stage === 'deep_retry' ? 20000 : 15000", prepare_code)
        self.assertIn("per_row_page_concurrency: stage === 'deep_retry' ? 2 : 2", prepare_code)
        self.assertIn("row_timeout_seconds: stage === 'deep_retry' ? 300 : 150", prepare_code)
        self.assertIn("allow_low_limits: false", prepare_code)
        http_node = nodes["Crawl4AI Public Enrich"]
        self.assertEqual(http_node["parameters"]["options"]["timeout"], 360000)
        self.assertNotIn("retryOnFail", http_node)
        patch_code = nodes["Prepare Enrichment Patch"]["parameters"]["jsCode"]
        self.assertIn("isTransportTimeout", patch_code)
        self.assertIn("return []", patch_code)

    def test_fast_public_enrichment_uses_static_first(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn('PUBLIC_ENRICH_FAST_STATIC_FIRST", "true"', source)
        self.assertIn('PUBLIC_ENRICH_FAST_BROWSER_FALLBACK", "false"', source)
        self.assertIn('PUBLIC_ENRICH_FAST_CHALLENGE_RECOVERY", "false"', source)
        self.assertIn("homepage_static_ms", source)
        self.assertIn("PUBLIC_WEB_STATIC_READ_TIMEOUT_SECONDS", source)

    def test_candidate_subpages_use_bounded_concurrency(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn("async def crawl_candidate_page", source)
        self.assertIn("len(batch) < per_row_page_concurrency", source)
        self.assertIn("await asyncio.gather", source)

    def test_fast_stage_defaults_to_static_transport(self):
        source = open("services/crawl4ai/app.py", encoding="utf-8").read()
        self.assertIn("use_static_transport = (", source)
        self.assertIn('PUBLIC_ENRICH_FALLBACK_RESERVE_SECONDS", "60"', source)
        self.assertIn("static_only=stage == \"fast\"", source)
        self.assertIn("fallback_limit = min(4 if stage == \"fast\" else 2", source)
        self.assertIn('PUBLIC_ENRICH_FAST_BROWSER_PRIMARY", "false"', source)
        self.assertIn("page_limit=min(max(1, request.page_limit), 8)", source)

    def test_workflow_url_only_mode_does_not_enter_public_enrichment(self):
        workflow = json.loads(open("wf-worker.json", encoding="utf-8").read())
        nodes = {node["name"]: node for node in workflow["nodes"]}
        webhook_code = nodes["Webhook To Item"]["parameters"]["jsCode"]
        parse_code = nodes["Parse URL Pick"]["parameters"]["jsCode"]
        continue_code = nodes["Continue URL Pick Patch"]["parameters"]["jsCode"]
        enrichment_url = nodes["Get Enrichment Rows"]["parameters"]["url"]
        rows_to_enrichment_code = nodes["Rows To Enrichment Items"]["parameters"]["jsCode"]
        self.assertIn("stage_mode", webhook_code)
        self.assertIn("stage_mode", parse_code)
        self.assertIn("url_picked", parse_code)
        self.assertIn("pickedUrl ? 'url_picked' : 'skipped'", parse_code)
        self.assertNotIn("'processing') : 'skipped'", parse_code)
        self.assertIn("status,eq,url_picked", enrichment_url)
        self.assertNotIn("status,eq,processing", enrichment_url)
        self.assertIn("=== 'url_picked'", rows_to_enrichment_code)
        self.assertIn("Hard stage boundary", continue_code)
        self.assertIn("return []", continue_code)
        self.assertEqual(workflow["connections"]["Patch URL Picked"]["main"], [[]])
        self.assertEqual(workflow["connections"]["Continue URL Pick Patch"]["main"], [[]])


if __name__ == "__main__":
    unittest.main()
