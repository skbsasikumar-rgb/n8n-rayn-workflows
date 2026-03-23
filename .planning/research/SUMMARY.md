# Research Summary: RAYN Sales Engine

**Project:** RAYN Sales Engine
**Domain:** n8n-based automated B2B cold outreach — Singapore healthcare/HIA compliance niche
**Researched:** 2026-03-23
**Confidence:** MEDIUM-HIGH

---

## Executive Summary

The RAYN Sales Engine is a solo-operator outreach pipeline built entirely in n8n, and research confirms this is the right architectural choice. The existing core — Google Places discovery, LLM classification, contact enrichment, email generation — is structurally sound. What it lacks is operational reliability: six specific bugs prevent it from running continuously at volume without human intervention. All six are fixable with established n8n patterns (loop nodes, status locks, polling loops, pagination) that are well-documented and carry HIGH confidence. Fixing these is not optional groundwork — it is a hard prerequisite for the Instantly push in v2, because without the race condition fix, duplicate leads will be pushed to campaigns, and without the verification timeout fix, leads with unknown email validity will be sent.

The recommended outreach stack is fully resolved by research: Instantly.ai for email (existing, community node maintained by Instantly), HeyReach for LinkedIn (community node, cloud-based, lower ban risk than browser-extension alternatives), and Meta WhatsApp Cloud API direct for WhatsApp (built-in n8n node, Singapore data residency available). All three have native n8n integration. The main constraint is LinkedIn, where the risk of account restriction is structural — not a tooling problem — and requires a 14-day manual warmup plus strict daily limits (10-20 connection requests/day) regardless of which tool is used.

The two non-negotiable compliance constraints for v4 planning: WhatsApp cannot be used for cold outreach under any architecture. Meta's policy and enforcement are explicit, and a Singapore healthcare list of scraped contacts has no opt-in consent. WhatsApp is viable only as a follow-up channel for leads who have already responded. Additionally, Singapore's PDPA requires DNC register checks before any WhatsApp or phone contact, and the Spam Control Act requires a visible unsubscribe link in every cold email — both must be built into the sequence templates before v2 launches.

---

## Key Findings

### Resolved: Tool Choices

Research resolves all outstanding tool decisions for v2-v4. No further tool evaluation is needed.

**Core stack by milestone:**

| Milestone | Tool | n8n Integration | Monthly Cost |
|-----------|------|-----------------|--------------|
| v1: Bug fixes | Existing stack (no changes) | — | — |
| v2: Email sequences | Instantly.ai API v2 | `n8n-nodes-instantly` (community node, Instantly-maintained) | $77.60/mo annual (Hypergrowth) — already in stack |
| v3: LinkedIn outreach | HeyReach | `n8n-nodes-heyreach` (community node) | $79/mo (1 sender) |
| v4: WhatsApp follow-up | Meta WhatsApp Cloud API | Built-in `n8n-nodes-base.whatsapp` | Free API + per-template Meta fee |

**Key rationale:**
- HeyReach over Dux-Soup: cloud infrastructure with dedicated IPs per sender vs. browser extension; no HMAC auth complexity; better for unattended automation
- Direct Meta Cloud API over 360dialog: Singapore data residency available (APAC region); no extra cost; no third-party data sharing risk under PDPA
- Instantly over Smartlead: community node maintained by Instantly-ai org; already in project stack

**Critical pre-requisites before install:**
- Instantly Hypergrowth plan ($77.60/mo annual) is the minimum plan with API access — verify current plan
- HeyReach requires a dedicated LinkedIn account (not the primary company account) — ban recovery rate is below 15% on primary accounts
- WhatsApp WABA setup requires a verified Meta Business account; template approval takes 24-48 hours

---

### v1 Bug Fixes: Specific Implementation Guidance

Research provides exact implementation patterns for each of the six v1 bugs. Priority order from research cross-referencing FEATURES.md and PITFALLS.md:

**1. Race condition / status lock (CRITICAL — do this first)**

The fix has two layers. Primary: implement a pessimistic status lock by writing `status = "processing"` to the NocoDB row immediately after fetching the ID, before any enrichment call. Secondary: set `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` in Railway environment variables — this queues all production executions sequentially and eliminates the overlap window entirely without application-level complexity. The env var fix is a fast one-line change; the status lock is the robust solution. Implement both.

Flow after fix: `GET WHERE status="pending" LIMIT 5` → `UPDATE status="processing"` → `GET full record` → enrichment chain.

