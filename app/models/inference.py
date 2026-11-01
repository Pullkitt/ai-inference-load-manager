"""
app/models/inference.py
───────────────────────
Pydantic schemas for inference requests, results, and the API predict body.

SRS §3.3 Collections 2 & 3:
  • inference_requests  — raw events, one doc per incoming request
  • inference_results   — processed outputs written by the worker
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.domains import DomainPayload


# =============================================================================
# Enums — kept as str enums for MongoDB serialisation compatibility
# =============================================================================

class LatencyPreference(str, Enum):
    FAST = "fast"
    FLEXIBLE = "flexible"


class RequestStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelUsed(str, Enum):
    FAST = "fast_model"
    SLOW = "slow_model"


class RoutingReason(str, Enum):
    FAST_PATH = "fast_path"                              # executed synchronously on Fast Model
    LATENCY_FLEXIBLE = "latency_preference_flexible"    # client explicitly chose flexible
    FALLBACK_QUEUE = "fallback_queue"                   # fast busy → diverted to queue
    CB_OPEN = "circuit_breaker_open"                    # circuit OPEN → diverted to queue
    CONCURRENCY_LIMIT = "concurrency_limit_reached"     # 5 slots full → diverted to queue
    HALF_OPEN_PROBE = "half_open_probe"                 # probe request in HALF-OPEN state
    IDEMPOTENT_CACHE_HIT = "idempotent_cache_hit"       # returned from cache, no compute


# =============================================================================
# API Request Body — POST /api/inference/predict
# =============================================================================

class PredictRequest(BaseModel):
    """
    Main inference request body (SRS §3.2, FR-4 / FR-5).

    The `payload.domain` discriminator field tells Pydantic which of the four
    domain sub-schemas to validate against, giving strict per-domain validation.

    Example (IoT fast path):
        {
          "latency_preference": "fast",
          "payload": {
            "domain": "iot",
            "device_id": "sensor_001",
            "sensor_type": "temperature",
            "reading_array": [23.4, 23.6],
            "timestamp": "2026-11-01T00:00:00Z"
          }
        }

    Example (NLP flexible path):
        {
          "latency_preference": "flexible",
          "payload": {
            "domain": "ai_nlp",
            "prompt_tokens": 128,
            "temperature": 0.7,
            "input_text": "Analyse this review..."
          }
        }
    """

    latency_preference: LatencyPreference = Field(
        ...,
        description=(
            "'fast' → attempt synchronous Fast Model (0.1–0.2s); "
            "'flexible' → always enqueue for background Slow Model (3–4s)"
        ),
    )
    payload: DomainPayload = Field(
        ...,
        description=(
            "Domain-specific inference payload. "
            "The `domain` field acts as the discriminator: "
            "iot | mobile_media | geospatial | ai_nlp"
        ),
    )


# =============================================================================
# MongoDB Document — inference_requests collection  (SRS §3.3 Collection 2)
# =============================================================================

class InferenceRequestDocument(BaseModel):
    """
    Raw event document stored in `inference_requests` on every incoming call.
    Updated in-place when status changes (queued → processing → completed).
    """

    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID for this inference request — returned to client as task_id",
    )
    user_id: str = Field(..., description="UUID of the authenticated user")
    idempotency_hash: str = Field(
        ...,
        description="SHA-256 of user_id + canonical JSON payload (used for dedup)",
    )
    domain: str = Field(..., description="Payload domain: iot | mobile_media | geospatial | ai_nlp")
    latency_preference: str = Field(..., description="fast | flexible")
    raw_payload: dict[str, Any] = Field(
        ...,
        description="Full raw payload dict as received (stored for audit / replay)",
    )
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: str = Field(
        default=RequestStatus.QUEUED.value,
        description="queued | processing | completed | failed",
    )
    model_used: Optional[str] = Field(
        default=None,
        description="fast_model | slow_model",
    )
    routing_reason: Optional[str] = Field(
        default=None,
        description="Reason for the routing decision",
    )

    model_config = {"use_enum_values": True}


# =============================================================================
# MongoDB Document — inference_results collection  (SRS §3.3 Collection 3)
# =============================================================================

class InferenceResultDocument(BaseModel):
    """
    Processed output written by the Fast Model (inline) or the background
    worker (async), and persisted to `inference_results`.
    """

    result_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
    )
    request_id: str = Field(
        ...,
        description="FK → inference_requests.request_id",
    )
    model_used: str = Field(
        ...,
        description="fast_model | slow_model",
    )
    routing_reason: str = Field(
        ...,
        description="Why this path was chosen (fast_path, fallback_queue, etc.)",
    )
    processing_time_ms: float = Field(
        ...,
        description="Wall-clock time from model entry to result (milliseconds)",
    )
    output_data: dict[str, Any] = Field(
        ...,
        description="Domain-specific inference output (simulated results)",
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = {"use_enum_values": True}


# =============================================================================
# API Response Schemas
# =============================================================================

class PredictFastResponse(BaseModel):
    """HTTP 200 — Fast Model synchronous result."""

    status: str = "success"
    request_id: str
    model_used: str = ModelUsed.FAST.value
    routing_reason: str
    processing_time_ms: float
    output_data: dict[str, Any]
    cached: bool = False


class PredictQueuedResponse(BaseModel):
    """HTTP 202 — Request accepted and enqueued for background processing."""

    status: str = "queued"
    request_id: str
    task_id: str
    routing_reason: str
    message: str = "Request accepted. Poll /api/inference/status/{task_id} for results."
    cached: bool = False


class TaskStatusResponse(BaseModel):
    """HTTP 200 — Status poll for a queued / completed task."""

    task_id: str
    status: str        # queued | processing | completed | failed
    domain: str
    latency_preference: str
    submitted_at: datetime
    result: Optional[dict[str, Any]] = None   # None until completed

