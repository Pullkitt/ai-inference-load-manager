"""
app/models/audit.py
───────────────────
System audit log document — stored in `system_audit_logs` collection.

SRS §3.3 Collection 4:
  log_id, event_type (CIRCUIT_OPENED | CIRCUIT_RESET | FAULT_INJECTED |
  OVERLOAD_503), details, timestamp
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Audit Event Types (SRS §3.3)
# =============================================================================

class AuditEventType(str, Enum):
    CIRCUIT_OPENED = "CIRCUIT_OPENED"     # CB transitioned CLOSED → OPEN
    CIRCUIT_RESET = "CIRCUIT_RESET"       # CB transitioned OPEN/HALF_OPEN → CLOSED
    CIRCUIT_HALF_OPEN = "CIRCUIT_HALF_OPEN"  # CB transitioned OPEN → HALF_OPEN
    FAULT_INJECTED = "FAULT_INJECTED"     # Admin toggled fault injection ON
    FAULT_CLEARED = "FAULT_CLEARED"       # Admin toggled fault injection OFF
    OVERLOAD_503 = "OVERLOAD_503"         # Queue exceeded MAX_QUEUE_DEPTH → 503
    RATE_LIMIT_429 = "RATE_LIMIT_429"     # User exceeded RATE_LIMIT_PER_MIN → 429
    USER_REGISTERED = "USER_REGISTERED"   # New user account created
    WORKER_STARTED = "WORKER_STARTED"     # Background worker process started
    WORKER_ERROR = "WORKER_ERROR"         # Worker failed to process a task


# =============================================================================
# MongoDB Document — system_audit_logs collection
# =============================================================================

class AuditLogDocument(BaseModel):
    """
    Immutable audit log entry.  Write-once; never updated after insertion.
    """

    log_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID for this audit log entry",
    )
    event_type: str = Field(
        ...,
        description=(
            "Type of system event: CIRCUIT_OPENED | CIRCUIT_RESET | "
            "FAULT_INJECTED | FAULT_CLEARED | OVERLOAD_503 | RATE_LIMIT_429 | "
            "USER_REGISTERED | WORKER_STARTED | WORKER_ERROR"
        ),
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value context for the event (user_id, counts, etc.)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    model_config = {"use_enum_values": True}


# =============================================================================
# API Response Schema — GET /api/logs/history (audit section)
# =============================================================================

class AuditLogResponse(BaseModel):
    """Public-safe audit log entry returned by GET /api/logs/history."""

    log_id: str
    event_type: str
    details: dict[str, Any]
    timestamp: datetime

