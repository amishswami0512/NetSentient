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

    def add_traffic(
        self,
        traffic_type: str,
        label: str,
        criticality_score: float | None = None,
        classification: dict[str, Any] | None = None,
        requested_mbps: float | None = None,
    ) -> dict[str, Any]:
        self._traffic_seq += 1
        traffic_id = f"traffic-{self._traffic_seq:03d}"
        score = criticality_score if criticality_score is not None else PRIORITY_MAP[traffic_type]
        entry = {
            "id": traffic_id,
            "type": traffic_type,
            "label": label,
            "priority": score,
            "criticality_score": score,
            "payload_bytes": len(label.encode("utf-8")),
        }
        if requested_mbps is not None:
            entry["requested_mbps"] = requested_mbps
        if classification:
            entry.update(classification)
        self._traffic[traffic_id] = entry
        return entry

    def get_traffic_list(self) -> list[dict[str, Any]]:
        return list(self._traffic.values())

    def clear_traffic(self) -> None:
        self._traffic = {}

    def set_congestion(self, enabled: bool) -> None:
        self._congestion = enabled

    def get_congestion(self) -> bool:
        return self._congestion

    def set_semantic_routing(self, enabled: bool) -> None:
        self._semantic_routing_enabled = enabled

    def get_semantic_routing(self) -> bool:
        return self._semantic_routing_enabled

    def next_simulation_id(self) -> str:
        self._simulation_seq += 1
        return f"sim-{self._simulation_seq:03d}"


state = StateService()
