# Technology Stack: Multi-Channel Outreach

**Project:** RAYN Sales Engine
**Researched:** 2026-03-23
**Scope:** v2 (Instantly push), v3 (LinkedIn outreach), v4 (WhatsApp outreach)
**Overall confidence:** MEDIUM — LinkedIn automation ToS landscape is volatile; WhatsApp PDPA specifics from official guidance but enforcement context is MEDIUM

---

## Recommended Stack

### Cold Email Sequencing (v2)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Instantly.ai | API v2 | Email sequence management, campaign delivery | Native n8n community node; maintained by Instantly team; Hypergrowth plan includes API + webhooks; already in project stack |
| n8n-nodes-instantly | Latest (npm) | n8n ↔ Instantly bridge | Official community node by Instantly-ai org; 31 operations across 5 resource types; API key auth |

**Integration method:** Native community node (`n8n-nodes-instantly`). Install via Settings > Community Nodes. Requires Hypergrowth plan ($77.60/mo annual) minimum for API access.

**API v2 operations available:**
- Campaign: create, retrieve, list, update, delete, launch, pause
- Lead: create, retrieve, update, assign to campaign
- Account: warmup control, lifecycle management
- Analytics: campaign performance metrics
- Email (Unibox): inbox, reply, filter

**Webhook events:** sent, opened, clicked, bounced, reply received, unsubscribed, meeting booked, not interested. Deliverable as JSON POST to n8n webhook trigger.

**Recommended pattern for v2:**
```
NocoDB (enriched lead) → Instantly node (Add Lead to Campaign) → Campaign auto-sequences
Instantly webhook (reply/booked) → n8n → NocoDB (update lead status)
```

---

### LinkedIn Automation (v3)

Ranked by n8n integration quality and ToS risk profile.

#### Tier 1 — Recommended: HeyReach

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| HeyReach | Current | LinkedIn connection + message sequences | Native n8n community node; multi-sender architecture (one IP per account); purpose-built for safe scale; transparent API |
| n8n-nodes-heyreach | Latest (npm) | n8n ↔ HeyReach bridge | Native community node; documented operations for Campaigns, Unibox, Lists, Stats, Webhooks |

**Integration method:** Native community node (`n8n-nodes-heyreach`). API key generated per workspace in HeyReach dashboard.

**Operations available:**
- Campaigns: add leads to campaign
- Lists: manage lead lists
- Unibox: message management
- Stats: analytics pull
- Webhooks: event-triggered automation (reply received, connection accepted)

**Pricing:** $79/mo for 1 LinkedIn sender. Pricing is per sender account, not per team member — unlimited users included. Agency plan: $799/mo for 50 senders.

**ToS risk:** MEDIUM. HeyReach uses cloud infrastructure with dedicated IPs per sender. Follows LinkedIn rate limits. Safer than browser-extension tools. Not officially sanctioned by LinkedIn (no tool is), but architecture mimics human patterns more reliably than script-based tools.

**Recommended pattern for v3:**
```
NocoDB (enriched lead, HIA=YES) → HeyReach node (Add Lead to Campaign)
HeyReach webhook (connection accepted/reply) → n8n → NocoDB (update LinkedIn status)
```

---

#### Tier 2 — Alternative: Dux-Soup (HTTP API, best for single operator)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Dux-Soup Turbo/Cloud | Current | LinkedIn connection + profile visits | Has REST API with HMAC-SHA1 auth; official n8n integration guides published by Dux-Soup; $55-99/mo |
| HTTP Request node | n8n built-in | n8n ↔ Dux-Soup bridge | No native node; uses HTTP Request with custom HMAC signature header |

**Integration method:** HTTP API via n8n HTTP Request node. Endpoint: `https://app.dux-soup.com/xapi/remote/control/<USER>/queue`. Authentication: HMAC-SHA1 signature of JSON payload sent as `X-Dux-Signature` header.

**What n8n can trigger:** Queue LinkedIn connection requests with AI-personalised messages. Lead data flows back to n8n via webhook when Dux-Soup completes actions.

