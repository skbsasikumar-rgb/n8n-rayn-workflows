# Operations Log

This is the operator-facing workflow log. Keep it short, current, and tied to live row evidence.

Historical/internal GSD logs:

- `.planning/phases/01-workflow-reliability/01-DISCUSSION-LOG.md`
- `.planning/phases/01-workflow-reliability/01-VERIFICATION.md`
- `.planning/phases/01-workflow-reliability/01-CONTEXT.md`

## Current State

Date: 2026-04-25

Active workflow files:

- `wf-discovery.json`: discovery seed generation
- `wf-latest.json`: dispatch orchestrator
- `wf-worker.json`: enrichment worker

Current local git state when this log was created:

- `wf-worker.json` has live worker changes for URL selection, dedupe, and false-positive blocking.
- Root `Dockerfile` pins n8n to `2.12.3` after the Railway service was accidentally running `1.123.37`.

## Latest Rerun Findings

| Row | Company | Status | Homepage | Notes |
| --- | --- | --- | --- | --- |
| `250` | Osler Health International | `partial` | `https://osler-group.com/` | Corrected from bad `osler-health.com`; scrape fallback used because page evaluation navigation interrupted. |
| `256` | GoodDoctors Medical Clinic | `partial` | `http://gooddoctors.com.sg/` | Correct homepage root. |
| `263` | Sree Narayana Mission | `partial` | `https://sreenarayanamission.org/` | Correct homepage root; avoids donation-platform evidence. |
| `257` | Frontier Medical | `partial` | `https://frontierhealthcare.com.sg/` | Correct group homepage and parent/root output. |
| `251` | GP | `partial` | blank | Ambiguous short name; false-positive domains blocked and row falls back to no official homepage. |
| `253` | 57 Medical Clinic | `partial` | `https://57medical.sg/` | Correct official clinic group homepage. |
| `260` | C3 Family Clinic | `partial` | blank | `enablingguide.sg` false positive blocked; no official homepage verified. |
| `262` | Baby Allergy Prevention By Eco Pacific Pte Ltd | `partial` | `https://babyallergyprevention.com.sg/` | Correct Singapore homepage for Baby Allergy Prevention by Eco Pacific. |
| `237` | Binjai Medical Clinic | `partial` | `https://binjaimedical.com/` | Correct official clinic homepage. |
| `244` | Providence Medical Centre Pte Ltd | `partial` | blank | No official homepage found; directory results remain rejected. |
| `231` | Bukit Timah Family Clinic & Surgery | `partial` | blank | No official homepage found; directory/Facebook-style evidence remains rejected. |

## Recent Fixes

- Homepage roots are normalized to clean registrable roots.
- Known bad third-party sources such as donation platforms and mall directories are blocked.
- Known homepage hints were added for GoodDoctors, Sree Narayana Mission, and Osler.
- Canonical-domain dedupe writes `duplicate_of_id` and skips enrichment.
- Scrape failures after URL validation now produce `partial` fallback output instead of a hard failed writeback.
- Added official-homepage hints for Frontier Medical, Minmed, Parkway Shenton, The Clinic Group, Advantage Medical, Healthway Medical, and Geylang Polyclinic.
- Added deterministic root-name and parent-company rules for those domains, including Osler's `osler-group.com` root.
- Strengthened the company-facts prompt so outlet, brand, group, and network parent relationships require official evidence.
- Restored Railway Primary to n8n `2.12.3`, set `N8N_PROXY_HOPS=1`, activated the worker webhook, and cleared old worker executions before the full-table rerun.
- Blocked late false positives from `tiktok.com`, `enablingguide.sg`, `singaporegp.sg`, `tickets.gp`, and `findglocal.com`; added a short-name guard for ambiguous names such as `GP`.
- Added precise homepage hints for Baby Allergy Prevention, 57 Medical, and Binjai Medical Clinic; reran only rows `262`, `253`, and `237`.

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
