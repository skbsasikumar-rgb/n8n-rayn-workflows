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
                    "provider": "openserp_duckduckgo",
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

    def test_official_site_llm_requires_exact_quote(self):
        content = "Our clinic is led by Dr Jane Tan, Clinical Director of Example Clinic."
        payload = {
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": content,
        }
        fake = {
            "accepted_candidates": [
                {
                    "name": "Jane Tan",
                    "role": "Clinical Director",
                    "role_bucket": "clinic_leadership",
                    "seniority": "manager",
                    "evidence_quote": "Dr Jane Tan, Clinical Director of Example Clinic",
                    "source_url": "https://exampleclinic.sg/",
                    "confidence": 0.93,
                    "reason": "Official site links the role and company.",
                },
                {
                    "name": "Invented Person",
                    "role": "CEO",
                    "role_bucket": "c_suite",
                    "seniority": "executive",
                    "evidence_quote": "Invented Person, CEO of Example Clinic",
                    "source_url": "https://exampleclinic.sg/",
                    "confidence": 0.99,
                    "reason": "This quote is not present.",
                },
            ],
            "rejected_candidates": [],
        }
        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_FAKE_RESPONSE": json.dumps(fake)}, clear=False):
            verification = c.verify_preflight_candidates_with_llm(payload, content)
        self.assertEqual([candidate.name for candidate in verification.accepted], ["Jane Tan"])
        self.assertEqual(verification.rejected_candidates[0]["raw_name"], "Invented Person")
        self.assertEqual(verification.rejected_candidates[0]["reason_code"], "insufficient_evidence")

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

    def test_email_validation_summary_lists_valid_and_rejected_attempts(self):
        result = c.ContactResult(
            row_id=1,
            contact_search_status="contact_found",
            contact_search_reason="sendable_person_specific_email_found",
            email_candidates=[
                {
                    "name": "Jane Tan",
                    "role": "Executive Director",
                    "email": "jane@example.org.sg",
                    "valid_email": "jane@example.org.sg",
                    "status": "valid",
                    "decision": "sendable",
                    "accepted": True,
                },
                {
                    "name": "John Lim",
                    "role": "Operations Manager",
                    "status": "not_found",
                    "decision": "rejected",
                    "validation_result": {
                        "input": {"domain": "example.org.sg", "full_name": "John Lim"},
                        "email_status": "not_found",
                    },
                },
            ],
            validated_email="jane@example.org.sg",
            email_validation_status="sendable",
        )
        summary = c.build_email_validation_summary(result)
        self.assertIn("Accepted: jane@example.org.sg", summary)
        self.assertIn("valid: jane@example.org.sg", summary)
        self.assertIn("not valid: John Lim @ example.org.sg", summary)

    def test_enrich_contact_preserves_selected_person_after_anymail_miss(self):
        payload = {
            "Id": 123,
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": "Jane Tan, Medical Director, Example Clinic",
            "site_fast_path_only": True,
        }

        def fake_anymail(candidate, domain):
            return {
                "configured": True,
                "error": "",
                "provider": "anymail_finder",
                "results": [{"email_status": "not_found", "input": {"domain": domain, "full_name": candidate.name}}],
                "mx_exists": True,
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_person", side_effect=fake_anymail):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_not_found")
        self.assertEqual(result.contact_search_reason, "candidates_found_but_no_sendable_email")
        self.assertEqual(result.validated_email, "")
        self.assertEqual(result.selected_contact_name, "Jane Tan")
        self.assertEqual(result.email_validation_provider, "anymail_finder")

    def test_decision_maker_category_order_matches_anymail_values(self):
        with patch.dict(os.environ, {}, clear=False):
            self.assertEqual(c.configured_decision_maker_categories(), ["ceo", "it", "operations", "hr", "marketing"])

    def test_anymail_post_retries_timeout_then_succeeds(self):
        calls = []

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"email_status": "valid", "valid_email": "jane@example.org.sg", "credits_charged": 1}

        def fake_post(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise c.requests.Timeout()
            return FakeResponse()

        with patch.dict(os.environ, {"ANYMAILFINDER_PERSON_RETRIES": "1", "ANYMAILFINDER_PERSON_RETRY_BACKOFF_SECONDS": "0"}, clear=False), patch.object(c.requests, "post", side_effect=fake_post), patch.object(c.time, "sleep"):
            result = c.post_anymail_with_retries(
                provider="anymail_finder",
                base_url="https://api.example.test/person",
                api_key="token",
                request_body={"domain": "example.org.sg", "full_name": "Jane Tan"},
                timeout_seconds=10,
                retry_prefix="ANYMAILFINDER_PERSON",
                default_retries=1,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["retried"])
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(result["attempts"][0]["error"], "timeout")
        self.assertEqual(result["payload"]["valid_email"], "jane@example.org.sg")

    def test_decision_maker_fallback_runs_when_person_lookup_misses(self):
        payload = {
            "Id": 123,
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": "Jane Tan, Medical Director, Example Clinic",
            "site_fast_path_only": True,
        }

        def fake_anymail(candidate, domain):
            return {
                "configured": True,
                "error": "",
                "provider": "anymail_finder",
                "results": [{"email_status": "not_found", "input": {"domain": domain, "full_name": candidate.name}}],
                "mx_exists": True,
            }

        def fake_decision_maker(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "provider": "anymail_finder_decision_maker",
                "categories": ["ceo", "it", "operations", "hr", "marketing"],
                "credits_charged": 2,
                "results": [
                    {
                        "credits_charged": 2,
                        "decision_maker_category": "operations",
                        "email": "ops@exampleclinic.sg",
                        "email_status": "valid",
                        "person_full_name": "Olivia Lim",
                        "person_job_title": "Operations Manager",
                        "person_linkedin_url": "https://www.linkedin.com/in/olivialim/",
                        "valid_email": "ops@exampleclinic.sg",
                    }
                ],
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_person", side_effect=fake_anymail), patch.object(c, "validate_anymail_decision_maker", side_effect=fake_decision_maker):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_decision_maker_email_found")
        self.assertEqual(result.validated_email, "ops@exampleclinic.sg")
        self.assertEqual(result.selected_contact_name, "Olivia Lim")
        self.assertEqual(result.selected_contact_linkedin_url, "https://www.linkedin.com/in/olivialim/")
        self.assertEqual(result.email_validation_provider, "anymail_finder+decision_maker")
        self.assertEqual(result.email_validation_evidence["decision_maker_fallback"]["categories"], ["ceo", "it", "operations", "hr", "marketing"])

    def test_generic_email_fallback_runs_after_person_lookup_miss(self):
        payload = {
            "Id": 123,
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": "Jane Tan, Medical Director, Example Clinic. Contact us at info@exampleclinic.sg",
            "site_fast_path_only": True,
        }

        def fake_anymail(candidate, domain):
            return {
                "configured": True,
                "error": "",
                "provider": "anymail_finder",
                "results": [{"email_status": "not_found", "input": {"domain": domain, "full_name": candidate.name}}],
                "mx_exists": True,
            }

        def fake_no2bounce(emails, timeout_seconds=None):
            self.assertEqual(emails, ["info@exampleclinic.sg"])
            return {
                "configured": True,
                "error": "",
                "results": [{"email": "info@exampleclinic.sg", "status": "Deliverable", "finalScoreValue": "Deliverable"}],
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_person", side_effect=fake_anymail), patch.object(c, "validate_no2bounce", side_effect=fake_no2bounce):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_generic_email_found")
        self.assertEqual(result.validated_email, "info@exampleclinic.sg")
        self.assertEqual(result.email_validation_provider, "no2bounce")
        self.assertEqual(result.selected_contact_name, "")

    def test_generic_email_fallback_runs_when_no_named_candidate_exists(self):
        payload = {
            "Id": 456,
            "company_name": "Example Community Care",
            "company_homepage_name": "Example Community Care",
            "canonical_domain": "examplecare.sg",
            "best_url": "https://examplecare.sg/",
            "website_content": "For enquiries email hello@examplecare.sg or support@examplecare.sg",
            "site_fast_path_only": True,
        }

        def fake_no2bounce(emails, timeout_seconds=None):
            self.assertEqual(emails, ["hello@examplecare.sg", "support@examplecare.sg"])
            return {
                "configured": True,
                "error": "",
                "results": [{"email": "hello@examplecare.sg", "status": "Deliverable", "finalScoreValue": "Deliverable"}],
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_no2bounce", side_effect=fake_no2bounce):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_generic_email_found")
        self.assertEqual(result.validated_email, "hello@examplecare.sg")
        self.assertEqual(result.email_validation_provider, "no2bounce")

    def test_generic_email_fallback_requires_no2bounce_when_generic_email_exists(self):
        payload = {
            "Id": 789,
            "company_name": "Example Care",
            "company_homepage_name": "Example Care",
            "canonical_domain": "examplecare.sg",
            "best_url": "https://examplecare.sg/",
            "website_content": "For enquiries email info@examplecare.sg",
            "site_fast_path_only": True,
        }

        def fake_no2bounce(emails, timeout_seconds=None):
            return {"configured": False, "error": "NO2BOUNCE_API_TOKEN is not configured", "results": []}

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_no2bounce", side_effect=fake_no2bounce):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "failed")
        self.assertEqual(result.contact_search_reason, "generic_email_validation_not_configured")
        self.assertEqual(result.email_validation_provider, "no2bounce")

    def test_decision_maker_linkedin_requires_matching_profile_slug(self):
        candidate = c.decision_maker_candidate_from_result(
            {
                "decision_maker_category": "operations",
                "person_full_name": "Etienne Ding",
                "person_job_title": "Operations Manager",
                "person_linkedin_url": "https://sg.linkedin.com/in/cherie-tan-1350b9163",
            },
            "exampleclinic.sg",
        )

        self.assertEqual(candidate["linkedin_url"], "")
        self.assertEqual(candidate["source_url"], "https://exampleclinic.sg/")

    def test_role_queries_cover_all_buckets_with_small_budget(self):
        queries = c.build_role_queries(
            "Example Community Clinic",
            "Example Community Clinic",
            "exampleclinic.sg",
            website_content="Example Community Clinic has a public website.",
            max_queries=4,
        )
        covered = {
            bucket
            for query in queries
            for bucket in query.get("covered_role_buckets", [])
        }
        self.assertLessEqual(len(queries), 4)
        self.assertEqual(covered, set(c.TARGET_ROLE_BUCKETS))
        self.assertEqual([query["role_bucket"] for query in queries], [
            "c_suite",
            "c_suite",
            "clinic_leadership",
            "compliance_privacy_security",
        ])
        self.assertIn("Founder", queries[0]["query"])
        self.assertTrue(queries[1]["query"].startswith("site:exampleclinic.sg"))
        self.assertIn("Operations Manager", queries[2]["query"])
        query_text = " ".join(query["query"] for query in queries)
        self.assertIn("Data Protection Officer", query_text)
        self.assertIn("hr manager", query_text.lower())

    def test_plural_role_terms_extract_names_from_search_snippets(self):
        text = "AMP Lab: Our Founders · Etienne Ding · Cherie Tan."
        role, group = c.role_match(text)
        self.assertEqual(role, "Founder")
        self.assertEqual(group["bucket"], "c_suite")
        self.assertIn(("Etienne Ding", 24, 36), c.name_matches_for_role(text, role))


if __name__ == "__main__":
    unittest.main()
