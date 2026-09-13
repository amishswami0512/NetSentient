"""Centralized configuration for the Semantic Router API.

All "magic numbers" that matter for the demo (priorities, CORS origins,
limits) live here so they are never scattered across route/service files.
"""
import os

from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = "semantic-router-api"
VERSION = "1.0.0"

# Legacy flat priority per category. No longer the primary priority
# mechanism -- see PRIORITY_WEIGHTS / CATEGORY_PRIORITY_BOUNDS below,
# which drive the real (context-aware) priority engine. This table now
# only backs the last-resort deterministic path (services/classifier_
# service.py's classify_text(), used when nothing else is available)
# and the demo's default per-type labels.
PRIORITY_MAP = {
    "emergency": 10,
    "critical_sensor": 9,
    "real_time": 7,
    "video": 5,
    "file": 2,
    "background": 1,
}

# Default human-readable labels used when a caller doesn't supply one.
DEFAULT_LABELS = {
    "emergency": "Emergency Alert",
    "critical_sensor": "Critical Sensor",
    "real_time": "Live Monitoring Feed",
    "video": "Video Call",
    "file": "File Transfer",
    "background": "Background Update",
}

SUPPORTED_TRAFFIC_TYPES = list(PRIORITY_MAP.keys())
MAX_PRIORITY = max(PRIORITY_MAP.values())

# --- Context-aware priority engine -----------------------------------
#
# Semantic factors (each 0.0-1.0), extracted per traffic description
# by services/semantic_service.py (Gemini, or the deterministic
# fallback when Gemini is unavailable):
#   urgency                 how quickly must this be delivered
#   consequence             how bad is it if delayed or dropped
#   latency_sensitivity     does the application need near-real-time delivery
#   reliability_requirement how important is guaranteed successful delivery
#
# These combine into a final 0-10 priority via a transparent weighted
# sum. The weights below are a manually chosen STARTING POLICY, not a
# machine-learned result -- they are deliberately kept in config so
# they can be tuned after live testing without touching code.
#
# Reasoning for the ordering (urgency > consequence > latency_sensitivity
# > reliability_requirement):
#   - urgency is weighted highest: how soon something must move is the
#     most directly actionable signal for a network scheduler.
#   - consequence is weighted second: closely reinforces urgency (what
#     happens if it's late), but on its own is a slower-acting concern
#     (e.g. a consequential-but-not-urgent scheduled safety check).
#   - latency_sensitivity is weighted third: whether an application
#     needs near-real-time delivery matters, but real-time-ness alone
#     doesn't imply importance (a casual video call is latency-sensitive
#     but not high-stakes).
#   - reliability_requirement is weighted lowest: it's the factor most
#     correlated with the other three already (most urgent/consequential
#     traffic also happens to need reliable delivery), so weighting it
#     highest would effectively double-count the same underlying signal.
PRIORITY_WEIGHTS = {
    "urgency": 0.35,
    "consequence": 0.30,
    "latency_sensitivity": 0.20,
    "reliability_requirement": 0.15,
}

# Category safety bounds: (min, max) the final priority is clamped
# into after the weighted formula, regardless of what the semantic
# factors alone would produce. This is a *guardrail*, not the primary
# mechanism -- it exists so a single noisy/hallucinated factor can't
# push e.g. background traffic to a 10, or emergency traffic below a
# safe floor. Within these bounds, semantic context still fully
# determines where in the range a given item lands (e.g. a routine
# critical_sensor reading can legitimately sit near 1.5, while a
# dangerous one sits near 9.5 -- both are valid within (1.0, 10.0)).
CATEGORY_PRIORITY_BOUNDS = {
    "emergency": (7.5, 10.0),
    "critical_sensor": (1.0, 10.0),
    "real_time": (2.0, 8.5),
    "video": (1.0, 7.5),
    "file": (0.3, 6.0),
    "background": (0.0, 3.5),
}

# Below this classification confidence, the response is marked
# low_confidence=true and priority is dampened conservatively (see
# services/priority_service.py) rather than trusted at face value.
LOW_CONFIDENCE_THRESHOLD = 0.55

