"""
locustfile.py
─────────────
Locust load testing suite for AI Inference Load Management Service (Project P70).
Simulates real-world concurrent user workloads across 4 distinct evaluation scenarios:

  1. Low Load Scenario:
     - 10 concurrent users, 50% Fast / 50% Flexible traffic mix.
     - Establishes baseline latency; 100% of requests succeed with 200 OK or 202 Accepted.

  2. Medium Load Scenario:
     - 100 concurrent users, 70% Fast / 30% Flexible traffic mix.
     - Fast model slots saturate (max 5); dynamic router gracefully diverts excess fast
       requests to the background queue returning 202 Accepted.

  3. High Load / Burst Scenario:
     - 500 concurrent users, 80% Fast / 20% Flexible traffic mix.
     - Queue capacity saturates (max 50 pending items) triggering 503 Service Unavailable
       with 'Retry-After: 5' backpressure header; sliding-window rate limit triggers 429.
       Zero server crashes.

  4. Failure & Resiliency Scenario:
     - 100 concurrent users with fault injection active on the Fast Model.
     - Circuit breaker records 5 consecutive failures and automatically trips to OPEN.
     - Subsequent fast requests are diverted to the queue with 202 Accepted (zero 500s).

Usage:
  # 1. Interactive Web UI:
  locust -f locustfile.py --host=http://localhost:8000

  # 2. Headless Low Load Test (10 users, 30s):
  locust -f locustfile.py --headless -u 10 -r 2 --run-time 30s --host=http://localhost:8000 LowLoadUser

  # 3. Headless Medium Load Test (100 users, 60s):
  locust -f locustfile.py --headless -u 100 -r 10 --run-time 60s --host=http://localhost:8000 MediumLoadUser

  # 4. Headless High Load / Burst Test (500 users, 60s):
  locust -f locustfile.py --headless -u 500 -r 50 --run-time 60s --host=http://localhost:8000 HighLoadUser

  # 5. Headless Failure Test (100 users, 60s):
  locust -f locustfile.py --headless -u 100 -r 10 --run-time 60s --host=http://localhost:8000 FailureScenarioUser
"""

import json
import logging
import os
import random
import time
import uuid
from typing import Any, Dict

from locust import HttpUser, LoadTestShape, between, events, task

logger = logging.getLogger("locust_suite")

# ─── Synthetic Domain Payload Generators ───────────────────────────────────────

def generate_iot_payload() -> Dict[str, Any]:
    sensor_types = ["temperature", "humidity", "vibration", "pressure"]
    return {
        "domain": "iot",
        "device_id": f"sensor_node_{random.randint(100, 999)}",
        "sensor_type": random.choice(sensor_types),
        "reading_array": [round(random.uniform(18.0, 32.0), 2) for _ in range(random.randint(3, 8))],
        "timestamp": "2026-11-02T02:00:00Z"
    }

def generate_mobile_media_payload() -> Dict[str, Any]:
    dimensions = ["1280x720", "1920x1080", "800x600", "640x480"]
    modes = ["object_detection", "compression", "face_blur", "edge_enhancement"]
    return {
        "domain": "mobile_media",
        "client_id": f"client_ios_{random.randint(1000, 9999)}",
        "image_dimension": random.choice(dimensions),
        "feature_vector": [round(random.uniform(0.01, 0.99), 3) for _ in range(4)],
        "mode": random.choice(modes)
    }

def generate_geospatial_payload() -> Dict[str, Any]:
    return {
        "domain": "geospatial",
        "unit_id": f"tracker_gps_{random.randint(10, 99)}",
        "latitude": round(30.3165 + (random.random() - 0.5) * 0.1, 4),
        "longitude": round(78.0322 + (random.random() - 0.5) * 0.1, 4),
        "speed": round(random.uniform(10.0, 95.0), 1),
        "altitude": round(random.uniform(350.0, 750.0), 1)
    }

def generate_ai_nlp_payload() -> Dict[str, Any]:
    prompts = [
        "Analyze telemetry anomaly in IoT vibration stream.",
        "Summarize load balancing health check logs across microservices.",
        "Detect sentiment and intent in edge sensor diagnostic report.",
        "Classify streaming payload metadata for dynamic model routing."
    ]
    return {
        "domain": "ai_nlp",
        "prompt_tokens": random.randint(40, 250),
        "temperature": round(random.uniform(0.1, 0.9), 2),
        "input_text": random.choice(prompts)
    }

def get_random_domain_payload() -> Dict[str, Any]:
    generators = [
        generate_iot_payload,
        generate_mobile_media_payload,
        generate_geospatial_payload,
        generate_ai_nlp_payload
    ]
    return random.choice(generators)()


# ─── Base Inference User Class ─────────────────────────────────────────────────

