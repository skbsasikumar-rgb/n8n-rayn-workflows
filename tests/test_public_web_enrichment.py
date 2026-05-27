import json
import os
import sys
import types
import unittest
from unittest import mock

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
    captcha_solver._detect_captcha_type = lambda html: None
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

    def test_nav_first_crawl_keeps_non_standard_header_links(self):
        homepage = "https://company.example/"
        links = [
            {"href": "https://company.example/our-story", "text": "Our Story", "source": "nav"},
            {"href": "https://company.example/what-we-do", "text": "What We Do", "source": "nav"},
            {"href": "https://company.example/programmes", "text": "Programmes", "source": "nav"},
            {"href": "https://company.example/login", "text": "Client Login", "source": "nav"},
            {"href": "https://company.example/news/latest", "text": "Latest News", "source": "nav"},
        ]
        selected = p.choose_candidate_pages(homepage, links, [], page_limit=5, profile="non_hia")
        self.assertEqual(selected[0], homepage)
        self.assertIn("https://company.example/our-story", selected)
        self.assertIn("https://company.example/what-we-do", selected)
        self.assertIn("https://company.example/programmes", selected)
        self.assertNotIn("https://company.example/login", selected)
        self.assertNotIn("https://company.example/news/latest", selected)

    def test_extract_page_artifact_marks_header_dropdown_links_as_nav(self):
        html = """
        <html><head><title>Example</title></head><body>
          <header>
            <nav>
              <ul>
                <li><a href="/our-story">Our Story</a></li>
                <li><button>Services</button><div><a href="/what-we-do">What We Do</a></div></li>
              </ul>
            </nav>
          </header>
          <footer><a href="/privacy">Privacy</a></footer>
          <main><h1>Example</h1><p>Primary healthcare advisory and support.</p></main>
        </body></html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://company.example/",
                "redirected_url": "https://company.example/",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Example"},
                "status_code": 200,
            }
        )
        link_sources = {item["href"]: item.get("source") for item in artifact.internal_link_items}
        self.assertEqual(link_sources["https://company.example/our-story"], "nav")
        self.assertEqual(link_sources["https://company.example/what-we-do"], "nav")
        self.assertEqual(link_sources["https://company.example/privacy"], "footer")

    def test_extract_page_artifact_keeps_content_when_body_theme_classes_include_noise_terms(self):
        html = """
        <html>
          <head><title>Our Services</title></head>
          <body class="et_pb_footer_columns4 et_header_style_left et_no_sidebar">
            <div id="main-content">
              <article class="page">
                <div class="entry-content">
                  <p>At Muhammadiyah Health & Day Care Centre we provide compassionate elderly care and rehabilitation support.</p>
                  <p>Our dedicated nursing team provides essential medical and personal care tailored to each client's needs.</p>
                </div>
              </article>
            </div>
          </body>
        </html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://mhcc.example/our-services",
                "redirected_url": "https://mhcc.example/our-services",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Our Services"},
                "status_code": 200,
            }
        )
        self.assertIn("compassionate elderly care", artifact.text)
        self.assertIn("dedicated nursing team", artifact.text)
        self.assertGreaterEqual(len(artifact.blocks), 2)

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
        self.assertIn("https://clinic.example/our-services", selected)

    def test_fast_hia_fallback_includes_dropdown_service_hubs(self):
        selected = p.choose_candidate_pages(
            "https://clinic.example/",
            [],
            [],
            page_limit=8,
            profile="hia",
            stage="fast",
        )

        self.assertIn("https://clinic.example/our-services", selected)

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

    def test_bare_captcha_feature_flag_is_not_challenge(self):
        html = """
        <html><head><title>Amazing Hearing</title></head><body>
        <nav>
          <a href="/about-us">About Us</a>
          <a href="/services">Services</a>
          <a href="/contact-us">Contact Us</a>
          <a href="/locations">Locations</a>
          <a href="/hearing-aids">Hearing Aids</a>
        </nav>
        <h1>Amazing Hearing</h1>
        <p>We provide hearing aid services across Singapore with multiple clinic locations and hearing care support.</p>
        <script>window.__WIX_FEATURES__=[\"captcha\",\"clickHandlerRegistrar\",\"businessLogger\"];</script>
        </body></html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://www.amazinghearing.com/",
                "redirected_url": "https://www.amazinghearing.com/",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Amazing Hearing"},
                "status_code": 200,
            }
        )
        self.assertEqual(artifact.challenge_hints, [])
        self.assertFalse(artifact.challenge_or_error)

    def test_recaptcha_widget_on_content_page_is_not_challenge(self):
        html = """
        <html><head><title>Home - Clinic Example</title></head><body>
        <nav>
          <a href="/about-us">About Us</a>
          <a href="/services">Services</a>
          <a href="/contact-us">Contact Us</a>
        </nav>
        <h1>Clinic Example</h1>
        <p>Our doctors provide endocrinology, diabetes, thyroid, screening, and nutrition services in Singapore.</p>
        <p>Book an appointment through our contact form below.</p>
        <form><div class="g-recaptcha" data-sitekey="site-key"></div></form>
        <script src="https://www.google.com/recaptcha/api.js"></script>
        </body></html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://clinic.example/",
                "redirected_url": "https://clinic.example/",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Home - Clinic Example"},
                "status_code": 200,
            }
        )
        self.assertEqual(artifact.challenge_hints, [])
        self.assertFalse(artifact.challenge_or_error)

    def test_recaptcha_gate_on_thin_page_still_counts_as_challenge(self):
        html = """
        <html><head><title>Security Check</title></head><body>
        <p>Complete the security check and verify you are human.</p>
        <div class=\"g-recaptcha\" data-sitekey=\"site-key\"></div>
        <script>if (typeof grecaptcha !== 'undefined') { grecaptcha.render('captcha'); }</script>
        </body></html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://clinic.example/",
                "redirected_url": "https://clinic.example/",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "Security Check"},
                "status_code": 200,
            }
        )
        self.assertIn("captcha", artifact.challenge_hints)
        self.assertTrue(artifact.challenge_or_error)

    def test_canonical_root_url_rejects_public_webmail_host(self):
        result = p.canonical_root_url("https://gmail.com")
        self.assertEqual(result.best_url, "")
        self.assertIn("clearly not an organization website", result.reason)

    def test_canonical_root_url_preserves_valid_landing_page_path(self):
        result = p.canonical_root_url("https://cavenaghmedical.page/hsg")
        self.assertEqual(result.best_url, "https://cavenaghmedical.page/hsg")
        self.assertEqual(result.registered_domain, "cavenaghmedical.page")

    def test_validation_variants_try_deep_path_before_same_domain_root(self):
        self.assertEqual(
            p.validation_variants("https://clinic.example/locations/bishan"),
            [
                "https://clinic.example/locations/bishan",
                "http://clinic.example/locations/bishan",
                "https://clinic.example/",
                "http://clinic.example/",
            ],
        )

    def test_page_artifact_uses_meta_description_and_nav_links_when_text_is_empty(self):
        html = """
        <html>
        <head>
          <title>AspenHealth</title>
          <meta name="description" content="AspenHealth is a management consulting firm focused on primary healthcare advisory, training, talent recruitment, pharmacy management and strategic resourcing.">
        </head>
        <body>
          <nav>
            <a href="/our-story">Our Story</a>
            <a href="/services">Services</a>
            <a href="/contact-us">Contact Us</a>
          </nav>
        </body>
        </html>
        """
        artifact = p.extract_page_artifact(
            {
                "url": "https://aspenhealth.sg/",
                "redirected_url": "https://aspenhealth.sg/",
                "html": html,
                "cleaned_html": html,
                "metadata": {"title": "AspenHealth"},
                "status_code": 200,
            }
        )
        self.assertIn("primary healthcare advisory", artifact.text)
        self.assertIn("Services", artifact.text)
        self.assertEqual(p.homepage_content_quality(artifact), "adequate")

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

    def test_sparse_homepage_completes_with_quality_reason(self):
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
        self.assertEqual(status, "adequate")
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
        self.assertEqual(status, "adequate")
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
        self.assertEqual(status, "adequate")
        self.assertEqual(reason, "thin_content")

    def test_deep_retry_thin_homepage_with_team_pages_can_pass(self):
        homepage = self.page(
            "https://amber-pharmacy.example/",
            "Compounding pharmacy Singapore",
            "homepage",
            title="Amber Compounding Pharmacy",
        )
        homepage.internal_link_items = [
            {"href": "https://amber-pharmacy.example/meet-our-team", "text": "Meet Our Team"},
            {"href": "https://amber-pharmacy.example/contact", "text": "Contact Us"},
        ]
        team = self.page(
            "https://amber-pharmacy.example/meet-our-team",
            "Our pharmacy team supports compounding and patient care in Singapore. " * 12,
            "team",
        )
        profile = self.page(
            "https://amber-pharmacy.example/team/cher-kai-wen",
            "Cher Kai Wen is part of the compounding pharmacy team in Singapore. " * 10,
            "doctor_profile",
        )
        status, reason = p.classify_enrichment_depth(
            [homepage, team, profile],
            services=[],
            locations=["Singapore"],
            leadership_signals=["Cher Kai Wen"],
            organization_type="Unknown",
            errors=[],
            stage="deep_retry",
        )
        self.assertEqual(status, "adequate")
        self.assertEqual(reason, "thin_content")

    def test_single_page_specialty_clinic_without_services_can_pass(self):
        homepage = self.page(
            "https://aaro.example/",
            "Radiation oncology clinic Singapore at Mount Elizabeth Novena.",
            "homepage",
            title="Asian Alliance Radiation & Oncology",
        )
        homepage.meta_description = (
            "Radiation oncology and specialist cancer care in Singapore with appointments at Mount Elizabeth Novena."
        )
        homepage.internal_link_items = [
            {"href": "https://aaro.example/contact", "text": "Contact Us"},
            {"href": "https://aaro.example/location", "text": "Our Location"},
        ]
        status, reason = p.classify_enrichment_depth(
            [homepage],
            services=[],
            locations=["Mount Elizabeth Novena"],
            leadership_signals=[],
            organization_type="Unknown",
            errors=[],
            stage="deep_retry",
        )
        self.assertEqual(status, "adequate")
        self.assertEqual(reason, "")

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

    def test_contact_links_count_for_deep_retry_sufficiency(self):
        homepage = self.page(
            "https://aspenhealth.sg/",
            (
                "AspenHealth is a management consulting firm focused on primary healthcare advisory "
                "and pharmacy management. " * 12
            ),
            "homepage",
            title="AspenHealth",
        )
        homepage.internal_link_items = [
            {"href": "https://aspenhealth.sg/services", "text": "Services"},
            {"href": "https://aspenhealth.sg/contact-us", "text": "Contact Us"},
        ]
        privacy = self.page("https://aspenhealth.sg/privacy-policy", "privacy policy personal data protection", "privacy_pdpa")
        status, reason = p.classify_enrichment_depth(
            [homepage, privacy],
            services=["primary healthcare advisory"],
            locations=[],
            leadership_signals=[],
            organization_type="Unknown",
            errors=[],
            stage="deep_retry",
        )
        self.assertEqual(status, "adequate")
        self.assertEqual(reason, "")

    def test_workflow_public_enrich_controls_are_bounded(self):
        workflow = json.loads(open("wf-worker.json", encoding="utf-8").read())
        nodes = {node["name"]: node for node in workflow["nodes"]}
        prepare_code = nodes["Prepare Public Enrichment"]["parameters"]["jsCode"]
        self.assertIn("enrichment_stage", prepare_code)
        self.assertIn("weak_retry", prepare_code)
        self.assertIn("page_limit: stage === 'deep_retry' ? 12 : 8", prepare_code)
        self.assertNotIn("? 14 : 8", prepare_code)
        self.assertIn("page_timeout_ms: stage === 'deep_retry' ? 20000 : 15000", prepare_code)
        self.assertIn("per_row_page_concurrency: stage === 'deep_retry' ? 2 : 2", prepare_code)
        self.assertIn("row_timeout_seconds: stage === 'deep_retry' ? 210 : 120", prepare_code)
        self.assertIn("allow_low_limits: false", prepare_code)
        http_node = nodes["Crawl4AI Public Enrich"]
        self.assertEqual(http_node["parameters"]["options"]["timeout"], 420000)
        self.assertNotIn("retryOnFail", http_node)
        patch_code = nodes["Prepare Enrichment Patch"]["parameters"]["jsCode"]
        self.assertIn("isTransportTimeout", patch_code)
        self.assertIn("status: 'failed_retryable'", patch_code)
        self.assertIn("status_reason: 'enrichment_transport_timeout'", patch_code)
        self.assertIn("NOCO_LONG_TEXT_LIMIT = 95000", patch_code)
        self.assertIn("compactStructuredData", patch_code)
        self.assertIn("capNocoLongTextFields(patch)", patch_code)

    def test_fast_public_enrichment_uses_static_first(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn('PUBLIC_ENRICH_FAST_STATIC_FIRST", "true"', source)
        self.assertIn('PUBLIC_ENRICH_FAST_BROWSER_FALLBACK", "false"', source)
        self.assertIn('PUBLIC_ENRICH_FAST_CHALLENGE_RECOVERY", "true"', source)
        self.assertIn("homepage_static_ms", source)
        self.assertIn("PUBLIC_WEB_STATIC_READ_TIMEOUT_SECONDS", source)

    def test_challenge_recovery_uses_browserless_and_2captcha_controls(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn("def browserless_ws_endpoint", source)
        self.assertIn('if crawler is None:', source)
        self.assertIn("BROWSERLESS_WS_URL", source)
        self.assertIn("BROWSERLESS_TOKEN", source)
        self.assertIn("BROWSERLESS_PROXY", source)
        self.assertIn('use_browserless_cdp = bool(endpoint) and not proxy_config', source)
        self.assertIn("proxy_config_for_url(best_url, force=True)", source)
        self.assertIn('reason: str = "challenge_browser_recovery"', source)
        self.assertIn('reason="homepage_challenge_browser_recovery"', source)
        self.assertIn("PUBLIC_ENRICH_CHALLENGE_BROWSER_FALLBACK", source)
        self.assertIn("PUBLIC_ENRICH_CHALLENGE_STEALTH", source)
        self.assertIn("apply_browser_stealth", source)
        self.assertIn("connect_over_cdp", source)
        self.assertIn("captcha_solver.solve_page_captcha", source)
        self.assertIn("challenge_browser_recovery", source)
        requirements = open("services/crawl4ai/requirements.txt", encoding="utf-8").read()
        self.assertIn("playwright-stealth==2.0.3", requirements)

    def test_deep_retry_browser_recovery_targets_empty_homepages(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn('if stage == "deep_retry" and quality in {"empty", "thin"}', source)
        self.assertIn('reason="homepage_browser_recovery"', source)
        self.assertIn('len(browser_page.text or "") > len(homepage_page.text or "")', source)

    def test_deep_retry_browser_recovery_targets_high_value_candidate_pages(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn("browser_candidate_recovery_urls = {", source)
        self.assertIn('for candidate_url in candidates[1:5]', source)
        self.assertIn('reason="candidate_browser_recovery"', source)
        self.assertIn('candidate_url in browser_candidate_recovery_urls', source)

    def test_candidate_subpages_use_bounded_concurrency(self):
        source = open("services/crawl4ai/public_web_enrichment.py", encoding="utf-8").read()
        self.assertIn("async def crawl_candidate_page", source)
        self.assertIn("len(batch) < per_row_page_concurrency", source)
        self.assertIn("await asyncio.gather", source)
        self.assertIn("if crawler is None:", source)
        self.assertIn("candidate_static_ms", source)

    def test_fast_stage_defaults_to_static_transport(self):
        source = open("services/crawl4ai/app.py", encoding="utf-8").read()
        self.assertIn("use_static_transport = (", source)
        self.assertIn('PUBLIC_ENRICH_FALLBACK_RESERVE_SECONDS", "60"', source)
        self.assertIn("fallback_limit = min(4, effective_page_limit)", source)
        self.assertIn("static_only=True", source)
        self.assertIn('PUBLIC_ENRICH_FAST_BROWSER_PRIMARY", "false"', source)
        self.assertIn('PUBLIC_ENRICH_DEEP_BROWSER_PRIMARY", "false"', source)
        self.assertIn('PUBLIC_ENRICH_DEEP_STATIC_FIRST"', source)
        self.assertIn("page_limit=min(max(1, request.page_limit), max_pages)", source)
        self.assertIn("PUBLIC_ENRICH_FORCE_BROWSER_KEY", source)
        self.assertIn("public_enrich_needs_browser_retry", source)
        self.assertIn("browser_retry_after_static_validation_warning", source)
        self.assertIn("force_browser_primary=bool", source)
        self.assertIn("not force_browser_primary", source)
        self.assertIn("normalized = public_enrichment.canonical_root_url(url_picked)", source)
        self.assertIn('"best_url": normalized.best_url', source)

    def test_workflow_url_only_mode_does_not_enter_public_enrichment(self):
        workflow = json.loads(open("wf-worker.json", encoding="utf-8").read())
        nodes = {node["name"]: node for node in workflow["nodes"]}
        webhook_code = nodes["Webhook To Item"]["parameters"]["jsCode"]
        parse_code = nodes["Parse URL Pick"]["parameters"]["jsCode"]
        enrichment_url = nodes["Get Enrichment Rows"]["parameters"]["url"]
        rows_to_enrichment_code = nodes["Rows To Enrichment Items"]["parameters"]["jsCode"]
        self.assertNotIn("Continue URL Pick Patch", nodes)
        self.assertIn("stage_mode", webhook_code)
        self.assertIn("stage_mode", parse_code)
        self.assertIn("url_picked", parse_code)
        self.assertIn("pickedUrl ? 'url_picked' : 'skipped'", parse_code)
        self.assertNotIn("'processing') : 'skipped'", parse_code)
        self.assertIn("status,eq,url_picked", enrichment_url)
        self.assertIn("status,eq,processing", enrichment_url)
        self.assertIn("manual_url_override,notblank", enrichment_url)
        self.assertIn("status_reason,eq,no_official_url_found", enrichment_url)
        self.assertIn("manual_url_override", enrichment_url)
        self.assertIn("retry_failed", enrichment_url)
        self.assertIn("status,eq,failed_retryable", enrichment_url)
        self.assertIn("retry_eligible,eq,true", enrichment_url)
        self.assertIn("isStaleProcessing(row)", rows_to_enrichment_code)
        self.assertIn("status === 'url_picked'", rows_to_enrichment_code)
        self.assertIn("status === 'failed_retryable'", rows_to_enrichment_code)
        self.assertIn("isManualUrlOverride", rows_to_enrichment_code)
        self.assertIn("normalizeManualUrl", rows_to_enrichment_code)
        self.assertIn("manual_url_override: manualUrl", rows_to_enrichment_code)
        self.assertEqual(workflow["connections"]["Patch URL Picked"]["main"], [[]])

    def test_workflow_keeps_sparse_successes_completed(self):
        workflow = json.loads(open("wf-worker.json", encoding="utf-8").read())
        nodes = {node["name"]: node for node in workflow["nodes"]}
        patch_code = nodes["Prepare Enrichment Patch"]["parameters"]["jsCode"]
        prepare_code = nodes["Prepare Public Enrichment"]["parameters"]["jsCode"]
        rerun_helper = open("scripts/rayn_selected_rerun.py", encoding="utf-8").read()
        self.assertNotIn("if (depth === 'weak_retry_needed') return 'url_picked'", patch_code)
        self.assertIn("enrichment_completed_${weakReason}", patch_code)
        self.assertIn("statusReason.includes('thin_content')", prepare_code)
        self.assertIn("row.homepage_root_url || row.best_url || row.url_picked", prepare_code)
        self.assertIn("matched_url: matchedUrl", prepare_code)
        self.assertIn("row.status_reason, row.error_type", prepare_code)
        self.assertIn("const retryEscalates = attemptCount > 1 && !statusReason.includes('enrichment_timeout')", prepare_code)
        self.assertIn("retryEscalates", prepare_code)
        self.assertIn("status === 'failed_retryable' && isTransportTimeout", patch_code)
        self.assertIn("finalStatus === 'failed_retryable'", patch_code)
        self.assertIn("RAYN_MAX_ENRICHMENT_ATTEMPTS", patch_code)
        self.assertIn("maxAttemptsReached ? 'enrichment_timeout_max_attempts'", patch_code)
        self.assertIn('"enrichment_stage": enrichment_stage', rerun_helper)
        self.assertIn('enrichment_stage = "deep_retry" if should_deep_retry else "fast"', rerun_helper)
        self.assertIn('"enrichment_timeout" not in prior_reason', rerun_helper)
        self.assertIn("or retry_escalates", rerun_helper)
        self.assertIn('resolved_status in {"failed", "failed_retryable"}', rerun_helper)
        self.assertIn("max_enrichment_attempts", rerun_helper)
        self.assertIn('"enrichment_timeout_max_attempts" if max_attempts_reached', rerun_helper)
        self.assertIn("or url_only_content", rerun_helper)
        self.assertIn('str(row.get("status") or "") == "completed"', rerun_helper)
        self.assertIn("website_content,website_scrape", rerun_helper)
        self.assertIn("homepage_root_url,canonical_domain", rerun_helper)
        self.assertIn("NOCO_LONG_TEXT_LIMIT = 95_000", rerun_helper)
        self.assertIn("cap_noco_long_text_fields(patch)", rerun_helper)

    def test_selected_rerun_detects_url_only_content_for_deep_retry(self):
        from scripts import rayn_selected_rerun as rerun

        self.assertTrue(rerun.content_is_url_only("https://www.advantagemedical.sg/", "https://www.advantagemedical.sg/"))
        self.assertFalse(rerun.content_is_url_only("# Advantage Medical\nUseful clinic content.", "https://www.advantagemedical.sg/"))
        self.assertFalse(rerun.content_is_url_only("https://unrelated.example/", "https://www.advantagemedical.sg/"))

    def test_selected_rerun_keeps_enrichment_timeout_retryable(self):
        from scripts import rayn_selected_rerun as rerun

        patch = {
            "last_stage": "enrichment_error",
            "last_error": "public_enrich_timeout_after_360s",
            "best_url": "https://clinic.example/",
        }

        self.assertEqual(rerun.terminal_status(patch), "failed_retryable")
        self.assertEqual(rerun.status_reason("failed_retryable", patch), "enrichment_timeout")

    def test_selected_rerun_uses_default_max_enrichment_attempts(self):
        from scripts import rayn_selected_rerun as rerun

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(rerun.max_enrichment_attempts(), 4)

    def test_selected_rerun_caps_oversized_nocodb_longtext_fields(self):
        from scripts import rayn_selected_rerun as rerun

        patch = {
            "structured_data_detected": json.dumps({"has_json_ld": True, "schema_types": ["MedicalClinic"], "sitemap_urls": ["x" * 6000] * 30}),
            "website_content": "a" * 120000,
            "website_scrape": "b" * 120000,
            "notes": "c" * 8000,
            "last_error": "d" * 8000,
        }
        rerun.cap_noco_long_text_fields(patch)

        self.assertLessEqual(len(patch["structured_data_detected"]), rerun.NOCO_LONG_TEXT_LIMIT)
        self.assertLessEqual(len(patch["website_content"]), rerun.NOCO_LONG_TEXT_LIMIT)
        self.assertLessEqual(len(patch["website_scrape"]), rerun.NOCO_LONG_TEXT_LIMIT)
        self.assertLessEqual(len(patch["notes"]), 4000)
        self.assertLessEqual(len(patch["last_error"]), 4000)
        structured = json.loads(patch["structured_data_detected"])
        self.assertTrue(structured["truncated_for_nocodb_longtext"])

    def test_selected_rerun_consolidates_same_run_duplicate_domains(self):
        from scripts import rayn_selected_rerun as rerun

        original_fetch_rows = rerun.fetch_rows
        original_patch = rerun.api.noco_patch
        patches = []
        rows = [
            {"Id": 305, "status": "url_picked", "canonical_domain": "theclinicgroup.com.sg"},
            {"Id": 309, "status": "url_picked", "canonical_domain": "theclinicgroup.com.sg"},
            {"Id": 310, "status": "url_picked", "canonical_domain": "onegeorgeclinic.sg"},
        ]
        try:
            rerun.fetch_rows = lambda ids: rows
            rerun.api.noco_patch = lambda payload: patches.extend(payload)

            result = rerun.consolidate_duplicate_canonical_rows([305, 309, 310], dry_run=False)
        finally:
            rerun.fetch_rows = original_fetch_rows
            rerun.api.noco_patch = original_patch

        self.assertEqual(result["duplicates_skipped"], 1)
        self.assertEqual(result["duplicate_ids"], [309])
        self.assertEqual(patches[0]["duplicate_of_id"], 305)
        self.assertEqual(patches[0]["status"], "skipped")
        self.assertEqual(patches[0]["status_reason"], "duplicate_canonical_domain")

    def test_public_enrichment_patch_caps_oversized_nocodb_longtext_fields(self):
        record = p.EnrichmentRecord(
            row_id="999",
            company_name="Long Text Clinic",
            url_picked="https://clinic.example/",
            best_url="https://clinic.example/",
            crawl_status="crawled",
            pages_crawled_count=1,
            pages_crawled_urls=["https://clinic.example/"],
            title="Long Text Clinic",
            meta_description="",
            organization_name_detected="Long Text Clinic",
            organization_type_guess="Medical clinic",
            solo_or_group_guess="solo",
            parent_or_affiliation_signals=[],
            size_signals={},
            industry_guess="healthcare",
            services_detected=[],
            locations_detected=[],
            contact_info_detected={},
            leadership_or_team_signals=[],
            social_links=[],
            structured_data_detected={"has_json_ld": True, "schema_types": ["MedicalClinic"], "sitemap_urls": ["x" * 6000] * 30},
            enrichment_notes="",
            confidence_score=0.8,
            error_notes=["e" * 8000],
            best_url_candidate="https://clinic.example/",
            http_status=200,
            redirect_chain=[],
            url_validation_status="ok",
            company_homepage_name="Long Text Clinic",
            company_homepage_name_evidence=[],
            parent_company="",
            parent_company_relationship="",
            parent_company_evidence=[],
            parent_company_confidence="",
            affiliations_detected=[],
            rejected_parent_candidates=[],
            parent_company_candidates_json=[],
            website_scrape="a" * 120000,
            enrichment_depth_status="",
            weak_enrichment_reason="",
            homepage_content_quality="",
        )
        patch = p.build_noco_patch(record)

        self.assertLessEqual(len(patch["website_content"]), p.NOCO_LONG_TEXT_LIMIT)
        self.assertLessEqual(len(patch["website_scrape"]), p.NOCO_LONG_TEXT_LIMIT)
        self.assertLessEqual(len(patch["structured_data_detected"]), p.NOCO_LONG_TEXT_LIMIT)
        self.assertLessEqual(len(patch["last_error"]), 4000)
        structured = json.loads(patch["structured_data_detected"])
        self.assertTrue(structured["truncated_for_nocodb_longtext"])

    def test_url_validation_warning_allows_same_domain_403(self):
        normalization = p.NormalizationResult(
            best_url="https://clinic.example/",
            hostname="clinic.example",
            registered_domain="clinic.example",
        )
        validation = p.UrlValidationResult(
            best_url_candidate="https://clinic.example/",
            best_url="https://clinic.example/",
            http_status=403,
            redirect_chain=[{"url": "https://clinic.example/", "status": 403}],
            url_validation_status="failed_http_status",
            error="final HTTP status 403 is not crawlable",
        )

        self.assertTrue(p.can_continue_after_url_validation_warning(validation, normalization))

    def test_url_validation_warning_allows_same_domain_redirect_loop(self):
        normalization = p.NormalizationResult(
            best_url="https://dermassoc.com.sg/wp/",
            hostname="dermassoc.com.sg",
            registered_domain="dermassoc.com.sg",
        )
        validation = p.UrlValidationResult(
            best_url_candidate="https://dermassoc.com.sg/wp/",
            best_url="https://dermassoc.com.sg/wp/",
            http_status=0,
            redirect_chain=[
                {"url": "https://dermassoc.com.sg/wp/", "status": 301, "location": "/wp/"},
            ],
            url_validation_status="failed_redirect_loop",
            error="redirect loop detected",
        )

        self.assertTrue(p.can_continue_after_url_validation_warning(validation, normalization))

    def test_url_validation_warning_allows_ssl_browser_retry(self):
        normalization = p.NormalizationResult(
            best_url="https://clinic.example/",
            hostname="clinic.example",
            registered_domain="clinic.example",
        )
        validation = p.UrlValidationResult(
            best_url_candidate="https://clinic.example/",
            best_url="https://clinic.example/",
            http_status=0,
            redirect_chain=[],
            url_validation_status="failed_request_error",
            error="ssl_error: certificate verify failed",
        )

        self.assertTrue(p.can_continue_after_url_validation_warning(validation, normalization))
        self.assertTrue(p.proxy_retryable_error(validation.error))

    def test_validation_variants_preserve_explicit_http_first(self):
        self.assertEqual(
            p.validation_variants("http://clinic.example/")[:2],
            ["http://clinic.example/", "https://clinic.example/"],
        )

    def test_url_validation_warning_allows_github_pages_custom_domain_redirect(self):
        normalization = p.NormalizationResult(
            best_url="http://clinic.example/",
            hostname="clinic.example",
            registered_domain="clinic.example",
        )
        validation = p.UrlValidationResult(
            best_url_candidate="http://clinic.example/",
            best_url="http://clinic.example/",
            http_status=301,
            redirect_chain=[
                {"url": "http://clinic.example/", "status": 301, "location": "https://owner.github.io/"}
            ],
            url_validation_status="failed_cross_domain_redirect",
            error="redirect left the original registered domain: owner.github.io",
        )

        self.assertTrue(p.can_continue_after_url_validation_warning(validation, normalization))

    def test_url_validation_warning_rejects_cross_domain_and_not_found(self):
        normalization = p.NormalizationResult(
            best_url="https://clinic.example/",
            hostname="clinic.example",
            registered_domain="clinic.example",
        )
        cross_domain = p.UrlValidationResult(
            best_url_candidate="https://clinic.example/",
            best_url="https://unrelated.example/",
            http_status=403,
            redirect_chain=[],
            url_validation_status="failed_http_status",
            error="final HTTP status 403 is not crawlable",
        )
        not_found = p.UrlValidationResult(
            best_url_candidate="https://clinic.example/",
            best_url="https://clinic.example/",
            http_status=404,
            redirect_chain=[],
            url_validation_status="failed_http_status",
            error="final HTTP status 404 is not crawlable",
        )

        self.assertFalse(p.can_continue_after_url_validation_warning(cross_domain, normalization))
        self.assertFalse(p.can_continue_after_url_validation_warning(not_found, normalization))


if __name__ == "__main__":
    unittest.main()
