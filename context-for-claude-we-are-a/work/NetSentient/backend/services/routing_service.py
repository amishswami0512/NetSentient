from datetime import datetime, timezone
from hashlib import sha256
from math import pi, sin
from typing import Any

from config import MAX_PRIORITY
from services.state_service import state

_SEMANTIC_CONGESTED_ANCHORS: list[tuple[int, float]] = [
    (1, 5.0),
    (2, 15.0),
    # Tier 3 is deliberately capped at ~0.9 Mbps on the 2 Mbps congested link.
    (5, 45.0),
    (9, 92.0),
    (10, 98.0),
]

_NO_CONGESTION_LOAD_PERCENT = 30
_CONGESTION_LOAD_PERCENT = 82
_NO_CONGESTION_BANDWIDTH_MBPS = 10.0
_CONGESTION_BANDWIDTH_MBPS = 2.0


def _interpolate_delivery(priority: int) -> float:
    anchors = _SEMANTIC_CONGESTED_ANCHORS
    if priority <= anchors[0][0]:
        return anchors[0][1]
    if priority >= anchors[-1][0]:
        return anchors[-1][1]
    for (p_low, d_low), (p_high, d_high) in zip(anchors, anchors[1:]):
        if p_low <= priority <= p_high:
            ratio = (priority - p_low) / (p_high - p_low)
            return d_low + (d_high - d_low) * ratio
    return anchors[-1][1]


def compute_metrics(
    priority: int, congestion: bool, semantic_routing_enabled: bool
) -> dict[str, Any]:
    if not congestion:
        delivery = round(99.5 - (MAX_PRIORITY - priority) * 0.3, 2)
        status = "normal"
    elif semantic_routing_enabled:
        delivery = round(_interpolate_delivery(priority), 2)
        if priority >= 8:
            status = "protected"
        elif priority >= 4:
            status = "degraded"
        else:
            status = "throttled"
    else:
        delivery = round(60.0 + (priority - 5.5) * 1.0, 2)
        status = "fair"

    packet_loss = round(max(0.1, (100 - delivery) * 0.6), 2)
    latency = round(15 + (100 - delivery) * 3.5)

    return {
        "latency_ms": latency,
        "packet_loss_percent": packet_loss,
        "delivery_percent": delivery,
        "status": status,
    }


def allocate_bandwidth(
    traffic: list[dict[str, Any]], congestion: bool, semantic_routing_enabled: bool
) -> dict[str, float]:
    """Allocate link capacity using each flow's requested rate and QoS weight."""
    capacity = _CONGESTION_BANDWIDTH_MBPS if congestion else _NO_CONGESTION_BANDWIDTH_MBPS
    remaining = {
        item["id"]: float(item.get("source_rate_mbps", item.get("requested_mbps", 0)))
        for item in traffic
    }
    allocation = {traffic_id: 0.0 for traffic_id in remaining}
    available = capacity

    while remaining and available > 0:
        weights = {
            # Demand always affects a flow's share. QoS adds priority as a
            # multiplier rather than replacing the actual requested rate.
            item["id"]: float(item.get("source_rate_mbps", item.get("requested_mbps", 0))) * (
                item["priority"] if semantic_routing_enabled else 1
            )
            for item in traffic
            if item["id"] in remaining
        }
        total_weight = sum(weights.values())
        satisfied = []
        for traffic_id, demand in remaining.items():
            share = available * weights[traffic_id] / total_weight
            if demand <= share:
                allocation[traffic_id] += demand
                available -= demand
                satisfied.append(traffic_id)
        if not satisfied:
            for traffic_id, demand in remaining.items():
                allocation[traffic_id] += available * weights[traffic_id] / total_weight
            break
        for traffic_id in satisfied:
            del remaining[traffic_id]

    return {traffic_id: round(rate, 3) for traffic_id, rate in allocation.items()}


def estimate_source_rate_mbps(traffic: dict[str, Any], timestamp: float) -> float:
    """Estimate the live source rate from payload size and packet arrival activity."""
    digest = sha256(traffic["id"].encode()).digest()
    phase = digest[0] / 255 * 2 * pi
    packets_per_second = 1_500 + digest[1] * 12
    activity = 0.35 + 0.65 * ((sin(timestamp * 0.8 + phase) + 1) / 2)
    return round(max(0.01, traffic["payload_bytes"] * 8 * packets_per_second * activity / 1_000_000), 3)


def get_network_status() -> dict[str, Any]:
    congestion = state.get_congestion()
    return {
        "congestion": congestion,
        "load_percent": _CONGESTION_LOAD_PERCENT
        if congestion
        else _NO_CONGESTION_LOAD_PERCENT,
        "bandwidth_mbps": _CONGESTION_BANDWIDTH_MBPS
        if congestion
        else _NO_CONGESTION_BANDWIDTH_MBPS,
        "semantic_routing_enabled": state.get_semantic_routing(),
        "active_connections": len(state.get_traffic_list()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
