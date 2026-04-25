# Data Contract

## Tables

The active lead table is the NocoDB table used by all three workflow files:

- project path in workflow URLs: `pb7f1zou786xyqc`
- lead table id in workflow URLs: `mey3zgihq7o4at9`

Keep table identifiers out of prompts unless a node needs them. Keep credentials out of repo files.

## Discovery Output

`wf-discovery.json` writes seed rows in bulk. Current seed fields are:

| Field | Meaning |
| --- | --- |
| `company_name` | Required company name to enrich. |
| `hia_batch` | Optional batch label. |
| `candidate_homepage` | Search hint only. The worker must re-validate it. |
| `candidate_domain` | Search hint only. The worker must re-validate it. |
| `discovery_category` | Discovery segment/category. |
| `discovery_area` | Discovery area/query group. |
| `status` | Always starts as `pending`. |

Worker enrichment must require only row identity plus `company_name`. Discovery evidence can improve ranking, but it must not bypass worker validation.

## Orchestrator Contract

`wf-latest.json` reads `pending` rows, claims capacity, PATCHes rows to `processing`, then dispatches worker payloads.

Minimum worker payload:

| Field | Required | Notes |
| --- | --- | --- |
| `Id` | Yes | NocoDB row id. |
| `company_name` | Yes | The only required enrichment input. |
| `hia_batch` | No | Preserved for audit and batch filtering. |

Current orchestrator capacity rules:

- stale `processing` rows are reset after 10 minutes
- maximum in-flight count is 10
- claimed rows are marked with `status=processing`

## Worker Writeback Fields

Core URL fields:

- `best_url`
- `homepage_root_url`
- `canonical_domain`
- `evidence_url`
- `scrape_url`
- `source_urls`

Company fields:

- `company_homepage_name`
- `operating_company_root_name`
- `parent_company`

Scrape and quality fields:

- `website_content`
- `website_scrape`
- `confidence`
- `notes`
- `fallback_used`
- `search_evidence_json`
- `evidence_gap`
- `last_stage`
- `last_error`

`website_content` starts with a structured evidence section from the scraper when available. It may include `About`, `Services`, `Locations`, `Team`, `Legal And Group Signals`, `Contacts`, `Privacy And Compliance`, `Footer`, and `Schema Org` sections before the broader cleaned page text. Future LLM extraction should prefer those sections for parent-company, group/umbrella, and company-size hints before falling back to raw page content.

Duplicate fields:

- `duplicate_of_id`

## URL Semantics

| Field | Rule |
| --- | --- |
| `best_url` | Clean official homepage root for the named company. |
| `homepage_root_url` | Same root used as canonical homepage evidence. |
| `canonical_domain` | Registrable domain used for dedupe. |
| `evidence_url` | URL that supported the homepage decision. |
| `scrape_url` | URL sent to scraper. |
| `source_urls` | Pipe-separated audit trail of material URLs. |

For Singapore domains, normalize roots to the registrable domain, for example `clinic.gooddoctors.com.sg/path` should not become a subdomain root unless the subdomain is clearly the official standalone site. Preserve explicit `http://` only when the official site requires it.

## Status Values

| Status | Meaning | Next Action |
| --- | --- | --- |
| `pending` | Ready for orchestrator dispatch. | Claim and dispatch. |
| `processing` | Claimed or running. | Reset if stale beyond threshold. |
| `partial` | Official evidence found, but scrape or extraction had a recoverable gap. | Review fallback fields before rerun. |
| `url duplicate` | Same canonical domain already exists. | Use `duplicate_of_id`; do not enrich further. |
| `failed` | Unrecoverable failure or older stale failure. | Inspect `last_stage` and `last_error`, then reset if retryable. |

Prefer `partial` over `failed` when a valid official homepage exists but scrape or page evaluation fails.

## Dedupe Rule

If `canonical_domain` matches an existing row with a different `Id`:

1. Select the earliest non-duplicate matching row as primary.
2. Write `duplicate_of_id` to the current row.
3. Write `status=url duplicate`.
4. Preserve `canonical_domain`, homepage root, and evidence.
5. Stop before scraping or company-facts extraction.

This avoids paying search, scrape, and LLM cost for duplicate companies.