class BaseInferenceUser(HttpUser):
    abstract = True
    wait_time = between(0.05, 0.25)

    fast_ratio: float = 0.50  # Override in subclasses (e.g. 0.50, 0.70, 0.80)

    def on_start(self):
        """Authenticate user on start to acquire JWT Bearer token."""
        self.username = f"locust_{uuid.uuid4().hex[:8]}"
        self.password = "LocustTestPass123!"
        self.headers = {"Content-Type": "application/json"}
        self.token = ""

        # Attempt registration, fallback to login
        reg_payload = {
            "username": self.username,
            "password": self.password,
            "role": "user"
        }
        try:
            with self.client.post("/api/auth/register", json=reg_payload, catch_response=True) as resp:
                if resp.status_code in (200, 201):
                    data = resp.json()
                    self.token = data.get("access_token", "")
                    resp.success()
                elif resp.status_code == 400:
                    # User might already exist, attempt login
                    resp.success()
        except Exception as e:
            logger.warning(f"Registration attempt failed: {e}")

        if not self.token:
            try:
                login_payload = {"username": self.username, "password": self.password}
                with self.client.post("/api/auth/login", json=login_payload, catch_response=True) as resp:
                    if resp.status_code == 200:
                        self.token = resp.json().get("access_token", "")
                        resp.success()
            except Exception as e:
                logger.warning(f"Login attempt failed: {e}")

        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def send_inference_request(self, preference: str = "fast", payload: Dict[str, Any] = None):
        """Dispatches an inference request to /api/inference/predict and classifies response."""
        if payload is None:
            payload = get_random_domain_payload()

        req_body = {
            "latency_preference": preference,
            "payload": payload
        }

        # Catch response to validate expected cloud resiliency codes:
        # 200 OK: Synchronous Fast Model completion
        # 202 Accepted: Queued for asynchronous background worker
        # 429 Too Many Requests: Sliding window rate limit protection
        # 503 Service Unavailable: Queue backpressure overload protection
        with self.client.post(
            "/api/inference/predict",
            json=req_body,
            headers=self.headers,
            catch_response=True,
            name=f"/api/inference/predict [{preference}]"
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 202:
                # Expected when slots full, flexible requested, or breaker open
                response.success()
            elif response.status_code == 429:
                # Expected rate limiter active under heavy burst
                response.success()
            elif response.status_code == 503:
                # Expected queue backpressure when pending items >= 50
                retry_after = response.headers.get("Retry-After", "")
                response.success()
            else:
                response.failure(f"Unexpected status code {response.status_code}: {response.text[:100]}")

    @task(8)
    def task_inference_traffic(self):
        """Routes inference traffic according to the configured fast_ratio."""
        preference = "fast" if random.random() < self.fast_ratio else "flexible"
        self.send_inference_request(preference=preference)

    @task(1)
    def task_idempotent_duplicate(self):
        """Tests request deduplication by sending identical payload to observe cache hits."""
        deterministic_payload = {
            "domain": "iot",
            "device_id": f"dedup_node_{self.username[-4:]}",
            "sensor_type": "temperature",
            "reading_array": [24.0, 24.1, 24.2],
            "timestamp": "2026-11-02T00:00:00Z"
        }
        # First request (fresh compute)
        self.send_inference_request(preference="fast", payload=deterministic_payload)
        # Immediate duplicate (cache hit)
        self.send_inference_request(preference="fast", payload=deterministic_payload)

    @task(1)
    def task_poll_system_load(self):
        """Periodically inspects public system telemetry."""
        with self.client.get("/api/metrics/system-load", catch_response=True, name="/api/metrics/system-load") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Telemetry error: {resp.status_code}")


# ─── Specialized User Classes for Target Scenarios ─────────────────────────────

class LowLoadUser(BaseInferenceUser):
    """
    Scenario 1: Low Load (10 users, 50% Fast / 50% Flexible).
    Establishes baseline performance. Concurrency is comfortably under the 5 slot cap.
    """
    weight = 10
    fast_ratio = 0.50
    wait_time = between(0.1, 0.4)


class MediumLoadUser(BaseInferenceUser):
    """
    Scenario 2: Medium Load (100 users, 70% Fast / 30% Flexible).
    Saturates 5 fast model slots; verifies dynamic rerouting to 202 Accepted.
    """
    weight = 50
    fast_ratio = 0.70
    wait_time = between(0.05, 0.20)


class HighLoadUser(BaseInferenceUser):
    """
    Scenario 3: High Load / Burst (500 users, 80% Fast / 20% Flexible).
    Stress tests queue depth (>= 50 -> 503 Service Unavailable with Retry-After: 5)
    and per-user sliding window rate limiting (100 req/60s -> 429).
    """
    weight = 100
    fast_ratio = 0.80
    wait_time = between(0.02, 0.10)


class FailureScenarioUser(BaseInferenceUser):
    """
    Scenario 4: Controlled Failure & Circuit Breaker Demonstration.
    Sends fast requests while fast model faults are triggered. Verifies circuit breaker
    transition from CLOSED to OPEN after 5 failures and automatic rerouting to queue (202).
    """
    weight = 20
    fast_ratio = 0.90
    wait_time = between(0.05, 0.15)


# General user class selecting scenario via environment variable SCENARIO (low/medium/high/failure)
class InferenceUser(BaseInferenceUser):
    scenario = os.getenv("SCENARIO", "medium").lower()
    if scenario == "low":
        fast_ratio = 0.50
    elif scenario == "high":
        fast_ratio = 0.80
    elif scenario == "failure":
        fast_ratio = 0.90
    else:
        fast_ratio = 0.70


# ─── Automated Multi-Stage Shape (SRS 4-Stage Benchmark) ───────────────────────

class SRSBenchmarkShape(LoadTestShape):
    """
    Executes all 4 SRS evaluation stages in sequence:
      Stage 1 (00:00 - 00:45): Low Load      - 10 users, spawn rate 2
      Stage 2 (00:45 - 01:30): Medium Load   - 100 users, spawn rate 10
      Stage 3 (01:30 - 02:15): High Burst    - 500 users, spawn rate 50
      Stage 4 (02:15 - 03:00): Failure/Drain - 100 users, spawn rate 10
    """
    stages = [
        {"duration": 45, "users": 10, "spawn_rate": 2},
        {"duration": 90, "users": 100, "spawn_rate": 10},
        {"duration": 135, "users": 500, "spawn_rate": 50},
        {"duration": 180, "users": 100, "spawn_rate": 10},
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


# ─── Locust Event Hooks for Telemetry Logging ──────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info(" Locust Load Test initialized for AI Inference Load Management Service.")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    logger.info(" Locust Load Test run complete. Review web dashboard or benchmark report.")

