# QueryPilot backend - FastAPI on Python 3.12
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY eval ./eval

# Run as an unprivileged user; data/ holds the SQLite files.
RUN useradd --create-home querypilot && mkdir -p /app/data && chown -R querypilot /app
USER querypilot

EXPOSE 8000

# Seed the read-only sample database on start (deterministic, < 1 s), then
# serve. PORT is set by hosts such as Render; 8000 locally. The client IP for
# rate limiting is configured with CLIENT_IP_HEADER, not uvicorn proxy flags.
CMD ["sh", "-c", "python -m scripts.seed_database && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/api/health')" || exit 1
