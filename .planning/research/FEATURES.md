# Feature Landscape: RAYN Sales Engine

**Domain:** Automated B2B cold outreach engine — n8n-based, single operator, Singapore healthcare/HIA compliance niche
**Researched:** 2026-03-23
**Sources confidence:** MEDIUM-HIGH (Instantly official docs, n8n community, 2025-2026 cold email benchmarks)

---

## Table Stakes

Features that must exist for the engine to function reliably. Missing any of these means the engine breaks silently, burns API budget on bad data, or produces unusable output.

### Workflow Reliability

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Status field as processing lock | Without it, concurrent 3-min runs grab the same lead (race condition — already a known bug) | Low | Pattern: read leads WHERE status = 'pending', immediately UPDATE to 'processing' before doing anything; prevents dual-processing |
| Idempotent per-lead operations | n8n retries on transient failures; without idempotency, the same expensive API calls fire twice | Low-Med | Key insight: upsert instead of insert everywhere; check existing enrichment fields before calling API |
| Error workflow on all production workflows | Silent failures leave leads stuck in 'processing' forever | Low | n8n native: set error workflow in settings; error workflow writes status = 'error' + error_message back to NocoDB row |
| Status terminal states | Engine needs to know when a lead is done, failed permanently, or needs retry | Low | States: pending → processing → enriched / enrichment_error / validation_timeout / dead_domain |
| Pagination on NocoDB reads | Hardcoded 10,000 row limit silently drops leads as table grows (already a known bug) | Low | Use offset pagination in loop; or filter WHERE status = 'pending' LIMIT 100 to avoid ever scanning full table |
| In-batch deduplication before NocoDB write | Same company from two Google Places results inserts twice before enrichment dedup catches it (already a known bug) | Low | Hash company URL at discovery time; check in-memory before inserting batch |
| Batch processing (5 leads/run, not 1) | Single-lead-per-run throttles throughput unnecessarily given API budget | Low | Fix `.first()` bug; use `.all()` then slice to 5 |
| Contact fallback OR logic | Anymail partial result (email but no name) should still trigger Hunter to get name; AND condition breaks this (already a known bug) | Low | Change: `IF name == '' OR email == ''` |
| Verification timeout handling | No2Bounce still processing when poll 4 fires; forcing verdict gives wrong result (already a known bug) | Low | Write `verification_timeout` status; add separate retry workflow that re-polls these leads |

### Email Outreach Core

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Push enriched leads to Instantly via API | Without this, generated emails never get sent; this is the v2 milestone | Low | Use community node `n8n-nodes-instantly`; operation: Add Lead to Campaign; include `skip_if_in_campaign: true` to prevent duplication |
| Sequence pauses on reply | Industry standard; continuing after reply is spammy and damages reputation | Low | Instantly handles this natively when reply_received webhook fires or via reply detection setting |
| Hard bounce suppression | Sending to hard bounces after first bounce degrades domain reputation rapidly | Low | Instantly handles natively + webhook event `email_bounced` → update NocoDB status = 'hard_bounce' |
| Unsubscribe/opt-out processing | Singapore Spam Control Act applies to B2B email; opt-out must be honoured | Low | Instantly webhook `lead_unsubscribed` → update NocoDB status = 'opted_out'; never re-add to campaigns |
| One visible unsubscribe link per email | Required by Singapore Spam Control Act and Google/Yahoo 2025 bulk sender rules | Low | Baked into Instantly sequence templates; verify it is present in all email variants |

### Data Integrity

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| URL-based deduplication (primary key) | Same company appears under slightly different names; URL is canonical (already implemented) | — | Keep as-is |
| Dead domain filtering before enrichment | Prevents wasting 3-4 API calls on leads that will never convert (already implemented) | — | HEAD request before LLM/scrape; keep as-is |
| HIA classification gate | Only YES and VENDOR leads should enter the outreach pipeline; NO leads should be archived, not queued | Low | Confirm classification filter is applied before Instantly push |

---

## Email Sequence Structure

