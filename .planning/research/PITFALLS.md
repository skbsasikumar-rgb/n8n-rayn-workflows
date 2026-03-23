# Domain Pitfalls: RAYN Sales Engine

**Domain:** n8n multi-channel sales automation (email, LinkedIn, WhatsApp) on Railway self-hosted
**Researched:** 2026-03-23
**Confidence:** MEDIUM-HIGH (n8n/Railway specifics from community + official docs; LinkedIn/WhatsApp policy from official sources; email deliverability from official sender guidelines)

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, account bans, or unrecoverable reputation damage.

---

### Pitfall 1: Concurrent Scheduled Triggers Grabbing the Same Lead

**What goes wrong:** Two instances of the 3-minute Phase 1 trigger fire before the previous one finishes. Both read the same `pending` lead rows from NocoDB before either writes a status update. Both process the same leads in parallel — double API spend, duplicate enrichment, corrupted state.

**Why it happens:** n8n's scheduler fires a new execution on schedule regardless of whether the previous execution is still running. This is the documented default behavior, not a bug. With a 3-minute interval and enrichment taking 90+ seconds, overlap is near-certain under normal load.

**Consequences:** Same lead processed twice (wasted API credits on Serper, OpenRouter, Anymail, Hunter, No2Bounce), NocoDB rows with conflicting field values, email validation credits consumed on already-validated leads.

**Prevention:**
- Set `EXECUTIONS_CONCURRENCY_PRODUCTION_LIMIT=1` (or `N8N_CONCURRENCY=1`) per workflow — forces sequential execution. On Railway, add this env var to the n8n service.
- Add a workflow-level timeout equal to the trigger interval (180 seconds for 3-minute trigger) — if execution exceeds this, n8n cancels it rather than running in parallel.
- Implement a status lock: before reading leads, write a `processing` status to a NocoDB lock row; at end of workflow, release it. Check lock state as first step — abort if locked.
- The `processing` status approach is already partially needed for the documented race condition bug in PROJECT.md.

**Detection:** Check n8n Executions list — if you see two Phase 1 executions with overlapping timestamps, the race condition is active.

**Phase relevance:** v1 (current bug fix milestone); critical before any volume increase.

---

### Pitfall 2: NocoDB API Row Cap Silently Misses Leads

**What goes wrong:** NocoDB's self-hosted API defaults: `DB_QUERY_LIMIT_DEFAULT=25`, `DB_QUERY_LIMIT_MAX=100`. The n8n NocoDB node's "Get All" operation respects these server-side caps. A `GET` request for 10,000 rows silently returns only 25-100. As the leads table grows past 100 rows, enrichment workflows stop seeing new leads without any error.

**Why it happens:** NocoDB's default query limit configuration is conservative. The n8n NocoDB node does not implement transparent pagination by default — it makes a single request and returns what the server sends.

**Consequences:** Lead pipeline appears healthy (no errors) but stops processing new leads once discovered row count exceeds 100. Entire enrichment system silently stalls.

**Prevention:**
- Set `DB_QUERY_LIMIT_MAX=10000` and `DB_QUERY_LIMIT_DEFAULT=1000` in NocoDB Railway service environment variables.
- In n8n workflows, always use the HTTP Request node to call NocoDB REST API directly with explicit `limit` and `offset` parameters rather than the NocoDB node for bulk reads — gives full control over pagination.
- Implement pagination loop: fetch until response count < page size.
- The 10,000-row hardcoded `GET` limit in the workflow is already flagged as a known bug in PROJECT.md — fix this in v1.

**Detection:** Count NocoDB table rows in UI vs. count returned by n8n `Get All` — discrepancy confirms the cap is active.

**Phase relevance:** v1 (known bug, must fix before table exceeds 100 enriched leads).

---

### Pitfall 3: n8n Execution Data Payload Exceeds 16 MB Limit

**What goes wrong:** n8n stores full execution data (all node inputs/outputs) in its database. When website scraping via Serper returns large HTML bodies, or when storing 4 generated email variants per lead, accumulated execution data can breach the 16 MB default limit. The execution fails with "Existing execution data is too large" and the lead is left in an indeterminate state.

**Why it happens:** n8n default: `N8N_PAYLOAD_SIZE_MAX=16` (MB). Every node's input and output is retained in the execution record. A single Serper scrape response can be 200-500 KB; multiply by several nodes and the full execution approaches the limit.

**Consequences:** Execution hard-fails mid-run, lead status not updated, API calls already consumed with no output written to NocoDB.

