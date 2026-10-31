"""
app/routers/health.py — GET /health

SRS §3.2: System health check endpoint.
Returns the connectivity status of MongoDB, Redis, and the inference queue.
Always returns HTTP 200; component-level status is inside the JSON body.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import get_db, get_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="System Health Check",
    description=(
        "Returns the connectivity status of all system components: "
        "MongoDB, Redis, and the inference queue depth. "
        "Always returns HTTP 200; check the `status` field in the body."
    ),
)
async def health_check() -> JSONResponse:
    """
    Probes MongoDB, Redis, and queue depth.
    Returns a structured JSON body with per-component status.
    """
    components: dict = {}
    overall = "healthy"

    # ─── 1. MongoDB connectivity check ────────────────────────────────────────
    try:
        db = get_db()
        await db.command("ping")
        components["mongodb"] = {
            "status": "connected",
            "database": settings.MONGODB_DB_NAME,
        }
    except Exception as exc:
        logger.warning("Health check — MongoDB error: %s", exc)
        components["mongodb"] = {"status": "error", "detail": str(exc)}
        overall = "degraded"

    # ─── 2. Redis connectivity check ──────────────────────────────────────────
    try:
        redis = get_redis()
        await redis.ping()
        components["redis"] = {"status": "connected"}
    except Exception as exc:
        logger.warning("Health check — Redis error: %s", exc)
        components["redis"] = {"status": "error", "detail": str(exc)}
        overall = "degraded"

    # ─── 3. Inference queue depth ─────────────────────────────────────────────
    try:
        redis = get_redis()
        depth = await redis.llen(settings.REDIS_QUEUE_KEY)
        queue_status = "overloaded" if depth >= settings.MAX_QUEUE_DEPTH else "operational"
        components["inference_queue"] = {
            "status": queue_status,
            "depth": depth,
            "max_capacity": settings.MAX_QUEUE_DEPTH,
        }
        if queue_status == "overloaded":
            overall = "degraded"
    except Exception as exc:
        logger.warning("Health check — queue error: %s", exc)
        components["inference_queue"] = {"status": "error", "detail": str(exc)}

    # ─── 4. Circuit Breaker state (informational) ─────────────────────────────
    try:
        redis = get_redis()
        cb_state = await redis.get(settings.REDIS_CB_STATE_KEY) or "CLOSED"
        components["circuit_breaker"] = {"state": cb_state}
    except Exception:
        components["circuit_breaker"] = {"state": "unknown"}

    return JSONResponse(
        status_code=200,
        content={
            "service": "AI Inference Load Management Service",
            "version": "1.0.0",
            "status": overall,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": components,
        },
    )

