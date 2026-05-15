import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

from services.crawl4ai import outreach_planner as planner


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ensure_rayn_outreach_columns.py"
WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-cold-email-planner.json"


def load_column_script():
    if "psycopg" not in sys.modules:
        sys.modules["psycopg"] = types.ModuleType("psycopg")
    spec = importlib.util.spec_from_file_location("ensure_rayn_outreach_columns", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class OutreachColumnContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_column_script()
        cls.columns = {column.name: column for column in cls.module.OUTREACH_COLUMNS}

    def test_outreach_columns_have_unique_names(self):
        names = [column.name for column in self.module.OUTREACH_COLUMNS]
        self.assertEqual(len(names), len(set(names)))

    def test_required_patch_fields_are_all_present_in_outreach_columns(self):
        result = planner.plan_and_patch(
            {
                "Id": 123,
                "company_name": "Amaris B. Clinic",
                "best_url": "https://amaris-b.com/",
                "website_content": "Singapore medical clinic with doctors, consultation and patient treatment.",
                "draft_only": True,
            }
        )
        patch_fields = set(result["patch"].keys()) - {"Id"}
        missing = sorted(patch_fields - set(self.columns))
        self.assertEqual(missing, [])

    def test_boolean_fields_use_checkbox_boolean(self):
        for name in [
            "singapore_registered_guess",
            "hia_relevant",
            "hia_deadline_claim_safe",
            "hia_disclaimer_needed",
            "pdpa_relevant",
            "funding_relevant",
            "funding_human_review_required",
            "pricing_claim_safe",
            "do_not_contact",
            "email_send_ready",
            "final_send_gate_passed",
        ]:
            with self.subTest(name=name):
                column = self.columns[name]
                self.assertEqual(column.uidt, "Checkbox")
                self.assertEqual(column.db_type, "boolean")

    def test_numeric_fields_use_number_numeric(self):
        for name in [
            "employee_count_guess",
            "hia_relevance_score",
            "certification_fit_score",
            "email_quality_score",
            "enrichment_quality_score",
            "copy_brief_quality_score",
        ]:
            with self.subTest(name=name):
                column = self.columns[name]
                self.assertEqual(column.uidt, "Number")
                self.assertEqual(column.db_type, "numeric")

    def test_email_body_fields_are_long_text(self):
        for index in range(1, 5):
            column = self.columns[f"email_{index}_body"]
            self.assertEqual(column.uidt, "LongText")
            self.assertEqual(column.db_type, "text")

    def test_funding_claim_line_exists_and_is_long_text(self):
        column = self.columns["funding_claim_line"]
        self.assertEqual(column.uidt, "LongText")
        self.assertEqual(column.db_type, "text")

    def test_classification_audit_columns_exist(self):
        expected = {
            "primary_email_track": "SingleSelect",
            "secondary_email_track": "SingleSelect",
            "regulatory_applicability": "LongText",
            "classification_confidence": "SingleSelect",
            "classification_evidence_json": "LongText",
            "classification_rejected_tracks_json": "LongText",
            "hia_official_service_type": "SingleSelect",
            "hia_official_service_label": "SingleLineText",
        }
        for name, uidt in expected.items():
            with self.subTest(name=name):
                column = self.columns[name]
                self.assertEqual(column.uidt, uidt)
                self.assertEqual(column.db_type, "text")

    def test_email_subject_body_fields_exist(self):
        for index in range(1, 5):
            self.assertIn(f"email_{index}_subject", self.columns)
            self.assertIn(f"email_{index}_body", self.columns)

    def test_quality_fields_exist(self):
        for name in [
            "email_quality_score",
            "email_quality_flags",
            "email_send_ready",
            "human_review_status",
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
        ]:
            self.assertIn(name, self.columns)

    def test_human_review_status_options_match_planner_outputs(self):
        options = self.module.SELECT_OPTIONS["human_review_status"]
        self.assertIn("not_required", options)
        self.assertIn("not_ready", options)
        self.assertIn("ready_for_review", options)

    def test_official_hia_service_options_match_taxonomy(self):
        options = self.module.SELECT_OPTIONS["hia_official_service_type"]
        self.assertEqual(
            options,
            [
                "outpatient_medical_gp",
                "outpatient_medical_specialist",
                "outpatient_dental",
                "acute_hospital",
                "nursing_home",
                "ambulatory_surgical_centre",
                "community_hospital",
                "contingency_care_service",
                "assisted_reproduction",
                "clinical_laboratory",
                "outpatient_renal_dialysis",
                "retail_pharmacy",
                "radiology_laboratory",
                "nuclear_medicine_service",
            ],
        )

    def test_workflow_fetch_fields_are_existing_or_installed(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        fields = url_expr.split("&fields=", 1)[1].split("&limit=", 1)[0].split(",")
        existing_fields = {
            "Id",
            "company_name",
            "company_homepage_name",
            "parent_company",
            "best_url",
            "canonical_domain",
            "website_content",
            "source_urls",
            "attempt_count",
        }
        missing = sorted(field for field in fields if field not in existing_fields and field not in self.columns)
        self.assertEqual(missing, [])

    def test_workflow_fetch_skips_existing_drafts_and_not_ready_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        self.assertIn("(email_1_subject,blank)", url_expr)
        self.assertIn("(automation_decision,blank)", url_expr)
        self.assertNotIn("(validated_email,notblank)", url_expr)

    def test_workflow_fetch_does_not_refetch_suppressed_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        self.assertIn("~and(automation_decision,blank)", url_expr)
        self.assertIn("~and(email_1_subject,blank)", url_expr)

    def test_cold_email_workflow_is_deterministic_only(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        node_names = {node["name"] for node in workflow["nodes"]}
        self.assertNotIn("Prepare OpenRouter Email Draft", node_names)
        self.assertNotIn("OpenRouter Email Draft", node_names)
        self.assertNotIn("Merge OpenRouter Email Draft", node_names)
        self.assertNotIn("Validate LLM Email Draft", node_names)
        self.assertNotIn("Copy Brief Ready?", node_names)
        generate_node = next(node for node in workflow["nodes"] if node["name"] == "Generate Outreach Plan")
        self.assertIn("/outreach-plan-batch", generate_node["parameters"]["url"])
        generate_connections = workflow["connections"]["Generate Outreach Plan"]["main"][0]
        self.assertEqual(generate_connections[0]["node"], "Collect NocoDB Patches")

    def test_collect_node_does_not_mutate_email_bodies(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        collect_node = next(node for node in workflow["nodes"] if node["name"] == "Collect NocoDB Patches")
        js_code = collect_node["parameters"]["jsCode"]
        self.assertNotIn("ensureFundingClaim", js_code)
        self.assertNotIn("fundingGreeting", js_code)
        self.assertNotIn("email_2_body: replacement", js_code)
        self.assertIn("const patches = []", js_code)
        self.assertIn("const results = Array.isArray(body.results)", js_code)
        self.assertIn("patches.push(...body.patches)", js_code)

    def test_rows_to_items_does_not_pre_filter_contact_suppression_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        rows_node = next(node for node in workflow["nodes"] if node["name"] == "Rows To Items")
        js_code = rows_node["parameters"]["jsCode"]
        self.assertNotIn("use_llm", js_code)
        self.assertNotIn("if (normalized.do_not_contact) continue", js_code)
        self.assertNotIn("blockedStatuses", js_code)
        self.assertIn("normalizedRows.push", js_code)
        self.assertIn("chunkSize", js_code)
        self.assertIn("normalizedRows.slice", js_code)

    def test_planner_never_send_ready_when_funding_not_verified(self):
        result = planner.plan_and_patch(
            {
                "Id": 456,
                "company_name": "Example Pte Ltd",
                "website_content": "Singapore company collecting customer and employee data.",
                "draft_only": True,
            }
        )
        self.assertNotEqual(result["patch"]["funding_status"], "verified_match")
        self.assertFalse(result["patch"]["email_send_ready"])

    def test_forbidden_phrases_rejected(self):
        classification = planner.classify_row(
            {
                "company_name": "Example Pte Ltd",
                "website_content": "Singapore company collecting customer and employee data.",
            }
        )
        funding = planner.plan_outreach(
            {"company_name": "Example Pte Ltd", "website_content": "customer data"}
        ).funding
        forbidden_phrases = [
            "if you are an SME",
            "if you are an NPO",
            "eligible SMEs and NPOs may",
            "guaranteed funding",
            "Cyber Essentials makes you PDPA compliant",
            "fully HIA compliant with Cyber Essentials",
        ]
        for phrase in forbidden_phrases:
            with self.subTest(phrase=phrase):
                emails = planner.generate_email_sequence({"company_name": "Example Pte Ltd"}, classification, funding)
                emails["email_1"]["body"] += f" {phrase}."
                emails["email_1"]["word_count"] = planner.word_count(emails["email_1"]["body"])
                _, flags, send_ready = planner.quality_gate(classification, funding, emails)
                self.assertTrue(any(flag.startswith("forbidden_phrase:") for flag in flags))
                self.assertFalse(send_ready)


if __name__ == "__main__":
    unittest.main()