**2. Batch processing — `.first()` to Loop Over Items (HIGH impact, low effort)**

Replace the `.first()` call with a `Loop Over Items` node (Split in Batches, `n8n-nodes-base.splitInBatches`) with Batch Size: 1. This is a node replacement, not a code change. The enrichment chain's final node loops back to the Loop Over Items input; the "done" output connects to end/status update. Do not use a Code node for this unless the loop node proves insufficient.

**Warning:** Fixing batch processing increases LLM call volume 5x. Before deploying this fix, add exponential backoff (1s → 2s → 5s → 13s) on all OpenRouter HTTP Request nodes to handle 429 responses, and verify OpenRouter account balance is above $10.

**3. Contact fallback OR logic (1-line change in IF node)**

In the IF node after Anymail, change the "Combine Conditions" operator from AND to OR. That is the entire fix. After this change, Hunter is called whenever name is empty OR email is empty (not only when both are empty). Add a 2-second delay between Hunter requests after this fix — the OR condition will trigger Hunter more frequently and Hunter's rate limit is 500 requests/minute.

**4. No2Bounce verification timeout (architectural change — most complex v1 fix)**

Two issues here that research identifies as distinct:

- The Poll 4 "force verdict" bug: replace the forced verdict with a `verification_timeout` status write and exit.
- The underlying timeout risk: the current polling loop runs inside a Code node or sequential flow subject to n8n's 300-second task runner timeout (`N8N_RUNNERS_TASK_TIMEOUT`). If polling takes longer, the execution is killed.

Fix: redesign No2Bounce polling as a separate scheduled workflow (run every 15-30 minutes) that queries NocoDB for `WHERE email_status = "verification_timeout"` and re-polls No2Bounce for those rows. This removes the blocking loop from the main enrichment chain entirely. As a secondary measure, set `N8N_RUNNERS_TASK_TIMEOUT=600` in Railway env vars.

Use a Wait node (not Code node sleep) between poll attempts — Wait node pauses execution and resumes without consuming the 300-second task runner budget.

After 3 hourly retries still returning `processing`, mark as `unverifiable` and include in Instantly with lower send priority rather than discarding.

**5. NocoDB pagination (time-bomb — must fix before table exceeds 100 rows)**

NocoDB's default server-side cap is 25-100 rows. Two actions required:
- Set `DB_QUERY_LIMIT_MAX=10000` and `DB_QUERY_LIMIT_DEFAULT=1000` in NocoDB Railway service environment variables (immediate fix).
- Implement pagination loop using NocoDB v2 API `pageInfo.isLastPage` as termination condition (durable fix). Use the n8n NocoDB node's "Return All" option if available in the installed version; otherwise use a Code node with `$http.request` in a while loop on `pageInfo.isLastPage`.

Note: the ARCHITECTURE.md pagination Code node uses `$http.request` — verify this is available in your n8n version. The HTTP Request node inside a pagination loop may be more reliable.

**6. Discovery in-batch dedup (lower priority — enrichment dedup catches most cases)**

Hash company URL at discovery time. Check in-memory before inserting to NocoDB batch. This is a Code node change in `wf-discovery`. Fix last — enrichment pipeline already deduplicates by URL, so the impact of this bug is duplicate rows in NocoDB that get deduplicated before outreach, not duplicate outreach.

---

### Architecture: Component Boundaries and Railway Env Vars

Research identifies several Railway environment variables that must be set before v1 goes to production at volume:

```
# n8n Railway service
N8N_CONCURRENCY_PRODUCTION_LIMIT=1   # eliminates race condition window
N8N_PAYLOAD_SIZE_MAX=128             # prevents 16 MB execution data cap from killing scrape runs
N8N_RUNNERS_TASK_TIMEOUT=600         # prevents task runner killing No2Bounce poll loops

# NocoDB Railway service
DB_QUERY_LIMIT_MAX=10000             # prevents silent row cap
DB_QUERY_LIMIT_DEFAULT=1000          # increases default fetch size
```

These are infrastructure changes, not workflow changes. They should be applied once and do not require workflow redeployment.

**Component map after v1 fixes:**

