# Workflow Overview

## Goal

RAYN's workflow supports outbound lead generation for Singapore companies that may need cyber and data security certification help from Rayn Secure.

The workflow should produce a clean, auditable company record with:

- official homepage root
- operating company homepage name
- parent company, only when supported by evidence
- source URLs and fallback notes
- duplicate linkage by canonical domain

## Components

| Component | File | Role |
| --- | --- | --- |
| Discovery | `wf-discovery.json` | Finds candidate companies from search and writes pending NocoDB seed rows. |
| Orchestrator | `wf-latest.json` | Resets stale processing rows, checks capacity, claims pending rows, and dispatches worker calls. |
| Worker | `wf-worker.json` | Enriches each row independently and writes final result fields. |
| Browser scraper | `services/crawl4ai/app.py` | Normalizes page scrape output for the worker. |
| Browserless fallback | Railway `browserless` service | Renders pages when Crawl4AI returns an error page, empty content, or navigation failure. |
| Search service | `services/searxng/settings.yml` | Supports deterministic homepage search. |
| Local helpers | `scripts/` | Resets rows, clears executions, probes evidence, and replays homepage selection. |

## Current Flow

1. `wf-discovery.json` runs from schedule or manual trigger.
2. Discovery normalizes search results and writes rows with `status=pending`.
3. `wf-latest.json` resets stale `processing` rows, checks in-flight capacity, and claims pending rows.
4. The orchestrator dispatches each claimed row to the worker webhook at `rayn-enrichment-worker-v2`.
5. `wf-worker.json` normalizes input, searches for homepage candidates, validates URL status, and resolves a clean homepage root.
6. The worker checks for existing rows with the same `canonical_domain`.
7. Duplicate rows are written with `duplicate_of_id` and enrichment stops.
8. Non-duplicate rows are scraped through the Crawl4AI service.
9. If Crawl4AI returns empty or unusable content, the worker tries Browserless on the same resolved scrape URL.
10. The scraper path returns bounded page text plus structured evidence when available.
11. Company facts are extracted from scrape evidence and written back to NocoDB.

## Source Of Truth

- Workflow JSON in this repo is the reviewed source of truth before deployment.
- Live n8n is the runtime source of truth after deployment.
- NocoDB row values are the final output source of truth after reruns.
- `docs/workflow/operations-log.md` is the current operator log.
- `.planning/` contains historical planning and verification notes only.

## Boundaries

Discovery should not decide final homepage, parent company, certification fit, or enrichment facts. It can store candidate hints for audit, but the worker must be able to enrich from `company_name` alone.

The worker should not depend on a discovery URL being correct. It should treat `candidate_homepage` and `candidate_domain` as weak hints and re-validate official homepage evidence.

The scraper should not crawl an entire site by default. It should keep the current bounded crawl, then organize high-value evidence into structured buckets so future LLM extraction can classify solo clinic, group/umbrella relationship, and SME/enterprise hints from cleaner inputs.

## Success Criteria

- Pending rows do not get stuck in `processing`.
- `best_url` is a clean official homepage root without unwanted subdomains.
- Directory and third-party evidence does not become the official homepage.
- Duplicate canonical domains are linked through `duplicate_of_id` and skipped.
- Scrape failures produce useful `partial` rows with evidence, not silent failures.
- Every row can be debugged from persisted evidence fields.
