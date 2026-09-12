from flask import Blueprint, jsonify, request

from config import DEFAULT_LABELS
from models.schemas import (
    optional_positive_number_field,
    optional_string_field,
    parse_json_body,
    require_string_field,
    require_traffic_type,
)
from services.classifier_service import ClassifierUnavailableError, classify_text
from services import routing_service, simulation_service
from services.state_service import state

traffic_bp = Blueprint("traffic", __name__)


@traffic_bp.route("/api/network/status", methods=["GET"])
def get_network_status():
    return jsonify(routing_service.get_network_status()), 200


@traffic_bp.route("/api/traffic", methods=["GET"])
def get_traffic():
    return jsonify({"traffic": simulation_service.traffic_with_metrics()}), 200


@traffic_bp.route("/api/traffic/throughput-comparison", methods=["GET"])
def get_throughput_comparison():
    return jsonify(simulation_service.throughput_comparison()), 200


@traffic_bp.route("/api/traffic", methods=["POST"])
def create_traffic():
    data = parse_json_body(request)
    traffic_type = require_traffic_type(data)
    label = optional_string_field(data, "label") or DEFAULT_LABELS[traffic_type]
    requested_mbps = optional_positive_number_field(data, "requested_mbps")

    entry = state.add_traffic(traffic_type, label, requested_mbps=requested_mbps)
    live_entry = next(
        item for item in simulation_service.traffic_with_metrics() if item["id"] == entry["id"]
    )
    return jsonify(live_entry), 201


@traffic_bp.route("/api/traffic/analyze", methods=["POST"])
def analyze_traffic():
    """Classify a payload and add the result to the live traffic stream."""
    data = parse_json_body(request)
    payload = require_string_field(data, "input")
    requested_mbps = optional_positive_number_field(data, "requested_mbps")
    try:
        classification = classify_text(payload)
    except ClassifierUnavailableError as error:
        return jsonify({"error": {"code": "CLASSIFIER_UNAVAILABLE", "message": str(error)}}), 503
    entry = state.add_traffic(
        classification["category"],
        payload,
        criticality_score=classification["criticality_score"],
        classification={
            "confidence": classification["confidence"],
            "reasoning": classification["reasoning"],
            "provider": classification["provider"],
        },
        requested_mbps=requested_mbps,
    )
    live_entry = next(
        item for item in simulation_service.traffic_with_metrics() if item["id"] == entry["id"]
    )
    return jsonify({**live_entry, "payload": payload, **classification}), 201
