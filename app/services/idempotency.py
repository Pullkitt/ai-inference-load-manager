"""
app/services/idempotency.py
───────────────────────────
Idempotency engine and payload deduplication.

SRS §2.1 Step 1 & §3.2.1:
  "Every request is hashed (SHA-256 of User ID + Request Payload) or checked against
   a client-supplied Idempotency-Key.
   The hash is queried in Redis with a 30-second TTL.
   If the hash already exists, the router immediately returns the previously cached response,
   saving compute resources on network retries."

SRS NFR-P3:
  "Cached duplicate requests shall return in under 10ms."
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)


def compute_idempotency_hash(
    user_id: str,
    payload: Any,
    client_key: Optional[str] = None,
) -> str:
    """
    Generate a deterministic SHA-256 hash for a given user and payload.

    Args:
        user_id: The authenticated user's ID.
        payload: Dict, primitive, or Pydantic model representing the request payload.
        client_key: Optional client-provided `Idempotency-Key` header. If provided,
                    it takes precedence and is combined with `user_id`.

    Returns:
        64-character hexadecimal SHA-256 digest string.
    """
    if client_key and client_key.strip():
        # Scoped by user_id to prevent key-space collisions between different users
        raw_str = f"{user_id}:key:{client_key.strip()}"
    else:
        # Canonicalise payload to guarantee identical hashes regardless of key order
        if hasattr(payload, "model_dump"):
            payload_data = payload.model_dump()
        elif isinstance(payload, dict):
            payload_data = payload
        else:
            payload_data = str(payload)

        canonical_json = json.dumps(
            payload_data,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            ensure_ascii=True,
        )
        raw_str = f"{user_id}:payload:{canonical_json}"

    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


async def get_cached_idempotent_response(
    redis: aioredis.Redis,
    hash_key: str,
) -> Optional[dict]:
    """
    Check if a response has already been cached for this idempotency hash.

    If found:
      - Automatically increments `settings.REDIS_CACHE_HIT_KEY`
      - Marks the dictionary with `"cached": True`
      - Returns cached response data in <10ms

    Returns:
        dict if cache hit, None if cache miss.
    """
    redis_key = f"{settings.REDIS_IDEMPOTENCY_PREFIX}{hash_key}"
    try:
        raw_data = await redis.get(redis_key)
        if raw_data:
            # Atomic increment of idempotency hit counter
            await redis.incr(settings.REDIS_CACHE_HIT_KEY)

            data = json.loads(raw_data)
            data["cached"] = True
            logger.info("Idempotency cache hit for hash: %s", hash_key)
            return data
    except Exception as exc:
        logger.warning("Idempotency cache lookup error: %s", exc)

    return None


async def set_idempotent_response(
    redis: aioredis.Redis,
    hash_key: str,
    response_data: dict,
    ttl_seconds: int = settings.IDEMPOTENCY_TTL_SECONDS,
) -> None:
    """
    Cache a successful response against its idempotency hash in Redis.

    Args:
        redis: Async Redis client.
        hash_key: 64-character SHA-256 hash.
        response_data: Dictionary response to cache.
        ttl_seconds: Time-To-Live in seconds (default 30s as per SRS).
    """
    redis_key = f"{settings.REDIS_IDEMPOTENCY_PREFIX}{hash_key}"
    try:
        # Clone and ensure 'cached' flag is set to False in stored state
        to_store = dict(response_data)
        to_store["cached"] = True
        payload_str = json.dumps(to_store, default=str)
        await redis.set(redis_key, payload_str, ex=ttl_seconds)
    except Exception as exc:
        logger.warning("Failed to store idempotency response: %s", exc)
