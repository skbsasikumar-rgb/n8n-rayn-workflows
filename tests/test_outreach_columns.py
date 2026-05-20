import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

from services.crawl4ai import outreach_planner as planner


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ensure_rayn_outreach_columns.py"
WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-cold-email-planner.json"
WORKER_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-worker.json"
AUTOMATION_CONTROLLER_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-automation-controller.json"
WORKFLOW_ALERTS_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-workflow-alerts.json"
INSTANTLY_SYNC_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-instantly-lead-sync.json"
INSTANTLY_EVENTS_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-instantly-events.json"
REVIEW_APPROVAL_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "wf-review-approval.json"


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
            "email_1_llm_rewritten",
            "email_2_llm_rewritten",
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

    def test_manual_review_approval_fields_are_visible(self):
        visible = self.module.DEFAULT_VISIBLE_GRID_COLUMNS
        self.assertIn("manual_send_approval", visible)
        self.assertIn("manual_review_notes", visible)

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
        self.assertIn("email_1_llm_rewritten", self.columns)
        self.assertIn("email_2_llm_rewritten", self.columns)

    def test_llm_rewrite_markers_are_ordered_after_body_columns(self):
        names = [column.name for column in self.module.OUTREACH_COLUMNS]
        self.assertEqual(names.index("email_1_llm_rewritten"), names.index("email_1_body") + 1)
        self.assertEqual(names.index("email_2_llm_rewritten"), names.index("email_2_body") + 1)

    def test_quality_fields_exist(self):
        for name in [
            "email_quality_score",
            "email_quality_flags",
            "email_send_ready",
            "human_review_status",
            "manual_send_approval",
            "manual_approved_at",
            "manual_approved_by",
            "manual_review_notes",
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

    def test_delivery_columns_exist(self):
        expected = {
            "sender_email": "Email",
            "send_provider": "SingleSelect",
            "sequence_status": "SingleSelect",
            "send_status": "SingleSelect",
            "send_attempt_count": "Number",
            "send_error": "LongText",
            "send_last_attempted_at": "SingleLineText",
            "email_1_send_status": "SingleSelect",
            "email_1_scheduled_at": "SingleLineText",
            "email_1_sent_at": "SingleLineText",
            "email_1_message_id": "SingleLineText",
            "email_2_send_status": "SingleSelect",
            "email_2_scheduled_at": "SingleLineText",
            "email_2_sent_at": "SingleLineText",
            "email_2_message_id": "SingleLineText",
            "reply_status": "SingleSelect",
            "reply_detected_at": "SingleLineText",
            "reply_type": "SingleSelect",
            "reply_message_id": "SingleLineText",
            "reply_snippet": "LongText",
            "followup_suppressed_reason": "SingleLineText",
            "instantly_campaign_id": "SingleLineText",
            "instantly_lead_id": "SingleLineText",
            "instantly_sync_status": "SingleSelect",
            "instantly_sync_error": "LongText",
            "instantly_synced_at": "SingleLineText",
            "instantly_last_event_type": "SingleLineText",
            "instantly_last_event_at": "SingleLineText",
            "instantly_email_account": "Email",
            "delivery_test_batch_number": "Number",
            "delivery_test_sent_at": "SingleLineText",
            "delivery_test_result": "SingleSelect",
            "delivery_health_status": "SingleSelect",
        }
        for name, uidt in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, self.columns)
                self.assertEqual(self.columns[name].uidt, uidt)

    def test_delivery_select_options_cover_sequence_states(self):
        self.assertIn("instantly", self.module.SELECT_OPTIONS["send_provider"])
        self.assertNotIn("postmark", self.module.SELECT_OPTIONS["send_provider"])
        self.assertIn("email_2_scheduled", self.module.SELECT_OPTIONS["sequence_status"])
        self.assertIn("replied", self.module.SELECT_OPTIONS["sequence_status"])
        self.assertIn("cancelled", self.module.SELECT_OPTIONS["email_2_send_status"])
        self.assertIn("human_reply", self.module.SELECT_OPTIONS["reply_status"])
        self.assertIn("out_of_office", self.module.SELECT_OPTIONS["reply_type"])
        self.assertIn("synced", self.module.SELECT_OPTIONS["instantly_sync_status"])
        self.assertIn("spam", self.module.SELECT_OPTIONS["delivery_test_result"])

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
            "contact_search_status",
            "contact_search_reason",
            "contact_search_evidence_json",
            "selected_contact_source_url",
            "email_candidates_json",
            "email_validation_evidence_json",
        }
        missing = sorted(field for field in fields if field not in existing_fields and field not in self.columns)
        self.assertEqual(missing, [])

    def test_workflow_fetch_skips_existing_drafts_and_not_ready_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        self.assertIn("(email_1_subject,blank)", url_expr)
        self.assertIn("(automation_decision,blank)", url_expr)
        self.assertNotIn("(contact_search_status,notblank)", url_expr)
        self.assertIn("(contact_search_status,eq,contact_not_found)", url_expr)
        self.assertIn("(contact_search_status,eq,failed)", url_expr)
        self.assertIn("(contact_search_status,eq,skipped)", url_expr)
        self.assertIn("(validated_email,notblank)", url_expr)
        self.assertIn("(selected_contact_email,notblank)", url_expr)

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

    def test_collect_node_throws_on_provider_account_errors(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        collect_node = next(node for node in workflow["nodes"] if node["name"] == "Collect NocoDB Patches")
        js_code = collect_node["parameters"]["jsCode"]
        self.assertIn("providerAccountError", js_code)
        self.assertIn("provider_account_error", js_code)
        self.assertIn("insufficient balance", js_code)

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

    def test_url_picker_worker_picks_new_blank_status_rows(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        get_rows_node = next(node for node in workflow["nodes"] if node["name"] == "Get Blank URL Picked Rows")
        rows_node = next(node for node in workflow["nodes"] if node["name"] == "Rows To Items")
        url_expr = get_rows_node["parameters"]["url"]
        js_code = rows_node["parameters"]["jsCode"]
        self.assertIn("(status,blank)", url_expr)
        self.assertIn("(status,eq,pending)", url_expr)
        self.assertIn("(status,eq,failed_retryable)", url_expr)
        self.assertIn("(status,eq,processing)", url_expr)
        self.assertIn("processing_started_at,lt", url_expr)
        self.assertIn("RAYN_URL_PICKER_DISCOVERY_LIMIT", url_expr)
        self.assertIn("RAYN_STALE_PROCESSING_MINUTES", url_expr)
        self.assertIn("Math.min(25", url_expr)
        self.assertIn("isPendingOrNew", js_code)
        self.assertIn("status === 'failed_retryable'", js_code)
        self.assertIn("isStaleProcessing(row)", js_code)
        self.assertIn("RAYN_STALE_PROCESSING_MINUTES", js_code)

    def test_url_picker_worker_picks_retryable_and_stale_enrichment_rows(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        get_rows_node = next(node for node in workflow["nodes"] if node["name"] == "Get Enrichment Rows")
        rows_node = next(node for node in workflow["nodes"] if node["name"] == "Rows To Enrichment Items")
        url_expr = get_rows_node["parameters"]["url"]
        js_code = rows_node["parameters"]["jsCode"]
        self.assertIn("(status,eq,url_picked)", url_expr)
        self.assertIn("(status,eq,failed_retryable)", url_expr)
        self.assertIn("(status,eq,processing)", url_expr)
        self.assertIn("processing_started_at,lt", url_expr)
        self.assertIn("RAYN_STALE_PROCESSING_MINUTES", url_expr)
        self.assertIn("status === 'failed_retryable'", js_code)
        self.assertIn("isStaleProcessing(row)", js_code)
        self.assertIn("RAYN_STALE_PROCESSING_MINUTES", js_code)

    def test_url_picker_worker_claims_stamp_attempt_and_processing_times(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        for node_name in ["Continue Discovery Claim", "Continue Enrichment Claim"]:
            with self.subTest(node=node_name):
                js_code = next(node for node in workflow["nodes"] if node["name"] == node_name)["parameters"][
                    "jsCode"
                ]
                self.assertIn("const now = new Date().toISOString()", js_code)
                self.assertIn("processing_started_at: now", js_code)
                self.assertIn("last_attempted_at: now", js_code)
                self.assertIn("attempt_count: String(attempt)", js_code)
                self.assertIn("retry_eligible: 'true'", js_code)

    def test_url_picker_worker_throws_on_provider_account_errors(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        guarded_nodes = [
            "Prepare URL Discovery Pick",
            "Parse URL Pick",
            "Prepare Enrichment Patch",
        ]
        for node_name in guarded_nodes:
            with self.subTest(node=node_name):
                js_code = next(node for node in workflow["nodes"] if node["name"] == node_name)["parameters"][
                    "jsCode"
                ]
                self.assertIn("providerAccountError", js_code)
                self.assertIn("provider_account_error", js_code)
                self.assertIn("insufficient balance", js_code)
        enrichment_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare Enrichment Patch"
        )["parameters"]["jsCode"]
        self.assertIn("providerErrorFields", enrichment_code)
        self.assertNotIn("payload.error || payload.message || payload.last_error || payload", enrichment_code)

    def test_url_picker_worker_queues_contact_search_after_enrichment(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        enrichment_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare Enrichment Patch"
        )["parameters"]["jsCode"]
        self.assertIn("finalStatus === 'completed'", enrichment_code)
        self.assertIn("patch.contact_search_status = 'pending'", enrichment_code)
        self.assertIn("pending_after_enrichment", enrichment_code)

    def test_url_picker_worker_patches_transport_timeout_as_retryable(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        enrichment_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare Enrichment Patch"
        )["parameters"]["jsCode"]
        self.assertIn("isTransportTimeout(errorText)", enrichment_code)
        self.assertIn("status: 'failed_retryable'", enrichment_code)
        self.assertIn("status_reason: 'enrichment_transport_timeout'", enrichment_code)
        self.assertIn("error_type: 'enrichment_timeout'", enrichment_code)
        self.assertNotIn("if (isTransportTimeout(errorText)) {\n    return [];", enrichment_code)

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


class InstantlyWorkflowContractTests(unittest.TestCase):
    def test_automation_controller_wakes_worker_and_planner_when_enabled(self):
        workflow = json.loads(AUTOMATION_CONTROLLER_WORKFLOW_PATH.read_text())
        self.assertEqual(workflow["name"], "RAYN Automation Controller v1")
        self.assertNotIn("active", workflow)
        node_names = {node["name"] for node in workflow["nodes"]}
        self.assertIn("Schedule Trigger", node_names)
        self.assertIn("Webhook Trigger", node_names)
        self.assertIn("Build Controller Actions", node_names)
        self.assertIn("Trigger Worker Or Planner", node_names)
        build_node = next(node for node in workflow["nodes"] if node["name"] == "Build Controller Actions")
        trigger_node = next(node for node in workflow["nodes"] if node["name"] == "Trigger Worker Or Planner")
        js_code = build_node["parameters"]["jsCode"]
        self.assertIn("RAYN_AUTOMATION_CONTROLLER_ENABLED", js_code)
        self.assertIn("RAYN_AUTOMATION_WORKER_TICKS", js_code)
        self.assertIn("RAYN_AUTOMATION_CONTACT_TICKS", js_code)
        self.assertIn("RAYN_AUTOMATION_RETRY_TICKS", js_code)
        self.assertIn("RAYN_CONTACT_SEARCH_BATCH_LIMIT", js_code)
        self.assertIn("RAYN_URL_PICKER_DISCOVERY_LIMIT", js_code)
        self.assertIn("RAYN_URL_PICKER_ENRICHMENT_LIMIT", js_code)
        self.assertIn("RAYN_URL_PICKER_RETRY_LIMIT", js_code)
        self.assertIn("RAYN_AUTOMATION_PLANNER_LIMIT", js_code)
        self.assertIn("process.env", js_code)
        self.assertNotIn("$env.", js_code)
        self.assertIn(".replace(/\\/$/, '')", js_code)
        self.assertNotIn(".replace(//$/, '')", js_code)
        self.assertIn("enabledDefault", js_code)
        self.assertIn("/webhook/rayn-url-picker-batch", js_code)
        self.assertIn("retry_failed_enrichment_tick", js_code)
        self.assertIn("retry_failed: true", js_code)
        self.assertIn("/webhook/rayn-contact-search-batch", js_code)
        self.assertIn("/webhook/rayn-cold-email-planner", js_code)
        self.assertIn("copy_qa_mode: copyQaMode", js_code)
        self.assertIn("RAYN_AUTOMATION_WORKER_TICKS, 1, 0, 10", js_code)
        self.assertEqual(trigger_node["parameters"]["method"], "POST")
        self.assertEqual(trigger_node["parameters"]["url"], "={{ $json.url }}")

    def test_workflow_alerts_send_telegram_only(self):
        workflow = json.loads(WORKFLOW_ALERTS_WORKFLOW_PATH.read_text())
        self.assertEqual(workflow["name"], "RAYN Workflow Alerts v1")
        self.assertNotIn("active", workflow)
        node_names = {node["name"] for node in workflow["nodes"]}
        self.assertIn("Error Trigger", node_names)
        self.assertIn("Webhook Trigger", node_names)
        self.assertIn("Build Alert Message", node_names)
        self.assertIn("Send Telegram Alert", node_names)
        self.assertNotIn("Deactivate Automation Controller", node_names)
        alert_node = next(node for node in workflow["nodes"] if node["name"] == "Build Alert Message")
        telegram_node = next(node for node in workflow["nodes"] if node["name"] == "Send Telegram Alert")
        workflow_text = json.dumps(workflow)
        self.assertNotIn("N8N_API_KEY", workflow_text)
        self.assertNotIn("/deactivate", workflow_text)
        self.assertIn("RAYN workflow alert", alert_node["parameters"]["jsCode"])
        self.assertIn("RAYN_TELEGRAM_BOT_TOKEN", telegram_node["parameters"]["url"])
        self.assertIn("RAYN_TELEGRAM_CHAT_ID", telegram_node["parameters"]["jsonBody"])
        self.assertEqual(workflow["settings"]["saveDataSuccessExecution"], "all")
        self.assertEqual(workflow["settings"]["saveDataErrorExecution"], "all")

    def test_instantly_sync_workflow_is_inactive_export_with_gates(self):
        workflow = json.loads(INSTANTLY_SYNC_WORKFLOW_PATH.read_text())
        self.assertEqual(workflow["name"], "RAYN Instantly Lead Sync v1")
        self.assertNotIn("active", workflow)
        node_names = {node["name"] for node in workflow["nodes"]}
        self.assertIn("Schedule Trigger", node_names)
        self.assertIn("Prepare Instantly Lead", node_names)
        self.assertIn("Create Instantly Lead", node_names)
        prepare_node = next(node for node in workflow["nodes"] if node["name"] == "Prepare Instantly Lead")
        result_node = next(node for node in workflow["nodes"] if node["name"] == "Build Instantly Sync Patch")
        js_code = prepare_node["parameters"]["jsCode"]
        self.assertIn("RAYN_INSTANTLY_SYNC_ENABLED", js_code)
        self.assertIn("INSTANTLY_API_KEY", js_code)
        self.assertIn("INSTANTLY_CAMPAIGN_ID", js_code)
        self.assertIn("custom_variables", js_code)
        self.assertIn("rayn_row_id", js_code)
        self.assertIn("email_1_body_html", js_code)
        self.assertIn("email_2_body_html", js_code)
        self.assertIn("skip_if_in_workspace", js_code)
        self.assertIn("send_provider: 'instantly'", result_node["parameters"]["jsCode"])
        self.assertIn("instantly_sync_status = 'synced'", result_node["parameters"]["jsCode"])
        self.assertIn("providerAccountError", result_node["parameters"]["jsCode"])
        self.assertIn("provider_account_error", result_node["parameters"]["jsCode"])
        self.assertIn("insufficient balance", result_node["parameters"]["jsCode"])

    def test_instantly_sync_workflow_uses_strict_fetch_gate(self):
        workflow = json.loads(INSTANTLY_SYNC_WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Send Ready Rows")["parameters"]["url"]
        for fragment in [
            "(email_send_ready,eq,true)",
            "(automation_decision,eq,auto_send_eligible)",
            "(final_send_gate_passed,eq,true)",
            "(validated_email,notblank)",
            "(do_not_contact,neq,true)",
            "(unsubscribe_status,eq,active)",
            "(send_provider,neq,instantly)",
            "(instantly_sync_status,neq,synced)",
        ]:
            self.assertIn(fragment, url_expr)

    def test_review_approval_workflow_promotes_only_manually_approved_rows(self):
        workflow = json.loads(REVIEW_APPROVAL_WORKFLOW_PATH.read_text())
        self.assertEqual(workflow["name"], "RAYN Review Approval v1")
        self.assertNotIn("active", workflow)
        node_names = {node["name"] for node in workflow["nodes"]}
        for name in [
            "Schedule Trigger",
            "Webhook Trigger",
            "Get Approved Review Rows",
            "Build Approval Patches",
            "Patch Approved Reviews",
        ]:
            self.assertIn(name, node_names)

        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Approved Review Rows")[
            "parameters"
        ]["url"]
        for fragment in [
            "(automation_decision,eq,draft_only_review)",
            "(manual_send_approval,eq,approved)",
            "(validated_email,notblank)",
            "(email_1_subject,notblank)",
            "(email_1_body,notblank)",
            "(send_provider,neq,instantly)",
            "(instantly_sync_status,neq,synced)",
        ]:
            self.assertIn(fragment, url_expr)

        build_code = next(node for node in workflow["nodes"] if node["name"] == "Build Approval Patches")[
            "parameters"
        ]["jsCode"]
        for fragment in [
            "manual_approved_review",
            "email_send_ready: true",
            "final_send_gate_passed: true",
            "human_review_status: 'approved'",
            "hasFlags(row.severe_email_flags)",
            "hasFlags(row.email_quality_flags)",
        ]:
            self.assertIn(fragment, build_code)

    def test_instantly_events_workflow_updates_reply_bounce_and_sent_state(self):
        workflow = json.loads(INSTANTLY_EVENTS_WORKFLOW_PATH.read_text())
        self.assertEqual(workflow["name"], "RAYN Instantly Events v1")
        self.assertNotIn("active", workflow)
        node_names = {node["name"] for node in workflow["nodes"]}
        self.assertIn("Instantly Webhook", node_names)
        self.assertIn("Get Matching Row", node_names)
        parse_node = next(node for node in workflow["nodes"] if node["name"] == "Normalize Instantly Event")
        patch_node = next(node for node in workflow["nodes"] if node["name"] == "Build Event Patch")
        js_code = parse_node["parameters"]["jsCode"]
        patch_code = patch_node["parameters"]["jsCode"]
        self.assertIn("rayn_row_id", js_code)
        self.assertIn("reply", js_code)
        self.assertIn("bounce", js_code)
        self.assertIn("reply_status = 'human_reply'", patch_code)
        self.assertIn("email_2_send_status = 'cancelled'", patch_code)
        self.assertIn("human_reply_to_email_1", patch_code)
        self.assertIn("unsubscribe_status = 'bounced'", patch_code)
        self.assertIn("send_provider: 'instantly'", patch_code)


if __name__ == "__main__":
    unittest.main()
