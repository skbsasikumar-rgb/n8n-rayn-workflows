#!/usr/bin/env python3
"""Backfill clean auto-send rows so Instantly sync can pick them up."""

from __future__ import annotations

import argparse
import json
import os

import psycopg


ELIGIBLE_WHERE = """
automation_decision = 'auto_send_eligible'
and final_send_gate_passed is true
and coalesce(validated_email, '') <> ''
and coalesce(email_1_subject, '') <> ''
and coalesce(email_1_body, '') <> ''
and coalesce(do_not_contact, false) is false
and coalesce(send_provider, '') <> 'instantly'
and coalesce(instantly_sync_status, '') not in ('synced', 'skipped')
and coalesce(severe_email_flags, '') in ('', '[]')
and coalesce(email_quality_flags, '') in ('', '[]')
"""


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--schema-name", default="pb7f1zou786xyqc")
    parser.add_argument("--table-name", default="leads")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum rows to update.")
    parser.add_argument("--apply", action="store_true", help="Apply the backfill. Defaults to dry-run.")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")

    table_ref = f"{quote_identifier(args.schema_name)}.{quote_identifier(args.table_name)}"
    limit_clause = "limit %s" if args.limit else ""
    limit_params = (args.limit,) if args.limit else ()

    with psycopg.connect(
        args.database_url,
        connect_timeout=15,
        options="-c statement_timeout=30000 -c lock_timeout=10000",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select id
                from {table_ref}
                where {ELIGIBLE_WHERE}
                and (
                    coalesce(email_send_ready, false) is false
                    or coalesce(unsubscribe_status, '') <> 'active'
                    or coalesce(sequence_status, '') = ''
                    or coalesce(send_status, '') = ''
                    or coalesce(instantly_sync_status, '') = ''
                )
                order by id
                {limit_clause}
                """,
                limit_params,
            )
            ids = [row[0] for row in cur.fetchall()]

            updated_ids: list[int] = []
            if args.apply and ids:
                cur.execute(
                    f"""
                    update {table_ref}
                    set
                        email_send_ready = true,
                        unsubscribe_status = 'active',
                        sequence_status = coalesce(nullif(sequence_status, ''), 'not_queued'),
                        send_status = coalesce(nullif(send_status, ''), 'not_ready'),
                        instantly_sync_status = coalesce(nullif(instantly_sync_status, ''), 'not_synced')
                    where id = any(%s)
                    returning id
                    """,
                    (ids,),
                )
                updated_ids = [row[0] for row in cur.fetchall()]

    print(
        json.dumps(
            {
                "dry_run": not args.apply,
                "matched": len(ids),
                "updated": len(updated_ids),
                "ids_preview": ids[:25],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