**Prevention:**
- Set `N8N_PAYLOAD_SIZE_MAX=128` in the n8n Railway service environment variables to raise the limit.
- Add a Code node after Serper scrape responses to trim HTML to the relevant text content before passing downstream — reduces per-node payload from 500 KB to ~5 KB.
- Do not store raw HTML in NocoDB fields; store only extracted, structured data.
- Use the "Execute Sub-Workflow" pattern for the Phase 2 enrichment chain — sub-workflows have isolated execution data budgets.

**Detection:** Check Railway n8n logs for "Existing execution data is too large" or execution failures immediately after scrape-heavy nodes.

**Phase relevance:** v1-v2; becomes acute when enabling full 5-lead batch processing (each lead adds scrape payload).

---

### Pitfall 4: n8n Code Node Hard-Stops at 300-Second Task Runner Timeout

**What goes wrong:** n8n's task runner (which executes Code nodes and AI Agent nodes) has a hard 300-second timeout per task. The No2Bounce polling loop — which waits for email verification results — is currently implemented with multiple sequential poll attempts in Phase 2. If total polling time exceeds 300 seconds, n8n kills the task and the execution fails silently or leaves leads stuck in `validating` state.

**Why it happens:** `N8N_RUNNERS_TASK_TIMEOUT` defaults to 300 seconds. This is separate from workflow-level execution timeout. AI and Code nodes are subject to this limit.

**Consequences:** Email verification never completes, lead stuck in `validating`, poll credits consumed without result. Already partially identified as the "Poll 4 forces verdict" bug in PROJECT.md.

**Prevention:**
- Set `N8N_RUNNERS_TASK_TIMEOUT=600` in n8n Railway env vars to extend task runner timeout.
- Redesign No2Bounce polling as a separate scheduled workflow that checks `validating` leads every N minutes rather than a blocking loop — removes the timeout risk entirely and is more resilient.
- Use the n8n Wait node between poll attempts instead of a Code node sleep loop — Wait node pauses execution and resumes, not subject to the 300-second task timeout.

**Detection:** Leads stuck in `validating` status for >10 minutes; n8n execution logs showing "Task execution timed out after 300 seconds."

**Phase relevance:** v1 (current bug fix — No2Bounce polling); critical for any long-running verification chain.

---

### Pitfall 5: LinkedIn Account Permanent Ban From n8n-Triggered Cloud Automation

**What goes wrong:** Any n8n workflow that directly calls LinkedIn APIs or automates browser actions via a cloud runner will be flagged and banned. LinkedIn's ML system detects: precise timing intervals, cloud/proxy IP addresses, message template similarity, geographic inconsistencies. First offense: feature restriction. Second: verification lock. Third: permanent ban — less than 15% recovery success rate. Apollo.io and Seamless.ai were officially banned by LinkedIn in 2025, signaling aggressive enforcement.

**Why it happens:** LinkedIn's User Agreement explicitly prohibits bots or automated access methods. Cloud-based automation from non-residential IPs and perfectly-timed request intervals are primary detection signals. n8n running on Railway uses Railway infrastructure IPs, not residential IPs.

**Consequences:** Permanent loss of LinkedIn account associated with sales outreach. All LinkedIn-sourced pipeline destroyed. Potential IP-level blacklisting affecting new account creation.

**Prevention:**
- Never call LinkedIn's internal APIs directly from n8n HTTP Request nodes.
- If LinkedIn outreach is required (v3), use only LinkedIn-approved automation platforms (Sales Navigator API, official LinkedIn Marketing API, or dedicated tools with proven ToS compliance like Dux-Soup cloud edition).
- Enforce safe daily limits: 10-20 connection requests per day, 50-100 messages per day, never on exact intervals — introduce ±20-40% random delay jitter.
- Warm up new LinkedIn accounts for 14 days (manual-only) before any automation. Ban probability drops from 23% to 5-10% with proper warmup.
- Keep automation volume 30-40% below LinkedIn's published limits.
- Never use a primary company LinkedIn account for automation — use a dedicated outreach account.

**Detection:** LinkedIn "suspicious activity" warning emails; reduced connection acceptance rates; "restricted" label appearing on account.

**Phase relevance:** v3 (LinkedIn automation); must be addressed in architecture before any v3 planning.

---

### Pitfall 6: WhatsApp Business Account Permanent Ban From Unsolicited Outreach

**What goes wrong:** WhatsApp (Meta) prohibits messaging contacts who have not provided explicit opt-in consent. Cold outreach to scraped Singapore healthcare contacts via WhatsApp will trigger immediate account ban. Meta's enforcement in 2025 monitors: high delivery failure rates (purchased lists have 15-40% invalid numbers), block/report rates, and account age vs. message volume ratio. A new account sending bulk cold messages is banned within hours.

