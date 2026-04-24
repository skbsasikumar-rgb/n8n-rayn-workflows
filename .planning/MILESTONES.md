# Milestones

## v1.0 Workflow Reliability MVP (Shipped: 2026-03-25)

**Phases completed:** 1 phases, 5 plans, 10 tasks

**Key accomplishments:**

- N8N concurrency cap (limit=1), 128MB payload limit, 600s task timeout, and NocoDB 100k row cap all activated on Railway — pipeline foundation for all Phase 1 workflow fixes
- Stuck-processing cleanup and pessimistic status lock added to wf-latest — two concurrent 3-minute trigger runs now grab different leads, and leads stuck in processing auto-recover after 10 minutes
- 6 Wait nodes added before each OpenRouter call in the enrichment loop; all 11 terminal nodes now loop back to Loop Over Items, enabling true 5-lead-per-run batch processing
- OR combinator on IF No Contact (Hunter on name OR email empty), verification_timeout for slow No2Bounce polls, and pagination loops replacing all limit=10000 NocoDB GET requests
- Standalone 30-min No2Bounce retry workflow for verification_timeout leads + isLastPage pagination and URL-based dedup in wf-discovery

---
