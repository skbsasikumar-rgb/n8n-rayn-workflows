---
status: testing
phase: 01-workflow-reliability
source: 01-01-SUMMARY.md, 01-02-SUMMARY.md, 01-03-SUMMARY.md, 01-04-SUMMARY.md, 01-05-SUMMARY.md
started: 2026-03-25T00:00:00Z
updated: 2026-03-25T00:00:00Z
---

## Current Test

number: 7
name: Hunter fallback triggers when Anymail finds no contact
expected: |
  Add a lead with company_name only, no email in NocoDB (status=pending). After Anymail returns no contact (or errors), the execution log shows the flow going through "IF No Contact → Hunter - Contact". Hunter should receive the company name as a query param (check the Hunter node output — meta.params.company should not be null).
awaiting: user response

## Tests

### 1. wf-latest imports without errors
expected: Import wf-latest.json into n8n. All nodes load cleanly — no red error indicators, no missing credential warnings on nodes other than Hunter/Anymail/Jina. Canvas shows all nodes connected with no orphaned nodes.
result: pass

### 2. 5 leads marked processing upfront
expected: Set 5 leads to status=pending in NocoDB. Trigger wf-latest. In the execution log, check "PATCH All Processing" — it should fire ONCE and mark all 5 leads as status=processing before the Loop Over Items begins. All 5 rows in NocoDB should show processing immediately after that single PATCH, before any enrichment starts.
result: pass

### 3. Full enrichment runs end-to-end for one lead
expected: Trigger wf-latest with at least one pending lead that has a known website (e.g. a GP clinic). The execution log should show the full chain: OpenRouter - Clean Name → Serper - Search → URL dedup → HTTP Status Check → URL Validate → Serper - Scrape → HIA Gate → Enrichment → Anymail → (Hunter if no contact) → Write Partial → Pain Logic → Email Gen → Write Final. The lead ends at status=enriched in NocoDB with vendor_pain and grant_eligibility populated.
result: issue
reported: "Write Final node ran (green checkmark) but NocoDB shows status=processing — fields only populated up to compliance_lead. vendor_pain, grant_eligibility, subject_line1-4, email_body1-4 all empty. Affected leads 2 and 5."
severity: major
fix: "Write Final had continueOnFail=true (hiding errors) and specifyBody=string (not supported). Fixed to specifyBody=json + JSON.stringify($json), continueOnFail=false. Prep Write Final now returns flat object instead of pre-stringified string."

### 4. Email fields written to NocoDB
expected: After a lead completes email gen, check its NocoDB row. All 8 fields should be populated: subject_line1, email_body1, subject_line2, email_body2, subject_line3, email_body3, subject_line4, email_body4. None should be empty. subject_line2 should contain "Up to 70% co-funded".
result: pass

### 5. No pending_verification status appears
expected: After a full run, no lead should end up with status=pending_verification. Final statuses should be: enriched, invalid email, no contact found, not HIA relevant, scrape failed, serper failed, clean failed, or url duplicate. The pending_verification status has been removed since No2Bounce was dropped.
result: pass

### 6. HIA Gate classifies correctly
expected: A GP clinic (e.g. "P Tan Family Medicine Clinic") gets classified as YES. A tech/SaaS vendor selling to healthcare gets VENDOR. A finance company or retailer gets NO and stops at "Status - not HIA relevant". Check the OpenRouter - HIA Gate node output — choices[0].message.content shows YES, VENDOR, or NO.
result: pass

### 7. Hunter fallback triggers when Anymail finds no contact
expected: Add a lead with company_name only, no email in NocoDB (status=pending). After Anymail returns no contact (or errors), the execution log shows the flow going through "IF No Contact → Prep Parent Company → OpenRouter - Parent Company → Parse Parent Company → Hunter - Contact". Hunter should receive the PARENT company name (not clinic name) as the company param.
result: issue
reported: "Hunter uses clean_company_name (clinic name like '1 Bishan Medical Clinic') but contacts live at parent company level ('1 Medical'). Also YSL Bedok Clinic & Surgery Pte Ltd should use 'Qualitas Health' from qualitashealth.com.sg."
severity: major
fix: "Added 3 new nodes: Prep Parent Company (prepares OpenRouter request with scraped website content), OpenRouter - Parent Company (extracts parent company/group name), Parse Parent Company (falls back to clean name if extraction fails). Hunter now uses parent_company instead of clean_company_name. Flow: IF No Contact → Prep Parent Company → OpenRouter - Parent Company → Parse Parent Company → Hunter - Contact. Also added parent_company field to Prep Partial Anymail, Prep Partial Hunter, and Write Partial & Pending."

### 8. Cloudflare scrape detection skips bad content
expected: For a lead where Jina returns a Cloudflare challenge page (content contains "Robot Challenge Screen" or "Checking the site connection"), the IF Scrape Failed node should route to "Status - scrape failed" rather than passing the useless content to HIA Gate. Check IF Scrape Failed — it should catch both length < 300 AND Cloudflare keyword matches.
result: [pending]

### 9. Cleanup resets stuck processing leads
expected: Manually set a NocoDB lead to status=processing and backdate its UpdatedAt to more than 10 minutes ago. Trigger wf-latest. In the execution log: "Cleanup Stuck Processing" computes cutoff → "GET Stuck Leads" returns that lead → "Build Bulk Reset" builds payload → "IF Has Stuck" routes to "PATCH Bulk Reset" → lead resets to status=pending → "Get Pending IDs" then picks it up as pending. Confirm cleanup_count > 0 in Build Bulk Reset output.
result: [pending]

### 10. wf-discovery runs end-to-end
expected: Import wf-discovery.json and trigger manually. The execution log shows: Serper Places → Parse Places → Dedup vs Discovery → Prep Discovery Bulk → Write Discovery → Paginate Read Leads → Dedup Against Leads → Write Leads. New company names appear in NocoDB discovery table and leads table with status=pending.
result: [pending]

## Summary

total: 10
passed: 5
issues: 2
pending: 3
skipped: 0
blocked: 0

## Gaps

- truth: "Hunter fallback uses parent company name (not clinic name) to search for contacts"
  status: failed
  reason: "User reported: Hunter uses clean_company_name (clinic name like '1 Bishan Medical Clinic') but contacts live at parent company level ('1 Medical')"
  severity: major
  test: 7
  artifacts:
    - path: "wf-latest.json"
      issue: "Hunter - Contact used $('OpenRouter - Clean Name') which returns clinic name, not parent company"
  missing:
    - "Parent company extraction from scraped website content before Hunter lookup"
  debug_session: ""
