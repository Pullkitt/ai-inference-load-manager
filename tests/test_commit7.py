"""
tests/test_commit7.py
─────────────────────
Unit tests for Commit 7 (Observability endpoints: Metrics & History):
  1. GET /api/metrics/system-load telemetry serialization & percentile calculations
  2. POST /api/metrics/reset endpoint
  3. GET /api/logs/history for regular user (scoped) vs admin (system-wide)
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.routers.logs import get_history
from app.routers.metrics import get_system_load, reset_system_metrics


class TestCommit7Observability(unittest.TestCase):

    # ── 1. Metrics Telemetry Endpoint ────────────────────────────────────────

    def test_get_system_load_structure(self):
        async def run_test():
            mock_redis = AsyncMock()
            mock_db = MagicMock()

            # Mock redis values
            mock_redis.get.side_effect = lambda k: {
                settings.REDIS_CONCURRENCY_KEY: "3",
                settings.REDIS_CB_STATE_KEY: "CLOSED",
                settings.REDIS_CB_TRIP_COUNT_KEY: "2",
                settings.REDIS_FAULT_INJECT_KEY: "0",
                settings.REDIS_CACHE_HIT_KEY: "15",
            }.get(k, None)

            mock_redis.llen.return_value = 8
            mock_redis.hgetall.return_value = {
                "status_200": "120",
                "status_202": "45",
                "status_429": "5",
                "status_503": "1",
                "total": "171",
            }
            # Simulate latency measurements (10ms to 200ms)
            mock_redis.lrange.return_value = [str(x) for x in range(10, 210, 10)]

            response = await get_system_load(db=mock_db, redis=mock_redis)

            self.assertEqual(response.active_fast_concurrency, 3)
            self.assertEqual(response.fast_model_max_concurrency, 5)
            self.assertEqual(response.redis_queue_depth, 8)
            self.assertEqual(response.max_queue_depth, 50)
            self.assertEqual(response.circuit_breaker_state, "CLOSED")
            self.assertEqual(response.circuit_breaker_trip_count, 2)
            self.assertFalse(response.fault_injection_active)
            self.assertEqual(response.idempotency_cache_hits, 15)

            # RPS assertions
            self.assertEqual(response.rps.status_200, 120)
            self.assertEqual(response.rps.status_202, 45)
            self.assertEqual(response.rps.total, 171)

            # Latency assertions
            self.assertGreater(response.latency.p50_ms, 0)
            self.assertGreater(response.latency.p95_ms, response.latency.p50_ms)
            self.assertIsNotNone(response.timestamp)

        asyncio.run(run_test())

    # ── 2. Reset Metrics Endpoint ────────────────────────────────────────────

    def test_reset_metrics_endpoint(self):
        async def run_test():
            mock_redis = AsyncMock()
            res = await reset_system_metrics(redis=mock_redis)
            self.assertTrue(res.success)
            mock_redis.delete.assert_awaited_once()

        asyncio.run(run_test())

    # ── 3. Logs History Scoping (User vs Admin) ──────────────────────────────

    def test_get_history_user_scoped(self):
        async def run_test():
            mock_db = MagicMock()
            user_ctx = {"user_id": "usr-1234", "role": "user"}

            mock_cursor = MagicMock()
            mock_cursor.sort = MagicMock(return_value=mock_cursor)
            mock_cursor.limit = MagicMock(return_value=mock_cursor)
            mock_cursor.to_list = AsyncMock(return_value=[{"request_id": "req-1", "user_id": "usr-1234"}])

            mock_db.inference_requests.find = MagicMock(return_value=mock_cursor)
            mock_db.inference_requests.aggregate = MagicMock(return_value=mock_cursor)
            mock_db.system_audit_logs.find = MagicMock(return_value=mock_cursor)

            history = await get_history(limit=50, event_type=None, current_user=user_ctx, db=mock_db)

            self.assertEqual(history["user_id"], "usr-1234")
            self.assertEqual(history["role"], "user")
            self.assertEqual(history["total_requests"], 1)
            self.assertEqual(len(history["requests"]), 1)
            # Confirmed find was called with user_id filter
            mock_db.inference_requests.find.assert_called_with({"user_id": "usr-1234"}, {"_id": 0})

        asyncio.run(run_test())

    def test_get_history_admin_system_wide(self):
        async def run_test():
            mock_db = MagicMock()
            admin_ctx = {"user_id": "admin-007", "role": "admin"}

            mock_cursor = MagicMock()
            mock_cursor.sort = MagicMock(return_value=mock_cursor)
            mock_cursor.limit = MagicMock(return_value=mock_cursor)
            mock_cursor.to_list = AsyncMock(return_value=[
                {"request_id": "req-1", "user_id": "usr-1"},
                {"request_id": "req-2", "user_id": "usr-2"},
            ])

            mock_db.inference_requests.find = MagicMock(return_value=mock_cursor)
            mock_db.inference_results.find = MagicMock(return_value=mock_cursor)
            mock_db.system_audit_logs.find = MagicMock(return_value=mock_cursor)

            history = await get_history(limit=50, event_type=None, current_user=admin_ctx, db=mock_db)

            self.assertEqual(history["role"], "admin")
            self.assertEqual(history["total_requests"], 2)
            # Admin queries all without user filter: {}
            mock_db.inference_requests.find.assert_called_with({}, {"_id": 0})
            mock_db.inference_results.find.assert_called_with({}, {"_id": 0})

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()

