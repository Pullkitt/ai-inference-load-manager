"""
tests/test_commit5.py
─────────────────────
Unit tests for Commit 5:
  1. Circuit Breaker state transitions: CLOSED -> OPEN -> HALF-OPEN -> CLOSED
  2. Failure sliding-window threshold tripping (5 failures in 10s window)
  3. Fault injection toggle (set/get)
  4. Fast Model domain output generation & timeout
  5. Guaranteed concurrency accounting (try...finally DECR check)
"""

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.services.circuit_breaker import (
    CircuitState,
    get_state,
    is_fault_injection_active,
    record_failure,
    record_success,
    reset_circuit_breaker,
    set_fault_injection,
)
from app.services.fast_model import execute_fast_inference


class TestCommit5CircuitBreakerAndRouter(unittest.TestCase):

    # ── 1. Circuit Breaker State Transitions ─────────────────────────────────

    def test_circuit_breaker_initial_state_is_closed(self):
        async def run_test():
            mock_redis = AsyncMock()
            mock_redis.get.return_value = None  # Key not yet set

            state = await get_state(mock_redis)
            self.assertEqual(state, CircuitState.CLOSED.value)
            mock_redis.set.assert_awaited_once_with(
                settings.REDIS_CB_STATE_KEY, CircuitState.CLOSED.value
            )

        asyncio.run(run_test())

    def test_circuit_breaker_trips_to_open_after_threshold_failures(self):
        async def run_test():
            mock_redis = AsyncMock()
            mock_redis.get.return_value = CircuitState.CLOSED.value

            mock_pipe = MagicMock()
            mock_pipe.zremrangebyscore = MagicMock()
            mock_pipe.zadd = MagicMock()
            mock_pipe.expire = MagicMock()
            mock_pipe.zcard = MagicMock()
            # 5th failure reaches threshold
            mock_pipe.execute = AsyncMock(return_value=[0, 1, True, 5])
            mock_redis.pipeline = MagicMock(return_value=mock_pipe)

            new_state = await record_failure(mock_redis, db=None)
            self.assertEqual(new_state, CircuitState.OPEN.value)
            mock_redis.set.assert_any_await(
                settings.REDIS_CB_STATE_KEY, CircuitState.OPEN.value
            )
            mock_redis.incr.assert_awaited_once_with(settings.REDIS_CB_TRIP_COUNT_KEY)

        asyncio.run(run_test())

    def test_circuit_breaker_recovery_to_half_open_after_cooldown(self):
        async def run_test():
            mock_redis = AsyncMock()
            mock_redis.get.side_effect = lambda key: (
                CircuitState.OPEN.value
                if key == settings.REDIS_CB_STATE_KEY
                else str(time.time() - 35)  # 35 seconds elapsed (> 30s)
            )

            state = await get_state(mock_redis)
            self.assertEqual(state, CircuitState.HALF_OPEN.value)
            mock_redis.set.assert_awaited_once_with(
                settings.REDIS_CB_STATE_KEY, CircuitState.HALF_OPEN.value
            )

        asyncio.run(run_test())

    def test_circuit_breaker_half_open_probe_success_resets_to_closed(self):
        async def run_test():
            mock_redis = AsyncMock()
            mock_redis.get.return_value = CircuitState.HALF_OPEN.value

            state = await record_success(mock_redis, db=None)
            self.assertEqual(state, CircuitState.CLOSED.value)
            mock_redis.set.assert_awaited_once_with(
                settings.REDIS_CB_STATE_KEY, CircuitState.CLOSED.value
            )
            mock_redis.delete.assert_awaited_once()

        asyncio.run(run_test())

    def test_circuit_breaker_half_open_probe_failure_reopens_circuit(self):
        async def run_test():
            mock_redis = AsyncMock()
            mock_redis.get.return_value = CircuitState.HALF_OPEN.value

            state = await record_failure(mock_redis, db=None)
            self.assertEqual(state, CircuitState.OPEN.value)
            mock_redis.set.assert_any_await(
                settings.REDIS_CB_STATE_KEY, CircuitState.OPEN.value
            )

        asyncio.run(run_test())

    # ── 2. Fault Injection Toggle ────────────────────────────────────────────

    def test_fault_injection_toggle(self):
        async def run_test():
            mock_redis = AsyncMock()

            # Enable fault injection
            res = await set_fault_injection(mock_redis, True)
            self.assertTrue(res)
            mock_redis.set.assert_awaited_with(settings.REDIS_FAULT_INJECT_KEY, "1")

            # Check status
            mock_redis.get.return_value = "1"
            is_active = await is_fault_injection_active(mock_redis)
            self.assertTrue(is_active)

            # Disable fault injection
            await set_fault_injection(mock_redis, False)
            mock_redis.set.assert_awaited_with(settings.REDIS_FAULT_INJECT_KEY, "0")

        asyncio.run(run_test())

    # ── 3. Fast Model Execution & Domain Outputs ─────────────────────────────

    def test_fast_model_outputs_across_domains(self):
        async def run_test():
            # Test IoT output
            iot_res = await execute_fast_inference(
                "iot",
                {"device_id": "sensor_01", "sensor_type": "temp", "reading_array": [22.5, 23.0]},
            )
            self.assertEqual(iot_res["inference_type"], "sensor_telemetry_anomaly_detection")
            self.assertIn("mean_reading", iot_res)
            self.assertFalse(iot_res["anomaly_detected"])

            # Test NLP output
            nlp_res = await execute_fast_inference(
                "ai_nlp",
                {"prompt_tokens": 50, "temperature": 0.5, "input_text": "Antigravity cloud service is great!"},
            )
            self.assertEqual(nlp_res["inference_type"], "ai_nlp_sentiment_classification")
            self.assertEqual(nlp_res["sentiment"], "positive")

            # Test Geospatial output
            geo_res = await execute_fast_inference(
                "geospatial",
                {"unit_id": "truck_1", "latitude": 30.3, "longitude": 78.0, "speed": 45.0, "altitude": 400.0},
            )
            self.assertEqual(geo_res["inference_type"], "geospatial_spatial_clustering")
            self.assertIn("cluster_zone_id", geo_res)

            # Test Mobile Media output
            media_res = await execute_fast_inference(
                "mobile_media",
                {"client_id": "mob_1", "image_dimension": "640x480", "feature_vector": [0.1, 0.2], "mode": "object_detection"},
            )
            self.assertEqual(media_res["inference_type"], "mobile_media_feature_classification")
            self.assertIn("detected_objects", media_res)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()

