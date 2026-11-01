"""
worker/worker.py
────────────────
Decoupled asynchronous background worker process consuming from the Redis queue.

SRS §1.1, §1.3, §2.1 Step 4, §2.5, §3.2.1 FR-8:
  - Consumes tasks from Redis `inference_queue` using non-busy blocking pop (`BRPOP`).
  - Simulates the resource-heavy Slow Model with a 3.0s – 4.0s processing delay.
  - Generates comprehensive domain outputs for all 4 schemas (IoT, Media, Geospatial, NLP).
  - Updates request lifecycle status in MongoDB `inference_requests` (queued -> processing -> completed).
  - Persists full inference results into MongoDB `inference_results`.
  - Records processing latency telemetry into Redis metrics.
  - Supports graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings
from app.crud.inference import (
    create_inference_result,
    update_request_status,
    write_audit_log,
)
from app.models.audit import AuditEventType
from app.models.inference import (
    InferenceResultDocument,
    ModelUsed,
    RequestStatus,
    RoutingReason,
)
from app.services import metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | [worker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("worker")

# Flag controlling the main loop execution
_running = True


def _handle_shutdown_signal(sig, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logger.info("Shutdown signal received (%s). Finishing current task and exiting...", sig)
    _running = False


# =============================================================================
# Simulated Slow Model Inference  (SRS §1.1, §2.2)
# =============================================================================

async def execute_slow_inference(
    domain: str,
    payload_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Simulate the heavy Slow Model computation.
    Delay: 3.0s - 4.0s (SRS SLOW_MODEL_LATENCY_MIN/MAX).
    Produces deep analytical inference outputs per domain.
    """
    delay = random.uniform(
        settings.SLOW_MODEL_LATENCY_MIN, settings.SLOW_MODEL_LATENCY_MAX
    )
    await asyncio.sleep(delay)

    if domain == "iot":
        readings = payload_data.get("reading_array", [0.0])
        mean_val = sum(readings) / max(len(readings), 1)
        variance = sum((x - mean_val) ** 2 for x in readings) / max(len(readings), 1)
        return {
            "inference_type": "deep_recurrent_telemetry_forecasting",
            "device_id": payload_data.get("device_id"),
            "sensor_type": payload_data.get("sensor_type"),
            "readings_analyzed": len(readings),
            "mean_reading": round(mean_val, 3),
            "variance": round(variance, 4),
            "lstm_reconstruction_error": 0.0142,
            "anomaly_probability": 0.038,
            "predicted_trend_next_6h": "stable_within_bounds",
            "recommended_action": "continue_nominal_telemetry",
            "model_architecture": "BiLSTM-Attention-Autoencoder-v2",
        }

    elif domain == "mobile_media":
        return {
            "inference_type": "high_res_multi_label_segmentation",
            "client_id": payload_data.get("client_id"),
            "mode": payload_data.get("mode", "object_detection"),
            "image_dimension": payload_data.get("image_dimension"),
            "segmented_instances_count": 5,
            "detected_objects": [
                {"label": "automobile", "confidence": 0.982, "pixel_area": 48200},
                {"label": "pedestrian", "confidence": 0.947, "pixel_area": 11300},
                {"label": "traffic_sign", "confidence": 0.912, "pixel_area": 3400},
            ],
            "feature_embedding_summary": {
                "dimensions": 4096,
                "norm_l2": 1.0,
                "latent_class": "urban_street_scene",
            },
            "model_architecture": "Mask-RCNN-ResNet101-FPN",
        }

    elif domain == "geospatial":
        lat = payload_data.get("latitude", 0.0)
        lon = payload_data.get("longitude", 0.0)
        speed = payload_data.get("speed", 0.0)
        return {
            "inference_type": "spatiotemporal_trajectory_optimization",
            "unit_id": payload_data.get("unit_id"),
            "coordinates": {"lat": lat, "lon": lon},
            "spatial_density_score": 0.84,
            "nearest_congestion_hotspots": ["Sector-4-Junction", "Ring-Road-Exit"],
            "optimized_waypoints": [
                {"step": 1, "lat": round(lat + 0.005, 4), "lon": round(lon + 0.008, 4), "eta_sec": 95},
                {"step": 2, "lat": round(lat + 0.012, 4), "lon": round(lon + 0.015, 4), "eta_sec": 190},
            ],
            "recommended_speed_kmh": round(max(30.0, min(80.0, speed * 1.1)), 1),
            "fuel_efficiency_score": "optimal",
            "model_architecture": "Spatiotemporal-Graph-Convolutional-Net",
        }

    elif domain == "ai_nlp":
        text = payload_data.get("input_text", "")
        tokens = payload_data.get("prompt_tokens", len(text.split()))
        return {
            "inference_type": "deep_contextual_comprehension_and_summarization",
            "prompt_tokens": tokens,
            "temperature": payload_data.get("temperature", 0.7),
            "executive_summary": (
                f"Contextual analysis performed across {tokens} tokens. "
                "Core themes: cloud-native routing, distributed reliability, and adaptive inference."
            ),
            "sentiment_polarity": 0.89,
            "named_entities": [
                {"entity": "AI Inference Service", "type": "SYSTEM", "confidence": 0.99},
                {"entity": "Redis Queue", "type": "INFRASTRUCTURE", "confidence": 0.98},
            ],
            "perplexity_score": 12.4,
            "model_architecture": "Llama-3-8B-Instruct-Simulated",
        }

    else:
        return {
            "inference_type": "generic_batch_inference",
            "domain": domain,
            "processed": True,
        }


