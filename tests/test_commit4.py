"""
tests/test_commit4.py
─────────────────────
Unit tests for Commit 4:
  1. Deterministic SHA-256 Idempotency hashing & payload canonicalisation
  2. Idempotency cache lookup, caching, and cache hit counter
  3. Sliding-window rate limiter logic (allow vs 429 backoff)
  4. Metrics recording (RPS status breakdown, latency p50/p95 calculations)
"""

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.idempotency import (
    compute_idempotency_hash,
    get_cached_idempotent_response,
    set_idempotent_response,
)
from app.services.metrics import (
    get_latency_percentiles,
    get_rps_breakdown,
    record_latency,
    record_request_status,
)
from app.services.rate_limiter import check_rate_limit


class TestCommit4Services(unittest.TestCase):

    # ── 1. Idempotency SHA-256 Hashing Tests ─────────────────────────────────

    def test_idempotency_hash_determinism_across_dict_key_ordering(self):
        """Keys in different order must yield identical SHA-256 digests."""
        user_id = "user-123"
        payload_a = {"domain": "iot", "sensor_type": "temp", "reading": 25.4}
        payload_b = {"reading": 25.4, "domain": "iot", "sensor_type": "temp"}

        hash_a = compute_idempotency_hash(user_id, payload_a)
        hash_b = compute_idempotency_hash(user_id, payload_b)

        self.assertEqual(hash_a, hash_b)
        self.assertEqual(len(hash_a), 64)  # Valid SHA-256 hex length

    def test_idempotency_hash_differs_per_user(self):
        """Same payload for two different users must generate distinct hashes."""
        payload = {"domain": "ai_nlp", "input_text": "hello"}
        hash_user1 = compute_idempotency_hash("user-1", payload)
        hash_user2 = compute_idempotency_hash("user-2", payload)

        self.assertNotEqual(hash_user1, hash_user2)

    def test_idempotency_hash_with_client_key(self):
        """Custom Idempotency-Key header overrides payload serialization."""
        user_id = "user-123"
        hash_key = compute_idempotency_hash(user_id, {"x": 1}, client_key="req-client-key-42")
        self.assertEqual(len(hash_key), 64)

        # Same client key produces same hash
        hash_key_dup = compute_idempotency_hash(user_id, {"x": 999}, client_key="req-client-key-42")
        self.assertEqual(hash_key, hash_key_dup)

    # ── 2. Idempotency Caching Tests (Async Mock) ────────────────────────────

    def test_get_cached_response_miss_and_hit(self):
        async def run_test():
            mock_redis = AsyncMock()

            # Case A: Cache miss
            mock_redis.get.return_value = None
            res = await get_cached_idempotent_response(mock_redis, "dummy_hash")
            self.assertIsNone(res)

            # Case B: Cache hit
            stored_data = {"status": "success", "result_id": "res-123", "cached": False}
            mock_redis.get.return_value = json.dumps(stored_data)
            mock_redis.incr.return_value = 1

            hit_res = await get_cached_idempotent_response(mock_redis, "dummy_hash")
            self.assertIsNotNone(hit_res)
            self.assertTrue(hit_res["cached"])
            mock_redis.incr.assert_awaited_once()

            # Case C: Store response
            await set_idempotent_response(mock_redis, "dummy_hash", hit_res, ttl_seconds=30)
            mock_redis.set.assert_awaited_once()

        asyncio.run(run_test())

    # ── 3. Rate Limiter Sliding Window Tests (Async Mock) ────────────────────

    def test_rate_limiter_lua_execution(self):
        async def run_test():
            mock_redis = AsyncMock()

            # Case A: Request allowed (Lua returns [1, 0, 5])
            mock_redis.eval.return_value = [1, 0, 5]
            allowed, retry_after, count = await check_rate_limit(
                mock_redis, "user-abc", limit=60, window_seconds=60
            )
            self.assertTrue(allowed)
            self.assertEqual(retry_after, 0)
            self.assertEqual(count, 5)

            # Case B: Request blocked / rate limited (Lua returns [0, 12, 60])
            mock_redis.eval.return_value = [0, 12, 60]
            allowed, retry_after, count = await check_rate_limit(
                mock_redis, "user-abc", limit=60, window_seconds=60
            )
            self.assertFalse(allowed)
            self.assertEqual(retry_after, 12)
            self.assertEqual(count, 60)

        asyncio.run(run_test())

    # ── 4. Metrics Recording & Percentiles Tests ──────────────────────────────

    def test_metrics_rps_and_latency(self):
        async def run_test():
            mock_redis = AsyncMock()

            # Status recording pipeline
            mock_pipe = MagicMock()
            mock_pipe.execute = AsyncMock()
            mock_redis.pipeline = MagicMock(return_value=mock_pipe)

            await record_request_status(mock_redis, 200)
            mock_pipe.hincrby.assert_any_call("metrics:rps", "status_200", 1)
            mock_pipe.hincrby.assert_any_call("metrics:rps", "total", 1)

            # Latency percentile calculation
            # Simulate latencies from 10ms to 100ms
            mock_redis.lrange.return_value = [str(x) for x in range(1, 101)]
            p = await get_latency_percentiles(mock_redis)
            self.assertAlmostEqual(p["p50_ms"], 50.0, delta=2.0)
            self.assertAlmostEqual(p["p95_ms"], 95.0, delta=2.0)

            # RPS breakdown retrieval
            mock_redis.hgetall.return_value = {
                "status_200": "50",
                "status_202": "30",
                "status_429": "2",
                "status_503": "1",
                "total": "83",
            }
            rps = await get_rps_breakdown(mock_redis)
            self.assertEqual(rps["status_200"], 50)
            self.assertEqual(rps["status_202"], 30)
            self.assertEqual(rps["status_429"], 2)
            self.assertEqual(rps["status_503"], 1)
            self.assertEqual(rps["total"], 83)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
