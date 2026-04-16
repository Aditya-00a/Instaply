# ─── Ravendise / Instaply Worker — production image ──────────────
# Playwright-ready Chromium browser, NIM client, Supabase client.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOG_LEVEL=INFO \
    WORKER_CONCURRENCY=2

WORKDIR /app

# Python deps first (cache layer)
COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install -r /app/worker/requirements.txt

# Ensure Chromium is present (base image ships it, but re-check is cheap)
RUN python -m playwright install chromium --with-deps

# App code
COPY worker /app/worker

# Workers don't listen on a port — no EXPOSE, no HTTP check.
# Health is liveness: if the process dies, Fly restarts the machine.
CMD ["python", "-m", "worker.orchestrator"]
