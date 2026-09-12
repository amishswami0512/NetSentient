from flask import Blueprint, jsonify

from services import routing_service, simulation_service
from services.state_service import state

demo_bp = Blueprint("demo", __name__)


@demo_bp.route("/api/demo/reset", methods=["POST"])
def demo_reset():
    traffic = simulation_service.seed_demo_traffic()
    return jsonify({"traffic": traffic, "network": routing_service.get_network_status()}), 200


@demo_bp.route("/api/demo/congest", methods=["POST"])
def demo_congest():
    state.set_congestion(True)
    return jsonify(simulation_service.run_simulation()), 200


@demo_bp.route("/api/demo/compare", methods=["POST"])
def demo_compare():
    return jsonify(simulation_service.compare_routing_modes()), 200
