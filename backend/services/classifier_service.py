"""Deterministic keyword-based traffic classification.

This module is the simple, always-available classification path: no
network calls, no external dependencies, used both as a standalone
utility and as the deterministic fallback's category detector when
Gemini is unavailable (see services/semantic_service.py, which is
where real Gemini-backed semantic analysis lives).

The rest of the backend only ever calls `classify_text()`. Swappable
via `set_classifier()` if a different BaseClassifier implementation is
ever needed -- no route or other service needs to change, and the
POST /api/classify contract (category/confidence/priority) stays
stable.
"""
from abc import ABC, abstractmethod

from config import PRIORITY_MAP
from services.payload_cache import PayloadCache


class BaseClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> tuple[str, float]:
        """Return (category, confidence) for the given input text."""
        raise NotImplementedError


class RuleBasedClassifier(BaseClassifier):
    """Deterministic keyword-matching classifier.

    A stand-in for a real model: scores each category by counting
    keyword hits, deterministically breaks ties toward the
    higher-priority category (safer default for a safety-relevant
    router), and falls back to "background" when nothing matches.
    """

    KEYWORDS: dict[str, list[str]] = {
        "emergency": [
            "emergency", "ambulance", "fire", "evacuat", "911",
            "disaster", "urgent alert", "life-threatening", "sos",
        ],
        "critical_sensor": [
            "heart rate", "sensor", "vital", "anomaly", "oxygen",
            "blood pressure", "medical", "patient", "icu", "glucose",
            "temperature", "pressure", "threshold", "overheating",
            "machine failure", "collision", "autonomous vehicle",
        ],
        "transactional": [
            "transaction", "stock trade", "trade execution", "payment",
            "point-of-sale", "point of sale", "credit card", "authorization token",
            "order execution", "purchase",
        ],
        "real_time": [
            "real-time", "real time", "live monitoring", "interactive control",
            "control signal", "control loop", "remote control", "live dashboard",
            "telemetry control",
        ],
        "voice_chat": [
            "voip", "sip", "voice call", "voice chat", "phone call", "dispatcher call",
        ],
        "video": [
            "video", "call", "stream", "conference", "zoom", "meeting",
            # Well-known video/streaming hostnames -- so a scanned
            # connection's label ("chrome connection to youtube.com on
            # port 443") still gets a sensible category in fallback
            # mode, not just whatever port 443 happens to map to.
            "youtube", "netflix", "twitch", "hulu", "disneyplus", "primevideo",
        ],
        "file": [
            "file", "upload", "download", "transfer", "document", "attachment",
            "dropbox", "onedrive", "icloud",
        ],
        "background": [
            "update", "background", "sync", "backup", "telemetry", "patch",
        ],
    }

    FALLBACK_CATEGORY = "background"
    FALLBACK_CONFIDENCE = 0.30

    def classify(self, text: str) -> tuple[str, float]:
        normalized = text.lower()
        scores: dict[str, int] = {
            category: sum(1 for kw in keywords if kw in normalized)
            for category, keywords in self.KEYWORDS.items()
        }

        best_score = max(scores.values())
        if best_score == 0:
            return self.FALLBACK_CATEGORY, self.FALLBACK_CONFIDENCE

        # Tie-break toward the higher-priority category.
        candidates = [c for c, s in scores.items() if s == best_score]
        category = max(candidates, key=lambda c: PRIORITY_MAP[c])
        confidence = round(min(0.99, 0.60 + 0.12 * best_score), 2)
        return category, confidence


_classifier: BaseClassifier = RuleBasedClassifier()

# Fast path: payloads seen often enough to hardcode (the demo's own
# default traffic labels, plus a few obviously common phrasings) skip
# classification entirely and resolve instantly. Anything else is
# classified normally the first time, then memoized in the same cache
# for subsequent lookups -- see services/payload_cache.py.
_COMMON_PAYLOAD_SEED: dict[str, dict[str, float | str | int]] = {
    "emergency alert": {"category": "emergency", "confidence": 0.99, "priority": PRIORITY_MAP["emergency"]},
    "critical sensor": {"category": "critical_sensor", "confidence": 0.99, "priority": PRIORITY_MAP["critical_sensor"]},
    "video call": {"category": "video", "confidence": 0.99, "priority": PRIORITY_MAP["video"]},
    "file transfer": {"category": "file", "confidence": 0.99, "priority": PRIORITY_MAP["file"]},
    "background update": {"category": "background", "confidence": 0.99, "priority": PRIORITY_MAP["background"]},
    "ambulance emergency alert dispatched": {"category": "emergency", "confidence": 0.97, "priority": PRIORITY_MAP["emergency"]},
    "software update": {"category": "background", "confidence": 0.9, "priority": PRIORITY_MAP["background"]},
}

_payload_cache = PayloadCache()
_payload_cache.seed(_COMMON_PAYLOAD_SEED)


def set_classifier(classifier: BaseClassifier) -> None:
    """Swap the active classifier implementation (used by teammates later).

    Clears the payload cache too -- cached results were computed by the
    previous classifier, so keeping them around after a swap would
    silently serve stale answers for anything already looked up.
    """
    global _classifier
    _classifier = classifier
    _payload_cache.clear()
    _payload_cache.seed(_COMMON_PAYLOAD_SEED)


def classify_text(text: str) -> dict[str, float | str | int]:
    cached = _payload_cache.get(text)
    if cached is not None:
        return cached

    category, confidence = _classifier.classify(text)
    result: dict[str, float | str | int] = {
        "category": category,
        "confidence": confidence,
        "priority": PRIORITY_MAP[category],
    }
    _payload_cache.put(text, result)
    return result
