# RAYN n8n Lead Outbound Workflow

This repo contains the n8n workflows, helper scripts, and scraper service used to find and enrich Singapore leads for Rayn Secure's cyber and data security certification outbound motion.

Rayn Secure: `https://www.raynsecure.com/`

## Current Workflow

| File | Purpose |
| --- | --- |
| `wf-discovery.json` | Finds candidate companies and writes pending seed rows to NocoDB. |
| `wf-latest.json` | Orchestrates dispatch: resets stale processing rows, claims capacity, and calls the worker webhook. |
| `wf-worker.json` | Enriches a row: homepage discovery, URL validation, canonical-domain dedupe, scrape, company facts, and writeback. |
| `services/crawl4ai/` | Browser scraper service used by the worker. |
| `services/searxng/` | Search service configuration used by homepage discovery. |
| `scripts/` | Local operator helpers for row reset, execution cleanup, and debugging. |

## Documentation

Start with these files:

- `docs/workflow/overview.md` for the end-to-end architecture.
- `docs/workflow/data-contract.md` for NocoDB fields, statuses, and worker writeback rules.
- `docs/workflow/runbook.md` for deployment, clean reruns, and verification.
- `docs/workflow/operations-log.md` for current progress and regression anchors.
- `docs/workflow/improvement-backlog.md` for the next work that will make the workflow more reliable.

The historical GSD discussion log lives at `.planning/phases/01-workflow-reliability/01-DISCUSSION-LOG.md`. The operator-facing log is now `docs/workflow/operations-log.md`.

## Operating Principles

- Discovery should find companies, not enrich them.
- The worker should be deterministic before using an LLM.
- Official homepage roots beat directories, donation platforms, malls, maps, social pages, and press mentions.
- Every writeback should be auditable from `evidence_url`, `scrape_url`, `source_urls`, `search_evidence_json`, `last_stage`, and `last_error`.
- A row with a duplicate `canonical_domain` should link to `duplicate_of_id` and stop enrichment.
- Full-table reruns should clear old executions first, reset only target rows, then verify final row fields.
- If an external repo, library, tool, or service looks like a better path, call it out and wait for approval before switching the workflow to it.

## Secrets

Do not put API keys, NocoDB tokens, n8n keys, or Railway credentials in repo files. Use n8n credentials, Railway variables, NocoDB credential storage, or user-level Codex configuration.
