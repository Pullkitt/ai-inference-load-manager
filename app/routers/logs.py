"""
app/routers/logs.py
───────────────────
Historical logging & audit trail endpoints.

SRS §3.2, §3.3:
  - GET /api/logs/history:
    Fetches historical raw requests (`inference_requests`), processed outputs
    (`inference_results`), and system audit logs (`system_audit_logs`).
    Scoped to the authenticated user; administrators receive a system-wide view.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import get_current_user, get_db_dep
from app.crud.inference import (
    get_all_requests,
    get_all_results,
    get_audit_logs,
    get_user_requests,
    get_user_results,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/logs", tags=["Logs"])


@router.get(
    "/history",
    summary="Fetch Historical Requests, Results & Audit Logs",
    description=(
        "Retrieves historical data across MongoDB collections:\n"
        "• `inference_requests`: Ingested payloads and execution status\n"
        "• `inference_results`: Computed outputs, latencies, and models used\n"
        "• `system_audit_logs`: Circuit breaker trips, resets, overload events, and faults\n"
        "Scoped to the authenticated user; administrators have system-wide visibility."
    ),
    responses={
        200: {"description": "Historical log entries and audit events"},
        401: {"description": "Authentication required"},
    },
)
async def get_history(
    limit: int = Query(50, ge=1, le=200, description="Max entries to retrieve per category"),
    event_type: Optional[str] = Query(None, description="Filter audit logs by event_type"),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
) -> Dict[str, Any]:
    user_id = current_user["user_id"]
    is_admin = current_user.get("role") == "admin"

    # 1. Fetch Requests & Results
    if is_admin:
        requests = await get_all_requests(db, limit=limit)
        results = await get_all_results(db, limit=limit)
    else:
        requests = await get_user_requests(db, user_id=user_id, limit=limit)
        results = await get_user_results(db, user_id=user_id, limit=limit)

    # 2. Fetch System Audit Logs (circuit breaker, backpressure, faults)
    audit_logs = await get_audit_logs(db, limit=limit, event_type=event_type)

    return {
        "user_id": user_id,
        "role": current_user.get("role", "user"),
        "total_requests": len(requests),
        "total_results": len(results),
        "total_audit_logs": len(audit_logs),
        "requests": requests,
        "results": results,
        "audit_logs": audit_logs,
    }

