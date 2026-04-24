#!/usr/bin/env python3
"""
Small helper for inspecting and resetting RAYN worker rows via the NocoDB API.

Environment:
  NOCO_BASE_URL      e.g. https://nocodb-production-f802.up.railway.app
  NOCO_API_TOKEN     NocoDB API token
  NOCO_PROJECT_ID    e.g. pb7f1zou786xyqc
  NOCO_TABLE_ID      e.g. mey3zgihq7o4at9
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_FIELDS = (
    "Id,company_name,hia_batch,status,best_url,homepage_root_url,evidence_url,scrape_url,canonical_domain,"
    "website_scrape,operating_company_root_name,company_homepage_name,parent_company,confidence,notes,"
    "source_urls,fallback_used,evidence_gap,last_stage,last_error,candidate_homepage,candidate_domain,"
    "discovery_category,discovery_area,discovered_at,UpdatedAt"
)

RESET_PRESERVE_FIELDS = (
    "company_name",
    "hia_batch",
    "candidate_homepage",
    "candidate_domain",
    "discovery_category",
    "discovery_area",
)

RESET_CLEAR_FIELDS = (
    "status",
    "best_url",
    "canonical_domain",
    "website_content",
    "homepage_root_url",
    "evidence_url",
    "scrape_url",
    "website_scrape",
    "operating_company_root_name",
    "company_homepage_name",
    "parent_company",
    "confidence",
    "notes",
    "source_urls",
    "fallback_used",
    "search_evidence_json",
    "evidence_gap",
    "last_stage",
    "last_error",
    "discovered_at",
)

RESET_READ_FIELDS = "Id," + ",".join(RESET_PRESERVE_FIELDS + ("discovered_at",))


def env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def base_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "xc-token": env("NOCO_API_TOKEN"),
    }


def table_base_url() -> str:
    base = env("NOCO_BASE_URL").rstrip("/")
    project = env("NOCO_PROJECT_ID")
    table = env("NOCO_TABLE_ID")
    return f"{base}/api/v1/db/data/noco/{project}/{table}"


def request_json(method: str, url: str, body: Any | None = None) -> Any:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=base_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {exc.reason}: {detail}") from exc


def fetch_rows(limit: int, where: str | None, fields: str) -> list[dict[str, Any]]:
    params = {"limit": str(limit), "fields": fields}
    if where:
        params["where"] = where
    url = f"{table_base_url()}?{urllib.parse.urlencode(params)}"
    payload = request_json("GET", url)
    return payload.get("list", [])


def patch_rows(rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return {"updated": 0}
    url = table_base_url().replace("/data/noco/", "/data/bulk/noco/")
    return request_json("PATCH", url, rows)


def print_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(json.dumps(row, ensure_ascii=True))


def cmd_show(args: argparse.Namespace) -> None:
    where = args.where
    if args.ids:
        ids = [part.strip() for part in args.ids.split(",") if part.strip()]
        where = f"(Id,in,{','.join(ids)})"
    rows = fetch_rows(limit=args.limit, where=where, fields=args.fields)
    print_rows(rows)


def cmd_reset(args: argparse.Namespace) -> None:
    where = args.where
    if args.ids:
        ids = [part.strip() for part in args.ids.split(",") if part.strip()]
        where = f"(Id,in,{','.join(ids)})"
        limit = max(args.limit, len(ids))
    else:
        limit = args.limit
    rows = fetch_rows(limit=limit, where=where, fields=RESET_READ_FIELDS)
    if args.ids:
        rows = [row for row in rows if row.get("Id")]

    payload = []
    for row in rows:
        preserved = {field: row.get(field, "") for field in RESET_PRESERVE_FIELDS}
        cleared = {field: "" for field in RESET_CLEAR_FIELDS}
        payload.append(
            {
                "Id": row["Id"],
                **preserved,
                **cleared,
                "status": "pending",
            }
        )

    result = patch_rows(payload)
    print(json.dumps({"requested": len(payload), "result": result}, ensure_ascii=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and reset RAYN NocoDB rows.")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show rows")
    show.add_argument("--ids", help="Comma-separated row IDs")
    show.add_argument("--where", help="Raw NocoDB where clause")
    show.add_argument("--limit", type=int, default=20)
    show.add_argument("--fields", default=DEFAULT_FIELDS)
    show.set_defaults(func=cmd_show)

    reset = sub.add_parser("reset", help="Reset rows back to clean pending state")
    reset.add_argument("--ids", help="Comma-separated row IDs")
    reset.add_argument("--where", help="Raw NocoDB where clause")
    reset.add_argument("--limit", type=int, default=20)
    reset.set_defaults(func=cmd_reset)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
