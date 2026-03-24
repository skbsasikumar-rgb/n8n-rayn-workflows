---
status: partial
phase: 01-workflow-reliability
source: 01-01-SUMMARY.md, 01-02-SUMMARY.md, 01-03-SUMMARY.md, 01-04-SUMMARY.md, 01-05-SUMMARY.md
started: 2026-03-24T00:00:00Z
updated: 2026-03-24T00:00:00Z
---

## Current Test

## Current Test

[testing complete]

## Tests

### 1. wf-latest imports without errors
expected: Import wf-latest.json into n8n. All nodes load cleanly — no red error indicators, no missing credential warnings on nodes other than Hunter. Canvas shows all nodes connected.
result: pass

### 2. Pending lead gets picked up
expected: Set one NocoDB lead to status=pending (or add a new row with only company_name and status=pending). Manually trigger wf-latest. In the execution log, the lead's status changes to processing immediately, then progresses through the enrichment chain.
result: pass

### 3. All 5 leads processed in one run
expected: Set 5 leads to status=pending in NocoDB. Trigger wf-latest once. The execution log shows all 5 leads going through the Loop Over Items chain — not just the first one stopping. At the end, all 5 have a non-pending status in NocoDB.
result: pass

### 4. Jina Reader fetches website content
expected: After a lead passes Serper Search and URL validation, the "Serper - Scrape" node (now Jina Reader) output shows a `data` field containing readable website text — not empty, and longer than 300 characters. This should work for clinic sites that previously showed "scrape failed".
result: issue
reported: "Jina returned a Cloudflare bot challenge page (Title: Robot Challenge Screen, CAPTCHA warning) for goodhealthmedical.com.sg — data is present and >300 chars so scrape check passes, but content is useless for HIA classification"
severity: minor

### 5. HIA Gate classifies correctly
expected: A GP clinic (e.g., "P Tan Family Medicine Clinic") gets classified as YES. A finance company or retailer gets NO. Check the OpenRouter - HIA Gate node output in the execution log — the `choices[0].message.content` field shows YES, VENDOR, or NO.
result: pass

### 6. Hunter fallback triggers for name-only leads
expected: Add a lead with company_name filled but no email in NocoDB (status=pending). After Anymail returns no contact, the Hunter - Contact node should execute. Visible in execution log as the flow going through "IF No Contact → Hunter - Contact" rather than stopping at "no contact found".
result: pass
note: "Two side issues found — (a) Anymail threw connection aborted error; continueOnFail handled it gracefully and flow reached Hunter. (b) Hunter - Contact sends company=null — company name not being passed as a query param, reducing search accuracy."

### 7. No2Bounce runs after contact found
expected: After Anymail or Hunter finds a contact with an email, the execution log shows: "Write Partial & Pending" → "No2Bounce - Submit" → "Wait - No2Bounce" (15s pause) → "No2Bounce - Check" → "Parse No2Bounce" → "Write No2Bounce Status". The lead's final NocoDB status is enriched, invalid email, or pending_verification — NOT stuck at pending_verification permanently.
result: pass
note: "Parse No2Bounce was reading wrong fields ($json.data instead of $json directly, wrong field names). Fixed inline — both Parse No2Bounce and Parse N2B Retry updated to use overallStatus/percent/Deliverable/Undeliverable fields matching actual API response."

### 8. pending_verification leads retried on next run
expected: If a lead ends up at status=pending_verification, the next scheduled trigger run (3 minutes later) should pick it up via the "Get Pending Verification" path at the bottom of the workflow. In the execution log, "Get Pending Verification" returns that lead, and it goes through No2Bounce Submit Retry → Wait → Check → Write Verification Status.
result: pass
note: "Covered by test 7 fix — retry path logic confirmed working after Parse No2Bounce response shape fix."

### 9. Cleanup resets stuck processing leads
expected: Manually update a NocoDB lead to status=processing and set its UpdatedAt to more than 10 minutes ago. Trigger wf-latest. The "Cleanup Stuck Processing" node should reset it back to pending before the new run fetches pending leads. Confirm in execution log that cleanup_count > 0 or the lead reappears as pending.
result: blocked
blocked_by: prior-phase
reason: "Cleanup Stuck Processing is a no-op stub — returns cleanup_count: 0 without querying or patching NocoDB. Needs to be rebuilt as HTTP Request nodes (GET stuck rows → PATCH back to pending). Not testable until implemented."

### 10. wf-discovery runs end-to-end without HTTP errors
expected: Import wf-discovery.json and trigger it manually (with .slice(0,5) limiting to 5 Serper calls). The execution log shows Serper Places → Parse Places → Dedup vs Discovery → Prep Discovery Bulk → Write Discovery → Paginate Read Leads → Dedup Against Leads → Write Leads. New company names appear in NocoDB discovery table with status=pending in the leads table.
result: pass

## Summary

total: 10
passed: 8
issues: 3
pending: 0
blocked: 1
skipped: 0
blocked: 0

## Gaps

- truth: "Jina Reader returns readable website content for HIA classification"
  status: failed
  reason: "User reported: Jina returned a Cloudflare bot challenge page (Title: Robot Challenge Screen, CAPTCHA warning) for goodhealthmedical.com.sg — data is present and >300 chars so scrape check passes, but content is useless for HIA classification"
  severity: minor
  test: 4
  artifacts: []
  missing: []

- truth: "Anymail Finder returns a contact or clean empty response"
  status: failed
  reason: "User reported: Anymail threw connection aborted error (NodeApiError: The connection was aborted, perhaps the server is offline). continueOnFail handled it and flow reached Hunter, but Anymail is unreliable."
  severity: minor
  test: 6
  artifacts: []
  missing: []

- truth: "Hunter - Contact passes company name to narrow search results"
  status: failed
  reason: "User reported: Hunter - Contact node shows company: null in params — company name not being passed as query parameter, reducing accuracy of contact search"
  severity: minor
  test: 6
  artifacts: []
  missing: []

- truth: "Cleanup Stuck Processing resets leads stuck at processing for >10 minutes back to pending"
  status: failed
  reason: "Node is a no-op stub — returns cleanup_count: 0 without querying or patching NocoDB. Needs to be rebuilt as HTTP Request node chain: GET stuck rows → IF any → PATCH back to pending."
  severity: major
  test: 9
  artifacts: []
  missing: []

- truth: "No2Bounce verifies email and writes enriched or invalid email status"
  status: fixed_inline
  reason: "Parse No2Bounce was using wrong field names ($json.data, totalEmails, deliverability). Actual API response uses $json directly with overallStatus/percent/Deliverable/Undeliverable fields. Fixed in wf-latest.json during UAT."
  severity: major
  test: 7
