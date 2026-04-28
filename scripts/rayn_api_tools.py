#!/usr/bin/env python3
"""
Compact API helpers for RAYN operations.

Use this for repeated NocoDB/n8n/Railway checks where MCP would waste tokens by
returning full records or large JSON fields.

Environment:
  NOCO_BASE_URL          e.g. https://nocodb-production-f802.up.railway.app
  NOCO_API_TOKEN         NocoDB API token or PAT
  NOCO_PROJECT_ID        e.g. pb7f1zou786xyqc
  NOCO_TABLE_ID          e.g. mey3zgihq7o4at9
  N8N_BASE_URL           e.g. https://primary-production-a6441.up.railway.app
  N8N_API_KEY            n8n API key
  RAILWAY_API_TOKEN      Railway account/workspace token
  RAILWAY_PROJECT_TOKEN  Railway project token, if using project-token auth
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any


NOCO_DEFAULT_FIELDS = (
    "Id,company_name,status,status_reason,run_id,contact_search_status,contact_search_reason,"
    "url_picked,best_url,canonical_domain,duplicate_of_id,"
    "selected_contact_name,selected_contact_role,validated_email,email_validation_status,"
    "processing_started_at,processing_finished_at,last_attempted_at,attempt_count,error_type,error_message,"
    "retry_eligible,UpdatedAt"
)
NOCO_CONTACT_RESET_FIELDS = (
    "contact_search_status",
    "contact_search_reason",
    "contact_candidates_json",
    "contact_search_evidence_json",
    "selected_contact_name",
    "selected_contact_role",
    "selected_contact_seniority",
    "selected_contact_source_url",
    "selected_contact_confidence",
    "email_candidates_json",
    "validated_email",
    "email_validation_status",
    "email_validation_provider",
    "email_validation_evidence_json",
    "contact_search_started_at",
    "contact_search_finished_at",
)
LARGE_FIELDS = {
    "website_content",
    "website_scrape",
    "search_evidence_json",
    "contact_search_evidence_json",
    "contact_candidates_json",
    "email_candidates_json",
    "email_validation_evidence_json",
}
TERMINAL_CONTACT_STATUSES = {"contact_found", "contact_not_found", "failed", "skipped"}
DEFAULT_WORKFLOW_ID = "BQEa6M2pKYmuEYMV"


def env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def read_json_arg(value: str) -> Any:
    if value.startswith("@"):
        with open(value[1:], "r", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(value)


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any | None = None,
    timeout: int = 60,
) -> tuple[Any, dict[str, str]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return payload, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Request failed: {exc.reason}") from exc


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def compact_value(value: Any, max_chars: int = 240) -> Any:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    elif value is None:
        return ""
    else:
        text = str(value)
    if len(text) <= max_chars:
        return value
    return text[: max_chars - 20] + f"...[truncated:{len(text)}]"


def compact_row(row: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return {
        key: compact_value(value, max_chars if key in LARGE_FIELDS else min(max_chars, 500))
        for key, value in row.items()
    }


def noco_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "rayn-api-tools/1.0",
        "xc-token": env("NOCO_API_TOKEN"),
    }


def noco_base_url(bulk: bool = False) -> str:
    base = env("NOCO_BASE_URL").rstrip("/")
    project = env("NOCO_PROJECT_ID")
    table = env("NOCO_TABLE_ID")
    segment = "bulk/noco" if bulk else "noco"
    return f"{base}/api/v1/db/data/{segment}/{project}/{table}"


def noco_fetch(limit: int, fields: str, where: str | None, offset: int = 0, sort: str | None = None) -> list[dict[str, Any]]:
    params = {"limit": str(limit), "offset": str(offset), "fields": fields}
    if where:
        params["where"] = where
    if sort:
        params["sort"] = sort
    payload, _headers = request_json("GET", f"{noco_base_url()}?{urllib.parse.urlencode(params)}", noco_headers())
    if isinstance(payload, dict):
        return payload.get("list", [])
    return []


def noco_patch(rows: list[dict[str, Any]]) -> Any:
    payload, _headers = request_json("PATCH", noco_base_url(bulk=True), noco_headers(), rows)
    return payload


def where_ids(ids: str) -> str:
    parts = [part.strip() for part in ids.split(",") if part.strip()]
    if not parts:
        raise SystemExit("--ids did not contain any row IDs")
    return f"(Id,in,{','.join(parts)})"


def cmd_noco_rows(args: argparse.Namespace) -> None:
    where = where_ids(args.ids) if args.ids else args.where
    rows = noco_fetch(args.limit, args.fields, where, args.offset, args.sort)
    print_json({"count": len(rows), "rows": [compact_row(row, args.max_chars) for row in rows]})


def cmd_noco_contact_summary(args: argparse.Namespace) -> None:
    where = where_ids(args.ids) if args.ids else args.where
    rows = noco_fetch(args.limit, args.fields, where, args.offset, args.sort)
    statuses = Counter(str(row.get("contact_search_status") or "blank") for row in rows)
    reasons = Counter(str(row.get("contact_search_reason") or "blank") for row in rows)
    email_statuses = Counter(str(row.get("email_validation_status") or "blank") for row in rows)
    non_terminal = [
        row.get("Id")
        for row in rows
        if str(row.get("contact_search_status") or "").strip() not in TERMINAL_CONTACT_STATUSES
    ]
    rows_with_email = [row.get("Id") for row in rows if str(row.get("validated_email") or "").strip()]
    print_json(
        {
            "count": len(rows),
            "contact_search_status": dict(statuses),
            "contact_search_reason_top": reasons.most_common(args.top),
            "email_validation_status": dict(email_statuses),
            "rows_with_validated_email": rows_with_email,
            "non_terminal_row_ids": non_terminal,
            "rows": [compact_row(row, args.max_chars) for row in rows] if args.include_rows else [],
        }
    )


def cmd_noco_reset_contact(args: argparse.Namespace) -> None:
    if not args.ids and not args.where:
        raise SystemExit("Pass --ids or --where so contact reset cannot accidentally touch the whole table")
    where = where_ids(args.ids) if args.ids else args.where
    rows = noco_fetch(args.limit, "Id,company_name,contact_search_status", where)
    now = datetime.now(timezone.utc).isoformat()
    payload = []
    for row in rows:
        cleared = {field: "" for field in NOCO_CONTACT_RESET_FIELDS}
        payload.append(
            {
                "Id": row["Id"],
                **cleared,
                "contact_search_status": "pending",
                "contact_search_reason": f"reset_for_rerun:{args.reason}",
                "last_attempted_at": now,
            }
        )
    result = noco_patch(payload) if not args.dry_run else {"dry_run": True}
    print_json({"matched": len(rows), "updated": len(payload) if not args.dry_run else 0, "result": result})


def n8n_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "rayn-api-tools/1.0",
        "X-N8N-API-KEY": env("N8N_API_KEY"),
    }


def n8n_url(path: str, params: dict[str, str] | None = None) -> str:
    base = env("N8N_BASE_URL").rstrip("/")
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return f"{base}{path}{query}"


def normalize_n8n_executions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        executions = data.get("executions")
        if isinstance(executions, list):
            return executions
    return []


def cmd_n8n_executions(args: argparse.Namespace) -> None:
    params = {"workflowId": args.workflow_id, "limit": str(args.limit)}
    if args.status:
        params["status"] = args.status
    payload, _headers = request_json("GET", n8n_url("/api/v1/executions", params), n8n_headers())
    executions = normalize_n8n_executions(payload)
    compact = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "workflowId": item.get("workflowId"),
            "startedAt": item.get("startedAt"),
            "stoppedAt": item.get("stoppedAt"),
            "finished": item.get("finished"),
            "mode": item.get("mode"),
        }
        for item in executions
    ]
    print_json({"count": len(compact), "executions": compact})


def railway_headers() -> dict[str, str]:
    project_token = env("RAILWAY_PROJECT_TOKEN", required=False)
    if project_token:
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "rayn-api-tools/1.0",
            "Project-Access-Token": project_token,
        }
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "rayn-api-tools/1.0",
        "Authorization": f"Bearer {env('RAILWAY_API_TOKEN')}",
    }


def cmd_railway_graphql(args: argparse.Namespace) -> None:
    body = read_json_arg(args.body) if args.body else {"query": args.query, "variables": read_json_arg(args.variables) if args.variables else {}}
    endpoint = env("RAILWAY_GRAPHQL_URL", required=False, default="https://backboard.railway.com/graphql/v2")
    payload, headers = request_json("POST", endpoint, railway_headers(), body, timeout=args.timeout)
    output = {"payload": payload}
    if args.rate_headers:
        output["rate_limit"] = {
            key: headers.get(key, "")
            for key in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After")
        }
    print_json(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Token-efficient RAYN API helpers.")
    sub = parser.add_subparsers(dest="command", required=True)

    noco_rows = sub.add_parser("noco-rows", help="Fetch compact NocoDB rows")
    noco_rows.add_argument("--ids", help="Comma-separated NocoDB Id values")
    noco_rows.add_argument("--where", help="Raw NocoDB where clause")
    noco_rows.add_argument("--fields", default=NOCO_DEFAULT_FIELDS)
    noco_rows.add_argument("--limit", type=int, default=25)
    noco_rows.add_argument("--offset", type=int, default=0)
    noco_rows.add_argument("--sort")
    noco_rows.add_argument("--max-chars", type=int, default=240)
    noco_rows.set_defaults(func=cmd_noco_rows)

    noco_summary = sub.add_parser("noco-contact-summary", help="Summarize contact-search rows without dumping evidence JSON")
    noco_summary.add_argument("--ids", help="Comma-separated NocoDB Id values")
    noco_summary.add_argument("--where", help="Raw NocoDB where clause")
    noco_summary.add_argument("--fields", default=NOCO_DEFAULT_FIELDS)
    noco_summary.add_argument("--limit", type=int, default=100)
    noco_summary.add_argument("--offset", type=int, default=0)
    noco_summary.add_argument("--sort")
    noco_summary.add_argument("--top", type=int, default=8)
    noco_summary.add_argument("--include-rows", action="store_true")
    noco_summary.add_argument("--max-chars", type=int, default=180)
    noco_summary.set_defaults(func=cmd_noco_contact_summary)

    noco_reset = sub.add_parser("noco-reset-contact", help="Reset only contact-search fields to pending")
    noco_reset.add_argument("--ids", help="Comma-separated NocoDB Id values")
    noco_reset.add_argument("--where", help="Raw NocoDB where clause")
    noco_reset.add_argument("--limit", type=int, default=100)
    noco_reset.add_argument("--reason", default="operator_requested")
    noco_reset.add_argument("--dry-run", action="store_true")
    noco_reset.set_defaults(func=cmd_noco_reset_contact)

    n8n_execs = sub.add_parser("n8n-executions", help="List compact n8n execution status")
    n8n_execs.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    n8n_execs.add_argument("--status", choices=["success", "error", "waiting"])
    n8n_execs.add_argument("--limit", type=int, default=20)
    n8n_execs.set_defaults(func=cmd_n8n_executions)

    railway = sub.add_parser("railway-graphql", help="Run a Railway GraphQL query")
    railway.add_argument("--query", help="GraphQL query string")
    railway.add_argument("--variables", help="JSON variables string or @file")
    railway.add_argument("--body", help="Full JSON request body string or @file")
    railway.add_argument("--timeout", type=int, default=60)
    railway.add_argument("--rate-headers", action="store_true")
    railway.set_defaults(func=cmd_railway_graphql)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "command", "") == "railway-graphql" and not args.body and not args.query:
        raise SystemExit("railway-graphql requires --query or --body")
    args.func(args)


if __name__ == "__main__":
    main()
