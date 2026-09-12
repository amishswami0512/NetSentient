"""In-memory state manager for the hackathon prototype.

Holds all mutable demo state (active traffic, congestion flag, semantic
routing flag, ID counters) behind one object instead of scattering
module-level globals across the codebase.

NOTE: State is process-local and volatile -- restarting Flask wipes it.
Use POST /api/simulation/reset or POST /api/demo/reset to get back to a
clean slate without restarting the server.
"""
from typing import Any

from config import PRIORITY_MAP


class StateService:
    def __init__(self) -> None:
        self._traffic: dict[str, dict[str, Any]] = {}
        self._congestion: bool = False
        self._semantic_routing_enabled: bool = True
        self._traffic_seq: int = 0
        self._simulation_seq: int = 0

    def reset(self) -> None:
        self._traffic = {}
        self._congestion = False
        self._semantic_routing_enabled = True
        self._traffic_seq = 0
        self._simulation_seq = 0

    # -- traffic -----------------------------------------------------
    def add_traffic(self, traffic_type: str, label: str) -> dict[str, Any]:
        self._traffic_seq += 1
        traffic_id = f"traffic-{self._traffic_seq:03d}"
        entry = {
            "id": traffic_id,
            "type": traffic_type,
            "label": label,
            "priority": PRIORITY_MAP[traffic_type],
        }
        self._traffic[traffic_id] = entry
        return entry

    def get_traffic_list(self) -> list[dict[str, Any]]:
        return list(self._traffic.values())

    def clear_traffic(self) -> None:
        self._traffic = {}

    # -- congestion ----------------------------------------------------
    def set_congestion(self, enabled: bool) -> None:
        self._congestion = enabled

    def get_congestion(self) -> bool:
        return self._congestion

    # -- semantic routing ----------------------------------------------
    def set_semantic_routing(self, enabled: bool) -> None:
        self._semantic_routing_enabled = enabled

    def get_semantic_routing(self) -> bool:
        return self._semantic_routing_enabled

    # -- simulation ------------------------------------------------------
    def next_simulation_id(self) -> str:
        self._simulation_seq += 1
        return f"sim-{self._simulation_seq:03d}"


# Single shared instance used across routes/services for this process.
state = StateService()
