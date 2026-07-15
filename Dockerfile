# syntax=docker/dockerfile:1.7

# Install Python deps in a throwaway stage so build tools never enter runtime.
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# cryptg may need a compiler when no prebuilt wheel is available.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && find /opt/venv -type d -name "__pycache__" -print0 | xargs -0r rm -rf \
    && find /opt/venv -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete \
    && find /opt/venv/lib -type d \( -name "tests" -o -name "test" \) -print0 | xargs -0r rm -rf

# Final image keeps only the virtualenv and application code.
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    TOGO115_DATA_DIR=/data \
    TOGO115_DATABASE_PATH=/data/togo115.sqlite3

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

RUN python -m compileall -q app \
    && mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]