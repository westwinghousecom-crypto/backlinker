# syntax=docker/dockerfile:1
#
# QuickIndex API (FastAPI). Build context: ./backend
#
#   docker build -t quickindex-api ./backend
#
# Runtime dependencies come ONLY from requirements.txt (tests and requirements-dev.txt are not installed here).
# No .env file is baked into the image: pass settings at run time (docker compose env_file / secrets manager).

# ---------------------------------------------------------------------------------------------- builder
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# Compiler only in this stage, in case a dependency has no prebuilt wheel for this Python version.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------------------------- runtime
FROM python:3.14-slim AS runtime

# PYTHONDONTWRITEBYTECODE lets the container run with a read-only root filesystem.
# FORWARDED_ALLOW_IPS = which peers uvicorn believes when they send X-Forwarded-For / X-Forwarded-Proto. NEVER '*': any
# client could then spoof its IP and defeat the per-IP rate limits. docker-compose.yml sets it to the proxy's fixed address.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    FORWARDED_ALLOW_IPS=127.0.0.1

RUN groupadd --system --gid 10001 quickindex \
 && useradd --system --uid 10001 --gid quickindex --no-create-home --shell /usr/sbin/nologin quickindex

COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=quickindex:quickindex app ./app
# Operator scripts (backup/restore, usage measurement, Google live check) so they can be run with: docker compose exec api python scripts/<name>.py
COPY --chown=quickindex:quickindex scripts ./scripts

USER quickindex
EXPOSE 8000

# Liveness only (no dependencies): the process is up and serving. /health/live is added by the app; /health also exists.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:%s/health/live' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"]

# EXACTLY ONE uvicorn process (--workers 1). Do not raise it. The background workers (IndexNow, backlink checks, Google
# inspections) run inside this process and claim Appwrite rows with best-effort optimistic locking; the per-minute Google
# quota window and the API rate limiters live in memory; and only ONE Google inspection worker may run. Scale by making
# this one process faster, not by adding processes. SIGTERM triggers a graceful stop: workers release their rows and
# anything unfinished is recovered by the stale-row sweep after the next start (see docs/DEPLOYMENT.md).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS}\" --timeout-graceful-shutdown 45"]
