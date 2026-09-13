"""Tests for services/semantic_service.py: cache -> Gemini -> fallback."""
from types import SimpleNamespace

import services.semantic_service as semantic_service
from services.gemini_service import SemanticAnalysis


class _FakeModels:
    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.call_count = 0

    def generate_content(self, **kwargs):
        self.call_count += 1
        if self.exception is not None:
            raise self.exception
        return self.response


class _FakeClient:
    def __init__(self, **kwargs):
        self.models = _FakeModels(**kwargs)


def _analysis(**overrides) -> SemanticAnalysis:
    defaults = dict(
        category="critical_sensor",
        confidence=0.94,
        urgency=0.92,
        consequence=0.95,
        latency_sensitivity=0.88,
        reliability_requirement=0.93,
        reason="Dangerous sensor condition requiring rapid response.",
    )
    defaults.update(overrides)
    return SemanticAnalysis(**defaults)


def _client_for(analysis: SemanticAnalysis, exception=None) -> _FakeClient:
    if exception is not None:
        return _FakeClient(exception=exception)
    return _FakeClient(response=SimpleNamespace(parsed=analysis, text=analysis.model_dump_json()))


def _restore():
    semantic_service.reset_client_resolution()


def test_analyze_uses_gemini_when_client_available():
    semantic_service.set_client(_client_for(_analysis()))
    try:
        result = semantic_service.analyze("Factory temperature exceeded dangerous threshold")
        assert result["source"] == "gemini"
        assert result["category"] == "critical_sensor"
        assert result["factors"]["urgency"] == 0.92
    finally:
        _restore()


def test_analyze_falls_back_when_no_client_configured():
    semantic_service.set_client(None)
    try:
        result = semantic_service.analyze("Ambulance emergency alert")
        assert result["source"] == "fallback"
        assert result["category"] == "emergency"
        assert set(result["factors"]) == {"urgency", "consequence", "latency_sensitivity", "reliability_requirement"}
    finally:
        _restore()


def test_analyze_falls_back_when_gemini_raises():
    semantic_service.set_client(_client_for(None, exception=RuntimeError("boom")))
    try:
        result = semantic_service.analyze("Ambulance emergency alert")
        assert result["source"] == "fallback"
    finally:
        _restore()


def test_analyze_falls_back_when_gemini_returns_unknown_category():
    semantic_service.set_client(_client_for(_analysis(category="not_a_real_category")))
    try:
        # SemanticAnalysis itself has no category enum constraint, so this
        # constructs fine -- semantic_service must still reject it.
        result = semantic_service.analyze("some payload")
        assert result["source"] == "fallback"
    finally:
        _restore()


def test_analyze_result_is_cached_and_gemini_is_called_once():
    client = _client_for(_analysis())
    semantic_service.set_client(client)
    try:
        text = "Factory temperature exceeded dangerous threshold"
        first = semantic_service.analyze(text)
        second = semantic_service.analyze(text)

        assert first == second
        assert client.models.call_count == 1
    finally:
        _restore()


def test_switching_client_invalidates_cache():
    semantic_service.set_client(_client_for(_analysis(category="critical_sensor")))
    text = "some traffic description"
    try:
        first = semantic_service.analyze(text)
        assert first["category"] == "critical_sensor"

        semantic_service.set_client(_client_for(_analysis(category="video")))
        second = semantic_service.analyze(text)
        assert second["category"] == "video"
    finally:
        _restore()


def test_fallback_never_crashes_on_empty_or_unusual_input():
    semantic_service.set_client(None)
    try:
        for text in ["", "   ", "asdkjaslkdjaslkdj", "a" * 500]:
            result = semantic_service.analyze(text)
            assert result["category"] in {
                "emergency", "critical_sensor", "real_time", "video", "file", "background",
            }
            assert 0.0 <= result["confidence"] <= 1.0
    finally:
        _restore()


def test_common_keyword_never_calls_gemini_even_when_configured():
    client = _client_for(_analysis(category="video"))  # would return "video" if called
    semantic_service.set_client(client)
    try:
        result = semantic_service.analyze("Software Update")
        assert result["source"] == "keyword"
        assert result["category"] == "background"
        assert client.models.call_count == 0
    finally:
        _restore()


def test_common_keyword_case_and_whitespace_insensitive():
    semantic_service.set_client(None)
    try:
        result = semantic_service.analyze("  EMERGENCY   ALERT  ")
        assert result["source"] == "keyword"
        assert result["category"] == "emergency"
    finally:
        _restore()


def test_descriptive_sentence_with_a_keyword_word_still_uses_gemini():
    # "temperature" alone is fast-pathed nowhere in our seed list, and a
    # full descriptive sentence should still go to Gemini for real
    # context -- the fast path must not swallow nuanced input just
    # because it shares a word with a common term.
    client = _client_for(_analysis(category="critical_sensor", urgency=0.95, consequence=0.97))
    semantic_service.set_client(client)
    try:
        result = semantic_service.analyze("Factory temperature sensor reports dangerous overheating")
        assert result["source"] == "gemini"
        assert client.models.call_count == 1
    finally:
        _restore()


def test_cache_key_lets_distinct_text_share_one_gemini_call():
    # Simulates services/capture_service.py's use case: two flow
    # observations of the same host produce different description text
    # (different packet/byte counts) but share a stable signature --
    # passing that signature as cache_key must make the second call
    # reuse the first's result instead of calling Gemini again.
    client = _client_for(_analysis(category="video"))
    semantic_service.set_client(client)
    try:
        first = semantic_service.analyze(
            "Encrypted TLS session to 'zoom.us' on port 443, 12 packets over 1.0s",
            cache_key="tls:zoom.us:443",
        )
        second = semantic_service.analyze(
            "Encrypted TLS session to 'zoom.us' on port 443, 9001 packets over 84.2s",
            cache_key="tls:zoom.us:443",
        )
        assert first == second
        assert client.models.call_count == 1
    finally:
        _restore()


def test_cache_key_none_falls_back_to_keying_on_text_itself():
    client = _client_for(_analysis())
    semantic_service.set_client(client)
    try:
        text = "some payload without an explicit cache key"
        semantic_service.analyze(text)
        semantic_service.analyze(text)
        assert client.models.call_count == 1
    finally:
        _restore()


def test_switching_client_keeps_common_keyword_seed_available():
    semantic_service.set_client(_client_for(_analysis(category="video")))
    try:
        result = semantic_service.analyze("Emergency Alert")
        assert result["source"] == "keyword"
        assert result["category"] == "emergency"
    finally:
        _restore()
