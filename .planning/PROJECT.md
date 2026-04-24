# RAYN Sales Engine

## What This Is

An automated n8n sales engine that discovers, enriches, and reaches out to Singapore healthcare organisations for HIA compliance sales. Three workflows run continuously: wf-discovery (lead discovery via Google Places), wf-latest (enrichment + email generation), and wf-no2bounce-retry (verification timeout retry) — all feeding into a multi-channel outreach stack.

## Core Value

Every discovered lead gets a personalised, compliance-context-aware cold email sent without manual intervention.

## Requirements

### Validated

- ✓ Lead discovery via Serper Places across 51 Singapore areas × 12 healthcare categories — v1.0
- ✓ Deduplication against leads table by URL — v1.0
- ✓ Company name cleaning via LLM (minimax) — v1.0
- ✓ Official website finding and URL deduplication — v1.0
- ✓ HIA relevance classification (YES / VENDOR / NO) — v1.0
- ✓ Website scraping via Serper — v1.0
- ✓ Contact lookup via Anymail + Hunter fallback — v1.0
- ✓ Email validation via No2Bounce with polling — v1.0
- ✓ Compliance pain point analysis via LLM — v1.0
- ✓ 4 personalised cold email generation via claude-sonnet — v1.0
- ✓ HTTP status check before URL validation (HEAD request, filters dead sites) — v1.0
- ✓ Race condition fix (pessimistic status lock) — v1.0
- ✓ Batch processing (all 5 leads per run) — v1.0
- ✓ OpenRouter backoff (1s delay between calls) — v1.0
- ✓ Contact fallback OR logic — v1.0
- ✓ verification_timeout status for slow No2Bounce — v1.0
- ✓ NocoDB pagination (isLastPage loop) — v1.0

### Active

- [ ] INST-01: Push leads to Instantly campaigns
- [ ] INST-02: Write instantly_pushed_at timestamp
- [ ] INST-03: Map email variants to Instantly
- [ ] INST-04: Webhook handler for Instantly events
- [ ] LI-01: Install HeyReach node
- [ ] LI-02: LinkedIn lead enqueue workflow
- [ ] LI-03: 5-touchpoint sequence configuration
- [ ] LI-04: LinkedIn webhook sync
- [ ] WA-01: PDPA consent framework (legal research)
- [ ] WA-02: Consent capture mechanism
- [ ] WA-03: WhatsApp Business Account setup
- [ ] WA-04: WhatsApp nurture workflow
- [ ] WA-05: Singapore DNC register check

### Out of Scope

- WhatsApp cold outreach — v4 is nurture only, PDPA requires explicit opt-in
- LinkedIn browser automation — only approved API (HeyReach) allowed
- Mobile app or UI dashboard — NocoDB is sufficient
- Multi-user / team access — single operator for now

## Context

- **Stack**: n8n (self-hosted on Railway) + NocoDB (Railway) + Serper + OpenRouter (minimax + claude-sonnet) + Anymail + Hunter + No2Bounce + Instantly (pending)
- **Target market**: Singapore licensed healthcare providers and healthcare IT vendors subject to HIA compliance
- **Search coverage**: 589 combos weekly (51 areas × 12 categories + 2 vendor terms)
- **Enrichment cadence**: Phase 1 every 3 min (5 leads/run), Phase 2 every 20 min (1 lead/run)
- **Output**: Fully enriched lead with 4 personalised cold emails, ready for outreach platform push
- **Workflows**: wf-latest (enrichment), wf-discovery (discovery), wf-no2bounce-retry (retry)
- **Last milestone**: v1.0 shipped 2026-03-25 — Phase 1 (Workflow Reliability) complete

## Constraints

- **Platform**: n8n workflows only — no code deployments outside n8n nodes
- **Data store**: NocoDB — all lead state lives here; no external DB
- **API budget**: OpenRouter, Serper, Anymail, Hunter, No2Bounce all metered — fixes must not increase call volume unnecessarily
- **Email sending**: Requires setup of Instantly, cold email domain with SPF/DKIM/DMARC before v2 launch

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| URL dedup as primary dedup (not name) | Same company appears under slightly different names across Google Places listings; URL is canonical | ✓ Good |
| HTTP check in wf-latest only (not wf-discovery) | Discovery is cheap writes; enrichment spends 3-4 API calls per dead URL — check there saves money | ✓ Good |
| HEAD request for HTTP check | Faster than GET, no body download needed | ✓ Good |
| Phase 1 processes 5 leads per run | Balance throughput vs API rate limits | ✓ Good |
| Pessimistic status lock (FIX-01) | Set status=processing before any API call to prevent race conditions | ✓ Good |
| SplitInBatches batchSize=1 | Fixed .first() bug, loop back terminal nodes for multi-lead processing | ✓ Good |
| verification_timeout status | Different from invalid — allows retry workflow to pick up slow validations | ✓ Good |
| NocoDB pagination via isLastPage loop | Silent row cap prevented full table reads; loop now handles any table size | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-25 after v1.0 milestone completion*