import json
import os
import unittest
from unittest.mock import patch

from services.crawl4ai.funding_programs import FundingMatch, FundingProgram
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
        exact_claim_allowed_in_email=True,
        exact_claim_text="Eligible SMEs can receive up to 70% support, subject to programme confirmation.",
    )


class OutreachPlannerTests(unittest.TestCase):
    def assert_no_final_email_batch_or_signal_language(self, plan):
        forbidden = ("signals", "Batch 1", "Batch 2", "Batch 3", "Sep 2027", "Sep 2028", "Mar 2030", "HIA window")
        for index in range(1, 5):
            body = plan.emails[f"email_{index}"]["body"]
            for phrase in forbidden:
                self.assertNotIn(phrase, body)

    def assert_no_email_signatures(self, emails):
        for index in range(1, 5):
            body = emails[f"email_{index}"]["body"]
            self.assertNotRegex(body, r"(?im)^\s*Best,?\s*$")
            self.assertNotRegex(body, r"(?im)^\s*SK\s*$")
            self.assertNotRegex(body, r"(?im)^\s*RAYN Secure\s*$")

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
        self.assertIn("2027", plan.emails["email_1"]["body"])
        self.assertIn("We help", plan.emails["email_1"]["body"])
        self.assertEqual(plan.copy_brief["email_hook"], plan.copy_brief["email_problem_statement"])

    def test_stale_industry_guess_does_not_override_website_content(self):
        plan = o.plan_outreach(
            {
                "Id": 101,
                "company_name": "Minmed Group Pte Ltd",
                "best_url": "https://minmed.sg/",
                "industry_guess": "Dental care",
                "website_content": "Health screening and GP clinics in Singapore with medical check-ups, vaccinations, GP consultations and Healthier SG.",
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertNotEqual(plan.classification["hia_service_type_guess"], "dental")
        self.assertNotIn("dental clinic", plan.emails["email_1"]["body"].lower())

    def test_secondary_site_links_do_not_force_dental_profile(self):
        plan = o.plan_outreach(
            {
                "Id": 102,
                "company_name": "My Health Partners",
                "best_url": "https://www.myhealthpartners.com.sg/",
                "website_content": (
                    "Welcome to My Health Partners Medical Clinic. Vaccination, Health Screening and Consultation. "
                    "Our pages also include an older dental clinic department link."
                ),
            }
        )
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertNotEqual(plan.classification["hia_service_type_guess"], "dental")
        self.assertNotIn("dental clinic", plan.emails["email_1"]["body"].lower())

    def test_strong_website_context_does_not_call_serper(self):
        original = o.fetch_serper_company_context

        def fail_fetch(row, classification, limit=5):
            raise AssertionError("serper should not be called for strong website context")

        o.fetch_serper_company_context = fail_fetch
        try:
            plan = o.plan_outreach(
                {
                    "Id": 103,
                    "company_name": "Strong Clinic Group",
                    "best_url": "https://strongclinic.example/",
                    "website_content": (
                        "Strong Clinic Group operates Singapore medical clinics with GP consultations, health screening, "
                        "vaccinations, patient appointment booking, referrals, clinic operations, doctors, nurses, patient "
                        "records, staff access, vendor systems and incident-response workflows. "
                    )
                    * 4,
                }
            )
        finally:
            o.fetch_serper_company_context = original
        self.assertEqual(plan.copy_brief["company_context_search"]["reason"], "website_context_strong")
        self.assertEqual(plan.emails["context_email_1"]["source"], "website_content")

    def test_weak_website_context_uses_serper_evidence_for_email_1_chain(self):
        original = o.fetch_serper_company_context

        def fake_fetch(row, classification, limit=5):
            return {
                "source": "serper",
                "used": True,
                "reason": "ok",
                "query": '"Thin Clinic" Singapore healthcare clinic services locations',
                "evidence": [
                    {
                        "title": "Thin Clinic Group - Singapore Medical Clinic Locations",
                        "link": "https://thinclinic.example/",
                        "snippet": "Thin Clinic Group operates medical clinic locations in Singapore with GP services and health screening.",
                    }
                ],
            }

        o.fetch_serper_company_context = fake_fetch
        try:
            plan = o.plan_outreach(
                {
                    "Id": 104,
                    "company_name": "Thin Clinic",
                    "best_url": "https://thinclinic.example/",
                    "website_content": "Medical clinic in Singapore.",
                }
            )
        finally:
            o.fetch_serper_company_context = original
        self.assertEqual(plan.copy_brief["email_hook_source"], "serper")
        self.assertIn("multi-location or group healthcare operation", plan.copy_brief["first_sentence_context"]["observation"])
        self.assertEqual(plan.emails["context_email_1"]["pressure_bridge"], plan.copy_brief["email_problem_statement"])
        self.assertIn("HIA starting from 2027", plan.emails["context_email_1"]["pressure_bridge"])
        self.assertIn("We help", plan.emails["context_email_1"]["mechanism"])
        self.assertEqual(plan.emails["company_context_search"]["source"], "serper")

    def test_thin_not_ready_row_uses_serper_before_classification(self):
        original_fetch = o.fetch_serper_company_context
        original_key = os.environ.get("SERPER_API_KEY")
        os.environ["SERPER_API_KEY"] = "test-key"

        def fake_fetch(row, classification, limit=5):
            return {
                "source": "serper",
                "used": True,
                "reason": "ok",
                "query": '"Mirxes" Singapore healthcare clinic services locations',
                "evidence": [
                    {
                        "title": "MiRXES cancer early detection tests",
                        "link": "https://www.mirxes.com/",
                        "snippet": "MiRXES provides cancer early detection, diagnostic testing and clinical laboratory services for healthcare providers.",
                    }
                ],
            }

        o.fetch_serper_company_context = fake_fetch
        try:
            plan = o.plan_outreach(
                {
                    "Id": 106,
                    "company_name": "Mirxes",
                    "best_url": "https://www.mirxes.com/",
                    "website_content": "# Mirxes - Home A NEW DAWN - In Disease Early Interception.",
                    "validated_email": "info@mirxes.example",
                }
            )
        finally:
            o.fetch_serper_company_context = original_fetch
            if original_key is None:
                os.environ.pop("SERPER_API_KEY", None)
            else:
                os.environ["SERPER_API_KEY"] = original_key

        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "diagnostic")
        self.assertEqual(plan.emails["company_context_search"]["source"], "serper")

    def test_thin_social_service_row_uses_serper_for_pdpa_track(self):
        original_fetch = o.fetch_serper_company_context
        original_key = os.environ.get("SERPER_API_KEY")
        os.environ["SERPER_API_KEY"] = "test-key"

        def fake_fetch(row, classification, limit=5):
            return {
                "source": "serper",
                "used": True,
                "reason": "ok",
                "query": '"Montfort Care" Singapore services personal data operations',
                "evidence": [
                    {
                        "title": "Montfort Care community services",
                        "link": "https://montfortcare.org.sg/",
                        "snippet": "Montfort Care is a social service agency supporting individuals, families, beneficiaries and community programmes.",
                    }
                ],
            }

        o.fetch_serper_company_context = fake_fetch
        try:
            plan = o.plan_outreach(
                {
                    "Id": 107,
                    "company_name": "Montfort Care",
                    "best_url": "https://montfortcare.org.sg/",
                    "website_content": "Montfort Care is a network of community-based services.",
                    "validated_email": "hello@montfort.example",
                }
            )
        finally:
            o.fetch_serper_company_context = original_fetch
            if original_key is None:
                os.environ.pop("SERPER_API_KEY", None)
            else:
                os.environ["SERPER_API_KEY"] = original_key

        self.assertEqual(plan.classification["pressure_type"], "pdpa_safeguards")
        self.assertFalse(plan.classification["hia_relevant"])
        self.assertIn("PDPA", plan.emails["email_1"]["body"])

    def test_email_display_company_name_strips_legal_suffix_and_location(self):
        self.assertEqual(
            o.email_display_company_name({"company_name": "Mission (Hougang) Medical Clinic Pte Ltd"}),
            "Mission Medical Clinic",
        )
        self.assertEqual(
            o.email_display_company_name({"company_name": "Dr Panda Medical Centre @ Sin Ming"}),
            "Dr Panda Medical Centre",
        )
        plan = o.plan_outreach(
            {
                "Id": 105,
                "company_name": "Mission (Hougang) Medical Clinic Pte Ltd",
                "best_url": "https://mission.example/",
                "website_content": "Singapore medical clinic providing doctor consultations, appointment booking and patient treatment services.",
            }
        )
        self.assertIn("Mission Medical Clinic", plan.emails["email_1"]["body"])
        self.assertNotIn("Mission (Hougang) Medical Clinic Pte Ltd", plan.emails["email_1"]["body"])

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
        self.assertIn("PDPA is the legal responsibility", plan.emails["email_1"]["body"])
        self.assertIn("hard part is usually proving safeguards", plan.emails["email_1"]["body"])
        self.assertIn("Cyber Essentials", plan.emails["email_1"]["body"])
        self.assertIn("We help", plan.emails["email_1"]["body"])
        self.assertNotIn("Cyber Essentials makes", plan.emails["email_1"]["body"])

    def test_entity_type_keeps_social_service_separate_from_hia_pressure(self):
        plan = o.plan_outreach(
            {
                "Id": 301,
                "company_name": "Community Care Foundation",
                "website_content": (
                    "Singapore charity IPC and social service agency supporting beneficiaries, "
                    "volunteers and community care programmes."
                ),
            }
        )
        self.assertEqual(plan.classification["entity_type_guess"], "charity")
        self.assertEqual(plan.classification["pressure_type"], "pdpa_safeguards")
        self.assertFalse(plan.classification["hia_relevant"])

    def test_long_term_care_can_be_social_entity_but_hia_pressure(self):
        plan = o.plan_outreach(
            {
                "Id": 302,
                "company_name": "Example Mission Nursing Home",
                "website_content": (
                    "Singapore mission society running a nursing home with resident care, "
                    "patient care at home and palliative services."
                ),
            }
        )
        self.assertEqual(plan.classification["entity_type_guess"], "social_service")
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "long_term_care")

    def test_generic_healthcare_marketplace_does_not_become_hia(self):
        plan = o.plan_outreach(
            {
                "Id": 303,
                "company_name": "Health Vendor Platform Pte Ltd",
                "website_content": (
                    "Singapore software platform for healthcare suppliers, enterprise clients, "
                    "procurement teams, customer accounts and vendor reviews."
                ),
            }
        )
        self.assertEqual(plan.classification["entity_type_guess"], "private_company")
        self.assertEqual(plan.classification["pressure_type"], "customer_trust")
        self.assertFalse(plan.classification["hia_relevant"])

    def test_pdpa_industry_variants(self):
        cases = [
            (
                "Training Centre",
                "Education and training provider handling student, parent, staff and enrolment records.",
                "education/training services handling student, parent, staff or enrolment records",
                "education data checklist",
            ),
            (
                "Talent Search Pte Ltd",
                "Recruitment firm handling candidate records, payroll data, employee records and client records.",
                "HR/recruitment services handling candidate, employee and client records",
                "HR data safeguards checklist",
            ),
            (
                "Account Admin Pte Ltd",
                "Accounting, finance and admin services handling client financial records, payroll and business records.",
                "admin/accounting/finance services handling client financial or business records",
                "client data safeguards checklist",
            ),
            (
                "Retail Support Pte Ltd",
                "Retail e-commerce customer service operations handling customer orders, support and payment-related records.",
                "customer-facing operations handling customer, order, support and payment-related records",
                "customer data checklist",
            ),
            (
                "Care Volunteers Society",
                "Charity social service organisation handling beneficiary, volunteer, donor and staff data.",
                "care/community-service setting handling beneficiary, volunteer, donor and staff data",
                "care-organisation checklist",
            ),
        ]
        for company, content, profile, asset in cases:
            with self.subTest(company=company):
                plan = o.plan_outreach({"company_name": company, "website_content": content})
                self.assertEqual(plan.classification["pressure_type"], "pdpa_safeguards")
                self.assertIn(profile, plan.emails["email_1"]["body"])
                self.assertEqual(plan.copy_brief["email_asset_offer"], asset)
                self.assertIn("PDPA is the legal responsibility", plan.emails["email_1"]["body"])
                self.assertNotIn("PDPA compliant", plan.emails["email_1"]["body"])

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
        self.assertIn(plan.emails["email_1"]["chosen_subject"], {"data protection evidence", "evidence checklist", "data evidence"})
        self.assertIn("data-protection / operations contact route", plan.emails["email_1"]["body"])
        self.assertRegex(plan.emails["email_1"]["body"], r"proof|evidence")

    def test_data_protection_owner_titles_use_evidence_angle(self):
        for title in ("DPO", "Operations Manager", "HR/Admin Manager"):
            with self.subTest(title=title):
                plan = o.plan_outreach(
                    {
                        "company_name": "Acme Services Pte Ltd",
                        "selected_contact_title": title,
                        "website_content": "Singapore private company handling customer records, employee data and vendor tools.",
                    }
                )
                self.assertEqual(plan.classification["campaign_track"], "dpo_evidence")
                self.assertEqual(plan.emails["email_1"]["chosen_subject"], "data protection evidence")
                self.assertIn("data-protection / operations contact route", plan.emails["email_1"]["body"])
                self.assertRegex(plan.emails["email_1"]["body"], r"proof|evidence")
                self.assertNotIn("is responsible for compliance", plan.emails["email_1"]["body"])

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
        self.assertIn(plan.emails["email_1"]["chosen_subject"], {"customer security evidence", "security evidence", "customer checklist"})
        self.assertRegex(plan.emails["email_1"]["body"], r"security proof|customer review|customers")
        self.assertIn("Cyber Essentials", plan.emails["email_1"]["body"])
        self.assertIn("customer security question", plan.emails["email_3"]["body"])
        self.assertNotIn("Cyber Essentials is", plan.emails["email_3"]["body"])

    def test_sentence_slot_rotation_is_deterministic(self):
        row = {
            "Id": 132,
            "campaign_id": "cold_email_may",
            "company_name": "Vendor Platform Pte Ltd",
            "website_content": "Singapore SaaS platform for enterprise clients with user data, admin access and procurement reviews.",
        }
        first = o.plan_outreach(row)
        second = o.plan_outreach(dict(row))
        self.assertEqual(first.emails["email_1"]["chosen_subject"], second.emails["email_1"]["chosen_subject"])
        self.assertEqual(first.emails["email_1"]["body"], second.emails["email_1"]["body"])
        self.assertNotIn("variant_id", first.emails["email_1"])
        self.assertIn("sentence_slot_metadata", first.emails)
        self.assertEqual(first.emails["sentence_slot_metadata"], second.emails["sentence_slot_metadata"])
        slot = o.sentence_slot_choice(row, first.classification, 2, "cost_opener", {"a": "A", "b": "B"})
        self.assertEqual(slot, o.sentence_slot_choice(dict(row), first.classification, 2, "cost_opener", {"a": "A", "b": "B"}))

    def test_sentence_slot_metadata_is_stored_only_inside_email_sequence_json(self):
        result = o.plan_and_patch(
            {
                "Id": 132,
                "campaign_id": "cold_email_may",
                "company_name": "Vendor Platform Pte Ltd",
                "validated_email": "info@vendor.example",
                "website_content": "Singapore SaaS platform for enterprise clients with user data, admin access and procurement reviews.",
            }
        )
        patch = result["patch"]
        sequence = json.loads(patch["email_sequence_json"])
        self.assertIn("sentence_slot_metadata", sequence)
        self.assertEqual(sequence["sentence_slot_metadata"]["selector"], "sha256(row_id:campaign_id:track:pressure_type:email_step:slot_name)")
        self.assertIn("problem_line", sequence["sentence_slot_metadata"]["email_steps"]["email_1"])
        self.assertNotIn("variant_metadata", patch)
        for index in range(1, 5):
            self.assertNotIn(f"email_{index}_variant_id", patch)

    def test_email_1_llm_rewrite_can_replace_deterministic_copy_when_qa_passes(self):
        captured = {}

        def fake_rewrite(payload):
            captured.update(payload)
            return {
                "subject": payload["deterministic_subject"],
                "body": (
                    "Hi Ivan, saw that Example Medical Clinic is a family clinic offering GP-style consultations.\n\n"
                    f"{payload['approved_problem']}\n\n"
                    f"{payload['approved_mechanism']}\n\n"
                    f"{payload['approved_cta']}"
                ),
                "notes": ["kept approved facts"],
            }

        with patch.object(o, "email_1_llm_rewrite_enabled", return_value=True), patch.object(o, "call_email_1_rewrite_llm", side_effect=fake_rewrite):
            plan = o.plan_outreach(
                {
                    "Id": 901,
                    "company_name": "Example Medical Clinic",
                    "selected_contact_name": "Ivan Tan",
                    "validated_email": "ivan@example.com",
                    "website_content": "Family clinic with doctors, patient appointments, consultation notes and patient services.",
                    "openrouter_allowed": True,
                    "use_llm_humaniser": True,
                    "skip_openrouter": False,
                },
                programmes=[verified_program()],
            )

        self.assertTrue(plan.emails["llm_email_1_rewrite"]["used"])
        self.assertIn("llm_email_1_rewrite_used", plan.quality_flags)
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hi Ivan, saw that"))
        self.assertIn("approved_problem", captured)

    def test_email_1_llm_rewrite_rejects_one_paragraph_output(self):
        def one_paragraph(payload):
            return {
                "subject": payload["deterministic_subject"],
                "body": (
                    "Hi Ivan, saw that Example Medical Clinic is a family clinic offering GP-style consultations. "
                    f"{payload['approved_problem']} {payload['approved_mechanism']} {payload['approved_cta']}"
                ),
                "notes": [],
            }

        with patch.object(o, "email_1_llm_rewrite_enabled", return_value=True), patch.object(o, "call_email_1_rewrite_llm", side_effect=one_paragraph):
            plan = o.plan_outreach(
                {
                    "Id": 903,
                    "company_name": "Example Medical Clinic",
                    "selected_contact_name": "Ivan Tan",
                    "validated_email": "ivan@example.com",
                    "website_content": "Family clinic with doctors, patient appointments, consultation notes and patient services.",
                    "openrouter_allowed": True,
                    "use_llm_humaniser": True,
                    "skip_openrouter": False,
                },
                programmes=[verified_program()],
            )

        self.assertFalse(plan.emails["llm_email_1_rewrite"]["used"])
        self.assertIn("llm_email_1_rewrite_paragraph_shape", plan.emails["llm_email_1_rewrite"]["flags"])

    def test_email_1_llm_rewrite_falls_back_when_qa_rejects(self):
        def bad_rewrite(_payload):
            return {
                "subject": "growth",
                "body": "Hi Ivan, we can unlock potential and transform your security.",
                "notes": [],
            }

        with patch.object(o, "email_1_llm_rewrite_enabled", return_value=True), patch.object(o, "call_email_1_rewrite_llm", side_effect=bad_rewrite):
            plan = o.plan_outreach(
                {
                    "Id": 902,
                    "company_name": "Example Medical Clinic",
                    "selected_contact_name": "Ivan Tan",
                    "validated_email": "ivan@example.com",
                    "website_content": "Family clinic with doctors, patient appointments, consultation notes and patient services.",
                    "openrouter_allowed": True,
                    "use_llm_humaniser": True,
                    "skip_openrouter": False,
                },
                programmes=[verified_program()],
            )

        self.assertFalse(plan.emails["llm_email_1_rewrite"]["used"])
        self.assertIn("qa_rejected", plan.emails["llm_email_1_rewrite"]["reason"])
        self.assertNotIn("unlock potential", plan.emails["email_1"]["body"].lower())
        self.assertTrue(any(flag.startswith("llm_email_1_rewrite_rejected:") for flag in plan.quality_flags))

    def test_variant_bank_has_multiple_approved_options_per_track_and_step(self):
        for track in ("hia_regulatory", "pdpa_safeguards", "dpo_evidence", "customer_trust"):
            with self.subTest(track=track):
                segment_bank = next(iter(o.TRACK_SEGMENT_SUBJECT_VARIANTS[track].values()))
                for step in (1, 2, 3, 4):
                    self.assertGreaterEqual(len(segment_bank[step]), 2)

    def test_rotated_templates_avoid_ai_vocabulary_and_keep_signatures_out(self):
        rows = [
            {"Id": 201, "company_name": "Heart Centre", "website_content": "Specialist heart cardiology clinic offering ECG, echocardiogram, referrals and cardiac consultations."},
            {"Id": 202, "company_name": "Acme Training", "website_content": "Education and training provider handling student, parent, staff and enrolment records."},
            {"Id": 203, "company_name": "Vendor Platform Pte Ltd", "website_content": "B2B SaaS platform for enterprise customers with user data and admin access."},
        ]
        forbidden = ("delve", "landscape", "leverage", "tapestry", "moreover", "furthermore", "additionally", "pivotal moment")
        for row in rows:
            with self.subTest(company=row["company_name"]):
                plan = o.plan_outreach(row, programmes=[verified_program()])
                for index in range(1, 5):
                    body = plan.emails[f"email_{index}"]["body"].lower()
                    for word in forbidden:
                        self.assertNotIn(word, body)
                self.assert_no_email_signatures(plan.emails)

    def test_sentence_slot_rotations_pass_quality_gate_guardrails(self):
        cases = [
            (
                "hia_regulatory",
                {
                    "company_name": "AMK Family Clinic",
                    "website_content": "Singapore family clinic with doctors, outpatient consultations, patient appointments and treatment services.",
                },
                [verified_program()],
            ),
            (
                "pdpa_safeguards",
                {
                    "company_name": "Acme Training Pte Ltd",
                    "website_content": "Singapore private education and training provider handling student, parent, staff and enrolment records for courses.",
                },
                [],
            ),
            (
                "dpo_evidence",
                {
                    "company_name": "Acme Services Pte Ltd",
                    "selected_contact_title": "Operations Manager",
                    "website_content": "Singapore private company handling customer records, employee data and vendor tools.",
                },
                [],
            ),
            (
                "customer_trust",
                {
                    "company_name": "Vendor Platform Pte Ltd",
                    "website_content": "B2B SaaS platform for enterprise clients with user data, admin access, backups and procurement reviews.",
                },
                [],
            ),
        ]
        forbidden = ("signals", "Batch 1", "Batch 2", "Batch 3", "Sep 2027", "Sep 2028", "Mar 2030", "HIA window")
        for expected_track, base_row, programmes in cases:
            seen = {index: set() for index in range(1, 5)}
            for row_id in range(1, 80):
                row = {**base_row, "Id": row_id, "campaign_id": f"{expected_track}_variant_test"}
                plan = o.plan_outreach(row, programmes=programmes)
                self.assertEqual(o.email_variant_track(plan.classification), expected_track)
                self.assertEqual(plan.quality_flags, [])
                slot_steps = plan.emails["sentence_slot_metadata"]["email_steps"]
                for index in range(1, 5):
                    item = plan.emails[f"email_{index}"]
                    seen[index].update(slot_steps.get(f"email_{index}", {}).values())
                    for phrase in forbidden:
                        self.assertNotIn(phrase, item["body"])
                self.assertIn(plan.copy_brief["email_problem_statement"], plan.emails["email_1"]["body"])
                self.assertIn(plan.copy_brief["email_mechanism_statement"], plan.emails["email_1"]["body"])
                self.assertIn(plan.copy_brief["email_cta"], plan.emails["email_1"]["body"])
                email1_first = plan.emails["email_1"]["body"].splitlines()[0]
                self.assertRegex(email1_first, r", (?:I noticed|saw that|looks like|had a quick look at|for )")
                self.assertNotIn("from the site", email1_first.lower())
                if plan.email_2_mode == "funding" and not o.hia_pricing_active(plan.classification, plan.copy_brief):
                    self.assertTrue(o.funding_only_email(plan.emails["email_2"]["body"], plan.funding.funding_claim_line))
                elif o.hia_pricing_active(plan.classification, plan.copy_brief):
                    self.assertIn("CISOaaS", plan.emails["email_2"]["body"])
                    self.assertLessEqual(plan.emails["email_2"]["body"].lower().count("size it"), 1)
                elif not o.hia_pricing_active(plan.classification, plan.copy_brief):
                    self.assertNotIn("funding", plan.emails["email_2"]["body"].lower())
            for index in range(1, 5):
                self.assertGreaterEqual(len(seen[index]), 2)

    def test_customer_trust_buyer_context_variants(self):
        cases = [
            (
                "SaaS Platform Pte Ltd",
                "SaaS platform for enterprise clients with user data, admin access, backups and procurement reviews.",
                "customers who may ask how user data, admin access and backups are controlled",
                "customer security evidence checklist",
            ),
            (
                "Advisory Partners Pte Ltd",
                "Professional services consulting firm working with business customers and client data before procurement reviews.",
                "business customers who may ask for reusable security evidence before sharing data",
                "security evidence checklist",
            ),
            (
                "Recruitment Vendor Pte Ltd",
                "Recruitment HR vendor working with clients who share candidate and employee data.",
                "clients who may ask how candidate and employee data is protected",
                "client security evidence checklist",
            ),
            (
                "Outsourcing Vendor Pte Ltd",
                "Outsourcing vendor and managed service supplier where customers ask for supplier security evidence.",
                "works as a vendor where customers may ask for supplier security evidence",
                "vendor security evidence checklist",
            ),
        ]
        for company, content, profile, asset in cases:
            with self.subTest(company=company):
                plan = o.plan_outreach({"company_name": company, "website_content": content})
                self.assertEqual(plan.classification["pressure_type"], "customer_trust")
                self.assertIn(profile, plan.emails["email_1"]["body"])
                self.assertEqual(plan.copy_brief["email_asset_offer"], asset)
                self.assertRegex(plan.emails["email_1"]["body"], r"security proof|customer review|customers")

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

    def test_email_2_uses_funding_claim_line_only(self):
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
        self.assertEqual(plan.email_2_mode, "funding")
        self.assertEqual(plan.funding_followup_mode, "funding")
        self.assertEqual(plan.email_3_mode, "funding")
        self.assertIn(claim, plan.emails["email_2"]["body"])
        self.assertNotIn("HIA timelines", plan.emails["email_2"]["body"])
        self.assertNotIn("PDPA", plan.emails["email_2"]["body"])
        self.assert_no_email_signatures(plan.emails)

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
        self.assertEqual(patch["email_2_mode"], "value_fallback")
        self.assertEqual(patch["funding_followup_mode"], "value_fallback")
        self.assertEqual(patch["email_3_mode"], "value_fallback")
        self.assertNotIn("funding_not_verified", patch["email_quality_flags"])
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
        self.assertEqual(partial_funding_patch["email_2_mode"], "value_fallback")
        self.assertEqual(partial_funding_patch["funding_followup_mode"], "value_fallback")
        self.assertEqual(partial_funding_patch["email_3_mode"], "value_fallback")
        self.assertNotIn("support route", partial_funding_patch["email_2_body"].lower())
        self.assertIn("safeguards checklist?", partial_funding_patch["email_2_body"])
        self.assertNotIn("email_2_missing_funding_claim_line", partial_funding_patch["email_quality_flags"])

    def test_plan_and_patch_includes_compact_audit_report(self):
        result = o.plan_and_patch(
            {
                "Id": 46,
                "company_name": "Amaris B. Clinic",
                "services_detected": ["aesthetic clinic services", "doctor consultations"],
                "leadership_or_team_signals": ["doctor and practitioner team"],
                "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
                "copy_qa_mode": True,
            },
            programmes=[verified_program()],
            copy_qa_mode=True,
        )
        audit = result["audit_report"]
        self.assertEqual(
            set(audit),
            {
                "row_id",
                "company_name",
                "pressure_type",
                "hia_service_type_guess",
                "hia_timeline_batch_guess",
                "funding_status",
                "email_quality_flags",
                "contains_hia_batch_wording",
                "asset_offer_too_generic_for_segment",
                "email_3_generic_hia_diagnostic",
                "clinic_profile_guess",
                "clinic_profile_phrase",
                "clinic_structure_guess",
                "clinic_structure_confidence",
                "umbrella_or_group_guess",
                "primary_service_summary",
                "clinic_structure_evidence",
                "email_1_subject",
                "email_1_body",
                "email_2_subject",
                "email_2_body",
                "email_3_subject",
                "email_3_body",
                "email_4_subject",
                "email_4_body",
                "automation_decision",
                "automation_decision_reason",
                "automation_blockers_json",
                "automation_advisory_flags_json",
                "contact_send_mode",
                "contact_identity_confidence",
                "email_2_mode",
                "funding_followup_mode",
                "email_3_mode",
                "clinic_size_guess",
                "clinic_size_confidence",
                "endpoint_band_guess",
                "endpoint_band_confidence",
                "pricing_email_2_mode",
                "pricing_claim_safe",
                "pricing_claim_line",
                "pricing_evidence_json",
                "enrichment_quality_score",
                "enrichment_quality_flags",
                "copy_brief_quality_score",
                "copy_brief_quality_flags",
                "severe_email_flags",
                "final_send_gate_passed",
            },
        )
        self.assertEqual(audit["row_id"], 46)
        self.assertEqual(audit["company_name"], "Amaris B. Clinic")
        self.assertEqual(audit["pressure_type"], "hia_regulatory")
        self.assertEqual(audit["funding_status"], result["patch"]["funding_status"])
        self.assertFalse(audit["contains_hia_batch_wording"])
        self.assertFalse(audit["asset_offer_too_generic_for_segment"])
        self.assertFalse(audit["email_3_generic_hia_diagnostic"])
        self.assertEqual(audit["email_1_subject"], result["patch"]["email_1_subject"])
        self.assertEqual(audit["email_1_body"], result["patch"]["email_1_body"])
        self.assertEqual(audit["email_4_subject"], result["patch"]["email_4_subject"])
        self.assertEqual(audit["email_4_body"], result["patch"]["email_4_body"])
        self.assertIsInstance(audit["email_quality_flags"], list)

    def test_draft_only_forces_not_send_ready_and_funding_caveat_not_duplicated(self):
        result = o.plan_and_patch(
            {
                "Id": 47,
                "company_name": "Amaris B. Clinic",
                "services_detected": ["aesthetic clinic services", "doctor consultations"],
                "leadership_or_team_signals": ["doctor and practitioner team"],
                "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
                "validated_email": "ivan@example.com",
                "selected_contact_name": "Ivan Puah",
                "email_validation_status": "deliverable",
                "draft_only": True,
            },
            programmes=[verified_program()],
        )
        self.assertFalse(result["patch"]["email_send_ready"])
        self.assertLessEqual(result["patch"]["email_2_body"].count("subject to programme confirmation"), 1)
        self.assertNotIn("Best,", result["patch"]["email_2_body"])
        self.assertNotIn("RAYN Secure", result["patch"]["email_2_body"])

    def test_automation_suppresses_blocked_or_missing_contact_rows(self):
        cases = [
            ({"do_not_contact": True, "validated_email": "info@example.com"}, "suppressed_do_not_contact"),
            ({"unsubscribe_status": "unsubscribed", "validated_email": "info@example.com"}, "suppressed_unsubscribed"),
            ({}, "suppressed_missing_validated_email"),
        ]
        for extra, reason in cases:
            with self.subTest(reason=reason):
                result = o.plan_and_patch(
                    {
                        "Id": 70,
                        "company_name": "Acme Services Pte Ltd",
                        "website_content": "Singapore company collecting customer enquiries and employee data.",
                        **extra,
                    }
                )
                self.assertEqual(result["patch"]["automation_decision"], "suppressed")
                self.assertEqual(result["patch"]["automation_decision_reason"], reason)
                self.assertFalse(result["patch"]["email_1_body"])

    def test_missing_validated_email_is_suppressed_without_openrouter_or_bodies(self):
        result = o.plan_and_patch(
            {
                "Id": 170,
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
            }
        )
        patch = result["patch"]
        self.assertEqual(patch["automation_decision"], "suppressed")
        self.assertEqual(patch["automation_decision_reason"], "suppressed_missing_validated_email")
        self.assertEqual(patch["automation_blockers_json"], "[\"suppressed_missing_validated_email\"]")
        self.assertFalse(result["openrouter_allowed"])
        self.assertTrue(result["skip_openrouter"])
        self.assertFalse(patch["email_send_ready"])
        self.assertFalse(patch["final_send_gate_passed"])
        self.assertEqual(patch["email_quality_flags"], "[]")
        self.assertIn("email_1_missing_problem_statement", patch["severe_email_flags"])
        for index in range(1, 5):
            self.assertFalse(patch[f"email_{index}_body"])

    def test_copy_qa_mode_allows_missing_email_without_send_ready(self):
        result = o.plan_and_patch(
            {
                "Id": 71,
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "copy_qa_mode": True,
            },
            copy_qa_mode=True,
        )
        self.assertEqual(result["patch"]["automation_decision"], "draft_only_review")
        self.assertFalse(result["patch"]["email_send_ready"])
        self.assertFalse(result["patch"]["final_send_gate_passed"])
        self.assertTrue(result["patch"]["email_1_body"])

    def test_contact_send_mode_named_generic_and_unresolved_personal(self):
        named = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "ivan@example.com",
                "selected_contact_name": "Ivan Puah",
            }
        )
        self.assertEqual(named["patch"]["contact_send_mode"], "named_person")
        self.assertIn(named["patch"]["contact_identity_confidence"], {"medium", "high"})
        self.assertTrue(named["patch"]["email_1_body"].startswith("Hi Ivan,"))

        generic = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "info@example.com",
            }
        )
        self.assertEqual(generic["patch"]["contact_send_mode"], "generic_team")
        self.assertEqual(generic["patch"]["contact_identity_confidence"], "none")
        self.assertTrue(generic["patch"]["email_1_body"].startswith("Hello team,"))

        generic_with_name = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "info@example.com",
                "selected_contact_name": "Ivan Puah",
            }
        )
        self.assertEqual(generic_with_name["patch"]["contact_send_mode"], "generic_team")
        self.assertTrue(generic_with_name["patch"]["email_1_body"].startswith("Hi Ivan,"))

        weak_named = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "randomperson@example.com",
                "selected_contact_name": "Ivan Puah",
            }
        )
        self.assertEqual(weak_named["patch"]["automation_decision"], "auto_send_eligible")
        self.assertEqual(weak_named["patch"]["contact_identity_confidence"], "low")
        self.assertEqual(weak_named["patch"]["contact_send_mode"], "generic_team")
        self.assertTrue(weak_named["patch"]["email_1_body"].startswith("Hi Ivan,"))

        unresolved = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "randomperson@example.com",
            }
        )
        self.assertEqual(unresolved["patch"]["contact_send_mode"], "generic_team")
        self.assertNotEqual(unresolved["patch"]["automation_decision_reason"], "unresolved_personal_email_identity")
        self.assertTrue(unresolved["patch"]["email_1_body"].startswith("Hello team,"))

        non_person_name = o.plan_and_patch(
            {
                "company_name": "Artisan Sports & Orthopaedics Clinic",
                "website_content": "Specialist orthopaedic clinic offering sports medicine consultations, imaging referrals and treatment plans.",
                "validated_email": "committee@example.com",
                "selected_contact_name": "Committee Memberships",
            },
            programmes=[verified_program()],
        )
        self.assertEqual(non_person_name["patch"]["contact_send_mode"], "generic_team")
        self.assertEqual(non_person_name["patch"]["contact_identity_confidence"], "none")
        self.assertTrue(non_person_name["patch"]["email_1_body"].startswith("Hello team,"))

    def test_unsafe_funding_uses_value_fallback_without_review(self):
        result = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "info@example.com",
            }
        )
        self.assertEqual(result["patch"]["email_3_mode"], "value_fallback")
        self.assertEqual(result["patch"]["email_2_mode"], "value_fallback")
        self.assertEqual(result["patch"]["funding_followup_mode"], "value_fallback")
        self.assertEqual(result["patch"]["automation_decision"], "auto_send_eligible")
        self.assertEqual(result["patch"]["automation_decision_reason"], "funding_claim_not_safe_used_value_fallback")
        self.assertNotIn("funding", result["patch"]["email_2_body"].lower())
        self.assertNotIn("you qualify", result["patch"]["email_2_body"].lower())
        self.assertIn("safeguards checklist?", result["patch"]["email_2_body"])

    def test_funding_requires_verified_current_matched_programme(self):
        row = {
            "company_name": "Amaris B. Clinic",
            "website_content": "Aesthetic medical clinic with doctors, treatments and patient appointments.",
        }
        classification = o.classify_row(row)
        unsafe_funding = FundingMatch(
            funding_status="verified_match",
            funding_relevant=True,
            primary_funding_program="Cyber Essentials",
            matched=[],
            funding_claim_line="Based on the company profile, the Cyber Essentials support route appears worth checking for Amaris B. Clinic.",
            funding_confidence="high",
        )
        brief = o.build_copy_brief(row, classification, unsafe_funding)
        self.assertFalse(o.funding_claim_send_safe(unsafe_funding, brief, classification))

        matched = o.plan_outreach(
            row,
            programmes=[verified_program()],
        )
        self.assertEqual(matched.copy_brief["email_3_mode"], "funding")
        self.assertEqual(matched.copy_brief["email_2_mode"], "funding")
        self.assertEqual(matched.copy_brief["funding_followup_mode"], "funding")
        self.assertTrue("endpoint-based" in matched.emails["email_2"]["body"] or "endpoint count" in matched.emails["email_2"]["body"])
        self.assertIn("S$4,300 before funding", matched.emails["email_2"]["body"])

    def test_send_readiness_distinguishes_gate_from_draft_mode(self):
        row = {
            "company_name": "Acme Services Pte Ltd",
            "website_content": "Singapore company collecting customer enquiries and employee data.",
            "validated_email": "info@example.com",
        }
        draft = o.plan_and_patch({**row, "draft_only": True})
        self.assertEqual(draft["patch"]["automation_decision"], "auto_send_eligible")
        self.assertEqual(draft["patch"]["human_review_status"], "not_required")
        self.assertTrue(draft["patch"]["final_send_gate_passed"])
        self.assertFalse(draft["patch"]["email_send_ready"])

        send = o.plan_and_patch({**row, "send_mode": True})
        self.assertEqual(send["patch"]["automation_decision"], "auto_send_eligible")
        self.assertEqual(send["patch"]["human_review_status"], "not_required")
        self.assertTrue(send["patch"]["final_send_gate_passed"])
        self.assertTrue(send["patch"]["email_send_ready"])

    def test_advisory_flags_do_not_become_blockers_when_score_passes(self):
        result = o.plan_and_patch(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
                "validated_email": "info@example.com",
            }
        )
        blockers = result["patch"]["automation_blockers_json"]
        advisory = result["patch"]["automation_advisory_flags_json"]
        self.assertNotIn("low_trigger_confidence", blockers)
        self.assertIn("funding_next_check_needed", advisory)
        self.assertEqual(result["patch"]["automation_decision"], "auto_send_eligible")

    def test_bad_llm_copy_falls_back_to_deterministic_strategy(self):
        row = {
            "Id": 44,
            "company_name": "Amaris B. Clinic",
            "services_detected": ["aesthetic clinic services", "doctor consultations"],
            "leadership_or_team_signals": ["doctor and practitioner team"],
            "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        bad_emails = o.normalize_llm_email_sequence(
            {
                "email_1": {"chosen_subject": "checking in", "body": "Hi team,\n\nI noticed your company and wanted to discuss cybersecurity.\n\nBest,\nSK"},
                "email_2": {"chosen_subject": "funding", "body": f"{plan.funding.funding_claim_line}\n\nHIA timelines and PDPA safeguards matter too."},
                "email_3": {"chosen_subject": "Re: checking in", "body": "Cyber Essentials is a baseline certification."},
                "email_4": {"chosen_subject": "close", "body": "Should I close the loop?"},
            }
        )
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding, bad_emails, plan.copy_brief)
        self.assertIn("medical/aesthetic clinic with doctor-led consultations", patch["email_1_body"])
        self.assertNotIn("signals", patch["email_1_body"].lower())
        self.assertIn("HIA", patch["email_1_body"])
        self.assertNotRegex(patch["email_1_body"], r"Batch 1|Batch 2|Batch 3|Sep 2027|Sep 2028|Mar 2030|HIA window")
        self.assertIn("llm_email_strategy_rejected:email_1_too_generic", patch["email_quality_flags"])
        self.assertNotIn("email_2_not_funding_only", patch["email_quality_flags"])

    def test_hia_question_hook_strips_company_prefixed_operates_signal(self):
        row = {
            "company_name": "Mother and Child Singapore",
            "website_content": "Women's and children's clinic in Singapore with patient appointments and consultations.",
        }
        classification = {
            "pressure_type": "hia_regulatory",
            "regulatory_driver": "HIA",
            "hia_relevant": True,
            "hia_service_type_guess": "GP_OMS",
        }
        copy_brief = {
            "prospect_facing_signal": "Mother and Child Singapore operates a multi-location or group healthcare operation",
            "clinic_profile_phrase": "multi-location or group healthcare operation",
        }
        first_sentence = o.email_1_question_hook(row, classification, copy_brief, row["company_name"])

        self.assertIn("For a multi-location or group healthcare operation like Mother and Child Singapore", first_sentence)
        self.assertNotIn("for Mother and Child Singapore operates", first_sentence.lower())

    def test_hia_email_3_wrong_segment_shape_falls_back_to_deterministic_strategy(self):
        row = {
            "Id": 48,
            "company_name": "Amber Compounding Pharmacy",
            "website_content": "Retail pharmacy and compounding pharmacy with prescriptions, dispensing, compounding and customer services.",
            "validated_email": "contact@example.com",
            "draft_only": True,
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        bad_emails = {
            key: dict(value)
            for key, value in plan.emails.items()
            if key.startswith("email_")
        }
        bad_emails["email_3"]["body"] = (
            "Hi Amber Compounding Pharmacy team,\n\n"
            "Appointment forms, patient records, clinic email, vendor systems, backups and incident-reporting steps "
            "should be checked for access mapping and controls. This directly addresses whether your prescription, "
            "dispensing and compounding records are clearly handled. Open to a practical diagnostic review?"
        )
        bad_emails["email_3"]["word_count"] = o.word_count(bad_emails["email_3"]["body"])
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding, bad_emails, plan.copy_brief)
        self.assertIn("prescription, dispensing, compounding, customer and supplier records", patch["email_3_body"])
        self.assertIn("backups", patch["email_3_body"])
        self.assertIn("incident", patch["email_3_body"])
        self.assertNotIn("clinic email", patch["email_3_body"])
        self.assertIn("llm_email_strategy_rejected:email_3_not_hia_segment_diagnostic_shape", patch["email_quality_flags"])

    def test_hia_profile_and_diagnostic_flags_block_final_send_gate(self):
        row = {
            "Id": 49,
            "company_name": "Heart Specialist Clinic",
            "website_content": "Specialist heart cardiology clinic offering ECG, echocardiogram, referrals and cardiac consultations.",
            "validated_email": "contact@example.com",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        flags = ["email_1_missing_clinic_profile", "email_3_not_hia_segment_diagnostic_shape"]
        decision, reason, blockers, final_gate = o.automation_decision_for(
            row,
            plan.classification,
            plan.funding,
            plan.copy_brief,
            plan.emails,
            8,
            flags,
            plan.enrichment_quality_score,
            plan.enrichment_quality_flags,
            plan.copy_brief_quality_score,
            plan.copy_brief_quality_flags,
        )
        self.assertEqual(decision, "auto_skipped")
        self.assertEqual(reason, "copy_failed_after_llm_and_deterministic_fallback")
        self.assertFalse(final_gate)
        self.assertIn("email_1_missing_clinic_profile", blockers)
        self.assertIn("email_3_not_hia_segment_diagnostic_shape", blockers)

    def test_weak_not_ready_rows_retry_once_before_auto_skip(self):
        first_pass = o.plan_and_patch(
            {
                "Id": 50,
                "company_name": "Asia Physio",
                "website_content": "# Asia Physio\nhttps://www.asiaphysio.com/",
                "validated_email": "team@example.com",
                "attempt_count": 1,
            }
        )
        first_patch = first_pass["patch"]
        self.assertEqual(first_patch["automation_decision"], "retry_enrichment_once")
        self.assertEqual(first_patch["automation_decision_reason"], "healthcare_evidence_retry_once")
        self.assertIn("retry_deeper_healthcare_pages", first_patch["automation_blockers_json"])

        retried = o.plan_and_patch(
            {
                "Id": 51,
                "company_name": "Asia Physio",
                "website_content": "# Asia Physio\nhttps://www.asiaphysio.com/",
                "validated_email": "team@example.com",
                "attempt_count": 2,
            }
        )
        retried_patch = retried["patch"]
        self.assertEqual(retried_patch["automation_decision"], "auto_skipped")
        self.assertEqual(retried_patch["automation_decision_reason"], "weak_hia_and_pdpa_evidence")

    def test_hia_specialist_diagnostic_uses_same_records_as_email_1(self):
        row = {
            "company_name": "Asian Heart & Vascular Centre",
            "website_content": "Specialist heart cardiology clinic offering ECG, echocardiogram, referrals and cardiac consultations.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        self.assertEqual(plan.quality_flags, [])
        records = o.hia_email_1_records(row, plan.classification, plan.copy_brief)
        self.assertIn(records, plan.emails["email_3"]["body"])
        self.assertIn("backups", plan.emails["email_3"]["body"])
        self.assertIn("incidents", plan.emails["email_3"]["body"])

    def test_hia_specialist_subtype_records_do_not_bleed_between_specialties(self):
        endocrinology = {
            "company_name": "Arden Endocrinology Specialist Clinic",
            "website_content": "Endocrinology specialist clinic for diabetes and thyroid care. Nearby oncology and radiation services are listed in the hospital directory.",
        }
        endo_plan = o.plan_outreach(endocrinology, programmes=[verified_program()])
        endo_records = o.hia_email_1_records(endocrinology, endo_plan.classification, endo_plan.copy_brief)
        self.assertIn("diabetes/thyroid care records", endo_records)
        self.assertNotIn("oncology/radiation", endo_records)
        self.assertIn(endo_records, endo_plan.emails["email_3"]["body"])

        orthopaedic = {
            "company_name": "Artisan Sports & Orthopaedics Clinic",
            "website_content": "Specialist orthopaedic and sports medicine clinic for musculoskeletal pain, imaging referrals and treatment plans.",
        }
        ortho_plan = o.plan_outreach(orthopaedic, programmes=[verified_program()])
        self.assertIn("orthopaedic / sports medicine clinic", ortho_plan.copy_brief["clinic_profile_phrase"])
        self.assertNotIn("pain management clinic", ortho_plan.copy_brief["clinic_profile_phrase"])
        ortho_records = o.hia_email_1_records(orthopaedic, ortho_plan.classification, ortho_plan.copy_brief)
        self.assertIn("orthopaedic consultation notes", ortho_records)
        self.assertIn(ortho_records, ortho_plan.emails["email_3"]["body"])

    def test_cancer_centre_stays_specialist_when_pharmacy_terms_appear(self):
        row = {
            "company_name": "National Cancer Centre Singapore",
            "website_content": "National Cancer Centre Singapore provides cancer care, oncology consultations and radiation treatment. The site also mentions pharmacy support, dispensing and eye clinic referrals.",
            "validated_email": "team@example.com",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        first_sentence = plan.emails["email_1"]["body"].split("\n\n", 1)[0]

        self.assertEqual(plan.classification["hia_service_type_guess"], "specialist_OMS")
        self.assertEqual(plan.copy_brief["clinic_profile_guess"], "specialist_led")
        self.assertIn("oncology", first_sentence.lower())
        self.assertNotIn("eye care", first_sentence.lower())
        self.assertNotIn("pharmacy / compounding provider", first_sentence.lower())

    def test_ivf_fertility_clinic_is_hia_specialist_service(self):
        row = {
            "company_name": "Monash IVF Singapore",
            "website_content": "Monash IVF Singapore is a fertility specialist clinic and treatment centre offering IVF, fertility treatments, appointments and patient consultations.",
            "validated_email": "team@example.com",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        patch = o.plan_and_patch(row, programmes=[verified_program()])["patch"]

        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "specialist_OMS")
        self.assertIn("fertility", plan.copy_brief["clinic_profile_phrase"].lower())
        self.assertNotIn("no_hia_service_evidence", patch["automation_blockers_json"])

    def test_family_clinic_evidence_overrides_weak_long_term_care_terms(self):
        row = {
            "company_name": "AMK Family Clinic",
            "website_content": "Family clinic with doctors, outpatient consultations, patient appointments, family contacts and care records.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        self.assertEqual(plan.classification["hia_service_type_guess"], "GP_OMS")
        self.assertEqual(plan.copy_brief["clinic_profile_guess"], "family_gp")
        self.assertIn("family clinic", plan.copy_brief["clinic_profile_phrase"])

    def test_hia_email_3_sentence_slots_keep_segment_diagnostic_shape(self):
        row = {
            "company_name": "Asian Heart & Vascular Centre",
            "website_content": "Specialist heart cardiology clinic offering ECG, echocardiogram, referrals and cardiac consultations.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        records = o.hia_email_1_records(row, plan.classification, plan.copy_brief)
        expected = {
            "A": f"A practical diagnostic: can Asian Heart & Vascular Centre show where {records} sit today, who owns access, how backups work and who handles incidents?",
            "B": f"One useful check: can Asian Heart & Vascular Centre map {records} to owners, access lists, backups and incident contacts?",
            "C": f"Simple check: can Asian Heart & Vascular Centre show who owns access to {records}, where backups sit and who handles incidents?",
        }
        for legacy_key, opener in expected.items():
            with self.subTest(legacy_key=legacy_key):
                body = o.hia_email_2_diagnostic(row, plan.classification, "specialist clinic readiness map", plan.copy_brief, legacy_key)
                self.assertIn(opener, body)
                self.assertFalse(o.email_3_not_hia_segment_diagnostic_shape(body, row, plan.classification))

    def test_funding_email_2_fixed_body_uses_human_followup_sentence(self):
        body = o.funding_email_2_body_fixed(
            "Hello team,",
            "Based on the company profile, the Cyber Essentials support route appears worth checking for Example Clinic.",
            "\n\nThis is subject to programme confirmation.",
        )
        self.assertIn(
            "The useful first step is to check the route before lining up readiness work.",
            body,
        )
        self.assertNotIn("before anyone spends time", body)

    def test_email_2_named_followup_lowercases_after_dash(self):
        funding = o.funding_email_2_body_fixed("Samuel - ", "Based on the company profile, the Cyber Essentials support route appears worth checking.", "")
        fallback = o.value_fallback_body_fixed("Samuel - ", "safeguards checklist")
        pricing = o.hia_pricing_email_2_body("Samuel - ", "group_or_larger_sizing_needed", False)
        self.assertTrue(funding.startswith("Samuel - based"))
        self.assertTrue(fallback.startswith("Samuel - a simple first pass"))
        self.assertTrue(pricing.startswith("Samuel - straight up"))

    def test_deterministic_aesthetic_and_allied_health_diagnostics_do_not_self_flag(self):
        cases = [
            {
                "company_name": "Apax Medical & Aesthetics Clinic",
                "website_content": "Aesthetic medical clinic with doctors, treatments, consultation, appointments and patient services.",
                "expected": "consultation records, treatment notes, appointment details, clinic email, vendor systems and backups",
            },
            {
                "company_name": "A Plus Physio",
                "website_content": "Physiotherapy clinic with appointments, treatment plans, exercise-plan records and patient care.",
                "expected": "appointment, treatment and exercise-plan records",
            },
            {
                "company_name": "Asia Psychology Centre",
                "website_content": "Psychology and mental-health clinic with appointments, assessments, case-note records and patient care.",
                "expected": "appointment, assessment and case-note records",
            },
        ]
        for row in cases:
            with self.subTest(company=row["company_name"]):
                plan = o.plan_outreach(row, programmes=[verified_program()])
                self.assertIn(row["expected"].replace(" and backups", ""), plan.emails["email_3"]["body"])
                self.assertIn("backups", plan.emails["email_3"]["body"])
                self.assertIn("incident", plan.emails["email_3"]["body"])
                self.assertNotIn("email_3_missing_hia_segment_terms", plan.quality_flags)
                self.assertNotIn("email_3_not_hia_segment_diagnostic_shape", plan.quality_flags)

    def test_funding_email_rebuilt_when_llm_adds_non_funding_claims(self):
        row = {
            "Id": 45,
            "company_name": "Example Charity",
            "website_content": "Singapore charity supporting beneficiaries and volunteers.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        claim = plan.funding.funding_claim_line
        bad_emails = {key: dict(value) if key.startswith("email_") else value for key, value in plan.emails.items()}
        bad_emails["email_2"]["body"] = f"{claim}\n\nHIA timelines and PDPA safeguards matter too."
        bad_emails["email_2"]["word_count"] = o.word_count(bad_emails["email_2"]["body"])
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding, bad_emails, plan.copy_brief)
        self.assertIn(claim, patch["email_2_body"])
        self.assertNotIn("HIA timelines", patch["email_2_body"])
        self.assertNotIn("PDPA", patch["email_2_body"])
        self.assertEqual(patch["email_2_body"].count("subject to programme confirmation"), 1)
        self.assertNotIn("Best,", patch["email_2_body"])
        self.assertNotIn("RAYN Secure", patch["email_2_body"])
        draft_patch = o.patch_with_email_sequence(
            {**row, "draft_only": True},
            plan.classification,
            plan.funding,
            bad_emails,
            plan.copy_brief,
        )
        self.assertFalse(draft_patch["email_send_ready"])

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
        self.assertNotIn("email_2_missing_funding_claim_line", patch["email_quality_flags"])
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
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hello team,"))
        self.assertIn("care/community-service", plan.emails["email_1"]["body"])
        self.assertIn("beneficiary, volunteer, donor and staff data", plan.emails["email_1"]["body"])
        self.assertNotIn("signals", plan.emails["email_1"]["body"].lower())
        self.assertIn("PDPA is the legal responsibility", plan.emails["email_1"]["body"])
        self.assertIn("beneficiary", plan.emails["email_3"]["body"])
        self.assertIn("beneficiary", brief["personal_data_handled_guess"])
        self.assertIn("volunteer", brief["personal_data_handled_guess"])
        self.assertIn("donor", brief["personal_data_handled_guess"])
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
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hello team,"))
        self.assertIn("medical/aesthetic clinic with doctor-led consultations", plan.emails["email_1"]["body"])
        self.assertIn("HIA", plan.emails["email_1"]["body"])
        self.assertTrue("access" in plan.emails["email_1"]["body"] and "backup" in plan.emails["email_1"]["body"] and "incident" in plan.emails["email_1"]["body"])
        self.assertNotIn("vendor systems, access", plan.emails["email_1"]["body"])
        self.assertNotIn("vendor systems, access, backups, patching, vendors", plan.emails["email_1"]["body"])
        self.assertIn("Cyber Essentials", plan.emails["email_1"]["body"])
        self.assertIn("HIA readiness map?", plan.emails["email_1"]["body"])
        self.assertIn("consultation records", plan.emails["email_3"]["body"])
        self.assertIn("treatment notes", plan.emails["email_3"]["body"])
        self.assertIn("clinic email", plan.emails["email_3"]["body"])
        self.assertIn("appointment", brief["data_systems_likely"])
        self.assertIn("backups", brief["data_systems_likely"])
        self.assertIn("vendor", brief["data_systems_likely"])
        self.assertIn("incident", brief["data_systems_likely"])
        self.assertEqual(brief["email_asset_offer"], "clinic readiness map")
        self.assert_no_final_email_batch_or_signal_language(plan)

    def test_american_international_clinic_matches_target_email_1_shape(self):
        plan = o.plan_outreach(
            {
                "Id": 61,
                "company_name": "American International Clinic Singapore",
                "best_url": "https://aiclinic.com.sg/",
                "services_detected": ["medical clinic", "doctor consultations", "outpatient appointments"],
                "leadership_or_team_signals": ["doctor team"],
                "website_content": "Singapore GP medical clinic with doctors, outpatient appointments, consultation and patient services.",
            },
            programmes=[verified_program()],
        )
        body = plan.emails["email_1"]["body"]
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "GP_OMS")
        self.assertIn("Batch 1 - Sep 2027", plan.classification["hia_timeline_batch_guess"])
        self.assertTrue(body.startswith("Hello team,"))
        self.assertIn("outpatient medical clinic offering doctor-led consultations", body)
        self.assertNotIn("family clinic", body)
        self.assertIn("HIA", body)
        self.assertTrue("access" in body and "backup" in body and "incident" in body)
        self.assertIn("Cyber Essentials", body)
        self.assertIn("HIA readiness map?", body)
        self.assertIn("patient records, appointment details, consultation notes, clinic email, vendor systems", plan.emails["email_3"]["body"])
        self.assertIn("backups", plan.emails["email_3"]["body"])
        self.assert_no_final_email_batch_or_signal_language(plan)

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
        self.assertNotEqual(plan.classification["pressure_type"], "not_ready")
        self.assertIn("health information", plan.copy_brief["personal_data_handled_guess"])
        self.assertIn("hearing-care provider offering hearing tests, hearing aids and audiology support", plan.emails["email_1"]["body"])
        self.assertIn("HIA", plan.emails["email_1"]["body"])
        self.assertIn("hearing test records", plan.emails["email_3"]["body"])
        self.assertIn("appointment details", plan.emails["email_3"]["body"])
        self.assertIn("device-related records", plan.emails["email_3"]["body"])
        self.assertEqual(plan.copy_brief["email_asset_offer"], "hearing-care readiness map")
        self.assert_no_final_email_batch_or_signal_language(plan)
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
        self.assertEqual(brief["email_asset_offer"], "customer security evidence checklist")
        self.assertRegex(brief["email_problem_statement"], r"security proof|customer review|customers")
        self.assertIn("works with customers who may ask how user data, admin access and backups are controlled", plan.emails["email_1"]["body"])
        self.assertIn("admin access", plan.emails["email_1"]["body"])
        self.assertIn("Cyber Essentials", plan.emails["email_1"]["body"])
        self.assertIn("common customer security question", plan.emails["email_3"]["body"])
        self.assert_no_final_email_batch_or_signal_language(plan)

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
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hello team,"))
        self.assertNotIn("Hi -", plan.emails["email_1"]["body"])
        self.assertNotIn("generic_inbox_wrong_greeting", plan.quality_flags)

    def test_named_contact_uses_first_name_greeting(self):
        plan = o.plan_outreach(
            {
                "company_name": "Amaris B. Clinic",
                "selected_contact_name": "Ivan Puah",
                "validated_email": "ivanpuah@amaris-b.com",
                "services_detected": ["aesthetic clinic services", "doctor consultations"],
                "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
            },
            programmes=[verified_program()],
        )
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hi Ivan,"))
        self.assertIn("medical/aesthetic clinic with doctor-led consultations", plan.emails["email_1"]["body"])
        self.assertTrue(plan.emails["email_2"]["body"].startswith("Ivan - "))
        self.assertTrue(plan.emails["email_3"]["body"].startswith("Ivan - "))
        self.assertTrue(plan.emails["email_4"]["body"].startswith("Ivan, "))
        self.assertFalse(plan.emails["email_4"]["body"].startswith("Ivan - "))

    def test_named_doctor_contact_uses_person_first_name(self):
        plan = o.plan_outreach(
            {
                "company_name": "American International Clinic Singapore",
                "selected_contact_name": "Dr Paul Zakowich",
                "validated_email": "zakowich@aiclinic.com.sg",
                "website_content": "Medical clinic with doctors, outpatient appointments and patient services.",
            },
            programmes=[verified_program()],
        )
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hi Paul,"))
        self.assertIn("outpatient medical clinic offering doctor-led consultations", plan.emails["email_1"]["body"])

    def test_blank_selected_contact_uses_team_greeting_and_keeps_company_observation(self):
        plan = o.plan_outreach(
            {
                "company_name": "Acme Services Pte Ltd",
                "selected_contact_name": "",
                "validated_email": "info@acme.com.sg",
                "website_content": "Singapore private company collecting customer enquiries and employee data.",
            }
        )
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hello team,"))
        self.assertIn("Acme Services", plan.emails["email_1"]["body"])
        self.assertNotIn("Acme Services Pte Ltd", plan.emails["email_1"]["body"])
        self.assertFalse(plan.emails["email_2"]["body"].lower().startswith(("hi ", "hello ")))
        self.assertFalse(plan.emails["email_3"]["body"].lower().startswith(("hi ", "hello ")))
        self.assertFalse(plan.emails["email_4"]["body"].lower().startswith(("hi ", "hello ")))

    def test_generic_contactus_email_does_not_invent_first_name(self):
        plan = o.plan_outreach(
            {
                "company_name": "Amber Family Clinic",
                "validated_email": "contactus@amberfamilyclinic.com",
                "website_content": "Family clinic with doctors, patient appointments, consultation and patient services.",
            },
            programmes=[verified_program()],
        )
        self.assertTrue(plan.emails["email_1"]["body"].startswith("Hello team,"))
        self.assertNotIn("Hi Amber,", plan.emails["email_1"]["body"])
        self.assertIn("family clinic offering GP-style consultations", plan.emails["email_1"]["body"])

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
        emails["email_2"]["body"] = f"{plan.funding.funding_claim_line}\n\nHIA timelines and PDPA safeguards matter too."
        emails["email_2"]["word_count"] = o.word_count(emails["email_2"]["body"])
        emails["email_3"]["body"] = "Cyber Essentials is a recognised baseline."
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
        self.assertIn("email_3_not_diagnostic", flags)
        self.assertIn("email_2_not_funding_only", flags)

    def test_internal_signal_language_is_flagged(self):
        plan = o.plan_outreach(
            {
                "Id": 46,
                "company_name": "Amaris B. Clinic",
                "services_detected": ["aesthetic clinic services", "doctor consultations"],
                "leadership_or_team_signals": ["doctor and practitioner team"],
                "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
            },
            programmes=[verified_program()],
        )
        emails = {
            key: dict(value)
            for key, value in plan.emails.items()
            if key.startswith("email_")
        }
        emails["email_1"]["body"] = (
            "Hi Amaris B. Clinic team,\n\n"
            "Noticed Amaris B. Clinic shows multiple clinic service and team/practitioner signals.\n\n"
            f"{plan.copy_brief['email_problem_statement']}\n\n"
            f"{plan.copy_brief['email_mechanism_statement']}\n\n"
            f"{plan.copy_brief['email_cta']}\n\nBest,\nSK\nRAYN Secure"
        )
        emails["email_1"]["word_count"] = o.word_count(emails["email_1"]["body"])
        flags = o.evaluate_email_strategy(
            {"company_name": "Amaris B. Clinic"},
            plan.classification,
            plan.funding,
            emails,
            plan.copy_brief,
        )
        self.assertIn("email_1_contains_internal_signal_language", flags)

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

    def test_hia_email_1_uses_clinic_profile_phrase(self):
        cases = [
            (
                {
                    "company_name": "American International Clinic Singapore",
                    "website_content": "International medical clinic in Singapore with doctors, outpatient appointments and patient treatment services.",
                    "services_detected": "medical clinic; doctor consultations; outpatient appointments",
                },
                "outpatient medical clinic offering doctor-led consultations",
            ),
            (
                {
                    "company_name": "Amaris B. Clinic",
                    "services_detected": ["aesthetic clinic services", "doctor consultations"],
                    "website_content": "Aesthetic medical clinic in Singapore with doctors, treatments, consultation and patient services.",
                },
                "medical/aesthetic clinic with doctor-led consultations",
            ),
            (
                {
                    "company_name": "Amazing Hearing Group",
                    "website_content": "Hearing care provider offering audiology, hearing tests, hearing aids and patient appointments.",
                },
                "hearing-care provider offering hearing tests, hearing aids and audiology support",
            ),
            (
                {
                    "company_name": "Clinic Group Example",
                    "parent_company": "Example Health Group",
                    "locations_detected": "Bedok; Jurong; Novena",
                    "website_content": "Medical group with branches, multiple doctors and outpatient clinics across Singapore.",
                },
                "part of a wider clinic group or multi-location healthcare operation",
            ),
            (
                {
                    "company_name": "Solo GP Clinic",
                    "website_content": "Family clinic and GP practice led by Dr Tan at one location with outpatient consultations.",
                },
                "solo GP-style clinic",
            ),
        ]
        for row, phrase in cases:
            with self.subTest(company=row["company_name"]):
                plan = o.plan_outreach(row, programmes=[verified_program()])
                self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
                self.assertIn(phrase, plan.emails["email_1"]["body"])
                if not phrase.startswith("provides "):
                    self.assertIn(phrase.replace("appears to be ", ""), plan.copy_brief["clinic_profile_phrase"])
                self.assertNotIn("signals", plan.emails["email_1"]["body"].lower())
                self.assert_no_final_email_batch_or_signal_language(plan)

    def test_first_10_hia_segments_use_segment_specific_assets_without_batch_copy(self):
        cases = [
            (
                {
                    "company_name": "Amber Family Clinic",
                    "website_content": "Family clinic with doctors, patient appointments, consultation and patient services.",
                },
                "family clinic offering GP-style consultations",
                "patient records, appointment details, consultation notes, clinic email, vendor systems and backups",
                "clinic readiness map",
            ),
            (
                {
                    "company_name": "Amber Compounding Pharmacy",
                    "website_content": "Retail pharmacy and compounding pharmacy with prescriptions, dispensing, compounding and customer services.",
                },
                "pharmacy / compounding provider",
                "prescription, dispensing, compounding, customer and supplier records",
                "pharmacy HIA checklist",
            ),
            (
                {
                    "company_name": "National Neuroscience Institute",
                    "website_content": "National Neuroscience Institute provides neurology, neurosurgery and neuroscience care. Patient appointments, specialist reports, pharmacy support and clinical records are handled across services.",
                },
                "specialist-led neuroscience provider",
                "consultation notes, patient reports, treatment records, vendor systems and backups",
                "specialist clinic readiness map",
            ),
            (
                {
                    "company_name": "Amoy Street Dental",
                    "website_content": "Dental clinic with dentists, patient appointments, imaging files and dental software.",
                },
                "dental clinic handling patient appointments and dental records",
                "patient records, imaging files, appointment details, dental software and backups",
                "dental readiness map",
            ),
            (
                {
                    "company_name": "Andrea's Digestive, Colon, Liver and Gallbladder Clinic",
                    "website_content": "Digestive specialist clinic providing gastroenterology consultations, procedure-related records, specialist appointments and patient reports.",
                },
                "provides specialist-led gastroenterology and digestive care",
                "consultation notes, patient reports, procedure-related records, vendor systems and backups",
                "specialist clinic readiness map",
            ),
        ]
        for row, observation, diagnostic, asset in cases:
            with self.subTest(company=row["company_name"]):
                plan = o.plan_outreach(row, programmes=[verified_program()])
                self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
                self.assertIn(observation, plan.emails["email_1"]["body"])
                self.assertIn(diagnostic.replace(" and backups", ""), plan.emails["email_3"]["body"])
                self.assertIn("backups", plan.emails["email_3"]["body"])
                self.assertEqual(plan.copy_brief["email_asset_offer"], asset)
                self.assertIn("HIA readiness map?", plan.emails["email_1"]["body"])
                self.assertIn(asset, plan.emails["email_4"]["body"])
                self.assert_no_final_email_batch_or_signal_language(plan)

    def test_specialist_hia_subtypes_use_specific_records_and_diagnostics(self):
        cases = [
            (
                "Heart Centre",
                "Specialist heart cardiology clinic offering ECG, echocardiogram, referrals and cardiac consultations.",
                "a specialist-led heart/cardiology clinic",
                "cardiac test reports",
            ),
            (
                "Pain Management Clinic",
                "Specialist pain management clinic offering spine pain care, injections, assessment notes and treatment plans.",
                "a specialist-led pain management clinic",
                "assessment notes, treatment plans, procedure-related records",
            ),
            (
                "Surgical Clinic",
                "Specialist surgical clinic led by a surgeon with consent forms, procedure records and post-operative follow-up notes.",
                "a specialist-led surgical clinic",
                "consent forms, procedure records, follow-up notes",
            ),
            (
                "Dermatology Clinic",
                "Dermatology clinic with dermatologist consultations for skin, acne, eczema, mole checks, laser treatment and clinical images.",
                "a specialist-led dermatology clinic",
                "skin consultation notes, treatment records, appointment details, clinical images where used",
            ),
            (
                "Eye Clinic",
                "Eye ophthalmology clinic with cataract, retina, LASIK, optometry, imaging, prescriptions and referrals.",
                "a specialist-led eye clinic",
                "eye examination records, imaging, prescriptions, referrals",
            ),
            (
                "Rheumatology Centre",
                "Rheumatologist specialist clinic offering arthritis and lupus treatment, referrals and consultations.",
                "a specialist-led rheumatology clinic",
                "consultation notes, treatment records, referrals, appointment details",
            ),
            (
                "Home Care Provider",
                "Home care caregiver provider offering home nursing and patient care at home for clients, families and staff.",
                "a home-care / caregiver provider",
                "client, patient, caregiver, family and staff records",
            ),
        ]
        for company, content, profile_phrase, diagnostic in cases:
            with self.subTest(company=company):
                plan = o.plan_outreach({"company_name": company, "website_content": content}, programmes=[verified_program()])
                self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
                self.assertIn(profile_phrase, plan.emails["email_1"]["body"])
                self.assertIn(diagnostic, plan.emails["email_3"]["body"])
                self.assert_no_final_email_batch_or_signal_language(plan)

    def test_rheumatology_clinic_stays_in_hia_not_customer_trust(self):
        plan = o.plan_outreach(
            {
                "company_name": "Asia Arthritis & Rheumatology Centre",
                "website_content": "# Asia Arthritis & Rheumatology Centre - Rheumatologist | Lupus Treatment Singapore\nhttps://aarc.sg/",
            },
            programmes=[verified_program()],
        )

        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "specialist_OMS")
        self.assertEqual(plan.classification["campaign_track"], "hia_regulatory")
        self.assertIn("a specialist-led rheumatology clinic", plan.emails["email_1"]["body"])
        self.assertIn("consultation notes, treatment records, referrals, appointment details", plan.emails["email_3"]["body"])
        self.assertEqual(plan.emails["email_1"]["chosen_subject"], "specialist clinic readiness")
        self.assert_no_final_email_batch_or_signal_language(plan)

    def test_heart_and_generic_specialist_words_do_not_override_better_clinic_routes(self):
        cases = [
            (
                "Amber Family Clinic",
                "# Amber Family Clinic | Primary Care Physician in Katong\nWelcome to Amber Family Clinic. MOH-approved clinic providing in-person consultations and video consultations for the community. Your health in focus. Our team looks forward to meeting you. We are proud to be recognized as a trusted panel clinic. Is your liver health at risk?",
                "GP_OMS",
                "a family clinic offering GP-style consultations",
                "heart/cardiology",
            ),
            (
                "AO Psychology",
                "# Clinical Psychologist Singapore | Counselling & Psychotherapy | AO Psychology\nClinical Psychologist in Singapore. Counselling and psychotherapy services for individuals, couples and families. Evidence-based therapy by registered psychologists. Mental wellness blog and resources.",
                "allied_health",
                "a psychology / mental-health provider handling assessment and case-note records",
                "heart/cardiology",
            ),
            (
                "Appletree Medical",
                "# Appletree Medical Group | Walk-In, Family Doctors, Virtual Care & Telemedicine\nAppletree Medical Group offers Virtual Care, Walk-In, Family Medicine and Specialists services in Ontario, for same-day doctor's visit or ongoing medical care. Healthcare that fits your life.",
                "GP_OMS",
                "part of a wider clinic group or multi-location healthcare operation",
                "heart/cardiology",
            ),
            (
                "Arden Endocrinology Specialist Clinic",
                "# Endocrinologists In Singapore | Arden Endocrinology Specialist Clinic\nUnderstanding hypertension, high cholesterol, diabetes and thyroid care. Physiotherapy supports sustainable weight loss.",
                "specialist_OMS",
                "a specialist-led endocrinology clinic",
                "allied-health",
            ),
            (
                "Asia Diagnostics Group",
                "# Asia Diagnostics Group\nGeneral Radiology Services. ADG is a qualified independent diagnostics service provider with Bedok X-ray Centre and Jurong Imaging Centre. Diagnostics imaging such as Chest X-ray supports diagnosis and monitoring.",
                "diagnostic",
                "a diagnostic / laboratory provider handling screening or test records",
                "dental",
            ),
            (
                "Asia Digestive Associates",
                "# Home | Asia Digestive Associates\nAt Asia Digestive Associates, we put our heart and soul into providing patient centered care. Our services include digestive and gastroenterology clinics.",
                "specialist_OMS",
                "specialist-led gastroenterology and digestive care",
                "heart/cardiology",
            ),
        ]
        for company, content, service, expected_phrase, forbidden_phrase in cases:
            with self.subTest(company=company):
                plan = o.plan_outreach({"company_name": company, "website_content": content}, programmes=[verified_program()])
                self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
                self.assertEqual(plan.classification["hia_service_type_guess"], service)
                self.assertIn(expected_phrase, plan.emails["email_1"]["body"])
                self.assertNotIn(forbidden_phrase, plan.emails["email_1"]["body"])
                self.assert_no_final_email_batch_or_signal_language(plan)

    def test_amk_family_clinic_prefers_gp_over_weak_diagnostic_evidence(self):
        plan = o.plan_outreach(
            {
                "company_name": "AMK Family Clinic",
                "website_content": "Family Clinic with doctors, consultation, health screening, patient appointments and treatment services.",
            },
            programmes=[verified_program()],
        )
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "GP_OMS")
        self.assertNotEqual(plan.copy_brief["clinic_profile_guess"], "diagnostic_lab")
        self.assertIn("family clinic offering GP-style consultations", plan.emails["email_1"]["body"])
        self.assertIn("patient records, appointment details, consultation notes, clinic email, vendor systems", plan.emails["email_3"]["body"])
        self.assertIn("backups", plan.emails["email_3"]["body"])

    def test_family_clinic_not_overridden_by_bare_fertility_term(self):
        result = o.plan_and_patch(
            {
                "company_name": "Assure Family Clinic",
                "website_content": "Family Clinic with doctors, family medicine, health screening, fertility support, patient appointments and treatment services.",
                "validated_email": "woodlands@example.com",
                "draft_only": True,
            }
        )
        patch = result["patch"]
        self.assertEqual(patch["hia_service_type_guess"], "GP_OMS")
        self.assertIn("family clinic offering GP-style consultations", patch["email_1_body"])
        self.assertEqual(patch["automation_decision"], "auto_send_eligible")
        self.assertTrue(patch["final_send_gate_passed"])
        self.assertEqual(patch["email_quality_flags"], "[]")

    def test_amp_lab_requires_clinical_diagnostic_evidence(self):
        clinical = o.plan_outreach(
            {
                "company_name": "AMP Lab",
                "website_content": "Clinical laboratory providing diagnostic lab tests, health screening and patient reports.",
            },
            programmes=[verified_program()],
        )
        self.assertEqual(clinical.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(clinical.classification["hia_service_type_guess"], "diagnostic")
        self.assertEqual(clinical.copy_brief["email_asset_offer"], "diagnostic readiness map")
        self.assertIn("diagnostic / laboratory provider handling screening or test records", clinical.emails["email_1"]["body"])
        self.assert_no_final_email_batch_or_signal_language(clinical)

        generic = o.plan_outreach(
            {
                "company_name": "AMP Lab",
                "website_content": "Research lab for product testing and business testing.",
            }
        )
        self.assertIn(generic.classification["pressure_type"], {"not_ready", "customer_trust"})
        self.assertNotEqual(generic.classification["hia_service_type_guess"], "diagnostic")

    def test_hia_small_clinic_email_2_uses_safe_starting_price(self):
        plan = o.plan_outreach(
            {
                "company_name": "AN Medical Clinic",
                "website_content": "Family clinic with GP doctors, outpatient appointments, consultation and patient services.",
                "validated_email": "team@example.com",
            },
            programmes=[verified_program()],
        )
        email2 = plan.emails["email_2"]["body"]
        self.assertIn(plan.copy_brief["clinic_size_guess"], {"solo_gp", "small_single_clinic"})
        self.assertEqual(plan.copy_brief["endpoint_band_guess"], "1_5")
        self.assertEqual(plan.copy_brief["pricing_email_2_mode"], "small_clinic_starting_price")
        self.assertIn("S$4,300 before funding", email2)
        self.assertTrue("If the route applies" in email2 or "Subject to programme confirmation" in email2)
        self.assertIn("software", email2.lower())
        self.assertTrue(plan.final_send_gate_passed)
        self.assertNotIn("you qualify", email2.lower())
        self.assertNotIn("you are eligible", email2.lower())
        self.assertNotIn("guaranteed", email2.lower())
        self.assert_no_email_signatures(plan.emails)

    def test_hia_unknown_endpoint_does_not_block_pricing_email_2(self):
        result = o.plan_and_patch(
            {
                "Id": 610,
                "company_name": "Example Medical Clinic",
                "website_content": "Medical clinic providing doctor consultations, appointments and patient services.",
                "validated_email": "team@example.com",
            },
            programmes=[verified_program()],
        )
        patch = result["patch"]
        record = result["record"]
        email2 = patch["email_2_body"]
        self.assertEqual(record["copy_brief"]["endpoint_band_guess"], "unknown")
        self.assertEqual(record["copy_brief"]["pricing_email_2_mode"], "endpoint_sizing_needed")
        self.assertTrue("endpoint-based" in email2 or "endpoint count" in email2)
        self.assertRegex(email2, r"[Ss]maller clinics|[Ss]mall clinic")
        self.assertIn("S$4,300 before funding", email2)
        self.assertEqual(patch["automation_decision"], "auto_send_eligible")
        self.assertTrue(patch["final_send_gate_passed"])

    def test_hia_group_email_2_requires_endpoint_sizing(self):
        plan = o.plan_outreach(
            {
                "company_name": "Example Clinic Group",
                "website_content": "Clinic group with our clinics at Orchard and Tampines, multiple doctors, medical team and specialist departments.",
                "locations_detected": json.dumps(["Orchard clinic", "Tampines clinic"]),
                "leadership_or_team_signals": json.dumps(["Dr Tan", "Dr Lim", "Dr Ong", "Dr Wong", "Dr Lee", "Dr Ng"]),
                "validated_email": "team@example.com",
            },
            programmes=[verified_program()],
        )
        email2 = plan.emails["email_2"]["body"]
        self.assertIn(plan.copy_brief["clinic_size_guess"], {"group_clinic", "multi_location_provider"})
        self.assertEqual(plan.copy_brief["pricing_email_2_mode"], "group_or_larger_sizing_needed")
        self.assertTrue("endpoint-based" in email2 or "endpoint count" in email2)
        self.assertTrue("group" in email2.lower() or "larger setups" in email2.lower())
        self.assertTrue("endpoint" in email2.lower() or "tier" in email2.lower())
        self.assertNotIn("S$4,300 before funding", email2)
        self.assertNotIn("larger setups start", email2.lower())
        self.assertTrue(plan.final_send_gate_passed)

    def test_long_term_care_uses_specific_clinic_profile(self):
        plan = o.plan_outreach(
            {
                "company_name": "Example Care Services",
                "website_content": "Long-term care provider supporting residents, caregivers, family contacts, patient records and care operations.",
                "validated_email": "team@example.com",
            },
            programmes=[verified_program()],
        )
        self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertEqual(plan.classification["hia_service_type_guess"], "long_term_care")
        self.assertRegex(plan.copy_brief["clinic_profile_phrase"], r"(long-term care|home-care|caregiver) provider")
        self.assertNotEqual(plan.copy_brief["clinic_profile_phrase"], "a healthcare provider")
        self.assertNotIn("email_1_missing_clinic_profile", plan.severe_email_flags)

    def test_serper_group_healthcare_signal_is_not_generic_for_hia(self):
        signal = "Example Clinic operates a multi-location or group healthcare operation."
        self.assertFalse(o.generic_personalisation_signal(signal))

    def test_serper_generic_healthcare_signal_does_not_replace_specific_local_signal(self):
        original = o.fetch_serper_company_context

        def fake_fetch(row, classification, limit=5):
            return {
                "source": "serper",
                "used": True,
                "reason": "ok",
                "query": "example",
                "evidence": [{"title": "Example Health", "link": "https://example.test", "snippet": "Example Health is a healthcare provider."}],
            }

        o.fetch_serper_company_context = fake_fetch
        try:
            plan = o.plan_outreach(
                {
                    "Id": 611,
                    "company_name": "Example Home Care",
                    "best_url": "https://example.test",
                    "website_content": "Home care and caregiver provider supporting patients, family contacts and care records.",
                    "validated_email": "team@example.com",
                },
                programmes=[verified_program()],
            )
        finally:
            o.fetch_serper_company_context = original
        self.assertIn("home-care", plan.copy_brief["prospect_facing_signal"])
        self.assertNotIn("healthcare setting", plan.copy_brief["prospect_facing_signal"].lower())
        self.assertNotIn("email_1_missing_clinic_profile", plan.severe_email_flags)

    def test_hia_funding_unsafe_keeps_pricing_but_omits_70_percent(self):
        plan = o.plan_outreach(
            {
                "company_name": "Amber Compounding Pharmacy",
                "website_content": "Retail pharmacy and compounding pharmacy with prescriptions, dispensing, customer and patient records.",
                "validated_email": "team@example.com",
            },
            programmes=[],
        )
        email2 = plan.emails["email_2"]["body"]
        self.assertEqual(plan.copy_brief["pricing_email_2_mode"], "small_clinic_starting_price")
        self.assertIn("S$4,300 before funding", email2)
        self.assertNotIn("70%", email2)
        self.assertNotIn("If the route applies", email2)
        self.assertTrue(plan.final_send_gate_passed)

    def test_non_hia_email_2_does_not_use_clinic_pricing(self):
        plan = o.plan_outreach(
            {
                "company_name": "Acme Services Pte Ltd",
                "website_content": "Singapore company collecting customer enquiries and employee data.",
            }
        )
        email2 = plan.emails["email_2"]["body"]
        self.assertNotEqual(plan.classification["pressure_type"], "hia_regulatory")
        self.assertNotIn("S$4,300", email2)
        self.assertNotIn("CISOaaS pricing", email2)
        self.assertIn("evidence", email2.lower())

    def test_friendlier_deterministic_copy_style_keeps_track_spines(self):
        cases = [
            o.plan_outreach(
                {
                    "company_name": "AN Medical Clinic",
                    "website_content": "Family clinic with GP doctors, outpatient appointments, consultation and patient services.",
                    "validated_email": "team@example.com",
                },
                programmes=[verified_program()],
            ),
            o.plan_outreach(
                {
                    "company_name": "Acme Services Pte Ltd",
                    "website_content": "Singapore company collecting customer enquiries and employee data.",
                }
            ),
            o.plan_outreach(
                {
                    "company_name": "Vendor Platform Pte Ltd",
                    "website_content": "SaaS platform for enterprise clients with user data, admin access, backups and procurement reviews.",
                }
            ),
            o.plan_outreach(
                {
                    "company_name": "Acme Ops Pte Ltd",
                    "selected_contact_title": "Operations Manager",
                    "website_content": "Singapore private company handling customer records, employee data and vendor tools.",
                }
            ),
        ]
        banned = (
            "comprehensive",
            "robust",
            "tailored",
            "leverage",
            "landscape",
            "readiness journey",
            "certification work",
            "value proposition",
            "stakeholders",
            "end-to-end",
            "unlock",
            "empower",
            "delve",
            "furthermore",
            "moreover",
            "additionally",
            "practical question is whether",
        )
        for plan in cases:
            with self.subTest(track=plan.classification["campaign_track"]):
                blob = "\n".join(plan.emails[f"email_{index}"]["body"] for index in range(1, 5)).lower()
                for phrase in banned:
                    self.assertNotIn(phrase, blob)
                for index in range(1, 5):
                    paragraphs = [paragraph for paragraph in plan.emails[f"email_{index}"]["body"].split("\n\n") if paragraph.strip()]
                    self.assertLessEqual(len(paragraphs), 4)
                self.assertEqual(plan.emails["style_metadata"]["human_email_style"], "short_plain_low_cta")
                self.assertEqual(plan.quality_flags, [])

    def test_pricing_email_rejects_forbidden_claims(self):
        row = {
            "company_name": "Example Clinic",
            "website_content": "Family clinic with GP doctors, appointments and patient services.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        emails = json.loads(json.dumps(plan.emails))
        emails["email_2"]["body"] += " You qualify for guaranteed funding."
        emails["email_2"]["word_count"] = o.word_count(emails["email_2"]["body"])
        _, flags, send_ready = o.quality_gate(row, plan.classification, plan.funding, emails, plan.copy_brief)
        self.assertIn("forbidden_phrase:you qualify", flags)
        self.assertIn("forbidden_phrase:guaranteed funding", flags)
        self.assertFalse(send_ready)

    def test_llm_signatures_are_stripped_before_patch(self):
        row = {
            "company_name": "Example Charity",
            "website_content": "Singapore charity supporting beneficiaries and volunteers.",
        }
        plan = o.plan_outreach(row, programmes=[verified_program()])
        candidate = {
            key: {
                "chosen_subject": value["chosen_subject"],
                "body": f"{value['body']}\n\nBest,\nSK\nRAYN Secure" if value["body"] else "",
            }
            for key, value in plan.emails.items()
            if key.startswith("email_")
        }
        emails = o.normalize_llm_email_sequence(candidate)
        patch = o.patch_with_email_sequence(row, plan.classification, plan.funding, emails, plan.copy_brief)
        for index in range(1, 5):
            self.assertNotIn("Best,", patch[f"email_{index}_body"])
            self.assertNotIn("RAYN Secure", patch[f"email_{index}_body"])

    def test_global_final_emails_do_not_contain_batch_or_signal_language(self):
        rows = [
            {"company_name": "American International Clinic Singapore", "website_content": "Medical clinic with doctors, outpatient appointments and patient services."},
            {"company_name": "Amber Compounding Pharmacy", "website_content": "Retail pharmacy and compounding pharmacy with prescriptions and dispensing records."},
            {"company_name": "Amoy Street Dental", "website_content": "Dental clinic with dentists, patient appointments, imaging files and dental software."},
            {"company_name": "Amazing Hearing Group", "website_content": "Hearing care provider offering audiology, hearing tests, hearing aids and patient appointments."},
            {"company_name": "Vendor Platform Pte Ltd", "website_content": "B2B SaaS outsourcing platform serving enterprise clients with customer data integrations and vendor dashboards."},
        ]
        for row in rows:
            with self.subTest(company=row["company_name"]):
                self.assert_no_final_email_batch_or_signal_language(o.plan_outreach(row, programmes=[verified_program()]))

    def test_audited_healthcare_segments_get_specific_copy_briefs(self):
        cases = [
            (
                {
                    "Id": 47,
                    "company_name": "Asia Physio",
                    "website_content": "Physiotherapy clinic in Singapore offering physiotherapy appointments, treatment plans and patient rehabilitation services.",
                    "services_detected": "physiotherapy appointments; rehabilitation treatment plans",
                },
                "allied_health",
                "allied-health provider offering physiotherapy or treatment support",
                "appointment, treatment and exercise-plan records",
            ),
            (
                {
                    "Id": 48,
                    "company_name": "Asia Psychology Centre",
                    "website_content": "Psychology clinic with psychologists, counselling appointments, mental health assessments and patient case notes.",
                    "leadership_or_team_signals": "psychologist team",
                },
                "allied_health",
                "psychology / mental-health provider handling assessment and case-note records",
                "appointment, assessment and case-note records",
            ),
            (
                {
                    "Id": 49,
                    "company_name": "Assisi Hospice",
                    "website_content": "Hospice and palliative care provider with patient care, resident support, family contacts, volunteers and staff.",
                    "services_detected": "patient care; palliative care; volunteer support",
                },
                "long_term_care",
                "hospice / long-term care provider handling patient, resident, family, volunteer and staff data",
                "patient, resident, family, volunteer and staff data",
            ),
            (
                {
                    "Id": 50,
                    "company_name": "Asia Digestive Associates",
                    "website_content": "Digestive specialist clinic providing gastroenterology consultations, specialist appointments and patient reports.",
                },
                "specialist_OMS",
                "provides specialist-led gastroenterology and digestive care",
                "consultation notes, patient reports, procedure-related records",
            ),
        ]
        for row, service_type, signal, diagnostic in cases:
            with self.subTest(company=row["company_name"]):
                plan = o.plan_outreach(row, programmes=[verified_program()])
                self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
                self.assertEqual(plan.classification["hia_service_type_guess"], service_type)
                self.assertIn(signal, plan.emails["email_1"]["body"])
                self.assertNotIn("signals", plan.emails["email_1"]["body"].lower())
                self.assertIn("HIA", plan.emails["email_1"]["body"])
                self.assertIn(diagnostic, plan.emails["email_3"]["body"])
                self.assertIn("Cyber Essentials", plan.emails["email_1"]["body"])

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
