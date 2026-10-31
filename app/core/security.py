"""
app/core/security.py
─────────────────────
Cryptographic utilities for the authentication layer.

Responsibilities:
  • Password hashing and verification via bcrypt (SRS NFR-S1)
  • API key generation — 32-byte cryptographically secure hex string (SRS NFR-S2)
  • JWT creation and decoding — HS256 signed with JWT_SECRET_KEY (SRS §3.2.1 FR-1)

Nothing in this module touches the database or the HTTP layer.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# =============================================================================
# Passlib / bcrypt compatibility fix
# passlib 1.7.4 reads bcrypt.__about__.__version__ which was removed in bcrypt 4.x
# This shim suppresses the AttributeError warning without affecting functionality.
# =============================================================================
try:
    import bcrypt as _bcrypt_mod
    if not hasattr(_bcrypt_mod, "__about__"):
        class _FakeAbout:
            __version__ = _bcrypt_mod.__version__
        _bcrypt_mod.__about__ = _FakeAbout()
except Exception:
    pass

# =============================================================================
# Password Hashing — bcrypt  (SRS NFR-S1)
# =============================================================================

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password with bcrypt.
    The resulting hash is safe to store in MongoDB.
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against its bcrypt hash.
    Returns True if they match, False otherwise.
    Uses constant-time comparison internally to prevent timing attacks.
    """
    return _pwd_context.verify(plain_password, hashed_password)


# =============================================================================
# API Key Generation  (SRS NFR-S2)
# =============================================================================

def generate_api_key() -> str:
    """
    Generate a cryptographically secure 32-byte API key encoded as hex.
    Produces a 64-character hex string.
    e.g. "a3f8c2d1e4b7f0a9c3d2e1f4b8c7a6d5e0f3b2a1c4d5e6f7a8b9c0d1e2f3a4b5"

    Uses Python's secrets module (CSPRNG) — safe for production credentials.
    """
    return secrets.token_hex(32)


# =============================================================================
# JWT Tokens  (SRS §3.2.1 FR-1)
# =============================================================================

def create_access_token(
    subject: str,
    role: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject:      The user_id UUID to embed as the `sub` claim.
        role:         The user's role ('user' or 'admin') embedded as `role` claim.
        extra_claims: Any additional key-value pairs to embed in the payload.

    Returns:
        A compact, URL-safe HS256-signed JWT string.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": subject,          # Subject — user_id
        "role": role,            # Role claim for RBAC
        "iat": now,              # Issued at
        "exp": expire,           # Expiry
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Returns:
        The decoded claims dict on success.

    Raises:
        JWTError: If the token is expired, malformed, or the signature is invalid.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
