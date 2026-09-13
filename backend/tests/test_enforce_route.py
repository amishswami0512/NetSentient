from unittest.mock import patch

import pytest

from config import Config


@pytest.fixture(autouse=True)
def _dry_run_only(monkeypatch):
    monkeypatch.setattr(Config, "ENFORCEMENT_ENABLED", False)
    monkeypatch.setattr(Config, "ENFORCEMENT_INTERFACE", "lo")


def test_apply_enforcement_dry_run(client):
    with patch("services.enforcement_service.subprocess.run") as mock_run:
        resp = client.post("/api/enforce/apply", json={"protocol": "tcp", "port": 443, "priority": 8.0})
    mock_run.assert_not_called()
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["dry_run"] is True
    assert data["tier"] == "critical"
    assert isinstance(data["commands"], list) and len(data["commands"]) > 0


def test_apply_enforcement_with_dst_cidr(client):
    resp = client.post(
        "/api/enforce/apply",
        json={"protocol": "udp", "port": 5004, "priority": 3.0, "dst_cidr": "10.1.2.0/24"},
    )
    assert resp.status_code == 200
    assert any("10.1.2.0/24" in c for c in resp.get_json()["commands"])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"protocol": "tcp", "port": 443},
        {"protocol": "icmp", "port": 443, "priority": 5.0},
        {"protocol": "tcp", "port": 70000, "priority": 5.0},
        {"protocol": "tcp", "port": 443, "priority": 11.0},
        {"protocol": "tcp", "port": 443, "priority": 5.0, "dst_cidr": "not-a-cidr"},
    ],
)
def test_apply_enforcement_rejects_invalid_input(client, payload):
    resp = client.post("/api/enforce/apply", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_enforcement_status(client):
    resp = client.get("/api/enforce/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is False
    assert data["interface"] == "lo"
    assert len(data["tiers"]) == 4


def test_reset_enforcement_dry_run(client):
    with patch("services.enforcement_service.subprocess.run") as mock_run:
        resp = client.post("/api/enforce/reset")
    mock_run.assert_not_called()
    assert resp.status_code == 200
    assert resp.get_json()["dry_run"] is True
