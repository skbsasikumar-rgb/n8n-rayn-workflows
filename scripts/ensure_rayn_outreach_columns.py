#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import string
from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class OutreachColumn:
    name: str
    uidt: str
    db_type: str
    grid_width: str = "220px"


OUTREACH_COLUMNS: list[OutreachColumn] = [
    # Company identity / entity enrichment
    OutreachColumn("entity_type_guess", "SingleSelect", "text"),
    OutreachColumn("entity_type_confidence", "SingleSelect", "text"),
    OutreachColumn("singapore_registered_guess", "Checkbox", "boolean", "160px"),
    OutreachColumn("uen_guess", "SingleLineText", "text"),
    OutreachColumn("uen_source_url", "URL", "text"),
    OutreachColumn("employee_count_guess", "Number", "numeric", "160px"),
    OutreachColumn("sme_likelihood", "SingleSelect", "text"),
    OutreachColumn("npo_likelihood", "SingleSelect", "text"),
    OutreachColumn("charity_or_social_service_likelihood", "SingleSelect", "text"),
    OutreachColumn("entity_evidence_json", "LongText", "text", "360px"),
    # Pressure classification
    OutreachColumn("pressure_type", "SingleSelect", "text"),
    OutreachColumn("primary_email_track", "SingleSelect", "text"),
    OutreachColumn("secondary_email_track", "SingleSelect", "text"),
    OutreachColumn("regulatory_applicability", "LongText", "text", "300px"),
    OutreachColumn("classification_confidence", "SingleSelect", "text"),
    OutreachColumn("classification_evidence_json", "LongText", "text", "420px"),
    OutreachColumn("classification_rejected_tracks_json", "LongText", "text", "360px"),
    OutreachColumn("pressure_reason", "LongText", "text", "360px"),
    OutreachColumn("outreach_trigger_signal", "LongText", "text", "360px"),
    OutreachColumn("outreach_trigger_source_url", "URL", "text"),
    OutreachColumn("outreach_trigger_confidence", "SingleSelect", "text"),
    OutreachColumn("data_type_signal", "SingleSelect", "text"),
    OutreachColumn("problem_area", "SingleSelect", "text"),
    OutreachColumn("problem_hypothesis", "LongText", "text", "360px"),
    OutreachColumn("value_asset_offer", "SingleSelect", "text"),
    # HIA enrichment
    OutreachColumn("hia_relevant", "Checkbox", "boolean", "140px"),
    OutreachColumn("hia_relevance_score", "Number", "numeric", "160px"),
    OutreachColumn("hia_confidence", "SingleSelect", "text"),
    OutreachColumn("hia_scope_reason", "LongText", "text", "360px"),
    OutreachColumn("hia_service_type_guess", "SingleSelect", "text"),
    OutreachColumn("hia_official_service_type", "SingleSelect", "text"),
    OutreachColumn("hia_official_service_label", "SingleLineText", "text"),
    OutreachColumn("hia_timeline_batch_guess", "SingleSelect", "text"),
    OutreachColumn("hia_deadline_claim_safe", "Checkbox", "boolean", "160px"),
    OutreachColumn("hia_disclaimer_needed", "Checkbox", "boolean", "160px"),
    OutreachColumn("hia_evidence_json", "LongText", "text", "360px"),
    # PDPA / data-protection enrichment
    OutreachColumn("pdpa_relevant", "Checkbox", "boolean", "140px"),
    OutreachColumn("pdpa_reason", "LongText", "text", "360px"),
    OutreachColumn("personal_data_intensity", "SingleSelect", "text"),
    OutreachColumn("sensitive_data_likelihood", "SingleSelect", "text"),
    OutreachColumn("pdpa_safeguard_angle", "SingleSelect", "text"),
    OutreachColumn("recommended_first_cert", "SingleSelect", "text"),
    OutreachColumn("recommended_cert_path", "LongText", "text", "360px"),
    OutreachColumn("certification_reason", "LongText", "text", "360px"),
    OutreachColumn("certification_fit_score", "Number", "numeric", "160px"),
    OutreachColumn("certification_evidence_json", "LongText", "text", "360px"),
    # Funding enrichment
    OutreachColumn("funding_status", "SingleSelect", "text"),
    OutreachColumn("funding_relevant", "Checkbox", "boolean", "140px"),
    OutreachColumn("primary_funding_program", "SingleLineText", "text"),
    OutreachColumn("funding_programs_matched_json", "LongText", "text", "360px"),
    OutreachColumn("funding_programs_possible_json", "LongText", "text", "360px"),
    OutreachColumn("funding_programs_not_applicable_json", "LongText", "text", "360px"),
    OutreachColumn("funding_eligibility_basis", "LongText", "text", "360px"),
    OutreachColumn("funding_claim_line", "LongText", "text", "360px"),
    OutreachColumn("funding_cta_asset", "SingleSelect", "text"),
    OutreachColumn("funding_confidence", "SingleSelect", "text"),
    OutreachColumn("funding_last_checked_at", "SingleLineText", "text"),
    OutreachColumn("funding_source_urls_json", "LongText", "text", "360px"),
    OutreachColumn("funding_human_review_required", "Checkbox", "boolean", "180px"),
    # Existing public-enrichment fields consumed by the copy brief.
    OutreachColumn("services_detected", "LongText", "text", "360px"),
    OutreachColumn("locations_detected", "LongText", "text", "360px"),
    OutreachColumn("leadership_or_team_signals", "LongText", "text", "360px"),
    OutreachColumn("contact_info_detected", "LongText", "text", "360px"),
    OutreachColumn("structured_data_detected", "LongText", "text", "360px"),
    OutreachColumn("website_content", "LongText", "text", "420px"),
    OutreachColumn("source_urls", "LongText", "text", "360px"),
    OutreachColumn("company_homepage_name", "SingleLineText", "text"),
    OutreachColumn("parent_company", "SingleLineText", "text"),
    OutreachColumn("industry_guess", "SingleLineText", "text"),
    # Copy brief enrichment
    OutreachColumn("company_profile_summary", "LongText", "text", "360px"),
    OutreachColumn("business_model_guess", "SingleSelect", "text"),
    OutreachColumn("primary_services_summary", "LongText", "text", "360px"),
    OutreachColumn("locations_summary", "LongText", "text", "360px"),
    OutreachColumn("team_structure_summary", "LongText", "text", "360px"),
    OutreachColumn("personal_data_handled_guess", "LongText", "text", "360px"),
    OutreachColumn("sensitive_data_examples", "LongText", "text", "360px"),
    OutreachColumn("data_systems_likely", "LongText", "text", "360px"),
    OutreachColumn("data_flow_complexity", "SingleSelect", "text"),
    OutreachColumn("data_risk_reason", "LongText", "text", "360px"),
    OutreachColumn("regulatory_pressure_summary", "LongText", "text", "360px"),
    OutreachColumn("hia_obligation_angle", "LongText", "text", "360px"),
    OutreachColumn("pdpa_obligation_angle", "LongText", "text", "360px"),
    OutreachColumn("customer_trust_angle", "LongText", "text", "360px"),
    OutreachColumn("deadline_or_timeline_angle", "LongText", "text", "360px"),
    OutreachColumn("funding_entity_basis", "LongText", "text", "360px"),
    OutreachColumn("funding_route_summary", "LongText", "text", "360px"),
    OutreachColumn("funding_specificity_level", "SingleSelect", "text"),
    OutreachColumn("funding_claim_safe", "Checkbox", "boolean", "160px"),
    OutreachColumn("funding_next_check_needed", "LongText", "text", "360px"),
    OutreachColumn("clinic_size_guess", "SingleSelect", "text"),
    OutreachColumn("clinic_size_confidence", "SingleSelect", "text"),
    OutreachColumn("endpoint_band_guess", "SingleSelect", "text"),
    OutreachColumn("endpoint_band_confidence", "SingleSelect", "text"),
    OutreachColumn("pricing_email_2_mode", "SingleSelect", "text"),
    OutreachColumn("pricing_claim_safe", "Checkbox", "boolean", "160px"),
    OutreachColumn("pricing_claim_line", "LongText", "text", "360px"),
    OutreachColumn("pricing_evidence_json", "LongText", "text", "360px"),
    OutreachColumn("email_personalisation_signal", "LongText", "text", "360px"),
    OutreachColumn("email_personalisation_quote", "LongText", "text", "360px"),
    OutreachColumn("email_personalisation_source_url", "URL", "text"),
    OutreachColumn("email_problem_statement", "LongText", "text", "360px"),
    OutreachColumn("email_mechanism_statement", "LongText", "text", "360px"),
    OutreachColumn("email_asset_offer", "LongText", "text", "360px"),
    OutreachColumn("email_cta", "SingleLineText", "text"),
    OutreachColumn("email_angle_reason", "LongText", "text", "360px"),
    # Contact / compliance fields used by the draft planner
    OutreachColumn("selected_contact_name", "SingleLineText", "text"),
    OutreachColumn("selected_contact_role", "SingleLineText", "text"),
    OutreachColumn("selected_contact_title", "SingleLineText", "text"),
    OutreachColumn("selected_contact_email", "Email", "text"),
    OutreachColumn("selected_contact_linkedin_url", "URL", "text"),
    OutreachColumn("validated_email", "Email", "text"),
    OutreachColumn("decision_maker_role_guess", "SingleSelect", "text"),
    OutreachColumn("do_not_contact", "Checkbox", "boolean", "140px"),
    OutreachColumn("unsubscribe_status", "SingleSelect", "text"),
    OutreachColumn("email_source", "SingleLineText", "text"),
    # Email draft fields
    OutreachColumn("outreach_variant", "SingleSelect", "text"),
    OutreachColumn("email_1_subject", "SingleLineText", "text"),
    OutreachColumn("email_1_body", "LongText", "text", "420px"),
    OutreachColumn("email_1_llm_rewritten", "Checkbox", "boolean", "160px"),
    OutreachColumn("email_2_subject", "SingleLineText", "text"),
    OutreachColumn("email_2_body", "LongText", "text", "420px"),
    OutreachColumn("email_2_llm_rewritten", "Checkbox", "boolean", "160px"),
    OutreachColumn("email_3_subject", "SingleLineText", "text"),
    OutreachColumn("email_3_body", "LongText", "text", "420px"),
    OutreachColumn("email_4_subject", "SingleLineText", "text"),
    OutreachColumn("email_4_body", "LongText", "text", "420px"),
    OutreachColumn("email_sequence_json", "LongText", "text", "420px"),
    OutreachColumn("email_quality_score", "Number", "numeric", "160px"),
    OutreachColumn("email_quality_flags", "LongText", "text", "360px"),
    OutreachColumn("email_send_ready", "Checkbox", "boolean", "140px"),
    OutreachColumn("human_review_status", "SingleSelect", "text"),
    # Deterministic automation decision fields
    OutreachColumn("automation_decision", "SingleSelect", "text"),
    OutreachColumn("automation_decision_reason", "SingleLineText", "text"),
    OutreachColumn("automation_blockers_json", "LongText", "text", "360px"),
    OutreachColumn("automation_advisory_flags_json", "LongText", "text", "360px"),
    OutreachColumn("contact_send_mode", "SingleSelect", "text"),
    OutreachColumn("contact_identity_confidence", "SingleSelect", "text"),
    OutreachColumn("email_2_mode", "SingleSelect", "text"),
    OutreachColumn("funding_followup_mode", "SingleSelect", "text"),
    OutreachColumn("email_3_mode", "SingleSelect", "text"),
    OutreachColumn("enrichment_quality_score", "Number", "numeric", "160px"),
    OutreachColumn("enrichment_quality_flags", "LongText", "text", "360px"),
    OutreachColumn("copy_brief_quality_score", "Number", "numeric", "160px"),
    OutreachColumn("copy_brief_quality_flags", "LongText", "text", "360px"),
    OutreachColumn("severe_email_flags", "LongText", "text", "360px"),
    OutreachColumn("final_send_gate_passed", "Checkbox", "boolean", "160px"),
    # Controlled delivery / sequence fields
    OutreachColumn("sender_email", "Email", "text"),
    OutreachColumn("send_provider", "SingleSelect", "text"),
    OutreachColumn("sequence_status", "SingleSelect", "text"),
    OutreachColumn("send_status", "SingleSelect", "text"),
    OutreachColumn("send_attempt_count", "Number", "numeric", "160px"),
    OutreachColumn("send_error", "LongText", "text", "360px"),
    OutreachColumn("send_last_attempted_at", "SingleLineText", "text"),
    OutreachColumn("email_1_send_status", "SingleSelect", "text"),
    OutreachColumn("email_1_scheduled_at", "SingleLineText", "text"),
    OutreachColumn("email_1_sent_at", "SingleLineText", "text"),
    OutreachColumn("email_1_message_id", "SingleLineText", "text"),
    OutreachColumn("email_2_send_status", "SingleSelect", "text"),
    OutreachColumn("email_2_scheduled_at", "SingleLineText", "text"),
    OutreachColumn("email_2_sent_at", "SingleLineText", "text"),
    OutreachColumn("email_2_message_id", "SingleLineText", "text"),
    OutreachColumn("reply_status", "SingleSelect", "text"),
    OutreachColumn("reply_detected_at", "SingleLineText", "text"),
    OutreachColumn("reply_type", "SingleSelect", "text"),
    OutreachColumn("reply_message_id", "SingleLineText", "text"),
    OutreachColumn("reply_snippet", "LongText", "text", "360px"),
    OutreachColumn("followup_suppressed_reason", "SingleLineText", "text"),
    OutreachColumn("instantly_campaign_id", "SingleLineText", "text"),
    OutreachColumn("instantly_lead_id", "SingleLineText", "text"),
    OutreachColumn("instantly_sync_status", "SingleSelect", "text"),
    OutreachColumn("instantly_sync_error", "LongText", "text", "360px"),
    OutreachColumn("instantly_synced_at", "SingleLineText", "text"),
    OutreachColumn("instantly_last_event_type", "SingleLineText", "text"),
    OutreachColumn("instantly_last_event_at", "SingleLineText", "text"),
    OutreachColumn("instantly_email_account", "Email", "text"),
    OutreachColumn("delivery_test_batch_number", "Number", "numeric", "180px"),
    OutreachColumn("delivery_test_sent_at", "SingleLineText", "text"),
    OutreachColumn("delivery_test_result", "SingleSelect", "text"),
    OutreachColumn("delivery_health_status", "SingleSelect", "text"),
]

