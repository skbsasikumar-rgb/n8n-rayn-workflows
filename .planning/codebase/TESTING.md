# Testing Patterns

**Analysis Date:** 2026-03-26

## Test Framework

**Runner:**
- The active automated test suite is in `/Users/sasikumar/Documents/n8n/get-shit-done/tests` and uses Node's built-in test runner via `require('node:test')`.
- `/Users/sasikumar/Documents/n8n/get-shit-done/scripts/run-tests.cjs` discovers `*.test.cjs` files and runs them with `node --test`, so there is no Jest or Vitest config in this repo snapshot.

**Assertion Library:**
- Assertions come from Node built-ins: both `require('node:assert')` and `require('node:assert/strict')` are used across the suite.
- Common assertion styles are `assert.ok(...)`, `assert.strictEqual(...)`, `assert.deepStrictEqual(...)`, and `assert.throws(...)`.

**Run Commands:**
```bash
cd /Users/sasikumar/Documents/n8n/get-shit-done && npm test
cd /Users/sasikumar/Documents/n8n/get-shit-done && npm run test:coverage
cd /Users/sasikumar/Documents/n8n/get-shit-done && node --test tests/config.test.cjs
```

## Test File Organization

**Location:**
- Package tests live in a dedicated tree at `/Users/sasikumar/Documents/n8n/get-shit-done/tests`.
- There are no automated tests for the root n8n workflow exports `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json`; those remain integration/manual assets.

**Naming:**
- Files follow `<subject>.test.cjs`, for example `config.test.cjs`, `commands.test.cjs`, `codex-config.test.cjs`, `security-scan.test.cjs`, and `workspace.test.cjs`.
- Helpers shared by many suites sit in non-test support files like `tests/helpers.cjs`.

**Structure:**
```text
/Users/sasikumar/Documents/n8n/get-shit-done/tests/
  helpers.cjs
  commands.test.cjs
  config.test.cjs
  core.test.cjs
  codex-config.test.cjs
  hook-validation.test.cjs
  security-scan.test.cjs
  workspace.test.cjs
  ...
```

## Test Structure

**Suite Organization:**
```javascript
describe('config-ensure-section command', () => {
  let tmpDir;

  beforeEach(() => {
    tmpDir = createTempProject();
  });

  afterEach(() => {
    cleanup(tmpDir);
  });

  test('creates config.json with expected structure and types', () => {
    const result = runGsdTools('config-ensure-section', tmpDir);
    assert.ok(result.success, `Command failed: ${result.error}`);
  });
});
```

**Patterns:**
- `describe()` groups behavior by command or helper; nested `describe()` blocks are common in larger suites like `config.test.cjs` and `codex-config.test.cjs`.
- `beforeEach()`/`afterEach()` are preferred for temp directory lifecycle, environment restoration, and git repo setup/teardown.
- Tests follow a pragmatic arrange/act/assert style, but not always with explicit section comments.

## Mocking

**Approach:**
- The suite favors real filesystem and subprocess interactions over deep mocking. Many tests create temp projects with `fs.mkdtempSync(...)`, run real CLI entrypoints, and inspect generated files.
- Command tests typically execute the actual CLI through `runGsdTools()` in `/Users/sasikumar/Documents/n8n/get-shit-done/tests/helpers.cjs`, which shells into `get-shit-done/bin/gsd-tools.cjs`.
- Install/config tests often import implementation functions directly from `/Users/sasikumar/Documents/n8n/get-shit-done/bin/install.js` after enabling `process.env.GSD_TEST_MODE = '1'`.

**What Gets Mocked or Sandboxed:**
- Environment variables are temporarily overridden to control runtime-specific branches, for example `CODEX_HOME`, `COPILOT_CONFIG_DIR`, `ANTIGRAVITY_CONFIG_DIR`, `BRAVE_API_KEY`, and `GSD_TEST_MODE`.
- HOME-like directories are sandboxed into temp folders so tests do not depend on a developer's real machine state, as documented in `config.test.cjs`.
- Output capture is usually done by subprocess execution rather than spy libraries. Comments in `commands.test.cjs` note targeted output interception when command helpers write directly to fd `1`.

