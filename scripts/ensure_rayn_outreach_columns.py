#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    OutreachColumn("email_2_subject", "SingleLineText", "text"),
    OutreachColumn("email_2_body", "LongText", "text", "420px"),
    OutreachColumn("email_3_subject", "SingleLineText", "text"),
    OutreachColumn("email_3_body", "LongText", "text", "420px"),
    OutreachColumn("email_4_subject", "SingleLineText", "text"),
    OutreachColumn("email_4_body", "LongText", "text", "420px"),
    OutreachColumn("email_sequence_json", "LongText", "text", "420px"),
    OutreachColumn("email_quality_score", "Number", "numeric", "160px"),
    OutreachColumn("email_quality_flags", "LongText", "text", "360px"),
    OutreachColumn("email_send_ready", "Checkbox", "boolean", "140px"),
    OutreachColumn("human_review_status", "SingleSelect", "text"),
]


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
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")

    with psycopg.connect(args.database_url) as conn:
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
            cur.execute("select id from public.nc_grid_view_columns_v2")
            existing_grid_ids = {row[0] for row in cur.fetchall()}

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
                    column_name = quote_identifier(column.name)
                    cur.execute(f"alter table {schema_name}.{table_name} add column {column_name} {column.db_type}")

                cur.execute(
                    "select id from public.nc_columns_v2 where fk_model_id = %s and column_name = %s",
                    (model_id, column.name),
                )
                row = cur.fetchone()
                if row:
                    column_id = row[0]
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

                cur.execute(
                    "select id from public.nc_grid_view_columns_v2 where fk_view_id = %s and fk_column_id = %s",
                    (view_id, column_id),
                )
                if not cur.fetchone():
                    grid_id = make_id("nc", existing_grid_ids)
                    cur.execute(
                        """
                        insert into public.nc_grid_view_columns_v2 (
                            id, fk_view_id, fk_column_id, source_id, base_id, width, show, "order", fk_workspace_id
                        ) values (%s, %s, %s, %s, %s, %s, true, %s, %s)
                        """,
                        (
                            grid_id,
                            view_id,
                            column_id,
                            source_id,
                            base_id,
                            column.grid_width,
                            next_grid_order + index,
                            workspace_id,
                        ),
                    )

            cur.execute("update public.nc_models_v2 set updated_at = now() where id = %s", (model_id,))
            cur.execute("update public.nc_views_v2 set updated_at = now() where id = %s", (view_id,))
        conn.commit()


if __name__ == "__main__":
    main()