DEFAULT_VISIBLE_GRID_COLUMNS = {
    "company_name",
    "status",
    "best_url",
    "contact_search_status",
    "contact_search_reason",
    "selected_contact_name",
    "selected_contact_role",
    "validated_email",
    "entity_type_guess",
    "pressure_type",
    "primary_email_track",
    "classification_confidence",
    "hia_service_type_guess",
    "hia_official_service_type",
    "funding_status",
    "selected_contact_title",
    "do_not_contact",
    "unsubscribe_status",
    "email_1_subject",
    "email_1_body",
    "email_1_llm_rewritten",
    "email_2_subject",
    "email_2_body",
    "email_2_llm_rewritten",
    "email_3_subject",
    "email_3_body",
    "email_4_subject",
    "email_4_body",
    "email_send_ready",
    "sequence_status",
    "send_status",
    "sender_email",
    "funding_claim_safe",
    "clinic_size_guess",
    "endpoint_band_guess",
    "pricing_email_2_mode",
    "pricing_claim_safe",
    "pricing_claim_line",
    "automation_decision",
    "automation_decision_reason",
    "contact_send_mode",
    "final_send_gate_passed",
    "email_2_mode",
    "email_1_send_status",
    "email_1_sent_at",
    "email_2_scheduled_at",
    "email_2_send_status",
    "reply_status",
    "instantly_sync_status",
    "instantly_last_event_type",
}

