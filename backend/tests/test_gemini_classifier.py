"""Unit tests for the Gemini-backed classifier (ported from the AI
teammate's "HackyWacky" prototype).

These never call the real Gemini API -- a fake client is injected
directly, so the tests stay fast, deterministic, and don't need
GEMINI_API_KEY set.
"""
import json
from types import SimpleNamespace

from services.classifier_service import (
    GeminiClassifier,
    RuleBasedClassifier,
    _build_default_classifier,
)


class _FakeModels:
    def __init__(self, response_text: str | None = None, raise_error: bool = False):
        self.response_text = response_text
        self.raise_error = raise_error
        self.call_count = 0

    def generate_content(self, **kwargs):
        self.call_count += 1
        if self.raise_error:
            raise RuntimeError("simulated Gemini API failure")
        return SimpleNamespace(text=self.response_text)


class _FakeGeminiClient:
    def __init__(self, response_text: str | None = None, raise_error: bool = False):
        self.models = _FakeModels(response_text, raise_error)


def test_gemini_classifier_maps_tier_1_to_emergency():
    client = _FakeGeminiClient(response_text=json.dumps({"tier": 1, "reason": "fire detected"}))
    classifier = GeminiClassifier(client)
    category, confidence = classifier.classify("Building on fire, evacuate now")
    assert category == "emergency"
    assert confidence == GeminiClassifier.CONFIDENCE


def test_gemini_classifier_maps_all_tiers():
    expected = {1: "emergency", 2: "critical_sensor", 3: "video", 4: "background"}
    for tier, category in expected.items():
        client = _FakeGeminiClient(response_text=json.dumps({"tier": tier, "reason": "x"}))
        classifier = GeminiClassifier(client)
        result_category, _ = classifier.classify(f"payload for tier {tier}")
        assert result_category == category


def test_gemini_classifier_falls_back_to_rule_based_on_api_error():
    client = _FakeGeminiClient(raise_error=True)
    classifier = GeminiClassifier(client)
    category, confidence = classifier.classify("large file upload in progress")

    expected_category, expected_confidence = RuleBasedClassifier().classify(
        "large file upload in progress"
    )
    assert category == expected_category
    assert confidence == expected_confidence


def test_gemini_classifier_falls_back_on_malformed_response():
    client = _FakeGeminiClient(response_text="not valid json")
    classifier = GeminiClassifier(client)
    category, confidence = classifier.classify("ambulance emergency alert")

    expected_category, expected_confidence = RuleBasedClassifier().classify(
        "ambulance emergency alert"
    )
    assert category == expected_category
    assert confidence == expected_confidence


def test_gemini_classifier_caches_repeat_calls():
    client = _FakeGeminiClient(response_text=json.dumps({"tier": 4, "reason": "backup job"}))
    classifier = GeminiClassifier(client)

    classifier.classify("nightly backup running")
    classifier.classify("nightly backup running")

    assert client.models.call_count == 1


def test_default_classifier_is_rule_based_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(_build_default_classifier(), RuleBasedClassifier)


def test_default_classifier_uses_gemini_when_api_key_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    assert isinstance(_build_default_classifier(), GeminiClassifier)