This is the specific structure the engine should produce and push to Instantly. Based on 2025-2026 benchmark data (Instantly's own research + Martal.ca study).

### Recommended Cadence: 5 emails over 21 days

| Step | Day | Label | Content Focus |
|------|-----|-------|---------------|
| Email 1 | 0 | Opening | Personalised hook: specific HIA compliance pain point extracted from website scrape; 3-5 sentences; single CTA (reply or 15-min call) |
| Email 2 | 3 | First follow-up | Different angle: regulatory deadline or enforcement risk; reference Email 1 briefly; add one concrete proof point |
| Email 3 | 7 | Value add | Case study or outcome story (anonymised OK); shift from pain to solution; keep under 100 words |
| Email 4 | 14 | Soft bump | "Wanted to resurface this in case it got buried"; one sentence summary of value; easy-yes CTA |
| Email 5 | 21 | Breakup | "I'll stop reaching out after this"; acknowledge they may not be the right contact; leave door open; no hard sell |

**Key rules:**
- Auto-pause entire sequence on any reply (positive or negative) — Instantly native
- Auto-pause on hard bounce — Instantly native
- Do not trigger on open events — Apple Mail Privacy Protection causes 30-40% false positive opens since 2021; open-rate triggers are broken
- Send window: Tuesday-Thursday, 9:00-11:00 AM Singapore time (SGT, UTC+8)
- Max 30 emails per inbox per day across all campaigns (Instantly deliverability limit)
- Use the 4 pre-generated email variants already in NocoDB as the 4 personalised emails; Email 5 (breakup) can be a static template

### Reply Handling

| Reply Type | Detection | Action |
|-----------|-----------|--------|
| Positive (interested) | Manual review in Instantly Unibox; or webhook reply_received | Pause sequence; mark NocoDB status = 'replied_positive'; log for human follow-up |
| Negative / not interested | Webhook reply_received | Pause sequence; mark NocoDB status = 'replied_negative'; suppress from future campaigns |
| Auto-reply / OOO | Webhook auto_reply_received | Do not pause sequence; do not count as reply; log event only |
| Bounce (hard) | Webhook email_bounced | Pause sequence; mark NocoDB email_status = 'hard_bounce'; remove from all future sends |
| Bounce (soft) | Webhook email_bounced with soft flag | Log; Instantly retries automatically; no NocoDB action needed |
| Unsubscribe | Webhook lead_unsubscribed | Mark NocoDB status = 'opted_out'; log timestamp; never re-add |

---

## LinkedIn Outreach Sequence

For v3. Structure based on SmartReach 6-step B2B sequence (2025) and LinkedIn safety limits.

### Sequence: 5 touchpoints over 14 days (skipping phone call for solo operator)

| Step | Day | Action | Content |
|------|-----|--------|---------|
| 1 | 1 | Profile view (x2) | View prospect's LinkedIn profile on Day 1 and Day 3 — creates awareness, often prompts reciprocal view; no message yet |
| 2 | 4 | Connection request | Short note: "Hi [Name], I work with Singapore healthcare providers on HIA compliance. Would value connecting." No pitch. |
| 3 | 7 | First message (post-connect) | Only send if connected. Reference a specific detail from their profile or company. Introduce HIA compliance context. No hard CTA. |
| 4 | 10 | Follow-up message | If no reply. Acknowledge previous message. One-line value proposition. CTA: "Worth a 15-minute call?" |
| 5 | 14 | InMail (if not connected) | If connection request not accepted. Full context since InMail reaches email. Last LinkedIn touch. |

**Safety limits (LinkedIn enforcement, 2025-2026):**
- Max 10-15 personalised connection requests per day — exceeding triggers account restriction
- Never use identical message text across connection requests — LinkedIn detects templated sequences
- Delays between actions must be randomised (not fixed-interval) to avoid pattern detection
- Recommended tool: Salesflow, Lemlist, or Phantombuster with cloud IP (not desktop automation from same IP)
- n8n can orchestrate timing but should not directly control LinkedIn browser sessions

**Stop conditions:**
- Connection accepted + reply received → move to human follow-up
- InMail replied → move to human follow-up
- "Not interested" message → suppress permanently
- 5 touches with no response → archive LinkedIn channel; continue email sequence independently

---

## Reporting and Visibility (Solo Operator)

The NocoDB table is the primary interface. These features make it operable without a custom dashboard.

| Feature | Why It Matters | Where |
|---------|---------------|-------|
| Lead status column with all terminal states | Know at a glance where every lead is in the pipeline | NocoDB leads table |
| Instantly push timestamp | Know when lead entered outreach; audit trail | NocoDB field: instantly_pushed_at |
| Sequence event log in NocoDB | Reply / bounce / opt-out events written back from Instantly webhooks | NocoDB field: outreach_status, last_event_at |
| Error message column | Diagnose stuck leads without opening n8n execution logs | NocoDB field: error_message |
| Daily counts view | NocoDB grouped view: count by status, count by hia_classification, count pushed today | NocoDB view (no code) |
| n8n execution error alerting | Know when a workflow silently dies overnight | n8n error workflow → send to email or Telegram |
| API cost sentinel | Flag if daily API spend exceeds threshold (Serper/OpenRouter/No2Bounce) | Low priority; manual check initially |

**What NOT to build as a dashboard (anti-feature):** Do not build a custom web UI or analytics dashboard. NocoDB filtered views + Instantly's built-in analytics cover all solo operator needs. A custom dashboard is 2-3 weeks of work that provides no outreach advantage.

---

## Differentiators

What makes this engine effective compared to a generic cold outreach setup. These are the capabilities that justify the build vs buying an off-the-shelf tool.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| HIA compliance pain point extraction from website scrape | Cold email is anchored to the prospect's actual website content, not a generic healthcare pitch — 52% higher reply rate from personalisation depth | Med | Already built; protect this in v1 fixes |
| 4 pre-generated email variants per lead | Sequence uses genuinely different angles per touchpoint, not cosmetic rewrites; avoids "check in" emails that get ignored | Med | Already built; map variants to sequence steps |
| YES vs VENDOR classification gate | Sends different pitch angle to healthcare IT vendors vs clinical providers; not a one-size-fits-all message | Med | Already built; confirm Instantly campaign split handles this |
| Continuous lead discovery (589 combos/week) | Pipeline never runs dry; no manual prospecting; lead quality is deterministic (Google Places licensed + HIA-relevant) | High | Already built |
| Verification before outreach (No2Bounce) | Industry average bounce rate is 7.5%; validated list achieves sub-2%; protects domain reputation | Med | Already built; v1 fix needed for timeout handling |
| Idempotent enrichment pipeline | Can be paused, resumed, and re-run without duplicate API calls or duplicate emails | Med | v1 fix scope |

---

## Anti-Features

Things to deliberately NOT build in v1 or v2. Each has a reason.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Custom web UI / dashboard | 2-3 week build; NocoDB views are sufficient for solo operator; adds maintenance surface | Use NocoDB gallery/grid views and Instantly analytics |
| AI-generated follow-up replies | Responding to prospect replies with AI creates reputational risk in a compliance-sensitive niche; prospects expect human responses after they engage | Route all replies to human inbox in Instantly Unibox |
| Trigger sequences on email opens | Apple Mail Privacy Protection breaks open tracking for 30-40% of recipients; false positives pause sequences prematurely or trigger follow-ups incorrectly | Trigger only on replies and time-based steps |
| Multi-inbox warming management in n8n | Instantly handles warmup natively and better than a custom n8n workflow can; duplicating this creates conflict | Configure warmup directly in Instantly UI |
| CRM sync (HubSpot, Salesforce) | Overkill for solo operator; NocoDB is the CRM | Keep NocoDB as single source of truth; revisit at team scale |
| LinkedIn browser automation in n8n | LinkedIn's bot detection bans accounts running browser automation from cloud IPs; n8n is not designed for browser sessions | Use dedicated LinkedIn tool (Salesflow/Lemlist) and orchestrate timing from n8n via API, not browser |
| WhatsApp cold outreach | Meta requires explicit opt-in consent before any WhatsApp message; cold outreach violates Meta Business Policy and risks permanent account ban | WhatsApp is a post-response nurture channel only, not cold outreach |
| Dynamic sequence branching by persona | Adds workflow complexity with marginal lift at low volume; YES vs VENDOR split is sufficient | If reply rates plateau at scale, add branching then |
| Phone/SMS outreach | Singapore DNC registry applies; adds compliance overhead; outside solo operator capacity | Email + LinkedIn covers the channel surface |

---

## Feature Dependencies

```
Lead discovery (running) → Deduplication → Enrichment pipeline (running)
Enrichment pipeline → HIA classification → Contact lookup → Email validation
Email validation → 4 cold email generation → [ready for push]

[v2] ready for push → Instantly push → Sequence sends → Webhook events
Webhook events → NocoDB status updates → Reply/bounce/opt-out suppression

[v3] ready for push → LinkedIn enrichment (find LinkedIn URL) → LinkedIn sequence tool
LinkedIn sequence → n8n timing orchestration → Status updates

v1 fixes are prerequisites for v2 Instantly push:
- Race condition fix (leads must not be double-pushed)
- Verification timeout fix (timeout leads must not be pushed with unknown email validity)
- Batch processing fix (throughput needed to fill Instantly campaign at useful rate)
```

---

## MVP Recommendation for v1

The v1 scope is bug fixes only. Prioritise in this order:

1. **Race condition / status lock** — highest severity; two runs grabbing same lead creates duplicate outreach records
2. **Batch processing fix** — 5x throughput improvement with no API cost increase
3. **Contact fallback OR logic** — directly increases contact discovery rate (current AND logic drops valid partial results)
4. **Email verification timeout handling** — prevents pushing leads with unknown email validity to Instantly
5. **NocoDB pagination** — time-bomb; must be fixed before table exceeds 10,000 leads
6. **Discovery in-batch dedup** — lower severity; enrichment dedup catches most duplicates eventually

Defer to v2: Instantly push, all sequence features, webhook handling.
Defer to v3: LinkedIn sequence.
Defer indefinitely: WhatsApp cold outreach (policy violation risk), custom dashboard.

---

## Sources

- [Instantly email sequence timing cadence](https://instantly.ai/blog/email-sequence-timing-cadence-optimal-send-times-and-intervals/) — HIGH confidence (official Instantly docs)
- [Instantly API & Webhooks](https://instantly.ai/blog/api-webhooks-custom-integrations-for-outreach/) — HIGH confidence (official)
- [n8n-nodes-instantly community node](https://github.com/Instantly-ai/n8n-nodes-instantly) — HIGH confidence (official Instantly GitHub)
- [n8n error handling patterns](https://www.wednesday.is/writing-articles/advanced-n8n-error-handling-and-recovery-strategies) — MEDIUM confidence (verified against n8n docs)
- [n8n idempotent webhook retries](https://medium.com/@Modexa/idempotent-webhook-retries-in-n8n-without-duplicates-8380273a95a2) — MEDIUM confidence (community; aligns with official pattern)
- [SmartReach 6-step LinkedIn sequence](https://smartreach.io/blog/linkedin-sales-sequence/) — MEDIUM confidence (industry tool; single source)
- [LinkedIn safe automation limits 2025](https://salesflow.io/blog/the-ultimate-guide-to-safe-linkedin-automation-in-2025) — MEDIUM confidence (tool vendor; consistent with LinkedIn policy)
- [Cold email sequence benchmarks — Martal.ca](https://martal.ca/cold-email-sequences-lb/) — MEDIUM confidence (agency; consistent with Instantly data)
- [Instantly deliverability 90% guide](https://instantly.ai/blog/how-to-achieve-90-cold-email-deliverability-in-2025/) — HIGH confidence (official)
- [Singapore PDPA B2B email rules](https://singaporelegaladvice.com/law-articles/email-newsletters-comply-singapore-law/) — MEDIUM confidence (legal advice site; no official PDPC source directly accessed)
- [B2B LinkedIn outreach benchmarks — Belkins](https://belkins.io/blog/linkedin-outreach-study) — MEDIUM confidence (agency study)
- [WhatsApp Business Policy](https://business.whatsapp.com/policy) — HIGH confidence (Meta official)