# =============================================================================
# Task Processing Logic
# =============================================================================

async def process_task(
    db: AsyncIOMotorDatabase,
    redis: aioredis.Redis,
    task_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Process a single queued inference task popped from Redis.
    Updates MongoDB request status and persists the result document.
    """
    request_id = task_data.get("request_id")
    domain = task_data.get("domain", "unknown")
    payload = task_data.get("payload", {})
    routing_reason = task_data.get("routing_reason", RoutingReason.LATENCY_FLEXIBLE.value)

    if not request_id:
        logger.warning("Received invalid task payload without request_id: %s", task_data)
        return None

    logger.info("Processing queued task: %s (domain=%s, reason=%s)", request_id, domain, routing_reason)

    try:
        # 1. Update status to 'processing'
        await update_request_status(db, request_id, RequestStatus.PROCESSING.value)

        # 2. Execute Slow Model computation (3.0s - 4.0s)
        start_time = time.time()
        output_data = await execute_slow_inference(domain, payload)
        processing_time_ms = round((time.time() - start_time) * 1000, 2)

        # 3. Persist processed output into MongoDB `inference_results`
        res_doc = InferenceResultDocument(
            request_id=request_id,
            model_used=ModelUsed.SLOW.value,
            routing_reason=routing_reason,
            processing_time_ms=processing_time_ms,
            output_data=output_data,
        )
        await create_inference_result(db, res_doc)

        # 4. Mark request status as 'completed'
        await update_request_status(db, request_id, RequestStatus.COMPLETED.value)

        # 5. Record telemetry latency in Redis
        await metrics.record_latency(redis, processing_time_ms)

        logger.info(
            "Task %s completed in %.2fms by Slow Model",
            request_id,
            processing_time_ms,
        )
        return res_doc.model_dump()

    except Exception as exc:
        logger.error("Error processing task %s: %s", request_id, exc, exc_info=True)
        # Mark as failed in MongoDB
        try:
            await update_request_status(db, request_id, RequestStatus.FAILED.value)
            await write_audit_log(
                db,
                event_type=AuditEventType.WORKER_ERROR.value,
                details={"request_id": request_id, "error": str(exc)},
            )
        except Exception:
            pass
        return None


# =============================================================================
# Main Worker Consumer Loop
# =============================================================================

async def run_worker() -> None:
    """Connect to Redis & MongoDB and run the non-busy BRPOP consumer loop."""
    logger.info("🚀 Starting Decoupled Background Inference Worker...")
    logger.info("   MongoDB URL: %s (DB: %s)", settings.MONGODB_URL, settings.MONGODB_DB_NAME)
    logger.info("   Redis URL:   %s (Queue: %s)", settings.REDIS_URL, settings.REDIS_QUEUE_KEY)

    # 1. Initialize MongoDB client
    mongo_client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        serverSelectionTimeoutMS=5000,
    )
    db = mongo_client[settings.MONGODB_DB_NAME]

    # Verify MongoDB connectivity
    try:
        await db.command("ping")
        logger.info("✅ Connected to MongoDB.")
    except Exception as exc:
        logger.error("❌ MongoDB connection failed: %s", exc)
        return

    # 2. Initialize Redis client
    redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    try:
        await redis.ping()
        logger.info("✅ Connected to Redis.")
    except Exception as exc:
        logger.error("❌ Redis connection failed: %s", exc)
        mongo_client.close()
        return

    # Write worker started audit log
    worker_uuid = str(uuid.uuid4())[:8]
    await write_audit_log(
        db,
        event_type=AuditEventType.WORKER_STARTED.value,
        details={"worker_id": worker_uuid, "queue": settings.REDIS_QUEUE_KEY},
    )

    logger.info(
        "🟢 Worker [%s] ready. Waiting for tasks on '%s' (Slow Model delay: %.1f-%.1fs)...",
        worker_uuid,
        settings.REDIS_QUEUE_KEY,
        settings.SLOW_MODEL_LATENCY_MIN,
        settings.SLOW_MODEL_LATENCY_MAX,
    )

    # 3. Main blocking BRPOP loop
    try:
        while _running:
            try:
                # BRPOP with 2-second timeout so the loop can check `_running` periodically
                pop_result = await redis.brpop([settings.REDIS_QUEUE_KEY], timeout=2)
                if not pop_result:
                    continue

                _, raw_data = pop_result
                try:
                    task_data = json.loads(raw_data)
                except Exception as json_err:
                    logger.warning("Failed to parse task JSON: %s (payload: %s)", json_err, raw_data)
                    continue

                await process_task(db, redis, task_data)

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.error("Unexpected error in worker consumer loop: %s", loop_err)
                await asyncio.sleep(1)

    finally:
        logger.info("🔌 Shutting down worker connections...")
        await redis.aclose()
        mongo_client.close()
        logger.info("✅ Worker gracefully stopped.")


def main():
    """Worker process entrypoint."""
    # Register termination signals
    if sys.platform != "win32":
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: _handle_shutdown_signal(s, None))
        try:
            loop.run_until_complete(run_worker())
        finally:
            loop.close()
    else:
        # On Windows, register standard signal handlers
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
