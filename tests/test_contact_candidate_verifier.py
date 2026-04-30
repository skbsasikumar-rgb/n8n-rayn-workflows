import json
import os
import unittest
from unittest.mock import patch

from services.crawl4ai import contact_enrichment as c


class ContactCandidateVerifierTests(unittest.TestCase):
    def test_structural_name_filter_rejects_non_people(self):
        for name in [
            "Dental Movies UK",
            "Past President",
            "Group Head",
            "Raffles Institution",
            "SINGWEALTH HOLDINGS PTE LTD",
            "Meet Doctor",
            "Owner, Asian Diabetic & Retinal Disease Center",
            "MBChB Glasgow",
            "Pain Specialist",
            "Clinical Director",
            "Clinic Operations Manager",
        ]:
            self.assertFalse(c.probable_human_name(name), name)

    def test_structural_name_filter_allows_real_names(self):
        for name in [
            "Jaideep Raj Rao",
            "Arthur Yeah",
            "Jimmy Gian",
            "Joshua Loh",
            "Jayne Wee",
            "Sharon Tan",
            "Tan Chin Beng Melvyn",
        ]:
            self.assertTrue(c.probable_human_name(name), name)

    def test_title_only_requires_stronger_evidence(self):
        for name in ["Dr Wong", "Owner", "Founder", "Medical Director", "Clinic Manager"]:
            self.assertFalse(c.probable_human_name(name), name)

    def test_raw_false_positive_is_rejected_not_counted(self):
        payload = {
            "Id": 1,
            "company_name": "Arden JR Surgery",
            "company_homepage_name": "Arden JR Surgery",
            "canonical_domain": "ardenjrsurgery.com.sg",
            "best_url": "https://ardenjrsurgery.com.sg/",
            "website_content": "",
            "excluded_candidate_names": ["Jaideep Raj Rao"],
            "search_attempts": [
                {
                    "provider": "serper_emergency",
                    "query": '"Arden JR Surgery" Singapore ("CEO" OR "Founder" OR "Owner")',
                    "role": "Owner",
                    "results": [
                        {
                            "rank": 1,
                            "title": "Jaideep Raj Rao | 16 comments - LinkedIn",
                            "url": "https://www.linkedin.com/posts/example",
                            "snippet": "Owner, Asian Diabetic & Retinal Disease Center. 4y. Report this ...",
                        }
                    ],
                }
            ],
        }
        with patch.dict(os.environ, {"CONTACT_LLM_VERIFIER_ENABLED": "false"}, clear=False):
            result = c.enrich_contact(payload, validate_email=False)
        evidence = result.contact_search_evidence
        self.assertEqual(evidence["raw_candidate_count"], 1)
        self.assertEqual(evidence["verified_candidate_count"], 0)
        self.assertEqual(evidence["candidate_count"], 0)
        self.assertEqual(evidence["candidate_names"], [])
        self.assertEqual(evidence["rejected_candidate_names"], ["Asian Diabetic"])
        self.assertIn("jaideep raj rao", evidence["previously_tried_candidate_names"])

    def test_llm_verifier_accepts_only_fake_accepted_candidate(self):
        raw = [
            {
                "raw_name": "Sharon Tan",
                "role_detected": "Operations Manager",
                "role_bucket": "operations",
                "role_priority": 4,
                "seniority": "manager",
                "source_url": "https://sg.linkedin.com/in/sharon-tan",
                "source_type": "public_linkedin_snippet",
                "source_strength": "strong_professional_profile",
                "title": "Sharon Tan - Operations Manager - Asian Heart & Vascular Centre",
                "snippet": "Operations Manager at Asian Heart & Vascular Centre",
                "evidence_text": "Sharon Tan - Operations Manager - Asian Heart & Vascular Centre",
                "query": "Asian Heart & Vascular Centre Operations Manager",
                "name_start": 0,
                "name_end": 10,
            }
        ]
        fake = {
            "accepted_candidates": [
                {
                    "name": "Sharon Tan",
                    "role": "Operations Manager",
                    "role_bucket": "operations",
                    "seniority": "manager",
                    "is_human": True,
                    "target_company_match": "direct",
                    "source_strength": "strong_professional_profile",
                    "confidence": 0.9,
                    "reason": "Snippet links role and company.",
                }
            ],
            "rejected_candidates": [],
            "needs_more_evidence_candidates": [],
        }
        payload = {"company_name": "Asian Heart & Vascular Centre", "company_homepage_name": "Asian Heart & Vascular Centre", "canonical_domain": "ahvc.com.sg"}
        with patch.dict(os.environ, {"CONTACT_LLM_VERIFIER_FAKE_RESPONSE": json.dumps(fake)}, clear=False):
            verification = c.verify_contact_candidates_with_llm(payload, raw)
        self.assertEqual([candidate.name for candidate in verification.accepted], ["Sharon Tan"])
        self.assertEqual(verification.rejected_candidates, [])

    def test_llm_verifier_rejects_accepted_candidate_not_in_raw_list(self):
        raw = [
            {
                "raw_name": "Sharon Tan",
                "role_detected": "Operations Manager",
                "role_bucket": "operations",
                "role_priority": 4,
                "seniority": "manager",
                "source_url": "https://sg.linkedin.com/in/sharon-tan",
                "source_type": "public_linkedin_snippet",
                "source_strength": "strong_professional_profile",
                "title": "Sharon Tan - Operations Manager - Asian Heart & Vascular Centre",
                "snippet": "Operations Manager at Asian Heart & Vascular Centre",
                "evidence_text": "Sharon Tan - Operations Manager - Asian Heart & Vascular Centre",
            }
        ]
        fake = {
            "accepted_candidates": [
                {
                    "name": "Invented Person",
                    "role": "CEO",
                    "role_bucket": "c_suite",
                    "seniority": "executive",
                    "is_human": True,
                    "target_company_match": "direct",
                    "source_strength": "strong_professional_profile",
                    "confidence": 0.9,
                    "reason": "Should not be accepted because this name is not in raw candidates.",
                }
            ],
            "rejected_candidates": [],
            "needs_more_evidence_candidates": [],
        }
        payload = {"company_name": "Asian Heart & Vascular Centre", "company_homepage_name": "Asian Heart & Vascular Centre", "canonical_domain": "ahvc.com.sg"}
        with patch.dict(os.environ, {"CONTACT_LLM_VERIFIER_FAKE_RESPONSE": json.dumps(fake)}, clear=False):
            verification = c.verify_contact_candidates_with_llm(payload, raw)
        self.assertEqual(verification.accepted, [])
        self.assertEqual(verification.rejected_candidates[0]["raw_name"], "Invented Person")
        self.assertEqual(verification.rejected_candidates[0]["reason_code"], "llm_candidate_not_in_raw_candidates")

    def test_official_site_profile_lines_support_general_industries(self):
        content = """
        # Structured Website Evidence
        ## About
        ABC Community Services is a Singapore social service agency.
        ## Team
        Board of Directors
        Jane Tan
        Executive Director
        Muhammad Faisal Rahman
        Programme Manager
        """
        candidates = c.extract_candidates_from_website_content(
            content,
            "ABC Community Services",
            "ABC Community Services",
            "abccommunity.org.sg",
            "https://abccommunity.org.sg/",
        )
        by_name = {candidate.name: candidate for candidate in candidates}
        self.assertEqual(by_name["Jane Tan"].role, "Executive Director")
        self.assertEqual(by_name["Jane Tan"].role_bucket, "c_suite")
        self.assertEqual(by_name["Muhammad Faisal Rahman"].role, "Programme Manager")
        self.assertEqual(by_name["Muhammad Faisal Rahman"].role_bucket, "operations")

    def test_official_site_profile_lines_do_not_accept_title_only(self):
        content = """
        # Structured Website Evidence
        ## Team
        Example Charity Singapore
        Executive Director
        Board of Directors
        Operations Manager
        """
        candidates = c.extract_candidates_from_website_content(
            content,
            "Example Charity",
            "Example Charity",
            "examplecharity.org.sg",
            "https://examplecharity.org.sg/",
        )
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
