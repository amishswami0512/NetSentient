from flask import Blueprint, jsonify, request

from models.schemas import parse_json_body, require_string_field
from services import priority_service, semantic_service

classify_bp = Blueprint("classify", __name__)


@classify_bp.route("/api/classify", methods=["POST"])
def classify():
    data = parse_json_body(request)
    text = require_string_field(data, "input")

    analysis = semantic_service.analyze(text)
    scored = priority_service.score(analysis["category"], analysis["confidence"], analysis["factors"])

    return jsonify(
        {
            "category": analysis["category"],
            "confidence": analysis["confidence"],
            "priority": scored["priority"],
            "priority_factors": analysis["factors"],
            "low_confidence": scored["low_confidence"],
            "source": analysis["source"],
            "reason": analysis["reason"],
        }
    ), 200
