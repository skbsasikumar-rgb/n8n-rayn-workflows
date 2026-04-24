# Codebase Structure

**Analysis Date:** 2026-03-26

## Directory Layout

```text
/Users/sasikumar/Documents/n8n/
├── .planning/                       # Workspace planning state and generated codebase docs
│   ├── codebase/                    # ARCHITECTURE/STRUCTURE/STACK/etc. map files
│   ├── milestones/                  # Archived milestone material
│   ├── phases/                      # Phase work artifacts
│   └── research/                    # Research notes and supporting docs
├── .claude/                         # Local Claude runtime install generated from GSD assets
├── .codex/                          # Local Codex runtime install, skills, and agents
├── get-shit-done/                   # Actual nested npm package/source tree
│   ├── agents/                      # Agent specs shipped to runtimes
│   ├── assets/                      # Logos and static media
│   ├── bin/                         # npm entry scripts
│   ├── commands/                    # User-facing command definitions
│   │   └── gsd/                     # GSD command set
│   ├── docs/                        # User and contributor docs, plus translations
│   ├── get-shit-done/               # Core internal resources and CLI implementation
│   │   ├── bin/                     # gsd-tools CLI and lib modules
│   │   ├── commands/                # Internal mirrored command docs
│   │   ├── references/              # Shared guidance docs
│   │   ├── templates/               # Markdown templates
│   │   └── workflows/               # Orchestration workflow docs
│   ├── hooks/                       # Runtime hook sources and dist output
│   ├── scripts/                     # Build and test helper scripts
│   ├── tests/                       # Node test files
│   └── .github/workflows/           # CI automation
├── wf-discovery.json                # Exported n8n discovery workflow
└── wf-latest.json                   # Exported n8n enrichment/latest workflow
```

## Directory Purposes

**Workspace root `/Users/sasikumar/Documents/n8n/`:**
- Purpose: Coordination repo that combines planning docs, local runtime installs, the nested `get-shit-done/` source package, and exported n8n workflows.
- Notable files: `wf-discovery.json`, `wf-latest.json`.
- Note: There is no root-level `package.json`; the executable package lives one level down in `get-shit-done/`.

**Planning directory `/Users/sasikumar/Documents/n8n/.planning/`:**
- Purpose: File-based project memory for the current workspace.
- Contains: `config.json`, `STATE.md`, `ROADMAP.md`, `MILESTONES.md`, plus subdirectories such as `codebase/`, `milestones/`, `phases/`, and `research/`.
- Key generated docs: `/Users/sasikumar/Documents/n8n/.planning/codebase/ARCHITECTURE.md`, `/Users/sasikumar/Documents/n8n/.planning/codebase/STRUCTURE.md`, and sibling analysis files.

**Local runtime installs `/Users/sasikumar/Documents/n8n/.claude/` and `/Users/sasikumar/Documents/n8n/.codex/`:**
- Purpose: Installed runtime-specific assets for Claude and Codex in this workspace.
- Contains: Agents, commands, hooks, skills, and mirrored `get-shit-done` resources for the host runtime.
- Important distinction: These are runtime materializations, not the canonical package source.

**Package root `/Users/sasikumar/Documents/n8n/get-shit-done/`:**
- Purpose: Source-of-truth npm package.
- Contains: `package.json`, `package-lock.json`, `README*.md`, `CHANGELOG.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`.
- Entry registration: `package.json` exposes the binary `get-shit-done-cc` and points it to `bin/install.js`.

**Agent definitions `/Users/sasikumar/Documents/n8n/get-shit-done/agents/`:**
- Purpose: Markdown specs for specialized subagents.
- Naming: Files use the `gsd-<role>.md` pattern, such as `gsd-codebase-mapper.md` and `gsd-verifier.md`.
- Usage: Installed into runtime-specific agent directories by the installer.

