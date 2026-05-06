#!/usr/bin/env python3
"""Convert cold-email planner audit JSON into a readable markdown QA report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EMAIL_KEYS = ("email_1", "email_2", "email_3", "email_4")


def load_payload(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def audit_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("audits"), list):
        return [row for row in payload["audits"] if isinstance(row, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("audits"), list):
            return [row for row in data["audits"] if isinstance(row, dict)]
        nested = data.get("data")
        if isinstance(nested, dict) and isinstance(nested.get("audits"), list):
            return [row for row in nested["audits"] if isinstance(row, dict)]
    if isinstance(payload.get("rows"), list):
        return [row for row in payload["rows"] if isinstance(row, dict)]
    if "audit_report" in payload and isinstance(payload["audit_report"], dict):
        return [payload["audit_report"]]
    return [payload]


def flags_text(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return ", ".join(str(item) for item in parsed) or "none"
        except json.JSONDecodeError:
            return value or "none"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    return "none"


def field(row: dict[str, Any], name: str) -> str:
    return str(row.get(name) or "").strip()


def render_markdown(rows: list[dict[str, Any]], debug: bool = False) -> str:
    lines = ["# Cold Email Planner QA Report", ""]
    for row in rows:
        title = field(row, "company_name") or f"Row {field(row, 'row_id')}"
        decision = field(row, "automation_decision")
        decision_reason = field(row, "automation_decision_reason")
        lines.extend(
            [
                f"## {field(row, 'row_id')} - {title}",
                "",
                f"- pressure_type: `{field(row, 'pressure_type') or 'unknown'}`",
                f"- hia_service_type_guess: `{field(row, 'hia_service_type_guess') or 'unknown'}`",
                f"- hia_timeline_batch_guess: `{field(row, 'hia_timeline_batch_guess') or 'unknown'}`",
                f"- funding_status: `{field(row, 'funding_status') or 'unknown'}`",
            ]
        )
        if decision == "suppressed":
            lines.extend(
                [
                    f"- Suppressed: `{decision_reason or 'suppressed'}`",
                    "- OpenRouter: skipped",
                    "- Emails: not generated",
                ]
            )
            if debug:
                lines.append(f"- email_quality_flags: {flags_text(row.get('email_quality_flags'))}")
            lines.append("")
            if not debug:
                continue
        else:
            lines.extend([f"- email_quality_flags: {flags_text(row.get('email_quality_flags'))}", ""])
        for index, key in enumerate(EMAIL_KEYS, start=1):
            subject = field(row, f"{key}_subject") or "(no subject)"
            body = field(row, f"{key}_body") or "(empty)"
            lines.extend([f"### Email {index}: {subject}", "", body, ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Audit JSON file, or '-' for stdin")
    parser.add_argument("-o", "--output", help="Markdown output path. Defaults to stdout.")
    parser.add_argument("--debug", action="store_true", help="Include raw flags and empty email sections for suppressed rows.")
    args = parser.parse_args()

    markdown = render_markdown(audit_rows(load_payload(args.input)), debug=args.debug)
    if args.output:
        Path(args.output).write_text(markdown)
    else:
        sys.stdout.write(markdown)


if __name__ == "__main__":
    main()
