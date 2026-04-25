# Data Contract

This document defines the rebuild contract for the lead enrichment table.

## Required Input Fields

- `company_name`: company or organisation name to enrich.

## Worker Output Fields

- `url_picked`: first-pass LLM-selected URL from the first 10 OpenSERP Google results.
- `status`: current workflow state.
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

## Status Values

- `url picked`: first-pass URL selection completed.
- `no url picked`: first-pass search did not produce a clearly official URL.
- `pending`: ready for worker.
- `processing`: claimed by worker.
- `enriched`: completed with sufficient official evidence.
- `partial`: useful output exists, but one or more enrichment stages failed.
- `no official homepage`: no official homepage verified.
- `url duplicate`: canonical domain matched an existing row and enrichment was skipped.
- `error`: unrecoverable workflow failure.

## URL Rules

- `best_url` must be a homepage root URL.
- Remove tracking parameters and fragments.
- Prefer registrable root domain when `www` or marketing subdomains are not essential.
- Keep a subdomain only when it is the official product or brand homepage.
- Never set `best_url` to a directory, social page, donation page, job page, marketplace, map page, or article.

## Duplicate Rules

If `canonical_domain` already exists on another row:

- set `status` to `url duplicate`.
- set `duplicate_of_id` to the existing row ID.
- skip website scraping and parent-company inference.
- keep enough notes to explain the duplicate match.

`canonical_domain` is derived from the selected URL, not from the raw company name. It removes protocol, path, query, fragment, port, credentials, and leading `www`, then stores the registrable root domain. Singapore suffixes such as `com.sg`, `org.sg`, and `net.sg` remain intact.
