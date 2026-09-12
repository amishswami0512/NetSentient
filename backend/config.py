"""Centralized configuration for the Semantic Router API.

All "magic numbers" that matter for the demo (priorities, CORS origins,
limits) live here so they are never scattered across route/service files.
"""
import os

from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = "semantic-router-api"
VERSION = "1.0.0"

# Semantic priority mapping. Higher number = higher priority.
# This is the single source of truth for priority scoring.
PRIORITY_MAP = {
    "emergency": 10,
    "critical_sensor": 9,
    "video": 5,
    "file": 2,
    "background": 1,
}

# Default human-readable labels used when a caller doesn't supply one.
DEFAULT_LABELS = {
    "emergency": "Emergency Alert",
    "critical_sensor": "Critical Sensor",
    "video": "Video Call",
    "file": "File Transfer",
    "background": "Background Update",
}

SUPPORTED_TRAFFIC_TYPES = list(PRIORITY_MAP.keys())
MAX_PRIORITY = max(PRIORITY_MAP.values())


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class Config:
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    HOST = os.environ.get("HOST", "0.0.0.0")

    # Comma-separated list of allowed frontend origins for CORS.
    ALLOWED_ORIGINS = _parse_origins(
        os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        )
    )

    # Reject request bodies larger than this (bytes). Protects the demo
    # server from accidental/malicious huge payloads without adding
    # real auth/security infrastructure.
    MAX_CONTENT_LENGTH_BYTES = int(
        os.environ.get("MAX_CONTENT_LENGTH_BYTES", str(64 * 1024))
    )
