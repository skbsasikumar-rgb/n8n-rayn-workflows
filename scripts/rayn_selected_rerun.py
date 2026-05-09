#!/usr/bin/env python3
"""Safely rerun selected RAYN lead rows through URL, contact, and planner stages."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ensure_rayn_outreach_columns as outreach_columns
from scripts import rayn_api_tools as api


URL_FIELDS = (
    "Id,company_name,status,status_reason,last_stage,last_error,url_picked,best_url,"
    "canonical_domain,duplicate_of_id,contact_search_status,automation_decision,"
    "attempt_count,processing_started_at,processing_finished_at,last_attempted_at"
)
PLANNER_FIELDS = (
    "Id,company_name,status,best_url,contact_search_status,validated_email,"
    "automation_decision,automation_decision_reason,final_send_gate_passed,email_send_ready,"
    "email_1_body,email_2_body,email_3_body,email_2_mode,email_3_mode"
)
TERMINAL_CONTACT_STATUSES = {"contact_found", "contact_not_found", "failed", "skipped"}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def parse_ids(value: str) -> list[int]:
    ids = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not ids:
        raise SystemExit("--ids is required")
    return ids


def where_ids(ids: list[int]) -> str:
    return "(Id,in," + ",".join(str(row_id) for row_id in ids) + ")"


def fetch_rows(ids: list[int], fields: str = URL_FIELDS) -> list[dict[str, Any]]:
    rows = api.noco_fetch(max(100, len(ids)), fields, where_ids(ids), 0, "Id")
    found = {int(row["Id"]) for row in rows}
    missing = sorted(set(ids) - found)
    if missing:
        raise SystemExit(f"Missing NocoDB rows: {missing}")
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "status": dict(Counter(str(row.get("status") or "") for row in rows)),
        "contact_search_status": dict(Counter(str(row.get("contact_search_status") or "") for row in rows)),
        "automation_decision": dict(Counter(str(row.get("automation_decision") or "") for row in rows)),
        "ids_by_status": {
            status: [row.get("Id") for row in rows if str(row.get("status") or "") == status]
            for status in sorted({str(row.get("status") or "") for row in rows})
        },
    }


def reset_patch_for_row(row_id: int, reason: str) -> dict[str, Any]:
    cleared: dict[str, Any] = {}
    for column in outreach_columns.OUTREACH_COLUMNS:
        if column.name in {"do_not_contact", "unsubscribe_status"}:
            continue
        if column.uidt == "Checkbox":
            cleared[column.name] = False
        elif column.uidt == "Number":
            cleared[column.name] = None
        else:
            cleared[column.name] = ""
    cleared.update(
        {
            "Id": row_id,
            "url_picked": "",
            "best_url": "",
            "canonical_domain": "",
            "duplicate_of_id": "",
            "search_evidence_json": "",
            "status": "pending",
            "status_reason": f"pending_selected_rerun:{reason}",
            "last_stage": "",
            "last_error": "",
            "notes": "",
            "run_id": "",
            "processing_started_at": "",
            "processing_finished_at": "",
            "last_attempted_at": "",
            "attempt_count": "0",
            "error_type": "",
            "error_message": "",
            "retry_eligible": "",
            "contact_search_status": "pending",
            "contact_search_reason": f"reset:selected_rerun:{reason}",
            "contact_search_started_at": "",
            "contact_search_finished_at": "",
            "contact_search_run_id": "",
            "contact_candidates_json": "",
            "contact_search_evidence_json": "",
            "selected_contact_seniority": "",
            "selected_contact_source_url": "",
            "selected_contact_confidence": "",
            "email_candidates_json": "",
            "email_validation_status": "",
            "email_validation_summary": "",
            "email_validation_provider": "",
            "email_validation_evidence_json": "",
            "website_scrape": "",
            "source_row_created_at": "",
            "source_row_updated_at": "",
            "human_review_status": "",
        }
    )
    return cleared


def reset_rows(ids: list[int], reason: str, dry_run: bool) -> None:
    payload = [reset_patch_for_row(row_id, reason) for row_id in ids]
    if dry_run:
        print(json.dumps({"dry_run": True, "reset_rows": ids}, ensure_ascii=True))
        return
    for start in range(0, len(payload), 25):
        api.noco_patch(payload[start : start + 25])


def request_json(method: str, url: str, body: Any, timeout: int) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"accept": "application/json", "content-type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw[:500]}
        return exc.code, payload
    except Exception as exc:
        return 0, {"error": str(exc)}


def n8n_webhook(path: str) -> str:
    return os.environ["N8N_BASE_URL"].rstrip("/") + f"/webhook/{path}"


def worker_url(path: str) -> str:
    base = os.getenv("CRAWL4AI_SCRAPER_URL", "https://n8n-rayn-workflows-production.up.railway.app/scrape")
    if base.endswith("/scrape"):
        return base[: -len("/scrape")] + path
    return base.rstrip("/") + path


def trigger_url_pick(row: dict[str, Any]) -> dict[str, Any]:
    code, payload = request_json(
        "POST",
        n8n_webhook("rayn-url-picker-v1"),
        {"Id": row["Id"], "company_name": row["company_name"], "stage_mode": "url_only"},
        60,
    )
    return {"Id": row["Id"], "code": code, "payload": payload}


def wait_url_pick(ids: list[int], timeout_seconds: int) -> list[dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    while True:
        rows = fetch_rows(ids)
        unresolved = [
            row
            for row in rows
            if str(row.get("status") or "") == "pending"
            or (str(row.get("status") or "") == "processing" and not str(row.get("url_picked") or "").strip())
        ]
        if not unresolved or time.time() >= deadline:
            return rows
        time.sleep(5)


def terminal_status(patch: dict[str, Any]) -> str:
    stage = str(patch.get("last_stage") or patch.get("crawl_status") or "").strip()
    depth = enrichment_depth_status(patch)
    if depth == "weak_retry_needed":
        return "url_picked"
    if stage == "crawled":
        return "completed"
    if stage == "partial":
        return "completed" if str(patch.get("best_url") or "").strip() else "needs_review"
    if stage in {"crawl_failed", "enrichment_error"}:
        return "failed"
    if stage == "blocked_by_robots" or stage.startswith("skipped_"):
        return "skipped"
    if not str(patch.get("best_url") or "").strip():
        return "needs_review"
    return "completed"


def status_reason(status: str, patch: dict[str, Any]) -> str:
    stage = str(patch.get("last_stage") or patch.get("crawl_status") or "").strip()
    depth = enrichment_depth_status(patch)
    if depth == "weak_retry_needed":
        return weak_enrichment_reason(patch) or "weak_retry_needed"
    if status == "completed":
        return "enrichment_completed_with_subpage_warnings" if stage == "partial" else "enrichment_completed"
    if status == "needs_review":
        return "partial_crawl" if stage == "partial" else "ambiguous_enrichment"
    if status == "skipped":
        return stage or "skipped"
    return stage or "failed"


def enrichment_depth(patch: dict[str, Any]) -> dict[str, Any]:
    raw = patch.get("structured_data_detected")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        parsed = {}
    if isinstance(parsed, dict) and isinstance(parsed.get("enrichment_depth"), dict):
        return parsed["enrichment_depth"]
    return {}


def enrichment_depth_status(patch: dict[str, Any]) -> str:
    return str(patch.get("enrichment_depth_status") or enrichment_depth(patch).get("enrichment_depth_status") or "").strip()


def weak_enrichment_reason(patch: dict[str, Any]) -> str:
    return str(patch.get("weak_enrichment_reason") or enrichment_depth(patch).get("weak_enrichment_reason") or "").strip()


def public_enrich_patch(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    attempt_count = str((int(str(row.get("attempt_count") or "0") or "0") + 1))
    run_id = f"selected-rerun:{int(time.time())}:{row['Id']}"
    api.noco_patch(
        [
            {
                "Id": row["Id"],
                "status": "processing",
                "last_stage": "crawl",
                "last_error": "",
                "run_id": run_id,
                "processing_started_at": started_at,
                "processing_finished_at": "",
                "last_attempted_at": started_at,
                "attempt_count": attempt_count,
                "status_reason": "processing:crawl",
                "error_type": "",
                "error_message": "",
                "retry_eligible": "true",
            }
        ]
    )
    code, payload = request_json(
        "POST",
        worker_url("/public-enrich"),
        {
            "Id": row["Id"],
            "company_name": row["company_name"],
            "url_picked": row["url_picked"],
            "page_limit": args.page_limit,
            "page_timeout_ms": args.page_timeout_ms,
            "request_delay_seconds": args.request_delay_seconds,
            "scrape_char_limit": args.scrape_char_limit,
            "per_row_page_concurrency": args.per_row_page_concurrency,
            "row_timeout_seconds": args.row_timeout_seconds,
            "allow_low_limits": args.allow_low_limits,
        },
        args.public_enrich_timeout,
    )
    finished_at = datetime.now(timezone.utc).isoformat()
    if code == 200 and isinstance(payload, dict) and isinstance(payload.get("patch"), dict):
        patch = dict(payload["patch"])
        final_status = terminal_status(patch)
        last_error = str(patch.get("last_error") or "")
        patch.update(
            {
                "status": final_status,
                "run_id": run_id,
                "processing_started_at": started_at,
                "processing_finished_at": finished_at,
                "last_attempted_at": started_at,
                "attempt_count": attempt_count,
                "status_reason": status_reason(final_status, patch),
                "error_type": (str(patch.get("last_stage") or patch.get("crawl_status") or "").strip() or "enrichment_error")
                if final_status == "failed"
                else "",
                "error_message": last_error if final_status == "failed" else "",
                "retry_eligible": "true" if final_status == "failed" else "false",
            }
        )
        api.noco_patch([patch])
        return {"Id": row["Id"], "status": final_status, "reason": patch["status_reason"]}
    error_text = str((payload or {}).get("error") or (payload or {}).get("message") or f"public_enrich_http_{code}")[:500]
    api.noco_patch(
        [
            {
                "Id": row["Id"],
                "status": "failed",
                "last_stage": "enrichment_error",
                "last_error": error_text,
                "notes": error_text,
                "run_id": run_id,
                "processing_started_at": started_at,
                "processing_finished_at": finished_at,
                "last_attempted_at": started_at,
                "attempt_count": attempt_count,
                "status_reason": "enrichment_error",
                "error_type": "enrichment_error",
                "error_message": error_text,
                "retry_eligible": "true",
            }
        ]
    )
    return {"Id": row["Id"], "status": "failed", "reason": "enrichment_error", "error": error_text}


def run_public_enrich(ids: list[int], args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = [
        row
        for row in fetch_rows(ids)
        if str(row.get("url_picked") or "").strip()
        and str(row.get("status") or "") in {"processing", "url_picked"}
        and not str(row.get("duplicate_of_id") or "").strip()
    ]
    if not rows:
        return []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.enrich_concurrency)) as pool:
        for result in pool.map(lambda item: public_enrich_patch(item, args), rows):
            results.append(result)
    return results


def run_contact(ids: list[int], args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_rows(ids)
    contact_ids = [
        row["Id"]
        for row in rows
        if str(row.get("status") or "") == "completed"
        and str(row.get("best_url") or "").strip()
        and str(row.get("contact_search_status") or "") == "pending"
    ]
    if not contact_ids:
        return {"rows_selected": 0, "results": []}
    code, payload = request_json(
        "POST",
        worker_url("/contact-enrich-batch"),
        {
            "ids": contact_ids,
            "limit": min(10, max(1, len(contact_ids))),
            "concurrency": args.contact_concurrency,
            "validate_email": True,
            "reset_provider_health": args.reset_provider_health,
            "dry_run": False,
        },
        args.contact_timeout,
    )
    if code != 200:
        raise SystemExit(f"contact-enrich-batch failed: HTTP {code} {payload}")
    return payload


def run_planner(ids: list[int], args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_rows(ids, PLANNER_FIELDS)
    blocked = [
        row["Id"]
        for row in rows
        if str(row.get("status") or "") != "completed" or not str(row.get("best_url") or "").strip()
    ]
    planner_ids = [
        row["Id"]
        for row in rows
        if row["Id"] not in blocked
        and str(row.get("contact_search_status") or "") in TERMINAL_CONTACT_STATUSES
        and not str(row.get("automation_decision") or "").strip()
    ]
    if not planner_ids:
        return {"rows_selected": 0, "blocked_upstream_ids": blocked}
    code, payload = request_json(
        "POST",
        n8n_webhook("rayn-cold-email-planner"),
        {"row_ids": planner_ids, "limit": len(planner_ids), "use_llm": False},
        args.planner_timeout,
    )
    if code != 200:
        raise SystemExit(f"cold-email planner webhook failed: HTTP {code} {payload}")
    deadline = time.time() + args.planner_wait_seconds
    while time.time() < deadline:
        pending = [
            row["Id"]
            for row in fetch_rows(planner_ids, PLANNER_FIELDS)
            if not str(row.get("automation_decision") or "").strip()
        ]
        if not pending:
            break
        time.sleep(5)
    return {"rows_selected": len(planner_ids), "planner_ids": planner_ids, "blocked_upstream_ids": blocked, "response": payload}


def main() -> None:
    load_env_file(ROOT / ".env.local")
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", required=True, help="Comma-separated NocoDB row IDs")
    parser.add_argument("--reason", default="operator_requested")
    parser.add_argument("--skip-reset", action="store_true")
    parser.add_argument("--skip-url", action="store_true")
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--skip-contact", action="store_true")
    parser.add_argument("--skip-planner", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--url-wait-seconds", type=int, default=240)
    parser.add_argument("--enrich-concurrency", type=int, default=1)
    parser.add_argument("--page-limit", type=int, default=8)
    parser.add_argument("--page-timeout-ms", type=int, default=15000)
    parser.add_argument("--request-delay-seconds", type=float, default=0.15)
    parser.add_argument("--scrape-char-limit", type=int, default=120000)
    parser.add_argument("--per-row-page-concurrency", type=int, default=1)
    parser.add_argument("--row-timeout-seconds", type=int, default=180)
    parser.add_argument("--allow-low-limits", action="store_true")
    parser.add_argument("--public-enrich-timeout", type=int, default=420)
    parser.add_argument("--contact-concurrency", type=int, default=2)
    parser.add_argument("--contact-timeout", type=int, default=1800)
    parser.add_argument("--reset-provider-health", action="store_true")
    parser.add_argument("--planner-timeout", type=int, default=300)
    parser.add_argument("--planner-wait-seconds", type=int, default=120)
    args = parser.parse_args()

    ids = parse_ids(args.ids)
    outputs: dict[str, Any] = {"before": summarize(fetch_rows(ids))}

    if not args.skip_reset:
        reset_rows(ids, args.reason, args.dry_run)
        outputs["reset"] = {"rows": ids, "dry_run": args.dry_run}
    if args.dry_run:
        print(json.dumps(outputs, ensure_ascii=True, indent=2))
        return

    if not args.skip_url:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(ids))) as pool:
            outputs["url_trigger"] = list(pool.map(trigger_url_pick, fetch_rows(ids)))
        outputs["after_url_pick"] = summarize(wait_url_pick(ids, args.url_wait_seconds))

    if not args.skip_enrich:
        outputs["public_enrich"] = run_public_enrich(ids, args)

    if not args.skip_contact:
        outputs["contact"] = run_contact(ids, args)

    if not args.skip_planner:
        outputs["planner"] = run_planner(ids, args)

    outputs["after"] = summarize(fetch_rows(ids))
    outputs["planner_snapshot"] = fetch_rows(ids, PLANNER_FIELDS)
    print(json.dumps(outputs, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
