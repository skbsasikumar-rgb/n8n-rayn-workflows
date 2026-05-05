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
        self.assertIn("customer security question", plan.emails["email_2"]["body"])
        self.assertNotIn("Cyber Essentials is", plan.emails["email_2"]["body"])

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

    def test_llm_email_not_ready_keeps_empty_sequence(self):
        row = {
            "Id": 43,
            "company_name": "Quiet Holdings",
            "website_content": "Singapore corporate website with a short homepage.",
        }
        plan = o.plan_outreach(row)
        candidate = {
            f"email_{index}": {
                "chosen_subject": "security check",
                "body": "This should not be used for a not-ready row.",
            }
            for index in range(1, 5)
        }
        emails = o.normalize_llm_email_sequence(candidate)
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding, emails)
        self.assertEqual(plan.classification["pressure_type"], "not_ready")
        for index in range(1, 5):
            self.assertFalse(patch[f"email_{index}_body"])
        self.assertFalse(patch["email_send_ready"])
        self.assertEqual(patch["human_review_status"], "not_ready")
        self.assertNotIn("email_3_missing_funding_claim_line", patch["email_quality_flags"])
        self.assertNotIn("funding_not_verified", patch["email_quality_flags"])

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
        _, flags, send_ready = o.quality_gate({"company_name": "Example Pte Ltd"}, classification, funding, emails)
        self.assertIn("forbidden_phrase:hope you are well", flags)
        self.assertFalse(send_ready)

    def test_cyber_essentials_not_equal_pdpa_compliance(self):
        classification = o.classify_row({"company_name": "Example Pte Ltd", "website_content": "customer data"})
        funding = o.plan_outreach({"company_name": "Example Pte Ltd", "website_content": "customer data"}).funding
        emails = o.generate_email_sequence({"company_name": "Example Pte Ltd"}, classification, funding)
        emails["email_1"]["body"] += " Cyber Essentials makes you PDPA compliant."
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        _, flags, send_ready = o.quality_gate({"company_name": "Example Pte Ltd"}, classification, funding, emails)
        self.assertIn("forbidden_phrase:cyber essentials makes you pdpa compliant", flags)
        self.assertFalse(send_ready)

    def test_cyber_essentials_not_equal_hia_compliance(self):
        classification = o.classify_row({"company_name": "Example Clinic", "website_content": "medical clinic patient treatment"})
        funding = o.plan_outreach({"company_name": "Example Clinic", "website_content": "medical clinic patient treatment"}).funding
        emails = o.generate_email_sequence({"company_name": "Example Clinic"}, classification, funding)
        emails["email_1"]["body"] += " Fully HIA compliant with Cyber Essentials."
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        _, flags, send_ready = o.quality_gate({"company_name": "Example Clinic"}, classification, funding, emails)
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
        brief = plan.copy_brief
        self.assertIn("care/community-service", plan.emails["email_1"]["body"])
        self.assertIn("resident, beneficiary, volunteer and staff data", plan.emails["email_1"]["body"])
        self.assertIn("resident, beneficiary, volunteer and staff data", plan.emails["email_2"]["body"])
        self.assertIn("resident", brief["personal_data_handled_guess"])
        self.assertIn("beneficiary", brief["personal_data_handled_guess"])
        self.assertIn("volunteer", brief["personal_data_handled_guess"])
        self.assertIn("staff", brief["personal_data_handled_guess"])
        self.assertIn("PDPA", brief["pdpa_obligation_angle"])
        self.assertIn("backups", brief["data_systems_likely"])
        self.assertIn("incident", brief["data_systems_likely"])
        self.assertEqual(brief["email_asset_offer"], "care-organisation checklist")
        self.assertIn("PDPA", plan.emails["email_1"]["body"])
        self.assertIn("Worth sending the care-organisation checklist?", plan.emails["email_1"]["body"])

    def test_amaris_clinic_hia_fixture(self):
        plan = o.plan_outreach(
            {
                "Id": 6,
                "company_name": "Amaris B. Clinic",
                "best_url": "https://amaris-b.com/",
                "services_detected": ["aesthetic clinic services", "doctor consultations"],
                "leadership_or_team_signals": ["doctor and practitioner team"],
                "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
            },
            programmes=[verified_program()],
        )
        self.assertIn(plan.classification["entity_type_guess"], {"clinic", "healthcare_provider"})
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertIn(plan.classification["data_type_signal"], {"patient_data", "health_information"})
        self.assertIn(plan.classification["recommended_first_cert"], {"Cyber Essentials", "HIA readiness"})
        brief = plan.copy_brief
        self.assertIn("HIA", brief["regulatory_pressure_summary"])
        self.assertIn("2027", brief["regulatory_pressure_summary"])
        self.assertIn("patient", brief["personal_data_handled_guess"])
        self.assertIn("health information", brief["personal_data_handled_guess"])
        self.assertIn("clinic service", plan.emails["email_1"]["body"])
        self.assertIn("team/practitioner", plan.emails["email_1"]["body"])
        self.assertIn("HIA timelines starting from 2027", plan.emails["email_1"]["body"])
        self.assertIn("where health information sits", plan.emails["email_1"]["body"])
        self.assertIn("who can access it", plan.emails["email_1"]["body"])
        self.assertIn("which vendors touch it", plan.emails["email_1"]["body"])
        self.assertIn("how backups work", plan.emails["email_1"]["body"])
        self.assertIn("who reports an incident", plan.emails["email_1"]["body"])
        self.assertIn("Cyber Essentials is a practical first baseline", plan.emails["email_1"]["body"])
        self.assertIn("Want the HIA readiness map?", plan.emails["email_1"]["body"])
        self.assertIn("where health information sits", plan.emails["email_2"]["body"])
        self.assertIn("appointment", brief["data_systems_likely"])
        self.assertIn("backups", brief["data_systems_likely"])
        self.assertIn("vendor", brief["data_systems_likely"])
        self.assertIn("incident", brief["data_systems_likely"])
        self.assertEqual(brief["email_asset_offer"], "HIA readiness map")

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
        self.assertIn("health information", plan.copy_brief["personal_data_handled_guess"])
        self.assertIn("hearing-care", plan.emails["email_1"]["body"])
        self.assertIn("health-information readiness", plan.emails["email_1"]["body"])
        self.assertIn("appointments, tests and device support", plan.emails["email_1"]["body"])
        self.assertIn("appointment", plan.emails["email_2"]["body"])
        self.assertIn("test", plan.emails["email_2"]["body"])
        self.assertIn("device", plan.emails["email_2"]["body"])
        self.assertIn("hearing tests", plan.copy_brief["data_systems_likely"])
        self.assertIn("device-related records", plan.copy_brief["data_systems_likely"])
        weak_plan = o.plan_outreach(
            {
                "Id": 8,
                "company_name": "Amazing Hearing Group",
                "website_content": "Singapore retailer offering hearing aid accessories and customer service.",
            }
        )
        if weak_plan.classification["hia_confidence"] == "low":
            self.assertNotEqual(weak_plan.classification["pressure_type"], "hia_regulatory")
            if weak_plan.classification["pressure_type"] != "not_ready":
                self.assertIn("Do not lead with HIA", weak_plan.copy_brief["hia_obligation_angle"])
                self.assertIn("PDPA", weak_plan.emails["email_1"]["body"])

    def test_generic_b2b_copy_brief_uses_customer_trust(self):
        plan = o.plan_outreach(
            {
                "Id": 9,
                "company_name": "Vendor Platform Pte Ltd",
                "website_content": "B2B SaaS outsourcing platform serving enterprise clients with customer data integrations and vendor dashboards.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "customer_trust")
        brief = plan.copy_brief
        self.assertIn("security evidence", brief["customer_trust_angle"])
        self.assertIn("Customers may ask", brief["customer_trust_angle"])
        self.assertEqual(brief["email_asset_offer"], "security evidence checklist")
        self.assertIn("security questions usually come down to proof", brief["email_problem_statement"])
        self.assertIn("customer security questions", plan.emails["email_1"]["body"])
        self.assertIn("reusable security evidence", plan.emails["email_1"]["body"])
        self.assertIn("common customer security question", plan.emails["email_2"]["body"])

    def test_copy_qa_mode_bypasses_sendable_email_but_never_send_ready(self):
        result = o.plan_and_patch(
            {
                "Id": 44,
                "company_name": "Amaris B. Clinic",
                "best_url": "https://amaris-b.com/",
                "website_content": "Singapore medical clinic with doctors, treatment services, consultation and patient appointments.",
                "copy_qa_mode": True,
            },
            programmes=[verified_program()],
            copy_qa_mode=True,
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["patch"]["email_send_ready"])
        self.assertEqual(result["patch"]["human_review_status"], "ready_for_review")
        self.assertIn("copy_qa_mode", result["patch"]["email_quality_flags"])

    def test_generic_inbox_uses_team_greeting(self):
        plan = o.plan_outreach(
            {
                "Id": 45,
                "company_name": "An Dental",
                "validated_email": "contact@andental.sg",
                "best_url": "https://andental.sg/",
                "website_content": "Singapore dental clinic with patient appointments, dentists and treatment services.",
            }
        )
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hi An Dental team,"))
        self.assertNotIn("Hi -", plan.emails["email_1"]["body"])
        self.assertNotIn("generic_inbox_wrong_greeting", plan.quality_flags)

    def test_strategy_evaluator_flags_bad_email_shape(self):
        plan = o.plan_outreach(
            {
                "Id": 46,
                "company_name": "Vendor Platform Pte Ltd",
                "website_content": "B2B SaaS outsourcing platform serving enterprise clients with customer data integrations and vendor dashboards.",
            }
        )
        emails = {
            key: dict(value)
            for key, value in plan.emails.items()
            if key.startswith("email_")
        }
        emails["email_1"]["body"] = "Hi team,\n\nWe help companies improve cybersecurity.\n\nWorth a chat?"
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        emails["email_2"]["body"] = "Cyber Essentials is a recognised baseline."
        emails["email_2"]["word_count"] = o.word_count(emails["email_2"]["body"])
        emails["email_3"]["body"] = f"{plan.funding.funding_claim_line}\n\nHIA timelines and PDPA safeguards matter too."
        emails["email_3"]["word_count"] = o.word_count(emails["email_3"]["body"])
        flags = o.evaluate_email_strategy(
            {"company_name": "Vendor Platform Pte Ltd"},
            plan.classification,
            plan.funding,
            emails,
            plan.copy_brief,
        )
        self.assertIn("email_1_missing_specific_signal", flags)
        self.assertIn("email_1_missing_problem_statement", flags)
        self.assertIn("email_1_missing_mechanism_statement", flags)
        self.assertIn("email_2_not_diagnostic", flags)
        self.assertIn("email_3_not_funding_only", flags)

    def test_copy_brief_not_ready_row_keeps_empty_emails(self):
        plan = o.plan_outreach(
            {
                "Id": 10,
                "company_name": "Quiet Holdings",
                "website_content": "Singapore corporate website with a short homepage.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "not_ready")
        self.assertFalse(plan.copy_brief["email_personalisation_signal"])
        self.assertEqual(plan.human_review_status, "not_ready")
        for index in range(1, 5):
            self.assertFalse(plan.emails[f"email_{index}"]["body"])

    def test_generic_personalisation_signal_is_flagged(self):
        plan = o.plan_outreach(
            {
                "Id": 11,
                "company_name": "Example Clinic",
                "website_content": "Singapore medical clinic with patient appointments.",
            }
        )
        emails = plan.emails
        copy_brief = {**plan.copy_brief, "email_personalisation_signal": "Example Clinic appears to operate in healthcare."}
        _, flags, send_ready = o.quality_gate({"company_name": "Example Clinic"}, plan.classification, plan.funding, emails, copy_brief)
        self.assertIn("generic_personalisation_signal", flags)
        self.assertFalse(send_ready)

    def test_sendable_email_uses_validated_email_only(self):
        self.assertEqual(o.sendable_email({"validated_email": "info@exampleclinic.sg"}), "info@exampleclinic.sg")
        self.assertEqual(o.sendable_email({"selected_contact_email": "ops@exampleclinic.sg"}), "")
        self.assertEqual(o.sendable_email({}), "")

    def test_american_international_clinic_is_hia_batch_1(self):
        plan = o.plan_outreach(
            {
                "Id": 46,
                "company_name": "American International Clinic Singapore",
                "validated_email": "info@aiclinic.com.sg",
                "best_url": "https://aiclinic.com.sg/",
                "website_content": "International medical clinic in Singapore with doctors, outpatient appointments and patient treatment services.",
                "services_detected": "medical clinic; doctor consultations; outpatient appointments",
                "leadership_or_team_signals": "doctor team",
            },
            programmes=[verified_program()],
        )
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "GP_OMS")
        self.assertEqual(plan.classification["hia_timeline_batch_guess"], "Batch 1 - Sep 2027")
        self.assertTrue(plan.classification["hia_deadline_claim_safe"])
        self.assertFalse(plan.classification["pdpa_relevant"])

    def test_dental_and_pharmacy_hia_batches(self):
        dental = o.classify_row(
            {
                "company_name": "Example Dental",
                "website_content": "Outpatient dental clinic with dentists and patient appointments in Singapore.",
            }
        )
        pharmacy = o.classify_row(
            {
                "company_name": "Example Pharmacy",
                "website_content": "Retail pharmacy in Singapore with patient prescriptions and medication records.",
            }
        )
        self.assertEqual(dental["hia_service_type_guess"], "dental")
        self.assertEqual(dental["hia_timeline_batch_guess"], "Batch 3 - Mar 2030")
        self.assertEqual(pharmacy["hia_service_type_guess"], "retail_pharmacy")
        self.assertEqual(pharmacy["hia_timeline_batch_guess"], "Batch 3 - Mar 2030")

    def test_unsupported_hia_batch_types_do_not_write_invalid_select_options(self):
        renal = o.classify_row(
            {
                "company_name": "Example Dialysis Centre",
                "website_content": "Outpatient renal dialysis service with patient appointments in Singapore.",
            }
        )
        self.assertEqual(renal["hia_service_type_guess"], "unknown")
        self.assertEqual(renal["hia_timeline_batch_guess"], "Batch 2 - Sep 2028")

    def test_clinic_entity_precedence_survives_incidental_social_terms(self):
        classification = o.classify_row(
            {
                "company_name": "Amaris B. Clinic",
                "website_content": "Medical clinic with doctor treatment services. Article mentions a medical society conference.",
            }
        )
        self.assertEqual(classification["entity_type_guess"], "clinic")

    def test_ambiguous_hia_llm_can_promote_hearing_care(self):
        classification = o.classify_row(
            {
                "company_name": "Example Hearing Group",
                "website_content": "Hearing care centre with hearing tests, appointments and device fitting records.",
                "hia_llm_review": {
                    "hia_relevant": True,
                    "hia_confidence": "medium",
                    "hia_service_type_guess": "hearing_care",
                    "hia_scope_reason": "Evidence shows hearing tests and appointments.",
                    "evidence": [{"quote": "hearing tests, appointments", "source_field": "website_content", "reason": "healthcare service evidence"}],
                },
            }
        )
        self.assertEqual(classification["pressure_type"], "hia_regulatory")
        self.assertTrue(classification["hia_relevant"])
        self.assertEqual(classification["hia_service_type_guess"], "hearing_care")
        self.assertIn("LLM ambiguous-HIA review", classification["hia_scope_reason"])

    def test_ambiguous_hia_llm_can_reject_wellness_without_healthcare_scope(self):
        classification = o.classify_row(
            {
                "company_name": "Example Wellness",
                "website_content": "Corporate wellness talks and lifestyle coaching for employees.",
                "hia_llm_review": {
                    "hia_relevant": False,
                    "hia_confidence": "high",
                    "hia_service_type_guess": "unknown",
                    "hia_scope_reason": "Evidence is wellness education, not healthcare provider scope.",
                    "evidence": [{"quote": "wellness talks", "source_field": "website_content", "reason": "non-healthcare scope"}],
                },
            }
        )
        self.assertNotEqual(classification["pressure_type"], "hia_regulatory")
        self.assertFalse(classification["hia_relevant"])

    def test_hia_llm_does_not_override_high_confidence_clinic(self):
        classification = o.classify_row(
            {
                "company_name": "Example Clinic",
                "website_content": "Medical clinic with doctors, outpatient appointments and patient treatment services.",
                "hia_llm_review": {
                    "hia_relevant": False,
                    "hia_confidence": "high",
                    "hia_service_type_guess": "unknown",
                    "hia_scope_reason": "Bad review should be ignored.",
                },
            }
        )
        self.assertEqual(classification["pressure_type"], "hia_regulatory")
        self.assertTrue(classification["hia_relevant"])
        self.assertNotIn("LLM ambiguous-HIA review", classification["hia_scope_reason"])


if __name__ == "__main__":
    unittest.main()
