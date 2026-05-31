import unittest
from unittest.mock import patch

from services.crawl4ai import funding_programs as funding_module
from services.crawl4ai.funding_programs import (
    FundingProgram,
    PROGRAMMES,
    extract_ncss_member_names,
    fetch_ncss_member_directory,
    match_programmes,
    normalize_member_key,
)


def verified_cyber_essentials() -> FundingProgram:
    return FundingProgram(
        programme_id="verified_ce",
        programme_name="Cyber Essentials first successful certification support",
        framework_or_regime="Cyber Essentials",
        relevant_entity_types=["sme", "npo", "charity", "social_service"],
        relevant_industries=["all"],
        benefit_summary="Verified test route.",
        email_safe_claim_template="Based on the company profile, the Cyber Essentials support route appears worth checking for {{company_name}}.",
        do_not_claim=["guaranteed funding"],
        official_source_urls=["https://example.gov.sg/ce"],
        last_checked="2026-05-04",
        verification_status="verified_current",
        use_in_email_when="verified fixture",
        do_not_claim_when="not verified",
    )


class FundingProgramTests(unittest.TestCase):
    def test_npo_funding_email_does_not_say_if_npo(self):
        match = match_programmes(
            {
                "company_name": "Sree Narayana Mission",
                "entity_type_guess": "npo",
                "entity_type_confidence": "high",
                "recommended_first_cert": "Cyber Essentials",
            },
            programmes=[verified_cyber_essentials()],
        )
        self.assertEqual(match.funding_status, "verified_match")
        self.assertNotIn("if you are an NPO", match.funding_claim_line)
        self.assertIn("Sree Narayana Mission", match.funding_claim_line)

    def test_sme_funding_email_does_not_say_if_sme(self):
        match = match_programmes(
            {
                "company_name": "Example SME",
                "entity_type_guess": "sme",
                "entity_type_confidence": "high",
                "recommended_first_cert": "Cyber Essentials",
            },
            programmes=[verified_cyber_essentials()],
        )
        self.assertEqual(match.funding_status, "verified_match")
        self.assertNotIn("if you are an SME", match.funding_claim_line)
        self.assertIn("Example SME", match.funding_claim_line)

    def test_unknown_entity_type_marks_funding_needs_review(self):
        match = match_programmes(
            {
                "company_name": "Unknown Entity",
                "entity_type_guess": "unknown",
                "entity_type_confidence": "low",
                "recommended_first_cert": "Cyber Essentials",
            },
            programmes=[verified_cyber_essentials()],
        )
        self.assertEqual(match.funding_status, "needs_review")
        self.assertTrue(match.funding_human_review_required)
        self.assertEqual(match.funding_claim_line, "Funding route needs human review before use.")

    def test_unverified_source_cannot_be_verified_match(self):
        program = verified_cyber_essentials()
        program.verification_status = "needs_refresh"
        match = match_programmes(
            {
                "company_name": "Example SME",
                "entity_type_guess": "sme",
                "entity_type_confidence": "high",
                "recommended_first_cert": "Cyber Essentials",
            },
            programmes=[program],
        )
        self.assertEqual(match.funding_status, "possible_match")
        self.assertTrue(match.funding_human_review_required)

    def test_hia_cisoaas_route_allows_verified_70_percent_claim_for_clinic(self):
        match = match_programmes(
            {
                "company_name": "American International Clinic Singapore",
                "entity_type_guess": "clinic",
                "entity_type_confidence": "high",
                "hia_relevant": True,
                "hia_confidence": "high",
                "hia_service_type_guess": "GP_OMS",
                "recommended_first_cert": "Cyber Essentials",
                "website_content": "medical clinic doctors outpatient patient appointments Singapore",
            },
            programmes=PROGRAMMES,
        )
        self.assertEqual(match.funding_status, "verified_match")
        self.assertEqual(match.primary_funding_program, "CISO-as-a-Service for HIA Cybersecurity and Data Security Essentials")
        self.assertIn("up to 70% co-funding", match.funding_claim_line)
        self.assertIn("subject to programme confirmation", match.funding_claim_line)
        self.assertFalse(match.funding_human_review_required)

    def test_extract_ncss_member_names_from_maps_html(self):
        html = (
            r'\"mapMarkers\":[{\"name\":\"365 CANCER PREVENTION SOCIETY\"},'
            r'{\"name\":\"4S\"},{\"name\":\"CARITAS HUMANITARIAN AID \\u0026 RELIEF INITIATIVES\"}]'
        )

        names = extract_ncss_member_names(html)

        self.assertEqual(
            names,
            [
                "365 CANCER PREVENTION SOCIETY",
                "4S",
                "CARITAS HUMANITARIAN AID & RELIEF INITIATIVES",
            ],
        )

    @patch("services.crawl4ai.funding_programs.load_ncss_member_snapshot")
    @patch("services.crawl4ai.funding_programs.urlopen")
    def test_ncss_directory_fetch_falls_back_to_snapshot(self, urlopen, load_snapshot):
        funding_module._NCSS_MEMBER_CACHE = {"loaded_at": 0.0, "members": {}}
        urlopen.side_effect = OSError("blocked")
        load_snapshot.return_value = ["4S"]

        members = fetch_ncss_member_directory(ttl_seconds=0)

        self.assertEqual(members[normalize_member_key("4S")], "4S")

    @patch("services.crawl4ai.funding_programs.fetch_ncss_member_directory")
    def test_ncss_member_gets_verified_tss_80_percent_claim(self, fetch_directory):
        fetch_directory.return_value = {
            normalize_member_key("365 CANCER PREVENTION SOCIETY"): "365 CANCER PREVENTION SOCIETY",
        }

        match = match_programmes(
            {
                "company_name": "365 Cancer Prevention Society",
                "entity_type_guess": "social_service",
                "entity_type_confidence": "high",
                "recommended_first_cert": "Cyber Essentials",
                "website_content": "charity social service cancer support beneficiaries Singapore",
            },
            programmes=PROGRAMMES,
        )

        self.assertEqual(match.funding_status, "verified_match")
        self.assertEqual(match.primary_funding_program, "NCSS Transformation Sustainability Scheme (TSS)")
        self.assertIn("up to 80% co-funding", match.funding_claim_line)
        self.assertFalse(match.funding_human_review_required)
        self.assertEqual(match.matched[0]["ncss_member_name"], "365 CANCER PREVENTION SOCIETY")
        self.assertIn("maps.gov.sg/ncss-members", match.matched[0]["ncss_member_source_url"])

    @patch("services.crawl4ai.funding_programs.fetch_ncss_member_directory")
    def test_ncss_track_requires_directory_match(self, fetch_directory):
        fetch_directory.return_value = {
            normalize_member_key("Unrelated Social Service Agency"): "Unrelated Social Service Agency",
        }

        match = match_programmes(
            {
                "company_name": "Not In NCSS Directory",
                "entity_type_guess": "social_service",
                "entity_type_confidence": "high",
                "recommended_first_cert": "Cyber Essentials",
                "website_content": "charity social service beneficiaries Singapore",
            },
            programmes=PROGRAMMES,
        )

        self.assertNotEqual(match.primary_funding_program, "NCSS Transformation Sustainability Scheme (TSS)")
        self.assertNotIn("80%", match.funding_claim_line)

    @patch("services.crawl4ai.funding_programs.fetch_ncss_member_directory")
    def test_ncss_member_match_uses_website_heading_for_domain_company(self, fetch_directory):
        fetch_directory.return_value = {normalize_member_key("4S"): "4S"}

        match = match_programmes(
            {
                "company_name": "4s.org.sg",
                "company_homepage_name": "Enhancing Senior Well-Being",
                "entity_type_guess": "social_service",
                "entity_type_confidence": "high",
                "best_url": "https://4s.org.sg/",
                "recommended_first_cert": "Cyber Essentials",
                "website_content": "# 4S | Enhancing Senior Well-Being\nSocial service support for seniors.",
            },
            programmes=PROGRAMMES,
        )

        self.assertEqual(match.funding_status, "verified_match")
        self.assertEqual(match.primary_funding_program, "NCSS Transformation Sustainability Scheme (TSS)")
        self.assertEqual(match.matched[0]["ncss_member_name"], "4S")


if __name__ == "__main__":
    unittest.main()
