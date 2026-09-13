"""Semantic traffic analysis: keyword fast-path -> Gemini -> deterministic fallback.

This is the only module the rest of the backend should call for
semantic analysis (routes/classify.py, services/state_service.py).
It never lets a Gemini failure propagate: every call returns a fully
valid result, explicitly marked with where it came from.

    TRAFFIC TEXT
      -> payload cache (instant repeat lookups, any source)
      -> curated common-word fast path (instant, skips Gemini entirely)
      -> Gemini (services/gemini_service.py) if configured
      -> independent validation of Gemini's output (untrusted input)
      -> deterministic fallback (services/classifier_service.py's
         RuleBasedClassifier + config.FALLBACK_SEMANTIC_FACTORS) if
         Gemini is unavailable, times out, or returns anything invalid
      -> {category, confidence, factors, reason, source}

`source` is one of:
  - "keyword"  matched a curated common word/phrase, Gemini not called
  - "gemini"   real semantic analysis
  - "fallback" Gemini was unavailable or returned something invalid

Gemini never decides priority or touches routing -- that happens in
services/priority_service.py, one layer up.

Why a curated list rather than "skip Gemini if any keyword matches":
a broad keyword trigger would defeat the point of Gemini for realistic
input -- "routine temperature reading" contains the same keyword
("temperature") as "temperature exceeded dangerous threshold" but needs
real context to tell them apart. Only short, genuinely unambiguous
common words/phrases are fast-pathed; anything more descriptive still
goes to Gemini.
"""
import logging
from typing import Any

from config import Config, FALLBACK_SEMANTIC_FACTORS, SUPPORTED_TRAFFIC_TYPES
from services import gemini_service
from services.classifier_service import RuleBasedClassifier
from services.payload_cache import PayloadCache

logger = logging.getLogger(__name__)

_cache = PayloadCache()
_fallback_classifier = RuleBasedClassifier()

_FACTOR_KEYS = ("urgency", "consequence", "latency_sensitivity", "reliability_requirement")

# Common short words/phrases that skip Gemini entirely -- instant,
# free, and correct enough for genuinely unambiguous input. Each maps
# to a category; confidence and factors reuse the same typical-value
# table as the deterministic fallback (config.FALLBACK_SEMANTIC_FACTORS),
# since a bare common word carries no more context than the category
# itself does.
_COMMON_KEYWORD_SEED: dict[str, str] = {
    "emergency": "emergency",
    "emergency alert": "emergency",
    "sos": "emergency",
    "fire": "emergency",
    "evacuation": "emergency",
    "ambulance": "emergency",
    "critical sensor": "critical_sensor",
    "sensor alert": "critical_sensor",
    "heart rate monitor": "critical_sensor",
    "real time control": "real_time",
    "real-time control": "real_time",
    "live monitoring": "real_time",
    "video call": "video",
    "video conference": "video",
    "voice call": "video",
    "file transfer": "file",
    "download": "file",
    "upload": "file",
    "software update": "background",
    "background sync": "background",
    "backup": "background",
    "cloud sync": "background",
}

def _seed_common_keywords() -> None:
    for phrase, category in _COMMON_KEYWORD_SEED.items():
        _cache.put(
            phrase,
            {
                "category": category,
                "confidence": 0.95,
                "factors": dict(FALLBACK_SEMANTIC_FACTORS[category]),
                "reason": f"Recognized as a common '{category}' term -- Gemini not needed.",
                "source": "keyword",
            },
        )


_seed_common_keywords()

# Client resolution state. "unset" means "not yet resolved from
# Config.GEMINI_API_KEY"; set_client() (used by tests, or to swap
# credentials without restarting) short-circuits that lazy resolution.
_client: Any = None
_client_resolved = False


def set_client(client: Any) -> None:
    """Explicitly set the Gemini client, bypassing env-based lookup.

    Used by tests to inject a fake client. Pass None to force
    fallback-only behavior. Clears the cache too, since cached results
    may have come from a different client/model.
    """
    global _client, _client_resolved
    _client = client
    _client_resolved = True
    _cache.clear()
    _seed_common_keywords()


def reset_client_resolution() -> None:
    """Forget any resolved client so the next call re-reads Config.GEMINI_API_KEY.

    Mainly for tests that change the API key between cases.
    """
    global _client, _client_resolved
    _client = None
    _client_resolved = False
    _cache.clear()
    _seed_common_keywords()


