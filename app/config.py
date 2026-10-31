"""
app/config.py — Centralised configuration for all viva-tunable thresholds.

All values are read from environment variables (loaded from `.env`).
Change any threshold in `.env` and restart — no code changes required.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Single source of truth for every configurable parameter in the system.
    Corresponds directly to the SRS §2.6 and §4.1 thresholds.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── MongoDB ─────────────────────────────────────────────────────────────
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "ai_inference_db"

    # ─── Redis ───────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ─── JWT Authentication ───────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "CHANGE_ME_to_a_strong_secret_key_min_32_chars"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ─── Fast Model Thresholds (SRS §2.6, §4.1 NFR-P1) ──────────────────────
    FAST_MODEL_MAX_CONCURRENCY: int = 5
    FAST_MODEL_LATENCY_MIN: float = 0.1    # seconds
    FAST_MODEL_LATENCY_MAX: float = 0.2    # seconds
    FAST_MODEL_TIMEOUT: float = 0.5        # seconds — triggers circuit failure

    # ─── Slow Model / Background Worker (SRS §2.1) ───────────────────────────
    SLOW_MODEL_LATENCY_MIN: float = 3.0   # seconds
    SLOW_MODEL_LATENCY_MAX: float = 4.0   # seconds

    # ─── Queue Backpressure (SRS §2.1 Step 3, FR-7) ──────────────────────────
    MAX_QUEUE_DEPTH: int = 50

    # ─── Rate Limiting — Sliding Window (SRS §2.1 Step 2, FR) ───────────────
    RATE_LIMIT_PER_MIN: int = 60

    # ─── Idempotency Engine (SRS §2.1 Step 1, FR-2) ──────────────────────────
    IDEMPOTENCY_TTL_SECONDS: int = 30

    # ─── Circuit Breaker (SRS §2.1 Step 6, FR-9) ─────────────────────────────
    CB_FAILURE_THRESHOLD: int = 5          # failures to open circuit
    CB_FAILURE_WINDOW_SEC: int = 10        # rolling window duration
    CB_RECOVERY_TIMEOUT_SEC: int = 30      # OPEN → HALF_OPEN pause

    # ─── Redis Key Names (internal — centralised to avoid typos) ─────────────
    REDIS_QUEUE_KEY: str = "inference_queue"
    REDIS_CONCURRENCY_KEY: str = "fast_model_active"
    REDIS_CB_STATE_KEY: str = "circuit_breaker_state"
    REDIS_CB_FAILURES_KEY: str = "circuit_breaker_failures"
    REDIS_CB_OPEN_SINCE_KEY: str = "circuit_breaker_open_since"
    REDIS_FAULT_INJECT_KEY: str = "fault_inject_active"
    REDIS_IDEMPOTENCY_PREFIX: str = "idempotency:"
    REDIS_RATE_LIMIT_PREFIX: str = "rate_limit:"
    REDIS_CACHE_HIT_KEY: str = "metrics:idempotency_hits"
    REDIS_LATENCY_KEY: str = "metrics:latencies"
    REDIS_RPS_KEY: str = "metrics:rps"


# Module-level singleton — import this everywhere
settings = Settings()

