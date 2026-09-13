from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from config import DEFAULT_LABELS
from models.schemas import optional_string_field, parse_json_body, require_traffic_type
from services import routing_service, simulation_service
from services.traffic_scanner_service import scan_active_connections
from services.state_service import state

traffic_bp = Blueprint("traffic", __name__)


@traffic_bp.route("/api/network/status", methods=["GET"])
def get_network_status():
    return jsonify(routing_service.get_network_status()), 200


@traffic_bp.route("/api/traffic", methods=["GET"])
def get_traffic():
    return jsonify({"traffic": simulation_service.traffic_with_metrics()}), 200


@traffic_bp.route("/api/traffic", methods=["POST"])
def create_traffic():
    data = parse_json_body(request)
    traffic_type = require_traffic_type(data)
    label = optional_string_field(data, "label") or DEFAULT_LABELS[traffic_type]

    entry = state.add_traffic(traffic_type, label)
    congestion = state.get_congestion()
    semantic = state.get_semantic_routing()
    metrics = routing_service.compute_metrics(entry["priority"], congestion, semantic)

    return jsonify({**entry, **metrics}), 201


@traffic_bp.route("/api/traffic/scan", methods=["POST"])
def scan_traffic():
    scanned = scan_active_connections()
    return jsonify({
        "traffic": simulation_service.traffic_with_metrics_for_entries(scanned),
        "count": len(scanned),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }), 200
