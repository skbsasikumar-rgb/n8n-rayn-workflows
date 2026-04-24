# Workflow Runbook

## When To Use This

Use this runbook when deploying workflow JSON, rerunning rows, cleaning stale executions, or validating result quality.

## Source Checks

Before changing live workflows:

1. Confirm the repo file being edited: `wf-discovery.json`, `wf-latest.json`, or `wf-worker.json`.
2. Confirm whether live n8n already has newer changes.
3. Validate JSON structure before deployment.
4. Run one known-bad row before running a larger batch.

## Clean Rerun Sequence

Use this sequence for first-20 or full-table reruns:

1. Clear old n8n execution records for the target workflow when practical.
2. Reset only the target NocoDB rows to clean `pending`.
3. Confirm reset fields are blanked: URL fields, company facts, duplicate fields, `last_stage`, and `last_error`.
4. Trigger the orchestrator or worker.
5. Verify n8n execution status.
6. Verify NocoDB final row fields.
7. Query for remaining `failed`, `pending`, or stale `processing` rows.

Local helper:

```bash
python3 scripts/rayn_prepare_rerun.py --ids 209,210,211
```

For a full-table clean rerun, prefer a scripted reset by status or filter after confirming the target where clause. Do not reset rows blindly if there are manually curated records in the same table.

## Row Inspection

Show specific rows:

```bash
python3 scripts/rayn_noco_rows.py show --ids 250,256,263
```

Show active problems:

```bash
python3 scripts/rayn_noco_rows.py show --where '(status,in,failed,pending,processing)' --limit 50
```

Probe company facts from stored evidence:

```bash
python3 scripts/rayn_company_facts_probe.py --ids 250
```

## Execution Cleanup

List worker executions:

```bash
python3 scripts/rayn_n8n_executions.py list --limit 20
```

List recent errors:

```bash
python3 scripts/rayn_n8n_executions.py list --status error --limit 20
```

Delete selected old execution records:

```bash
python3 scripts/rayn_n8n_executions.py delete --ids 101,102,103
```

Required environment variables are documented in `scripts/README.md`.

## Deployment Checklist

For workflow changes:

- Validate the workflow JSON.
- Deploy/update the matching live n8n workflow.
- Toggle active state if needed so webhook changes take effect.
- Run one known-bad row.
- Run the first 20 rows or the smallest useful batch.
- Check live row output, not only webhook response.
- Record the result in `docs/workflow/operations-log.md`.

For scraper changes:

- Build or deploy `services/crawl4ai`.
- Check `GET /health`.
- Run one known URL through `POST /scrape`.
- Confirm worker still writes `partial` when scraping fails after URL validation.

## Regression Anchors

Use these rows when tuning homepage selection:

| Row | Company | Expected homepage |
| --- | --- | --- |
| `250` | Osler Health International | `https://osler-group.com/` |
| `256` | GoodDoctors Medical Clinic | `http://gooddoctors.com.sg/` |
| `263` | Sree Narayana Mission | `https://sreenarayanamission.org/` |

Use these known truth examples when tuning parent/company extraction:

| Company | Expected homepage | Expected notes |
| --- | --- | --- |
| HMI Medical | `https://www.hmimedical.com/` | Root is HMI Medical. |
| HMI OneCare | `https://www.onecaremedical.com.sg/` | Parent can be HMI Medical or HMI Group if evidence supports it. |
| Tokio Marine Life Insurance Singapore | `https://www.tokiomarine.com/sg/en/life.html` | Parent is Tokio Marine Group. |

## Common Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Webhook says started but row stays blank | Payload shape mismatch or early node failure. | Inspect execution data and `Normalize Input`. |
| Row stays `processing` | Worker still running or failed before writeback. | Check execution history; stale reset should recover after threshold. |
| Correct URL but `partial` | Scrape failed after URL validation. | Inspect `last_error`; harden scraper or accept fallback. |
| Directory URL chosen | Candidate filters too weak. | Add domain/path/text deny rules and regression row. |
| Duplicate company enriched again | `canonical_domain` missing or dedupe read failed. | Inspect `Read Domain Duplicates` and `duplicate_of_id`. |

## What Good Looks Like

After a rerun, the table should have:

- no stale `processing` rows
- no unexpected `pending` rows
- no directory or donation-platform `best_url`
- duplicates marked with `duplicate_of_id`
- `partial` rows only where the reason is visible in `fallback_used`, `evidence_gap`, and `last_error`
