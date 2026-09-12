"""Tests for services/gemini_service.py: the raw Gemini call wrapper.

Uses a fake client that mimics google.genai's client.models.generate_content()
interface -- no real network calls, no API key required.
"""
import time
from types import SimpleNamespace

from services.gemini_service import SemanticAnalysis, analyze


class _FakeModels:
    def __init__(self, response=None, exception=None, delay=0.0):
        self.response = response
        self.exception = exception
        self.delay = delay
        self.call_count = 0

    def generate_content(self, **kwargs):
        self.call_count += 1
        if self.delay:
            time.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.response


class _FakeClient:
    def __init__(self, **kwargs):
        self.models = _FakeModels(**kwargs)


def _valid_analysis() -> SemanticAnalysis:
    return SemanticAnalysis(
        category="critical_sensor",
        confidence=0.94,
        urgency=0.92,
        consequence=0.95,
        latency_sensitivity=0.88,
        reliability_requirement=0.93,
        reason="Dangerous sensor condition requiring rapid response.",
    )


def test_analyze_returns_dict_for_valid_structured_response():
    parsed = _valid_analysis()
    client = _FakeClient(response=SimpleNamespace(parsed=parsed, text=parsed.model_dump_json()))

    result = analyze("Factory temperature exceeded dangerous threshold", client, timeout_seconds=2.0)

    assert result is not None
    assert result["category"] == "critical_sensor"
    assert result["confidence"] == 0.94
    assert result["urgency"] == 0.92


def test_analyze_falls_back_to_manual_parse_when_parsed_is_missing():
    parsed = _valid_analysis()
    # Simulate the SDK not auto-populating .parsed but still returning
    # valid JSON text -- analyze() should recover via manual parsing.
    client = _FakeClient(response=SimpleNamespace(parsed=None, text=parsed.model_dump_json()))

    result = analyze("Factory temperature exceeded dangerous threshold", client, timeout_seconds=2.0)

    assert result is not None
    assert result["category"] == "critical_sensor"


def test_analyze_returns_none_for_malformed_json_text():
    client = _FakeClient(response=SimpleNamespace(parsed=None, text="not valid json at all"))
    result = analyze("some input", client, timeout_seconds=2.0)
    assert result is None


def test_analyze_returns_none_for_missing_fields():
    client = _FakeClient(response=SimpleNamespace(parsed=None, text='{"category": "video"}'))
    result = analyze("some input", client, timeout_seconds=2.0)
    assert result is None


def test_analyze_returns_none_for_confidence_above_one():
    bad_json = (
        '{"category": "video", "confidence": 1.5, "urgency": 0.5, '
        '"consequence": 0.5, "latency_sensitivity": 0.5, '
        '"reliability_requirement": 0.5, "reason": "x"}'
    )
    client = _FakeClient(response=SimpleNamespace(parsed=None, text=bad_json))
    result = analyze("some input", client, timeout_seconds=2.0)
    assert result is None


def test_analyze_returns_none_for_negative_confidence():
    bad_json = (
        '{"category": "video", "confidence": -0.2, "urgency": 0.5, '
        '"consequence": 0.5, "latency_sensitivity": 0.5, '
        '"reliability_requirement": 0.5, "reason": "x"}'
    )
    client = _FakeClient(response=SimpleNamespace(parsed=None, text=bad_json))
    result = analyze("some input", client, timeout_seconds=2.0)
    assert result is None


def test_analyze_returns_none_for_urgency_above_one():
    bad_json = (
        '{"category": "video", "confidence": 0.8, "urgency": 1.5, '
        '"consequence": 0.5, "latency_sensitivity": 0.5, '
        '"reliability_requirement": 0.5, "reason": "x"}'
    )
    client = _FakeClient(response=SimpleNamespace(parsed=None, text=bad_json))
    result = analyze("some input", client, timeout_seconds=2.0)
    assert result is None


def test_analyze_returns_none_on_client_exception():
    client = _FakeClient(exception=RuntimeError("simulated API failure"))
    result = analyze("some input", client, timeout_seconds=2.0)
    assert result is None


def test_analyze_returns_none_on_timeout_without_hanging():
    client = _FakeClient(response=SimpleNamespace(parsed=_valid_analysis(), text="{}"), delay=1.5)

    start = time.monotonic()
    result = analyze("some input", client, timeout_seconds=0.3)
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < 2.0  # bounded, not left hanging for the full 1.5s+ call


def test_analyze_is_deterministic_for_the_same_valid_response():
    parsed = _valid_analysis()
    client = _FakeClient(response=SimpleNamespace(parsed=parsed, text=parsed.model_dump_json()))

    first = analyze("same input", client, timeout_seconds=2.0)
    second = analyze("same input", client, timeout_seconds=2.0)
    assert first == second
