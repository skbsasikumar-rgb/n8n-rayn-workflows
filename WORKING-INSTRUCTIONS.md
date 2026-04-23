# Working Instructions

This file is the standing operating record for work on the `RAYN Enrichment Worker`.

## Operating Rules

- Store standing instructions in a `.md` file in the repository instead of leaving them only in chat context.
- Read this file before changing the workflow.
- Simple is best. Do not be over clever.
- Keep the worker narrowly scoped. Do not expand into downstream enrichment unless explicitly requested.
- Prefer deterministic logic over LLM logic whenever the same outcome can be achieved reliably without an LLM.
- If search evidence is weak, fail cleanly. Do not force a homepage guess just to avoid a partial result.
- Reject bad URLs early rather than letting them flow downstream.
- When a choice is between a wrong URL and no URL, prefer no URL.
- Keep the worker focused on this path only:
  - Searx/Serper homepage discovery
  - LLM URL choice
  - URL validation
  - Crawl4AI scrape
  - company homepage name and parent company extraction
  - final writeback
  - stop
- `best_url` must come from the URL-resolution stage only.
- `website_content` must come from the Crawl4AI scrape stage only.
- `company_homepage_name` and `parent_company` must come only after scraping.
- Keep logic generic. Do not hardcode behavior around clinics unless explicitly required.

## [PLANS]

### Current workflow plan

- Stabilize homepage discovery first, then company facts.
- Do not mix homepage fixes and company-facts fixes in the same pass unless one directly depends on the other.
- Use this loop:
  1. inspect live row state
  2. map row to execution
  3. identify the first bad stage
  4. patch only that stage
  5. sync repo JSON and live workflow together
  6. rerun a small controlled batch
  7. verify in Postgres

### Rerun plan

- Before rerunning rows or testing workflow updates:
  1. deactivate the worker and upstream dispatcher/orchestrator
  2. if executions may still be in flight, restart Railway `Primary`
  3. clear old execution history for the target workflow
  4. reset target rows to clean `pending`
  5. reactivate the workflow
  6. run the target batch
  7. verify results from Postgres after executions settle

### Debug plan

- Start with execution evidence, not guesses.
- For partial or failed rows, inspect:
  - `status`
  - `evidence_gap`
  - `last_stage`
  - `last_error`
  - `best_url`
- Pull node-level execution data for the exact failing rows and inspect:
  - `Assess Homepage Search`
  - `Serper - Homepage Search`
  - `Pick First Valid Homepage`
  - `Parse URL Choice`
  - `Resolve URL Status`
  - `Crawl4AI - Scrape`
  - `Parse Company Facts`
  - `Prepare Final Result`
- Do not patch later nodes to hide an upstream quality problem.

## [DECISIONS]

### Standing workflow decisions

- Keep Searx first. Use Serper only as fallback when Searx is weak or noisy.
- Do not trigger Serper fallback when Searx already surfaced at least one strong official candidate.
- When Serper fallback runs, merge usable Searx and Serper candidates. Do not discard Searx just because fallback was used.
- Keep search queries identity-anchored:
  - exact company name in quotes
  - exact company name + Singapore
  - backup query only when needed
- Keep fallback queries simple. Do not append `official website` unless there is clear evidence it helps.
- If exact and broad search both fail, one small brand-core fallback query is acceptable. Do not add clever multi-branch search logic.
- If the input already contains an explicit location qualifier such as `@ <place>`, do not let a generic domain-clue query override the stronger exact or backup query path.

### Homepage selection decisions

- LLM URL choice is a tie-breaker only. It must not rescue weak candidates.
- Use official branch pages as evidence when they are clearly on the official domain, but write the clean homepage root into `best_url`.
- If the root is the stored `best_url` but the matched evidence sits on a stronger branch or subpage, scrape the matched official evidence page while still writing the clean root into `best_url`.
- Preserve correct official subdomains and official page URLs. Do not collapse to the wrong broader root.
- If collapsing to the bare root would remove the only clear country or entity linkage, preserve the selected country or entity landing page instead.
- A global official root is acceptable if the evidence clearly links that site to the input company or entity.
- If the only evidence is third-party directory or marketplace pages, leave `best_url` blank.

### Candidate filtering decisions

- Block common junk before the LLM sees it:
  - directories
  - listing/profile pages
  - map pages
  - PDFs and office documents
  - obvious third-party business databases
  - noisy social/forum/community pages
- Treat review pages, opening-hours pages, local-business directories, and profile pages as noise unless the official domain itself is clearly present.
- Do not promote clue domains from snippet text alone unless the hostname itself carries company identity.
- Ignore malformed clue domains and weak labels.
- Use word-level token matching for homepage identity checks. Do not rely on short substring matches.
- Generic business words such as `clinic`, `centre`, `center`, `gp`, `doctor`, or `practice` must not create official evidence on their own.

### Company facts decisions

- `company_homepage_name` is the matched business, brand, entity, network, or branch name you want to keep from the official site.
- Prefer short, clean brand or entity names over long marketing titles and descriptive headings.
- When the official site clearly supports a broader official brand or group name that is a stronger canonical identity than the branch suffix, prefer that broader brand for `company_homepage_name`.
- When the exact input business name is clearly listed on the official site and no stronger brand-level override is supported, keep the input business name.
- Split evidence titles on `-`, `•`, or `»` and treat the clean brand/entity segment as a first-class candidate.
- If the scraped page looks like a `404` or utility page but the matched evidence URL or title still clearly identifies the official brand or entity, prefer the evidence identity over the `404` text.
- For legal-entity inputs, prefer the exact legal entity over a consumer-facing marketing brand when the site supports that entity.
- `parent_company` should only be different when the official site clearly supports it with wording such as:
  - `part of`
  - `a member of`
  - `a brand of`
  - `by`
  - `under`
  - `owned by`
  - `clinic chain by`
