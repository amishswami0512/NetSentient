def test_enable_congestion(client):
    resp = client.post("/api/simulation/congestion", json={"enabled": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["congestion"] is True
    assert data["bandwidth_mbps"] < 10


def test_disable_congestion(client):
    client.post("/api/simulation/congestion", json={"enabled": True})
    resp = client.post("/api/simulation/congestion", json={"enabled": False})
    data = resp.get_json()
    assert data["congestion"] is False


def test_congestion_invalid_boolean(client):
    resp = client.post("/api/simulation/congestion", json={"enabled": "yes"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_congestion_missing_field(client):
    resp = client.post("/api/simulation/congestion", json={})
    assert resp.status_code == 400


def test_enable_semantic_routing(client):
    resp = client.post("/api/simulation/semantic-routing", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"semantic_routing_enabled": True}


def test_disable_semantic_routing(client):
    resp = client.post("/api/simulation/semantic-routing", json={"enabled": False})
    assert resp.get_json() == {"semantic_routing_enabled": False}


def test_semantic_routing_invalid_boolean(client):
    resp = client.post("/api/simulation/semantic-routing", json={"enabled": 1})
    assert resp.status_code == 400


def test_run_simulation_shape(client):
    client.post("/api/traffic", json={"type": "emergency"})
    resp = client.post("/api/simulation/run")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "simulation_id" in data
    assert "network" in data
    assert len(data["results"]) == 1
    result = data["results"][0]
    for field in ("traffic_id", "priority", "latency_ms", "packet_loss_percent", "delivery_percent"):
        assert field in result


def test_semantic_routing_changes_simulation_behavior_under_congestion(client):
    client.post("/api/traffic", json={"type": "emergency"})
    client.post("/api/traffic", json={"type": "file"})
    client.post("/api/simulation/congestion", json={"enabled": True})

    client.post("/api/simulation/semantic-routing", json={"enabled": True})
    with_semantic = client.post("/api/simulation/run").get_json()["results"]

    client.post("/api/simulation/semantic-routing", json={"enabled": False})
    without_semantic = client.post("/api/simulation/run").get_json()["results"]

    assert with_semantic != without_semantic

    emergency_with = next(r for r in with_semantic if r["priority"] == 10)
    file_with = next(r for r in with_semantic if r["priority"] == 2)
    # With semantic routing on, high priority must clearly outperform low priority.
    assert emergency_with["delivery_percent"] > file_with["delivery_percent"]

    emergency_without = next(r for r in without_semantic if r["priority"] == 10)
    file_without = next(r for r in without_semantic if r["priority"] == 2)
    # Without semantic routing, congestion hits both roughly equally,
    # so the gap should be far smaller than with routing enabled.
    gap_with = emergency_with["delivery_percent"] - file_with["delivery_percent"]
    gap_without = emergency_without["delivery_percent"] - file_without["delivery_percent"]
    assert gap_with > gap_without


def test_simulation_reset_clears_state(client):
    client.post("/api/traffic", json={"type": "emergency"})
    client.post("/api/simulation/congestion", json={"enabled": True})
    client.post("/api/simulation/semantic-routing", json={"enabled": False})

    resp = client.post("/api/simulation/reset")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["traffic"] == []
    assert data["network"]["congestion"] is False
    assert data["network"]["semantic_routing_enabled"] is True

    traffic_resp = client.get("/api/traffic")
    assert traffic_resp.get_json() == {"traffic": []}
