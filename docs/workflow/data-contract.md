# Data Contract

This document defines the rebuild contract for the lead enrichment table.

## Required Input Fields

- `company_name`: company or organisation name to enrich.

## Worker Output Fields

- `url_picked`: first-pass LLM-selected URL from the first 10 Google SERP results.
- `status`: queue-control source of truth. Only `pending` rows are normally eligible to run.
- `best_url`: clean official homepage root URL.
- `homepage_root_url`: same canonical homepage root used by downstream steps.
- `canonical_domain`: domain used for dedupe.
- `duplicate_of_id`: existing record ID when this row duplicates another canonical domain.
- `company_homepage_name`: company name found on the official site.
- `parent_company`: parent, umbrella, or group company when supported.
- `website_scrape`: compact website content for later extraction.
- `source_urls`: evidence URLs separated by ` | `.
- `search_evidence_json`: JSON evidence for search query, first 10 Google results, selected URL, and LLM reason.
- `confidence`: `High`, `Medium`, or `Low`.
- `notes`: concise explanation.
- `last_stage`: last completed stage.
- `last_error`: actionable error if any.

## Workflow Control Fields

Current supported fields:

- `status`: one of `pending`, `processing`, `completed`, `skipped`, `failed`, or `needs_review`.
- `status_reason`: stable row outcome or claim reason such as `processing:crawl`, `url_picked`, `duplicate_canonical_domain`, `enrichment_completed`, or `partial_crawl`.
- `run_id`: workflow execution identifier for the current or latest run.
- `processing_started_at`: timestamp when the row was claimed.
- `processing_finished_at`: timestamp when the row reached a terminal status.
- `last_attempted_at`: timestamp of the latest attempt.
- `attempt_count`: number of attempts recorded by the worker.
- `error_type`: stable technical or business error category.
- `error_message`: technical or business error detail.
- `retry_eligible`: `true` or `false` flag written by the worker.
- `source_row_created_at`: snapshot of the row `CreatedAt` at claim time.
- `source_row_updated_at`: snapshot of the row `UpdatedAt` at claim time.
- `last_stage`: technical pipeline stage such as `url_discovery`, `url_pick`, `dedupe`, `crawl`, `crawled`, `partial`, or `enrichment_error`.
- `last_error`: short actionable error or final skip reason.
- `notes`: human-readable evidence and status detail.

## Status Values

- `pending`: ready for worker.
- `processing`: claimed by worker.
- `completed`: completed with sufficient official evidence.
- `skipped`: intentionally not processed further, such as no official URL, duplicate domain, invalid URL, excluded category, or robots restriction.
- `failed`: attempted but failed because of a technical or provider error.
- `needs_review`: useful output exists but the result is ambiguous, partial, low confidence, or requires human review.

Do not write stage values such as `url picked`, `partial`, `skipped_url_validation_failed`, or `url duplicate` into `status`. Put those details in `last_stage`, `last_error`, and `notes`.

## URL Rules

- `best_url` must be a homepage root URL.
- Remove tracking parameters and fragments.
- Prefer registrable root domain when `www` or marketing subdomains are not essential.
- Keep a subdomain only when it is the official product or brand homepage.
- Never set `best_url` to a directory, social page, donation page, job page, marketplace, map page, or article.

## Duplicate Rules

If `canonical_domain` already exists on another row:

- set `status` to `skipped`.
- set `duplicate_of_id` to the existing row ID.
- skip website scraping and parent-company inference.
- keep enough notes to explain the duplicate match.

`canonical_domain` is derived from the selected URL, not from the raw company name. It removes protocol, path, query, fragment, port, credentials, and leading `www`, then stores the registrable root domain. Singapore suffixes such as `com.sg`, `org.sg`, and `net.sg` remain intact.

## Rerun Boundaries

URL discovery reruns may update `url_picked`, `canonical_domain`, `duplicate_of_id`, `search_evidence_json`, `status`, `status_reason`, `run_id`, processing timestamps, retry fields, `last_stage`, and `last_error`.

Enrichment reruns must preserve `url_picked` and must not call the Google SERP provider. They may update only downstream website fields such as `best_url`, `homepage_root_url`, `website_content`, `website_scrape`, `company_homepage_name`, `parent_company`, `source_urls`, `notes`, `confidence`, `status`, `status_reason`, `run_id`, processing timestamps, retry fields, `last_stage`, and `last_error`.
