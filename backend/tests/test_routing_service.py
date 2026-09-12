from services.routing_service import allocate_bandwidth, compute_metrics


def test_video_throughput_is_between_point_seven_and_one_mbps_during_congestion():
    metrics = compute_metrics(priority=5, congestion=True, semantic_routing_enabled=True)
    congested_bandwidth_mbps = 2.0
    throughput_mbps = metrics["delivery_percent"] / 100 * congested_bandwidth_mbps

    assert 0.7 <= throughput_mbps <= 1.0


def test_non_qos_bandwidth_share_uses_requested_data_rates():
    traffic = [
        {"id": "small", "priority": 10, "requested_mbps": 1.0},
        {"id": "large", "priority": 1, "requested_mbps": 3.0},
    ]

    allocation = allocate_bandwidth(traffic, congestion=True, semantic_routing_enabled=False)

    assert allocation["small"] == 0.5
    assert allocation["large"] == 1.5
