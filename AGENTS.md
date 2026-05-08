<INSTRUCTIONS>
@/Users/sasikumar/.codex/RTK.md

# Context Mode default routing

Use Context Mode for all work it can safely handle.

Default to `ctx_batch_execute` for multi-step inspection, command batches, and
combined gather/search flows.

Default to `ctx_execute` for single commands, command output over 20 lines,
data processing, counting, filtering, comparing, parsing, transformation, and
any command where raw output could flood context.

Default to `ctx_execute_file` for reading files to analyze, summarize, count,
filter, compare, or extract facts. Program the analysis and print only the
answer.

Default to `ctx_search` for session continuity, prior decisions, indexed
outputs, compaction recovery, and follow-up questions over previously indexed
content.

Default to `ctx_fetch_and_index` or Context Mode fetch execution for web/API
fetches; do not use raw `curl`/`wget` in direct shell.

Use direct shell only for actions Context Mode cannot perform cleanly: git
writes (`git add`, `git commit`, `git push`), file mutations, process control,
interactive commands, long-running sessions, and tool operations that need a
real terminal. When direct shell is unavoidable, follow RTK rules and keep
output short.

Use `apply_patch` for manual file edits.
</INSTRUCTIONS>