**Why it happens:** WhatsApp Business Policy requires explicit opt-in before any outreach message. This is not a gray area — it is explicitly prohibited and actively enforced. Starting March 2025, Meta increased automated detection of non-compliant behavior.

**Consequences:** Permanent WhatsApp Business account ban. Meta may also restrict associated Facebook Business Manager assets. Phone number cannot be re-registered for WhatsApp for an extended period.

**Prevention:**
- WhatsApp outreach (v4) is only viable as a follow-up channel for leads who have already engaged via email or inbound — never as cold outreach.
- Use only the official WhatsApp Business Platform (Cloud API via Meta) — never unofficial automation libraries.
- Implement opt-in collection before any WhatsApp messaging (e.g., a landing page with WhatsApp consent checkbox).
- Keep spam complaint rate under 2%; if users block or report messages, deliverability is throttled before ban.
- Start with approved Message Templates only (pre-approved by Meta for marketing/utility use cases).

**Detection:** WhatsApp "Quality Rating" dropping to Red in Business Manager; sudden drop in message delivery rates; account suspension notice.

**Phase relevance:** v4 (WhatsApp); architecture must include opt-in collection before v4 builds.

---

## Moderate Pitfalls

Mistakes that cause degraded performance, wasted spend, or slow recovery.

---

### Pitfall 7: Burning the Primary Domain With Cold Email Campaigns

