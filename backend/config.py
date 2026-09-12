import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

SERVICE_NAME = "semantic-router-api"
VERSION = "1.0.0"

PRIORITY_MAP = {
    "emergency": 10,
    "critical_sensor": 9,
    "video": 5,
    "file": 2,
    "background": 1,
}

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

    ALLOWED_ORIGINS = _parse_origins(
        os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        )
    )

    MAX_CONTENT_LENGTH_BYTES = int(
        os.environ.get("MAX_CONTENT_LENGTH_BYTES", str(64 * 1024))
    )