**ToS risk:** MEDIUM-HIGH. Browser extension-based architecture is more detectable than cloud tools. Dux-Soup's own docs acknowledge ToS risk ("Use of Dux-Soup is at your own risk"). Suitable for low-volume single-operator use.

**Why not Tier 1:** No native n8n node (extra HMAC integration complexity). Browser extension model is less reliable for 24/7 unattended automation. Less suited for multi-account scale.

---

#### Tier 3 — Not Recommended (for this project)

| Tool | Why Not |
|------|---------|
| Phantombuster | Native n8n node exists (launch Agent operations only); primarily a scraping/data extraction tool, not a sequencing tool; session cookie management is manual; 340% increase in LinkedIn restrictions reported for cloud tools with fixed-interval patterns |
| Expandi | Has REST API + Zapier integration but no native n8n node; 67% of users report account restriction issues per independent review; $99/mo per seat |
| La Growth Machine | Listed in n8n integrations but integration method is HTTP Request only (no native node); $60-220/mo per seat; adds Twitter/email but LinkedIn is the value prop here; overkill for single operator |
| Lemlist (LinkedIn steps) | Multichannel Expert plan at $99/seat includes LinkedIn auto-visits/invites; native n8n node + trigger node exist; but LinkedIn features are secondary to email-first architecture — not purpose-built for LinkedIn sequences |

---

### WhatsApp Business (v4)

**Critical constraint:** The WhatsApp on-premises API was fully deprecated on 23 October 2025. Only Cloud API and official BSPs are viable going forward.

**Critical compliance note:** Singapore PDPA and Spam Control Act apply to WhatsApp outreach. B2B messaging to named individuals at businesses constitutes personal data collection and use. Cold WhatsApp outreach requires either (a) legitimate business interest basis with opt-out, or (b) express consent. Consent must be documented. The PDPA penalty for non-compliance reaches S$1 million (or 10% of annual turnover for large orgs). Healthcare organisations are a regulated sector — consult PDPA advisory guidelines before launching v4.

#### Option A — Recommended: Meta WhatsApp Cloud API direct (via n8n built-in node)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Meta WhatsApp Cloud API | Current (Cloud only) | WhatsApp message sending | Free API access (pay per template message); direct Meta integration; Singapore data residency available via Cloud API regional settings |
| n8n WhatsApp Business Cloud node | Built-in | n8n ↔ WhatsApp Cloud API | Native built-in node (no install needed); send messages, upload/download/delete media; "Send and Wait for Response" operation for conversational workflows |

**Integration method:** Built-in n8n node (`n8n-nodes-base.whatsapp`). Authentication via Meta for Developers → App → WhatsApp → API Setup → Access Token. No BSP markup on message costs.

**Data residency:** Meta Cloud API supports Singapore (APAC region) for message data at rest. Configure during WABA setup.

**Pricing:** Pay-per-template-message (Meta changed from per-conversation to per-template billing in July 2025). No platform fee. Only pay Meta directly.

**PDPA compliance posture:** Direct Meta relationship = no third-party data sharing. Data at rest in Singapore region reduces cross-border transfer exposure. Still requires consent framework on your side.

**Limitation:** Requires a verified Meta Business account and WABA (WhatsApp Business Account) setup. Template messages require Meta approval (24-48 hours). Free-form messages only within 24-hour service window (initiated by recipient).

---

#### Option B — Alternative: 360dialog (BSP, lowest cost managed option)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| 360dialog | Current | Managed WABA access | Official Meta BSP; purpose-built WhatsApp-only API; GDPR-compliant (Germany HQ); minimal markup |
| HTTP Request node | n8n built-in | n8n ↔ 360dialog bridge | No native n8n node; REST API via HTTP Request with Partner API key |

**Integration method:** HTTP Request node. 360dialog provides a REST endpoint that proxies to Meta Cloud API. No native n8n node.