**What goes wrong:** Sending cold outreach from `@primarydomain.com` (the company's main business domain). One campaign with high bounce or spam complaint rates permanently damages the domain's sender reputation, causing all future email (including transactional and internal) to land in spam. Domain reputation damage takes months to recover and may require abandonment.

**Prevention:**
- Use separate cold email domains (e.g., `rayn-hia.com`, `tryrayn.com`) for all Instantly campaigns — never the primary domain.
- Set up SPF, DKIM, and DMARC on all cold email domains before first send.
- Warm up each new domain: start at 5-10 emails/day, ramp to 30/day over 3-4 weeks using Instantly's warmup pool.
- Hard limits: 30 cold emails + 10 warmup emails per inbox per day maximum. Google's spam complaint threshold is 0.1% — exceeding it triggers throttling.
- Bounce rate must stay under 2%; No2Bounce validation directly supports this.

**Phase relevance:** v2 (Instantly push integration).

---

### Pitfall 8: OpenRouter Rate Limit Hits Causing Silent Lead Failures

**What goes wrong:** OpenRouter's paid rate limits are dynamically tied to account balance — "$1 = 1 RPS." As the balance depletes, concurrent request capacity drops. An n8n workflow running 5 leads in parallel (each requiring 2-3 LLM calls) can easily hit rate limits if the account balance is low. 429 errors in n8n fail the node silently if error handling is not configured.

**Prevention:**
- Add explicit error handling on all OpenRouter HTTP Request nodes: catch 429 responses, implement exponential backoff (1s → 2s → 5s → 13s) with ±20% jitter.
- Set up OpenRouter balance alerts — do not let balance drop below $10 (sub-$10 drops concurrent capacity significantly on free tier models).
- Process leads sequentially within a workflow run rather than in parallel batches if rate limit errors emerge.
- Separate minimax (cheap classification) from claude-sonnet (expensive generation) into different execution windows to spread load.

**Phase relevance:** v1 (fixing batch processing to 5 leads/run increases LLM call volume 5x).

---

### Pitfall 9: Serper Credit Exhaustion From Retry Storms

**What goes wrong:** A Serper Places API call fails (network error, 5xx). n8n retries the HTTP Request node automatically. If the retry fires during a Serper outage, the workflow retries multiple times per execution plus across concurrent executions — burning credits on requests that will all fail.

**Prevention:**
- Configure Serper HTTP Request nodes with a maximum of 2 retries (not the default 5) and a 30-second delay between retries.
- Add a dead-letter pattern: if Serper returns 5xx twice, mark the discovery run as `api_error` and skip rather than retrying indefinitely.
- Monitor Serper credit balance weekly — the 589 combo weekly coverage consumes credits rapidly.
- Cache Serper results: if a `(area, category)` combo was searched within the last 7 days, skip it. NocoDB can store a `last_searched_at` field per combo.

**Phase relevance:** v1 and ongoing; especially critical as discovery runs scale.

---

### Pitfall 10: Hunter.io Rate Limit on Fallback Triggering Too Aggressively

**What goes wrong:** Hunter's Email Finder endpoint is limited to 15 requests/second and 500/minute. If Anymail returns empty results and Hunter fallback triggers for every lead (which the current AND-condition bug prevents but the OR-condition fix will enable), Hunter can be overwhelmed during batch runs. Hunter also has monthly credit quotas that can deplete faster than expected.

**Prevention:**
- Fix the AND→OR fallback condition (v1 bug fix), but add a 2-second delay between Hunter requests.
- Track Hunter monthly credit consumption in NocoDB meta table — alert when 80% consumed.
- Use Hunter as last resort only: try Anymail first, then Hunter only if Anymail returns zero results (not partial results) — keep Hunter for high-value HIA:YES leads only.

**Phase relevance:** v1 (fallback logic fix).

---

### Pitfall 11: NocoDB SQLite Concurrent Write Locks Under Multi-Workflow Load

**What goes wrong:** NocoDB's default storage engine on Railway is SQLite. SQLite uses a single-writer model — only one write operation can occur at a time. With Phase 1 (3-minute trigger) and Phase 2 (20-minute trigger) both attempting NocoDB writes concurrently, SQLite write lock contention causes `SQLITE_BUSY` errors, failed row updates, and silent data loss.

**Why it happens:** Two n8n workflows running simultaneously hit NocoDB at the same second. SQLite serializes writes — one succeeds, the other returns BUSY. NocoDB does not retry writes automatically.

**Prevention:**
- Migrate NocoDB to PostgreSQL backend on Railway (Railway supports managed Postgres). This eliminates the single-writer bottleneck entirely.
- Until migration: stagger Phase 1 and Phase 2 trigger times so they do not overlap at common intervals (e.g., if Phase 2 is every 20 min at :00/:20/:40, schedule Phase 1 offset by 90 seconds).
- Add error handling on NocoDB write nodes to catch 5xx responses and retry with exponential backoff.

**Detection:** n8n execution logs showing NocoDB HTTP 500 errors on write operations; leads stuck in intermediate states unexpectedly.

**Phase relevance:** v1-v2; critical when volume increases to full 5-lead batch processing.

---

## Minor Pitfalls

---

### Pitfall 12: Railway Sleep/Restart Dropping In-Flight Executions

**What goes wrong:** Railway free/hobby tier services can sleep after inactivity or restart during deployments. An in-flight n8n execution (e.g., a 90-second enrichment run) is killed mid-workflow when Railway restarts the container. The lead is left in `processing` status with no NocoDB update.

**Prevention:**
- Set a `processing_started_at` timestamp when marking leads as processing. A recovery workflow (run every hour) resets leads stuck in `processing` for >10 minutes back to `pending`.
- Use Railway's Pro tier to avoid sleep behavior if uptime SLA matters.
- Design workflows to be idempotent: if re-run on a partially-processed lead, detect what was completed (by checking NocoDB fields) and resume from the last successful step.

**Phase relevance:** All phases; design for Railway restarts from v1 onward.

---

### Pitfall 13: No2Bounce Polling Lead Stuck in `verification_timeout`

**What goes wrong:** No2Bounce's async verification API can return `processing` status for 5-15+ minutes on difficult domains (catch-all, greylisted servers). The current Poll 4 behavior forces a verdict after the 4th attempt — this is already identified as a known bug in PROJECT.md. If leads are incorrectly marked `invalid` due to timeout, valid contacts are discarded.

**Prevention:**
- Implement the `verification_timeout` status as a separate retry queue — already planned in v1 bug fixes.
- A scheduled hourly workflow retries all `verification_timeout` leads by re-calling No2Bounce rather than forcing a verdict.
- Set a final fallback: after 3 timeout attempts across 3 separate hourly retries, mark the email as `unverifiable` and include it in Instantly with lowered send priority rather than discarding it.

**Phase relevance:** v1 (known bug fix).

---

### Pitfall 14: Sending More Than 30 Cold Emails/Day Per Inbox Before Warmup Completes

**What goes wrong:** Pushing Instantly to send volume before inbox warmup is complete (minimum 2-4 weeks) triggers Gmail's automated spam detection. Even with SPF/DKIM/DMARC correctly configured, volume spikes on a new domain cause Google's reputation system to sandbox all mail from that domain. Recovery requires stopping sends entirely for 4-6 weeks.

**Prevention:**
- Enforce Instantly's Campaign Slow Ramp setting on all new inboxes — start at 5/day, ramp by 5/day weekly.
- Never send more than 30 cold emails + 10 warmup emails per inbox per day, regardless of lead queue depth.
- Monitor spam complaint rate in Google Postmaster Tools (free) — alert if above 0.05%.
- Build a buffer: enrich leads faster than you send (queue depth of 500+ before enabling Instantly) so volume pressure never forces oversending.

**Phase relevance:** v2 (Instantly push).

---

## Phase-Specific Warnings

| Phase/Milestone | Likely Pitfall | Mitigation |
|-----------------|---------------|------------|
| v1: Fix batch to 5 leads/run | OpenRouter rate limits 5x worse; NocoDB SQLite write contention | Add LLM backoff; stagger Phase 1/2 triggers |
| v1: Fix race condition | Two Phase 1 runs still grabbing same leads | Implement processing lock row in NocoDB before reading leads |
| v1: Fix NocoDB row cap | Table silently capped at 100 rows | Set DB_QUERY_LIMIT_MAX=10000 in NocoDB env; use HTTP pagination |
| v1: Fix No2Bounce polling | Lead stuck in verification timeout → Poll 4 forces wrong verdict | verification_timeout status + hourly retry workflow |
| v2: Instantly push | Cold email domain burned by premature high volume | Separate cold email domain, 2-4 week warmup, 30/day max |
| v3: LinkedIn automation | Account banned within 90 days (23% base rate) | Official APIs only, residential proxy, 14-day warmup, 10-20 req/day |
| v4: WhatsApp outreach | Immediate ban for cold outreach to scraped list | Opt-in collection first; WhatsApp Cloud API only; follow-up channel only |
| Any phase: scale discovery | Serper credits exhausted by retry storms | 2-retry max, dead-letter skip, cache per (area,category) combo |
| Any phase: Railway deploy | In-flight execution killed on restart | processing_started_at + hourly recovery workflow |

---

## Sources

- n8n Memory Errors Docs: https://docs.n8n.io/hosting/scaling/memory-errors/
- n8n Execution Payload Too Large (community): https://community.n8n.io/t/existing-execution-data-is-too-large/256344
- n8n Task Runner 300s Timeout (GitHub): https://github.com/n8n-io/n8n/issues/14865
- n8n Concurrency + Railway: https://station.railway.com/questions/how-to-increase-n8n-concurrent-execution-1c5f5249
- n8n Schedule Trigger Duplicate Prevention: https://n8nplaybook.com/post/2025/07/how-to-prevent-concurrent-n8n-workflows/
- n8n Execution Timeout Configuration: https://docs.n8n.io/hosting/configuration/configuration-examples/execution-timeout/
- NocoDB Row Limit Bug (GitHub): https://github.com/nocodb/nocodb/issues/7761
- NocoDB API Query Limit Config: https://github.com/nocodb/nocodb/discussions/900
- NocoDB SQLite vs Postgres (community): https://community.nocodb.com/t/self-hosted-sqllite-postgres/1733
- LinkedIn Automation Ban Risk 2026: https://growleads.io/blog/linkedin-automation-ban-risk-2026-safe-use/
- LinkedIn ToS (official): https://www.linkedin.com/help/linkedin/answer/a1341387
- LinkedIn Safety Limits 2025: https://blog.closelyhq.com/linkedin-automation-daily-limits-the-2025-safety-guidelines/
- WhatsApp Business Policy (official): https://business.whatsapp.com/policy
- WhatsApp Ban Causes 2025: https://chakrahq.com/article/whatsapp-business-account-restricted-fix/
- WhatsApp Marketing Compliance 2025: https://sendwo.com/blog/whatsapp-marketing-compliance-checklist/
- Cold Email Sending Limits 2025: https://www.topo.io/blog/safe-sending-limits-cold-email
- Google Email Sender Guidelines (official): https://support.google.com/a/answer/81126
- Instantly Deliverability 2025: https://instantly.ai/blog/how-to-achieve-90-cold-email-deliverability-in-2025/
- Cold Email Domain Strategy 2025: https://www.mailreach.co/blog/cold-email-domain-why-you-need-one-and-how-to-set-it-up-right-practical-guide-2025
- Hunter Rate Limits (official): https://help.hunter.io/en/articles/1971004-is-there-a-request-per-second-limit
- OpenRouter Rate Limits (official): https://openrouter.ai/docs/api/reference/limits
- Outlook New High-Volume Sender Requirements 2025: https://techcommunity.microsoft.com/blog/microsoftdefenderforoffice365blog/strengthening-email-ecosystem-outlook-s-new-requirements-for-high-volume-senders/4399730
