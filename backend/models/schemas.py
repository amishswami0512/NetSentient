"""Request validation helpers and the shared API error type.

Every route funnels bad input through APIError so the error response
shape (see app.py's error handler) is always identical.
"""
from typing import Any

from flask import Request

from config import SUPPORTED_TRAFFIC_TYPES


class APIError(Exception):
    """Raised for any client-facing validation failure.

    Caught centrally in app.py and turned into the standard
    {"error": {"code": ..., "message": ...}} JSON response.
    """

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def parse_json_body(request: Request) -> dict[str, Any]:
    """Parse the request body as a JSON object, or raise APIError.

    Uses silent=True so Flask/Werkzeug never raises its own HTML-based
    400 error for malformed JSON -- every bad-body case is normalized
    into our own JSON error shape here.
    """
    data = request.get_json(silent=True)
    if data is None:
        raise APIError(
            "INVALID_REQUEST",
            "Request body must be valid JSON.",
            400,
        )
    if not isinstance(data, dict):
        raise APIError(
            "INVALID_REQUEST",
            "Request body must be a JSON object.",
            400,
        )
    return data


def require_string_field(data: dict[str, Any], field: str) -> str:
    if field not in data:
        raise APIError(
            "INVALID_REQUEST", f"Field '{field}' is required.", 400
        )
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise APIError(
            "INVALID_REQUEST",
            f"Field '{field}' must be a non-empty string.",
            400,
        )
    return value.strip()


def optional_string_field(data: dict[str, Any], field: str) -> str | None:
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise APIError(
            "INVALID_REQUEST",
            f"Field '{field}' must be a non-empty string.",
            400,
        )
    return value.strip()


def require_traffic_type(data: dict[str, Any]) -> str:
    value = require_string_field(data, "type")
    if value not in SUPPORTED_TRAFFIC_TYPES:
        raise APIError(
            "INVALID_REQUEST",
            f"Field 'type' must be one of: {', '.join(SUPPORTED_TRAFFIC_TYPES)}.",
            400,
        )
    return value


def require_bool_field(data: dict[str, Any], field: str) -> bool:
    if field not in data:
        raise APIError(
            "INVALID_REQUEST", f"Field '{field}' is required.", 400
        )
    value = data[field]
    if not isinstance(value, bool):
        raise APIError(
            "INVALID_REQUEST",
            f"Field '{field}' must be a boolean (true or false).",
            400,
        )
    return value
