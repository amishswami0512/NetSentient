import pytest

from config import Config


@pytest.fixture
def with_api_keys(monkeypatch):
    monkeypatch.setattr(Config, "API_KEYS", frozenset({"secret-key-123"}))


def test_health_never_requires_auth(client, with_api_keys):
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_protected_endpoint_rejects_missing_key(client, with_api_keys):
    resp = client.post("/api/classify", json={"input": "test"})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_protected_endpoint_rejects_wrong_key(client, with_api_keys):
    resp = client.post(
        "/api/classify", json={"input": "test"},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


def test_protected_endpoint_rejects_malformed_header(client, with_api_keys):
    resp = client.post(
        "/api/classify", json={"input": "test"},
        headers={"Authorization": "secret-key-123"},  # missing "Bearer " prefix
    )
    assert resp.status_code == 401


def test_protected_endpoint_accepts_correct_key(client, with_api_keys):
    resp = client.post(
        "/api/classify", json={"input": "test"},
        headers={"Authorization": "Bearer secret-key-123"},
    )
    assert resp.status_code == 200


def test_get_endpoint_also_requires_auth(client, with_api_keys):
    resp = client.get("/api/traffic")
    assert resp.status_code == 401


def test_no_api_keys_configured_means_no_auth_required(client):
    # Default test config: Config.API_KEYS is empty (see conftest.py --
    # no fixture here overrides it).
    resp = client.post("/api/classify", json={"input": "test"})
    assert resp.status_code == 200
