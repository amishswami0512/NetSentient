"""Simulation orchestration: turns current state into API-shaped results.

Keeps app.py/routes free of business logic -- routes just call these
functions and serialize the result.
"""
from typing import Any

from config import DEFAULT_LABELS
from services import routing_service
from services.state_service import state

DEMO_TRAFFIC_TYPES = ["emergency", "critical_sensor", "video", "file"]


def traffic_with_metrics() -> list[dict[str, Any]]:
    """Current active traffic, annotated with live metrics."""
    congestion = state.get_congestion()
    semantic = state.get_semantic_routing()
    items = []
    for t in state.get_traffic_list():
        metrics = routing_service.compute_metrics(t["priority"], congestion, semantic)
        items.append({**t, **metrics})
    return items


def run_simulation() -> dict[str, Any]:
    network = {
        "congestion": state.get_congestion(),
        "semantic_routing_enabled": state.get_semantic_routing(),
    }
    results = []
    for t in state.get_traffic_list():
        metrics = routing_service.compute_metrics(
            t["priority"], network["congestion"], network["semantic_routing_enabled"]
        )
        results.append(
            {
                "traffic_id": t["id"],
                "priority": t["priority"],
                **metrics,
            }
        )
    return {
        "simulation_id": state.next_simulation_id(),
        "network": network,
        "results": results,
    }


def seed_demo_traffic() -> list[dict[str, Any]]:
    """Reset state and create the standard demo traffic set."""
    state.reset()
    state.set_semantic_routing(True)
    state.set_congestion(False)
    for traffic_type in DEMO_TRAFFIC_TYPES:
        state.add_traffic(traffic_type, DEFAULT_LABELS[traffic_type])
    return traffic_with_metrics()


def compare_routing_modes() -> dict[str, Any]:
    """Side-by-side baseline vs. semantic routing under congestion.

    Read-only: does not mutate the actual congestion/semantic-routing
    state, so it can be called at any time during a demo.
    """
    traffic = state.get_traffic_list()

    baseline = []
    semantic = []
    improvement = []
    for t in traffic:
        baseline_metrics = routing_service.compute_metrics(t["priority"], True, False)
        semantic_metrics = routing_service.compute_metrics(t["priority"], True, True)

        baseline.append({"traffic_id": t["id"], "type": t["type"], "priority": t["priority"], **baseline_metrics})
        semantic.append({"traffic_id": t["id"], "type": t["type"], "priority": t["priority"], **semantic_metrics})
        improvement.append(
            {
                "traffic_id": t["id"],
                "type": t["type"],
                "priority": t["priority"],
                "delivery_improvement_percent": round(
                    semantic_metrics["delivery_percent"] - baseline_metrics["delivery_percent"], 2
                ),
            }
        )

    return {"baseline": baseline, "semantic": semantic, "improvement": improvement}
