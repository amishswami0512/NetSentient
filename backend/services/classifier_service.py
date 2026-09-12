"""Traffic classification, behind a swappable abstraction.

The rest of the backend only ever calls `classify_text()`. The temporary
rule-based implementation below can be swapped out later (e.g. by the
AI/ML teammate) by calling `set_classifier()` with a different
BaseClassifier subclass -- no route or other service needs to change,
and the POST /api/classify contract (category/confidence/priority)
stays stable.
"""
import json
import logging
import os
from abc import ABC, abstractmethod

from config import PRIORITY_MAP

logger = logging.getLogger(__name__)


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


class GeminiClassifier(BaseClassifier):
    """Real AI classifier backed by Google's Gemini API.

    Ported from the AI teammate's "HackyWacky" prototype: prompts Gemini
    to sort a payload into one of 4 severity tiers, then maps that tier
    onto our 5-category contract. Keeps the same in-memory cache (0ms
    repeat lookups) and the same "never let a bad API call take down
    classification" fallback -- except the fallback here delegates to
    RuleBasedClassifier instead of guessing a fixed tier, so a Gemini
    outage never produces a worse answer than the deterministic default.
    """

    TIER_TO_CATEGORY: dict[int, str] = {
        1: "emergency",
        2: "critical_sensor",
        3: "video",
        4: "background",
    }

    SYSTEM_INSTRUCTION = (
        "You are an expert Layer-7 network classifier for a critical infrastructure network.\n"
        "Your task is to analyze the semantic meaning of data packet payloads and categorize them "
        "into one of four priority tiers:\n"
        "Tier 1: Emergency/Life Safety/Imminent Failure (e.g., ICU alerts, structural collapse, fire)\n"
        "Tier 2: Core Operational Sensors (e.g., normal telemetry, status heartbeats, grid metrics)\n"
        "Tier 3: Standard Communication (e.g., human chat messages, standard logging, standard emails)\n"
        "Tier 4: Bulk / Background Traffic (e.g., software updates, media streaming, file backups)\n\n"
        "CRITICAL REQUIREMENT: You must respond ONLY with a valid JSON object. Do not include markdown blocks like ```json.\n"
        "The JSON object must contain exactly two keys:\n"
        "1. \"tier\": an integer (1, 2, 3, or 4)\n"
        "2. \"reason\": a brief, single-sentence string explanation."
    )

    CONFIDENCE = 0.90

    def __init__(self, client, model: str = "gemini-3.5-flash-lite") -> None:
        self._client = client
        self._model = model
        self._cache: dict[str, tuple[str, float]] = {}
        self._fallback = RuleBasedClassifier()

    def classify(self, text: str) -> tuple[str, float]:
        cleaned = text.strip()
        if cleaned in self._cache:
            return self._cache[cleaned]

        result = self._classify_via_gemini(cleaned)
        if result is None:
            result = self._fallback.classify(cleaned)

        self._cache[cleaned] = result
        return result

    def _classify_via_gemini(self, text: str) -> tuple[str, float] | None:
        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self._model,
                contents=f"Analyze this payload: '{text}'",
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_INSTRUCTION,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            parsed = json.loads(response.text)
            category = self.TIER_TO_CATEGORY[int(parsed["tier"])]
            return category, self.CONFIDENCE
        except Exception:
            logger.exception("Gemini classification failed, falling back to rule-based classifier")
            return None


def _build_default_classifier() -> BaseClassifier:
    """Use Gemini when configured, otherwise the safe deterministic default.

    Never raises: a missing package, missing API key, or client-init
    failure all just mean the rule-based classifier stays active.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return RuleBasedClassifier()
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        return GeminiClassifier(client)
    except Exception:
        logger.exception("Could not initialize GeminiClassifier, using RuleBasedClassifier")
        return RuleBasedClassifier()


_classifier: BaseClassifier = _build_default_classifier()


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
