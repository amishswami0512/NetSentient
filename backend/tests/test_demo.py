def test_demo_reset_creates_predefined_traffic(client):
    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200
    data = resp.get_json()
    types = {t["type"] for t in data["traffic"]}
    assert types == {"emergency", "critical_sensor", "video", "file", "background"}
    assert len(data["traffic"]) == 40
    assert data["network"]["semantic_routing_enabled"] is True
    assert data["network"]["congestion"] is False


def test_demo_congest_enables_congestion_and_runs_simulation(client):
    client.post("/api/demo/reset")
    resp = client.post("/api/demo/congest")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["network"]["congestion"] is True
    assert len(data["results"]) == 40


def test_demo_compare_shows_semantic_routing_benefit_for_emergency(client):
    client.post("/api/demo/reset")
    resp = client.post("/api/demo/compare")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "baseline" in data and "semantic" in data and "improvement" in data
    assert len(data["baseline"]) == 40
    assert len(data["semantic"]) == 40
    assert len(data["improvement"]) == 40

    emergency_baseline = next(t for t in data["baseline"] if t["type"] == "emergency")
    emergency_semantic = next(t for t in data["semantic"] if t["type"] == "emergency")
    assert emergency_semantic["delivery_percent"] > emergency_baseline["delivery_percent"]

    emergency_improvement = next(t for t in data["improvement"] if t["type"] == "emergency")
    assert emergency_improvement["delivery_improvement_percent"] > 0


def test_demo_compare_is_read_only(client):
    client.post("/api/demo/reset")
    client.post("/api/demo/compare")
    status = client.get("/api/network/status").get_json()
    # compare should not have mutated the real congestion/routing state
    assert status["congestion"] is False
    assert status["semantic_routing_enabled"] is True