**What Usually Is Not Mocked:**
- Internal parsing and config-merging logic is commonly exercised against real files on disk.
- Git behavior is tested with actual temporary repositories in suites like `workspace.test.cjs`, `commands.test.cjs`, and helper functions such as `createTempGitProject()`.
- Shell scripts in `/Users/sasikumar/Documents/n8n/get-shit-done/scripts/*.sh` are invoked directly by `security-scan.test.cjs` using `execFileSync(...)`.

## Fixtures and Factories

**Patterns:**
- Shared test setup lives in helper functions rather than a dedicated fixtures directory.
- Common builders include `createTempDir()`, `createTempProject()`, `createTempGitProject()`, `cleanup()`, and `runGsdTools()` in `tests/helpers.cjs`.
- Small suite-local fixture builders are inlined when they improve readability, such as `commandEntry()` and `agentEntry()` in `hook-validation.test.cjs`.

**Test Data Shape:**
- Markdown frontmatter, config JSON, hook objects, and runtime config files are usually created inline with `fs.writeFileSync(...)`.
- For parser and history tests, realistic document fixtures are embedded as template literals, as seen in `commands.test.cjs`.
- Security scan tests generate temporary markdown or shell-script inputs on demand rather than relying on checked-in fixtures.

## Coverage

**Tooling and Thresholds:**
- Coverage is collected with `c8`, configured in `/Users/sasikumar/Documents/n8n/get-shit-done/package.json`.
- `npm run test:coverage` enforces a `70%` line threshold with `--check-coverage --lines 70`.

**Scope:**
- Coverage includes only `/Users/sasikumar/Documents/n8n/get-shit-done/get-shit-done/bin/lib/*.cjs`.
- Tests themselves are excluded, and the coverage run uses `--all` so uncovered library files still count.
- Top-level assets like the root `wf-*.json` workflow exports, Markdown templates, and most installer surface code are outside the explicit `c8` include pattern.

## Test Types

**CLI / Integration-Style Tests:**
- A large portion of the suite is black-box or gray-box CLI testing: execute a command, inspect stdout/stderr, and verify file-system side effects.
- Examples include `config.test.cjs`, `commands.test.cjs`, `workspace.test.cjs`, and `milestone-summary.test.cjs`.

**Library-Focused Unit Tests:**
- Some suites import pure or semi-pure helpers directly from implementation files for narrower checks, especially `hook-validation.test.cjs`, `codex-config.test.cjs`, and `security.test.cjs`.
- These are still stateful at times because the codebase prefers real paths and env variables over injection-heavy architecture.

**Script and Platform Tests:**
- `security-scan.test.cjs` validates executable shell scripts directly and conditionally skips behavioral checks on Windows.
- Runtime adapter suites such as `copilot-install.test.cjs`, `codex-config.test.cjs`, `cursor-conversion.test.cjs`, and `windsurf-conversion.test.cjs` verify cross-tooling config generation and merge behavior.

**Untested Surface:**
- The root workflow exports `/Users/sasikumar/Documents/n8n/wf-discovery.json` and `/Users/sasikumar/Documents/n8n/wf-latest.json` do not have adjacent automated tests in this repository.

## Common Patterns

**Async and Subprocess Testing:**
```javascript
test('runs scanner and captures status', () => {
  const result = execFileSync(scriptPath, args, {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 10000,
  });
});
```
- Even when the code under test is synchronous, subprocess-based tests are common because many behaviors live behind CLI boundaries.

**Error Testing:**
```javascript
test('rejects unknown config keys', () => {
  const result = runGsdTools('config-set workflow.nyquist_validation_enabled false', tmpDir);
  assert.strictEqual(result.success, false);
  assert.ok(result.error.includes('Unknown config key'));
});

test('throws on invalid shell arg', () => {
  assert.throws(() => validateShellArg('', 'test'));
});
```
- Error assertions usually inspect exact status booleans, exit codes, or substrings in stderr rather than snapshotting full messages.

**Platform Guards:**
- Platform-specific tests explicitly branch on `process.platform`; `security-scan.test.cjs` skips bash behavior on Windows, and install/config suites preserve and restore OS-specific env state carefully.

**Cleanup Discipline:**
- Temp directories are aggressively removed with `fs.rmSync(..., { recursive: true, force: true })`.
- Suites that mutate cwd or environment restore them in `finally`, `afterEach()`, or `after()` hooks.

**Snapshot Testing:**
- No Jest/Vitest snapshot usage is present in the current suite.

---

*Testing analysis: 2026-03-26*
