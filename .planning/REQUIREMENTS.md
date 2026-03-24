# Requirements: RAYN Sales Engine

**Defined:** 2026-03-23
**Core Value:** Every discovered lead gets a personalised, compliance-context-aware cold email sent without manual intervention.

## v1 Requirements — Workflow Reliability

Fix all bugs preventing the engine from running reliably at volume. These are prerequisites for v2 — the race condition alone will duplicate leads to Instantly campaigns if not fixed first.

### Infrastructure

- [x] **INFRA-01**: Set `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` on Railway n8n env vars — prevents new concurrent trigger overlaps while other fixes are applied
- [x] **INFRA-02**: Raise `DB_QUERY_LIMIT_MAX` on Railway NocoDB env vars — default cap may be 100 rows, silently stopping the pipeline as the table grows

### wf-latest Fixes

- [ ] **FIX-01**: Fix race condition — set lead status to `processing` immediately after fetching (before any API call), so overlapping 3-min runs cannot grab the same lead
- [ ] **FIX-02**: Fix batch processing — replace `.first()` pattern with Loop Over Items (batch size 1) so all 5 filtered leads are processed per run, not just the first
- [ ] **FIX-03**: Add OpenRouter backoff — add retry delay between LLM calls before enabling 5× throughput from FIX-02, to avoid rate limit spikes
- [ ] **FIX-04**: Fix contact fallback logic — change IF No Contact condition from AND to OR (Anymail returning name-but-no-email currently blocks Hunter fallback)
- [x] **FIX-05**: Fix email validation final poll — replace Poll 4 forced verdict with `verification_timeout` status; add a separate retry path for timed-out leads instead of incorrectly marking them invalid
- [ ] **FIX-06**: Fix NocoDB row pagination in wf-latest — paginate all GET requests using offset/limit loop until `pageInfo.isLastPage === true`

### wf-discovery Fixes

- [x] **FIX-07**: Fix NocoDB row pagination in wf-discovery — same pagination fix for the Read Discovery and Read Leads GET requests

## v2 Requirements — Instantly Email Push

Push enriched leads into Instantly campaigns and sync reply/bounce/opt-out events back to NocoDB.

### Lead Push

- [ ] **INST-01**: New workflow reads NocoDB rows WHERE `status = enriched` and pushes each lead to the correct Instantly campaign via `n8n-nodes-instantly` community node
- [ ] **INST-02**: Write `instantly_pushed_at` timestamp and update status to `in_sequence` after successful push
- [ ] **INST-03**: Map the 4 pre-generated email variants (subject_line_1-4 + email_body_1-4) to Instantly sequence step custom variables

### Event Sync

- [ ] **INST-04**: Webhook handler workflow receives Instantly events and updates NocoDB status accordingly:
  - `reply_received` → status = `replied`
  - `email_bounced` → status = `bounced`
  - `lead_unsubscribed` → status = `unsubscribed`
  - `auto_reply_received` → status = `auto_replied` (do not pause sequence)

### Pre-requisites (not code tasks)

- [ ] **INST-05**: Cold email sending domain set up with SPF/DKIM/DMARC before first send
- [ ] **INST-06**: Inbox warmup completed (2–4 weeks) before live campaign launch
- [ ] **INST-07**: Verify Instantly plan is Hypergrowth (API access requirement)

## v3 Requirements — LinkedIn Outreach via HeyReach

Parallel LinkedIn outreach channel for HIA:YES leads, running alongside the email sequence.

- [ ] **LI-01**: Install `n8n-nodes-heyreach` community node on Railway n8n instance
- [ ] **LI-02**: New workflow reads NocoDB rows WHERE `hia_relevant = YES` AND `status = in_sequence` and adds contact to HeyReach campaign
- [ ] **LI-03**: 5-touchpoint LinkedIn sequence: connection request → message 1 (day 3) → message 2 (day 7) → message 3 (day 14) → final note (day 21)
- [ ] **LI-04**: Sync HeyReach reply/accept/ignore events back to NocoDB via webhook
- [ ] **LI-05**: LinkedIn sender account warmed up (14 days manual activity minimum before automation)

## v4 Requirements — WhatsApp Nurture

**Scope note:** WhatsApp cannot be used for cold outreach — Meta's policy requires explicit opt-in consent before first contact. Scraped contacts have not opted in. Cold WhatsApp outreach = immediate permanent account ban. v4 is post-engagement nurture only.

- [ ] **WA-01**: Resolve PDPA consent framework for WhatsApp B2B healthcare outreach in Singapore before any implementation (legal/compliance research, not a code task)
- [ ] **WA-02**: Add consent capture mechanism — leads who reply to email/LinkedIn get an opt-in prompt before any WhatsApp contact
- [ ] **WA-03**: Set up WhatsApp Business Account via Meta for Developers (APAC region for PDPA data residency)
- [ ] **WA-04**: New workflow reads NocoDB rows WHERE `status = replied` AND `whatsapp_consent = true` and sends nurture message via n8n WhatsApp Business Cloud node
- [ ] **WA-05**: Singapore DNC register check before any WhatsApp send (verify if PDPC DNC API is available or if manual check needed)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Cold WhatsApp outreach | Meta policy violation — permanent account ban risk; must be opt-in nurture only |
| Custom email sequencer in n8n | Instantly handles this better; building in n8n is unnecessary complexity |
| Browser automation for LinkedIn | LinkedIn detects cloud IPs; only approved platform APIs (HeyReach) allowed |
| UI dashboard | NocoDB is sufficient for single operator; no frontend needed |
| Multi-user / team access | Single operator for now |
| SMS outreach | Not part of stated scope; WhatsApp covers Singapore mobile channel |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| FIX-01 | Phase 1 | Pending |
| FIX-02 | Phase 1 | Pending |
| FIX-03 | Phase 1 | Pending |
| FIX-04 | Phase 1 | Pending |
| FIX-05 | Phase 1 | Complete |
| FIX-06 | Phase 1 | Pending |
| FIX-07 | Phase 1 | Complete |
| INST-01 | Phase 2 | Pending |
| INST-02 | Phase 2 | Pending |
| INST-03 | Phase 2 | Pending |
| INST-04 | Phase 2 | Pending |
| INST-05 | Phase 2 | Pending |
| INST-06 | Phase 2 | Pending |
| INST-07 | Phase 2 | Pending |
| LI-01 | Phase 3 | Pending |
| LI-02 | Phase 3 | Pending |
| LI-03 | Phase 3 | Pending |
| LI-04 | Phase 3 | Pending |
| LI-05 | Phase 3 | Pending |
| WA-01 | Phase 4 | Pending |
| WA-02 | Phase 4 | Pending |
| WA-03 | Phase 4 | Pending |
| WA-04 | Phase 4 | Pending |
| WA-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 9 total
- v2 requirements: 7 total
- v3 requirements: 5 total
- v4 requirements: 5 total
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-23 after initial definition*
