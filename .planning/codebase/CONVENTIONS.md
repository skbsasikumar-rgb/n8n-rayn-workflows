# Coding Conventions

**Analysis Date:** 2026-03-26

## Naming Patterns

**Files:**
- Root workflow exports use `wf-*.json`, currently `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json`.
- The publishable package lives under `/Users/sasikumar/Documents/n8n/get-shit-done`; shipped source is mostly CommonJS `.cjs` in `get-shit-done/bin/lib/`, tests are `*.test.cjs` in `get-shit-done/tests/`, and hooks are `gsd-*.js` in `get-shit-done/hooks/`.
- Command and workflow docs stay kebab-case Markdown, for example `get-shit-done/commands/gsd/map-codebase.md` and `get-shit-done/get-shit-done/workflows/map-codebase.md`.

**Functions:**
- Runtime code uses camelCase for functions such as `buildNewProjectConfig()`, `ensureConfigFile()`, `getOpencodeGlobalDir()`, and `validateSyntax()`.
- Command-style functions are prefixed with `cmd` in library modules, e.g. `cmdConfigNewProject()` and `cmdConfigEnsureSection()` in `get-shit-done/get-shit-done/bin/lib/config.cjs`.
- Tests name helpers by intent rather than test doubles, such as `runGsdTools()`, `createTempProject()`, `readCodexConfig()`, and `assertUsesOnlyEol()`.

**Variables and Constants:**
- Local variables are camelCase; constants are `UPPER_SNAKE_CASE`, especially for file-system roots and marker strings like `HOOKS_DIR`, `DIST_DIR`, `GSD_CODEX_MARKER`, and `VALID_CONFIG_KEYS`.
- Feature flags and environment toggles are explicit booleans or string sentinels, for example `hasCodex`, `hasAll`, `hasErrors`, and `process.env.GSD_TEST_MODE = '1'`.
- Paths are usually assembled with `path.join(...)` and stored in descriptive names like `configPath`, `planningBase`, `globalDefaultsPath`, and `tmpDir`.

**Types and Data Shapes:**
- There is no TypeScript in the active package; shape contracts are implied through object literals, Sets, and documented helper return values.
- CLI/library code prefers normalized JSON-serializable objects for machine output, for example `{ created: true, path: '.planning/config.json' }` in `get-shit-done/get-shit-done/bin/lib/config.cjs`.
- Tests use inline fixture builders instead of formal factories when a shape is small, as seen in `commandEntry()` and `agentEntry()` in `get-shit-done/tests/hook-validation.test.cjs`.

## Code Style

**Formatting:**
- Source consistently uses 2-space indentation, semicolons, and single quotes in `.cjs` and `.js` files.
- `'use strict';` appears in many executable and test files, especially scripts that rely on Node CommonJS semantics, such as `get-shit-done/scripts/run-tests.cjs`.
- Long comments are common when preserving cross-runtime behavior or documenting regressions; examples in `get-shit-done/scripts/build-hooks.js` and `get-shit-done/bin/install.js` reference specific issue numbers and operational constraints.

**Tooling:**
- No ESLint or Prettier config is present in this repo snapshot; consistency is maintained manually.
- Syntax safety for hooks is enforced by code rather than a linter: `get-shit-done/scripts/build-hooks.js` compiles hook files with `vm.Script` before copying them to `get-shit-done/hooks/dist`.
- The package targets Node `>=20.0.0` via `get-shit-done/package.json`, and code leans on built-in Node modules instead of third-party runtime dependencies.

## Import Organization

**Order:**
1. Node built-ins first, typically grouped as destructured imports from `fs`, `path`, `os`, `child_process`, `node:test`, or `node:assert`.
2. Relative internal modules second, such as `require('./core.cjs')` or `require('../bin/install.js')`.
3. `package.json` or other local data files last when needed, for example `const pkg = require('../package.json');` in `get-shit-done/bin/install.js`.

**Grouping:**
- Imports are usually declared as one contiguous block at the top of the file, with minimal blank lines.
- Destructuring from built-ins is preferred when only a few functions are needed, such as `const { readdirSync } = require('fs');` in `get-shit-done/scripts/run-tests.cjs`.
- There are no path aliases; all internal references are relative paths.

## Error Handling

