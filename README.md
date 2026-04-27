# Rayn Secure Lead Workflow

This repository holds the rebuild of Rayn Secure's n8n lead workflow for Singapore cyber and data security certification outbound.

The rebuild starts from a clean base:

1. Worker workflow first.
2. Discovery workflow second.
3. Orchestration only after the worker contract is stable.

## Goal

Turn a company name into reliable enrichment data for outbound prioritisation:

- official homepage root URL
- canonical domain
- company homepage name
- parent or umbrella company, when clearly supported
- website scrape evidence for later LLM extraction
- duplicate detection by canonical domain

## Operating Principles

All workflow changes must follow the four engineering principles in [WORKING-INSTRUCTIONS.md](WORKING-INSTRUCTIONS.md):

- think before coding
- simplicity first
- surgical changes
- goal-driven execution

## Documentation Map

- [Worker Design](docs/workflow/worker-design.md): worker responsibilities, stages, and success criteria.
- [Discovery Design](docs/workflow/discovery-design.md): discovery boundaries and handoff to worker.
- [Data Contract](docs/workflow/data-contract.md): table fields and status semantics.
- [Runbook](docs/workflow/runbook.md): manual operating steps and rerun process.
- [Operations Log](docs/workflow/operations-log.md): rebuild decisions, progress, and open issues.

## Search Backend

The worker uses OpenSERP Google for homepage discovery and OpenSERP provider cascade for contact search. The container lives in `services/openserp/`.
Set `OPENSERP_BASE_URL` in the worker runtime to point at the deployed service.