- Reject as `parent_company`:
  - programme names such as `Healthier SG`
  - membership or sector bodies such as `NCSS`
  - government agencies such as `Ministry of Health`
  - doctor names
  - slogans
  - sentence fragments
  - bare location tokens
  - subsidiary or product labels that do not carry family-brand or legal-entity structure
- If the scraped page contains a fuller legal-entity form that clearly extends the chosen parent, prefer the richer legal form in writeback.
- If no distinct parent is explicitly supported, set `parent_company = company_homepage_name`.

### Infra decisions

- Use direct Postgres inspection when NocoDB output is unreliable.
- Verify the live table schema before changing writeback payloads.
- Do not assume a push will redeploy Railway `Primary`.
- For `Primary`, inspect Railway build logs before assuming the service is down.
- Keep a root [Dockerfile](/Users/sasikumar/Documents/n8n/Dockerfile) if Railway is configured to build `Primary` from repo root.

## [PROGRESS]

### Workflow direction changes

- Early work mixed homepage fixes and company-facts fixes, which caused regressions to reopen after good URL behavior had already been achieved.
- The current operating rule is to freeze the unaffected stages and patch only the first bad stage for the rows being tested.
- Company-facts extraction was moved toward stronger deterministic cleanup after the LLM instead of relying on the raw LLM output.
- Final writeback now carries a meaningful share of normalization logic because some bad values are only obvious after both scrape content and parsed facts are available together.

### Current active gap list

- Homepage resolution still needs work on:
  - `209` `1 Bishan Medical Clinic`
  - `219` `ORI Medical Clinic (Dr Lim Kien Sin)`
  - `220` `Dr Panda Medical Centre @ Sin Ming`
- Facts-stage verification still needs a clean settled rerun on:
  - `213` `DR+ Medical & Paincare Bishan`
  - `216` `HMI OneCare Clinic Bishan`
- Stable improvements already observed on:
  - `215` `Raffles Medical Bishan`
  - `217` `HMI Medical`
  - `221` `Bukit Merah Family Clinic`
  - `228` `Pacific Family Clinic`

## [DISCOVERIES]

### Search and picker behavior

- If `Assess Homepage Search` says Searx is strong but the surviving pages are directories or review sites, the assess-node logic is wrong. Do not loosen the picker to compensate.
- Third-party article pages can survive if title or snippet token overlap is too permissive. This happened on `209`, where `pacificprime.sg` was the only candidate left even though it was clearly not official.
- Direct Postgres checks are the most reliable source of truth for:
  - lead row state
  - whether a rerun actually settled
  - whether a fix held after writeback

### Execution behavior

- If a rerun never reaches any node and stays at `worker_started`, treat that as runtime or execution-state instability first, not a workflow-logic bug.
- After a `Primary` restart, fresh webhook executions can sit at `worker_started` for a few minutes before node data appears.
- Avoid firing a large parallel batch immediately after a restart when possible. A small controlled rerun gives a clearer signal while the runner settles.

### Company-facts behavior

- Footer and navigation text can help confirm a parent, but they are not enough on their own if the extracted value is prose or a location token.
- Evidence titles using `Location » Brand` are common and need explicit splitting on `»`.
- Some parent mistakes are only visible at final writeback time, where broader page context and legal-entity snippets are both available.

### Local tools

- Current helper scripts:
  - [scripts/rayn_noco_rows.py](/Users/sasikumar/Documents/n8n/scripts/rayn_noco_rows.py) for row inspection and reset
  - [scripts/rayn_n8n_executions.py](/Users/sasikumar/Documents/n8n/scripts/rayn_n8n_executions.py) for execution listing and cleanup
  - [scripts/rayn_company_facts_probe.py](/Users/sasikumar/Documents/n8n/scripts/rayn_company_facts_probe.py) for probing scraped site text against current facts output
- Useful local packages already available:
  - `psycopg`
  - `pgcli`
  - `httpie`
  - `rich`
  - `tabulate`

## [OUTCOMES]

### What has been achieved

- The worker is now scoped to homepage discovery, scrape, company facts, and final writeback only.
- Downstream enrichment logic is no longer the active work surface.
- Several bad third-party URL writes were eliminated by tightening homepage candidate filtering.
- Several company-facts outputs were cleaned up by adding deterministic normalization after scrape:
  - broader brand promotion when the page clearly supports it
  - rejection of programme and location-only parent values
  - richer legal-entity preference in writeback

### What remains

- Homepage resolution still needs another narrow pass for `209`, `219`, and `220`.
- Facts-stage reruns for `213` and `216` still need clean settled verification after the latest patch.
- The batch should not be widened until `209–228` is clean again.

### Lessons learned

- Fixing one thing and breaking another is usually a process problem, not just a code problem.
- The main prevention is:
  - keep the flow clear
  - record decisions once
  - patch only one stage at a time
  - verify against a small truth set before widening scope
