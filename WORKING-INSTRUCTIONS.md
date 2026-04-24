# RAYN Worker Operating Notes

This file is the compact default context for RAYN enrichment work. Read only this file first unless the task names another file, node, execution, or row.

## Token Budget Rules

- Start with this file plus the exact workflow JSON/node/row being changed.
- Do not scan `.codex/`, `.planning/`, workflow history, or generated temp files unless the task specifically needs them.
- Use `rg` to find exact node names or field names; avoid broad reads of entire workflow JSON unless editing graph structure.
- Use MCP tools through deferred discovery/tool search where possible; do not load full MCP schemas just to check availability.
- Validate with a small row slice before widening. Prefer one known-bad row, then first 20, then broader batches.
- Keep workflow edits in one canonical artifact unless asked otherwise: `wf-worker.json` for enrichment worker changes.
- Do not create extra scratch files unless they materially speed validation; clean or ignore them before handoff.

## Workflow Contract

- Discovery is lead generation. It should send only `company_name` into the worker enrichment path.
- Worker enrichment owns homepage discovery, URL validation, website scrape, facts extraction, parent-company detection, and writeback.
- Default worker path: search candidates, choose homepage, validate URL, scrape via Crawl4AI, extract facts, write NocoDB result, stop.
- Do deterministic filtering before LLM calls. Use LLMs for ambiguous ranking/extraction, not for basic cleanup.
- Prefer official company homepage roots over directories, PDF files, LinkedIn, maps, social pages, press articles, or government/program pages.
- If the website is unavailable or blocked, write a clear fallback status instead of inventing homepage facts.

## URL Selection

- `best_url` should be the most specific official homepage for the named company.
- `homepage_root_url` should be the root official website used for crawl and evidence.
- Accept local subsidiary or clinic roots when they are the official customer-facing site.
- Reject search results whose titles/snippets are primarily jobs, news, archives, directories, PDFs, social profiles, maps, procurement pages, or unrelated parents.
- Use parent domains only when the child brand has no clear standalone official homepage.
- Preserve `evidence_url`, `scrape_url`, and `source_urls` so each writeback is auditable.

## Company Name Fields

- `company_homepage_name` is the operating name shown on the resolved homepage.
- `operating_company_root_name` is the normalized legal or brand root for the homepage.
- `parent_company` is filled only when evidence shows a broader owning group or parent brand.
- Do not copy a parent name into `company_homepage_name` when the homepage clearly represents the child operating company.
- If no parent is supported by evidence, leave parent blank or use the workflow’s explicit no-parent convention.

## Known Truth Set

Use these rows as quick regression anchors when tuning homepage or parent extraction:

- HMI Medical: `https://www.hmimedical.com/`; root `HMI Medical`; no separate parent unless evidence says otherwise.
- HMI OneCare: `https://www.onecaremedical.com.sg/`; root `HMI OneCare Clinics`; parent `HMI Medical` or `HMI Group`.
- Tokio Marine Life Insurance Singapore: `https://www.tokiomarine.com/sg/en/life.html`; root `Tokio Marine Life Insurance Singapore`; parent `Tokio Marine Group`.
- First-20 validation usually covers NocoDB IDs `209` through `228`; verify the live table before rerunning.

## Rerun Protocol

- Confirm whether repo JSON or live n8n is the source of truth before deployment.
- For live n8n changes, update the workflow, validate it, then run the smallest useful slice.
- For first-20 reruns, reset only the relevant rows/claim fields, dispatch them, and verify final NocoDB writeback.
- A successful webhook response is not enough; confirm execution history and row output fields.
- When a row fails, inspect the search result list and the deterministic extractor output before changing prompts.

## MCP Usage

- NocoDB MCP is preferred for table schema, row reads, row updates, and first-20 verification.
- n8n MCP is preferred for workflow reads, validation, deployment, and execution history when auth is healthy.
- Railway MCP is only needed for deployment/log tasks; do not load it for local workflow JSON edits.
- Keep API keys out of repo-local files. Store live MCP credentials in user-level Codex config or the platform credential store.

## Prompt And Model Routing

- Default to lean reasoning for routine workflow edits, row checks, and docs cleanup.
- Escalate to higher reasoning only for graph rewrites, ambiguous production failures, or multi-service deployment decisions.
- Keep prompts field-specific. Prefer short deterministic rules and named examples over long prose.
- Put reusable rules here instead of duplicating them in node prompts.
- In workflow nodes, pass compact JSON evidence, not full raw HTML or complete search payloads, unless the model explicitly needs them.

## Writeback Fields

- Core URL fields: `best_url`, `homepage_root_url`, `evidence_url`, `scrape_url`, `source_urls`.
- Scrape fields: `website_content`, `website_scrape`, `fallback_used`.
- Company fields: `company_homepage_name`, `operating_company_root_name`, `parent_company`.
- Quality fields: `confidence`, `notes`, `search_evidence_json`.
- Before adding writeback fields, confirm the NocoDB schema or ship the schema update with the workflow change.