# Deterministic fallback factor estimates per category, used only when
# Gemini is unavailable (missing/invalid key, timeout, network error,
# malformed response). These are *typical* values for the category,
# not context-aware -- the fallback genuinely cannot distinguish
# "routine" from "dangerous" within a category the way Gemini's
# semantic analysis can. This is a known, documented limitation of
# fallback mode, and every fallback response is marked source="fallback"
# so it is never mistaken for a real semantic analysis.
FALLBACK_SEMANTIC_FACTORS = {
    "emergency": {"urgency": 0.95, "consequence": 0.95, "latency_sensitivity": 0.85, "reliability_requirement": 0.95},
    "critical_sensor": {"urgency": 0.65, "consequence": 0.70, "latency_sensitivity": 0.55, "reliability_requirement": 0.75},
    "real_time": {"urgency": 0.55, "consequence": 0.45, "latency_sensitivity": 0.80, "reliability_requirement": 0.55},
    "video": {"urgency": 0.35, "consequence": 0.30, "latency_sensitivity": 0.65, "reliability_requirement": 0.45},
    "file": {"urgency": 0.15, "consequence": 0.15, "latency_sensitivity": 0.10, "reliability_requirement": 0.35},
    "background": {"urgency": 0.05, "consequence": 0.05, "latency_sensitivity": 0.05, "reliability_requirement": 0.20},
}


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class Config:
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    HOST = os.environ.get("HOST", "0.0.0.0")

    # Comma-separated list of allowed frontend origins for CORS.
    ALLOWED_ORIGINS = _parse_origins(
        os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        )
    )

    # Reject request bodies larger than this (bytes). Protects the demo
    # server from accidental/malicious huge payloads without adding
    # real auth/security infrastructure.
    MAX_CONTENT_LENGTH_BYTES = int(
        os.environ.get("MAX_CONTENT_LENGTH_BYTES", str(64 * 1024))
    )

    # Gemini semantic analysis (services/gemini_service.py). Only used
    # when GEMINI_API_KEY is set; the app runs fully on the
    # deterministic fallback otherwise.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    # Hard cap on how long a single Gemini call may take before we give
    # up and use the fallback. Keeps a single slow/hanging API call from
    # ever stalling a request during a live demo.
    #
    # Must stay >= 10s: the Gemini API server itself rejects any shorter
    # manually-set deadline with "400 INVALID_ARGUMENT: Manually set
    # deadline Xs is too short. Minimum allowed deadline is 10s." A
    # lower default here would make every real Gemini call fail
    # outright, regardless of how valid the API key is.
    GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "12.0"))

    # Where active traffic / congestion / routing state is persisted to
    # disk (see services/state_service.py), so restarting Flask no
    # longer wipes it -- only an explicit reset does. Defaults to a
    # path next to this file so it resolves correctly regardless of
    # the process's current working directory.
    #
    # Uses `or` rather than os.environ.get(key, default): .env.example
    # ships this key present but blank (meaning "use the default"), and
    # os.environ.get's default only kicks in when the key is *absent* --
    # a present-but-empty value would otherwise resolve to "", the same
    # class of bug GEMINI_TIMEOUT_SECONDS hit earlier.
    STATE_FILE_PATH = os.environ.get("STATE_FILE_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "state.json"
    )

    # Directory POST /api/capture/analyze is allowed to read pcap files
    # from (services/capture_service.py). Requests may only reference
    # files inside this directory -- see routes/capture.py's path
    # resolution -- so a client can never read arbitrary files off disk
    # via a crafted pcap_path.
    CAPTURES_DIR = os.environ.get("CAPTURES_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "captures"
    )
    # Cap on how many distinct flows a single capture analysis returns
    # (ranked by packet count) -- keeps a huge pcap from turning one
    # request into thousands of Gemini calls / traffic entries.
    CAPTURE_MAX_FLOWS = int(os.environ.get("CAPTURE_MAX_FLOWS", "25"))
