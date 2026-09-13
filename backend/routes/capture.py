"""Real network traffic ingestion: reads a pcap file, extracts flows,
and runs each one through the same classify/priority pipeline as
POST /api/classify -- no separate scoring logic here.
"""
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import Config
from models.schemas import APIError, parse_json_body, require_string_field
from services import capture_service
from services.state_service import state

capture_bp = Blueprint("capture", __name__)


def _resolve_capture_path(raw_path: str) -> Path:
    """Resolve `raw_path` against Config.CAPTURES_DIR and reject
    anything that would escape it (e.g. `../../etc/passwd`) -- this
    endpoint reads arbitrary files by client-supplied name, so this
    check is the only thing standing between it and a path traversal
    read of the server's filesystem.
    """
    captures_dir = Path(Config.CAPTURES_DIR).resolve()
    candidate = (captures_dir / raw_path).resolve()

    if not candidate.is_relative_to(captures_dir):
        raise APIError(
            "INVALID_REQUEST", "pcap_path must stay within the captures directory.", 400
        )
    if candidate.suffix not in (".pcap", ".pcapng"):
        raise APIError(
            "INVALID_REQUEST", "pcap_path must point to a .pcap or .pcapng file.", 400
        )
    if not candidate.is_file():
        raise APIError("NOT_FOUND", f"No capture file found at '{raw_path}'.", 404)
    return candidate


@capture_bp.route("/api/capture/analyze", methods=["POST"])
def analyze_capture():
    data = parse_json_body(request)
    raw_path = require_string_field(data, "pcap_path")
    resolved = _resolve_capture_path(raw_path)

    try:
        flows = capture_service.extract_flows(str(resolved), max_flows=Config.CAPTURE_MAX_FLOWS)
    except capture_service.CaptureUnavailable as exc:
        raise APIError("CAPTURE_UNAVAILABLE", str(exc), 501)

    traffic = []
    for flow in flows:
        entry = state.add_captured_traffic(flow["description"])
        traffic.append({
            **entry,
            "flow_metadata": {k: v for k, v in flow.items() if k != "description"},
        })

    return jsonify({"flows_processed": len(traffic), "traffic": traffic}), 200
