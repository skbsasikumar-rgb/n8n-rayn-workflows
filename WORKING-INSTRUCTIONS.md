# Working Instructions

This file records standing task instructions for this repository.

## Documentation Rule

- Store standing instructions in a `.md` file in the repository instead of leaving them only in chat context.

## General Rules

- Simple is best. Do not be over clever.
- Read relevant `.md` files for useful instructions before working.
- Keep the worker narrowly scoped. Do not expand into downstream enrichment unless explicitly requested.
- Prefer deterministic logic over LLM logic whenever the same outcome can be achieved reliably without an LLM.
- If search evidence is weak, fail cleanly. Do not force a homepage guess just to avoid a partial result.
- Reject bad URLs early rather than letting them flow downstream.
- When a choice is between a wrong URL and no URL, prefer no URL.

## n8n Rerun Procedure

- Before rerunning rows or testing workflow updates, deactivate the worker and upstream dispatcher/orchestrator.
- If any executions may still be in flight, restart the Railway `Primary` service to hard-stop them.
- Clear old execution history for the target workflow before the new test cycle.
- Reset the target rows in the table back to a clean `pending` state before the new batch.
- Do not compare new results against stale executions or stale row values.
- Reactivate the workflow only after cleanup is complete.
- Run the new batch.
- Verify results in the NocoDB table after the executions finish.

## Homepage Discovery Rules

- Keep Searx first. Use Serper only as fallback when Searx is weak or noisy.
- Do not trigger Serper fallback when Searx already surfaced at least one strong official candidate. Fallback is for missing search signal, not for replacing a usable official result.
- Keep homepage discovery generic. Do not hardcode industry-specific heuristics unless explicitly required.
- Keep search queries identity-anchored:
  - exact company name in quotes
  - exact company name + Singapore
  - only use a backup query when needed
- Do not over-strip company names.
- Do not build the homepage picker around clinic-specific logic. The job is to find the official homepage for `company_name`.
- LLM URL choice is a tie-breaker only. It must not rescue weak candidates.
- `best_url` must come only from the URL-resolution stage.
- Use official branch or clinic pages as evidence when they are clearly on the official domain, but write the clean homepage root into `best_url`.
- Do not treat official branch pages on a strong official domain as directory noise just because the title or snippet contains address, hours, or branch wording.
- If a result title is an exact or near-exact branch/page match for the input and the path also matches the branch identity, do not discard it just because the snippet contains address or appointment wording.
- If the only evidence is third-party directory or marketplace pages, leave `best_url` blank.
- If the input is a legal entity or holding company, prefer the corporate site root over a consumer brand or branch page.
- For legal-entity rows, one small deterministic domain-clue fallback is acceptable when it is generic and evidence-based. Do not add clever multi-branch search logic.
- Preserve correct official subdomains and correct official page URLs. Do not collapse to the wrong broader root.
- If collapsing to the bare root would remove the only clear country or entity linkage, preserve the selected official country or entity landing page instead.
- A global brand root is acceptable if the evidence clearly links that site to the input company or entity. Do not reject a global official site just because it is not on a local domain.
- Block common junk before the LLM sees it:
  - directories
  - listing/profile pages
  - map pages
  - PDFs and office documents
  - obvious third-party business databases
  - noisy social/forum/community pages
- If search results only show third-party mentions, return `no_official_homepage` and stop.
- If you extract a bare domain from a third-party snippet, only keep it when the hostname itself still carries company identity. Do not promote ticker, finance, or transit domains from snippet text alone.
- Do not promote clue domains with malformed or weak labels. Ignore domains with one-character labels or registrable labels that do not carry real company identity.
- Use word-level token matching for homepage identity checks. Do not rely on short substring matches that can turn unrelated text into false company evidence.

## Debugging Practice

- Start with execution evidence, not guesses.
- For partial or failed rows, inspect:
  - `status`
  - `evidence_gap`
  - `last_stage`
  - `last_error`
  - `best_url`
- Map row IDs to execution IDs before changing logic.
- Pull node-level execution data for the exact failing rows and inspect:
  - `Assess Homepage Search`
  - `Serper - Homepage Search`
  - `Pick First Valid Homepage`
  - `Parse URL Choice`
  - `Resolve URL Status`
  - `Crawl4AI - Scrape`
- Identify the first bad step in the chain. Fix that step only.
- Do not patch later nodes to hide an upstream quality problem.
- When debugging homepage issues, separate these failure modes:
  - no official site found
  - weak candidate filtering
  - wrong candidate accepted
  - URL validation rejected candidate
  - scrape timeout or scrape quality failure
- Keep before/after samples for the same row set when testing a fix.
- After each material fix, rerun a small controlled batch first.
- If a stricter filter removes bad URLs but increases `no_official_homepage`, treat that as an honest intermediate state, not a regression.
- Prefer a clean partial over polluted writeback data.

## Agentic Workflow

Use this loop when working on the worker without waiting for extra prompts:

1. Read this instruction file and inspect the current workflow before changing anything.
2. Pull live evidence first:
   - current row state from the table
   - recent executions
   - exact failing node/stage
3. Build a small truth set for the batch being tested:
   - row id
   - expected official evidence page if known
   - expected `best_url`
   - whether blank `best_url` is the correct outcome
