# Working Instructions

These instructions govern the Rayn Secure n8n workflow rebuild.

## Four Principles

### 1. Think Before Coding

Do not assume silently.

- State assumptions before changing workflow logic.
- Present multiple interpretations when a requirement can mean more than one thing.
- Push back when a simpler or safer approach is available.
- Stop and ask when the next step is genuinely unclear.

### 2. Simplicity First

Build the minimum workflow that solves the current goal.

- No speculative nodes.
- No abstractions for single-use logic.
- No configuration until the workflow needs it.
- No defensive branches for scenarios that cannot happen in the current contract.
- If a node can be removed without breaking the success criteria, remove it.

### 3. Surgical Changes

Touch only what is required.

- Worker changes must not alter discovery unless explicitly requested.
- Discovery changes must not alter the worker contract unless explicitly requested.
- Do not refactor adjacent nodes while fixing one node.
- Remove only unused fields, nodes, or docs created by the current change.
- Mention unrelated cleanup opportunities instead of doing them.

### 4. Goal-Driven Execution

Every task needs a verification loop.

- Define what success means before editing.
- Test with concrete rows or sample payloads.
- Compare expected and actual output.
- Keep looping until the stated check passes or the blocker is explicit.

## External Tools Rule

If a repo, library, SaaS tool, MCP server, or online service could materially simplify the workflow, propose it first and wait for approval before integrating it.

## Rerun Discipline

Use the same cleanup sequence before every meaningful rerun.

- Disable the live workflow before resetting rows.
- Stop or wait out any in-flight executions before triggering new work.
- Clear old n8n execution history for the workflow being tested.
- Reset only the target NocoDB rows for the rerun.
- Clear stale workflow output fields before rerunning.
- Add a fresh batch marker or run label whenever possible.
- Restart `primary` only when executions are stuck or workflow state is inconsistent.
- Do not restart NocoDB just to clear stale worker state.
- Do not scale concurrency until the small verification batch passes cleanly.

## Closeout Rule

After each completed patch, use this exact closeout only when it is true:

- `Implemented, deployed live, committed, and pushed.`

If any part is not true, state the exact remaining gap instead of using the full closeout line.

## Workflow Rebuild Order

1. Worker: accept company name and produce enrichment output.
2. Discovery: create lead candidates and pass only `company_name` plus minimal metadata to worker.
3. Orchestrator: dispatch work at controlled concurrency after worker behaviour is stable.

## Current Scope

The current rebuild is worker-first. Do not recreate discovery or orchestrator workflows until the worker contract and tests are stable.
