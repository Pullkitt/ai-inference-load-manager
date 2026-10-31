"""
app/core/dependencies.py
─────────────────────────
FastAPI dependency functions for authentication and RBAC.

Two auth strategies are supported (SRS §3.2.1 FR-1):
  1. JWT Bearer token  — Authorization: Bearer <token>
  2. API Key header    — X-API-Key: <64-char hex key>

The dependency tries JWT first, then falls back to the API key.
If neither is present or valid → HTTP 401 Unauthorized.

RBAC:
  • `require_admin` — wraps `get_current_user`, raises 403 if role != 'admin'.

Database handles are injected via simple synchronous getter dependencies
(Motor + redis.asyncio are already connected at startup).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.security import decode_access_token
from app.crud.users import get_user_by_api_key, get_user_by_id
from app.database import get_db, get_redis

import redis.asyncio as aioredis

# =============================================================================
# FastAPI Security Schemes
# =============================================================================

_http_bearer = HTTPBearer(
    scheme_name="JWT Bearer Token",
    description="Paste the JWT access_token from /api/auth/login or /api/auth/register",
    auto_error=False,   # Don't auto-raise 403 — we handle errors ourselves
)

_api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="API Key Header",
    description="32-byte hex API key returned at registration (X-API-Key header)",
    auto_error=False,   # Don't auto-raise 403 — we handle errors ourselves
)


# =============================================================================
# Database Dependency Helpers
# =============================================================================

def get_db_dep() -> AsyncIOMotorDatabase:
    """FastAPI dependency that returns the active Motor database handle."""
    return get_db()


def get_redis_dep() -> aioredis.Redis:
    """FastAPI dependency that returns the active Redis client."""
    return get_redis()


# =============================================================================
# Core Auth Dependency  (SRS §3.2.1 FR-1)
# =============================================================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_http_bearer),
    api_key: Optional[str] = Security(_api_key_header),
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
) -> dict:
    """
    Dual-strategy authentication dependency.

    Resolution order:
      1. If an `Authorization: Bearer <token>` header is present:
         - Decode the JWT.
         - Extract the `sub` (user_id) claim.
         - Fetch the user document from MongoDB.
         - Return the user dict on success.
      2. If an `X-API-Key` header is present:
         - Look up the key in the `users` collection.
         - Return the user dict on success.
      3. If neither is present or both fail → HTTP 401.

    Returns:
        The full user document dict (including `role` for RBAC checks).
    """
    # ── Strategy 1: JWT Bearer ─────────────────────────────────────────────
    if credentials and credentials.credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            user_id: str = payload.get("sub", "")
            if user_id:
                user = await get_user_by_id(db, user_id)
                if user:
                    return user
        except JWTError:
            # Token expired, tampered, or malformed — fall through to API key
            pass

    # ── Strategy 2: X-API-Key header ──────────────────────────────────────
    if api_key:
        user = await get_user_by_api_key(db, api_key)
        if user:
            return user

    # ── Neither strategy succeeded ────────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a valid JWT Bearer token or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# =============================================================================
# RBAC Guard — Admin-Only  (SRS NFR-S3, §3.2 /admin/*)
# =============================================================================

async def require_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    RBAC guard — raises HTTP 403 if the authenticated user is not an admin.

    Usage:
        @router.post("/admin/fail-fast-model")
        async def fail_fast_model(user: dict = Depends(require_admin)):
            ...
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Admin role required. "
                f"Your role is '{current_user.get('role', 'unknown')}'. "
                "Register with role='admin' or ask an administrator."
            ),
        )
    return current_user

