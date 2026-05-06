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
            "email_3_mode",
            "enrichment_quality_score",
            "enrichment_quality_flags",
            "copy_brief_quality_score",
            "copy_brief_quality_flags",
            "severe_email_flags",
            "final_send_gate_passed",
        ]:
            self.assertIn(name, self.columns)

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
        }
        missing = sorted(field for field in fields if field not in existing_fields and field not in self.columns)
        self.assertEqual(missing, [])

    def test_workflow_fetch_skips_existing_drafts_and_not_ready_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        self.assertIn("(email_1_subject,blank)", url_expr)

    def test_cold_email_openrouter_model_is_grok(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        prepare_node = next(node for node in workflow["nodes"] if node["name"] == "Prepare OpenRouter Email Draft")
        self.assertIn("model: 'x-ai/grok-4.3'", prepare_node["parameters"]["jsCode"])
        self.assertNotIn("anthropic/claude-sonnet-4.6", prepare_node["parameters"]["jsCode"])

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
