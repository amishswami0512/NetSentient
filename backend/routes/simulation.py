from flask import Blueprint, jsonify, request

from models.schemas import parse_json_body, require_bool_field
from services import routing_service, simulation_service
from services.state_service import state

simulation_bp = Blueprint("simulation", __name__)


@simulation_bp.route("/api/simulation/congestion", methods=["POST"])
def set_congestion():
    data = parse_json_body(request)
    enabled = require_bool_field(data, "enabled")
    state.set_congestion(enabled)
    status = routing_service.get_network_status()
    return jsonify(
        {
            "congestion": status["congestion"],
            "load_percent": status["load_percent"],
            "bandwidth_mbps": status["bandwidth_mbps"],
            "latency_ms": status["latency_ms"],
            "measurement_ok": status["measurement_ok"],
            "measurement_source": status["measurement_source"],
        }
    ), 200


@simulation_bp.route("/api/simulation/semantic-routing", methods=["POST"])
def set_semantic_routing():
    data = parse_json_body(request)
    enabled = require_bool_field(data, "enabled")
    state.set_semantic_routing(enabled)
    return jsonify({"semantic_routing_enabled": state.get_semantic_routing()}), 200


@simulation_bp.route("/api/simulation/run", methods=["POST"])
def run_simulation():
    return jsonify(simulation_service.run_simulation()), 200


@simulation_bp.route("/api/simulation/reset", methods=["POST"])
def reset_simulation():
    state.reset()
    return jsonify(
        {
            "status": "reset",
            "network": routing_service.get_network_status(),
            "traffic": [],
        }
    ), 200
