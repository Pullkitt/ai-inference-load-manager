"""
app/routers/metrics.py
──────────────────────
Observability & Telemetry API endpoints.

SRS §3.2, §5.3:
  - GET /api/metrics/system-load:
    Exposes real-time system metrics:
      1. Requests Per Second (RPS) breakdown by HTTP status code (200, 202, 429, 503)
      2. Response Latencies: p50 (median) and p95 percentiles in milliseconds
      3. Active Fast Model Concurrency (slots currently occupied)
      4. Redis Queue Depth & capacity utilization
      5. Circuit Breaker State (CLOSED, OPEN, HALF-OPEN) and cumulative trip count
      6. Idempotency Cache Hit counter
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
import redis.asyncio as aioredis

from app.config import settings
from app.core.dependencies import get_db_dep, get_redis_dep
from app.models.responses import (
    LatencyPercentiles,
    RPSBreakdown,
    SuccessResponse,
    SystemMetricsResponse,
)
from app.services import circuit_breaker, metrics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/metrics", tags=["Metrics"])


@router.get(
    "/system-load",
    response_model=SystemMetricsResponse,
    summary="Real-time System Load & Telemetry",
    description=(
        "Returns continuous operational metrics for monitoring and evaluation:\n"
        "• Concurrency & Queue: active Fast slots (max 5) and Redis queue depth (max 50)\n"
        "• Resiliency: Circuit Breaker state (CLOSED/OPEN/HALF-OPEN), trips, fault mode\n"
        "• Performance: p50 & p95 latencies and throughput split by HTTP status\n"
        "• Efficiency: Idempotency deduplication cache hits"
    ),
    responses={
        200: {"model": SystemMetricsResponse, "description": "Current system metrics"},
    },
)
async def get_system_load(
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> SystemMetricsResponse:
    # 1. Concurrency and Queue Depth
    raw_concurrency = await redis.get(settings.REDIS_CONCURRENCY_KEY)
    active_concurrency = max(0, int(raw_concurrency)) if raw_concurrency else 0
    queue_depth = await redis.llen(settings.REDIS_QUEUE_KEY)

    # 2. Circuit Breaker State & Telemetry
    cb_state = await circuit_breaker.get_state(redis, db)
    trip_count = await circuit_breaker.get_trip_count(redis)
    fault_active = await circuit_breaker.is_fault_injection_active(redis)

    # 3. Idempotency Cache Hits
    cache_hits = await metrics.get_cache_hits(redis)

    # 4. RPS Status Code Breakdown
    rps_data = await metrics.get_rps_breakdown(redis)

    # 5. Latency Percentiles (p50 and p95)
    latency_data = await metrics.get_latency_percentiles(redis)

    return SystemMetricsResponse(
        active_fast_concurrency=active_concurrency,
        fast_model_max_concurrency=settings.FAST_MODEL_MAX_CONCURRENCY,
        redis_queue_depth=queue_depth,
        max_queue_depth=settings.MAX_QUEUE_DEPTH,
        circuit_breaker_state=cb_state,
        circuit_breaker_trip_count=trip_count,
        fault_injection_active=fault_active,
        idempotency_cache_hits=cache_hits,
        rps=RPSBreakdown(**rps_data),
        latency=LatencyPercentiles(**latency_data),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/reset",
    response_model=SuccessResponse,
    summary="Reset Metrics Telemetry",
    description="Resets RPS counters, latency percentiles, and cache hit metrics in Redis.",
)
async def reset_system_metrics(
    redis: aioredis.Redis = Depends(get_redis_dep),
) -> SuccessResponse:
    await metrics.reset_metrics(redis)
    logger.info("System load metrics reset by request.")
    return SuccessResponse(
        success=True,
        message="System telemetry metrics (RPS, latency samples, cache hits) have been reset.",
    )

