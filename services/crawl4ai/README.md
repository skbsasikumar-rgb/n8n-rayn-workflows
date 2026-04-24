# Browser Scraper Service

This service gives `wf-worker.json` one normalized scrape endpoint:

- `POST /scrape`
- input: `url`, `company_name`, optional `market`
- output: `ok`, `final_url`, `title`, `markdown`, `main_text`, `website_content`, `metadata`, `signals`, `quality`, `error`

Workflow operating docs:

- `docs/workflow/overview.md` explains where this service sits in the n8n flow.
- `docs/workflow/runbook.md` covers scraper deployment and rerun checks.
- `docs/workflow/operations-log.md` tracks current scrape-related failures.

## Why this exists

The workflow currently depends on scraper-specific response shapes. This service isolates that dependency and always returns the same payload to n8n.

Current implementation:

- Playwright for browser rendering and navigation
- Beautiful Soup + `lxml` for deterministic HTML parsing
- no autonomous agent loop
- same `/scrape` contract used by n8n

## Request

```json
{
  "url": "https://example.com",
  "company_name": "Example Medical Clinic",
  "market": "Singapore"
}
```

## Response

```json
{
  "ok": true,
  "url": "https://example.com",
  "final_url": "https://example.com/",
  "title": "Example Medical Clinic Singapore",
  "markdown": "...",
  "main_text": "...",
  "website_content": "...",
  "metadata": {
    "description": "...",
    "lang": "en"
  },
  "signals": {
    "is_singapore_relevant": true,
    "country_hint": "SG",
    "matched_terms": ["singapore", "clinic"],
    "company_name_seen": true
  },
  "quality": {
    "content_chars": 4231,
    "word_count": 712,
    "has_icp_terms": true,
    "looks_like_error_page": false
  },
  "error": ""
}
```

## Run with Docker

```bash
cd /Users/sasikumar/Documents/n8n/services/crawl4ai
docker build -t rayn-crawl4ai -f Dockerfile ../..
docker run --rm -p 8080:8080 rayn-crawl4ai
```

Health check:

```bash
curl http://localhost:8080/health
```

## Run with Python

```bash
cd /Users/sasikumar/Documents/n8n/services/crawl4ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 8080
```

Runtime notes:

- The service keeps the `services/crawl4ai` path and `CRAWL4AI_*` env names for deployment compatibility
- The service defaults its runtime home to `services/crawl4ai/runtime-home` when not explicitly set
- On macOS it defaults `PLAYWRIGHT_BROWSERS_PATH` to `~/Library/Caches/ms-playwright`
- On Linux it defaults `PLAYWRIGHT_BROWSERS_PATH` to `~/.cache/ms-playwright`
- Railway/Docker sets `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` and `CRAWL4AI_RUNTIME_HOME=/app/runtime-home`
- Override either with environment variables if needed
- If scraping fails after the worker has verified an official homepage, the workflow should write a `partial` row with `fallback_used`, `evidence_gap`, and `last_error` instead of blocking enrichment.

## n8n URL

The current worker calls the deployed Railway scrape endpoint directly:

```text
https://n8n-rayn-workflows-production.up.railway.app/scrape
```

For future portability, prefer configuring the worker with:

```text
{{ $env.CRAWL4AI_SCRAPER_URL || 'http://127.0.0.1:8080/scrape' }}
```

Set `CRAWL4AI_SCRAPER_URL` if your n8n runtime cannot reach `127.0.0.1:8080` or if the Railway scrape service URL changes.

## Railway

Railway should deploy this service from the `services/crawl4ai` directory using the included `Dockerfile`.

Per Railway's Dockerfile docs, if the service source root is still the repo root, set:

```text
RAILWAY_DOCKERFILE_PATH=services/crawl4ai/Dockerfile
```

Recommended Railway service variables:

```text
PORT=8080
CRAWL4AI_HEADLESS=true
CRAWL4AI_VERBOSE=false
CRAWL4AI_PAGE_TIMEOUT_MS=45000
```

Then set this variable on your Railway n8n service:

```text
CRAWL4AI_SCRAPER_URL=https://<your-crawl4ai-service-domain>/scrape
```

Health endpoint:

```text
GET /health
```
