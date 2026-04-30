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
            ("Clinic is accredited by CHAS.", "CHAS"),
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


if __name__ == "__main__":
    unittest.main()
