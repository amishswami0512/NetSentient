import pytest


def test_classify_critical_sensor_input(client):
    resp = client.post("/api/classify", json={"input": "Critical heart rate anomaly detected"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["category"] == "critical_sensor"
    assert data["priority"] == 9
    assert 0.0 < data["confidence"] <= 1.0


def test_classify_emergency_input(client):
    resp = client.post("/api/classify", json={"input": "Ambulance emergency alert dispatched"})
    data = resp.get_json()
    assert data["category"] == "emergency"
    assert data["priority"] == 10


def test_classify_is_deterministic(client):
    payload = {"input": "large file upload in progress"}
    first = client.post("/api/classify", json=payload).get_json()
    second = client.post("/api/classify", json=payload).get_json()
    assert first == second


def test_classify_unknown_text_falls_back_to_background(client):
    resp = client.post("/api/classify", json={"input": "xyzzy plugh qux"})
    data = resp.get_json()
    assert data["category"] == "background"


@pytest.mark.parametrize(
    "payload",
    [{}, {"input": ""}, {"input": 123}, {"other_field": "no input key"}],
)
def test_classify_invalid_input(client, payload):
    resp = client.post("/api/classify", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_classify_missing_body_returns_400(client):
    resp = client.post("/api/classify")
    assert resp.status_code == 400
