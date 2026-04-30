#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import random
import string

import psycopg

CONTACT_COLUMNS: list[tuple[str, str, str]] = [
    ("contact_search_status", "SingleLineText", "text"),
    ("contact_search_reason", "SingleLineText", "text"),
    ("contact_candidates_json", "LongText", "text"),
    ("contact_search_evidence_json", "LongText", "text"),
    ("selected_contact_name", "SingleLineText", "text"),
    ("selected_contact_role", "SingleLineText", "text"),
    ("selected_contact_seniority", "SingleLineText", "text"),
    ("selected_contact_source_url", "SingleLineText", "text"),
    ("selected_contact_confidence", "SingleLineText", "text"),
    ("email_candidates_json", "LongText", "text"),
    ("validated_email", "SingleLineText", "text"),
    ("email_validation_status", "SingleLineText", "text"),
    ("email_validation_summary", "LongText", "text"),
    ("email_validation_provider", "SingleLineText", "text"),
    ("email_validation_evidence_json", "LongText", "text"),
    ("contact_search_started_at", "SingleLineText", "text"),
    ("contact_search_finished_at", "SingleLineText", "text"),
    ("contact_search_run_id", "SingleLineText", "text"),
]


def make_id(prefix: str, existing: set[str], length: int = 14) -> str:
    alphabet = string.ascii_lowercase + string.digits
    while True:
        candidate = prefix + "".join(random.choice(alphabet) for _ in range(length))
        if candidate not in existing:
            existing.add(candidate)
            return candidate


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
                "select coalesce(max(\"order\"), 0) from public.nc_columns_v2 where fk_model_id = %s",
                (model_id,),
            )
            next_column_order = int(cur.fetchone()[0] or 0)
            cur.execute(
                "select coalesce(max(\"order\"), 0) from public.nc_grid_view_columns_v2 where fk_view_id = %s",
                (view_id,),
            )
            next_grid_order = int(cur.fetchone()[0] or 0)

            for index, (name, uidt, db_type) in enumerate(CONTACT_COLUMNS, start=1):
                if name not in existing_physical:
                    cur.execute(
                        f'alter table "{args.schema_name}"."{args.table_name}" add column "{name}" text'
                    )

                cur.execute(
                    "select id from public.nc_columns_v2 where fk_model_id = %s and column_name = %s",
                    (model_id, name),
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
                            name,
                            name,
                            uidt,
                            db_type,
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
                        ) values (%s, %s, %s, %s, %s, '220px', true, %s, %s)
                        """,
                        (
                            grid_id,
                            view_id,
                            column_id,
                            source_id,
                            base_id,
                            next_grid_order + index,
                            workspace_id,
                        ),
                    )

            cur.execute("update public.nc_models_v2 set updated_at = now() where id = %s", (model_id,))
            cur.execute("update public.nc_views_v2 set updated_at = now() where id = %s", (view_id,))
        conn.commit()


if __name__ == "__main__":
    main()