| Component | Responsibility | Notes |
|-----------|---------------|-------|
| Schedule Trigger (3 min) | Fires Phase 1 | Blocked by concurrency limit if previous run active |
| Status Lock Step | Writes `processing` before enrichment | Prevents dual-processing |
| Loop Over Items (Batch 5) | Iterates pending leads | Replaces `.first()` |
| Enrichment Chain | HTTP check → HIA → scrape → contact → email | Per-lead; 60-90s per lead |
| Polling Loop (Wait-based) | No2Bounce re-queue | Separate scheduled workflow, not inline |
| Error Branch | Catches failures, writes `failed` + error_message | On all enrichment nodes |
| Stuck-Processing Recovery | Resets `processing` rows older than 10 min to `pending` | Hourly scheduled workflow |
| Pagination Code | Fetches all pending leads across NocoDB pages | Activated when table > 1000 rows |

**SQLite write contention warning:** NocoDB on Railway defaults to SQLite, which has a single-writer model. With Phase 1 (3-min trigger) and Phase 2 (20-min trigger) running concurrently, SQLite write locks (`SQLITE_BUSY`) can corrupt lead state. Mitigation: stagger Phase 1 and Phase 2 trigger times by 90 seconds (e.g., Phase 2 at :00/:20/:40, Phase 1 offset to :01:30/:04:30). Long-term fix: migrate NocoDB to PostgreSQL on Railway before v2 launch.

---

### Critical Pitfalls by Phase

**For v1 (current work):**
1. **Payload size cap kills scrape runs.** Set `N8N_PAYLOAD_SIZE_MAX=128`. Add a Code node after Serper scrape to trim HTML to extracted text before passing downstream (reduces 500 KB node payload to ~5 KB).
2. **Task runner 300s timeout kills No2Bounce polling.** Redesign polling as a separate workflow using Wait nodes, not inline Code node loops.
3. **Batch fix multiplies OpenRouter rate limit exposure 5x.** Add backoff before deploying the batch fix.

**For v2 (Instantly push):**
4. **Never send from the primary domain.** Use a dedicated cold email domain (e.g., `rayn-hia.com`). Set up SPF/DKIM/DMARC before first send. Start at 5 emails/day, ramp over 3-4 weeks. Hard limit: 30 cold emails + 10 warmup per inbox per day.
5. **Lead queue depth before enabling Instantly.** Build a buffer of 500+ enriched leads before enabling sends — this prevents throughput pressure from forcing over-sending on a fresh domain.

**For v3 (LinkedIn):**
6. **LinkedIn account ban is structural, not tool-dependent.** 23% base ban rate on new accounts. Mandatory: 14-day manual warmup on dedicated account before any automation; randomised delays (not fixed intervals); 10-15 connection requests/day maximum; never reuse identical message text across requests. HeyReach's cloud IP architecture helps but does not eliminate the risk.

**For v4 (WhatsApp):**
7. **Cold outreach to scraped contacts will trigger an immediate ban.** Meta's enforcement as of March 2025 is aggressive. WhatsApp is only viable as a post-response nurture channel. Architecture must include opt-in collection (consent checkbox on landing page or reply-based consent trigger) before v4 is built.

**Ongoing:**
8. **Serper retry storms.** Set max 2 retries on all Serper HTTP Request nodes. Cache per (area, category) combo in NocoDB with `last_searched_at` to avoid re-querying the same combo within 7 days.

---

### Contradictions and Surprises Between Research Files

**Contradiction 1: LinkedIn tool recommendation**

FEATURES.md recommends Salesflow, Lemlist, or Phantombuster for LinkedIn safety. STACK.md recommends HeyReach as Tier 1. These are not contradictory in outcome (all three are cloud-based tools), but STACK.md is more specific and more current — HeyReach has a native n8n community node that Salesflow lacks, and PITFALLS.md confirms Phantombuster has a "340% increase in LinkedIn restrictions reported" for cloud tools with fixed-interval patterns. **Resolution: HeyReach is the correct choice. FEATURES.md guidance on safe limits (10-20 connection requests/day, randomised delays) remains valid regardless of tool.**

**Contradiction 2: Hunter fallback scope**

FEATURES.md says fix AND→OR so Hunter is called "if ANY required field is empty." PITFALLS.md says after fixing this, "use Hunter as last resort only: try Anymail first, then Hunter only if Anymail returns zero results — keep Hunter for high-value HIA:YES leads only." These conflict. **Resolution: implement OR logic (the correct fix), but add a qualifier: only trigger Hunter fallback for leads where `hia_classification = "YES"`. For VENDOR and unclassified leads, the partial Anymail result (name or email, not both) is sufficient to proceed. This controls Hunter credit burn.**

