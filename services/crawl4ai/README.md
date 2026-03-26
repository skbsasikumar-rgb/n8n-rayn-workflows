# Crawl4AI Scraper Service

This service gives `wf-latest.json` one normalized scrape endpoint:

- `POST /scrape`
- input: `url`, `company_name`, optional `market`
- output: `ok`, `final_url`, `title`, `markdown`, `main_text`, `website_content`, `metadata`, `signals`, `quality`, `error`

## Why this exists

The workflow currently depends on scraper-specific response shapes. This service isolates that dependency and always returns the same payload to n8n.

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
docker compose up -d --build
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
crawl4ai-setup
crawl4ai-doctor
uvicorn app:app --host 0.0.0.0 --port 8080
```

Runtime notes:

- The service defaults its Crawl4AI runtime home to `/Users/sasikumar/Documents/n8n/services/crawl4ai/runtime-home`
- It defaults `PLAYWRIGHT_BROWSERS_PATH` to `~/Library/Caches/ms-playwright`
- Override either with environment variables if needed

## n8n URL

The workflow uses:

```text
{{ $env.CRAWL4AI_SCRAPER_URL || 'http://127.0.0.1:8080/scrape' }}
```

Set `CRAWL4AI_SCRAPER_URL` if your n8n runtime cannot reach `127.0.0.1:8080`.
