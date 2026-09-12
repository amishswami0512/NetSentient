"""Explicit tests for fallback behavior: the app must work with no
Gemini configured at all, and must never crash Flask when Gemini fails.
"""
import services.semantic_service as semantic_service
from app import create_app


def test_app_starts_successfully_with_no_gemini_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    semantic_service.reset_client_resolution()
    try:
        app = create_app()
        with app.test_client() as test_client:
            resp = test_client.get("/api/health")
            assert resp.status_code == 200
    finally:
        semantic_service.reset_client_resolution()


def test_classify_endpoint_works_with_no_gemini_api_key(monkeypatch, client):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    semantic_service.reset_client_resolution()
    try:
        resp = client.post("/api/classify", json={"input": "Ambulance emergency alert"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "fallback"
        assert data["category"] == "emergency"
    finally:
        semantic_service.reset_client_resolution()


def test_fallback_result_is_always_marked_as_fallback_never_pretends_to_be_gemini():
    semantic_service.set_client(None)
    try:
        result = semantic_service.analyze("some traffic description")
        assert result["source"] == "fallback"
    finally:
        semantic_service.reset_client_resolution()


def test_fallback_covers_every_supported_category():
    from config import SUPPORTED_TRAFFIC_TYPES

    semantic_service.set_client(None)
    try:
        for category in SUPPORTED_TRAFFIC_TYPES:
            result = semantic_service.analyze_for_category("some label text", category)
            assert result["category"] == category
            assert result["source"] == "fallback"
            assert set(result["factors"]) == {
                "urgency", "consequence", "latency_sensitivity", "reliability_requirement",
            }
    finally:
        semantic_service.reset_client_resolution()
