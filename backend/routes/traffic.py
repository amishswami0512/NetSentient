from flask import Blueprint, jsonify, request

from config import DEFAULT_LABELS
from models.schemas import optional_string_field, parse_json_body, require_traffic_type
from services import network_scan_service, routing_service, simulation_service
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
    metrics = routing_service.compute_metrics(entry["priority"], congestion, semantic, entry["type"])

    return jsonify({**entry, **metrics}), 201


@traffic_bp.route("/api/traffic/scan", methods=["POST"])
def scan_traffic():
    connections = network_scan_service.scan_active_connections()
    congestion = state.get_congestion()
    semantic = state.get_semantic_routing()
    created = []
    for connection in connections:
        entry = state.add_traffic(connection["type"], connection["label"])
        metrics = routing_service.compute_metrics(entry["priority"], congestion, semantic, entry["type"])
        created.append({**entry, **metrics})

    return jsonify({"traffic": created}), 201