# Stack

## Repository Shape

- The repository root at `/Users/sasikumar/Documents/n8n` is not a conventional application root with a single build manifest. It contains:
- A Node.js CLI/package in `/Users/sasikumar/Documents/n8n/get-shit-done`
- Local Claude/Codex runtime configuration in `/Users/sasikumar/Documents/n8n/.claude` and `/Users/sasikumar/Documents/n8n/.codex`
- Planning state in `/Users/sasikumar/Documents/n8n/.planning`
- Two exported n8n workflow definitions in `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json`

## Languages

- JavaScript with CommonJS modules is the primary implementation language:
  - `/Users/sasikumar/Documents/n8n/get-shit-done/bin/install.js`
  - `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/config.cjs`
  - `/Users/sasikumar/Documents/n8n/get-shit-done/hooks/*.js`
  - `/Users/sasikumar/Documents/n8n/get-shit-done/tests/*.cjs`
- Markdown is heavily used for agent prompts, workflow specs, docs, and templates:
  - `/Users/sasikumar/Documents/n8n/get-shit-done/agents/*.md`
  - `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/workflows/*.md`
  - `/Users/sasikumar/Documents/n8n/get-shit-done/docs/*.md`
- JSON and TOML are used for runtime/configuration artifacts:
  - `/Users/sasikumar/Documents/n8n/.planning/config.json`
  - `/Users/sasikumar/Documents/n8n/.claude/settings.json`
  - `/Users/sasikumar/Documents/n8n/.codex/config.toml`
  - `/Users/sasikumar/Documents/n8n/wf-discovery.json`
  - `/Users/sasikumar/Documents/n8n/wf-latest.json`

## Runtime

- Node.js is the only explicit application runtime declared in-repo.
- `/Users/sasikumar/Documents/n8n/get-shit-done/package.json` requires `node >=20.0.0`.
- The package is published as the CLI `get-shit-done-cc`, with entrypoint `/Users/sasikumar/Documents/n8n/get-shit-done/bin/install.js`.
- The workflow exports in `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json` target n8n runtime execution using node types such as `n8n-nodes-base.scheduleTrigger`, `n8n-nodes-base.httpRequest`, `n8n-nodes-base.code`, `n8n-nodes-base.if`, `n8n-nodes-base.noOp`, and `n8n-nodes-base.splitInBatches`.

## Frameworks And Product Layers

- GSD itself is a prompt-engineering/spec-driven development toolkit rather than a web framework app.
- The main product layers are:
  - CLI installer and config management in `/Users/sasikumar/Documents/n8n/get-shit-done/bin` and `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib`
  - Agent and workflow prompt assets in `/Users/sasikumar/Documents/n8n/get-shit-done/agents` and `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/workflows`
  - Runtime hooks for Claude/Codex in `/Users/sasikumar/Documents/n8n/get-shit-done/hooks`, `/Users/sasikumar/Documents/n8n/.claude/hooks`, and `/Users/sasikumar/Documents/n8n/.codex/config.toml`
  - n8n automation flows at `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json`

## Dependencies

- Declared package metadata lives in `/Users/sasikumar/Documents/n8n/get-shit-done/package.json`.
- Production/runtime dependency model is intentionally light; the package lists only `devDependencies`:
  - `c8` for coverage
  - `esbuild` for hook bundling/build support
- Tooling and platform dependencies are mostly external CLIs/services that GSD installs into or interoperates with:
  - Claude Code
  - Codex
  - Gemini CLI
  - OpenCode
  - Copilot
  - Cursor
  - Windsurf
  - Antigravity
- The n8n workflows depend on built-in n8n node types rather than local npm modules.

## Configuration Surfaces

- Project planning/config state:
  - `/Users/sasikumar/Documents/n8n/.planning/config.json`
  - Current config enables research/plan-check/verifier flows and disables hook context warnings.
- Claude runtime config:
  - `/Users/sasikumar/Documents/n8n/.claude/settings.json`
  - Registers `SessionStart`, `PostToolUse`, and `PreToolUse` hooks plus a custom `statusLine` command.
- Codex runtime config:
  - `/Users/sasikumar/Documents/n8n/.codex/config.toml`
  - Enables `codex_hooks`, registers many `gsd-*` agents, and defines a `SessionStart` hook.
- Internal config library:
  - `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/config.cjs`
  - Handles `.planning/config.json` CRUD, defaults, model profiles, workflow toggles, branching templates, and agent skill injection.

## Tooling

- Test runner:
  - `/Users/sasikumar/Documents/n8n/get-shit-done/scripts/run-tests.cjs`
  - Invoked by `npm test` from `/Users/sasikumar/Documents/n8n/get-shit-done/package.json`
- Coverage:
  - `c8` via the `test:coverage` script in `/Users/sasikumar/Documents/n8n/get-shit-done/package.json`
- Build step:
  - `/Users/sasikumar/Documents/n8n/get-shit-done/scripts/build-hooks.js`
  - Invoked by `npm run build:hooks` and `prepublishOnly`
- Package manager evidence:
  - `/Users/sasikumar/Documents/n8n/get-shit-done/package-lock.json` indicates npm is the lockfile authority
- GitHub automation evidence:
  - README badges and templates reference GitHub Actions and GitHub-hosted distribution, though workflow YAML was not part of the inspected top-level mapping set

## Current Stack Summary

- Primary implementation: Node.js 20+, JavaScript/CommonJS
- Packaging: npm package published from `/Users/sasikumar/Documents/n8n/get-shit-done`
- Automation layer: exported n8n workflows in root JSON files
- Runtime integrations: Claude/Codex local hook systems plus multi-runtime AI tooling support
- Documentation/prompts: Markdown-first repository with large prompt/template surface area
