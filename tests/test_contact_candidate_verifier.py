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

        with patch.dict(
            os.environ,
            {
                "CONTACT_PREFLIGHT_LLM_ENABLED": "false",
                "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false",
                "CONTACT_COMPANY_EMAIL_FALLBACK_ENABLED": "false",
            },
            clear=False,
        ), patch.object(c, "validate_anymail_person", side_effect=fake_anymail):
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

    def test_decision_maker_fallback_accepts_provider_validated_alias_domain(self):
        payload = {
            "Id": 313,
            "company_name": "Sree Narayana Mission",
            "company_homepage_name": "Sree Narayana Mission",
            "canonical_domain": "sreenarayanamission.org",
            "best_url": "https://sreenarayanamission.org/",
            "website_content": "Our Management Team Chief Executive Officer S. Devendran.",
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
                "categories": ["ceo"],
                "results": [
                    {
                        "decision_maker_category": "ceo",
                        "email": "devendran@snm.org.sg",
                        "email_status": "valid",
                        "person_full_name": "S. Devendran",
                        "person_job_title": "Chief Executive Officer",
                        "valid_email": "devendran@snm.org.sg",
                    }
                ],
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_person", side_effect=fake_anymail), patch.object(c, "validate_anymail_decision_maker", side_effect=fake_decision_maker):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_decision_maker_email_found")
        self.assertEqual(result.validated_email, "devendran@snm.org.sg")
        self.assertEqual(result.selected_contact_name, "S Devendran")

    def test_company_email_fallback_runs_after_person_lookup_miss(self):
        payload = {
            "Id": 123,
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": "Jane Tan, Medical Director, Example Clinic.",
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

        def fake_company(domain, company_name=""):
            self.assertEqual(domain, "exampleclinic.sg")
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["contact@exampleclinic.sg", "info@exampleclinic.sg"],
                    "valid_emails": ["info@exampleclinic.sg"],
                }],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_person", side_effect=fake_anymail), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_company_email_found")
        self.assertEqual(result.validated_email, "info@exampleclinic.sg")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")
        self.assertEqual(result.selected_contact_name, "")

    def test_company_email_fallback_runs_when_no_named_candidate_exists(self):
        payload = {
            "Id": 456,
            "company_name": "Example Community Care",
            "company_homepage_name": "Example Community Care",
            "canonical_domain": "examplecare.sg",
            "best_url": "https://examplecare.sg/",
            "website_content": "Community care provider in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["hello@examplecare.sg", "support@examplecare.sg"],
                    "valid_emails": ["hello@examplecare.sg", "support@examplecare.sg"],
                }],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_company_email_found")
        self.assertEqual(result.validated_email, "hello@examplecare.sg")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")

    def test_company_email_fallback_infers_person_name_from_specific_email(self):
        payload = {
            "Id": 458,
            "company_name": "Dr Panda Medical Centre @ Sin Ming",
            "company_homepage_name": "Dr Panda Medical Centre",
            "canonical_domain": "drpanda.one",
            "best_url": "https://www.drpanda.one/",
            "website_content": "Dr Panda Medical Centre is open daily in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["joycetan@drpanda.one"],
                    "valid_emails": ["joycetan@drpanda.one"],
                }],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade", return_value=[]):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_reason, "sendable_company_email_found")
        self.assertEqual(result.validated_email, "joycetan@drpanda.one")
        self.assertEqual(result.selected_contact_name, "Joyce Tan")
        self.assertEqual(result.selected_contact_role, "Company Contact")
        self.assertEqual(result.selected_contact_seniority, "team")
        self.assertEqual(result.selected_contact_confidence, "Low")

    def test_company_email_fallback_runs_after_decision_maker_miss(self):
        payload = {
            "Id": 457,
            "company_name": "Example Community Care",
            "company_homepage_name": "Example Community Care",
            "canonical_domain": "examplecare.sg",
            "best_url": "https://examplecare.sg/",
            "website_content": "Community care provider in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_decision_maker(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "provider": "anymail_finder_decision_maker",
                "categories": ["ceo", "it", "operations", "hr", "marketing"],
                "credits_charged": 0,
                "results": [],
            }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["hello@examplecare.sg", "support@examplecare.sg"],
                    "valid_emails": ["hello@examplecare.sg"],
                }],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_decision_maker", side_effect=fake_decision_maker), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_company_email_found")
        self.assertEqual(result.validated_email, "hello@examplecare.sg")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")

    def test_company_email_fallback_requires_anymail_configured(self):
        payload = {
            "Id": 789,
            "company_name": "Example Care",
            "company_homepage_name": "Example Care",
            "canonical_domain": "examplecare.sg",
            "best_url": "https://examplecare.sg/",
            "website_content": "Primary care clinic.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {"configured": False, "enabled": True, "error": "ANYMAILFINDER_API_KEY is not configured", "results": []}

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "failed")
        self.assertEqual(result.contact_search_reason, "company_email_validation_not_configured")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")

    def test_company_email_fallback_uses_first_valid_email_in_ranked_results(self):
        payload = {
            "Id": 790,
            "company_name": "Example Rehab",
            "company_homepage_name": "Example Rehab",
            "canonical_domain": "examplerehab.sg",
            "best_url": "https://examplerehab.sg/",
            "website_content": "Rehab clinic in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["team@examplerehab.sg", "info@examplerehab.sg", "support@examplerehab.sg"],
                    "valid_emails": ["info@examplerehab.sg", "support@examplerehab.sg"],
                }],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_company_email_found")
        self.assertEqual(result.validated_email, "info@examplerehab.sg")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")
        self.assertEqual(result.email_validation_evidence["company_email_fallback"]["accepted_email"], "info@examplerehab.sg")

    def test_company_email_fallback_prefers_name_like_email_before_generic(self):
        payload = {
            "Id": 792,
            "company_name": "APAX Medical & Aesthetics Clinic",
            "company_homepage_name": "APAX Medical & Aesthetics Clinic",
            "canonical_domain": "apaxmedical.com",
            "best_url": "https://apaxmedical.com/",
            "website_content": "",
            "search_attempts": [],
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["us@apaxmedical.com", "jessicachoo@apaxmedical.com"],
                    "valid_emails": ["us@apaxmedical.com", "jessicachoo@apaxmedical.com"],
                }],
                "email_type": "any",
            }

        def fake_search(payload):
            queries = [item["query"] for item in payload.get("search_queries", [])]
            self.assertEqual(len(queries), 1)
            self.assertIn("Jessica Choo", queries[0])
            return [
                {
                    "provider": "serper",
                    "query": queries[0],
                    "results": [
                        {
                            "rank": 1,
                            "title": "Terms of Use & Privacy Policy - APAX Medical & Aesthetics Clinic",
                            "url": "https://apaxmedical.com/terms-of-use/",
                            "snippet": "Contact APAX Medical & Aesthetics Clinic at jessicachoo@apaxmedical.com.",
                        }
                    ],
                    "usable_results_count": 1,
                }
            ]

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade", side_effect=fake_search):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.validated_email, "jessicachoo@apaxmedical.com")
        self.assertEqual(result.selected_contact_name, "Jessica Choo")
        self.assertEqual(result.selected_contact_role, "Company Contact")
        self.assertEqual(result.selected_contact_seniority, "team")
        self.assertEqual(result.selected_contact_confidence, "Low")
        self.assertTrue(result.email_validation_evidence["company_email_identity_resolution"]["partially_proved"])

    def test_decision_maker_fallback_runs_before_public_search(self):
        payload = {
            "Id": 794,
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": "",
        }

        def fake_decision_maker(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "email": "ops@exampleclinic.sg",
                    "valid_email": "ops@exampleclinic.sg",
                    "person_full_name": "Olivia Tan",
                    "person_job_title": "Operations Manager",
                    "decision_maker_category": "operations",
                }],
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_decision_maker", side_effect=fake_decision_maker), patch.object(c, "execute_provider_cascade") as search:
            result = c.enrich_contact(payload, validate_email=True)

        search.assert_not_called()
        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.validated_email, "ops@exampleclinic.sg")
        self.assertEqual(result.selected_contact_name, "Olivia Tan")
        self.assertEqual(result.email_validation_provider, "anymail_finder+decision_maker")

    def test_personal_company_email_resolves_identity_from_search_evidence(self):
        payload = {
            "Id": 793,
            "company_name": "American International Clinic Singapore",
            "company_homepage_name": "American International Clinic Singapore",
            "canonical_domain": "aiclinic.com.sg",
            "best_url": "https://www.aiclinic.com.sg/",
            "website_content": "International clinic in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["zakowich@aiclinic.com.sg"],
                    "valid_emails": ["zakowich@aiclinic.com.sg"],
                }],
                "email_type": "any",
            }

        def fake_search(payload):
            queries = [item["query"] for item in payload.get("search_queries", [])]
            self.assertEqual(len(queries), 1)
            self.assertTrue(any("zakowich" in query.lower() for query in queries))
            return [
                {
                    "provider": "serper",
                    "query": 'site:aiclinic.com.sg "zakowich"',
                    "results": [
                        {
                            "rank": 1,
                            "title": "Dr Paul Zakowich - American International Clinic Singapore",
                            "url": "https://www.aiclinic.com.sg/our-specialist/",
                            "snippet": "Dr Paul Zakowich is a Doctor at American International Clinic Singapore.",
                        }
                    ],
                    "usable_results_count": 1,
                }
            ]

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade", side_effect=fake_search):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.contact_search_reason, "sendable_company_email_found")
        self.assertEqual(result.validated_email, "zakowich@aiclinic.com.sg")
        self.assertEqual(result.selected_contact_name, "Paul Zakowich")
        self.assertEqual(result.selected_contact_role, "Doctor")
        self.assertEqual(result.selected_contact_seniority, "manager")
        self.assertEqual(result.selected_contact_confidence, "High")
        self.assertEqual(result.selected_contact_source_url, "https://www.aiclinic.com.sg/our-specialist/")
        self.assertTrue(result.email_validation_evidence["company_email_identity_resolution"]["resolved"])

    def test_personal_company_email_conflicting_person_slug_falls_back_to_homepage_source(self):
        payload = {
            "Id": 795,
            "company_name": "American International Clinic Singapore",
            "company_homepage_name": "American International Clinic Singapore",
            "canonical_domain": "aiclinic.com.sg",
            "best_url": "https://aiclinic.com.sg/",
            "website_content": "International clinic in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["zakowich@aiclinic.com.sg"],
                    "valid_emails": ["zakowich@aiclinic.com.sg"],
                }],
                "email_type": "any",
            }

        def fake_search(payload):
            return [
                {
                    "provider": "serper",
                    "query": 'site:aiclinic.com.sg "zakowich"',
                    "results": [
                        {
                            "rank": 1,
                            "title": "Dr Paul Zakowich - American International Clinic Singapore",
                            "url": "https://www.aiclinic.com.sg/ms-amy-tan/",
                            "snippet": "Dr Paul Zakowich is a Doctor at American International Clinic Singapore.",
                        }
                    ],
                    "usable_results_count": 1,
                }
            ]

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade", side_effect=fake_search):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.selected_contact_name, "Paul Zakowich")
        self.assertEqual(result.selected_contact_source_url, "https://aiclinic.com.sg/")
        self.assertEqual(result.email_validation_evidence["company_email_identity_resolution"]["evidence_url"], "https://www.aiclinic.com.sg/ms-amy-tan/")

    def test_personal_company_email_resolves_lowercase_and_middle_initial_identity(self):
        payload = {
            "Id": 796,
            "company_name": "American International Clinic Singapore",
            "company_homepage_name": "American International Clinic Singapore",
            "canonical_domain": "aiclinic.com.sg",
            "best_url": "https://aiclinic.com.sg/",
            "website_content": "International clinic in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["zakowich@aiclinic.com.sg", "enquiries@aiclinic.com.sg"],
                    "valid_emails": ["zakowich@aiclinic.com.sg", "enquiries@aiclinic.com.sg"],
                }],
                "email_type": "any",
            }

        def fake_search(payload):
            return [
                {
                    "provider": "serper",
                    "query": '"zakowich@aiclinic.com.sg" OR "zakowich" "aiclinic.com.sg"',
                    "results": [
                        {
                            "rank": 1,
                            "title": "paul zakowich - Specialist in Internal Medicine ... - LinkedIn Singapore",
                            "url": "https://sg.linkedin.com/in/paul-zakowich-0b32a752",
                            "snippet": "Paul Zakowich is listed with American International Clinic Singapore.",
                        },
                        {
                            "rank": 2,
                            "title": "Dr Paul E. Zakowich - Singapore - Novena Medical Center",
                            "url": "https://novenamedicalcenter.com/our-doctors/dr-paul-e-zakowich/",
                            "snippet": "Dr Paul E. Zakowich is a Specialist in Internal Medicine connected with American International Clinic Singapore.",
                        },
                    ],
                    "usable_results_count": 2,
                }
            ]

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade", side_effect=fake_search):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.validated_email, "zakowich@aiclinic.com.sg")
        self.assertEqual(result.selected_contact_name, "Paul Zakowich")
        self.assertEqual(result.selected_contact_role, "Specialist")
        self.assertEqual(result.selected_contact_seniority, "manager")
        self.assertEqual(result.selected_contact_confidence, "Medium")
        self.assertTrue(result.email_validation_evidence["company_email_identity_resolution"]["resolved"])

    def test_generic_company_email_skips_identity_resolution(self):
        payload = {
            "Id": 794,
            "company_name": "An Dental",
            "company_homepage_name": "An Dental",
            "canonical_domain": "andental.sg",
            "best_url": "https://andental.sg/",
            "website_content": "Dental clinic in Singapore.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{
                    "credits_charged": 1,
                    "email_status": "valid",
                    "emails": ["contact@andental.sg"],
                    "valid_emails": ["contact@andental.sg"],
                }],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade") as search_mock:
            result = c.enrich_contact(payload, validate_email=True)

        search_mock.assert_not_called()
        self.assertEqual(result.contact_search_status, "contact_found")
        self.assertEqual(result.validated_email, "contact@andental.sg")
        self.assertEqual(result.selected_contact_name, "")
        self.assertEqual(result.email_validation_evidence["company_email_identity_resolution"]["skipped"], "generic_company_email")

    def test_company_email_fallback_records_zero_candidates_when_none_found(self):
        payload = {
            "Id": 791,
            "company_name": "Example Diagnostics",
            "company_homepage_name": "Example Diagnostics",
            "canonical_domain": "exampledx.sg",
            "best_url": "https://exampledx.sg/",
            "website_content": "Visit our clinic and call our front desk for appointments.",
            "site_fast_path_only": True,
        }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{"credits_charged": 0, "email_status": "not_found", "emails": [], "valid_emails": []}],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false", "ANYMAILFINDER_DECISION_MAKER_FALLBACK_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_not_found")
        self.assertEqual(result.contact_search_reason, "no_deliverable_company_email_found")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")
        self.assertEqual(result.email_validation_evidence["company_email_fallback"]["candidate_count"], 0)
        self.assertEqual(result.email_candidates[-1]["provider"], "anymail_finder_company")
        self.assertEqual(result.email_candidates[-1]["status"], "no_deliverable_email")

    def test_company_email_fallback_zero_candidates_are_preserved_after_person_lookup_miss(self):
        payload = {
            "Id": 792,
            "company_name": "Example Physio",
            "company_homepage_name": "Example Physio",
            "canonical_domain": "examplephysio.sg",
            "best_url": "https://examplephysio.sg/",
            "website_content": "Jane Tan, Clinical Director, Example Physio. Call us for appointments.",
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
                "credits_charged": 0,
                "results": [],
            }

        def fake_company(domain, company_name=""):
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{"credits_charged": 0, "email_status": "not_found", "emails": [], "valid_emails": []}],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_person", side_effect=fake_anymail), patch.object(c, "validate_anymail_decision_maker", side_effect=fake_decision_maker), patch.object(c, "validate_anymail_company", side_effect=fake_company):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(result.contact_search_status, "contact_not_found")
        self.assertEqual(result.email_validation_status, "no_deliverable_email")
        self.assertEqual(result.email_validation_provider, "anymail_finder_company")
        self.assertEqual(result.email_validation_evidence["company_email_fallback"]["candidate_count"], 0)
        self.assertEqual(result.email_candidates[-1]["provider"], "anymail_finder_company")
        self.assertEqual(result.email_candidates[-1]["status"], "no_deliverable_email")

    def test_early_anymail_fallback_is_reused_after_search_miss(self):
        payload = {
            "Id": 793,
            "company_name": "Example Clinic",
            "company_homepage_name": "Example Clinic",
            "canonical_domain": "exampleclinic.sg",
            "best_url": "https://exampleclinic.sg/",
            "website_content": "",
            "site_fast_path_only": False,
        }
        calls = {"decision_maker": 0, "company": 0}

        def fake_decision_maker(domain, company_name=""):
            calls["decision_maker"] += 1
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "provider": "anymail_finder_decision_maker",
                "categories": ["ceo", "it", "operations", "hr", "marketing"],
                "credits_charged": 0,
                "results": [],
            }

        def fake_company(domain, company_name=""):
            calls["company"] += 1
            return {
                "configured": True,
                "enabled": True,
                "error": "",
                "results": [{"credits_charged": 0, "email_status": "not_found", "emails": [], "valid_emails": []}],
                "email_type": "any",
            }

        with patch.dict(os.environ, {"CONTACT_PREFLIGHT_LLM_ENABLED": "false"}, clear=False), patch.object(c, "validate_anymail_decision_maker", side_effect=fake_decision_maker), patch.object(c, "validate_anymail_company", side_effect=fake_company), patch.object(c, "execute_provider_cascade", return_value=[]):
            result = c.enrich_contact(payload, validate_email=True)

        self.assertEqual(calls, {"decision_maker": 1, "company": 1})
        self.assertEqual(result.contact_search_status, "contact_not_found")
        self.assertEqual(result.contact_search_reason, "no_validated_person_found")
        self.assertTrue(result.email_validation_evidence["final_domain_fallback_skipped"])
        self.assertEqual(
            result.email_validation_evidence["final_domain_fallback_skip_reason"],
            "early_anymail_decision_maker_company_already_checked",
        )

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
