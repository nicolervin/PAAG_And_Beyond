# syntax=docker/dockerfile:1
FROM python:3.12-slim

# System dependencies for Pillow, pypdfium2, matplotlib, and Cloud Run health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root runtime user and writable directories
RUN groupadd --gid 10001 paag \
    && useradd --uid 10001 --gid paag --shell /bin/bash --create-home paag \
    && mkdir -p /app/data/uploads /tmp/matplotlib \
    && chown -R paag:paag /app /tmp/matplotlib

WORKDIR /app

# Install Python dependencies first for optimal Docker layer caching
COPY --chown=paag:paag requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy application source
COPY --chown=paag:paag . /app

# Runtime environment defaults for Google Cloud Run
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    MPLCONFIGDIR=/tmp/matplotlib \
    PAAG_DATA_DIR=/app/data \
    PAAG_UPLOAD_DIR=/app/data/uploads \
    PAAG_DB_PATH=/app/data/paag.db \
    PAAG_CACHE_MAX_MB=256 \
    PAAG_SQLITE_TIMEOUT_S=30 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

USER paag

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail http://127.0.0.1:${PORT:-8080}/_stcore/health || exit 1

# Use exec so Cloud Run SIGTERM reaches Streamlit/Python directly and flushes GCS sync
ENTRYPOINT ["sh", "-c", "exec streamlit run streamlit_app.py --server.port=${PORT:-8080} --server.address=0.0.0.0"]
