import json
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
    captcha_solver.is_configured = lambda: False
    captcha_solver._detect_captcha_type = lambda *args, **kwargs: False
    sys.modules["captcha_solver"] = captcha_solver

from services.crawl4ai import public_web_enrichment as p


def page_with_blocks(*blocks: str) -> p.PageArtifact:
    return p.PageArtifact(
        url="https://exampleclinic.sg/about",
        title="About Example Clinic",
        meta_description="",
        blocks=list(blocks),
        text="\n".join(blocks),
    )


class ParentCompanyExtractionTests(unittest.TestCase):
    def verify(self, *blocks: str) -> p.ParentCompanyVerification:
        with patch.dict(os.environ, {"PARENT_COMPANY_LLM_VERIFIER_ENABLED": "false"}, clear=False):
            return p.detect_parent_company(
                [page_with_blocks(*blocks)],
                "Example Clinic",
                company_name="Example Clinic",
                canonical_domain="exampleclinic.sg",
                best_url="https://exampleclinic.sg/",
            )

    def test_accepts_true_parent_operator_group_relationships(self):
        cases = [
            ("Example Clinic is part of Qualitas Health.", "Qualitas Health", "clinic_network"),
            ("Example Clinic is operated by Fullerton Health.", "Fullerton Health", "operator"),
            ("Example Medical is a subsidiary of Raffles Medical Group.", "Raffles Medical Group", "subsidiary_of"),
            ("Example Clinic is managed by OneCare Medical.", "OneCare Medical", "managed_by"),
        ]
        for text, expected_parent, expected_relationship in cases:
            with self.subTest(text=text):
                result = self.verify(text)
                self.assertEqual(result.parent_company, expected_parent)
                self.assertEqual(result.relationship_type, expected_relationship)
                self.assertIn(result.confidence, {"High", "Medium"})
                self.assertEqual(result.evidence, [text])

    def test_rejects_weak_affiliations_as_parent(self):
        cases = [
            ("Our doctors are members of the Singapore Medical Association.", "Singapore Medical Association"),
            ("Dr Tan completed residency at National University Hospital.", "National University Hospital"),
            ("Dr Tan is a Fellow of the Academy of Medicine Singapore.", ""),
            ("Clinic is accredited by CHAS.", ""),
            ("Located at Mount Elizabeth Medical Centre.", "Mount Elizabeth Medical Centre"),
            ("Our website is powered by Example Vendor.", "Example Vendor"),
        ]
        for text, expected_affiliation in cases:
            with self.subTest(text=text):
                result = self.verify(text)
                self.assertEqual(result.parent_company, "")
                if expected_affiliation:
                    names = {item["name"] for item in result.affiliations}
                    self.assertIn(expected_affiliation, names)

    def test_rejects_ambiguous_group_language(self):
        result = self.verify("Example Clinic is part of our network of clinics.")
        self.assertEqual(result.parent_company, "")
        self.assertEqual(result.candidates, [])

        result = self.verify("Example Clinic is an affiliate clinic of Example Hospital.")
        self.assertEqual(result.parent_company, "")
        self.assertIn("Example Hospital", {item["name"] for item in result.affiliations})

    def test_rejects_public_programmes_and_care_networks_as_parent_company(self):
        cases = [
            "We are Now under the Primary Care Network (PCN).",
            "Our clinic is now officially one of the Healthier SG clinics under the national initiative by the Ministry of Health (MOH).",
            "We are a participating clinic in the HPV Immunisation Programme.",
            "Clinic is part of the Community Health Assist Scheme.",
        ]
        for text in cases:
            with self.subTest(text=text):
                result = self.verify(text)
                self.assertEqual(result.parent_company, "")

    def test_part_of_requires_known_private_healthcare_group(self):
        accepted = self.verify("Example Clinic is part of Qualitas Health.")
        self.assertEqual(accepted.parent_company, "Qualitas Health")
        self.assertEqual(accepted.relationship_type, "clinic_network")

        rejected = self.verify("Example Clinic is part of Example Community Network.")
        self.assertEqual(rejected.parent_company, "")

    def test_schema_parent_still_works_when_llm_disabled(self):
        page = page_with_blocks("About Example Clinic")
        page.structured_data = [{"parentOrganization": {"name": "Fullerton Health"}}]
        with patch.dict(os.environ, {"PARENT_COMPANY_LLM_VERIFIER_ENABLED": "false"}, clear=False):
            result = p.detect_parent_company(
                [page],
                "Example Clinic",
                company_name="Example Clinic",
                canonical_domain="exampleclinic.sg",
                best_url="https://exampleclinic.sg/",
            )
        self.assertEqual(result.parent_company, "Fullerton Health")
        self.assertEqual(result.relationship_type, "parent")

    def test_llm_cannot_invent_parent_company(self):
        page = page_with_blocks("Example Clinic is operated by Fullerton Health.")
        fake = {
            "accepted_parent": {
                "name": "Invented Parent Group",
                "relationship_type": "parent",
                "confidence": "High",
                "evidence_quote": "Example Clinic is operated by Fullerton Health.",
                "reason": "bad",
            },
            "affiliations": [],
            "rejected_candidates": [],
        }
        with patch.dict(
            os.environ,
            {
                "PARENT_COMPANY_LLM_VERIFIER_ENABLED": "true",
                "PARENT_COMPANY_LLM_VERIFIER_FAKE_RESPONSE": json.dumps(fake),
            },
            clear=False,
        ):
            result = p.detect_parent_company(
                [page],
                "Example Clinic",
                company_name="Example Clinic",
                canonical_domain="exampleclinic.sg",
                best_url="https://exampleclinic.sg/",
            )
        self.assertEqual(result.parent_company, "Fullerton Health")
        self.assertIn("candidate_not_in_input", {item.get("reason_code") for item in result.rejected_candidates})

    def test_llm_quote_must_exist_in_crawl_text(self):
        page = page_with_blocks("Example Clinic is operated by Fullerton Health.")
        fake = {
            "accepted_parent": {
                "name": "Fullerton Health",
                "relationship_type": "operator",
                "confidence": "High",
                "evidence_quote": "Example Clinic is owned by Fullerton Health.",
                "reason": "quote was changed",
            },
            "affiliations": [],
            "rejected_candidates": [],
        }
        with patch.dict(
            os.environ,
            {
                "PARENT_COMPANY_LLM_VERIFIER_ENABLED": "true",
                "PARENT_COMPANY_LLM_VERIFIER_FAKE_RESPONSE": json.dumps(fake),
            },
            clear=False,
        ):
            result = p.detect_parent_company(
                [page],
                "Example Clinic",
                company_name="Example Clinic",
                canonical_domain="exampleclinic.sg",
                best_url="https://exampleclinic.sg/",
            )
        self.assertEqual(result.parent_company, "Fullerton Health")
        self.assertIn("quote_not_found", {item.get("reason_code") for item in result.rejected_candidates})


