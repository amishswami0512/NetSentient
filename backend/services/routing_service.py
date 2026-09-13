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
from services.state_service import state
from services.network_measurement_service import get_network_measurement

# (priority, delivery_percent) anchor points used to interpolate delivery
# for congested traffic *with* semantic routing enabled. Priority 10
# (emergency) stays almost fully protected; priority 1 (background) is
# sacrificed almost entirely so higher-priority traffic gets through.
_SEMANTIC_CONGESTED_ANCHORS: list[tuple[int, float]] = [
    (1, 5.0),
    (2, 15.0),
    (5, 60.0),
    (9, 92.0),
    (10, 98.0),
]

_NO_CONGESTION_LOAD_PERCENT = 30
_CONGESTION_LOAD_PERCENT = 82


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
    priority: float, congestion: bool, semantic_routing_enabled: bool
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
        delivery = round(_interpolate_delivery(priority), 2)
        if priority >= 8:
            status = "protected"
        elif priority >= 4:
            status = "degraded"
        else:
            status = "throttled"
    else:
        # Baseline/fair allocation: congestion hurts everyone roughly
        # equally, regardless of priority.
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


def get_network_status() -> dict[str, Any]:
    congestion = state.get_congestion()
    measurement = get_network_measurement()
    return {
        "congestion": congestion,
        # Load remains a controlled simulation input; bandwidth/latency are
        # measured from the machine running Flask.
        "load_percent": _CONGESTION_LOAD_PERCENT
        if congestion
        else _NO_CONGESTION_LOAD_PERCENT,
        "bandwidth_mbps": measurement["bandwidth_mbps"],
        "latency_ms": measurement["latency_ms"],
        "measurement_ok": measurement["measurement_ok"],
        "measurement_source": measurement["measurement_source"],
        "semantic_routing_enabled": state.get_semantic_routing(),
        "active_connections": len(state.get_traffic_list()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
