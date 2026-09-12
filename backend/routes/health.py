from flask import Blueprint, jsonify

from config import SERVICE_NAME, VERSION

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health", methods=["GET"])
def get_health():
    return jsonify({"status": "ok", "service": SERVICE_NAME, "version": VERSION}), 200
