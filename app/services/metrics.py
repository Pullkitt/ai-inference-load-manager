"""
app/services/metrics.py
───────────────────────
Redis telemetry and metrics collection helpers.

SRS §5.3 Measurable Metrics & Logging:
  - RPS Breakdown: split by HTTP status codes (200, 202, 429, 503)
  - Latencies (p50, p95) in milliseconds
  - Idempotency Cache Hits counter
  - Active Concurrency and Queue Depth tracking helpers
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

# Maximum latency samples stored in Redis for rolling p50/p95 calculations
MAX_LATENCY_SAMPLES = 1000


async def record_request_status(
    redis: aioredis.Redis,
    status_code: int,
) -> None:
    """
    Increment the corresponding status code counter in Redis for RPS & throughput metrics.
    Supported key tracking: status_200, status_202, status_429, status_503, total.
    """
    field_name = f"status_{status_code}"
    pipe = redis.pipeline(transaction=False)
    pipe.hincrby(settings.REDIS_RPS_KEY, field_name, 1)
    pipe.hincrby(settings.REDIS_RPS_KEY, "total", 1)
    try:
        await pipe.execute()
    except Exception as exc:
        logger.warning("Failed to record request status in Redis: %s", exc)


async def record_latency(
    redis: aioredis.Redis,
    latency_ms: float,
) -> None:
    """
    Record an inference or routing latency measurement (in milliseconds).
    Keeps the list capped at MAX_LATENCY_SAMPLES to prevent unbounded memory growth.
    """
    pipe = redis.pipeline(transaction=False)
    pipe.rpush(settings.REDIS_LATENCY_KEY, round(latency_ms, 2))
    pipe.ltrim(settings.REDIS_LATENCY_KEY, -MAX_LATENCY_SAMPLES, -1)
    try:
        await pipe.execute()
    except Exception as exc:
        logger.warning("Failed to record latency metric in Redis: %s", exc)


async def increment_cache_hit(redis: aioredis.Redis) -> int:
    """Increment and return the idempotency cache hit counter."""
    try:
        return await redis.incr(settings.REDIS_CACHE_HIT_KEY)
    except Exception as exc:
        logger.warning("Failed to increment cache hits in Redis: %s", exc)
        return 0


async def get_cache_hits(redis: aioredis.Redis) -> int:
    """Get the current count of idempotency cache hits."""
    try:
        val = await redis.get(settings.REDIS_CACHE_HIT_KEY)
        return int(val) if val else 0
    except Exception as exc:
        logger.warning("Failed to get cache hits from Redis: %s", exc)
        return 0


async def get_rps_breakdown(redis: aioredis.Redis) -> Dict[str, int]:
    """
    Retrieve counts of responses broken down by HTTP status codes:
    200, 202, 429, 503 and total.
    """
    defaults = {
        "status_200": 0,
        "status_202": 0,
        "status_429": 0,
        "status_503": 0,
        "total": 0,
    }
    try:
        raw_map = await redis.hgetall(settings.REDIS_RPS_KEY)
        if not raw_map:
            return defaults
        return {
            "status_200": int(raw_map.get("status_200", 0)),
            "status_202": int(raw_map.get("status_202", 0)),
            "status_429": int(raw_map.get("status_429", 0)),
            "status_503": int(raw_map.get("status_503", 0)),
            "total": int(raw_map.get("total", 0)),
        }
    except Exception as exc:
        logger.warning("Failed to get RPS breakdown: %s", exc)
        return defaults


async def get_latency_percentiles(redis: aioredis.Redis) -> Dict[str, float]:
    """
    Calculate 50th (median) and 95th percentile latencies from recent samples.
    """
    try:
        raw_list = await redis.lrange(settings.REDIS_LATENCY_KEY, 0, -1)
        if not raw_list:
            return {"p50_ms": 0.0, "p95_ms": 0.0}

        samples = sorted([float(x) for x in raw_list])
        n = len(samples)

        p50_idx = int(0.50 * (n - 1))
        p95_idx = int(0.95 * (n - 1))

        return {
            "p50_ms": round(samples[p50_idx], 2),
            "p95_ms": round(samples[p95_idx], 2),
        }
    except Exception as exc:
        logger.warning("Failed to calculate latency percentiles: %s", exc)
        return {"p50_ms": 0.0, "p95_ms": 0.0}


async def reset_metrics(redis: aioredis.Redis) -> None:
    """Reset all tracked metrics in Redis (useful for load testing benchmarks)."""
    keys = [
        settings.REDIS_CACHE_HIT_KEY,
        settings.REDIS_LATENCY_KEY,
        settings.REDIS_RPS_KEY,
    ]
    try:
        await redis.delete(*keys)
    except Exception as exc:
        logger.warning("Failed to reset metrics: %s", exc)

