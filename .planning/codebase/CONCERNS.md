# Codebase Concerns

**Analysis Date:** 2026-03-26

## High-Risk Areas

### 1. The repository contains two very different systems with no obvious boundary
- The root-level automation assets `wf-latest.json` and `wf-discovery.json` are production-like n8n workflows, while `get-shit-done/` is a separate Node.js CLI/package with its own installer, hooks, docs, and tests.
- This mixed shape is a maintenance risk because security posture, testing strategy, and deployment assumptions are different across the two halves.
- A future refactor or release process can easily fix one half while missing the other.

### 2. `get-shit-done/bin/install.js` is a major maintenance hotspot
- `get-shit-done/bin/install.js` is 4,925 lines and mixes CLI parsing, runtime detection, config mutation, hook installation, migration logic, uninstall logic, and output formatting.
- The file is large enough that changes are hard to reason about locally and regressions are likely to show up in edge-case runtime combinations.
- Tests exist, but the installer still concentrates a lot of cross-platform and cross-runtime behavior into one file instead of a small set of isolated modules.

### 3. Workflow JSON files encode critical business logic in opaque strings
- `wf-latest.json` and `wf-discovery.json` store JavaScript, prompt templates, retry settings, branching rules, and credential behavior inside large serialized JSON blobs.
- That makes review, diffing, code search, and targeted testing much harder than if the logic lived in source modules.
- Even small edits are fragile because one malformed string or copied node property can break execution.

## Security Concerns

### Hardcoded secrets are still committed in workflow JSON
- `wf-discovery.json` contains a plaintext NocoDB `xc-token` in multiple request nodes.
- `wf-latest.json` also contains inline `xc-token` headers and at least one inline `Authorization` header alongside credential-backed nodes.
- This is the highest-severity issue in the repo: secrets in versioned workflow files are exposed to history, copies, and local scans.

### Security controls are inconsistent across the repo
- `get-shit-done/get-shit-done/bin/lib/security.cjs` adds path validation, prompt-injection scanning, and shell-argument validation for the CLI.
- The root n8n workflows do not get equivalent structured protections; they rely mostly on `continueOnFail`, ad hoc code-node guards, and manual conventions.
- The result is a split security model where the CLI has defense-in-depth, but the workflow automation layer still accepts much weaker guarantees.

### Prompt-injection protection is advisory in hooks, not enforcement
- `get-shit-done/hooks/gsd-prompt-guard.js` only warns when suspicious content is written into `.planning/`.
- `get-shit-done/hooks/gsd-workflow-guard.js` is also advisory and disabled by default unless `hooks.workflow_guard` is set.
- That is a reasonable DX tradeoff, but it means the repo intentionally prefers non-blocking warnings over hard prevention for risky content flows.

### Background update checking shells out to npm during session start
- `get-shit-done/hooks/gsd-check-update.js` spawns a detached child process and runs `npm view get-shit-done-cc version`.
- That adds a network-dependent execution path to session startup behavior and creates a reliability/security surface around shelling out to package metadata.
- It also means startup behavior can differ by runtime environment even when the core package code is unchanged.

## Reliability And Bug Risks

### Silent fallback patterns can hide real failures
- In `wf-latest.json`, parse nodes such as `Parse Enrichment`, `Parse Pain Logic`, and `Parse Email Gen` call `JSON.parse(...)` and fall back to `{}` on failure.
- In practice that converts malformed LLM output into blank enrichment fields instead of a hard stop with actionable diagnostics.
- Because downstream status transitions still happen, bad or partial output can look like successful automation.

### `continueOnFail` is heavily used in production workflow paths
- `wf-latest.json` and `wf-discovery.json` contain many nodes with `continueOnFail: true`.
- This keeps the workflow moving, but also makes state corruption and silent partial success more likely when upstream APIs fail or return unexpected shapes.
- The workflows rely on status strings and branch conditions more than on typed failure channels or centralized error reporting.

### Business logic depends heavily on brittle string state
- Workflow branching in `wf-latest.json` depends on values such as `status`, `_skip`, `verification_status`, and LLM-derived fields.
- There is no type system or enum enforcement around those values in the workflow JSON.
- Typos, casing drift, or prompt output changes can alter behavior without any compile-time signal.

### The CLI still carries regression-sensitive config compatibility logic
- `get-shit-done/get-shit-done/bin/lib/core.cjs` and `get-shit-done/get-shit-done/bin/lib/config.cjs` both perform compatibility merging and migration for old/new config layouts.
- `get-shit-done/tests/core.test.cjs` includes explicit regression coverage for prior config bugs like omitted `model_overrides`, which is a sign this area has already been error-prone.
- Backward-compatibility code is useful, but it increases the chance that future changes break older project states in subtle ways.

### Hook behavior is intentionally fail-open
- `get-shit-done/hooks/gsd-context-monitor.js`, `get-shit-done/hooks/gsd-prompt-guard.js`, and `get-shit-done/hooks/gsd-workflow-guard.js` all swallow parse/file errors and exit silently.
- That avoids disrupting the user, but it also means broken hooks are easy to miss in real use.
- Observability is weak: a hook can stop protecting users and still appear healthy.

