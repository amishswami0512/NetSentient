def test_root_returns_api_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"NetSentient" in resp.data
    assert resp.mimetype == "text/html"


def test_health_returns_200_and_expected_shape(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {
        "status": "ok",
        "service": "semantic-router-api",
        "version": "1.0.0",
    }


def test_unknown_route_returns_404_json(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"]["code"] == "NOT_FOUND"


def test_wrong_method_returns_405_json(client):
    resp = client.post("/api/health")
    assert resp.status_code == 405
    data = resp.get_json()
    assert data["error"]["code"] == "METHOD_NOT_ALLOWED"
