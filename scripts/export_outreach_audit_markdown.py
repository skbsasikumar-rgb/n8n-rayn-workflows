#!/usr/bin/env python3
"""Convert cold-email planner audit JSON into a readable markdown QA report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


EMAIL_KEYS = ("email_1", "email_2", "email_3", "email_4")
STYLE_BANNED_PHRASES = (
    "comprehensive",
    "robust",
    "tailored",
    "leverage",
    "landscape",
    "readiness journey",
    "certification work",
    "value proposition",
    "stakeholders",
    "end-to-end",
    "unlock",
    "empower",
    "delve",
    "furthermore",
    "moreover",
    "additionally",
    "practical question is whether",
)


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


def parse_json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def field(row: dict[str, Any], name: str) -> str:
    return str(row.get(name) or "").strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def body_style_flags(row: dict[str, Any]) -> list[str]:
    bodies = [field(row, f"{key}_body") for key in EMAIL_KEYS]
    blob = "\n".join(bodies).lower()
    flags: list[str] = []
    long_paragraphs = [
        f"email_{index}_long_paragraph"
        for index, body in enumerate(bodies, start=1)
        if any(word_count(paragraph) > 45 for paragraph in body.split("\n\n"))
    ]
    flags.extend(long_paragraphs)
    banned = [phrase for phrase in STYLE_BANNED_PHRASES if phrase in blob]
    if banned:
        flags.append("banned_words_found:" + ",".join(banned))
    email2 = field(row, "email_2_body").lower()
    pressure = field(row, "pressure_type")
    if "s$4,300" in email2:
        if pressure != "hia_regulatory":
            flags.append("non_hia_pricing_leak")
        if "smaller clinic" not in email2 and "smaller clinics" not in email2:
            flags.append("price_missing_small_clinic_context")
    if "70%" in email2 and "if the route applies" not in email2 and "subject to programme confirmation" not in email2:
        flags.append("percentage_missing_caveat")
    if pressure == "hia_regulatory":
        email3 = field(row, "email_3_body").lower()
        if not all(term in email3 for term in ("access", "backup", "incident")):
            flags.append("hia_diagnostic_missing_access_backup_incident")
    return flags


def sentence_slot_metadata(row: dict[str, Any]) -> dict[str, Any]:
    direct = row.get("sentence_slot_metadata")
    if isinstance(direct, dict):
        return direct
    sequence = parse_json_value(row.get("email_sequence_json"))
    if isinstance(sequence, dict) and isinstance(sequence.get("sentence_slot_metadata"), dict):
        return sequence["sentence_slot_metadata"]
    return {}


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
                f"- email_2_mode: `{field(row, 'email_2_mode') or field(row, 'email_3_mode') or 'unknown'}`",
                f"- funding_followup_mode: `{field(row, 'funding_followup_mode') or field(row, 'email_2_mode') or field(row, 'email_3_mode') or 'unknown'}`",
                f"- email_3_mode: `{field(row, 'email_3_mode') or 'unknown'}`",
                f"- clinic_size_guess: `{field(row, 'clinic_size_guess') or 'unknown'}`",
                f"- clinic_size_confidence: `{field(row, 'clinic_size_confidence') or 'unknown'}`",
                f"- endpoint_band_guess: `{field(row, 'endpoint_band_guess') or 'unknown'}`",
                f"- endpoint_band_confidence: `{field(row, 'endpoint_band_confidence') or 'unknown'}`",
                f"- pricing_email_2_mode: `{field(row, 'pricing_email_2_mode') or 'unknown'}`",
                f"- pricing_claim_safe: `{field(row, 'pricing_claim_safe') or 'unknown'}`",
                f"- pricing_claim_line: {field(row, 'pricing_claim_line') or 'none'}",
                f"- final_send_gate_passed: `{field(row, 'final_send_gate_passed') or 'unknown'}`",
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
            slot_meta = sentence_slot_metadata(row)
            slot_steps = slot_meta.get("email_steps") if isinstance(slot_meta, dict) else {}
            if isinstance(slot_steps, dict) and slot_steps:
                lines.extend(["### Sentence Slots", ""])
                for email_key in EMAIL_KEYS:
                    slots = slot_steps.get(email_key)
                    if not isinstance(slots, dict) or not slots:
                        continue
                    rendered = ", ".join(f"{slot}: `{choice}`" for slot, choice in slots.items())
                    lines.append(f"- {email_key}: {rendered}")
                lines.append("")
            style_flags = body_style_flags(row)
            lines.extend(
                [
                    "### Style Check",
                    "",
                    f"- paragraphs_over_limit: `{', '.join(flag for flag in style_flags if flag.endswith('_long_paragraph')) or 'none'}`",
                    f"- banned_words_found: `{next((flag.split(':', 1)[1] for flag in style_flags if flag.startswith('banned_words_found:')), 'none')}`",
                    f"- email_2_price_funding_safety: `{'ok' if not any(flag in style_flags for flag in ('non_hia_pricing_leak', 'price_missing_small_clinic_context', 'percentage_missing_caveat')) else 'check'}`",
                    f"- hia_diagnostic_segment_check: `{'check' if 'hia_diagnostic_missing_access_backup_incident' in style_flags else 'ok'}`",
                    "",
                ]
            )
        for index, key in enumerate(EMAIL_KEYS, start=1):
            subject = field(row, f"{key}_subject") or "(no subject)"
            body = field(row, f"{key}_body") or "(empty)"
            lines.extend([f"### Email {index}: {subject}", "", f"- word_count: `{word_count(body)}`", "", body, ""])
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
