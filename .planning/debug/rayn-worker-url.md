# RAYN Enrichment Worker URL Debug

## Symptom
- Rows with valid official URLs were still ending at `resolve_url` with `no_official_homepage`.
- Example live traces showed `Score URL Candidates` had good candidates for rows like `Raffles Medical Bishan`.
- The worker has partial checkpoints, so URL resolution was being checkpointed before duplicate lookup and later stages.

## Root Cause
- `IF URL None` is placed after `Write Partial - URL`.
- That IF evaluated `$json.best_url`.
- After the PATCH checkpoint, `$json` is the NocoDB HTTP response, not the output from `Finalize URL`.
- The PATCH response does not reliably carry `best_url`, so the branch misfired and converted a real URL into the `no_official_homepage` path.

## Evidence
- `Score URL Candidates` can produce real candidates.
- In execution `18033`, the URL candidate list included:
  - `https://www.rafflesmedicalgroup.com/clinic/raffles-medical-bishan/`
  - `https://www.rafflesmedicalgroup.com/`
- `Finalize URL` preserves the selected raw/page URL.
- `Write Partial - URL` is only a status checkpoint and should not be the source of truth for URL existence.

## Minimal Fix
- Change `IF URL None` to read from `Finalize URL` directly:
  - `={{ !String($('Finalize URL').item.json.best_url || '').trim() }}`
- Do not move the partial checkpoint.
- Do not change scoring, search, or dedupe.

## Checkpoints
1. `Score URL Candidates` found valid official URLs for the failing row class.
2. `Write Partial - URL` was confirmed to sit between `Finalize URL` and `IF URL None`.
3. `IF URL None` was confirmed to read `$json.best_url` instead of `Finalize URL`.
4. Root cause confirmed: post-PATCH context loss.

## Expected outcome after fix
- Rows with official sites continue through scrape, classification, contact, and email.
- Rows with no website remain `partial` with empty `best_url`.
- Branch and clinic pages remain valid if they are the best official result.
