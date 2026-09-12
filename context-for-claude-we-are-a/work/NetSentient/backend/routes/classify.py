from flask import Blueprint, jsonify, request

from models.schemas import parse_json_body, require_string_field
from services.classifier_service import ClassifierUnavailableError, classify_text

classify_bp = Blueprint("classify", __name__)


@classify_bp.route("/api/classify", methods=["POST"])
def classify():
    data = parse_json_body(request)
    text = require_string_field(data, "input")
    try:
        return jsonify(classify_text(text)), 200
    except ClassifierUnavailableError as error:
        return jsonify({"error": {"code": "CLASSIFIER_UNAVAILABLE", "message": str(error)}}), 503
