# ROADMAP: RAYN Sales Engine

**Project:** RAYN Sales Engine
**Core Value:** Every discovered lead gets a personalised, compliance-context-aware cold email sent without manual intervention.
**Created:** 2026-03-24
**Milestones:** 4 (v1-v4)
**Granularity:** Standard (3-5 plans per phase)
**Coverage:** 26/26 requirements mapped

---

## Phases

- [x] **Phase 1: Workflow Reliability** -- Fix all bugs in wf-latest and wf-discovery so the enrichment pipeline runs continuously at volume without manual intervention (completed 2026-03-24)
- [ ] **Phase 2: Instantly Email Push** -- Push enriched leads into Instantly campaigns and sync reply/bounce/unsubscribe events back to NocoDB
- [ ] **Phase 3: LinkedIn Outreach** -- Add parallel HeyReach LinkedIn channel for HIA:YES leads with a 5-touchpoint sequence
- [ ] **Phase 4: WhatsApp Nurture** -- Post-engagement, consent-gated WhatsApp nurture for warm leads who have already replied

---

## Phase Details

### Phase 1: Workflow Reliability
**Goal**: The enrichment pipeline runs continuously, processes all 5 leads per trigger, never races on the same lead, paginates across the full NocoDB table, and handles verification timeouts without manual intervention.
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, FIX-01, FIX-02, FIX-03, FIX-04, FIX-05, FIX-06, FIX-07
**Plans:** 5/5 plans complete

Plans:
- [x] 01-01-PLAN.md -- Railway env var hardening on n8n and NocoDB services (INFRA-01, INFRA-02)
- [x] 01-02-PLAN.md -- Race condition status lock + stuck-processing cleanup in wf-latest (FIX-01)
- [x] 01-03-PLAN.md -- OpenRouter backoff + batch processing loop verification in wf-latest (FIX-02, FIX-03)
- [x] 01-04-PLAN.md -- Contact fallback OR fix + No2Bounce timeout + NocoDB pagination in wf-latest (FIX-04, FIX-05 Part A, FIX-06)
- [x] 01-05-PLAN.md -- No2Bounce retry workflow + NocoDB pagination and URL dedup in wf-discovery (FIX-05 Part B, FIX-07)

**Success Criteria** (what must be TRUE):
1. Two overlapping 3-minute trigger runs process different leads -- no row appears in both runs' output
2. A single trigger run produces exactly 5 enrichment completions when 5+ pending leads exist (not 1)
3. When NocoDB leads table exceeds 100 rows, all rows in `status=pending` are visible to wf-latest on the next run
4. A lead whose No2Bounce validation is still processing after 60 seconds is written as `verification_timeout`, not `valid` or `invalid`
5. Hunter is called when Anymail returns a name but no email (OR logic confirmed by execution log)

### Phase 2: Instantly Email Push
**Goal**: Every lead with `status=enriched` and a validated email is pushed to the correct Instantly campaign, receives a personalised 4-email sequence, and reply/bounce/unsubscribe events are reflected in NocoDB within minutes.
**Depends on**: Phase 1
**Requirements**: INST-01, INST-02, INST-03, INST-04, INST-05, INST-06, INST-07

**Plans**:
1. **Pre-launch gate** -- Verify Instantly Hypergrowth plan (API access requirement); set up cold email sending domain with SPF/DKIM/DMARC; confirm Singapore Spam Control Act unsubscribe link is present in all sequence templates; complete 2-4 week inbox warmup before first live send (covers INST-05, INST-06, INST-07)
2. **Lead push workflow** -- Install `n8n-nodes-instantly` community node; build new n8n workflow that reads NocoDB WHERE `status=enriched`, pushes each lead to the correct Instantly campaign using `skip_if_in_campaign: true`, and writes `instantly_pushed_at` timestamp + updates status to `in_sequence` on success (covers INST-01, INST-02)
3. **Email variant mapping** -- Map the 4 pre-generated email fields (subject_line_1-4, email_body_1-4) from NocoDB to Instantly sequence step custom variables; validate that Email 1-4 content reaches Instantly correctly via test lead push (covers INST-03)
4. **Webhook event sync** -- Build Instantly webhook handler workflow: receive `reply_received` -> `replied`, `email_bounced` -> `bounced`, `lead_unsubscribed` -> `unsubscribed`, `auto_reply_received` -> `auto_replied` (sequence continues); confirm NocoDB status updates within 2 minutes of Instantly event (covers INST-04)

**Success Criteria** (what must be TRUE):
1. A lead reaching `status=enriched` in NocoDB is pushed to Instantly and marked `in_sequence` within one workflow run cycle
2. The Instantly campaign shows the correct personalised email content drawn from the lead's NocoDB email fields
3. A reply to a sequence email triggers a NocoDB status update to `replied` within 2 minutes
4. A bounce event updates the lead to `bounced` and does not trigger any further outreach
5. No lead is pushed to Instantly twice (idempotent push confirmed via `skip_if_in_campaign`)
**Plans**: TBD

