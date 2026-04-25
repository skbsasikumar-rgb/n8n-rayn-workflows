# OpenSERP Service

Google-only search backend for the worker.

Build and run the container with:

```bash
docker build -t openserp .
docker run -p 7000:7000 openserp serve -a 0.0.0.0 -p 7000
```

The workflow expects the service base URL to expose `/google/search?text=...&limit=10`.
On Railway, the container binds to `${PORT:-7000}`.
