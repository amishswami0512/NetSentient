from unittest.mock import patch

import pytest


def test_network_status_shape(client):
    resp = client.get("/api/network/status")
    assert resp.status_code == 200
    data = resp.get_json()
    for field in (
        "congestion",
        "load_percent",
        "bandwidth_mbps",
        "latency_ms",
        "measurement_ok",
        "measurement_source",
        "semantic_routing_enabled",
        "active_connections",
        "timestamp",
    ):
        assert field in data
    assert data["measurement_source"] in ("measured", "fallback")


def test_get_traffic_empty_initially(client):
    resp = client.get("/api/traffic")
    assert resp.status_code == 200
    assert resp.get_json() == {"traffic": []}


def test_create_traffic_valid(client):
    resp = client.post("/api/traffic", json={"type": "emergency", "label": "Ambulance alert"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["type"] == "emergency"
    assert data["label"] == "Ambulance alert"
    assert 7.5 <= data["priority"] <= 10.0  # emergency's safety bound range
    assert data["id"].startswith("traffic-")
    assert "delivery_percent" in data
    assert "latency_ms" in data
    assert "packet_loss_percent" in data
    assert "priority_factors" in data
    assert "low_confidence" in data
    assert "source" in data


def test_create_traffic_generates_server_side_id_and_ignores_client_id(client):
    resp = client.post("/api/traffic", json={"id": "client-supplied", "type": "video", "label": "Call"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["id"] != "client-supplied"


def test_create_traffic_default_label_when_omitted(client):
    resp = client.post("/api/traffic", json={"type": "file"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["label"] == "File Transfer"


def test_create_traffic_shows_up_in_get(client):
    client.post("/api/traffic", json={"type": "background"})
    resp = client.get("/api/traffic")
    data = resp.get_json()
    assert len(data["traffic"]) == 1
    assert data["traffic"][0]["type"] == "background"


@pytest.mark.parametrize(
    "payload,expected_status",
    [
        ({"type": "not_a_real_type"}, 400),
        ({}, 400),
        ({"label": "no type given"}, 400),
        ({"type": 123}, 400),
    ],
)
def test_create_traffic_invalid_input(client, payload, expected_status):
    resp = client.post("/api/traffic", json=payload)
    assert resp.status_code == expected_status
    data = resp.get_json()
    assert data["error"]["code"] == "INVALID_REQUEST"


def test_create_traffic_missing_body_returns_400(client):
    resp = client.post("/api/traffic", data="", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "INVALID_REQUEST"


def test_create_traffic_malformed_json_returns_400(client):
    resp = client.post("/api/traffic", data="{not valid json", content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "INVALID_REQUEST"


def test_emergency_traffic_has_higher_priority_than_file_and_background(client):
    emergency = client.post("/api/traffic", json={"type": "emergency"}).get_json()
    file_ = client.post("/api/traffic", json={"type": "file"}).get_json()
    background = client.post("/api/traffic", json={"type": "background"}).get_json()

    assert emergency["priority"] > file_["priority"]
    assert emergency["priority"] > background["priority"]


def test_scan_traffic_classifies_via_real_pipeline_not_port_guess(client):
    # A youtube.com connection on port 443 -- previously this would
    # have been categorized purely by port number (443 -> "video"
    # unconditionally). Now it goes through the same semantic
    # pipeline as everything else, so the RuleBasedClassifier's
    # "youtube" keyword (added specifically for this) is what actually
    # drives the category, not the port.
    fake_connections = [
        {"label": "chrome connection to youtube.com on port 443", "hostname": "youtube.com", "port": "443"},
    ]
    with patch("services.network_scan_service.scan_active_connections", return_value=fake_connections):
        resp = client.post("/api/traffic/scan")

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["count"] == 1
    assert "scanned_at" in data
    assert len(data["traffic"]) == 1
    entry = data["traffic"][0]
    assert entry["type"] == "video"
    assert entry["label"] == "chrome connection to youtube.com on port 443"
    assert "priority" in entry and "delivery_percent" in entry


def test_scan_traffic_with_no_connections_returns_empty_list(client):
    with patch("services.network_scan_service.scan_active_connections", return_value=[]):
        resp = client.post("/api/traffic/scan")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["traffic"] == []
    assert data["count"] == 0
    assert "scanned_at" in data
