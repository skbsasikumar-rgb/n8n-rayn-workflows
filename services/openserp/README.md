# OpenSERP Service

Google-only search backend for the worker.

Build and run the container with:

```bash
docker build -t openserp .
docker run -p 7000:7000 openserp
```

The workflow expects the service base URL to expose `/google/search?text=...&limit=10`.
On Railway, the container binds to `${PORT:-7000}` and runs OpenSERP in browser mode.
The image pins OpenSERP upstream and patches Chromium launch flags with `no-sandbox` / `disable-setuid-sandbox`; without this, Railway can fail Chromium startup with sandbox permission errors.
The image also wraps dedicated search responses as `{ "results": [...] }` so n8n keeps one item per company instead of splitting a result array into many unrelated items.
The service uses `config.yaml` to keep Google direct-search pressure low, cache successful results longer, and leave endpoint fallback disabled.
Railway healthchecks must use `/health`.
