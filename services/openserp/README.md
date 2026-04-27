# OpenSERP Service

Google-only search backend for the worker.

Build and run the container with:

```bash
docker build -t openserp .
docker run -p 7000:7000 openserp
```

The workflow expects the service base URL to expose `/google/search?text=...&limit=10`.
On Railway, the container binds to `${PORT:-7000}` and runs OpenSERP in browser mode.
The image now pins OpenSERP `v0.7.2` and patches Chromium launch flags with `no-sandbox` / `disable-setuid-sandbox`; without this, Railway can fail Chromium startup with sandbox permission errors.
OpenSERP `v0.7.2` already returns dedicated search responses as envelopes with a top-level `results` array, and the current picker logic in `wf-worker.json` already reads `results`.
The service uses `config.yaml` to keep Google direct-search pressure low, cache successful results longer, and leave endpoint fallback disabled.
Railway healthchecks must use `/health`.
