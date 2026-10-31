"""
app/models/domains.py
─────────────────────
Four domain-specific inference payload schemas (SRS §2.2, §3):
  • IoT Sensor Telemetry
  • Mobile Media Inference
  • Geospatial Tracking
  • AI / NLP Request

Uses Pydantic v2 discriminated unions on the `domain` literal field so that
FastAPI can automatically validate, document, and deserialise the correct
sub-schema from a single polymorphic JSON body.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# =============================================================================
# IoT Sensor Telemetry  (SRS §2.2 row 1)
# =============================================================================

class IoTPayload(BaseModel):
    """
    Lightweight numeric payload — anomaly detection / classification simulation.

    Example:
        {
          "domain": "iot",
          "device_id": "sensor_001",
          "sensor_type": "temperature",
          "reading_array": [23.4, 23.6, 23.5, 23.7],
          "timestamp": "2026-11-01T00:00:00Z"
        }
    """

    domain: Literal["iot"] = "iot"

    device_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Unique physical device identifier (e.g. sensor_001, edge-node-A)",
    )
    sensor_type: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Sensor category — e.g. temperature, humidity, pressure, vibration",
    )
    reading_array: list[float] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Ordered array of sensor readings captured in the telemetry window",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 UTC timestamp when the readings were captured",
    )


# =============================================================================
# Mobile Media Inference  (SRS §2.2 row 2)
# =============================================================================

class MobileMediaPayload(BaseModel):
    """
    Medium-sized feature arrays — object detection / classification simulation.

    Example:
        {
          "domain": "mobile_media",
          "client_id": "mobile_client_42",
          "image_dimension": "640x480",
          "feature_vector": [0.12, 0.85, 0.33],
          "mode": "object_detection"
        }
    """

    domain: Literal["mobile_media"] = "mobile_media"

    client_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Unique mobile client or session identifier",
    )
    image_dimension: str = Field(
        ...,
        description="Image resolution string — e.g. 640x480, 1920x1080",
        examples=["640x480", "1280x720", "1920x1080"],
    )
    feature_vector: list[float] = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Pre-extracted feature vector from the client-side encoder",
    )
    mode: str = Field(
        ...,
        description="Inference mode — e.g. object_detection, segmentation, classification",
        examples=["object_detection", "segmentation", "classification"],
    )


# =============================================================================
# Geospatial Tracking  (SRS §2.2 row 3)
# =============================================================================

class GeospatialPayload(BaseModel):
    """
    Location coordinate telemetry — spatial clustering simulation.

    Example:
        {
          "domain": "geospatial",
          "unit_id": "vehicle_007",
          "latitude": 30.3165,
          "longitude": 78.0322,
          "speed": 62.5,
          "altitude": 345.0
        }
    """

    domain: Literal["geospatial"] = "geospatial"

    unit_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Tracked asset identifier — vehicle, drone, container, etc.",
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees (WGS-84)",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees (WGS-84)",
    )
    speed: float = Field(
        ...,
        ge=0.0,
        description="Speed in km/h at time of capture",
    )
    altitude: float = Field(
        ...,
        description="Altitude above sea level in metres",
    )


# =============================================================================
# AI / NLP Request  (SRS §2.2 row 4)
# =============================================================================

class AINLPPayload(BaseModel):
    """
    Text embedding and sentiment classification simulation.

    Example:
        {
          "domain": "ai_nlp",
          "prompt_tokens": 128,
          "temperature": 0.7,
          "input_text": "Analyse the sentiment of this customer review..."
        }
    """

    domain: Literal["ai_nlp"] = "ai_nlp"

    prompt_tokens: int = Field(
        ...,
        ge=1,
        le=32768,
        description="Number of input tokens in the prompt",
    )
    temperature: float = Field(
        ...,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic, 2 = very random)",
    )
    input_text: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="Raw input text to be embedded or classified",
    )


# =============================================================================
# Discriminated Union — used in PredictRequest
# =============================================================================

# Pydantic v2 uses the `domain` Literal field as the discriminator key.
# FastAPI will surface all four sub-schemas correctly in OpenAPI /docs.
DomainPayload = Annotated[
    Union[IoTPayload, MobileMediaPayload, GeospatialPayload, AINLPPayload],
    Field(discriminator="domain"),
]