## Performance And Scale Concerns

### Workflow throughput is limited by sequential API-heavy design
- `wf-latest.json` performs multiple serial HTTP requests to OpenRouter, NocoDB, and other services with retries and long timeouts.
- The enrichment path includes expensive prompt construction and multiple parse/write stages per lead.
- This will scale linearly with lead volume and can become slow or costly before there is any obvious signal in the repo.

### Discovery still loads and compares large result sets inside code nodes
- `wf-discovery.json` reads discovery/leads tables via `?limit=1000` requests and then performs deduping in inline JavaScript.
- That is acceptable for small data volumes, but the current pattern shifts more work into in-memory workflow execution as the tables grow.
- There is no sign of indexed server-side deduplication, incremental checkpoints, or a durable paging strategy.

### Installer and hook logic do repeated sync filesystem work
- `get-shit-done/bin/install.js` and the files under `get-shit-done/get-shit-done/bin/lib/` use `readFileSync`, `writeFileSync`, `readdirSync`, `execSync`, and `spawnSync` extensively.
- For a CLI this is often fine, but the concentration of sync operations makes large installs and validation flows less responsive and harder to parallelize.
- The performance risk is mostly user-experience related rather than raw server cost.

## Fragile Implementation Areas

### Cross-runtime support is broad, so edge cases are hard to retire
- `get-shit-done/bin/install.js` supports Claude, OpenCode, Gemini, Codex, Copilot, Antigravity, Cursor, and Windsurf.
- Every new runtime increases the matrix for config locations, hook behavior, uninstall/migration paths, and docs correctness.
- The code already contains runtime-specific branching and migration comments, which suggests this area accumulates compatibility debt quickly.

### Hook/config discovery still looks easy to desynchronize
- `get-shit-done/hooks/gsd-check-update.js` has its own runtime config-dir detection logic, while installer/runtime path logic also lives in `get-shit-done/bin/install.js`.
- Duplicate path-resolution logic raises the chance that one path gets updated for a new runtime and another does not.
- Tests cover some regressions here, but the structure is still fragile.

### Core planning/state code is regex-heavy and text-format dependent
- `get-shit-done/get-shit-done/bin/lib/state.cjs` updates `STATE.md` by regex replacement against markdown headings and field labels.
- `get-shit-done/get-shit-done/bin/lib/core.cjs` and `state.cjs` both depend on exact file naming and section-shape conventions inside `.planning/`.
- That makes the system powerful but brittle: manual edits to markdown structure can break automation without obvious validation.

### The repo depends on generated documentation staying aligned with behavior
- `get-shit-done/docs/`, localized READMEs, installer messages in `get-shit-done/bin/install.js`, and templates under `get-shit-done/get-shit-done/templates/` all document runtime behavior.
- Because there are many runtime-specific branches and multiple translated docs, documentation drift is a realistic concern.
- This is especially risky for installation and hook behavior where users rely on docs to recover from partial setups.

## Testing Gaps

### Tests are strong for the CLI, but they do not cover the n8n workflows as software
- `get-shit-done/tests/` is extensive and covers config, hooks, install flows, model profiles, roadmap/state behavior, and security helpers.
- There is no comparable automated test suite for `wf-latest.json` or `wf-discovery.json`.
- The highest-risk production automation artifacts are therefore the least testable parts of the repo.

### Workflow logic has no fixture-driven regression harness
- The inline JavaScript and prompt-output parsing in `wf-latest.json` and `wf-discovery.json` are not extracted into testable modules.
- There is no visible replay harness for sample payloads, LLM failures, malformed API responses, or database write failures.
- Any workflow edit is likely validated manually in n8n rather than through repeatable repository tests.

### The installer is tested, but its surface area still outpaces easy review
- The existence of tests such as `get-shit-done/tests/hook-validation.test.cjs`, `get-shit-done/tests/agent-install-validation.test.cjs`, and many installer/runtime tests is a positive sign.
- Even so, the breadth of runtime combinations in `get-shit-done/bin/install.js` means coverage can miss behavior at the seams between install, upgrade, uninstall, and migration paths.

## Practical Priorities

### Fix first
- Remove all inline secrets from `wf-latest.json` and `wf-discovery.json`, rotate exposed credentials, and move everything to managed n8n credentials/secrets.
- Add explicit failure signaling and logging around the parse/code nodes in `wf-latest.json` instead of silently defaulting to empty objects.
- Break up `get-shit-done/bin/install.js` into smaller runtime/config/hook modules before adding more runtime-specific behavior.

### Stabilize next
- Extract the root workflow JavaScript snippets into versioned source files or a fixture-backed representation so changes can be reviewed and tested.
- Centralize runtime path detection shared by `get-shit-done/bin/install.js` and hook scripts like `get-shit-done/hooks/gsd-check-update.js`.
- Add a lightweight health or replay harness for `wf-latest.json` and `wf-discovery.json` so the most operationally sensitive assets stop being test-dark.
