# OpenSERP Service

Primary public-search backend for the worker.

Build and run the container with:

```bash
docker build -t openserp .
docker run -p 7000:7000 openserp
```

The worker uses the dedicated engine routes exposed by OpenSERP `v0.7.2`:

- `/duck/search?text=...&limit=10`
- `/google/search?text=...&limit=10`

`/duck/search` is the DuckDuckGo route in this release.
On Railway, the container binds to `${PORT:-7000}` and runs OpenSERP in browser mode.
The Docker image pins `ARG OPENSERP_REF=v0.7.2`.
The Railway patch still adds Chromium `no-sandbox` / `disable-setuid-sandbox` launch flags; this is kept because Railway has previously failed Chromium startup without them.
OpenSERP `v0.7.2` returns dedicated search responses as envelopes with a top-level `results` array.
The service uses `config.yaml` to keep Google pressure low, prefer cache reuse for contact-search queries, and leave endpoint fallback disabled.
The OpenSERP circuit breaker is intentionally shorter for RAYN contact search: it opens after `3` consecutive failures and recovers after `180` seconds, so a bad engine backs off without poisoning the full batch for too long.
RAYN contact search uses DuckDuckGo first, then Google. Bing is not part of the active provider order because repeated live polls showed circuit-breaker failures. Serper remains in the worker as an emergency provider, but it is disabled unless explicitly enabled by environment.
Railway healthchecks must use `/health`.
