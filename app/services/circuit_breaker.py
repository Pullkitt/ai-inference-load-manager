"""
app/services/circuit_breaker.py
───────────────────────────────
Circuit Breaker state machine for Fast Model failure isolation and self-healing.

SRS §2.1 Step 6, §5.1, and FR-9:
  - CLOSED (Normal): Fast requests execute synchronously.
  - OPEN (Failing): If Fast Model fails 5 times within a 10s window, the circuit
    trips to OPEN for 30 seconds. Fast requests are automatically diverted to the
    background Redis queue with 202 Accepted (Graceful Degradation: zero 500 errors).
  - HALF-OPEN (Testing): After 30 seconds cooldown, 1 probe request is permitted through.
    If it succeeds, transitions back to CLOSED. If it fails, resets to OPEN for another 30s.

Features:
  - Rolling window failure tracking in Redis using sorted sets (ZSET).
  - Automatic audit logging to MongoDB `system_audit_logs`.
  - Fault injection toggle support for viva / grading evaluation demonstrations.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Optional

import redis.asyncio as aioredis
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.crud.inference import write_audit_log
from app.models.audit import AuditEventType

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF-OPEN"


async def get_state(
    redis: aioredis.Redis,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> str:
    """
    Query the current circuit breaker state.
    Handles automatic self-healing transition from OPEN to HALF-OPEN after
    settings.CB_RECOVERY_TIMEOUT_SEC (30s) elapses.
    """
    try:
        current_state = await redis.get(settings.REDIS_CB_STATE_KEY)
        if not current_state:
            current_state = CircuitState.CLOSED.value
            await redis.set(settings.REDIS_CB_STATE_KEY, current_state)

        if current_state == CircuitState.OPEN.value:
            open_since_val = await redis.get(settings.REDIS_CB_OPEN_SINCE_KEY)
            open_since = float(open_since_val) if open_since_val else 0.0
            elapsed = time.time() - open_since

            if elapsed >= settings.CB_RECOVERY_TIMEOUT_SEC:
                # 30-second cooldown elapsed: transition to HALF-OPEN for recovery probe
                new_state = CircuitState.HALF_OPEN.value
                await redis.set(settings.REDIS_CB_STATE_KEY, new_state)
                logger.info(
                    "Circuit Breaker transitioned: OPEN -> HALF-OPEN (probe ready after %.1fs)",
                    elapsed,
                )
                if db is not None:
                    await write_audit_log(
                        db,
                        event_type=AuditEventType.CIRCUIT_HALF_OPEN.value,
                        details={
                            "cooldown_seconds": elapsed,
                            "reason": "recovery_timeout_elapsed",
                        },
                    )
                return new_state

        return current_state
    except Exception as exc:
        logger.warning("Error fetching circuit breaker state: %s", exc)
        return CircuitState.CLOSED.value


async def record_failure(
    redis: aioredis.Redis,
    db: Optional[AsyncIOMotorDatabase] = None,
    reason: str = "fast_model_failure",
) -> str:
    """
    Record a failure in the Fast Model.
    - If in HALF-OPEN: probe failed -> reopens circuit for 30s.
    - If in CLOSED: records failure in rolling window. Trips to OPEN if >= 5 failures in 10s.
    """
    now = time.time()
    try:
        current_state = await get_state(redis, db)

        if current_state == CircuitState.HALF_OPEN.value:
            # Probe request failed -> Trip back to OPEN for another recovery period
            await redis.set(settings.REDIS_CB_STATE_KEY, CircuitState.OPEN.value)
            await redis.set(settings.REDIS_CB_OPEN_SINCE_KEY, str(now))
            await redis.incr(settings.REDIS_CB_TRIP_COUNT_KEY)
            logger.warning("Circuit Breaker probe failed: HALF-OPEN -> OPEN (reset 30s)")
            if db is not None:
                await write_audit_log(
                    db,
                    event_type=AuditEventType.CIRCUIT_OPENED.value,
                    details={
                        "previous_state": "HALF-OPEN",
                        "reason": "probe_request_failed",
                        "trigger": reason,
                    },
                )
            return CircuitState.OPEN.value

        if current_state == CircuitState.CLOSED.value:
            member = f"{now}:{uuid.uuid4().hex[:6]}"
            pipe = redis.pipeline(transaction=True)
            # 1. Clean out timestamps older than the failure window
            pipe.zremrangebyscore(
                settings.REDIS_CB_FAILURES_KEY, "-inf", now - settings.CB_FAILURE_WINDOW_SEC
            )
            # 2. Add current failure timestamp
            pipe.zadd(settings.REDIS_CB_FAILURES_KEY, {member: now})
            # 3. Set key expiration to window + 5s
            pipe.expire(settings.REDIS_CB_FAILURES_KEY, settings.CB_FAILURE_WINDOW_SEC + 5)
            # 4. Count failures in this window
            pipe.zcard(settings.REDIS_CB_FAILURES_KEY)
            results = await pipe.execute()
            failures_count = int(results[3])

            logger.info(
                "Circuit Breaker failure recorded: %d/%d in %ds window",
                failures_count,
                settings.CB_FAILURE_THRESHOLD,
                settings.CB_FAILURE_WINDOW_SEC,
            )

            if failures_count >= settings.CB_FAILURE_THRESHOLD:
                # Threshold reached -> Trip to OPEN!
                await redis.set(settings.REDIS_CB_STATE_KEY, CircuitState.OPEN.value)
                await redis.set(settings.REDIS_CB_OPEN_SINCE_KEY, str(now))
                trip_count = await redis.incr(settings.REDIS_CB_TRIP_COUNT_KEY)
                logger.error(
                    "CIRCUIT BREAKER TRIPPED to OPEN! (%d failures in %ds window, trip #%d)",
                    failures_count,
                    settings.CB_FAILURE_WINDOW_SEC,
                    trip_count,
                )
                if db is not None:
                    await write_audit_log(
                        db,
                        event_type=AuditEventType.CIRCUIT_OPENED.value,
                        details={
                            "previous_state": "CLOSED",
                            "failures_count": failures_count,
                            "window_sec": settings.CB_FAILURE_WINDOW_SEC,
                            "trip_count": trip_count,
                            "reason": f"{failures_count} failures in {settings.CB_FAILURE_WINDOW_SEC}s",
                        },
                    )
                return CircuitState.OPEN.value

            return CircuitState.CLOSED.value

        return current_state
    except Exception as exc:
        logger.error("Failed to record circuit breaker failure: %s", exc)
        return CircuitState.CLOSED.value


async def record_success(
    redis: aioredis.Redis,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> str:
    """
    Record a successful Fast Model execution.
    If the circuit was in HALF-OPEN, probe succeeded -> reset circuit back to CLOSED.
    """
    try:
        current_state = await redis.get(settings.REDIS_CB_STATE_KEY)
        if current_state == CircuitState.HALF_OPEN.value:
            await redis.set(settings.REDIS_CB_STATE_KEY, CircuitState.CLOSED.value)
            await redis.delete(
                settings.REDIS_CB_FAILURES_KEY, settings.REDIS_CB_OPEN_SINCE_KEY
            )
            logger.info("Circuit Breaker probe succeeded: HALF-OPEN -> CLOSED (healthy)")
            if db is not None:
                await write_audit_log(
                    db,
                    event_type=AuditEventType.CIRCUIT_RESET.value,
                    details={
                        "previous_state": "HALF-OPEN",
                        "reason": "half_open_probe_succeeded",
                    },
                )
            return CircuitState.CLOSED.value

        return CircuitState.CLOSED.value
    except Exception as exc:
        logger.warning("Error recording circuit breaker success: %s", exc)
        return CircuitState.CLOSED.value


async def reset_circuit_breaker(
    redis: aioredis.Redis,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> None:
    """Manually reset the Circuit Breaker to CLOSED (used by admin or tests)."""
    try:
        await redis.set(settings.REDIS_CB_STATE_KEY, CircuitState.CLOSED.value)
        await redis.delete(
            settings.REDIS_CB_FAILURES_KEY, settings.REDIS_CB_OPEN_SINCE_KEY
        )
        logger.info("Circuit Breaker manually reset to CLOSED")
        if db is not None:
            await write_audit_log(
                db,
                event_type=AuditEventType.CIRCUIT_RESET.value,
                details={"reason": "manual_admin_reset"},
            )
    except Exception as exc:
        logger.warning("Failed to reset circuit breaker: %s", exc)


async def set_fault_injection(
    redis: aioredis.Redis,
    enable: bool,
    db: Optional[AsyncIOMotorDatabase] = None,
) -> bool:
    """
    Toggle simulated failure injection on the Fast Model.
    When enabled=True, subsequent fast requests will simulate 500 errors,
    triggering the Circuit Breaker to trip to OPEN.
    """
    try:
        await redis.set(settings.REDIS_FAULT_INJECT_KEY, "1" if enable else "0")
        logger.info("Fault injection set to: %s", enable)
        if db is not None:
            event = (
                AuditEventType.FAULT_INJECTED.value
                if enable
                else AuditEventType.FAULT_CLEARED.value
            )
            await write_audit_log(
                db,
                event_type=event,
                details={"fault_injection_active": enable},
            )
        return enable
    except Exception as exc:
        logger.warning("Failed to set fault injection: %s", exc)
        return False


async def is_fault_injection_active(redis: aioredis.Redis) -> bool:
    """Check if fault injection mode is currently active in Redis."""
    try:
        val = await redis.get(settings.REDIS_FAULT_INJECT_KEY)
        return val == "1"
    except Exception:
        return False


async def get_trip_count(redis: aioredis.Redis) -> int:
    """Return the total number of times the circuit breaker has tripped to OPEN."""
    try:
        val = await redis.get(settings.REDIS_CB_TRIP_COUNT_KEY)
        return int(val) if val else 0
    except Exception:
        return 0

