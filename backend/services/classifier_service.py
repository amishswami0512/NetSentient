"""Traffic classification, behind a swappable abstraction.

The rest of the backend only ever calls `classify_text()`. The temporary
rule-based implementation below can be swapped out later (e.g. by the
AI/ML teammate) by calling `set_classifier()` with a different
BaseClassifier subclass -- no route or other service needs to change,
and the POST /api/classify contract (category/confidence/priority)
stays stable.
"""
from abc import ABC, abstractmethod

from config import PRIORITY_MAP


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
        ],
        "video": [
            "video", "call", "stream", "conference", "zoom", "meeting",
        ],
        "file": [
            "file", "upload", "download", "transfer", "document", "attachment",
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


def set_classifier(classifier: BaseClassifier) -> None:
    """Swap the active classifier implementation (used by teammates later)."""
    global _classifier
    _classifier = classifier


def classify_text(text: str) -> dict[str, float | str | int]:
    category, confidence = _classifier.classify(text)
    return {
        "category": category,
        "confidence": confidence,
        "priority": PRIORITY_MAP[category],
    }
