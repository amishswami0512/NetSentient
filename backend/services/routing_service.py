"""Priority-aware network metrics.

This is where the "semantic routing" behavior actually lives: given a
traffic item's priority and the current network state (congestion,
semantic routing on/off), compute deterministic latency/loss/delivery
numbers. No randomness -- every call with the same inputs returns the
same output, which keeps a live demo reproducible.
"""
from datetime import datetime, timezone
from typing import Any

from config import MAX_PRIORITY
from services import network_probe
from services.state_service import state

_TIER_1_DELIVERY_PERCENT = 98.0
_TIER_2_DELIVERY_PERCENT = round(_TIER_1_DELIVERY_PERCENT * 0.8, 2)
_TIER_3_DELIVERY_PERCENT = round(_TIER_1_DELIVERY_PERCENT * 0.2, 2)
_TIER_4_DELIVERY_PERCENT = round(_TIER_1_DELIVERY_PERCENT * 0.1, 2)

_SEMANTIC_CONGESTED_ANCHORS: list[tuple[int, float]] = [
    (1, 2.0),
    (2, 5.0),
    (5, _TIER_4_DELIVERY_PERCENT),
    (7, _TIER_3_DELIVERY_PERCENT),
    (9, _TIER_2_DELIVERY_PERCENT),
    (10, _TIER_1_DELIVERY_PERCENT),
]

_CONGESTION_BANDWIDTH_FRACTION = 0.2
_CONGESTION_BANDWIDTH_CAP_MBPS = 2.0

_TRAFFIC_TYPE_DEMAND_MBPS = {
    "emergency": 0.05,
    "critical_sensor": 0.1,
    "real_time": 0.5,
    "video": 2.5,
    "file": 4.0,
    "background": 0.5,
}
_PROTECTED_EMERGENCY_PRIORITY = 10.0
_PROTECTED_SENSOR_PRIORITY = 9.0


def _interpolate_delivery(priority: float) -> float:
    anchors = _SEMANTIC_CONGESTED_ANCHORS
    if priority <= anchors[0][0]:
        return anchors[0][1]
    if priority >= anchors[-1][0]:
        return anchors[-1][1]
    for (p_low, d_low), (p_high, d_high) in zip(anchors, anchors[1:]):
        if p_low <= priority <= p_high:
            ratio = (priority - p_low) / (p_high - p_low)
            return d_low + (d_high - d_low) * ratio
    return anchors[-1][1]  # unreachable, satisfies type-checkers


def compute_metrics(
    priority: float,
    congestion: bool,
    semantic_routing_enabled: bool,
    traffic_type: str | None = None,
) -> dict[str, Any]:
    """Compute latency/loss/delivery/status for one traffic item.

    `priority` is continuous (0-10), not limited to a fixed set of
    values -- the anchor-based interpolation and linear formulas below
    already work for any priority in range, so no changes were needed
    here to support the context-aware priority engine.
    """
    if not congestion:
        delivery = round(99.5 - (MAX_PRIORITY - priority) * 0.3, 2)
        status = "normal"
    elif semantic_routing_enabled:
        if traffic_type == "emergency":
            routing_priority = max(priority, _PROTECTED_EMERGENCY_PRIORITY)
        elif traffic_type == "critical_sensor":
            routing_priority = max(priority, _PROTECTED_SENSOR_PRIORITY)
        else:
            routing_priority = priority
        delivery = round(_interpolate_delivery(routing_priority), 2)
        if routing_priority >= 8:
            status = "protected"
        elif routing_priority >= 4:
            status = "degraded"
        else:
            status = "throttled"
    else:
        # Baseline/fair allocation: congestion hurts everyone roughly
        # equally, regardless of priority.
        delivery = round(60.0 + (priority - 5.5) * 1.0, 2)
        status = "fair"

    packet_loss = round(max(0.1, (100 - delivery) * 0.2), 2)
    latency = round(15 + (100 - delivery) * 3.5)

    return {
        "latency_ms": latency,
        "packet_loss_percent": packet_loss,
        "delivery_percent": delivery,
        "status": status,
    }


def get_network_status() -> dict[str, Any]:
    congestion = state.get_congestion()
    bandwidth_mbps, _ = network_probe.get_measured_bandwidth()
    if congestion:
        bandwidth_mbps = round(
            min(bandwidth_mbps * _CONGESTION_BANDWIDTH_FRACTION, _CONGESTION_BANDWIDTH_CAP_MBPS), 2
        )
    background_throughput_mbps = network_probe.get_current_throughput_mbps()
    traffic_demand_mbps = sum(
        _TRAFFIC_TYPE_DEMAND_MBPS.get(t["type"], 0.0) for t in state.get_traffic_list()
    )
    total_throughput_mbps = background_throughput_mbps + traffic_demand_mbps
    load_percent = (
        min(100, round((total_throughput_mbps / bandwidth_mbps) * 100)) if bandwidth_mbps else 0
    )
    return {
        "congestion": congestion,
        "load_percent": load_percent,
        "bandwidth_mbps": bandwidth_mbps,
        "semantic_routing_enabled": state.get_semantic_routing(),
        "active_connections": len(state.get_traffic_list()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }