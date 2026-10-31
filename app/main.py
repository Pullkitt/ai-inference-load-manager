"""
app/main.py — FastAPI application factory.

Configures:
  - Lifespan (startup / shutdown) for database connection pools
  - All routers mounted under their SRS-specified path prefixes
  - OpenAPI metadata for evaluator reference
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import (
    connect_mongodb,
    connect_redis,
    disconnect_mongodb,
    disconnect_redis,
    get_db,
)
from app.crud import users as users_crud
from app.crud import inference as inference_crud
from app.routers import health, auth

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Lifespan — runs once at startup and once at shutdown
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open all connection pools on startup; close them on shutdown."""
    logger.info("🚀  Starting AI Inference Load Management Service...")
    await connect_mongodb()
    await connect_redis()

    # Bootstrap MongoDB indexes on all 4 collections
    db = get_db()
    await users_crud.ensure_indexes(db)
    await inference_crud.ensure_indexes(db)
    logger.info("📑  MongoDB indexes verified.")

    logger.info("🟢  All connections established. API is ready.")

    yield  # ← application runs here

    logger.info("🛑  Shutting down...")
    await disconnect_redis()
    await disconnect_mongodb()
    logger.info("✅  Clean shutdown complete.")


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="AI Inference Load Management Service",
    description=(
        "Cloud-Native Adaptive Model Routing & Resiliency Platform — Project P70\n\n"
        "Implements dynamic routing, idempotency, circuit breaker, backpressure, "
        "and live observability across Fast Model and async background worker paths."
    ),
    version="1.0.0",
    contact={
        "name": "Pulkit Jain",
        "email": "jpulkit0205@gmail.com",
    },
    license_info={"name": "Academic Project — UPES, Dehradun"},
    lifespan=lifespan,
)

# ─── CORS (required for the live dashboard to call the API) ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Router Registration
# =============================================================================

# Commit 1: Health check
app.include_router(health.router)

# Commit 3: Authentication
app.include_router(auth.router)

# Commits 4–8: Additional routers will be mounted here as they are implemented:
# app.include_router(inference.router, prefix="/api/inference", tags=["Inference"])
# app.include_router(metrics.router,   prefix="/api/metrics",   tags=["Metrics"])
# app.include_router(logs.router,      prefix="/api/logs",      tags=["Logs"])
# app.include_router(admin.router,     prefix="/admin",         tags=["Admin"])

