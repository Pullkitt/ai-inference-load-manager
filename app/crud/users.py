"""
app/crud/users.py
─────────────────
Async MongoDB CRUD helpers for the `users` collection.

All functions receive a Motor `AsyncIOMotorDatabase` handle injected by the
router and perform only the minimal I/O needed — no business logic here.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.user import UserDocument


# MongoDB projection that excludes the internal `_id` and `hashed_password`
_PUBLIC_PROJECTION = {"_id": 0, "hashed_password": 0}
_FULL_PROJECTION = {"_id": 0}


async def create_user(db: AsyncIOMotorDatabase, user: UserDocument) -> str:
    """
    Insert a new user document.
    Returns the user_id on success.
    Raises DuplicateKeyError if the username already exists (index enforced).
    """
    doc = user.model_dump()
    await db.users.insert_one(doc)
    return user.user_id


async def get_user_by_username(
    db: AsyncIOMotorDatabase,
    username: str,
) -> Optional[dict]:
    """
    Fetch a full user document (including hashed_password) by username.
    Returns None if not found.
    Used by the login endpoint to verify credentials.
    """
    return await db.users.find_one({"username": username}, {"_id": 0})


async def get_user_by_id(
    db: AsyncIOMotorDatabase,
    user_id: str,
) -> Optional[dict]:
    """
    Fetch a full user document by user_id UUID.
    Returns None if not found.
    """
    return await db.users.find_one({"user_id": user_id}, {"_id": 0})


async def get_user_by_api_key(
    db: AsyncIOMotorDatabase,
    api_key: str,
) -> Optional[dict]:
    """
    Fetch a full user document by API key.
    Used by the X-API-Key authentication dependency.
    Returns None if the key is invalid/not found.
    """
    return await db.users.find_one({"api_key": api_key}, {"_id": 0})


async def username_exists(db: AsyncIOMotorDatabase, username: str) -> bool:
    """
    Check whether a username is already taken.
    Uses count_documents for O(1) index lookup.
    """
    count = await db.users.count_documents({"username": username}, limit=1)
    return count > 0


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create unique indexes on users.username and users.api_key.
    Safe to call multiple times — Motor skips if index already exists.
    Called once at application startup.
    """
    await db.users.create_index("username", unique=True, background=True)
    await db.users.create_index("api_key", unique=True, background=True)
    await db.users.create_index("user_id", unique=True, background=True)

