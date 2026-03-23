# RAYN Sales Engine

## What This Is

An automated n8n sales engine that discovers, enriches, and reaches out to Singapore healthcare organisations for HIA compliance sales. Two workflows run continuously: one discovers leads via Google Places, the other enriches them with contact details, HIA classification, and personalised cold emails — all feeding into a multi-channel outreach stack.

## Core Value

Every discovered lead gets a personalised, compliance-context-aware cold email sent without manual intervention.

## Requirements

### Validated

- ✓ Lead discovery via Serper Places across 51 Singapore areas × 12 healthcare categories — existing
- ✓ Deduplication against leads table by URL — existing
- ✓ Company name cleaning via LLM (minimax) — existing
- ✓ Official website finding and URL deduplication — existing
- ✓ HIA relevance classification (YES / VENDOR / NO) — existing
- ✓ Website scraping via Serper — existing
- ✓ Contact lookup via Anymail + Hunter fallback — existing
- ✓ Email validation via No2Bounce with polling — existing
- ✓ Compliance pain point analysis via LLM — existing
- ✓ 4 personalised cold email generation via claude-sonnet — existing
- ✓ HTTP status check before URL validation (HEAD request, filters dead sites) — existing

### Active

<!-- v1: Fix workflow bugs -->

- [ ] Fix batch processing — wf-latest processes only 1 lead per run due to `.first()` bug; should process all 5 filtered leads
- [ ] Fix contact fallback logic — Anymail→Hunter fallback uses AND condition (both name+email empty); should be OR so partial Anymail results still trigger Hunter
- [ ] Fix race condition — Phase 1 reads then processes with no status lock; two 3-min runs can grab the same lead simultaneously
- [ ] Fix email validation final poll — Poll 4 forces a valid/invalid verdict even if No2Bounce is still processing; should mark as `verification_timeout` and retry later
- [ ] Fix NocoDB row cap — GET requests hardcoded at 10,000 rows; will silently miss leads as table grows; needs pagination or higher limit
- [ ] Fix wf-discovery in-batch dedup — discovery write can insert same company twice from different area/category combos before enrichment dedup catches it

### Out of Scope

- Instantly push — v2
- LinkedIn automated outreach — v3
- WhatsApp outreach — v4
- Mobile app or UI dashboard — not needed, NocoDB is the interface
- Multi-user / team access — single operator for now

## Context

- **Stack**: n8n (self-hosted on Railway) + NocoDB (Railway) + Serper + OpenRouter (minimax + claude-sonnet) + Anymail + Hunter + No2Bounce + Instantly (pending)
- **Target market**: Singapore licensed healthcare providers and healthcare IT vendors subject to HIA compliance
- **Search coverage**: 589 combos weekly (51 areas × 12 categories + 2 vendor terms)
- **Enrichment cadence**: Phase 1 every 3 min (5 leads/run), Phase 2 every 20 min (1 lead/run)
- **Output**: Fully enriched lead with 4 personalised cold emails, ready for outreach platform push
- **HTTP checker**: Added to wf-latest between IF URL None → OpenRouter URL Validate; catches dead domains before expensive LLM + scrape calls

## Constraints

- **Platform**: n8n workflows only — no code deployments outside n8n nodes
- **Data store**: NocoDB — all lead state lives here; no external DB
- **API budget**: OpenRouter, Serper, Anymail, Hunter, No2Bounce all metered — fixes must not increase call volume unnecessarily

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| URL dedup as primary dedup (not name) | Same company appears under slightly different names across Google Places listings; URL is canonical | ✓ Good |
| HTTP check in wf-latest only (not wf-discovery) | Discovery is cheap writes; enrichment spends 3-4 API calls per dead URL — check there saves money | ✓ Good |
| HEAD request for HTTP check | Faster than GET, no body download needed | — Pending |
| Phase 1 processes 5 leads per run | Balance throughput vs API rate limits | — Pending |

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
*Last updated: 2026-03-23 after initialization*