GRID_COLUMN_AFTER = {
    "email_1_llm_rewritten": "email_1_body",
    "email_2_llm_rewritten": "email_2_body",
}

SELECT_OPTIONS: dict[str, list[str]] = {
    "entity_type_guess": ["sme", "npo", "charity", "social_service", "healthcare_provider", "clinic", "private_company", "sole_proprietor", "partnership", "foreign_entity_sg_ops", "unknown"],
    "entity_type_confidence": ["low", "medium", "high"],
    "sme_likelihood": ["likely", "possible", "unlikely", "unknown"],
    "npo_likelihood": ["likely", "possible", "unlikely", "unknown"],
    "charity_or_social_service_likelihood": ["likely", "possible", "unlikely", "unknown"],
    "pressure_type": ["hia_regulatory", "pdpa_safeguards", "customer_trust", "funding", "not_ready"],
    "primary_email_track": ["hia_regulatory", "dpo_evidence", "customer_trust", "pdpa_safeguards", "funding", "not_ready"],
    "secondary_email_track": ["hia_regulatory", "dpo_evidence", "customer_trust", "pdpa_safeguards", "funding", "not_ready"],
    "classification_confidence": ["low", "medium", "high"],
    "outreach_trigger_confidence": ["low", "medium", "high"],
    "data_type_signal": ["patient_data", "health_information", "resident_data", "beneficiary_data", "customer_data", "employee_data", "student_data", "financial_data", "business_partner_data", "unknown"],
    "problem_area": ["access_control", "data_mapping", "offboarding", "backup", "patching", "malware_protection", "incident_response", "vendor_management", "staff_awareness", "evidence_collection", "hia_readiness", "pdpa_safeguards", "unknown"],
    "value_asset_offer": ["hia_readiness_map", "clinic_access_checklist", "solo_gp_checklist", "pdpa_safeguards_checklist", "data_access_map", "offboarding_checklist", "cyber_essentials_readiness_checklist", "funding_route_summary", "security_evidence_checklist"],
    "hia_confidence": ["low", "medium", "high"],
    "hia_service_type_guess": ["GP_OMS", "specialist_OMS", "dental", "retail_pharmacy", "diagnostic", "hospital", "allied_health", "hearing_care", "long_term_care", "outpatient_renal_dialysis", "ambulatory_surgical_centre", "HIMS_provider", "NEHR_user", "unknown"],
    "hia_official_service_type": [
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
    "hia_timeline_batch_guess": ["Batch 1 - Sep 2027", "Batch 2 - Sep 2028", "Batch 3 - Mar 2030", "Other CS/DS by Sep 2028", "unknown"],
    "personal_data_intensity": ["low", "medium", "high", "unknown"],
    "sensitive_data_likelihood": ["low", "medium", "high", "unknown"],
    "pdpa_safeguard_angle": ["access_control", "data_inventory", "vendor_management", "breach_response", "staff_training", "cyber_essentials_baseline", "unknown"],
    "recommended_first_cert": ["Cyber Essentials", "DPE", "DPTM", "Cyber Trust", "HIA readiness", "unknown"],
    "funding_status": ["verified_match", "possible_match", "not_applicable", "needs_review", "not_checked"],
    "funding_cta_asset": ["funding_route_summary", "funding_checklist", "hia_support_route_summary", "cyber_essentials_support_summary"],
    "funding_confidence": ["low", "medium", "high"],
    "business_model_guess": ["clinic", "healthcare_provider", "social_service", "npo", "b2b_services", "professional_services", "saas", "education", "finance", "retail", "unknown"],
    "data_flow_complexity": ["low", "medium", "high", "unknown"],
    "funding_specificity_level": ["low", "medium", "high", "unknown"],
    "clinic_size_guess": ["solo_gp", "small_single_clinic", "specialist_single_clinic", "group_clinic", "multi_location_provider", "dental_single_clinic", "pharmacy_single_site", "allied_health_single_site", "unknown"],
    "clinic_size_confidence": ["low", "medium", "high"],
    "endpoint_band_guess": ["1_5", "6_10", "11_20", "21_50", "unknown"],
    "endpoint_band_confidence": ["low", "medium", "high"],
    "pricing_email_2_mode": ["small_clinic_starting_price", "group_or_larger_sizing_needed", "endpoint_sizing_needed", "no_price_claim"],
    "decision_maker_role_guess": ["founder", "owner", "doctor", "clinic_manager", "operations", "dpo", "compliance", "it", "hr", "director", "executive_director", "unknown"],
    "unsubscribe_status": ["active", "unsubscribed", "bounced", "complained"],
    "outreach_variant": ["hia_healthcare", "hia_clinic", "solo_gp", "team_clinic", "dental_clinic", "allied_health", "npo_social_service", "pdpa_general", "dpo_evidence", "customer_trust", "funding_first", "not_ready"],
    "human_review_status": ["not_required", "not_ready", "ready_for_review", "approved", "rejected", "sent"],
    "automation_decision": ["auto_send_eligible", "auto_skipped", "retry_enrichment_once", "suppressed", "draft_only_review"],
    "contact_send_mode": ["named_person", "generic_team", "suppressed", "auto_skipped_unresolved_identity"],
    "contact_identity_confidence": ["none", "low", "medium", "high"],
    "email_2_mode": ["funding", "value_fallback"],
    "funding_followup_mode": ["funding", "value_fallback"],
    "email_3_mode": ["funding", "value_fallback"],
    "send_provider": ["instantly", "outlook_graph", "smtp", "smartlead"],
    "sequence_status": ["not_queued", "queued", "email_1_sent", "email_2_scheduled", "completed", "replied", "suppressed", "failed", "paused"],
    "send_status": ["not_ready", "queued", "sent", "failed_retryable", "failed_final", "suppressed", "paused"],
    "email_1_send_status": ["not_queued", "queued", "sent", "failed_retryable", "failed_final", "suppressed"],
    "email_2_send_status": ["not_queued", "scheduled", "queued", "sent", "cancelled", "failed_retryable", "failed_final", "suppressed"],
    "reply_status": ["none", "human_reply", "auto_reply", "bounce", "complaint", "unknown"],
    "reply_type": ["human", "out_of_office", "auto_reply", "bounce", "complaint", "unknown"],
    "instantly_sync_status": ["not_synced", "queued", "synced", "failed_retryable", "failed_final", "skipped"],
    "delivery_test_result": ["not_checked", "inbox", "spam", "missing", "bounced", "unknown"],
    "delivery_health_status": ["unknown", "healthy", "warning", "paused"],
}


def make_id(prefix: str, existing: set[str], length: int = 14) -> str:
    alphabet = string.ascii_lowercase + string.digits
    while True:
        candidate = prefix + "".join(random.choice(alphabet) for _ in range(length))
        if candidate not in existing:
            existing.add(candidate)
            return candidate


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--base-id", default="pb7f1zou786xyqc")
    parser.add_argument("--table-name", default="leads")
    parser.add_argument("--schema-name", default="pb7f1zou786xyqc")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and report planned changes without mutating Postgres or NocoDB metadata.")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")

    summary: dict[str, object] = {
        "dry_run": args.dry_run,
        "total_columns": len(OUTREACH_COLUMNS),
        "created_physical": 0,
        "existing_physical": 0,
        "created_metadata": 0,
        "existing_metadata": 0,
        "created_grid": 0,
        "existing_grid": 0,
        "planned_physical_columns": [],
        "planned_metadata_columns": [],
        "planned_grid_columns": [],
        "updated_grid_visibility": 0,
        "planned_grid_visibility_updates": [],
        "updated_grid_order": 0,
        "planned_grid_order_updates": [],
        "created_select_options": 0,
        "existing_select_options": 0,
        "planned_select_options": [],
    }

    with psycopg.connect(
        args.database_url,
        connect_timeout=15,
        options="-c statement_timeout=30000 -c lock_timeout=10000",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, source_id, base_id, fk_workspace_id
                from public.nc_models_v2
                where base_id = %s and table_name = %s
                """,
                (args.base_id, args.table_name),
            )
            model = cur.fetchone()
            if not model:
                raise SystemExit("model not found")
            model_id, source_id, base_id, workspace_id = model

            cur.execute(
                "select id from public.nc_views_v2 where fk_model_id = %s order by created_at asc limit 1",
                (model_id,),
            )
            view = cur.fetchone()
            if not view:
                raise SystemExit("view not found")
            (view_id,) = view

            cur.execute(
                """
                select column_name from information_schema.columns
                where table_schema = %s and table_name = %s
                """,
                (args.schema_name, args.table_name),
            )
            existing_physical = {row[0] for row in cur.fetchall()}

            cur.execute("select id from public.nc_columns_v2")
            existing_column_ids = {row[0] for row in cur.fetchall()}
            cur.execute(
                "select column_name, id from public.nc_columns_v2 where fk_model_id = %s",
                (model_id,),
            )
            existing_columns_by_name = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute("select id from public.nc_grid_view_columns_v2")
            existing_grid_ids = {row[0] for row in cur.fetchall()}
            cur.execute(
                "select fk_column_id, id, show from public.nc_grid_view_columns_v2 where fk_view_id = %s",
                (view_id,),
            )
            existing_grid_by_column_id = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
            cur.execute("select id from public.nc_col_select_options_v2")
            existing_select_option_ids = {row[0] for row in cur.fetchall()}
            cur.execute("select fk_column_id, title from public.nc_col_select_options_v2")
            existing_select_options = {(row[0], row[1]) for row in cur.fetchall()}

            cur.execute(
                'select coalesce(max("order"), 0) from public.nc_columns_v2 where fk_model_id = %s',
                (model_id,),
            )
            next_column_order = int(cur.fetchone()[0] or 0)
            cur.execute(
                'select coalesce(max("order"), 0) from public.nc_grid_view_columns_v2 where fk_view_id = %s',
                (view_id,),
            )
            next_grid_order = int(cur.fetchone()[0] or 0)

            schema_name = quote_identifier(args.schema_name)
            table_name = quote_identifier(args.table_name)

            for index, column in enumerate(OUTREACH_COLUMNS, start=1):
                if column.name not in existing_physical:
                    summary["created_physical"] = int(summary["created_physical"]) + 1
                    summary["planned_physical_columns"].append(column.name)  # type: ignore[union-attr]
                    if not args.dry_run:
                        column_name = quote_identifier(column.name)
                        cur.execute(f"alter table {schema_name}.{table_name} add column {column_name} {column.db_type}")
                else:
                    summary["existing_physical"] = int(summary["existing_physical"]) + 1

                column_id = existing_columns_by_name.get(column.name)
                if column_id:
                    summary["existing_metadata"] = int(summary["existing_metadata"]) + 1
                else:
                    summary["created_metadata"] = int(summary["created_metadata"]) + 1
                    summary["planned_metadata_columns"].append(column.name)  # type: ignore[union-attr]
                    if args.dry_run:
                        column_id = ""
                    else:
                        column_id = make_id("c", existing_column_ids)
                        cur.execute(
                            """
                            insert into public.nc_columns_v2 (
                                id, source_id, base_id, fk_model_id, title, column_name, uidt, dt,
                                pk, rqd, system, "order", fk_workspace_id
                            ) values (%s, %s, %s, %s, %s, %s, %s, %s, false, false, false, %s, %s)
                            """,
                            (
                                column_id,
                                source_id,
                                base_id,
                                model_id,
                                column.name,
                                column.name,
                                column.uidt,
                                column.db_type,
                                next_column_order + index,
                                workspace_id,
                            ),
                        )
                        existing_columns_by_name[column.name] = column_id

                grid_exists = False
                grid_id = ""
                grid_show = None
                if column_id:
                    grid_row = existing_grid_by_column_id.get(column_id)
                    if grid_row:
                        grid_id, grid_show = grid_row
                        grid_exists = True
                if grid_exists:
                    summary["existing_grid"] = int(summary["existing_grid"]) + 1
                else:
                    summary["created_grid"] = int(summary["created_grid"]) + 1
                    summary["planned_grid_columns"].append(column.name)  # type: ignore[union-attr]
                desired_show = column.name in DEFAULT_VISIBLE_GRID_COLUMNS
                if not grid_exists and not args.dry_run:
                    grid_id = make_id("nc", existing_grid_ids)
                    cur.execute(
                        """
                        insert into public.nc_grid_view_columns_v2 (
                            id, fk_view_id, fk_column_id, source_id, base_id, width, show, "order", fk_workspace_id
                        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            grid_id,
                            view_id,
                            column_id,
                            source_id,
                            base_id,
                            column.grid_width,
                            desired_show,
                            next_grid_order + index,
                            workspace_id,
                        ),
                    )
                    existing_grid_by_column_id[column_id] = (grid_id, desired_show)

                for option_index, option_title in enumerate(SELECT_OPTIONS.get(column.name, []), start=1):
                    if not column_id:
                        summary["created_select_options"] = int(summary["created_select_options"]) + 1
                        summary["planned_select_options"].append(f"{column.name}:{option_title}")  # type: ignore[union-attr]
                        continue
                    if (column_id, option_title) in existing_select_options:
                        summary["existing_select_options"] = int(summary["existing_select_options"]) + 1
                        continue
                    summary["created_select_options"] = int(summary["created_select_options"]) + 1
                    summary["planned_select_options"].append(f"{column.name}:{option_title}")  # type: ignore[union-attr]
                    if not args.dry_run:
                        option_id = make_id("sl", existing_select_option_ids)
                        cur.execute(
                            """
                            insert into public.nc_col_select_options_v2 (
                                id, fk_column_id, title, color, "order", base_id, fk_workspace_id
                            ) values (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                option_id,
                                column_id,
                                option_title,
                                "#cfd3d8",
                                option_index,
                                base_id,
                                workspace_id,
                            ),
                        )
                        existing_select_options.add((column_id, option_title))

            cur.execute(
                """
                select g.id, c.column_name, g."order"
                from public.nc_grid_view_columns_v2 g
                join public.nc_columns_v2 c on c.id = g.fk_column_id
                where g.fk_view_id = %s
                order by g."order", c.column_name
                """,
                (view_id,),
            )
            grid_rows = [{"id": row[0], "name": row[1], "order": float(row[2] or 0)} for row in cur.fetchall()]
            ordered_names = [str(row["name"]) for row in grid_rows]
            grid_row_by_name = {str(row["name"]): row for row in grid_rows}
            order_updates: dict[str, float] = {}
            for target, anchor in GRID_COLUMN_AFTER.items():
                if target not in ordered_names or anchor not in ordered_names:
                    continue
                current_index = ordered_names.index(target)
                anchor_index = ordered_names.index(anchor)
                target_row = grid_row_by_name[target]
                anchor_row = grid_row_by_name[anchor]
                target_order = float(target_row["order"])
                anchor_order = float(anchor_row["order"])
                if current_index == anchor_index + 1 and target_order > anchor_order:
                    continue
                order_updates[target] = anchor_order + 0.1
                summary["planned_grid_order_updates"].append(f"{target}:after:{anchor}")  # type: ignore[union-attr]

            for name, desired_order in order_updates.items():
                row = grid_row_by_name.get(name)
                if not row or float(row["order"]) == desired_order:
                    continue
                summary["updated_grid_order"] = int(summary["updated_grid_order"]) + 1
                if not args.dry_run:
                    cur.execute(
                        'update public.nc_grid_view_columns_v2 set "order" = %s where id = %s',
                        (desired_order, row["id"]),
                    )

            if not args.dry_run:
                cur.execute("update public.nc_models_v2 set updated_at = now() where id = %s", (model_id,))
                cur.execute("update public.nc_views_v2 set updated_at = now() where id = %s", (view_id,))
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
