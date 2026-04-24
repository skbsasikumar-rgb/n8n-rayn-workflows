#!/usr/bin/env python3
"""
Prepare a clean rerun for the RAYN worker.

Behavior:
1. List recent executions for visibility.
2. Optionally delete provided execution IDs.
3. Reset target rows back to a clean pending state.
4. Show the reset rows for verification.

This script stays deliberately simple.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
NOCO_HELPER = os.path.join(ROOT, "rayn_noco_rows.py")
N8N_HELPER = os.path.join(ROOT, "rayn_n8n_executions.py")


def run(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a clean rerun for selected RAYN rows.")
    parser.add_argument("--ids", required=True, help="Comma-separated row IDs to reset and verify")
    parser.add_argument(
        "--delete-execution-ids",
        help="Optional comma-separated n8n execution IDs to delete before resetting rows",
    )
    parser.add_argument(
        "--list-limit",
        type=int,
        default=20,
        help="How many recent executions to list before cleanup",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    print("== Recent executions ==")
    run([sys.executable, N8N_HELPER, "list", "--limit", str(args.list_limit)])

    if args.delete_execution_ids:
        print("== Delete execution records ==")
        run([sys.executable, N8N_HELPER, "delete", "--ids", args.delete_execution_ids])

    print("== Reset rows ==")
    run([sys.executable, NOCO_HELPER, "reset", "--ids", args.ids])

    print("== Verify rows ==")
    run([sys.executable, NOCO_HELPER, "show", "--ids", args.ids])


if __name__ == "__main__":
    main()
