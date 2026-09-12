def test_analyze_traffic_classifies_and_adds_payload_to_live_stream(client):
    response = client.post(
        "/api/traffic/analyze",
        json={"input": "ICU patient oxygen anomaly detected"},
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["payload"] == "ICU patient oxygen anomaly detected"
    assert data["category"] == "critical_sensor"
    assert 6 <= data["criticality_score"] <= 8
    assert data["priority"] == data["criticality_score"]
    assert data["id"]

    traffic = client.get("/api/traffic").get_json()["traffic"]
    assert any(item["id"] == data["id"] for item in traffic)


def test_analyze_traffic_requires_a_nonempty_payload(client):
    response = client.post("/api/traffic/analyze", json={"input": ""})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"
