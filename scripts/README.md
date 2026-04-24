# Local Helper Scripts

These scripts are intentionally small and explicit.

Simple is best. Do not be over clever.

## NocoDB Row Helper

File: `scripts/rayn_noco_rows.py`

Purpose:
- inspect worker rows
- reset rows back to clean `pending`
- preserve only the identity and discovery fields needed to rerun the lead
- blank the rest of the prior row state before rerun

Required environment variables:
- `NOCO_BASE_URL`
- `NOCO_API_TOKEN`
- `NOCO_PROJECT_ID`
- `NOCO_TABLE_ID`

Examples:

```bash
python3 scripts/rayn_noco_rows.py show --ids 209,210,211
python3 scripts/rayn_noco_rows.py show --where '(status,eq,partial)' --limit 20
python3 scripts/rayn_noco_rows.py reset --ids 209,210,211
python3 scripts/rayn_noco_rows.py reset --where '(status,eq,processing)' --limit 20
```

## n8n Execution Helper

File: `scripts/rayn_n8n_executions.py`

Purpose:
- list recent executions for the worker
- delete old execution records by ID

Required environment variables:
- `N8N_BASE_URL`
- `N8N_API_KEY`

Examples:

```bash
python3 scripts/rayn_n8n_executions.py list --limit 20
python3 scripts/rayn_n8n_executions.py list --status error --limit 20
python3 scripts/rayn_n8n_executions.py delete --ids 101,102,103
```

## Rerun Preparation Helper

File: `scripts/rayn_prepare_rerun.py`

Purpose:
- list recent executions
- purge old execution records before a clean rerun
- reset chosen rows
- immediately show the cleaned rows for verification

Example:

```bash
python3 scripts/rayn_prepare_rerun.py --ids 209,210,211
```

## Company Facts Probe

File: `scripts/rayn_company_facts_probe.py`

Purpose:
- inspect raw scraped evidence for homepage-name and parent-company debugging
- surface likely brand phrases and likely parent phrases from stored `website_content`
- compare the row's current values with the strongest evidence in the text

Required environment variables:
- `DATABASE_URL`

Examples:

```bash
python3 scripts/rayn_company_facts_probe.py --ids 215
python3 scripts/rayn_company_facts_probe.py --ids 213,215 --format json
```

## Notes

- These are local operator tools, not production workflow code.
- They do not try to be smart.
- For in-flight executions that refuse to stop cleanly, restart the Railway `Primary` service before rerunning rows.
- `rayn_prepare_rerun.py` does not stop live in-flight executions. It only cleans execution records and resets target rows.
