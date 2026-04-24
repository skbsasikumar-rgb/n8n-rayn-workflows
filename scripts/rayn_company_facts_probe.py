#!/usr/bin/env python3
"""
Probe company-facts evidence for a RAYN lead row.

This script is intentionally small and explicit.
Simple is best. Do not be over clever.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Iterable

import psycopg


GENERIC_TOKENS = {
    "clinic",
    "clinics",
    "centre",
    "center",
    "medical",
    "group",
    "holdings",
    "holding",
    "doctor",
    "doctors",
    "practice",
    "health",
    "healthcare",
    "care",
    "surgery",
    "family",
    "service",
    "services",
    "the",
    "and",
    "of",
    "pte",
    "ltd",
    "limited",
    "private",
    "singapore",
    "sg",
}

BRAND_RE = re.compile(
    r"[A-Z][A-Za-z0-9&+.,'()\-\s]{2,140}?"
    r"(?:Group|Holdings?|Paincare|OneCare|Medical Group)"
)

PARENT_RE = re.compile(
    r"(?:part of|a member of|member of|a brand of|brand of|owned by|under|operated by|managed by|clinic chain by)\s+"
    r"(?:the\s+)?"
    r"([A-Z][A-Za-z0-9&+.,'()\-\s]{2,120}?)(?=[.;,\n]|$)",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    value: str
    score: int


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def tokens(value: object) -> list[str]:
    return [token for token in clean(value).lower().split() if token]


def distinctive_tokens(value: object) -> list[str]:
    return [token for token in tokens(value) if len(token) >= 2 and token not in GENERIC_TOKENS]


def extract_brand_phrases(text: str) -> list[str]:
    found: set[str] = set()
    for match in BRAND_RE.finditer(text or ""):
        phrase = clean(match.group(0))
        if phrase:
            found.add(phrase)
    return sorted(found, key=lambda item: (-len(item), item.lower()))


def extract_parent_phrases(text: str) -> list[str]:
    found: set[str] = set()
    for match in PARENT_RE.finditer(text or ""):
        phrase = clean(match.group(1))
        if phrase:
            found.add(phrase)
    return sorted(found, key=lambda item: (-len(item), item.lower()))


def score_candidate(candidate: str, input_name: str) -> int:
    value = clean(candidate)
    if not value:
        return -10

    score = len(value)
    value_compact = compact(value)
    input_compact = compact(input_name)

    if input_compact and value_compact == input_compact:
        score += 100
    elif input_compact and value_compact.startswith(input_compact):
        score += 40
    elif input_compact and input_compact.startswith(value_compact):
        score += 20

    input_tokens = distinctive_tokens(input_name)
    value_tokens = distinctive_tokens(value)
    shared = len(set(input_tokens) & set(value_tokens))
    score += shared * 10

    if len(tokens(value)) > 8:
        score -= 100
    if re.match(r"^(from|as of|our heritage|our group|about us|north bridge road)\b", value, re.I):
        score -= 100

    if re.search(r"\b(group|holdings?|paincare|onecare|medical group)\b", value, re.I):
        score += 35
    if re.search(r"\b(group|holdings?|paincare|onecare|medical group)\b", clean(input_name), re.I):
        score += 15

    return score


def choose_best_brand(input_name: str, candidates: Iterable[str]) -> Candidate:
    best = Candidate(value="", score=-10_000)
    for candidate in candidates:
        score = score_candidate(candidate, input_name)
        if score > best.score:
            best = Candidate(value=clean(candidate), score=score)
    return best


def fetch_rows(dsn: str, ids: list[int]) -> list[dict]:
    sql = """
        select id, company_name, status, best_url, company_homepage_name,
               parent_company, website_content, last_stage, evidence_gap, last_error
        from pb7f1zou786xyqc.leads
        where id = any(%s)
        order by id
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ids,))
            cols = [desc.name for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe company-facts evidence for RAYN rows.")
    parser.add_argument("--ids", required=True, help="Comma-separated row IDs to inspect")
    parser.add_argument(
        "--dsn",
        default=os.getenv("DATABASE_URL", "").strip(),
        help="Postgres DSN. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--max-content",
        type=int,
        default=4000,
        help="Maximum website_content chars to display.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.dsn:
        raise SystemExit("Missing --dsn or DATABASE_URL")

    ids = [int(part.strip()) for part in args.ids.split(",") if part.strip()]
    rows = fetch_rows(args.dsn, ids)

    out = []
    for row in rows:
        content = clean(row.get("website_content", ""))
        input_name = clean(row.get("company_name", ""))
        brand_candidates = extract_brand_phrases(content)
        parent_candidates = extract_parent_phrases(content)
        best_brand = choose_best_brand(input_name, brand_candidates)
        out.append(
            {
                "id": row["id"],
                "company_name": input_name,
                "status": row.get("status", ""),
                "best_url": row.get("best_url", ""),
                "company_homepage_name": row.get("company_homepage_name", ""),
                "parent_company": row.get("parent_company", ""),
                "last_stage": row.get("last_stage", ""),
                "evidence_gap": row.get("evidence_gap", ""),
                "brand_candidates": brand_candidates[:10],
                "best_brand_candidate": {
                    "value": best_brand.value,
                    "score": best_brand.score,
                },
                "parent_candidates": parent_candidates[:10],
                "content_excerpt": content[: args.max_content],
            }
        )

    if args.format == "json":
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return

    for item in out:
        print(f"ID: {item['id']}")
        print(f"Company: {item['company_name']}")
        print(f"Current homepage: {item['company_homepage_name']}")
        print(f"Current parent: {item['parent_company']}")
        print(f"Best brand candidate: {item['best_brand_candidate']['value']}")
        print("Brand candidates:")
        for candidate in item["brand_candidates"]:
            print(f"  - {candidate}")
        print("Parent candidates:")
        for candidate in item["parent_candidates"]:
            print(f"  - {candidate}")
        print("Content excerpt:")
        print(item["content_excerpt"])
        print("-" * 80)


if __name__ == "__main__":
    main()
