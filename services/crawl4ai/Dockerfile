FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    CRAWL4AI_RUNTIME_HOME=/app/runtime-home

WORKDIR /app

COPY services/crawl4ai/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/crawl4ai/app.py ./app.py
COPY services/crawl4ai/contact_enrichment.py ./contact_enrichment.py
COPY services/crawl4ai/public_web_enrichment.py ./public_web_enrichment.py
COPY services/crawl4ai/parent_company_registry.json ./parent_company_registry.json

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