**Surprise: NocoDB row cap is more severe than documented**

PROJECT.md describes the row cap bug as a 10,000-row issue. PITFALLS.md reveals NocoDB's default server-side `DB_QUERY_LIMIT_MAX` is 100 rows — not 10,000. The bug is not theoretical at 10,000 rows; it may already be active if the leads table has grown past 100 rows. **This is the most urgent v1 fix to validate. Check actual row count vs. count returned by n8n Get All today.**

**Surprise: WhatsApp v4 is architecturally broken as planned**

PROJECT.md lists WhatsApp as a planned v4 milestone without scope qualification. Both STACK.md and PITFALLS.md independently conclude that cold WhatsApp outreach to scraped healthcare contacts is impossible under Meta's policy and Singapore PDPA — it will result in permanent account ban, not degraded performance. **The v4 scope must be reframed from "WhatsApp outreach" to "WhatsApp follow-up for engaged leads with opt-in consent." This is a fundamental scope change, not an implementation detail.**

---

## Implications for Roadmap

### Phase 1: Workflow Reliability (v1 bug fixes)

**Rationale:** All six bugs are active in production. The race condition and row cap bugs in particular mean the engine may already be producing incorrect output. Fixing these is not setup work — it is recovering the system to its intended behaviour. None of the v2-v4 milestones are safe to build on the current broken foundation.

**Delivers:** A continuously-running, self-recovering enrichment pipeline that processes 5 leads per run, correctly locks rows, paginates across the full NocoDB table, and handles verification timeouts without manual intervention.

**Implementation order within phase:**
1. Railway env vars first (no workflow changes, instant effect): `N8N_CONCURRENCY_PRODUCTION_LIMIT=1`, `N8N_PAYLOAD_SIZE_MAX=128`, `N8N_RUNNERS_TASK_TIMEOUT=600`, `DB_QUERY_LIMIT_MAX=10000`, `DB_QUERY_LIMIT_DEFAULT=1000`
2. NocoDB row cap validation: check actual row count vs. n8n Get All output today
3. Race condition status lock (highest-severity workflow change)
4. Batch processing fix — but only after OpenRouter backoff is added
5. Contact fallback OR logic (with Hunter rate limiting)
6. No2Bounce polling redesign as separate workflow
7. Discovery in-batch dedup (lowest priority)

**Pitfalls to avoid:** OpenRouter rate limit surge from batch fix (add backoff first); SQLite write contention from concurrent Phase 1/Phase 2 (stagger trigger times).

**Research flag:** Standard patterns, no further research needed. All fixes have HIGH-confidence implementation patterns in ARCHITECTURE.md.

---

### Phase 2: Email Outreach via Instantly (v2)

**Rationale:** Once the pipeline reliably produces enriched leads with validated emails, the v2 push to Instantly is the primary value delivery — every lead gets a personalised sequence sent automatically. This phase converts the enrichment engine into an actual outreach engine.

**Delivers:** Automated 5-email sequences (21-day cadence) sent to enriched leads via Instantly, with webhook-driven status sync back to NocoDB for replies, bounces, and unsubscribes.

**Sequence structure (from FEATURES.md):**
- Email 1 (Day 0): HIA compliance pain point from website scrape
- Email 2 (Day 3): Regulatory deadline / enforcement risk angle
- Email 3 (Day 7): Case study / outcome
- Email 4 (Day 14): Soft bump
- Email 5 (Day 21): Breakup email (static template)

**Key implementation decisions:**
- Install `n8n-nodes-instantly` community node; use `skip_if_in_campaign: true` on Add Lead operation to prevent duplicate push
- Use the 4 pre-generated email variants in NocoDB as Email 1-4; Email 5 is a static template
- Trigger sequences only on time-based steps and replies — never on opens (Apple Mail Privacy Protection causes 30-40% false positive opens)
- Webhook events to handle: `reply_received`, `email_bounced`, `lead_unsubscribed`, `auto_reply_received`
- Send window: Tuesday-Thursday, 9:00-11:00 AM SGT

**Pre-launch gate:** 500+ enriched leads in queue; cold email domain set up with SPF/DKIM/DMARC; Instantly warmup running for 2-4 weeks; Singapore Spam Control Act unsubscribe link present in all templates.

**Pitfalls to avoid:** Sending from primary domain (permanent reputation damage); launching before inbox warmup completes; omitting Singapore Spam Control Act unsubscribe link.

