"""
app/routers/admin.py
────────────────────
Administrative and viva demonstration endpoints.

SRS §3.2, §5.1, and NFR-S3:
  - POST /admin/fail-fast-model:
    Enforces Role-Based Access Control (RBAC); rejects non-admins with 403 Forbidden.
    Toggles simulated failures on the Fast Model to demonstrate the Circuit Breaker
    transitioning from CLOSED to OPEN and auto-recovering in HALF-OPEN.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
import redis.asyncio as aioredis

from app.core.dependencies import get_db_dep, get_redis_dep, require_admin
from app.models.responses import FaultInjectionResponse, SuccessResponse
from app.services import circuit_breaker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post(
    "/fail-fast-model",
    response_model=FaultInjectionResponse,
    summary="Toggle Fast Model Fault Injection (Viva Demonstration)",
    description=(
        "Admin-only endpoint enforcing RBAC (returns 403 Forbidden for non-admins).\n"
        "Toggles simulated 500 errors on the Fast Model to demonstrate the Circuit Breaker.\n"
        "When active, the next 5 fast requests trigger failures, automatically tripping the "
        "Circuit Breaker from CLOSED to OPEN, diverting traffic to the flexible queue without "
        "dropping client requests."
    ),
    responses={
        200: {"model": FaultInjectionResponse, "description": "Fault injection state updated"},
        403: {"description": "Admin privileges required"},
    },
)
async def toggle_fault_injection(
    enable: bool = Query(True, description="Set true to inject errors; false to clear fault"),
    current_admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
    redis: aioredis.Redis = Depends(get_redis_dep),
):
    await circuit_breaker.set_fault_injection(redis, enable=enable, db=db)
    cb_state = await circuit_breaker.get_state(redis, db)

    action_str = "ENABLED (Fast Model will simulate 500 errors)" if enable else "DISABLED (Fast Model restored)"
    logger.info("Admin %s updated fault injection: %s", current_admin.get("username"), action_str)

    return FaultInjectionResponse(
        message=f"Fast Model fault injection {action_str}.",
        fault_injection_active=enable,
        circuit_breaker_state=cb_state,
        note=(
            "When fault injection is active, the next 5 fast requests will fail, "
            "tripping the Circuit Breaker to OPEN."
            if enable
            else "Fault cleared. The circuit breaker can now self-heal or be reset."
        ),
    )


@router.post(
    "/reset-circuit-breaker",
    response_model=SuccessResponse,
    summary="Reset Circuit Breaker to CLOSED State",
    description="Admin-only utility to manually restore the circuit breaker to CLOSED status.",
)
async def reset_circuit(
    current_admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
    redis: aioredis.Redis = Depends(get_redis_dep),
):
    await circuit_breaker.reset_circuit_breaker(redis, db)
    await circuit_breaker.set_fault_injection(redis, enable=False, db=db)
    return SuccessResponse(
        success=True,
        message="Circuit Breaker has been reset to CLOSED and fault injection disabled.",
    )

