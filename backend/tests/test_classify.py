from types import SimpleNamespace

import pytest

import services.semantic_service as semantic_service
from services.gemini_service import SemanticAnalysis


class _FakeModels:
    def __init__(self, response):
        self.response = response

    def generate_content(self, **kwargs):
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.models = _FakeModels(response)


def _gemini_response(**overrides) -> SimpleNamespace:
    defaults = dict(
        category="critical_sensor",
        confidence=0.9,
        urgency=0.5,
        consequence=0.5,
        latency_sensitivity=0.5,
        reliability_requirement=0.5,
        reason="test",
    )
    defaults.update(overrides)
    analysis = SemanticAnalysis(**defaults)
    return SimpleNamespace(parsed=analysis, text=analysis.model_dump_json())


def _use_fake_gemini(**overrides):
    semantic_service.set_client(_FakeClient(_gemini_response(**overrides)))


def _restore_no_gemini():
    semantic_service.reset_client_resolution()


@pytest.fixture(autouse=True)
def _clean_semantic_service_state():
    yield
    _restore_no_gemini()


def test_classify_returns_full_response_shape(client):
    resp = client.post("/api/classify", json={"input": "Ambulance emergency alert dispatched"})
    assert resp.status_code == 200
    data = resp.get_json()
    for field in ("category", "confidence", "priority", "priority_factors", "low_confidence", "source", "reason"):
        assert field in data
    assert isinstance(data["priority"], (int, float))
    assert 0.0 <= data["priority"] <= 10.0
    for factor in ("urgency", "consequence", "latency_sensitivity", "reliability_requirement"):
        assert factor in data["priority_factors"]


def test_classify_critical_sensor_input(client):
    resp = client.post("/api/classify", json={"input": "Critical heart rate anomaly detected"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["category"] == "critical_sensor"
    assert 0.0 < data["confidence"] <= 1.0
    assert data["source"] == "fallback"  # no GEMINI_API_KEY set in test env


def test_classify_emergency_input(client):
    resp = client.post("/api/classify", json={"input": "Ambulance emergency alert dispatched"})
    data = resp.get_json()
    assert data["category"] == "emergency"


def test_emergency_priority_outranks_file_priority(client):
    emergency = client.post("/api/classify", json={"input": "Ambulance emergency alert dispatched"}).get_json()
    file_ = client.post("/api/classify", json={"input": "large file upload in progress"}).get_json()
    assert emergency["priority"] > file_["priority"]


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


def test_classify_source_is_gemini_when_configured(client):
    _use_fake_gemini(category="video", urgency=0.9, consequence=0.9, latency_sensitivity=0.9, reliability_requirement=0.9)
    resp = client.post("/api/classify", json={"input": "Emergency response live video feed"})
    data = resp.get_json()
    assert data["source"] == "gemini"
    assert data["category"] == "video"


def test_context_changes_priority_within_the_same_category(client):
    # Same category, deliberately different semantic factors -- proves
    # priority is NOT a flat function of category alone.
    _use_fake_gemini(
        category="critical_sensor",
        urgency=0.1, consequence=0.1, latency_sensitivity=0.1, reliability_requirement=0.2,
    )
    routine = client.post("/api/classify", json={"input": "Routine temperature telemetry"}).get_json()

    semantic_service.reset_client_resolution()
    _use_fake_gemini(
        category="critical_sensor",
        urgency=0.95, consequence=0.97, latency_sensitivity=0.9, reliability_requirement=0.95,
    )
    dangerous = client.post(
        "/api/classify", json={"input": "Factory temperature sensor reports dangerous overheating"}
    ).get_json()

    assert routine["category"] == dangerous["category"] == "critical_sensor"
    assert dangerous["priority"] > routine["priority"]


def test_low_confidence_flag_dampens_priority_without_crashing(client):
    _use_fake_gemini(
        category="critical_sensor", confidence=0.2,
        urgency=0.99, consequence=0.99, latency_sensitivity=0.99, reliability_requirement=0.99,
    )
    uncertain = client.post("/api/classify", json={"input": "some ambiguous payload"}).get_json()

    semantic_service.reset_client_resolution()
    _use_fake_gemini(
        category="critical_sensor", confidence=0.95,
        urgency=0.99, consequence=0.99, latency_sensitivity=0.99, reliability_requirement=0.99,
    )
    confident = client.post("/api/classify", json={"input": "some ambiguous payload 2"}).get_json()

    assert uncertain["low_confidence"] is True
    assert confident["low_confidence"] is False
    assert uncertain["priority"] < confident["priority"]
