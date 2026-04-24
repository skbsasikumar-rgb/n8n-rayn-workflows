#!/usr/bin/env python3
"""
Small helper for listing and deleting n8n executions for the RAYN worker.

Environment:
  N8N_BASE_URL   e.g. https://primary-production-a6441.up.railway.app
  N8N_API_KEY    n8n API key
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_WORKFLOW_ID = "bAyrbtzx6m3FRe44"


def env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def base_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "X-N8N-API-KEY": env("N8N_API_KEY"),
    }


def api_url(path: str, params: dict[str, str] | None = None) -> str:
    base = env("N8N_BASE_URL").rstrip("/")
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return f"{base}{path}{query}"


def request_json(method: str, path: str, params: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(api_url(path, params), method=method, headers=base_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {exc.reason}: {detail}") from exc


def cmd_list(args: argparse.Namespace) -> None:
    params = {
        "workflowId": args.workflow_id,
        "limit": str(args.limit),
    }
    if args.status:
        params["status"] = args.status
    payload = request_json("GET", "/api/v1/executions", params)
    data = payload.get("data", payload)
    print(json.dumps(data, ensure_ascii=True))


def cmd_delete(args: argparse.Namespace) -> None:
    deleted = []
    for execution_id in [part.strip() for part in args.ids.split(",") if part.strip()]:
        request_json("DELETE", f"/api/v1/executions/{execution_id}")
        deleted.append(execution_id)
    print(json.dumps({"deleted": deleted}, ensure_ascii=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List and delete n8n executions.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List workflow executions")
    list_cmd.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    list_cmd.add_argument("--status", choices=["success", "error", "waiting"])
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.set_defaults(func=cmd_list)

    delete_cmd = sub.add_parser("delete", help="Delete executions by ID")
    delete_cmd.add_argument("--ids", required=True, help="Comma-separated execution IDs")
    delete_cmd.set_defaults(func=cmd_delete)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
