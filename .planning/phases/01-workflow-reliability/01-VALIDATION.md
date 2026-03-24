---
phase: 1
slug: workflow-reliability
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Manual execution validation via n8n execution log + NocoDB UI inspection |
| **Config file** | None — n8n workflows tested by running them in the n8n editor with test data |
| **Quick run command** | Manually trigger wf-latest in n8n UI → check execution log |
| **Full suite command** | Run wf-latest + wf-discovery back-to-back; inspect NocoDB leads table |
| **Estimated runtime** | ~5 minutes per full run |

---

## Sampling Rate

- **After every task commit:** Manually trigger the specific changed workflow in n8n editor
- **After every plan wave:** Full wf-latest run with 5 pending leads, check NocoDB state matches success criteria
- **Before `/gsd:verify-work`:** All 5 success criteria from phase definition confirmed in NocoDB + n8n execution logs
- **Max feedback latency:** ~5 minutes

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | INFRA-01 | smoke | `railway variables --service n8n` | N/A | ⬜ pending |
| 1-01-02 | 01 | 0 | INFRA-02 | smoke | `railway variables --service nocodb` | N/A | ⬜ pending |
| 1-02-01 | 02 | 1 | FIX-01 | manual | Trigger two runs within 10s, compare execution logs | N/A | ⬜ pending |
| 1-03-01 | 03 | 1 | FIX-02 | manual | Trigger with 5+ pending leads, check execution log | N/A | ⬜ pending |
| 1-03-02 | 03 | 1 | FIX-03 | smoke | Trigger full run, inspect execution log for 429 errors | N/A | ⬜ pending |
| 1-04-01 | 04 | 2 | FIX-04 | manual | Seed lead with name only, trigger run, check Hunter node executed | N/A | ⬜ pending |
| 1-04-02 | 04 | 2 | FIX-05 | manual | Submit email with slow No2Bounce response, check verification_timeout in NocoDB | N/A | ⬜ pending |
| 1-05-01 | 05 | 2 | FIX-06 | manual | Insert 150 pending leads, trigger run, verify all visible | N/A | ⬜ pending |
| 1-05-02 | 05 | 2 | FIX-07 | manual | Confirm Read Discovery/Leads pagination returns count matching NocoDB UI total | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Verify `$http.request()` availability in Code nodes on current Railway n8n version — if unavailable, fallback to chained HTTP Request nodes for pagination
- [ ] Confirm NocoDB `UpdatedAt` / `updated_at` field name casing from live table schema — needed for stuck-processing cleanup filter
- [ ] Confirm current n8n version on Railway — needed to validate `N8N_CONCURRENCY_PRODUCTION_LIMIT` env var name (vs legacy alternatives)

*No test files to create — this is an n8n-only environment; all testing is manual execution validation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Two overlapping runs process different leads | FIX-01 | n8n has no API for concurrent execution output comparison | Trigger two runs within 10s, compare lead IDs in both execution logs — no overlap |
| Single run produces exactly 5 completions | FIX-02 | Requires seeded test data in NocoDB | Ensure 5+ pending leads in NocoDB, trigger run, count PATCH success calls in execution log |
| Hunter called when name exists but email empty | FIX-04 | Requires seeded lead data | Insert lead with name only (no email), trigger run, verify Hunter - Contact node executed |
| verification_timeout written after slow No2Bounce | FIX-05 | Requires real or mocked slow No2Bounce response | Submit known-slow email, wait for 6 retry exhaustion, check NocoDB row status |
| wf-latest sees all pending rows > 100 | FIX-06 | Requires large dataset in NocoDB | Insert 150+ pending rows, trigger run, verify pagination loop output count matches NocoDB pending count |
| wf-discovery reads all rows via pagination | FIX-07 | Requires large dataset | Confirm Read Discovery/Leads node counts match NocoDB table row counts |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (field name casing, $http.request availability, n8n version)
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
