# Working Instructions

This file records standing task instructions for this repository.

## Documentation Rule

- Store standing instructions in a `.md` file in the repository instead of leaving them only in chat context.

## General Rules

- Simple is best. Do not be over clever.
- Read relevant `.md` files for useful instructions before working.

## n8n Rerun Procedure

- Before rerunning rows or testing workflow updates, deactivate the worker and upstream dispatcher/orchestrator.
- If any executions may still be in flight, restart the Railway `Primary` service to hard-stop them.
- Clear old execution history for the target workflow before the new test cycle.
- Reactivate the workflow only after cleanup is complete.
- Run the new batch.
- Verify results in the NocoDB table after the executions finish.

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