4. Identify the first wrong stage in the chain:
   - search quality
   - candidate filtering
   - LLM URL choice
   - URL normalization/root handling
   - URL validation
   - scrape
   - company facts extraction
5. Change the smallest possible part of the workflow that can fix that stage.
6. Prefer deterministic fixes before prompt changes.
7. Keep the worker narrow. Do not add new branches or new enrichment stages while debugging homepage resolution.
8. Sync repo JSON and live n8n workflow together after each meaningful fix.
9. Rerun a small controlled batch only:
   - clear old executions
   - reset target rows to clean `pending`
   - rerun the exact rows being tested
10. Pull results from the table and compare against the truth set.
11. Record the remaining misses as a short gap list:
   - row id
   - actual result
   - expected result
   - first bad stage
12. Repeat until the gap list is shrinking for the right reasons.

Additional rules for agentic work:

- If the user provides expected homepage outcomes, treat them as the target truth set for debugging.
- Do not claim a fix worked until the rerun results were pulled from the table.
- If one row is stuck in `processing`, treat it as an execution issue and do not confuse it with homepage-selection quality.
- When a bad domain survives, inspect candidate generation and filtering before touching company-facts extraction.
- When the selected evidence page is correct but `best_url` is wrong, fix root normalization rather than search.
- When a legal-entity row is missing a site that clearly exists, add at most one simple deterministic fallback query before changing later stages.

## Data And Infra Debugging

- Use direct Postgres inspection when NocoDB API output is unreliable or credentials drift.
- Prefer reading actual table state after runs instead of assuming writeback succeeded.
- Verify the live table schema before changing writeback payloads. Do not write fields that do not exist in the target table.
- Check Railway service variables and deploy state when behavior changes unexpectedly.
- Check Railway `/healthz` and the latest successful deployment separately. A failed latest deployment does not mean the currently serving instance is down.
- For `Primary`, inspect Railway build logs before assuming an app/runtime outage. Failed repo-root deployments here can be simple build-configuration mistakes rather than service crashes.
- Do not assume a push will redeploy `Primary`. If Railway is pointed at a root without a valid Dockerfile or start target, the deploy will fail even though the previous healthy deployment stays live.
- Keep a root [Dockerfile](/Users/sasikumar/Documents/n8n/Dockerfile) for `Primary` if Railway is configured to build that service from the repo root.
- For scraper issues, verify:
  - request timeout
  - total timeout
  - concurrency
  - retry behavior
  - whether timeouts are explicit and observable in output
- If old executions appear to linger, clean execution history and hard-stop in-flight services before rerunning.

## Current Learnings

- The best debugging path for this worker is:
  - inspect the exact row state in Postgres
  - map the row to its execution ID
  - inspect the first bad node only
  - patch the smallest rule that explains the miss
  - rerun only the affected rows
- Direct Postgres checks are currently the most reliable source for:
  - lead row truth
  - stuck execution truth
  - whether a rerun actually settled
- For homepage selection quality:
  - keep clue-domain extraction strict
  - reject malformed domains and weak labels
  - use word-level identity matching
  - do not let short substrings create fake evidence
- Official branch pages are valid evidence when:
  - the title is an exact or near-exact identity match
  - the path also matches the branch or clinic identity
  - the page is on a defensible official domain
- Write the clean root into `best_url`, but allow the branch page to survive as evidence when it is the best official page found.
- If a rerun never reaches any node and stays at `worker_started`, treat that as runtime or execution-state instability first, not a homepage-selection bug.
- When this happens:
  - deactivate the workflow
  - redeploy or restart Railway `Primary`
  - clear the stuck execution record
  - reset only the target rows
  - reactivate and rerun
- Do not broaden the worker to solve isolated misses. Keep fixing the exact decision rule that failed.

## Local Helper Tools

- Use the bundled Python runtime for local debugging helpers to avoid polluting the repo.
- Keep these tools available locally when useful:
  - `psycopg` for direct Postgres inspection
  - `pgcli` for interactive Postgres access
  - `httpie` for quick webhook and HTTP testing
  - `rich` and `tabulate` for readable debug output
- Prefer small explicit local helper scripts over repeated manual API calls.
- Keep local helper scripts under [scripts/README.md](/Users/sasikumar/Documents/n8n/scripts/README.md).
- Current helper scripts:
  - [scripts/rayn_noco_rows.py](/Users/sasikumar/Documents/n8n/scripts/rayn_noco_rows.py) for row inspection and reset
  - [scripts/rayn_n8n_executions.py](/Users/sasikumar/Documents/n8n/scripts/rayn_n8n_executions.py) for execution listing and cleanup

## Worker Flow Goal

- Keep the worker focused on this path only: Searx/Serper homepage discovery -> LLM URL choice -> URL validation -> Crawl4AI scrape -> company homepage name and parent company extraction -> final writeback -> stop.
- Use LLMs only where useful:
  - choose the best official homepage from search candidates
  - extract `company_homepage_name` and `parent_company` from scraped website evidence
- `best_url` must come from the URL-resolution stage only.
- `website_content` must come from the Crawl4AI scrape stage only.
- `company_homepage_name` and `parent_company` must come only after scraping.
- Prefer the first search result only when it is a strong official match.
- If the first result is noisy, third-party, or not clearly official, keep scanning lower-ranked results until a better official URL is found or the list is exhausted.
