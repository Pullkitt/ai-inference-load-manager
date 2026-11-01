"""
app/services/fast_model.py
──────────────────────────
Simulated lightweight, in-process Fast Model inference service.

SRS §1.1, §2.2, §4.1 NFR-P1, AD04:
  - Latency: 0.1s – 0.2s (configurable via FAST_MODEL_LATENCY_MIN/MAX).
  - Enforces a 0.5s timeout (FAST_MODEL_TIMEOUT); timeouts trigger circuit breaker failures.
  - Generates domain-tailored inference results for:
      • iot: Anomaly detection and sensor statistics
      • mobile_media: Object classification and feature embeddings
      • geospatial: Traffic density and spatial clustering
      • ai_nlp: Sentiment analysis and text embeddings
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict

from app.config import settings


async def execute_fast_inference(
    domain: str,
    payload_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Simulate Fast Model execution with realistic domain output data.
    Enforces timeout using asyncio.wait_for.
    """
    async def _simulate():
        # Simulated inference computation delay (0.1s - 0.2s)
        delay = random.uniform(
            settings.FAST_MODEL_LATENCY_MIN, settings.FAST_MODEL_LATENCY_MAX
        )
        await asyncio.sleep(delay)

        # Generate realistic domain outputs according to SRS §2.2
        if domain == "iot":
            readings = payload_data.get("reading_array", [0.0])
            mean_val = sum(readings) / max(len(readings), 1)
            is_anomaly = any(r > 100.0 or r < -20.0 for r in readings)
            return {
                "inference_type": "sensor_telemetry_anomaly_detection",
                "device_id": payload_data.get("device_id"),
                "sensor_type": payload_data.get("sensor_type"),
                "readings_count": len(readings),
                "mean_reading": round(mean_val, 2),
                "anomaly_detected": is_anomaly,
                "confidence_score": 0.985,
                "status": "warning" if is_anomaly else "nominal",
            }

        elif domain == "mobile_media":
            return {
                "inference_type": "mobile_media_feature_classification",
                "client_id": payload_data.get("client_id"),
                "mode": payload_data.get("mode", "object_detection"),
                "image_dimension": payload_data.get("image_dimension"),
                "detected_objects": ["pedestrian", "bicycle", "traffic_light"],
                "confidence_scores": [0.96, 0.91, 0.88],
                "bounding_boxes": [
                    {"label": "pedestrian", "box": [45, 120, 180, 310]},
                    {"label": "bicycle", "box": [50, 130, 160, 290]},
                ],
            }

        elif domain == "geospatial":
            lat = payload_data.get("latitude", 0.0)
            lon = payload_data.get("longitude", 0.0)
            speed = payload_data.get("speed", 0.0)
            return {
                "inference_type": "geospatial_spatial_clustering",
                "unit_id": payload_data.get("unit_id"),
                "coordinates": {"lat": lat, "lon": lon},
                "cluster_zone_id": f"zone_grid_{abs(int(lat * 10))}_{abs(int(lon * 10))}",
                "traffic_density": "high" if speed < 20 else "normal",
                "estimated_delay_min": round(max(0, (50 - speed) * 0.2), 1),
                "eta_minutes": round(15.5 + random.uniform(-1, 1), 1),
            }

        elif domain == "ai_nlp":
            text = payload_data.get("input_text", "")
            tokens = payload_data.get("prompt_tokens", len(text.split()))
            # Simulated sentiment polarity
            is_positive = not any(w in text.lower() for w in ["bad", "fail", "slow", "error", "poor"])
            return {
                "inference_type": "ai_nlp_sentiment_classification",
                "tokens_processed": tokens,
                "sentiment": "positive" if is_positive else "negative",
                "sentiment_score": 0.94 if is_positive else 0.23,
                "embedding_dimensions": 768,
                "simulated_model": "bert-mini-finetuned",
            }

        else:
            return {
                "inference_type": "generic_classification",
                "domain": domain,
                "processed": True,
            }

    # Enforce timeout (SRS AD04)
    return await asyncio.wait_for(_simulate(), timeout=settings.FAST_MODEL_TIMEOUT)

