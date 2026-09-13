from services.simulation_service import DEMO_SCENARIOS

# Derived from the real scenario list rather than hardcoded, so this
# test doesn't go stale again the next time someone adds/removes a
# demo scenario -- that's exactly what broke this file before (it
# assumed 5 scenarios/{emergency, critical_sensor, real_time, video,
# file} when the real list had grown to 20 scenarios across 7 types,
# including two categories -- transactional, voice_chat -- that were
# also missing from config.py entirely until now).
_EXPECTED_TYPES = {traffic_type for traffic_type, _ in DEMO_SCENARIOS}
_EXPECTED_COUNT = len(DEMO_SCENARIOS)


def test_demo_reset_creates_predefined_traffic(client):
    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["traffic"]) == _EXPECTED_COUNT
    types = {t["type"] for t in data["traffic"]}
    assert types == _EXPECTED_TYPES
    assert data["network"]["semantic_routing_enabled"] is True
    assert data["network"]["congestion"] is False


def test_demo_congest_enables_congestion_and_runs_simulation(client):
    client.post("/api/demo/reset")
    resp = client.post("/api/demo/congest")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["network"]["congestion"] is True
    assert len(data["results"]) == _EXPECTED_COUNT


def test_demo_compare_shows_semantic_routing_benefit_for_emergency(client):
    client.post("/api/demo/reset")
    resp = client.post("/api/demo/compare")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "baseline" in data and "semantic" in data and "improvement" in data
    assert len(data["baseline"]) == _EXPECTED_COUNT
    assert len(data["semantic"]) == _EXPECTED_COUNT
    assert len(data["improvement"]) == _EXPECTED_COUNT

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


def test_demo_scenarios_produce_meaningfully_different_priorities(client):
    # The demo's descriptive scenario labels should drive genuinely
    # different priorities across categories, not just a flat per-type
    # value. Multiple scenarios can share a category now (e.g. 4
    # distinct "emergency" entries), so this compares one representative
    # priority per category rather than every individual scenario --
    # in fallback mode (no GEMINI_API_KEY, as in tests), every scenario
    # within the same category legitimately gets the same fallback
    # factors, which is a documented limitation, not a bug to test around.
    resp = client.post("/api/demo/reset")
    traffic = {t["type"]: t["priority"] for t in resp.get_json()["traffic"]}

    assert traffic["emergency"] > traffic["critical_sensor"] > traffic["file"]
    assert traffic["critical_sensor"] > traffic["video"]
    # priorities must not all collapse onto the same fixed constant
    assert len(set(traffic.values())) == len(traffic)
