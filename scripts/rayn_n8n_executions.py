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


def normalize_execution_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"executions": payload, "returned": len(payload), "nextCursor": None, "hasMore": False}
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"executions": data, "returned": len(data), "nextCursor": None, "hasMore": False}
        return payload
    return {"executions": [], "returned": 0, "nextCursor": None, "hasMore": False}


def cmd_list(args: argparse.Namespace) -> None:
    data = list_executions(args.workflow_id, args.limit, args.status, args.all)
    print(json.dumps(data, ensure_ascii=True))


def cmd_delete(args: argparse.Namespace) -> None:
    deleted = []
    for execution_id in [part.strip() for part in args.ids.split(",") if part.strip()]:
        request_json("DELETE", f"/api/v1/executions/{execution_id}")
        deleted.append(execution_id)
    print(json.dumps({"deleted": deleted}, ensure_ascii=True))


def list_executions(workflow_id: str, limit: int, status: str | None, all_pages: bool) -> dict[str, Any]:
    params = {
        "workflowId": workflow_id,
        "limit": str(limit),
    }
    if status:
        params["status"] = status

    if not all_pages:
        payload = request_json("GET", "/api/v1/executions", params)
        return normalize_execution_payload(payload)

    executions = []
    cursor = None
    while True:
        current_params = dict(params)
        if cursor:
            current_params["cursor"] = cursor
        payload = request_json("GET", "/api/v1/executions", current_params)
        data = normalize_execution_payload(payload)
        executions.extend(data.get("executions", []))
        cursor = data.get("nextCursor")
        if not cursor:
            return {"executions": executions, "returned": len(executions), "nextCursor": None, "hasMore": False}


def cmd_purge(args: argparse.Namespace) -> None:
    payload = list_executions(args.workflow_id, args.limit, args.status, True)
    execution_ids = [str(item.get("id", "")).strip() for item in payload.get("executions", []) if str(item.get("id", "")).strip()]
    deleted = []
    for execution_id in execution_ids:
        request_json("DELETE", f"/api/v1/executions/{execution_id}")
        deleted.append(execution_id)
    print(json.dumps({"deleted": deleted, "workflow_id": args.workflow_id, "count": len(deleted)}, ensure_ascii=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List and delete n8n executions.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List workflow executions")
    list_cmd.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    list_cmd.add_argument("--status", choices=["success", "error", "waiting"])
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument("--all", action="store_true", help="Fetch all execution pages")
    list_cmd.set_defaults(func=cmd_list)

    delete_cmd = sub.add_parser("delete", help="Delete executions by ID")
    delete_cmd.add_argument("--ids", required=True, help="Comma-separated execution IDs")
    delete_cmd.set_defaults(func=cmd_delete)

    purge_cmd = sub.add_parser("purge", help="Delete all executions for a workflow")
    purge_cmd.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    purge_cmd.add_argument("--status", choices=["success", "error", "waiting"])
    purge_cmd.add_argument("--limit", type=int, default=100)
    purge_cmd.set_defaults(func=cmd_purge)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
