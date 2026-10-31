"""
app/models/user.py
──────────────────
Pydantic schemas and MongoDB document model for the `users` collection.

SRS §3.3 Collection 1 — users:
  user_id, username, hashed_password, api_key, role, created_at
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


# =============================================================================
# MongoDB Document  (stored in the `users` collection)
# =============================================================================

class UserDocument(BaseModel):
    """
    Complete user record as it is persisted to MongoDB.
    `hashed_password` and `api_key` are never returned to the client.
    """

    user_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID for the user",
    )
    username: str = Field(..., min_length=3, max_length=50)
    hashed_password: str = Field(..., description="bcrypt hash of the plain-text password")
    api_key: str = Field(..., description="32-byte hex API key (64 hex chars)")
    role: UserRole = Field(default=UserRole.USER)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = {"use_enum_values": True}


# =============================================================================
# Request Schemas (received from the client)
# =============================================================================

class RegisterRequest(BaseModel):
    """Body for POST /api/auth/register"""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique username (3–50 characters, alphanumeric + underscore)",
        examples=["pulkit_jain"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (min 8 chars — stored as bcrypt hash)",
    )
    role: UserRole = Field(
        default=UserRole.USER,
        description="User role. Use 'admin' for evaluator/admin accounts.",
    )


class LoginRequest(BaseModel):
    """Body for POST /api/auth/login"""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)


# =============================================================================
# Response Schemas (returned to the client — no secrets included)
# =============================================================================

class UserPublic(BaseModel):
    """Public-safe user representation — excludes hashed_password."""

    user_id: str
    username: str
    role: str
    created_at: datetime


class RegisterResponse(BaseModel):
    """Response for POST /api/auth/register (SRS §3.2)"""

    message: str = "User registered successfully"
    user_id: str
    username: str
    role: str
    api_key: str = Field(
        ...,
        description="32-byte hex API key — store safely, used in X-API-Key header",
    )
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Response for POST /api/auth/login (SRS §3.2)"""

    message: str = "Login successful"
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str