**Research flag:** No further research needed. Instantly node operations are well-documented. Sequence structure is resolved.

---

### Phase 3: LinkedIn Outreach via HeyReach (v3)

**Rationale:** Adds a parallel channel for HIA:YES leads who do not respond to email. LinkedIn outreach in the Singapore healthcare compliance niche has a different signal-to-noise ratio — direct connection requests from a named professional with a specific compliance context have higher engagement rates than cold email for this persona.

**Delivers:** 5-touchpoint LinkedIn sequence (14-day cadence) running in parallel to email for HIA:YES classified leads, with connection/reply status synced to NocoDB via HeyReach webhooks.

**Sequence structure (from FEATURES.md):**
- Day 1 + 3: Profile view (creates awareness, prompts reciprocal view)
- Day 4: Connection request (no pitch, compliance context only)
- Day 7: First message if connected
- Day 10: Follow-up message
- Day 14: InMail if not connected

**Key implementation decisions:**
- Install `n8n-nodes-heyreach` community node; $79/mo Starter plan (1 sender)
- Dedicated LinkedIn account required — not the primary company account
- 14-day manual warmup on the dedicated account before activating HeyReach
- Message text must be personalised per lead — LinkedIn detects templated sequences; use NocoDB fields (company name, HIA classification, scraped website content) to generate per-lead variants
- n8n orchestrates campaign timing; HeyReach handles the actual LinkedIn interaction

**Pitfalls to avoid:** LinkedIn account ban from cloud automation (use HeyReach, not direct HTTP calls to LinkedIn); identical message text across requests; exceeding 10-15 connection requests/day.

**Research flag:** LinkedIn safety limits and HeyReach operations are well-documented. However, the per-lead message personalisation at LinkedIn step level may need a research-phase pass on HeyReach's dynamic variable support and whether LLM-generated connection request notes can be injected at the API level.

---

### Phase 4: WhatsApp Nurture Channel (v4 — SCOPE CHANGE REQUIRED)

**Rationale:** WhatsApp is viable only for leads who have already engaged (replied to email or LinkedIn). This is a nurture/conversion channel, not a discovery channel. The scope must be reframed before planning — "WhatsApp outreach" implies cold contact, which will result in permanent account ban.

**Revised scope:** WhatsApp follow-up sequences for leads who have replied positively to email or LinkedIn, using only Meta-approved Message Templates and requiring explicit consent before first message.

**Delivers:** WhatsApp nurture sequences for warm leads, with conversational follow-up capability via "Send and Wait for Response" n8n node operation.

**Key implementation decisions:**
- Built-in `n8n-nodes-base.whatsapp` node — no installation needed
- WABA setup required: Meta Business account verification + WhatsApp Business Account; 24-48 hours for template approval
- Singapore APAC data residency: configure during WABA setup to keep personal data at rest in Singapore (required for PDPA compliance)
- Consent collection before first message: opt-in must be documented; a reply to email does not constitute WhatsApp consent — a separate explicit trigger is required
- DNC register check required before any WhatsApp contact: Singapore DNC covers phone numbers used for WhatsApp

**Pitfalls to avoid:** Cold outreach to scraped contacts (immediate ban); using unofficial WhatsApp APIs (permanent ban + number blacklisting); 360dialog routing data through EU (PDPA cross-border transfer issue — use direct Meta Cloud API instead).

**Research flag:** Needs a focused research pass on consent collection mechanics (what triggers constitute valid PDPA consent for WhatsApp), DNC register API integration for phone number screening, and Meta template approval process for healthcare/compliance messaging.

---

### Phase Ordering Rationale