**Command definitions `/Users/sasikumar/Documents/n8n/get-shit-done/commands/gsd/`:**
- Purpose: User-facing command catalog.
- Contains: 57 markdown files, including `map-codebase.md`, `plan-phase.md`, `execute-phase.md`, `review.md`, and `ship.md`.
- Naming: Flat `kebab-case.md` filenames keyed by command intent.

**Internal resource tree `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/`:**
- Purpose: Core resources consumed by the installer and runtimes.
- Subdirectories:
- `bin/` contains `gsd-tools.cjs` plus implementation modules in `bin/lib/`.
- `commands/` contains internal command docs used by some runtimes.
- `references/` stores shared guidance like `git-integration.md` and `verification-patterns.md`.
- `templates/` holds markdown scaffolds, including `templates/codebase/*.md`.
- `workflows/` holds 56 orchestration markdown files.

**CLI implementation `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/`:**
- Purpose: Executable backend behind the markdown workflows.
- Key files:
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/gsd-tools.cjs`
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/core.cjs`
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/init.cjs`
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/state.cjs`
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/phase.cjs`
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/roadmap.cjs`
- `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/verify.cjs`
- Naming: Functional CommonJS modules with `kebab-case.cjs`.

**Hooks `/Users/sasikumar/Documents/n8n/get-shit-done/hooks/`:**
- Purpose: Runtime safety and telemetry scripts.
- Source files: `gsd-check-update.js`, `gsd-context-monitor.js`, `gsd-prompt-guard.js`, `gsd-statusline.js`, `gsd-workflow-guard.js`.
- Build output: `scripts/build-hooks.js` copies validated files into `hooks/dist/` for publishing.

**Scripts `/Users/sasikumar/Documents/n8n/get-shit-done/scripts/`:**
- Purpose: Build, test, and security support scripts.
- Key files: `build-hooks.js`, `run-tests.cjs`, `secret-scan.sh`, `prompt-injection-scan.sh`, `base64-scan.sh`.
- Naming: Node helpers use `.cjs` or `.js`; shell scanners use `.sh`.

**Tests `/Users/sasikumar/Documents/n8n/get-shit-done/tests/`:**
- Purpose: Regression coverage for installer, CLI, hooks, and planning behavior.
- Contains: Flat `*.test.cjs` files plus `helpers.cjs`.
- Representative files: `commands.test.cjs`, `init.test.cjs`, `roadmap.test.cjs`, `security.test.cjs`, `workstream.test.cjs`, `codex-config.test.cjs`.

**Documentation `/Users/sasikumar/Documents/n8n/get-shit-done/docs/`:**
- Purpose: Product and contributor docs.
- Structure: Base English docs at the top level, translated sets under `ja-JP/`, `ko-KR/`, `pt-BR/`, and `zh-CN/`, plus `superpowers/` design docs.
- Representative files: `ARCHITECTURE.md`, `USER-GUIDE.md`, `COMMANDS.md`, `CLI-TOOLS.md`.

**CI `/Users/sasikumar/Documents/n8n/get-shit-done/.github/workflows/`:**
- Purpose: Repository automation.
- Files: `test.yml`, `security-scan.yml`, `auto-label-issues.yml`.

## Key File Locations

**Entry Points:**
- `get-shit-done/package.json` defines the published package and binary.
- `get-shit-done/bin/install.js` is the install/uninstall executable.
- `get-shit-done/get-shit-done/bin/gsd-tools.cjs` is the internal command router used by workflows.
- `get-shit-done/scripts/run-tests.cjs` is the local test runner entry.

**Configuration and State:**
- `.planning/config.json` stores workspace planning configuration.
- `.planning/STATE.md` stores current project state.
- `.planning/ROADMAP.md` stores roadmap and phase definitions.
- `get-shit-done/package.json` stores package metadata, scripts, and publish surface.

**Core Logic:**
- `get-shit-done/get-shit-done/bin/lib/core.cjs` contains shared path, output, and config helpers.
- `get-shit-done/get-shit-done/bin/lib/init.cjs` builds workflow bootstrap payloads.
- `get-shit-done/get-shit-done/bin/lib/state.cjs` manages `STATE.md`.
- `get-shit-done/get-shit-done/bin/lib/template.cjs` handles template filling.
- `get-shit-done/get-shit-done/bin/lib/security.cjs` centralizes safety checks.

