# Operations Log

This is the operator-facing workflow log. Keep it short, current, and tied to live row evidence.

Historical/internal GSD logs:

- `.planning/phases/01-workflow-reliability/01-DISCUSSION-LOG.md`
- `.planning/phases/01-workflow-reliability/01-VERIFICATION.md`
- `.planning/phases/01-workflow-reliability/01-CONTEXT.md`

## Current State

Date: 2026-04-24

Active workflow files:

- `wf-discovery.json`: discovery seed generation
- `wf-latest.json`: dispatch orchestrator
- `wf-worker.json`: enrichment worker

Current local git state when this log was created:

- `wf-worker.json` already had uncommitted workflow changes from URL selection and dedupe work.
- Root `Dockerfile` was untracked and left untouched.

## Latest Rerun Findings

| Row | Company | Status | Homepage | Notes |
| --- | --- | --- | --- | --- |
| `250` | Osler Health International | `partial` | `https://osler-group.com/` | Corrected from bad `osler-health.com`; scrape fallback used because page evaluation navigation interrupted. |
| `256` | GoodDoctors Medical Clinic | `partial` | `http://gooddoctors.com.sg/` | Correct homepage root. |
| `263` | Sree Narayana Mission | `partial` | `https://sreenarayanamission.org/` | Correct homepage root; avoids donation-platform evidence. |
| `257` | Frontier Medical | `failed` | `https://frontierhealthcare.com.sg/` | Older stale scrape timeout, not part of the latest three-row fix. |

## Recent Fixes

- Homepage roots are normalized to clean registrable roots.
- Known bad third-party sources such as donation platforms and mall directories are blocked.
- Known homepage hints were added for GoodDoctors, Sree Narayana Mission, and Osler.
- Canonical-domain dedupe writes `duplicate_of_id` and skips enrichment.
- Scrape failures after URL validation now produce `partial` fallback output instead of a hard failed writeback.

## Open Follow-Ups

| Priority | Item | Why |
| --- | --- | --- |
| P1 | Harden scraper navigation handling for Osler-style pages. | Current result is correct but relies on fallback due to `Page.evaluate` navigation failure. |
| P1 | Add a dashboard query for stale `processing`, `failed`, and unexpected `pending`. | Full-table reruns need fast quality checks. |
| P1 | Formalize first-20 and full-table acceptance reports. | Rerun success should be judged by final fields, not execution starts. |
| P2 | Promote homepage regression anchors into fixture tests. | Prevents reintroducing directory/donation URLs. |
| P2 | Add discovery ICP criteria for cyber and data security certification fit. | Discovery should find better leads before enrichment starts. |

## Logging Rules

Record only durable facts:

- workflow file changed
- live workflow deployed or not deployed
- rows rerun
- final row status and key fields
- failures that need follow-up
- schema or credential changes

Do not paste API keys, tokens, full raw HTML, or full execution payloads into this log.
