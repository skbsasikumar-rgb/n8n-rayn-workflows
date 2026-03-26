FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/crawl4ai/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && crawl4ai-setup \
    && crawl4ai-doctor

COPY services/crawl4ai/app.py ./app.py

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