**Workflow Definitions:**
- `get-shit-done/commands/gsd/` is the user command surface.
- `get-shit-done/get-shit-done/workflows/` is the reusable orchestration layer.
- `get-shit-done/agents/` holds worker definitions referenced by workflows.

**Testing and Validation:**
- `get-shit-done/tests/` holds automated tests.
- `get-shit-done/scripts/build-hooks.js` validates hook syntax before copying.
- `get-shit-done/.github/workflows/test.yml` and `get-shit-done/.github/workflows/security-scan.yml` define CI checks.

## Naming Conventions

**Files:**
- Markdown commands, workflows, references, and templates use `kebab-case.md`.
- Agent files use `gsd-<role>.md`.
- Internal Node modules use `kebab-case.cjs`.
- Hook files use `gsd-<purpose>.js`.
- Tests use `<subject>.test.cjs`.
- High-importance planning docs use uppercase names like `STATE.md`, `ROADMAP.md`, `ARCHITECTURE.md`, and `STRUCTURE.md`.

**Directories:**
- Collection directories are lowercase and usually plural: `agents/`, `commands/`, `hooks/`, `scripts/`, `tests/`, `templates/`, `workflows/`.
- Translation directories use locale names like `ja-JP/`, `ko-KR/`, `pt-BR/`, and `zh-CN/`.
- Hidden runtime/config roots use dot-prefix names: `.planning/`, `.claude/`, `.codex/`.

**Special Patterns:**
- Runtime-installed copies mirror source assets but live under hidden tool-specific directories.
- The nested folder `get-shit-done/get-shit-done/` is intentional: the outer folder is the npm package root, and the inner folder contains packaged runtime resources and the `gsd-tools` implementation.
- Root workflow exports follow `wf-*.json`.

## Where to Add New Code

**New user-facing command:**
- Add the command spec under `get-shit-done/commands/gsd/<command-name>.md`.
- Add or update the orchestration doc under `get-shit-done/get-shit-done/workflows/<command-name>.md`.
- Add tests in `get-shit-done/tests/`, usually as `<command-or-flow>.test.cjs`.

**New CLI utility behavior:**
- Extend `get-shit-done/get-shit-done/bin/gsd-tools.cjs`.
- Put the domain logic into the appropriate `get-shit-done/get-shit-done/bin/lib/*.cjs` module or add a new sibling module if the concern is distinct.

**New agent or checker:**
- Add `get-shit-done/agents/gsd-<role>.md`.
- Wire command/workflow references to it and add install/test coverage where needed.

**New template or reference doc:**
- Put templates in `get-shit-done/get-shit-done/templates/`.
- Put reusable guidance in `get-shit-done/get-shit-done/references/`.

**New hook or installable runtime behavior:**
- Add the hook source under `get-shit-done/hooks/`.
- Update `get-shit-done/scripts/build-hooks.js` if it should ship in `hooks/dist/`.
- Update `get-shit-done/bin/install.js` if the new behavior affects installation or runtime mapping.

## Special Directories

**`/Users/sasikumar/Documents/n8n/.planning/`:**
- Meaning: Generated and human-maintained workspace memory for active work.
- Mutation path: Written by agents, `gsd-tools`, and planning workflows.

**`/Users/sasikumar/Documents/n8n/.claude/` and `/Users/sasikumar/Documents/n8n/.codex/`:**
- Meaning: Local installed runtime assets for this workspace.
- Mutation path: Typically produced or updated by the installer rather than treated as the primary implementation tree.

**`/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/templates/codebase/`:**
- Meaning: Source templates for generated codebase-map docs.
- Mutation path: Updated when the expected structure of codebase-map outputs changes.

---

*Structure analysis: 2026-03-26*
