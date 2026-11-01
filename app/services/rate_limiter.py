"""
app/services/rate_limiter.py
────────────────────────────
Sliding-window rate limiter using Redis sorted sets (ZSET).

SRS §2.1 Step 2 & §3.2.1:
  "A sliding window in Redis verifies whether the user has exceeded their request
   quota (e.g., 60 requests/minute). If exceeded, the system returns 429 Too Many Requests."

Implementation Details:
  - Redis Lua script executes atomically in a single round-trip.
  - Removes timestamps older than (current_time - window_seconds).
  - Inspects ZCARD; if within limit, adds current timestamp and extends TTL.
  - If limit is reached, calculates dynamic `retry_after` based on the oldest element.
"""

from __future__ import annotations

import math
import time
import uuid
import logging
from typing import Tuple

import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

# Atomic sliding window rate limiter Lua script
# KEYS[1] = rate limit key for user
# ARGV[1] = current timestamp (float)
# ARGV[2] = window size in seconds (float/int)
# ARGV[3] = maximum requests allowed (int)
# ARGV[4] = unique member string (timestamp:uuid)
_RATE_LIMIT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

-- 1. Remove elements outside the sliding window
local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Check current request count in this window
local current_count = redis.call('ZCARD', key)

if current_count < limit then
    -- Record this request
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    return {1, 0, current_count + 1}
else
    -- Over limit: calculate seconds until the oldest request falls out
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 1
    if oldest and #oldest >= 2 then
        local oldest_time = tonumber(oldest[2])
        local delta = math.ceil((oldest_time + window) - now)
        if delta > 0 then
            retry_after = delta
        end
    end
    return {0, retry_after, current_count}
end
"""


async def check_rate_limit(
    redis: aioredis.Redis,
    user_id: str,
    limit: int = settings.RATE_LIMIT_PER_MIN,
    window_seconds: int = 60,
) -> Tuple[bool, int, int]:
    """
    Check if the user is within their allowed sliding-window quota.

    Args:
        redis: Async Redis connection.
        user_id: Unique user identifier.
        limit: Max requests allowed within the window (default 60).
        window_seconds: Sliding window span (default 60s).

    Returns:
        tuple (is_allowed: bool, retry_after: int, current_count: int)
        - is_allowed: True if request is permitted, False if 429
        - retry_after: Recommended seconds to backoff if rate limited (0 if allowed)
        - current_count: Number of requests in the active window
    """
    now = time.time()
    key = f"{settings.REDIS_RATE_LIMIT_PREFIX}{user_id}"
    unique_member = f"{now}:{uuid.uuid4().hex[:8]}"

    try:
        res = await redis.eval(
            _RATE_LIMIT_LUA,
            1,
            key,
            str(now),
            str(window_seconds),
            str(limit),
            unique_member,
        )
        is_allowed = bool(res[0] == 1)
        retry_after = int(res[1])
        current_count = int(res[2])
        return is_allowed, retry_after, current_count
    except Exception as exc:
        # Fail-open with warning if Redis transient error occurs, to maintain availability
        logger.error("Rate limiter Redis failure for user %s: %s", user_id, exc)
        return True, 0, 0


async def get_current_window_count(
    redis: aioredis.Redis,
    user_id: str,
    window_seconds: int = 60,
) -> int:
    """Return the number of requests made by the user in the active sliding window."""
    now = time.time()
    key = f"{settings.REDIS_RATE_LIMIT_PREFIX}{user_id}"
    try:
        await redis.zremrangebyscore(key, "-inf", now - window_seconds)
        return await redis.zcard(key)
    except Exception as exc:
        logger.warning("Error getting rate limit count for %s: %s", user_id, exc)
        return 0


async def reset_rate_limit(redis: aioredis.Redis, user_id: str) -> None:
    """Clear rate limit data for a specific user (useful in tests and admin actions)."""
    key = f"{settings.REDIS_RATE_LIMIT_PREFIX}{user_id}"
    await redis.delete(key)