def _get_client() -> Any:
    global _client, _client_resolved
    if _client_resolved:
        return _client
    _client_resolved = True
    if not Config.GEMINI_API_KEY:
        return None
    try:
        from google import genai

        _client = genai.Client(api_key=Config.GEMINI_API_KEY)
    except Exception:
        logger.exception("Could not initialize Gemini client")
        _client = None
    return _client


def _validate_gemini_result(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Independently validate Gemini's output. Treat it as untrusted:
    re-check ranges and category membership ourselves regardless of
    what the SDK's schema enforcement already did.
    """
    try:
        category = raw["category"]
        if category not in SUPPORTED_TRAFFIC_TYPES:
            return None

        confidence = float(raw["confidence"])
        factors = {key: float(raw[key]) for key in _FACTOR_KEYS}

        if not (0.0 <= confidence <= 1.0):
            return None
        if not all(0.0 <= v <= 1.0 for v in factors.values()):
            return None

        reason = str(raw.get("reason", "")).strip()[:280]
        return {
            "category": category,
            "confidence": round(confidence, 4),
            "factors": {k: round(v, 4) for k, v in factors.items()},
            "reason": reason or "Semantic analysis of the traffic description.",
        }
    except (KeyError, TypeError, ValueError):
        return None


def _fallback_result(text: str) -> dict[str, Any]:
    category, confidence = _fallback_classifier.classify(text)
    factors = dict(FALLBACK_SEMANTIC_FACTORS[category])
    return {
        "category": category,
        "confidence": confidence,
        "factors": factors,
        "reason": (
            "Deterministic fallback estimate for this category "
            "(Gemini unavailable or returned an invalid response)."
        ),
        "source": "fallback",
    }


def analyze_for_category(text: str, category: str) -> dict[str, Any]:
    """Like analyze(), but the category is already known (e.g. traffic
    creation via a validated `type` field) -- only the semantic factors
    need extracting from `text`. Gemini's own category guess is ignored
    in favor of the declared one, and the fallback looks up
    FALLBACK_SEMANTIC_FACTORS[category] directly instead of re-guessing
    the category via keyword matching (which could disagree with the
    already-known, validated category).
    """
    cache_key = f"{category}::{text}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    result = None
    client = _get_client()
    if client is not None:
        raw = gemini_service.analyze(text, client)
        if raw is not None:
            validated = _validate_gemini_result(raw)
            if validated is not None:
                validated["category"] = category
                validated["source"] = "gemini"
                result = validated

    if result is None:
        _, confidence = _fallback_classifier.classify(text)
        result = {
            "category": category,
            "confidence": confidence,
            "factors": dict(FALLBACK_SEMANTIC_FACTORS[category]),
            "reason": (
                "Deterministic fallback estimate for this category "
                "(Gemini unavailable or returned an invalid response)."
            ),
            "source": "fallback",
        }

    if result["source"] != "fallback":
        _cache.put(cache_key, result)
    return result


def analyze(text: str, cache_key: str | None = None) -> dict[str, Any]:
    """Return {category, confidence, factors, reason, source} for `text`.

    Always succeeds. `factors` is a dict with keys urgency, consequence,
    latency_sensitivity, reliability_requirement, each 0.0-1.0.
    `source` is "gemini", "keyword", or "fallback". Only non-fallback
    results are cached (by normalized text, or by `cache_key` if given
    -- see below): caching a fallback answer would mean a transient
    Gemini failure (a timeout, a network blip) gets stuck showing
    "fallback" forever for that input, instead of the next call simply
    retrying Gemini and self-healing once it recovers.

    `cache_key`, when given, is used for the cache lookup/store instead
    of `text` itself, while `text` is still what actually gets sent to
    Gemini on a miss. This matters for real captured traffic
    (services/capture_service.py): the display description bakes in
    per-observation stats ("340 packets over 12.4s") that make every
    single flow's literal text unique, so keying the cache on that text
    would call Gemini fresh for every repeat connection to the same
    host -- keying on a stable signature instead ("tls:zoom.us:443")
    means the *first* observation of a pattern gets a real Gemini call
    with its full descriptive text, and every later occurrence of that
    same pattern reuses the result instantly, regardless of its own
    (different) packet/byte counts.
    """
    key = cache_key or text
    cached = _cache.get(key)
    if cached is not None:
        return cached

    result = None
    client = _get_client()
    if client is not None:
        raw = gemini_service.analyze(text, client)
        if raw is not None:
            validated = _validate_gemini_result(raw)
            if validated is not None:
                validated["source"] = "gemini"
                result = validated

    if result is None:
        result = _fallback_result(text)

    if result["source"] != "fallback":
        _cache.put(key, result)
    return result
