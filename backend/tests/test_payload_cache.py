"""Tests for the fast-path payload cache in front of classification.

Uses a counting fake classifier injected via set_classifier() to prove
cache hits genuinely skip classification work, not just that the
returned value happens to match.
"""
from services.classifier_service import (
    BaseClassifier,
    RuleBasedClassifier,
    classify_text,
    set_classifier,
)
from services.payload_cache import PayloadCache


class _CountingClassifier(BaseClassifier):
    def __init__(self, category: str = "background", confidence: float = 0.5):
        self.call_count = 0
        self._category = category
        self._confidence = confidence

    def classify(self, text: str) -> tuple[str, float]:
        self.call_count += 1
        return self._category, self._confidence


def _restore_default_classifier():
    set_classifier(RuleBasedClassifier())


def test_seeded_common_payload_never_calls_the_classifier():
    fake = _CountingClassifier()
    set_classifier(fake)
    try:
        result = classify_text("Emergency Alert")
        assert result["category"] == "emergency"
        assert fake.call_count == 0
    finally:
        _restore_default_classifier()


def test_seeded_lookup_is_case_and_whitespace_insensitive():
    fake = _CountingClassifier()
    set_classifier(fake)
    try:
        result = classify_text("  EMERGENCY   alert  ")
        assert result["category"] == "emergency"
        assert fake.call_count == 0
    finally:
        _restore_default_classifier()


def test_new_payload_is_classified_then_memoized():
    fake = _CountingClassifier(category="video", confidence=0.7)
    set_classifier(fake)
    try:
        text = "a payload never seen before in this test suite xyz123"
        first = classify_text(text)
        assert fake.call_count == 1
        assert first["category"] == "video"

        second = classify_text(text)
        assert fake.call_count == 1  # not called again
        assert second == first
    finally:
        _restore_default_classifier()


def test_switching_classifier_invalidates_previously_cached_results():
    fake_a = _CountingClassifier(category="video", confidence=0.7)
    set_classifier(fake_a)
    text = "a payload that will be reclassified after a classifier swap"
    try:
        first = classify_text(text)
        assert first["category"] == "video"

        fake_b = _CountingClassifier(category="file", confidence=0.8)
        set_classifier(fake_b)
        second = classify_text(text)

        assert second["category"] == "file"
        assert fake_b.call_count == 1
    finally:
        _restore_default_classifier()


def test_switching_classifier_keeps_common_payload_seed_available():
    set_classifier(_CountingClassifier())
    try:
        result = classify_text("Video Call")
        assert result["category"] == "video"
    finally:
        _restore_default_classifier()


def test_classify_text_is_deterministic_through_the_cache():
    payload = {"input": "large file upload in progress"}
    first = classify_text(payload["input"])
    second = classify_text(payload["input"])
    assert first == second


def test_payload_cache_lru_eviction():
    cache = PayloadCache(max_entries=2)
    cache.put("a", {"category": "emergency", "confidence": 1.0, "priority": 10})
    cache.put("b", {"category": "video", "confidence": 1.0, "priority": 5})
    cache.put("c", {"category": "file", "confidence": 1.0, "priority": 2})

    assert "a" not in cache
    assert "b" in cache
    assert "c" in cache
    assert len(cache) == 2


def test_payload_cache_get_returns_a_copy_not_a_live_reference():
    cache = PayloadCache()
    cache.put("x", {"category": "video", "confidence": 1.0, "priority": 5})
    result = cache.get("x")
    result["category"] = "mutated"
    assert cache.get("x")["category"] == "video"