- v1 before v2: The race condition alone is sufficient to send duplicate leads to Instantly campaigns. Building v2 on the current engine is building on a broken foundation.
- v2 before v3: Email deliverability and sender reputation must be established before adding a second channel. HeyReach's effectiveness depends on LinkedIn sequences complementing an existing email thread — the email sequence is the primary channel.
- v3 before v4: WhatsApp requires a prior relationship (reply to email or LinkedIn). v3 provides the LinkedIn engagement signal; v4 consumes it.
- PDPA compliance posture established in v2 (unsubscribe links, opt-out processing) carries forward to v3 and v4 — the compliance infrastructure compounds across phases.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack (v1 tools) | HIGH | Existing stack is verified and operational |
| Stack (v2 Instantly) | HIGH | Official community node, Instantly-maintained |
| Stack (v3 HeyReach) | MEDIUM-HIGH | Native n8n node; LinkedIn ToS landscape volatile |
| Stack (v4 WhatsApp) | HIGH | Built-in node; Meta direct is the only compliant path |
| Features (v1 bugs) | HIGH | Bugs are documented and patterns are verified |
| Features (v2 sequence) | HIGH | Based on Instantly official docs and 2025-2026 benchmarks |
| Features (v3 LinkedIn) | MEDIUM | Safety limits from tool vendors; LinkedIn enforcement patterns shift |
| Architecture (n8n patterns) | HIGH | All patterns verified against official n8n docs |
| Architecture (Railway env vars) | HIGH | Confirmed from official n8n and Railway documentation |
| Pitfalls (v1-v2) | HIGH | Directly observable; exact env vars and node configurations identified |
| Pitfalls (v3 LinkedIn) | MEDIUM | LinkedIn enforcement is probabilistic, not deterministic |
| Pitfalls (v4 WhatsApp) | HIGH | Meta policy is explicit; enforcement data from 2025 |
| PDPA/Spam Control Act | MEDIUM | Based on legal advice sites and PDPC overview; not direct PDPC advisory |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

1. **NocoDB row cap: validate today.** Check actual row count in NocoDB leads table vs. count returned by n8n Get All. If the table already has more than 100 rows, the cap is active right now and the pipeline has been silently missing leads. This takes 5 minutes to check and determines whether the pagination fix is urgent (today) or scheduled (next sprint).

2. **OpenRouter balance and current plan check.** Batch processing fix multiplies LLM call volume 5x. Before deploying, verify current OpenRouter balance and confirm "$1 = 1 RPS" concurrency model applies to the current tier. If balance is below $10, top up before deploying batch fix.

3. **Instantly plan verification.** Confirm current Instantly plan is Hypergrowth ($77.60/mo annual) or above. API access is Hypergrowth-minimum. If on a lower plan, v2 cannot start until upgraded.

4. **NocoDB backend.** Confirm whether NocoDB is running on SQLite (default) or PostgreSQL. SQLite write contention becomes a real risk at v2 volume. If on SQLite, schedule PostgreSQL migration before v2 launch.

5. **HeyReach message personalisation at API level.** Research confirms HeyReach supports dynamic variables in campaign messages, but the exact variable injection mechanism via the n8n node's API (vs. the HeyReach UI) needs validation during v3 planning. This affects whether LLM-generated per-lead connection request notes can be injected at the API call level.

6. **PDPA consent framework for WhatsApp.** No specific PDPC guidance was found on what constitutes valid WhatsApp opt-in consent for B2B healthcare outreach. This needs a legal/compliance review before v4 scope is finalised. Do not assume email reply = WhatsApp consent.

---

## Sources

### Primary (HIGH confidence)
- Instantly official node (Instantly-ai/n8n-nodes-instantly GitHub) — operations, webhook events, API v2
- n8n official docs (docs.n8n.io) — Loop Over Items, error handling, concurrency control, WhatsApp node
- Meta official (developers.facebook.com, business.whatsapp.com) — on-premises sunset, WhatsApp Business Policy
- Google Email Sender Guidelines (support.google.com) — spam complaint thresholds
- Instantly deliverability guide (instantly.ai/blog) — send limits, warmup, inbox warming
- Hunter rate limits (help.hunter.io) — 500 req/min limit

### Secondary (MEDIUM confidence)
- HeyReach n8n integration docs (heyreach.io/blog) — community node operations, pricing
- n8n community sources — payload size limits, task runner timeout, polling loop patterns
- NocoDB GitHub discussions — row limit bug, pagination API, SQLite/Postgres comparison
- Singapore legal sources (singaporelegaladvice.com, ismartcom.com, pdpc.gov.sg) — PDPA B2B email rules, DNC register
- Cold email benchmark studies (Instantly, Martal.ca, Belkins) — cadence timing, reply rates
- LinkedIn safety limit guides (salesflow.io, closelyhq.com) — daily limits, enforcement patterns

### Tertiary (LOW confidence — verify during implementation)
- PDPA WhatsApp consent framework for healthcare — no direct PDPC advisory found; extrapolated from general PDPA guidance
- HeyReach dynamic variable injection via n8n API node — described in HeyReach docs but not verified in n8n node context
- NocoDB `$http.request` Code node pattern — pattern documented but n8n version compatibility needs verification

---

*Research completed: 2026-03-23*
*Ready for roadmap: yes*
