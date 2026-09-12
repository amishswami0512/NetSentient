"""Persistent state manager for the hackathon prototype.

Holds all mutable demo state (active traffic, congestion flag, semantic
routing flag, ID counters) behind one object instead of scattering
module-level globals across the codebase.

State is written to Config.STATE_FILE_PATH after every mutation and
reloaded from it on startup, so restarting Flask no longer wipes active
traffic. Use POST /api/simulation/reset or POST /api/demo/reset (or
delete the state file) to get back to a clean slate.
"""
import json
import logging
from pathlib import Path
from typing import Any

from config import Config
from services import priority_service, semantic_service

logger = logging.getLogger(__name__)


class StateService:
    def __init__(self) -> None:
        self._traffic: dict[str, dict[str, Any]] = {}
        self._congestion: bool = False
        self._semantic_routing_enabled: bool = True
        self._traffic_seq: int = 0
        self._simulation_seq: int = 0
        self._load()

    def _save(self) -> None:
        """Best-effort persistence. A write failure (e.g. read-only
        filesystem) must never crash a request -- it just means this
        one mutation won't survive a restart.
        """
        try:
            path = Path(Config.STATE_FILE_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "traffic": self._traffic,
                "congestion": self._congestion,
                "semantic_routing_enabled": self._semantic_routing_enabled,
                "traffic_seq": self._traffic_seq,
                "simulation_seq": self._simulation_seq,
            }))
        except OSError:
            logger.exception("Could not persist state to %s", Config.STATE_FILE_PATH)

    def _load(self) -> None:
        """Best-effort restore. A missing or corrupt state file must
        never crash startup -- it just means starting from empty state,
        same as before persistence existed.
        """
        path = Path(Config.STATE_FILE_PATH)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._traffic = data["traffic"]
            self._congestion = data["congestion"]
            self._semantic_routing_enabled = data["semantic_routing_enabled"]
            self._traffic_seq = data["traffic_seq"]
            self._simulation_seq = data["simulation_seq"]
        except (OSError, json.JSONDecodeError, KeyError):
            logger.exception(
                "Could not load persisted state from %s -- starting empty",
                Config.STATE_FILE_PATH,
            )

    def reset(self) -> None:
        self._traffic = {}
        self._congestion = False
        self._semantic_routing_enabled = True
        self._traffic_seq = 0
        self._simulation_seq = 0
        self._save()

    # -- traffic -----------------------------------------------------
    def add_traffic(self, traffic_type: str, label: str) -> dict[str, Any]:
        """Create a traffic item, with priority computed from the label's
        actual semantic content (not just a flat per-type lookup).

        `traffic_type` (client-declared, already validated against
        SUPPORTED_TRAFFIC_TYPES) is used as the category for priority
        safety-bounds purposes; the label text is what's semantically
        analyzed (via Gemini, or the deterministic fallback) to get the
        urgency/consequence/latency/reliability factors that actually
        differentiate priority within that category.
        """
        self._traffic_seq += 1
        traffic_id = f"traffic-{self._traffic_seq:03d}"

        analysis = semantic_service.analyze_for_category(label, traffic_type)
        scored = priority_service.score(traffic_type, analysis["confidence"], analysis["factors"])

        entry = {
            "id": traffic_id,
            "type": traffic_type,
            "label": label,
            "priority": scored["priority"],
            "priority_factors": analysis["factors"],
            "low_confidence": scored["low_confidence"],
            "source": analysis["source"],
        }
        self._traffic[traffic_id] = entry
        self._save()
        return entry

    def get_traffic_list(self) -> list[dict[str, Any]]:
        return list(self._traffic.values())

    def clear_traffic(self) -> None:
        self._traffic = {}
        self._save()

    # -- congestion ----------------------------------------------------
    def set_congestion(self, enabled: bool) -> None:
        self._congestion = enabled
        self._save()

    def get_congestion(self) -> bool:
        return self._congestion

    # -- semantic routing ----------------------------------------------
    def set_semantic_routing(self, enabled: bool) -> None:
        self._semantic_routing_enabled = enabled
        self._save()

    def get_semantic_routing(self) -> bool:
        return self._semantic_routing_enabled

    # -- simulation ------------------------------------------------------
    def next_simulation_id(self) -> str:
        self._simulation_seq += 1
        self._save()
        return f"sim-{self._simulation_seq:03d}"


# Single shared instance used across routes/services for this process.
state = StateService()
