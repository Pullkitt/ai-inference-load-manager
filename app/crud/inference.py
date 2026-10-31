"""
app/crud/inference.py
─────────────────────
Async MongoDB CRUD helpers for:
  • inference_requests  — raw event documents
  • inference_results   — processed output documents
  • system_audit_logs   — immutable audit trail

All functions accept a Motor `AsyncIOMotorDatabase` handle.
"""

from __future__ import annotations

from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.audit import AuditLogDocument
from app.models.inference import (
    InferenceRequestDocument,
    InferenceResultDocument,
)


# =============================================================================
# inference_requests CRUD
# =============================================================================

async def create_inference_request(
    db: AsyncIOMotorDatabase,
    request: InferenceRequestDocument,
) -> str:
    """
    Insert a new inference request document.
    Returns the request_id (used as task_id for polling).
    """
    doc = request.model_dump()
    await db.inference_requests.insert_one(doc)
    return request.request_id


async def get_inference_request(
    db: AsyncIOMotorDatabase,
    request_id: str,
) -> Optional[dict[str, Any]]:
    """
    Fetch a single inference request document by request_id.
    Returns None if not found.
    """
    return await db.inference_requests.find_one(
        {"request_id": request_id},
        {"_id": 0},
    )


async def update_request_status(
    db: AsyncIOMotorDatabase,
    request_id: str,
    status: str,
) -> None:
    """
    Update the `status` field of an inference request in-place.
    Called by the worker when a task transitions states.
    """
    await db.inference_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": status}},
    )


async def get_user_requests(
    db: AsyncIOMotorDatabase,
    user_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Fetch the most recent `limit` inference requests for a user.
    Returns newest first (descending submitted_at).
    """
    cursor = (
        db.inference_requests.find(
            {"user_id": user_id},
            {"_id": 0},
        )
        .sort("submitted_at", -1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


# =============================================================================
# inference_results CRUD
# =============================================================================

async def create_inference_result(
    db: AsyncIOMotorDatabase,
    result: InferenceResultDocument,
) -> str:
    """
    Insert a processed result document.
    Returns the result_id.
    """
    doc = result.model_dump()
    await db.inference_results.insert_one(doc)
    return result.result_id


async def get_result_by_request_id(
    db: AsyncIOMotorDatabase,
    request_id: str,
) -> Optional[dict[str, Any]]:
    """
    Fetch the inference result for a given request_id.
    Returns None if the task is not yet completed.
    """
    return await db.inference_results.find_one(
        {"request_id": request_id},
        {"_id": 0},
    )


async def get_user_results(
    db: AsyncIOMotorDatabase,
    user_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Fetch the most recent `limit` inference results belonging to the user
    (via a lookup through inference_requests).
    Performs an aggregation pipeline join.
    """
    pipeline = [
        # Step 1: get request IDs for this user
        {
            "$lookup": {
                "from": "inference_results",
                "localField": "request_id",
                "foreignField": "request_id",
                "as": "result",
            }
        },
        {"$match": {"user_id": user_id}},
        {"$unwind": {"path": "$result", "preserveNullAndEmptyArrays": True}},
        {"$sort": {"submitted_at": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0}},
    ]
    cursor = db.inference_requests.aggregate(pipeline)
    return await cursor.to_list(length=limit)


# =============================================================================
# system_audit_logs CRUD
# =============================================================================

async def write_audit_log(
    db: AsyncIOMotorDatabase,
    event_type: str,
    details: dict[str, Any],
) -> str:
    """
    Write an immutable audit log entry.
    Returns log_id.

    Usage:
        await write_audit_log(db, AuditEventType.CIRCUIT_OPENED, {
            "trip_count": 3,
            "triggered_by": request_id,
        })
    """
    log = AuditLogDocument(event_type=event_type, details=details)
    await db.system_audit_logs.insert_one(log.model_dump())
    return log.log_id


async def get_audit_logs(
    db: AsyncIOMotorDatabase,
    limit: int = 100,
    event_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Fetch the most recent audit log entries, newest first.
    Optionally filter by event_type.
    """
    query: dict[str, Any] = {}
    if event_type:
        query["event_type"] = event_type

    cursor = (
        db.system_audit_logs.find(query, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


# =============================================================================
# Index Bootstrapping
# =============================================================================

async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create indexes for inference_requests and inference_results.
    Safe to call multiple times at startup.
    """
    # inference_requests
    await db.inference_requests.create_index(
        "request_id", unique=True, background=True
    )
    await db.inference_requests.create_index("user_id", background=True)
    await db.inference_requests.create_index("idempotency_hash", background=True)
    await db.inference_requests.create_index("status", background=True)

    # inference_results
    await db.inference_results.create_index(
        "result_id", unique=True, background=True
    )
    await db.inference_results.create_index("request_id", background=True)

    # system_audit_logs
    await db.system_audit_logs.create_index("timestamp", background=True)
    await db.system_audit_logs.create_index("event_type", background=True)

