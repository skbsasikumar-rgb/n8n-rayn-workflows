import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

from services.crawl4ai import outreach_planner as planner


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ensure_rayn_outreach_columns.py"
CONTACT_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ensure_rayn_contact_columns.py"
INSTANTLY_BACKFILL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backfill_instantly_send_ready.py"
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


def load_contact_column_script():
    if "psycopg" not in sys.modules:
        sys.modules["psycopg"] = types.ModuleType("psycopg")
    spec = importlib.util.spec_from_file_location("ensure_rayn_contact_columns", CONTACT_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_instantly_backfill_script():
    if "psycopg" not in sys.modules:
        sys.modules["psycopg"] = types.ModuleType("psycopg")
    spec = importlib.util.spec_from_file_location("backfill_instantly_send_ready", INSTANTLY_BACKFILL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
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

    def test_contact_duplicate_email_column_is_next_to_validated_email(self):
        contact_module = load_contact_column_script()
        names = [column[0] for column in contact_module.CONTACT_COLUMNS]
        validated_index = names.index("validated_email")
        self.assertEqual(names[validated_index + 1], "duplicate_validated_email_of_id")
        self.assertIn("duplicate_validated_email_of_id", contact_module.DEFAULT_VISIBLE_CONTACT_COLUMNS)

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

    def test_email_three_review_fields_are_visible_and_email_four_is_hidden(self):
        visible = self.module.DEFAULT_VISIBLE_GRID_COLUMNS
        self.assertIn("email_3_subject", visible)
        self.assertIn("email_3_body", visible)
        self.assertNotIn("email_4_subject", visible)
        self.assertNotIn("email_4_body", visible)

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

    def test_grid_order_keeps_email_three_after_email_two(self):
        self.assertEqual(self.module.GRID_COLUMN_AFTER["email_3_subject"], "email_2_llm_rewritten")
        self.assertEqual(self.module.GRID_COLUMN_AFTER["email_3_body"], "email_3_subject")

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
            "status_reason",
            "last_stage",
            "attempt_count",
            "contact_search_status",
            "contact_search_reason",
            "contact_search_evidence_json",
            "selected_contact_source_url",
            "email_candidates_json",
            "email_validation_evidence_json",
            "duplicate_validated_email_of_id",
        }
        missing = sorted(field for field in fields if field not in existing_fields and field not in self.columns)
        self.assertEqual(missing, [])
        self.assertIn("status_reason", fields)
        self.assertIn("last_stage", fields)

    def test_workflow_fetch_skips_planned_and_not_ready_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        self.assertIn("(automation_decision,blank)", url_expr)
        self.assertNotIn("(email_1_subject,blank)", url_expr)
        self.assertNotIn("(contact_search_status,notblank)", url_expr)
        self.assertIn("(contact_search_status,eq,contact_not_found)", url_expr)
        self.assertIn("(contact_search_status,eq,failed)", url_expr)
        self.assertIn("(contact_search_status,eq,skipped)", url_expr)
        self.assertIn("(validated_email,notblank)", url_expr)
        self.assertIn("(duplicate_validated_email_of_id,blank)", url_expr)
        self.assertIn("(selected_contact_email,notblank)", url_expr)

    def test_workflow_fetch_does_not_refetch_suppressed_rows(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        url_expr = next(node for node in workflow["nodes"] if node["name"] == "Get Outreach Rows")["parameters"]["url"]
        self.assertIn("~and(automation_decision,blank)", url_expr)
        self.assertNotIn("~and(email_1_subject,blank)", url_expr)

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
        self.assertIn("'status_reason'", js_code)
        self.assertIn("'last_stage'", js_code)

    def test_cold_email_planner_live_mode_is_not_hardcoded_draft_only(self):
        workflow = json.loads(WORKFLOW_PATH.read_text())
        rows_node = next(node for node in workflow["nodes"] if node["name"] == "Rows To Items")
        js_code = rows_node["parameters"]["jsCode"]
        self.assertNotIn("const draftOnly = true", js_code)
        self.assertIn("RAYN_COLD_EMAIL_DRAFT_ONLY", js_code)
        self.assertIn("draft_only: draftOnly", js_code)

    def test_url_picker_worker_picks_new_blank_status_rows(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        get_rows_node = next(node for node in workflow["nodes"] if node["name"] == "Get Blank URL Picked Rows")
        rows_node = next(node for node in workflow["nodes"] if node["name"] == "Rows To Items")
        url_expr = get_rows_node["parameters"]["url"]
        js_code = rows_node["parameters"]["jsCode"]
        self.assertIn("(status,blank)", url_expr)
        self.assertIn("(status,eq,pending)", url_expr)
        self.assertIn("(status,eq,failed_retryable)", url_expr)
        self.assertIn("skipped_url_validation_failed", url_expr)
        self.assertIn("best_url,canonical_domain", url_expr)
        self.assertIn("(status,eq,processing)", url_expr)
        self.assertIn("processing_started_at,lt", url_expr)
        self.assertIn("RAYN_URL_PICKER_DISCOVERY_LIMIT", url_expr)
        self.assertIn("RAYN_STALE_PROCESSING_MINUTES", url_expr)
        self.assertIn("Math.min(25", url_expr)
        self.assertIn("isPendingOrNew", js_code)
        self.assertIn("status === 'failed_retryable'", js_code)
        self.assertIn("isUrlRediscovery", js_code)
        self.assertIn("RAYN_MAX_URL_REDISCOVERY_ATTEMPTS", js_code)
        self.assertIn("skipped_url_validation_failed", js_code)
        self.assertIn("canonical_domain", js_code)
        self.assertIn("excludedUrlDomain", js_code)
        self.assertIn("excluded_url_domain: excludedUrlDomain(row)", js_code)
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
        self.assertIn("(status,eq,failed)", url_expr)
        self.assertIn("(retry_eligible,eq,true)", url_expr)
        self.assertIn("(automation_decision,eq,retry_enrichment_once)", url_expr)
        self.assertIn("automation_decision,automation_decision_reason", url_expr)
        self.assertIn("(status,eq,processing)", url_expr)
        self.assertIn("processing_started_at,lt", url_expr)
        self.assertIn("(manual_url_override,notblank)", url_expr)
        self.assertIn("(status_reason,eq,no_official_url_found)", url_expr)
        self.assertIn("(send_provider,neq,instantly)", url_expr)
        self.assertIn("(instantly_sync_status,neq,synced)", url_expr)
        self.assertIn("send_provider,send_status,sequence_status,instantly_sync_status", url_expr)
        self.assertIn("manual_url_override", url_expr)
        self.assertIn("RAYN_STALE_PROCESSING_MINUTES", url_expr)
        self.assertIn("isRetryableFailure", js_code)
        self.assertIn("status === 'failed_retryable' || status === 'failed'", js_code)
        self.assertIn("RAYN_MAX_ENRICHMENT_ATTEMPTS", js_code)
        self.assertIn("isWeakEnrichmentRetry", js_code)
        self.assertIn("automation_decision || '').trim() === 'retry_enrichment_once'", js_code)
        self.assertIn("isStaleProcessing(row)", js_code)
        self.assertIn("isManualUrlOverride", js_code)
        self.assertIn("isAlreadyInSendPipeline", js_code)
        self.assertIn("provider === 'instantly'", js_code)
        self.assertIn("syncStatus === 'synced'", js_code)
        self.assertIn("if (isAlreadyInSendPipeline(row)) return false", js_code)
        self.assertIn("manual_url_override: manualUrl", js_code)
        self.assertIn("send_provider: String(row.send_provider || '').trim()", js_code)
        self.assertIn("instantly_sync_status: String(row.instantly_sync_status || '').trim()", js_code)
        self.assertIn("canonicalDomain(manualUrl)", js_code)
        self.assertIn("startsWith('https://')", js_code)
        self.assertNotIn("/^https?:///", js_code)
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

    def test_url_picker_worker_clears_stale_planner_fields_for_weak_enrichment_retry(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        claim_node = next(node for node in workflow["nodes"] if node["name"] == "Claim Enrichment Row")
        body_expr = claim_node["parameters"]["jsonBody"]
        self.assertIn("weakRetry", body_expr)
        self.assertIn("retry_enrichment_once", body_expr)
        self.assertIn("automation_decision: ''", body_expr)
        self.assertIn("email_1_subject: ''", body_expr)
        self.assertIn("email_2_body: ''", body_expr)
        self.assertIn("email_3_body: ''", body_expr)
        self.assertIn("manual_url_override", body_expr)
        self.assertIn("url_picked: manualUrl", body_expr)
        self.assertIn("canonical_domain: manualDomain", body_expr)
        self.assertIn("processing:crawl:manual_url_override", body_expr)
        self.assertIn("final_send_gate_passed: false", body_expr)
        self.assertIn("email_send_ready: false", body_expr)

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

    def test_url_picker_worker_rejects_third_party_article_fallbacks(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        parse_code = next(node for node in workflow["nodes"] if node["name"] == "Parse URL Pick")[
            "parameters"
        ]["jsCode"]
        self.assertIn("thirdPartyEditorialCandidate", parse_code)
        self.assertIn("pathSegmentCount(url)", parse_code)
        self.assertIn("strongHostIdentity", parse_code)
        self.assertIn("textHasCompanyIdentity", parse_code)
        self.assertIn("const deepPath = pathSegmentCount(candidate) > 1", parse_code)
        self.assertIn("if (deepPath && !hostStrong && !hostedOfficial) continue", parse_code)
        self.assertIn("\\bhomepage\\b", parse_code)
        self.assertNotIn("\\bhome\\b|\\bour\\s+clinic\\b", parse_code)
        self.assertIn("cosmeticsnews", parse_code)
        self.assertIn("acquisition", parse_code)
        self.assertIn("wa.me", parse_code)
        self.assertIn("chas.sg", parse_code)
        self.assertIn("giving.sg", parse_code)
        self.assertIn("prospeo.io", parse_code)
        self.assertIn("businesstimes.com.sg", parse_code)
        self.assertIn("'singapore','clinic','group','health'", parse_code)
        self.assertIn("thirdPartyEditorialCandidate(candidate, prepared.company_name)", parse_code)
        self.assertIn("thirdPartyEditorialCandidate(url, prepared.company_name)", parse_code)

    def test_url_picker_worker_rediscovery_excludes_previous_failed_domain(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        build_code = next(node for node in workflow["nodes"] if node["name"] == "Build URL Discovery Query")[
            "parameters"
        ]["jsCode"]
        prepare_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare URL Discovery Pick"
        )["parameters"]["jsCode"]
        parse_code = next(node for node in workflow["nodes"] if node["name"] == "Parse URL Pick")[
            "parameters"
        ]["jsCode"]
        continue_code = next(
            node for node in workflow["nodes"] if node["name"] == "Continue Discovery Claim"
        )["parameters"]["jsCode"]
        webhook_code = next(node for node in workflow["nodes"] if node["name"] == "Webhook To Item")[
            "parameters"
        ]["jsCode"]
        self.assertIn("excluded_url_domain", build_code)
        self.assertIn("rediscoveryExcludedDomain", build_code)
        self.assertIn("reason === 'skipped_url_validation_failed'", build_code)
        self.assertIn("-site:", build_code)
        self.assertIn("canonical_domain", build_code)
        self.assertIn("Retry rule: reject the previous failed domain", prepare_code)
        self.assertIn("excluded_url_domain", prepare_code)
        self.assertIn("isExcludedCandidate", parse_code)
        self.assertIn("canonicalDomain(url) === excluded", parse_code)
        self.assertIn("isExcludedCandidate(candidate, prepared)", parse_code)
        self.assertIn("isExcludedCandidate(candidatePickedUrl, prepared)", parse_code)
        self.assertIn("best_url: operatingRootUrl || pickedUrl", parse_code)
        self.assertIn("rediscoveryExcludedDomain", continue_code)
        self.assertIn("excluded_url_domain: excludedDomain", continue_code)
        self.assertIn("excluded_url_domain: String(payload.excluded_url_domain || '').trim()", webhook_code)
        self.assertIn("canonical_domain: String(payload.canonical_domain || '').trim()", webhook_code)
        claim_body = next(node for node in workflow["nodes"] if node["name"] == "Claim Discovery Row")[
            "parameters"
        ]["jsonBody"]
        self.assertIn("url_picked: String($json.url_picked || '')", claim_body)
        self.assertIn("best_url: String($json.best_url || '')", claim_body)
        self.assertIn("canonical_domain: String($json.canonical_domain || '')", claim_body)
        patch_body = next(node for node in workflow["nodes"] if node["name"] == "Patch URL Picked")[
            "parameters"
        ]["jsonBody"]
        self.assertIn("best_url: $json.best_url", patch_body)

    def test_url_picker_worker_caps_large_enrichment_background_fields(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        enrichment_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare Enrichment Patch"
        )["parameters"]["jsCode"]
        for field in [
            "services_detected",
            "locations_detected",
            "contact_info_detected",
            "leadership_or_team_signals",
        ]:
            self.assertIn(f"patch.{field} = limitLongText(patch.{field} || '', 20000)", enrichment_code)

    def test_url_picker_worker_patches_transport_timeout_as_retryable(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        enrichment_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare Enrichment Patch"
        )["parameters"]["jsCode"]
        self.assertIn("isTransportTimeout(errorText)", enrichment_code)
        self.assertIn("text.includes('timeout')", enrichment_code)
        self.assertIn("status: 'failed_retryable'", enrichment_code)
        self.assertIn("status_reason: 'enrichment_transport_timeout'", enrichment_code)
        self.assertIn("enrichment_transport_timeout_preserved_existing_url", enrichment_code)
        self.assertIn("pending_after_preserved_enrichment_timeout", enrichment_code)
        self.assertIn("source.url_picked", enrichment_code)
        self.assertIn("best_url: sourceBestUrl", enrichment_code)
        self.assertIn("error_type: 'enrichment_timeout'", enrichment_code)
        self.assertIn("finalStatus === 'failed_retryable'", enrichment_code)
        self.assertIn("genericMaxAttemptsReached", enrichment_code)
        self.assertIn("retry_eligible: genericMaxAttemptsReached ? 'false' : 'true'", enrichment_code)
        self.assertNotIn("if (isTransportTimeout(errorText)) {\n    return [];", enrichment_code)

    def test_url_picker_worker_respects_public_enrichment_page_limit_cap(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        enrichment_code = next(
            node for node in workflow["nodes"] if node["name"] == "Prepare Public Enrichment"
        )["parameters"]["jsCode"]
        self.assertIn("page_limit: stage === 'deep_retry' ? 12 : 8", enrichment_code)
        self.assertNotIn("? 14 : 8", enrichment_code)

    def test_contact_search_runs_as_async_row_jobs(self):
        workflow = json.loads(WORKER_WORKFLOW_PATH.read_text())
        node_names = {node["name"] for node in workflow["nodes"]}
        for node_name in [
            "Get Contact Search Rows",
            "Rows To Contact Search Items",
            "Claim Contact Search Row",
            "Continue Contact Search Claim",
            "Run Contact Search Row",
            "Build Contact Search Transport Patches",
            "Patch Contact Search Transport Failure",
        ]:
            with self.subTest(node=node_name):
                self.assertIn(node_name, node_names)
        self.assertNotIn("Run Contact Search Batch", node_names)

        connections = workflow["connections"]
        self.assertEqual(
            connections["Webhook Contact Search Trigger"]["main"][0][0]["node"],
            "Get Contact Search Rows",
        )
        self.assertEqual(
            connections["Continue Contact Search Claim"]["main"][0][0]["node"],
            "Run Contact Search Row",
        )

        get_node = next(node for node in workflow["nodes"] if node["name"] == "Get Contact Search Rows")
        get_url = get_node["parameters"]["url"]
        self.assertIn("RAYN_CONTACT_SEARCH_BATCH_LIMIT", get_url)
        self.assertIn("(contact_search_status,eq,pending)", get_url)
        self.assertIn("(send_provider,neq,instantly)", get_url)
        self.assertIn("(instantly_sync_status,neq,synced)", get_url)
        self.assertIn("send_provider,send_status,sequence_status,instantly_sync_status", get_url)
        self.assertIn("duplicate_validated_email_of_id", get_url)
        self.assertIn("&sort=Id", get_url)

        claim_node = next(node for node in workflow["nodes"] if node["name"] == "Claim Contact Search Row")
        claim_body = claim_node["parameters"]["jsonBody"]
        self.assertIn("processing:contact_search_claimed", claim_body)
        self.assertIn("selected_contact_source_url", claim_body)
        self.assertIn("duplicate_validated_email_of_id", claim_body)

        run_node = next(node for node in workflow["nodes"] if node["name"] == "Run Contact Search Row")
        self.assertIn("/contact-enrich-row", run_node["parameters"]["url"])
        self.assertIn("row_id: $json.Id", run_node["parameters"]["jsonBody"])
        self.assertEqual(run_node["parameters"]["options"]["timeout"], 30000)
        self.assertTrue(run_node.get("continueOnFail"))

        patch_node = next(
            node for node in workflow["nodes"] if node["name"] == "Build Contact Search Transport Patches"
        )
        patch_code = patch_node["parameters"]["jsCode"]
        self.assertIn("status: 'failed_retryable'", patch_code)
        self.assertIn("contact_search_transport_timeout", patch_code)

    def test_contact_search_backend_accepts_async_row_jobs(self):
        app_source = (Path(__file__).resolve().parents[1] / "services" / "crawl4ai" / "app.py").read_text()
        self.assertIn("class ContactRowRunRequest", app_source)
        self.assertIn('CONTACT_ROW_ASYNC_CONCURRENCY', app_source)
        self.assertIn('@app.post("/contact-enrich-row")', app_source)
        self.assertIn("asyncio.create_task(run_contact_row_background", app_source)
        self.assertIn("noco_fetch_contact_rows(1, [row_id])", app_source)
        self.assertIn("def noco_find_duplicate_validated_email", app_source)
        self.assertIn("annotate_validated_email_duplicate(patch)", app_source)
        self.assertIn("suppressed_duplicate_validated_email", app_source)

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

    def test_planner_marks_auto_send_rows_ready_for_instantly_sync(self):
        result = planner.plan_and_patch(
            {
                "Id": 457,
                "company_name": "Example Dental Clinic",
                "best_url": "https://exampledental.sg/",
                "canonical_domain": "exampledental.sg",
                "website_content": (
                    "Singapore dental clinic providing dental appointments, patient treatment, "
                    "dental records, and oral health services."
                ),
                "validated_email": "hello@exampledental.sg",
                "email_validation_evidence_json": json.dumps({"status": "sendable"}),
                "contact_search_reason": "sendable_company_email_found",
            }
        )
        patch = result["patch"]
        self.assertEqual(patch["automation_decision"], "auto_send_eligible")
        self.assertTrue(patch["final_send_gate_passed"])
        self.assertTrue(patch["email_send_ready"])
        self.assertEqual(patch["unsubscribe_status"], "active")
        self.assertEqual(patch["sequence_status"], "not_queued")
        self.assertEqual(patch["send_status"], "not_ready")
        self.assertEqual(patch["instantly_sync_status"], "not_synced")

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

    def test_hia_email_1_third_paragraph_keeps_cyber_data_security_route(self):
        for row_id in range(1, 12):
            with self.subTest(row_id=row_id):
                plan = planner.plan_outreach(
                    {
                        "Id": row_id,
                        "company_name": "Example Dental Clinic",
                        "best_url": "https://example.sg/",
                        "website_content": (
                            "Singapore dental clinic providing dental appointments, patient treatment, "
                            "dental records, dentists, oral health services, and patient care."
                        ),
                        "disable_llm_rewrite": True,
                    }
                )
                body = plan.emails["email_1"]["body"]
                self.assertEqual(plan.classification["pressure_type"], "hia_regulatory")
                self.assertTrue(planner.hia_email_1_cyber_data_security_paragraph_ok(body), body)

    def test_hia_llm_rewrite_rejects_email_1_without_cyber_data_security_route(self):
        classification = {"pressure_type": "hia_regulatory"}
        deterministic = (
            "Hello team, does Example Dental Clinic keep patient records across appointment and dental software?\n\n"
            "If so, HIA starting from 2027 makes that trail the issue.\n\n"
            "We help map that trail into a Cyber Essentials route for the HIA cyber/data-security side.\n\n"
            "Worth sending the HIA readiness map?"
        )
        weak_rewrite = (
            "Hello team, does Example Dental Clinic keep patient records across appointment and dental software?\n\n"
            "If so, HIA starting from 2027 makes that trail the issue.\n\n"
            "Cyber Essentials is a practical first baseline before deeper HIA work.\n\n"
            "Worth sending the HIA readiness map?"
        )
        flags = planner.email_1_rewrite_static_flags(weak_rewrite, deterministic, classification)
        self.assertIn("llm_email_1_rewrite_missing_hia_cyber_data_security", flags)
        self.assertNotIn(
            "llm_email_1_rewrite_missing_hia_cyber_data_security",
            planner.email_1_rewrite_static_flags(deterministic, deterministic, classification),
        )

    def test_email_rewrite_prompt_requires_hia_cyber_data_security_in_email_1(self):
        self.assertIn("HIA cyber/data-security side", planner.EMAIL_1_REWRITE_PROMPT)
        self.assertIn("Email 1 paragraph 3", planner.EMAIL_1_REWRITE_PROMPT)


class InstantlyBackfillScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_instantly_backfill_script()

    def test_backfill_where_matches_strict_instantly_gate(self):
        where = self.module.ELIGIBLE_WHERE
        for fragment in [
            "automation_decision = 'auto_send_eligible'",
            "final_send_gate_passed is true",
            "coalesce(validated_email, '') <> ''",
            "coalesce(email_1_subject, '') <> ''",
            "coalesce(email_1_body, '') <> ''",
            "coalesce(do_not_contact, false) is false",
            "coalesce(send_provider, '') <> 'instantly'",
            "coalesce(instantly_sync_status, '') not in ('synced', 'skipped')",
            "coalesce(severe_email_flags, '') in ('', '[]')",
            "coalesce(email_quality_flags, '') in ('', '[]')",
        ]:
            self.assertIn(fragment, where)

    def test_quote_identifier_escapes_double_quotes(self):
        self.assertEqual(self.module.quote_identifier('bad"name'), '"bad""name"')


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
        self.assertIn("email_3_subject", js_code)
        self.assertIn("email_3_body", js_code)
        self.assertIn("email_3_body_html", js_code)
        self.assertIn("skip_if_in_workspace", js_code)
        self.assertIn("return candidates.map((row) =>", js_code)
        self.assertNotIn("const row = candidates[0]", js_code)
        self.assertIn("send_provider: 'instantly'", result_node["parameters"]["jsCode"])
        self.assertIn("instantly_sync_status = 'synced'", result_node["parameters"]["jsCode"])
        self.assertIn("json: { patches }", result_node["parameters"]["jsCode"])
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
            "(email_3_subject,notblank)",
            "(email_3_body,notblank)",
            "(duplicate_validated_email_of_id,blank)",
            "(do_not_contact,neq,true)",
            "(unsubscribe_status,eq,active)",
            "(send_provider,neq,instantly)",
            "(instantly_sync_status,neq,synced)",
            "(email_quality_flags,eq,[])",
            "(severe_email_flags,eq,[])",
        ]:
            self.assertIn(fragment, url_expr)
        self.assertIn("email_3_subject", url_expr)
        self.assertIn("email_3_body", url_expr)
        prepare_node = next(node for node in workflow["nodes"] if node["name"] == "Prepare Instantly Lead")
        patch_node = next(node for node in workflow["nodes"] if node["name"] == "Patch Instantly Sync Result")
        self.assertIn("requestedLimit", url_expr)
        self.assertIn("envLimit >= 5 ? envLimit : 25", url_expr)
        self.assertIn("duplicate_validated_email_of_id", prepare_node["parameters"]["jsCode"])
        self.assertIn("!text(row.email_3_subject)", prepare_node["parameters"]["jsCode"])
        self.assertIn("!text(row.email_3_body)", prepare_node["parameters"]["jsCode"])
        self.assertIn("$json.patches", patch_node["parameters"]["jsonBody"])

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