**Patterns:**
- CLI/library code usually fails fast with explicit process termination through shared helpers like `error(...)` and `output(...)` from `get-shit-done/get-shit-done/bin/lib/core.cjs`.
- Guard clauses are heavily used before file writes, parsing, or branching. `cmdConfigNewProject()` short-circuits if `config.json` already exists, and test helpers return structured `{ success, output, error }` objects instead of throwing.
- Hooks favor non-blocking behavior. Files like `get-shit-done/hooks/gsd-prompt-guard.js` wrap their whole stdin flow in `try/catch` and exit `0` on parse or runtime failure so editor/runtime integrations keep working.

**Boundary Choices:**
- User-facing commands surface actionable error text and stop the process for invalid inputs, malformed JSON, or failed filesystem operations.
- Background or defensive automation code often swallows failures intentionally, especially around optional config discovery, global defaults migration, hook parsing, and WSL detection fallbacks.
- Result objects often encode idempotency explicitly with keys like `created: false` and `reason: 'already_exists'` rather than treating repeated operations as errors.

## Logging and Output

**Framework:**
- There is no logging library; runtime messaging uses `console.log`, `console.warn`, `console.error`, `process.stdout.write(...)`, and shared CLI output helpers.
- Several scripts print colorized terminal output with ANSI escapes, especially `get-shit-done/bin/install.js` and `get-shit-done/scripts/build-hooks.js`.

**Patterns:**
- Human-facing installers/scripts use readable prose and status symbols.
- Machine-facing commands and hooks emit JSON strings so tests and wrappers can parse stable output.
- Tests generally capture stdout/stderr indirectly through `execSync`/`execFileSync` wrappers instead of patching console methods.

## Comments

**When to Comment:**
- Comments are used to explain portability constraints, regression history, and safety rationale rather than restating obvious code.
- Section dividers made from box-drawing characters are common in larger test files, for example `get-shit-done/tests/config.test.cjs` and `get-shit-done/tests/hook-validation.test.cjs`.
- Top-of-file header comments in tests usually state the subject under test and the user-facing requirement or bug class being guarded.

**Documentation Style:**
- JSDoc-style block comments are used sparingly for public-ish helpers and behavior notes, especially in test helpers and install utilities.
- Inline comments frequently explain why a fallback is intentionally silent or why a branch exists for a specific runtime, such as the WSL section in `get-shit-done/bin/install.js`.

## Function Design

**Structure:**
- Files commonly mix small focused helpers with a few orchestration functions. `get-shit-done/get-shit-done/bin/lib/config.cjs` is representative: validation helpers at the top, config builders in the middle, and `cmd*` entry points below.
- Pure helpers are extracted when they support many branches or tests, such as `isValidConfigKey()`, `validateKnownConfigKeyPath()`, and `buildNewProjectConfig()`.
- Scripts that act as entrypoints still keep most logic in named functions instead of deeply nested callbacks; `build()` in `get-shit-done/scripts/build-hooks.js` is a good example.

**Parameters and Returns:**
- More than two or three inputs are often grouped into objects or optional parameters, especially env overrides and raw-output flags.
- Return values are explicit and shape-stable. Helpers either return domain objects, booleans, or structured status payloads, avoiding implicit `undefined` except in early exits.
- Tests mirror this design by wrapping command execution and filesystem setup in reusable helpers rather than repeating subprocess boilerplate inline.

## Module Design

**Exports:**
- Library modules under `get-shit-done/get-shit-done/bin/lib/` use `module.exports` and are organized by concern (`config.cjs`, `core.cjs`, `roadmap.cjs`, `security.cjs`, etc.).
- Entrypoints such as `get-shit-done/bin/install.js` expose extra functions under test when `GSD_TEST_MODE` is enabled; tests import those functions directly instead of only testing through the CLI shell.
- Hooks are standalone executables, not imported modules; they communicate via stdin/stdout and are copied into `hooks/dist` for installation.

**Repository-Level Pattern:**
- The repository is not a traditional monorepo with shared tooling. The actual executable/tested package is `get-shit-done/`, while the top-level `wf-*.json` files are n8n workflow exports analyzed directly rather than compiled.
- Generated or mirrored content under `/Users/sasikumar/Documents/n8n/.claude/` and `/Users/sasikumar/Documents/n8n/.codex/` should be treated as runtime/config artifacts unless a task explicitly targets them.

## Workflow JSON Patterns

**n8n Files:**
- Root workflow files remain large exported JSON documents rather than hand-factored modules.
- Naming inside those files follows n8n node conventions and relies on embedded expressions instead of package-level helper imports.
- Because the workflow exports coexist with the Node package, codebase documentation and automation should distinguish between the root workflow JSON surface and the package source under `get-shit-done/`.

---

*Convention analysis: 2026-03-26*
