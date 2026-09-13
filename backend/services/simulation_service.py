"""Simulation orchestration: turns current state into API-shaped results.

Keeps app.py/routes free of business logic -- routes just call these
functions and serialize the result.
"""
from typing import Any

from services import routing_service
from services.state_service import state

# (type, label) pairs for the standard demo scenario. Deliberately
# descriptive rather than generic ("Factory temperature exceeded fire
# safety threshold", not just "Critical Sensor") so the demo actually
# exercises context-aware semantic analysis instead of just re-deriving
# a flat per-type default.
DEMO_SCENARIOS: list[tuple[str, str]] = [
    ("emergency", "Active active-shooter alert triggered on campus building B"),
    ("emergency", "SOS heartbeat packet from offshore oil rig crew capsule"),
    ("emergency", "Airbag deployment confirmation and GPS coordinates from vehicle"),
    ("emergency", "Residential smart alarm reporting active carbon monoxide leak"),
    ("critical_sensor", "Main grid transformer oil temperature at 140C - melt risk"),
    ("critical_sensor", "Gas pipeline telemetry showing pressure drop in Sector 4"),
    ("critical_sensor", "Hydroelectric dam water level sensor exceeding spillway limit"),
    ("critical_sensor", "Server room rack B4 humidity alert - condensation danger"),
    ("real_time", "Drone telemetry stream requesting immediate landing vector"),
    ("real_time", "Lidar obstacle distance stream for warehouse forklift automation"),
    ("transactional", "API request: High-frequency stock trade execution order"),
    ("transactional", "Point-of-Sale credit card authorization token exchange"),
    ("video", "Remote surgical robot camera stream payload chunk 402"),
    ("video", "Corporate board meeting 4K video conference chunk"),
    ("voice_chat", "VoIP packet SIP signal for emergency dispatcher call"),
    ("voice_chat", "Customer support live chat websocket message text payload"),
    ("file", "Nightly database replication sync chunk for backup servers"),
    ("file", "Windows 11 monthly security patch update archive split_05"),
    ("file", "Text message saying: Emergency! I forgot to download the movie file"),
    ("critical_sensor", "Weather station report: Temperature is a beautiful 22 degrees")
]


def traffic_with_metrics() -> list[dict[str, Any]]:
    """Current active traffic, annotated with live metrics."""
    congestion = state.get_congestion()
    semantic = state.get_semantic_routing()
    items = []
    for t in state.get_traffic_list():
        metrics = routing_service.compute_metrics(t["priority"], congestion, semantic, t["type"])
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
            t["priority"], network["congestion"], network["semantic_routing_enabled"], t["type"]
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
    for traffic_type, label in DEMO_SCENARIOS:
        state.add_traffic(traffic_type, label)
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
        baseline_metrics = routing_service.compute_metrics(t["priority"], True, False, t["type"])
        semantic_metrics = routing_service.compute_metrics(t["priority"], True, True, t["type"])

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
