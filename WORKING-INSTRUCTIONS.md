# RAYN Workflow Working Instructions

This file is the compact default context for RAYN n8n workflow work. Start here, then open only the exact workflow JSON, script, row, or doc needed for the task.

## Start Here

- Workflow overview: `docs/workflow/overview.md`
- Data and status contract: `docs/workflow/data-contract.md`
- Rerun and deployment runbook: `docs/workflow/runbook.md`
- Operator log and current progress: `docs/workflow/operations-log.md`
- Improvement backlog: `docs/workflow/improvement-backlog.md`

The older GSD planning log still exists at `.planning/phases/01-workflow-reliability/01-DISCUSSION-LOG.md`, with verification state in `.planning/phases/01-workflow-reliability/01-VERIFICATION.md`. Treat those as historical/internal planning artifacts, not the day-to-day operator log.

## Workflow Contract

- Rayn Secure site: `https://www.raynsecure.com/`
- Business goal: Singapore outbound lead workflow for cyber and data security certification.
- Discovery is lead generation. It may store search evidence, but the enrichment worker must require only row identity plus `company_name`.
- `wf-discovery.json` finds candidate companies and writes pending seed rows.
- `wf-latest.json` is the orchestrator that claims pending rows and dispatches the worker.
- `wf-worker.json` owns homepage discovery, URL validation, canonical-domain dedupe, scrape, facts extraction, and NocoDB writeback.

## Token Budget Rules

- Open this file first, then the specific doc under `docs/workflow/` for the task.
- Do not scan `.codex/`, `.planning/`, workflow history, or generated temp files unless the task needs them.
- Use `rg` for node names, field names, and status values.
- Keep workflow edits in the canonical JSON file being deployed: discovery in `wf-discovery.json`, orchestration in `wf-latest.json`, enrichment in `wf-worker.json`.
- Prefer one known-bad row, then first 20, then full-table reruns.

## Quality Rules

- `best_url` and `homepage_root_url` must be clean official homepage roots.
- Reject directories, donation platforms, malls, social profiles, government/program pages, PDFs, jobs, maps, and unrelated parent pages.
- Preserve `evidence_url`, `scrape_url`, `source_urls`, `search_evidence_json`, `last_stage`, and `last_error` for auditability.
- If a canonical-domain duplicate exists, write `duplicate_of_id`, mark the row as duplicate, and stop enrichment.
- If scrape fails after a valid official homepage is found, write a `partial` result with fallback evidence instead of inventing facts.

## Live Validation Rules

- A successful webhook response only means the workflow started. Always verify n8n execution history and final NocoDB row fields.
- Before adding writeback fields, confirm the NocoDB schema or pair the workflow change with a schema update.
- Before clean reruns, clear old execution records when practical, then reset only the target rows.
- Keep credentials out of repo files. Use n8n credentials, NocoDB credentials, Railway variables, or user-level Codex config.
