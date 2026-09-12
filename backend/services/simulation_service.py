from time import time
from typing import Any

from services import routing_service
from services.classifier_service import classify_texts
from services.state_service import state

DEMO_TRAFFIC = [
    ("emergency", "Evacuate now due to chemical leak", 0.50),
    ("emergency", "Fire suppression system activation now", 0.45),
    ("emergency", "ICU code-blue escalation requires immediate response", 0.40),
    ("critical_sensor", "ICU oxygen saturation reading is abnormal", 0.35),
    ("critical_sensor", "Grid frequency sensor reading is outside normal range", 0.35),
    ("critical_sensor", "Water pressure sensor reports an anomaly", 0.35),
    ("video", "Standard team video call", 0.10),
    ("video", "Routine security camera video stream", 0.10),
    ("video", "Staff video conference", 0.10),
    ("video", "Remote inspection video feed", 0.10),
    ("video", "Operations briefing video stream", 0.10),
    ("video", "Training webinar video stream", 0.10),
    ("video", "Recorded media playback stream", 0.10),
    ("file", "Nightly database backup", 0.08),
    ("file", "Software patch download", 0.08),
    ("file", "Satellite imagery upload", 0.08),
    ("file", "Archive file synchronization", 0.08),
    ("file", "Email attachment upload", 0.08),
    ("file", "Document download", 0.08),
    ("background", "Routine heartbeat telemetry sync", 0.05),
    ("emergency", "Immediate shelter-in-place alert for toxic gas release", 0.45),
    ("critical_sensor", "Patient heart-rate monitor reports a sustained irregular rhythm", 0.30),
    ("critical_sensor", "Transformer temperature sensor exceeds its warning threshold", 0.30),
    ("video", "Weekly project status video call", 0.10),
    ("video", "Office lobby camera stream", 0.10),
    ("video", "Recorded training session playback", 0.10),
    ("video", "Customer support video meeting", 0.10),
    ("file", "Monthly accounting spreadsheet download", 0.08),
    ("file", "Routine photo archive upload", 0.08),
    ("file", "Build artifact download", 0.08),
    ("file", "Completed report document transfer", 0.08),
    ("background", "Routine application log rotation", 0.05),
    ("background", "Low-priority configuration synchronization", 0.05),
    ("background", "Periodic service heartbeat", 0.05),
    ("background", "Scheduled cache refresh", 0.05),
    ("background", "Routine inventory metadata sync", 0.05),
    ("video", "Public information livestream", 0.10),
    ("file", "Old records archive transfer", 0.08),
    ("video", "Remote presentation screen share", 0.10),
    ("file", "Routine export of analytics data", 0.08),
]


def traffic_with_metrics() -> list[dict[str, Any]]:
    congestion = state.get_congestion()
    semantic = state.get_semantic_routing()
    traffic = [
        {
            **item,
            "source_rate_mbps": item.get("requested_mbps")
            or routing_service.estimate_source_rate_mbps(item, time()),
        }
        for item in state.get_traffic_list()
    ]
    allocation = routing_service.allocate_bandwidth(traffic, congestion, semantic)
    items = []
    for t in traffic:
        metrics = routing_service.compute_metrics(t["priority"], congestion, semantic)
        throughput = allocation[t["id"]]
        delivery = round(min(100, throughput / t["source_rate_mbps"] * 100), 2)
        items.append({
            **t,
            **metrics,
            "throughput_mbps": throughput,
            "delivery_percent": delivery,
        })
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
    labels = [label for _traffic_type, label, _sample_rate in DEMO_TRAFFIC]
    classifications = classify_texts(labels)
    classified_demo = [
        (label, sample_rate, classification)
        for (_traffic_type, label, sample_rate), classification in zip(DEMO_TRAFFIC, classifications)
    ]

    state.reset()
    state.set_semantic_routing(True)
    state.set_congestion(False)
    for label, sample_rate, classification in classified_demo:
        state.add_traffic(
            classification["category"],
            label,
            criticality_score=classification["criticality_score"],
            classification={
                "confidence": classification["confidence"],
                "reasoning": classification["reasoning"],
                "provider": classification["provider"],
            },
            requested_mbps=sample_rate,
        )
    return traffic_with_metrics()


def compare_routing_modes() -> dict[str, Any]:
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
