"""Applies a priority to a real network flow pattern via tc/iptables.

Deliberately decoupled from how the priority was computed (classify,
traffic creation, or a captured flow) -- this endpoint only needs a
protocol/port/priority triple, so any of those sources can drive it.
"""
from flask import Blueprint, jsonify, request

from models.schemas import APIError, parse_json_body, require_string_field
from services import enforcement_service

enforce_bp = Blueprint("enforce", __name__)

_VALID_PROTOCOLS = ("tcp", "udp")


def _require_port(data: dict) -> int:
    if "port" not in data:
        raise APIError("INVALID_REQUEST", "Field 'port' is required.", 400)
    port = data["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise APIError("INVALID_REQUEST", "Field 'port' must be an integer 1-65535.", 400)
    return port


def _require_priority(data: dict) -> float:
    if "priority" not in data:
        raise APIError("INVALID_REQUEST", "Field 'priority' is required.", 400)
    priority = data["priority"]
    if isinstance(priority, bool) or not isinstance(priority, (int, float)) or not (0.0 <= priority <= 10.0):
        raise APIError("INVALID_REQUEST", "Field 'priority' must be a number 0-10.", 400)
    return float(priority)


def _optional_dst_cidr(data: dict) -> str | None:
    if data.get("dst_cidr") is None:
        return None
    raw = data["dst_cidr"]
    if not isinstance(raw, str):
        raise APIError("INVALID_REQUEST", "Field 'dst_cidr' must be a string.", 400)
    try:
        return enforcement_service.validate_dst_cidr(raw)
    except ValueError:
        raise APIError("INVALID_REQUEST", "Field 'dst_cidr' must be a valid CIDR (e.g. '10.0.0.0/24').", 400)


@enforce_bp.route("/api/enforce/apply", methods=["POST"])
def apply_enforcement():
    data = parse_json_body(request)
    protocol = require_string_field(data, "protocol").lower()
    if protocol not in _VALID_PROTOCOLS:
        raise APIError("INVALID_REQUEST", "Field 'protocol' must be 'tcp' or 'udp'.", 400)
    port = _require_port(data)
    priority = _require_priority(data)
    dst_cidr = _optional_dst_cidr(data)

    return jsonify(enforcement_service.apply_flow_priority(protocol, port, priority, dst_cidr)), 200


@enforce_bp.route("/api/enforce/status", methods=["GET"])
def enforcement_status():
    return jsonify(enforcement_service.get_status()), 200


@enforce_bp.route("/api/enforce/reset", methods=["POST"])
def reset_enforcement():
    return jsonify(enforcement_service.reset_enforcement()), 200
