import unittest

from services.crawl4ai.funding_programs import FundingProgram
from services.crawl4ai import outreach_planner as o


def verified_program() -> FundingProgram:
    return FundingProgram(
        programme_id="verified_ce",
        programme_name="Cyber Essentials first successful certification support",
        framework_or_regime="Cyber Essentials",
        relevant_entity_types=["sme", "npo", "charity", "social_service", "clinic", "healthcare_provider"],
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


class OutreachPlannerTests(unittest.TestCase):
    def test_hia_high_confidence_uses_regulatory_pressure(self):
        plan = o.plan_outreach(
            {
                "Id": 1,
                "company_name": "Amaris B. Clinic",
                "best_url": "https://amaris-b.com/",
                "website_content": "Singapore medical clinic providing doctor consultations and patient treatment services.",
            },
            programmes=[verified_program()],
        )
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertTrue(plan.classification["hia_relevant"])
        self.assertIn("HIA", plan.emails["email_1"]["body"])

    def test_hia_low_confidence_marks_review_before_deadline_claim(self):
        plan = o.plan_outreach(
            {
                "Id": 2,
                "company_name": "Wellness Content Pte Ltd",
                "best_url": "https://wellness.example/",
                "website_content": "Singapore wellness articles and customer newsletter signups.",
            }
        )
        self.assertFalse(plan.classification["hia_deadline_claim_safe"])
        self.assertFalse(plan.email_send_ready)
        self.assertNotRegex(plan.emails["email_1"]["body"], r"Sep 2027|Sep 2028|Mar 2030")

    def test_non_hia_private_company_uses_pdpa_safeguards(self):
        plan = o.plan_outreach(
            {
                "Id": 3,
                "company_name": "Acme Services Pte Ltd",
                "best_url": "https://acme.com.sg/",
                "website_content": "Singapore private company collecting customer enquiries and employee data.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "pdpa_safeguards")
        self.assertTrue(plan.classification["pdpa_relevant"])
        self.assertIn("PDPA", plan.emails["email_1"]["body"])
        self.assertIn("Cyber Essentials supports the security-safeguards side of PDPA readiness", plan.emails["email_1"]["body"])

    def test_dpo_contact_uses_data_protection_evidence_track(self):
        plan = o.plan_outreach(
            {
                "Id": 31,
                "company_name": "Acme Services Pte Ltd",
                "best_url": "https://acme.com.sg/",
                "selected_contact_title": "Operations and Compliance Manager",
                "website_content": "Singapore private company collecting customer enquiries and employee data.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "pdpa_safeguards")
        self.assertEqual(o.choose_variant(plan.classification), "dpo_evidence")
        self.assertEqual(plan.emails["email_1"]["chosen_subject"], "data protection evidence")
        self.assertIn("DPOs and ops teams", plan.emails["email_1"]["body"])

    def test_b2b_company_uses_customer_trust_track(self):
        plan = o.plan_outreach(
            {
                "Id": 32,
                "company_name": "Vendor Platform Pte Ltd",
                "best_url": "https://vendor.example/",
                "website_content": "Singapore SaaS platform for enterprise clients and procurement teams.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "customer_trust")
        self.assertEqual(o.choose_variant(plan.classification), "customer_trust")
        self.assertEqual(plan.emails["email_1"]["chosen_subject"], "security evidence")
        self.assertIn("security questions usually come down to proof", plan.emails["email_1"]["body"])

    def test_low_signal_row_is_not_ready(self):
        plan = o.plan_outreach(
            {
                "Id": 33,
                "company_name": "Quiet Holdings",
                "best_url": "https://quiet.example/",
                "website_content": "Singapore corporate website with a short homepage.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "not_ready")
        self.assertEqual(o.choose_variant(plan.classification), "not_ready")
        self.assertEqual(plan.human_review_status, "not_ready")
        for index in range(1, 5):
            self.assertFalse(plan.emails[f"email_{index}"]["body"])

    def test_email_3_uses_funding_claim_line_only(self):
        plan = o.plan_outreach(
            {
                "Id": 4,
                "company_name": "Example Charity",
                "best_url": "https://charity.example/",
                "website_content": "Singapore charity supporting beneficiaries and volunteers.",
            },
            programmes=[verified_program()],
        )
        claim = plan.funding.funding_claim_line
        self.assertIn(claim, plan.emails["email_3"]["body"])
        self.assertNotIn("HIA timelines", plan.emails["email_3"]["body"])
        self.assertNotIn("PDPA", plan.emails["email_3"]["body"])

    def test_normalize_llm_email_sequence_and_patch_quality(self):
        row = {
            "Id": 41,
            "company_name": "Acme Services Pte Ltd",
            "website_content": "Singapore private company collecting customer enquiries and employee data.",
        }
        plan = o.plan_outreach(row)
        candidate = {
            f"email_{index}": {
                "chosen_subject": plan.emails[f"email_{index}"]["chosen_subject"],
                "body": plan.emails[f"email_{index}"]["body"],
            }
            for index in range(1, 5)
        }
        emails = o.normalize_llm_email_sequence(candidate)
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding.to_dict(), emails)
        self.assertEqual(patch["email_1_body"], plan.emails["email_1"]["body"])
        self.assertFalse(patch["email_send_ready"])
        self.assertIn("funding_not_verified", patch["email_quality_flags"])
        partial_funding_patch = o.patch_with_email_sequence(
            row,
            plan.classification,
            {
                "funding_status": "possible_match",
                "funding_claim_line": "The relevant support route appears worth checking, subject to programme confirmation.",
            },
            emails,
        )
        self.assertFalse(partial_funding_patch["email_send_ready"])
        self.assertIn("The relevant support route appears worth checking", partial_funding_patch["email_3_body"])
        self.assertNotIn("email_3_missing_funding_claim_line", partial_funding_patch["email_quality_flags"])

    def test_llm_email_forbidden_phrase_stays_not_send_ready(self):
        row = {
            "Id": 42,
            "company_name": "Acme Services Pte Ltd",
            "website_content": "Singapore private company collecting customer enquiries and employee data.",
        }
        plan = o.plan_outreach(row)
        candidate = {
            f"email_{index}": {
                "chosen_subject": plan.emails[f"email_{index}"]["chosen_subject"],
                "body": plan.emails[f"email_{index}"]["body"],
            }
            for index in range(1, 5)
        }
        candidate["email_1"]["body"] += " Cyber Essentials makes you PDPA compliant."
        emails = o.normalize_llm_email_sequence(candidate)
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding, emails)
        self.assertFalse(patch["email_send_ready"])
        self.assertIn("forbidden_phrase:cyber essentials makes you pdpa compliant", patch["email_quality_flags"])

    def test_forbidden_phrases_rejected(self):
        classification = o.classify_row(
            {
                "company_name": "Example Pte Ltd",
                "website_content": "Singapore company collecting customer data.",
            }
        )
        funding = o.plan_outreach({"company_name": "Example Pte Ltd", "website_content": "customer data"}).funding
        emails = o.generate_email_sequence({"company_name": "Example Pte Ltd"}, classification, funding)
        emails["email_1"]["body"] += " Hope you are well."
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        _, flags, send_ready = o.quality_gate(classification, funding, emails)
        self.assertIn("forbidden_phrase:hope you are well", flags)
        self.assertFalse(send_ready)

    def test_cyber_essentials_not_equal_pdpa_compliance(self):
        classification = o.classify_row({"company_name": "Example Pte Ltd", "website_content": "customer data"})
        funding = o.plan_outreach({"company_name": "Example Pte Ltd", "website_content": "customer data"}).funding
        emails = o.generate_email_sequence({"company_name": "Example Pte Ltd"}, classification, funding)
        emails["email_1"]["body"] += " Cyber Essentials makes you PDPA compliant."
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        _, flags, send_ready = o.quality_gate(classification, funding, emails)
        self.assertIn("forbidden_phrase:cyber essentials makes you pdpa compliant", flags)
        self.assertFalse(send_ready)

    def test_cyber_essentials_not_equal_hia_compliance(self):
        classification = o.classify_row({"company_name": "Example Clinic", "website_content": "medical clinic patient treatment"})
        funding = o.plan_outreach({"company_name": "Example Clinic", "website_content": "medical clinic patient treatment"}).funding
        emails = o.generate_email_sequence({"company_name": "Example Clinic"}, classification, funding)
        emails["email_1"]["body"] += " Fully HIA compliant with Cyber Essentials."
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        _, flags, send_ready = o.quality_gate(classification, funding, emails)
        self.assertIn("forbidden_phrase:fully hia compliant with cyber essentials", flags)
        self.assertFalse(send_ready)

    def test_sree_narayana_social_service_fixture(self):
        plan = o.plan_outreach(
            {
                "Id": 5,
                "company_name": "Sree Narayana Mission (Singapore)",
                "best_url": "https://sreenarayanamission.org.sg/",
                "website_content": "Charity and social service organisation supporting residents, beneficiaries, volunteers and staff in Singapore.",
            },
            programmes=[verified_program()],
        )
        self.assertIn(plan.classification["entity_type_guess"], {"charity", "social_service", "npo"})
        self.assertIn(plan.classification["pressure_type"], {"pdpa_safeguards", "customer_trust"})
        self.assertIn(plan.classification["data_type_signal"], {"resident_data", "beneficiary_data"})
        self.assertNotIn("if you are an NPO", plan.emails["email_3"]["body"])

    def test_amaris_clinic_hia_fixture(self):
        plan = o.plan_outreach(
            {
                "Id": 6,
                "company_name": "Amaris B. Clinic",
                "best_url": "https://amaris-b.com/",
                "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
            },
            programmes=[verified_program()],
        )
        self.assertIn(plan.classification["entity_type_guess"], {"clinic", "healthcare_provider"})
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertIn(plan.classification["data_type_signal"], {"patient_data", "health_information"})
        self.assertIn(plan.classification["recommended_first_cert"], {"Cyber Essentials", "HIA readiness"})

    def test_amazing_hearing_group_fixture(self):
        plan = o.plan_outreach(
            {
                "Id": 7,
                "company_name": "Amazing Hearing Group",
                "best_url": "https://amazinghearing.com.sg/",
                "website_content": "Singapore hearing care provider offering audiology, hearing assessments and patient appointments.",
            },
            programmes=[verified_program()],
        )
        self.assertIn(plan.classification["entity_type_guess"], {"healthcare_provider", "private_company"})
        self.assertTrue(plan.classification["hia_relevant"])
        self.assertIn(plan.classification["data_type_signal"], {"patient_data", "health_information", "customer_data"})
        self.assertEqual(plan.classification["hia_service_type_guess"], "hearing_care")


if __name__ == "__main__":
    unittest.main()
