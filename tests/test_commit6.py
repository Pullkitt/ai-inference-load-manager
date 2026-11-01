"""
tests/test_commit6.py
─────────────────────
Unit tests for Commit 6 (Decoupled Background Inference Worker):
  1. Slow Model multi-domain inference output generation (IoT, Media, Geospatial, NLP)
  2. Full process_task lifecycle: queued -> processing -> completed
  3. Proper recording of result documents with model_used="slow_model"
  4. Error resilience: failed task transitions to status="failed" and writes WORKER_ERROR
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.inference import ModelUsed, RequestStatus, RoutingReason
from worker.worker import execute_slow_inference, process_task


class TestCommit6Worker(unittest.TestCase):

    # ── 1. Slow Model Domain Outputs ─────────────────────────────────────────

    def test_slow_model_outputs_across_all_domains(self):
        async def run_test():
            # Fast-forward simulated delay for lightning-fast test execution
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # IoT
                iot_res = await execute_slow_inference(
                    "iot",
                    {"device_id": "sensor_bilstm_01", "sensor_type": "vibration", "reading_array": [1.2, 1.4, 1.3, 1.5]},
                )
                self.assertEqual(iot_res["inference_type"], "deep_recurrent_telemetry_forecasting")
                self.assertIn("lstm_reconstruction_error", iot_res)
                self.assertIn("anomaly_probability", iot_res)
                self.assertEqual(iot_res["model_architecture"], "BiLSTM-Attention-Autoencoder-v2")

                # Mobile Media
                media_res = await execute_slow_inference(
                    "mobile_media",
                    {"client_id": "mobile_user_88", "image_dimension": "1920x1080", "mode": "segmentation"},
                )
                self.assertEqual(media_res["inference_type"], "high_res_multi_label_segmentation")
                self.assertIn("segmented_instances_count", media_res)
                self.assertEqual(media_res["model_architecture"], "Mask-RCNN-ResNet101-FPN")

                # Geospatial
                geo_res = await execute_slow_inference(
                    "geospatial",
                    {"unit_id": "drone_alpha", "latitude": 30.3165, "longitude": 78.0322, "speed": 55.0},
                )
                self.assertEqual(geo_res["inference_type"], "spatiotemporal_trajectory_optimization")
                self.assertIn("spatial_density_score", geo_res)
                self.assertIn("optimized_waypoints", geo_res)

                # NLP
                nlp_res = await execute_slow_inference(
                    "ai_nlp",
                    {"prompt_tokens": 250, "temperature": 0.7, "input_text": "Autonomous cloud architecture inference evaluation."},
                )
                self.assertEqual(nlp_res["inference_type"], "deep_contextual_comprehension_and_summarization")
                self.assertIn("executive_summary", nlp_res)
                self.assertIn("named_entities", nlp_res)
                self.assertEqual(nlp_res["model_architecture"], "Llama-3-8B-Instruct-Simulated")

        asyncio.run(run_test())

    # ── 2. Task Processing Lifecycle ─────────────────────────────────────────

    def test_process_task_successful_lifecycle(self):
        async def run_test():
            mock_db = MagicMock()
            mock_db.inference_requests.update_one = AsyncMock()
            mock_db.inference_results.insert_one = AsyncMock()

            mock_redis = AsyncMock()
            mock_pipe = MagicMock()
            mock_pipe.rpush = MagicMock()
            mock_pipe.ltrim = MagicMock()
            mock_pipe.execute = AsyncMock()
            mock_redis.pipeline = MagicMock(return_value=mock_pipe)

            task_data = {
                "request_id": "test-req-uuid-1234",
                "user_id": "test-user-5678",
                "domain": "iot",
                "payload": {"device_id": "dev_1", "sensor_type": "temp", "reading_array": [21.0, 21.5]},
                "routing_reason": RoutingReason.LATENCY_FLEXIBLE.value,
            }

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await process_task(mock_db, mock_redis, task_data)

            self.assertIsNotNone(result)
            self.assertEqual(result["request_id"], "test-req-uuid-1234")
            self.assertEqual(result["model_used"], ModelUsed.SLOW.value)
            self.assertEqual(result["routing_reason"], RoutingReason.LATENCY_FLEXIBLE.value)

            # Check that status was updated to 'processing', then 'completed'
            mock_db.inference_requests.update_one.assert_any_await(
                {"request_id": "test-req-uuid-1234"},
                {"$set": {"status": RequestStatus.PROCESSING.value}},
            )
            mock_db.inference_requests.update_one.assert_any_await(
                {"request_id": "test-req-uuid-1234"},
                {"$set": {"status": RequestStatus.COMPLETED.value}},
            )

            # Check result inserted into inference_results
            mock_db.inference_results.insert_one.assert_awaited_once()

        asyncio.run(run_test())

    # ── 3. Error Handling and Failure Transition ─────────────────────────────

    def test_process_task_failure_transitions_to_failed(self):
        async def run_test():
            mock_db = MagicMock()
            mock_db.inference_requests.update_one = AsyncMock()
            mock_db.system_audit_logs.insert_one = AsyncMock()
            mock_redis = AsyncMock()

            task_data = {
                "request_id": "error-req-uuid-9999",
                "user_id": "user-err",
                "domain": "iot",
                "payload": {},
            }

            # Force execute_slow_inference to fail
            with patch("worker.worker.execute_slow_inference", side_effect=RuntimeError("Simulated GPU OOM")):
                result = await process_task(mock_db, mock_redis, task_data)

            self.assertIsNone(result)

            # Must transition to failed status in MongoDB
            mock_db.inference_requests.update_one.assert_any_await(
                {"request_id": "error-req-uuid-9999"},
                {"$set": {"status": RequestStatus.FAILED.value}},
            )

            # Must write audit log for WORKER_ERROR
            mock_db.system_audit_logs.insert_one.assert_awaited_once()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()

