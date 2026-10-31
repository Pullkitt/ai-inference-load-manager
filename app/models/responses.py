"""
app/models/responses.py
────────────────────────
Shared API response envelopes and error models used across all routers.

Keeps response shapes consistent and simplifies OpenAPI documentation.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Generic Envelopes
# =============================================================================

class SuccessResponse(BaseModel):
    """Generic success envelope for simple acknowledgement responses."""

    success: bool = True
    message: str
    data: Optional[dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """
    Standard error envelope — returned for 400, 401, 403, 404, 429, 503.
    Always include `detail` for debugging.
    """

    success: bool = False
    error: str = Field(..., description="Short machine-readable error code")
    detail: str = Field(..., description="Human-readable error description")
    retry_after: Optional[int] = Field(
        None,
        description="Seconds to wait before retrying (populated on 429 and 503)",
    )


# =============================================================================
# Health Check Response (mirrored here for OpenAPI typing)
# =============================================================================

class ComponentStatus(BaseModel):
    status: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    service: str
    version: str
    status: str   # healthy | degraded
    timestamp: str
    components: dict[str, Any]


# =============================================================================
# Fault Injection Response — POST /admin/fail-fast-model
# =============================================================================

class FaultInjectionResponse(BaseModel):
    """Response for POST /admin/fail-fast-model"""

    message: str
    fault_injection_active: bool
    circuit_breaker_state: str
    note: str = (
        "When fault injection is active, the next 5 fast requests will fail, "
        "tripping the Circuit Breaker to OPEN."
    )


# =============================================================================
# Metrics Response — GET /api/metrics/system-load
# =============================================================================

class LatencyPercentiles(BaseModel):
    p50_ms: float = 0.0
    p95_ms: float = 0.0


class RPSBreakdown(BaseModel):
    status_200: int = 0
    status_202: int = 0
    status_429: int = 0
    status_503: int = 0
    total: int = 0


class SystemMetricsResponse(BaseModel):
    """Full payload for GET /api/metrics/system-load (SRS §5.3)"""

    active_fast_concurrency: int
    fast_model_max_concurrency: int
    redis_queue_depth: int
    max_queue_depth: int
    circuit_breaker_state: str           # CLOSED | OPEN | HALF_OPEN
    circuit_breaker_trip_count: int
    fault_injection_active: bool
    idempotency_cache_hits: int
    rps: RPSBreakdown
    latency: LatencyPercentiles
    timestamp: str

