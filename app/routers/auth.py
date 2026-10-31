"""
app/routers/auth.py
────────────────────
Authentication endpoints (SRS §3.2):
  POST /api/auth/register  — register a new user, return JWT + API key
  POST /api/auth/login     — authenticate, return JWT

Security measures enforced:
  • Passwords hashed with bcrypt (NFR-S1)
  • API keys are 32-byte cryptographically secure hex strings (NFR-S2)
  • Credentials and secrets loaded from .env, never hard-coded (NFR-S4)
  • Duplicate username returns 400 Bad Request (not 500)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import get_db_dep
from app.core.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.crud.users import (
    create_user,
    get_user_by_username,
    username_exists,
)
from app.crud.inference import write_audit_log
from app.models.audit import AuditEventType
from app.models.user import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserDocument,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# =============================================================================
# POST /api/auth/register
# =============================================================================

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_200_OK,
    summary="Register a new user",
    description=(
        "Creates a new user account with a bcrypt-hashed password and a "
        "cryptographically generated 32-byte hex API key. "
        "Returns a JWT access token and the API key — **store the API key safely**, "
        "it is only shown once. "
        "Returns `400 Bad Request` if the username is already taken."
    ),
    responses={
        200: {"description": "User registered successfully"},
        400: {"description": "Username already taken"},
        422: {"description": "Validation error in request body"},
    },
)
async def register(
    body: RegisterRequest,
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
) -> RegisterResponse:
    """
    Registration flow:
      1. Check username uniqueness (→ 400 if taken).
      2. Hash the password with bcrypt.
      3. Generate a 32-byte hex API key.
      4. Persist the UserDocument to MongoDB.
      5. Issue a JWT access token.
      6. Write USER_REGISTERED audit log.
      7. Return JWT + api_key to the client.
    """

    # ── 1. Uniqueness check ───────────────────────────────────────────────────
    if await username_exists(db, body.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{body.username}' is already taken. Choose a different username.",
        )

    # ── 2 & 3. Hash password + generate API key ───────────────────────────────
    hashed_pw = hash_password(body.password)
    api_key = generate_api_key()

    # ── 4. Create user document ───────────────────────────────────────────────
    user = UserDocument(
        username=body.username,
        hashed_password=hashed_pw,
        api_key=api_key,
        role=body.role,
    )
    user_id = await create_user(db, user)
    logger.info("✅  New user registered — username=%s role=%s", body.username, body.role)

    # ── 5. Issue JWT ──────────────────────────────────────────────────────────
    token = create_access_token(subject=user_id, role=user.role.value if hasattr(user.role, 'value') else str(user.role))

    # ── 6. Audit log ──────────────────────────────────────────────────────────
    await write_audit_log(
        db,
        event_type=AuditEventType.USER_REGISTERED.value,
        details={"user_id": user_id, "username": body.username, "role": str(user.role)},
    )

    # ── 7. Return response ────────────────────────────────────────────────────
    return RegisterResponse(
        user_id=user_id,
        username=body.username,
        role=str(user.role.value) if hasattr(user.role, 'value') else str(user.role),
        api_key=api_key,
        access_token=token,
    )


# =============================================================================
# POST /api/auth/login
# =============================================================================

@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in and receive a JWT token",
    description=(
        "Authenticates a registered user by username + password. "
        "Returns a JWT access token valid for `JWT_EXPIRE_MINUTES` minutes. "
        "Returns `401 Unauthorized` for invalid credentials."
    ),
    responses={
        200: {"description": "Login successful — JWT returned"},
        401: {"description": "Invalid username or password"},
        422: {"description": "Validation error in request body"},
    },
)
async def login(
    body: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_db_dep),
) -> LoginResponse:
    """
    Login flow:
      1. Fetch user document by username.
      2. Verify password against stored bcrypt hash.
      3. Issue a fresh JWT access token.
      4. Return the token.

    Deliberately uses a generic 401 message on failure to prevent
    username enumeration attacks.
    """

    # ── 1. Fetch user ─────────────────────────────────────────────────────────
    user = await get_user_by_username(db, body.username)

    # ── 2. Verify password (constant-time via bcrypt) ─────────────────────────
    # Use the same generic message for "not found" and "wrong password"
    # to prevent username enumeration.
    _invalid_creds = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not user:
        raise _invalid_creds

    if not verify_password(body.password, user["hashed_password"]):
        raise _invalid_creds

    logger.info("🔑  User logged in — username=%s", body.username)

    # ── 3. Issue JWT ──────────────────────────────────────────────────────────
    token = create_access_token(
        subject=user["user_id"],
        role=user["role"],
    )

    # ── 4. Return response ────────────────────────────────────────────────────
    return LoginResponse(
        access_token=token,
        user_id=user["user_id"],
        username=user["username"],
        role=user["role"],
    )

