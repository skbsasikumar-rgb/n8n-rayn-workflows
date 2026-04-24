# Improvement Backlog

This backlog is scoped to making the RAYN workflow successful for Singapore cyber and data security certification outbound. It is ordered by operational value, not implementation size.

## P1: Define Lead Quality Gates

Discovery should score whether a company is worth certification outreach before enrichment volume grows.

Add fields or deterministic tags for:

- Singapore relevance
- business category
- company size signal
- regulated or data-sensitive industry signal
- cyber/data compliance trigger
- likely buyer persona
- source query that produced the lead

Acceptance gate: every new seed row has enough context to explain why Rayn Secure should contact it.

## P1: Make Result QA Fast

Add a repeatable report after reruns:

- total rows checked
- `done`, `partial`, `url duplicate`, `failed`, `pending`, `processing` counts
- rows with directory/social/donation/mall domains
- rows with blank `canonical_domain`
- rows with duplicate canonical domains but missing `duplicate_of_id`
- rows with `partial` and high-severity `last_error`

Acceptance gate: after a full-table rerun, bad rows are visible in one report without manual table scanning.

## P1: Stabilize Scrape Fallback

Correct official homepage selection is more important than perfect scrape content, but scrape failures should be predictable.

Improve:

- navigation retry after `Execution context was destroyed`
- timeout-specific fallback notes
- smaller scrape payload sent to model
- content quality flags before facts extraction

Acceptance gate: a scrape failure writes `partial` with clear evidence and never blocks the row.

## P1: Preserve The Discovery/Worker Boundary

Discovery can write hints, but worker enrichment should stand on `company_name`.

Improve:

- worker ignores weak discovery homepage hints unless independently validated
- candidate evidence is stored for audit
- discovery categories map to Rayn Secure outreach angles, not homepage facts

Acceptance gate: a bad discovery URL cannot become `best_url` unless the worker verifies it as official.

## P2: Regression Fixtures

Turn known failures into local replay fixtures.

Start with:

- GoodDoctors Medical Clinic should not choose `singmalls.app`.
- Sree Narayana Mission should not choose `give.asia`.
- Osler Health International should resolve to `osler-group.com`.
- HMI Medical should resolve to `hmimedical.com`.

Acceptance gate: homepage selection can be replayed locally before deploying workflow JSON.

## P2: Prompt And Model Routing

Keep prompts short and route by task complexity.

Rules:

- deterministic URL cleanup before LLM ranking
- no full raw HTML in model calls unless needed
- compact JSON evidence for facts extraction
- higher reasoning only for ambiguous parent-company or legal-entity cases
- cache reusable rules in docs and workflow code, not duplicated prompt prose

Acceptance gate: token usage falls without reducing homepage correctness.

## P2: Monitoring And Recovery

Add operational checks for:

- stale `processing`
- repeated `failed` by `last_stage`
- scrape timeout rate
- duplicate rate
- blank homepage rate
- rows with suspicious third-party domains

Acceptance gate: the workflow can run unattended and surface only actionable exceptions.

## P3: Outreach Readiness

After enrichment is stable, add fields that directly help outbound:

- certification/compliance pain hypothesis
- likely security trigger
- suggested Rayn Secure offer angle
- confidence score
- do-not-contact or low-fit reason

Acceptance gate: enriched rows are useful for campaign copy and prioritization, not just data cleanup.