class PublicCrawlSelectionTests(unittest.TestCase):
    def test_homepage_link_anchor_text_increases_follow_priority(self):
        selected = p.choose_candidate_pages(
            "https://exampleclinic.sg/",
            [
                {"href": "https://exampleclinic.sg/dr-tan", "text": "Meet our doctors"},
                {"href": "https://exampleclinic.sg/privacy-policy", "text": "Privacy policy"},
                {"href": "https://exampleclinic.sg/contact", "text": "Contact"},
            ],
            [],
            page_limit=3,
        )

        self.assertEqual(selected[0], "https://exampleclinic.sg/")
        self.assertIn("https://exampleclinic.sg/dr-tan", selected)
        self.assertIn("https://exampleclinic.sg/contact", selected)
        self.assertNotIn("https://exampleclinic.sg/privacy-policy", selected)

    def test_candidate_selection_uses_sitemap_urls_beyond_keyword_filter(self):
        selected = p.choose_candidate_pages(
            "https://exampleclinic.sg/",
            [],
            [
                "https://exampleclinic.sg/dental-implants",
                "https://exampleclinic.sg/our-dentists",
                "https://exampleclinic.sg/terms",
            ],
            page_limit=3,
        )

        self.assertIn("https://exampleclinic.sg/our-dentists", selected)
        self.assertIn("https://exampleclinic.sg/dental-implants", selected)
        self.assertNotIn("https://exampleclinic.sg/terms", selected)


if __name__ == "__main__":
    unittest.main()
