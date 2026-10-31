# =============================================================================
#  Dockerfile — FastAPI Application
#  Multi-stage build: slim runtime image for production
# =============================================================================
FROM python:3.11-slim AS base

# Prevent .pyc files and enable unbuffered stdout/stderr for clean Docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ─── Install system dependencies ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ─── Install Python dependencies ─────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ─── Copy application source ─────────────────────────────────────────────────
COPY . .

# ─── Health-check: verifies the /health endpoint is reachable ─────────────────
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ─── Expose port ─────────────────────────────────────────────────────────────
EXPOSE 8000

# ─── Default command: hot-reload in dev (override in docker-compose.prod.yml) ─
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

