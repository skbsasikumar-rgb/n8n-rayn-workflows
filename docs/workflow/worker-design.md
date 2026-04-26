# Worker Design

The worker enriches one company at a time.

Input is intentionally small. The required input is `company_name`. Optional metadata can support auditability, but the worker must not depend on discovery-specific fields.

## Primary Output

The worker must produce:

- `best_url`: clean homepage root URL with no subdomain unless the subdomain is the official brand homepage.
- `canonical_domain`: domain used for duplicate detection.
- `company_homepage_name`: name presented by the official site.
- `parent_company`: umbrella or parent company when clearly evidenced.
- `website_scrape`: compact but useful website content for later LLM extraction.
- `source_urls`: URLs used as evidence.
- `confidence`: `High`, `Medium`, or `Low`.
- `notes`: short reason for the result.

## Worker Stages

1. Normalize input.
2. Search official homepage candidates.
3. Reject directories, marketplaces, social sites, job boards, and donation platforms.
4. Pick the official homepage root.
5. Detect canonical-domain duplicates.
6. Scrape the website.
7. Infer company homepage name and parent company from evidence.
8. Write final result.

## Rebuild Slice 1

The first rebuild slice is intentionally smaller than the full worker:

1. Read rows with `company_name` and blank `url_picked`.
2. Query OpenSERP Google with `company_name Singapore`.
3. Keep the first 10 search results.
4. Ask an LLM to choose the best official URL or return blank.
5. Derive `canonical_domain` from the selected URL.
6. If another row already has the same `canonical_domain`, set `duplicate_of_id`, mark `status` as `url duplicate`, and stop enrichment for that row.
7. Write the selected URL and dedupe state to NocoDB.
8. Store the query, first 10 Google results, canonical domain, LLM reason, and raw LLM output in `search_evidence_json`.

No input normalization, scraping, parent-company inference, or discovery logic belongs in this slice.

## Enrichment Rerun Branch

The batch enrichment webhook is separate from URL discovery.

1. Read rows with `company_name`, non-blank `url_picked`, and blank `best_url`.
2. Convert NocoDB rows directly into enrichment items.
3. Call the Crawl4AI public enrichment endpoint.
4. Write `best_url`, `homepage_root_url`, `website_content`, `website_scrape`, `company_homepage_name`, `parent_company`, `source_urls`, `notes`, `confidence`, `last_stage`, and `last_error`.

This branch must not call OpenSERP or OpenRouter. Existing `url_picked` values are treated as the source of truth for website scraping unless validation rejects the URL.

The Crawl4AI HTTP node uses a 300s timeout. Do not lower this without reducing `page_limit` or `page_timeout_ms`, because legitimate five-page crawls can exceed 120s and otherwise get written back as false `enrichment_error` rows.

## Success Criteria

The worker is successful when:

- obvious official homepages are selected.
- obvious non-official pages are rejected.
- `best_url` is always a root homepage URL.
- duplicate canonical domains stop enrichment and set `duplicate_of_id`.
- parent company is populated only when evidence supports it.
- failed scrape does not erase a verified homepage.

## Non-Goals

The worker does not:

- discover new leads.
- decide outbound prioritisation.
- guess parent companies from weak signals.
- hardcode one-off company URL hints as normal logic.
- enrich rows when canonical-domain duplicate detection has already matched an existing lead.

## Canonical-Domain Dedupe

The worker computes `canonical_domain` immediately after `url_picked`.

Rules:

- strip protocol, path, query, fragment, port, credentials, and leading `www`.
- keep Singapore second-level suffixes such as `com.sg`, `org.sg`, and `net.sg` as registrable roots.
- otherwise use the final two hostname labels.
- lookup existing rows by `canonical_domain`, excluding the current row.
- if a duplicate exists, set `duplicate_of_id` to the existing row ID and `status` to `url duplicate`.

Later enrichment stages must skip rows where `duplicate_of_id` is present or `status` is `url duplicate`.

## Initial Test Set

Use a small fixed set before scaling:

- known official homepage
- no official homepage
- directory false positive
- parent company example
- canonical-domain duplicate
- scrape failure with verified homepage