### Phase 3: LinkedIn Outreach
**Goal**: HIA:YES leads who are already in an email sequence also receive a parallel 5-touchpoint LinkedIn sequence via HeyReach, with connection and reply events tracked in NocoDB.
**Depends on**: Phase 2
**Requirements**: LI-01, LI-02, LI-03, LI-04, LI-05

**Plans**:
1. **Account warmup + HeyReach setup** -- Complete 14-day manual warmup on dedicated LinkedIn account (not primary); install `n8n-nodes-heyreach` community node; configure HeyReach Starter plan ($79/mo) with dedicated sender account; set daily connection request cap to 10-15 with randomised delays (covers LI-01, LI-05)
2. **LinkedIn lead enqueue workflow** -- Build n8n workflow that reads NocoDB WHERE `hia_relevant=YES` AND `status=in_sequence`; adds each contact to the correct HeyReach campaign using per-lead personalisation variables drawn from NocoDB (company name, HIA classification, scraped website content) (covers LI-02)
3. **5-touchpoint sequence configuration** -- Configure HeyReach campaign: Day 1+3 profile views -> Day 4 connection request (compliance context, no pitch) -> Day 7 first message (connected) -> Day 14 follow-up -> Day 21 InMail (not connected); validate that dynamic variables inject correctly at API level (covers LI-03)
4. **Webhook event sync** -- Build HeyReach webhook handler: connection accepted -> `li_connected`, reply received -> `li_replied`, invite ignored -> `li_ignored`; all events written to NocoDB alongside existing email status (covers LI-04)

**Success Criteria** (what must be TRUE):
1. An HIA:YES lead entering `in_sequence` status is enrolled in the HeyReach campaign within one workflow run cycle
2. The HeyReach campaign shows the correct per-lead personalised message content, not a generic template
3. A LinkedIn reply event updates NocoDB to `li_replied` within 5 minutes
4. Connection request volume stays at or below 15 per day on the sender account
5. The dedicated LinkedIn account remains in good standing (no restriction notice) after 30 days of automation
**Plans**: TBD
**UI hint**: no

### Phase 4: WhatsApp Nurture
**Goal**: Leads who have replied to email or LinkedIn and explicitly opted in to WhatsApp receive a nurture sequence via Meta WhatsApp Cloud API, with Singapore PDPA compliance enforced at every step.
**Depends on**: Phase 3
**Requirements**: WA-01, WA-02, WA-03, WA-04, WA-05

**Plans**:
1. **Compliance and consent framework** -- Complete PDPA legal review for WhatsApp B2B healthcare outreach in Singapore (what constitutes valid opt-in consent); document the consent trigger (a reply to email/LinkedIn is not sufficient -- a separate explicit opt-in is required); confirm DNC register check process for phone numbers used on WhatsApp (covers WA-01, WA-05)
2. **Consent capture mechanism** -- Add opt-in prompt to reply workflow: when a lead replies to email or LinkedIn, trigger a follow-up that asks for explicit WhatsApp consent and writes `whatsapp_consent=true` to NocoDB only on affirmative response (covers WA-02)
3. **WABA setup** -- Set up WhatsApp Business Account via Meta for Developers using APAC region endpoint for Singapore data residency; complete Meta Business account verification; submit and receive approval for nurture message templates (24-48 hour approval window) (covers WA-03)
4. **Nurture workflow** -- Build n8n workflow using built-in `n8n-nodes-base.whatsapp` node; reads NocoDB WHERE `status=replied` AND `whatsapp_consent=true`; checks DNC register before each send; sends approved Meta templates only; uses "Send and Wait for Response" for conversational follow-up (covers WA-04)

**Success Criteria** (what must be TRUE):
1. No WhatsApp message is sent to any lead without a confirmed `whatsapp_consent=true` NocoDB record
2. A lead whose phone number appears on the Singapore DNC register does not receive a WhatsApp message
3. WhatsApp message templates are Meta-approved before any live send
4. A nurture message is delivered to a consenting, DNC-clear lead within one workflow run cycle of consent being recorded
5. All personal data processed via WhatsApp is stored in the APAC/Singapore data residency region (confirmed in WABA settings)
**Plans**: TBD

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Workflow Reliability | 5/5 | Complete   | 2026-03-24 |
| 2. Instantly Email Push | 0/4 | Not started | - |
| 3. LinkedIn Outreach | 0/4 | Not started | - |
| 4. WhatsApp Nurture | 0/4 | Not started | - |

---

## Coverage

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Pending |
| FIX-01 | Phase 1 | Pending |
| FIX-02 | Phase 1 | Pending |
| FIX-03 | Phase 1 | Pending |
| FIX-04 | Phase 1 | Pending |
| FIX-05 | Phase 1 | Pending |
| FIX-06 | Phase 1 | Pending |
| FIX-07 | Phase 1 | Pending |
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

**Total:** 26/26 requirements mapped. No orphans.

---

*Roadmap created: 2026-03-24*
*Last updated: 2026-03-24 after Phase 1 planning*
