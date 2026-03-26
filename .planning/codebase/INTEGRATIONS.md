# Integrations

## Integration Overview

- This repository has two distinct integration surfaces:
  - GSD runtime/tool integrations for AI coding environments, configured under `/Users/sasikumar/Documents/n8n/.claude`, `/Users/sasikumar/Documents/n8n/.codex`, and `/Users/sasikumar/Documents/n8n/get-shit-done/bin/install.js`
  - External service integrations embedded directly in the n8n workflow exports `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json`

## AI Runtime And Developer Tool Integrations

- Claude Code
  - Local hook config in `/Users/sasikumar/Documents/n8n/.claude/settings.json`
  - Hook commands point to `/Users/sasikumar/Documents/n8n/.claude/hooks/gsd-check-update.js`, `/Users/sasikumar/Documents/n8n/.claude/hooks/gsd-context-monitor.js`, `/Users/sasikumar/Documents/n8n/.claude/hooks/gsd-prompt-guard.js`, and `/Users/sasikumar/Documents/n8n/.claude/hooks/gsd-statusline.js`
- Codex
  - Agent registry and hooks in `/Users/sasikumar/Documents/n8n/.codex/config.toml`
  - Config references agent TOML files under `/Users/sasikumar/Documents/n8n/.codex/agents`
- Other supported runtimes handled by installer logic in `/Users/sasikumar/Documents/n8n/get-shit-done/bin/install.js`
  - OpenCode via `OPENCODE_CONFIG_DIR` / `OPENCODE_CONFIG`
  - Gemini via `GEMINI_CONFIG_DIR`
  - Copilot via `COPILOT_CONFIG_DIR`
  - Cursor via `CURSOR_CONFIG_DIR`
  - Windsurf via `WINDSURF_CONFIG_DIR`
  - Antigravity via `ANTIGRAVITY_CONFIG_DIR`
  - Claude via `CLAUDE_CONFIG_DIR`
  - Codex via `CODEX_HOME`

## Search, Crawl, And Research Services

- Brave Search, Firecrawl, and Exa are optional capability toggles in `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/config.cjs`
  - Detected from env vars or key files:
  - `BRAVE_API_KEY`
  - `FIRECRAWL_API_KEY`
  - `EXA_API_KEY`
  - File fallbacks under `~/.gsd/` are also supported by the config loader
- These services are configuration-aware inside GSD, but this repo does not contain direct API calls to them in the current checked files

## n8n Workflow Integrations

### Workflow: `/Users/sasikumar/Documents/n8n/wf-discovery.json`

- Trigger/runtime
  - Uses `n8n-nodes-base.scheduleTrigger`
  - Workflow name is `RAYN Lead Discovery - NocoDB`
- External APIs and services
  - Google Serper Places API via `POST https://google.serper.dev/places`
  - NocoDB on Railway via multiple `/api/v1/db/data/...` endpoints at `https://nocodb-production-f802.up.railway.app`
- Data flow
  - Reads discovered businesses from Serper
  - Writes discovery rows to one NocoDB table
  - Reads discovery and leads tables from NocoDB
  - Pushes deduplicated/processed records into a leads table in NocoDB
- Authentication pattern
  - NocoDB calls send an `xc-token` header directly in the workflow JSON
  - `Content-Type: application/json` is set for bulk POST writes

### Workflow: `/Users/sasikumar/Documents/n8n/wf-latest.json`

- Trigger/runtime
  - Uses `n8n-nodes-base.scheduleTrigger` and `n8n-nodes-base.splitInBatches`
  - Workflow name is `RAYN Lead Enrichment - NocoDB`
  - `active` is `true` in the export; settings include `executionOrder: v1` and `binaryMode: separate`
- External APIs and services
  - OpenRouter chat completions via `https://openrouter.ai/api/v1/chat/completions`
  - Google Serper Search via `https://google.serper.dev/search`
  - Serper Scrape fallback via `https://scrape.serper.dev/search`
  - Jina Reader proxy via dynamic `https://r.jina.ai/...`
  - Hunter Domain Search via `https://api.hunter.io/v2/domain-search`
  - Anymailfinder decision-maker lookup via `https://api.anymailfinder.com/v5.1/find-email/decision-maker`
  - NocoDB on Railway via `https://nocodb-production-f802.up.railway.app/api/v1/db/data/...`
  - Arbitrary target-site reachability checks through dynamic `HEAD {{ $json.best_url }}`
- Integration behavior
  - OpenRouter is used for multiple LLM stages: clean name, URL dedupe, URL validation, HIA gate, enrichment, vendor enrichment, pain logic, email generation, and parent-company inference
  - NocoDB is both the system of record and workflow state store; the flow repeatedly patches row status values such as failure states, pending, processing resets, and final writes
  - Serper and Jina are used for search/scrape collection before enrichment
  - Hunter and Anymailfinder are used for contact discovery
- Authentication pattern
  - OpenRouter requests include `HTTP-Referer=https://primary-production-a6441.up.railway.app` and `X-Title=RAYN Secure Enrichment`
  - Hunter uses `X-API-KEY`
  - Jina scraping uses `Authorization: Bearer ...`
  - Serper scrape fallback uses `X-API-Key`
  - NocoDB updates use `xc-token`

## Databases And Persistence

- NocoDB is the only concrete database/service layer visible in the checked repository content.
- It is accessed over HTTP rather than through a driver/ORM.
- The workflows reference at least two tables/resources under project path fragments such as:
  - `/api/v1/db/data/bulk/noco/pb7f1zou786xyqc/mp36f8mgk115qse`
  - `/api/v1/db/data/noco/pb7f1zou786xyqc/mey3zgihq7o4at9`
- GSD itself persists local state in repository files rather than a database:
  - `/Users/sasikumar/Documents/n8n/.planning/config.json`
  - `/Users/sasikumar/Documents/n8n/.claude/gsd-file-manifest.json`
  - `/Users/sasikumar/Documents/n8n/.codex/gsd-file-manifest.json`

## Auth Providers

- No end-user auth provider or application login system is implemented in the repository code that was inspected.
- Authentication is service-to-service and mostly header-based inside workflow JSON exports.
- AI runtime integrations authenticate through host tools and config directories rather than in-repo auth code.

## Webhooks And Event Hooks

- Claude hook events are configured in `/Users/sasikumar/Documents/n8n/.claude/settings.json`:
  - `SessionStart`
  - `PostToolUse`
  - `PreToolUse`
- Codex hook events are configured in `/Users/sasikumar/Documents/n8n/.codex/config.toml`:
  - `SessionStart`
- n8n workflows in this repo are schedule-driven, not inbound-webhook-driven; no `webhook` node type was found in the exported workflow JSON files.

## Practical Concerns Visible In The Current Repo

- The n8n workflow exports contain live-looking integration secrets directly in source JSON:
  - NocoDB `xc-token`
  - Hunter `X-API-KEY`
  - Jina bearer token
  - Serper scrape API key
- Because those credentials are embedded in `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json`, integration changes currently require source edits instead of secret injection through environment-backed credentials.
- No local Docker/database service definitions were found at repo root for these integrations, so the external systems appear to be hosted services rather than local development dependencies.