**Data residency:** 360dialog is GDPR-compliant (EU hosting) but does not offer Singapore-specific data residency — data routes through EU infrastructure. This may be a PDPA cross-border transfer issue for Singapore healthcare data.

**Pricing:** Low flat API fee (~$5-10/mo per WABA number) + Meta per-template costs. Cheaper than Twilio for high volume.

**Why not Tier 1:** No native n8n node (HTTP Request adds complexity). EU data residency is potentially non-compliant for Singapore personal data under PDPA transfer provisions. Direct Meta Cloud API (Option A) gives Singapore data residency with no extra cost.

---

#### Option C — Viable but more expensive: Twilio

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Twilio | Current | WhatsApp via CPaaS platform | Native n8n node exists; well-documented; reliable; global infrastructure |
| n8n Twilio node | Built-in | n8n ↔ Twilio bridge | 2 operations: send message (SMS/MMS/WhatsApp) and make call; simplest setup |

**Integration method:** Native built-in n8n node. Twilio node handles auth via Account SID + Auth Token. Toggle message channel to WhatsApp.

**Pricing:** Twilio adds per-message markup on top of Meta costs. Higher cost than direct Meta Cloud API or 360dialog at scale.

**Why consider it:** Easiest setup if already using Twilio for SMS. Most mature developer experience. Good Singapore coverage.

**Why not primary:** More expensive than direct Cloud API. No Singapore data residency advantage over Option A.

---

#### Option D — Do Not Use: Unofficial WhatsApp APIs (e.g. Baileys, WPPConnect, wa-web.js)

**Verdict: Hard no.** Using unofficial APIs violates WhatsApp Terms of Service and results in permanent account and number blacklisting. Meta's detection of unofficial behaviour increased significantly in 2025. In a Singapore B2B healthcare context, a banned WhatsApp number would also constitute a reputational and compliance risk. The on-premises API (which provided a similar bypass) was fully deprecated October 2025.

---

## Alternatives Considered: Cold Email Sequencing

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Email sequencing | Instantly.ai | Smartlead | Smartlead's community node (`n8n-nodes-smartlead`) is third-party, not maintained by Smartlead; Instantly node is maintained by Instantly-ai GitHub org — better reliability |
| Email sequencing | Instantly.ai | Lemlist | Lemlist has native n8n node + trigger (46 triggers, 15 actions); strong choice but per-user pricing ($69-99/seat) vs Instantly's account-based pricing; Instantly already in project stack |
| Email sequencing | Instantly.ai | Reply.io | Multichannel (email + LinkedIn + WhatsApp calls); no native n8n node; more complex than needed for v2 scope |

**Smartlead as Instantly alternative** (if needed): Pro plan at $94/mo includes API access, unlimited mailboxes/warmup, 150k emails/mo. Community node v1.9.0 exists on npm (`n8n-nodes-smartlead-v1-9-0`). Operations: Campaign Management (Get All), Lead Management (Add to Campaign), Analytics. Functional but less mature than Instantly's official node.

---

## Full Stack Summary by Milestone

| Milestone | Tool | n8n Integration Method | Plan Required | Cost |
|-----------|------|----------------------|---------------|------|
| v2: Email sequences | Instantly.ai API v2 | Native community node (`n8n-nodes-instantly`) | Hypergrowth ($77.60/mo annual) | Already in stack |
| v3: LinkedIn outreach | HeyReach | Native community node (`n8n-nodes-heyreach`) | Starter ($79/mo, 1 sender) | New |
| v4: WhatsApp | Meta WhatsApp Cloud API | Built-in node (`n8n-nodes-base.whatsapp`) | Free API + per-template Meta fee | New (WABA setup required) |

---

## Installation

```bash
# v2 — Instantly (install via Settings > Community Nodes in n8n UI)
# Package name: n8n-nodes-instantly
# Or via npm for self-hosted:
npm install n8n-nodes-instantly

# v3 — HeyReach (install via Settings > Community Nodes in n8n UI)
# Package name: n8n-nodes-heyreach
# Or via npm for self-hosted:
npm install n8n-nodes-heyreach

# v4 — WhatsApp Business Cloud (built-in, no install needed)
# Enable via: n8n node search → "WhatsApp Business Cloud"
```

