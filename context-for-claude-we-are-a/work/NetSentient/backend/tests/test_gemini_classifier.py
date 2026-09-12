"""Unit tests for the Gemini-backed classifier (ported from the AI
teammate's "HackyWacky" prototype).

These never call the real Gemini API -- a fake client is injected
directly, so the tests stay fast, deterministic, and don't need
GEMINI_API_KEY set.
"""
import json
from types import SimpleNamespace

import pytest

from services.classifier_service import (
    GeminiClassifier,
    RuleBasedDemoClassifier,
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


def test_gemini_classifier_uses_gemini_category_and_criticality():
    client = _FakeGeminiClient(response_text=json.dumps({
        "category": "emergency",
        "criticality_score": 10,
        "confidence": 0.97,
        "reason": "fire detected",
    }))
    classifier = GeminiClassifier(client)
    result = classifier.classify("Building on fire, evacuate now")
    assert result.category == "emergency"
    assert result.criticality_score == 10
    assert result.confidence == 0.97
    assert result.reasoning == "fire detected"
    assert result.provider == "gemini"


def test_gemini_classifier_preserves_one_decimal_criticality():
    client = _FakeGeminiClient(response_text=json.dumps({
        "category": "video",
        "criticality_score": 3.7,
        "confidence": 0.81,
        "reason": "routine video call",
    }))
    result = GeminiClassifier(client).classify("Routine team video call")
    assert result.criticality_score == 3.7


def test_gemini_classifier_accepts_gemini_scores_without_tier_mapping():
    expected = {
        "emergency": 10,
        "critical_sensor": 8,
        "video": 5,
        "background": 2,
    }
    for category, score in expected.items():
        client = _FakeGeminiClient(response_text=json.dumps({
            "category": category,
            "criticality_score": score,
            "confidence": 0.8,
            "reason": "x",
        }))
        classifier = GeminiClassifier(client)
        result = classifier.classify(f"payload for {category}")
        assert result.category == category
        assert result.criticality_score == score


def test_gemini_classifier_uses_local_rule_when_api_is_unavailable():
    client = _FakeGeminiClient(raise_error=True)
    classifier = GeminiClassifier(client)

    result = classifier.classify("large file upload in progress")
    assert result.category == "file"
    assert result.provider == "rule-based-demo"


def test_gemini_classifier_falls_back_when_response_is_malformed():
    client = _FakeGeminiClient(response_text="not valid json")
    classifier = GeminiClassifier(client)

    result = classifier.classify("ambulance emergency alert")
    assert result.provider == "rule-based-demo"


def test_gemini_classifier_caches_repeat_calls():
    client = _FakeGeminiClient(response_text=json.dumps({
        "category": "background",
        "criticality_score": 2,
        "confidence": 0.8,
        "reason": "backup job",
    }))
    classifier = GeminiClassifier(client)

    classifier.classify("nightly backup running")
    classifier.classify("nightly backup running")

    assert client.models.call_count == 1


def test_default_classifier_uses_offline_demo_rules_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    classifier = _build_default_classifier()
    assert isinstance(classifier, RuleBasedDemoClassifier)
    assert classifier.classify("ICU oxygen is below threshold").category == "critical_sensor"


def test_default_classifier_uses_gemini_when_api_key_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    assert isinstance(_build_default_classifier(), GeminiClassifier)
