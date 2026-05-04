import unittest

from services.crawl4ai.funding_programs import FundingProgram, match_programmes


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


if __name__ == "__main__":
    unittest.main()