---

## Singapore-Specific Notes

### WhatsApp + PDPA

1. **Legitimate interest vs consent:** B2B outreach to a company's business contact (e.g. clinic manager's work mobile) falls in a grey zone. PDPA's legitimate business interest basis requires the purpose to be proportionate and not override individual interests. Healthcare sector heightens sensitivity — individuals are also patients/staff with elevated privacy expectations.

2. **Opt-out mechanism mandatory:** Any WhatsApp template message for marketing must include a clear opt-out path (WhatsApp native "Stop" button on template messages satisfies this).

3. **DNC register check:** Singapore operates a Do Not Call (DNC) register for phone numbers. WhatsApp numbers attached to the DNC register cannot be contacted for marketing. Check DNC before sending: https://www.pdpc.gov.sg/dnc.

4. **Data localisation:** Meta Cloud API's Singapore region setting (APAC) is the only fully compliant path for personal data at rest. 360dialog routes through EU, which requires explicit cross-border transfer safeguards under PDPA Section 26.

5. **HIA context:** Healthcare providers subject to HIA compliance are B2B targets, but decision-makers are natural persons. Personal data of the contact (name, mobile, email) collected during enrichment phase is already subject to PDPA — extend that compliance posture to WhatsApp outreach.

### LinkedIn + PDPA

LinkedIn profiles are public, but automated scraping and storage of profile data for outreach constitutes personal data collection under PDPA. The consent/legitimate interest analysis applies. Ensure NocoDB records include a data source field and that the enrichment pipeline does not store unnecessary personal attributes.

---

## Sources

- Instantly n8n community node (official): https://github.com/Instantly-ai/n8n-nodes-instantly
- Instantly API + webhooks: https://instantly.ai/blog/api-webhooks-custom-integrations-for-outreach/
- Instantly pricing (Hypergrowth): https://instantly.ai/pricing
- HeyReach n8n integration: https://www.heyreach.io/blog/n8n-integration
- HeyReach pricing: https://www.heyreach.io/pricing
- n8n HeyReach API integrations: https://n8n.io/integrations/heyreach-api/
- Dux-Soup n8n guide (official): https://support.dux-soup.com/article/573-trigger-a-custom-ai-connection-request-message-from-your-crm-into-dux-soup-using-n8n
- Dux-Soup API docs: https://www.dux-soup.com/api
- Phantombuster n8n docs: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.phantombuster/
- Expandi review (account restriction rate): https://connectsafely.ai/articles/expandi-review-linkedin-automation-alternative-2026
- n8n WhatsApp Business Cloud node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.whatsapp/
- WhatsApp on-premises sunset (Meta official): https://developers.facebook.com/docs/whatsapp/on-premises/sunset
- n8n Twilio node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.twilio/
- Smartlead n8n community node (npm): https://www.npmjs.com/package/n8n-nodes-smartlead-v1-9-0
- Smartlead n8n integration guide: https://helpcenter.smartlead.ai/en/articles/181-how-to-use-n8n-and-smartlead-automation-a-step-by-step-guide
- Lemlist n8n node docs: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.lemlist/
- Singapore PDPA overview: https://www.pdpc.gov.sg/Overview-of-PDPA/The-Legislation/Personal-Data-Protection-Act
- Singapore B2B lead gen compliance: https://www.ismartcom.com/blog/critical-legal-and-compliance-considerations-in-b2b-lead-generation-navigating-the-landscape-safely/
- PDPA Data Protection & Privacy 2025 (Singapore): https://practiceguides.chambers.com/practice-guides/data-protection-privacy-2025/singapore/trends-and-developments
- WhatsApp pricing change July 2025 (per-template): https://zixflow.com/blog/whatsapp-api-providers/
- Phantombuster LinkedIn safety 2025: https://phantombuster.com/blog/social-selling/linkedin-limits-2025-safe-automation-strategies/
