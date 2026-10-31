"""
app/database.py — Async connection pools for MongoDB (Motor) and Redis.

Lifecycle:
  - Connections are opened in FastAPI's lifespan startup hook (app/main.py).
  - Connections are closed in the lifespan shutdown hook.
  - All application code accesses the clients via the get_db() / get_redis()
    dependency helpers, keeping coupling minimal.
"""

import logging
from typing import Optional

import redis.asyncio as aioredis
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Module-level connection holders ──────────────────────────────────────────
_mongo_client: Optional[AsyncIOMotorClient] = None
_redis_client: Optional[aioredis.Redis] = None


# =============================================================================
# MongoDB
# =============================================================================

async def connect_mongodb() -> None:
    """Open the async Motor connection pool and ping the server."""
    global _mongo_client
    _mongo_client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        serverSelectionTimeoutMS=5000,   # fail fast if MongoDB is unreachable
        connectTimeoutMS=5000,
    )
    # Ping to validate connectivity at startup
    await _mongo_client.admin.command("ping")
    logger.info("✅  MongoDB connected — database: %s", settings.MONGODB_DB_NAME)


async def disconnect_mongodb() -> None:
    """Close the Motor connection pool cleanly."""
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None
        logger.info("🔌  MongoDB disconnected.")


def get_db() -> AsyncIOMotorDatabase:
    """
    Return the active database handle.
    Raises RuntimeError if called before connect_mongodb().
    """
    if _mongo_client is None:
        raise RuntimeError("MongoDB client is not initialised. "
                           "Ensure connect_mongodb() was called at startup.")
    return _mongo_client[settings.MONGODB_DB_NAME]


# =============================================================================
# Redis
# =============================================================================

async def connect_redis() -> None:
    """Open the async Redis connection pool and ping the server."""
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    await _redis_client.ping()
    logger.info("✅  Redis connected — url: %s", settings.REDIS_URL)


async def disconnect_redis() -> None:
    """Close the Redis connection pool cleanly."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("🔌  Redis disconnected.")


def get_redis() -> aioredis.Redis:
    """
    Return the active Redis client.
    Raises RuntimeError if called before connect_redis().
    """
    if _redis_client is None:
        raise RuntimeError("Redis client is not initialised. "
                           "Ensure connect_redis() was called at startup.")
    return _redis_client

