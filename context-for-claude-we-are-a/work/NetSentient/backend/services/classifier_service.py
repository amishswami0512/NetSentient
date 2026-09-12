import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from config import SUPPORTED_TRAFFIC_TYPES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    confidence: float
    criticality_score: float
    reasoning: str
    provider: str


class ClassifierUnavailableError(RuntimeError):
    """Raised when the configured AI classifier cannot produce a result."""


class BaseClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> ClassificationResult:
        raise NotImplementedError


class UnconfiguredGeminiClassifier(BaseClassifier):
    """Prevents production traffic from being classified by keyword rules."""

    def classify(self, text: str) -> ClassificationResult:
        raise ClassifierUnavailableError(
            "Gemini is not configured. Create backend/.env and set GEMINI_API_KEY, then restart Flask."
        )


class RuleBasedDemoClassifier(BaseClassifier):
    """Offline classifier used for a fully runnable hackathon demo without an API key."""

    RULES = (
        ("emergency", 9.5, ("near death", "heart attack", "cardiac arrest", "stroke", "not breathing", "severe bleeding", "life-threatening", "life threatening", "met with an accident", "accident", "dog bite", "evacuate", "code-blue", "code blue", "fire", "toxic", "shelter-in-place", "immediate")),
        ("critical_sensor", 7.5, ("icu", "oxygen", "patient", "heart-rate", "heart rate", "sensor", "pressure", "temperature", "grid", "transformer", "fracture", "fractured", "anomaly", "abnormal")),
        ("video", 4.2, ("video", "camera", "webinar", "livestream", "screen share", "conference", "meeting")),
        ("file", 2.4, ("backup", "download", "upload", "archive", "document", "spreadsheet", "patch", "artifact", "export", "file")),
        ("background", 1.5, ("routine", "periodic", "scheduled", "heartbeat", "synchronization", "sync", "log", "cache", "metadata")),
    )

    def classify_if_confident(self, text: str) -> ClassificationResult | None:
        lowered = text.lower()
        for category, score, keywords in self.RULES:
            if any(keyword in lowered for keyword in keywords):
                return ClassificationResult(
                    category, 0.72, score,
                    f"Local safety rule matched this payload to {category.replace('_', ' ')} traffic.",
                    "rule-based-demo",
                )
        return None

    def classify(self, text: str) -> ClassificationResult:
        matched = self.classify_if_confident(text)
        if matched:
            return matched
        return ClassificationResult(
            "background", 0.60, 1.5,
            "Offline demo classifier found no urgent traffic indicators, so this is background traffic.",
            "rule-based-demo",
        )


class GeminiClassifier(BaseClassifier):
    SYSTEM_INSTRUCTION = (
        "You are an expert Layer-7 network classifier for a critical infrastructure network.\n"
        "Analyze the payload as a network-flow description, not as a general news story. "
        "Return a category plus an independent criticality score from 1.0 to 10.0, in 0.1 increments. Calibrate scores "
        "carefully: do not call ordinary traffic critical just because it mentions an emergency, "
        "a hospital, security, or critical infrastructure. Classify the traffic being transmitted.\n"
        "Use these rules:\n"
        "- emergency: an immediate life-safety event or imminent catastrophic failure that requires action now; score 9-10 only.\n"
        "- critical_sensor: an active abnormal medical, industrial, grid, or safety sensor reading, but not an immediate emergency; score 6-8.\n"
        "- video: a normal video call, camera stream, conference, or media stream, even when it supports emergency operations; score 3-5.\n"
        "- file: a normal upload, download, backup, patch, document, or archive transfer; score 2-4.\n"
        "- background: routine synchronization, heartbeat, logging, or low-urgency telemetry; score 1-3.\n"
        "Never give video, file, or background traffic a 9 or 10. Use 10 rarely: only when the payload itself says immediate action is needed to protect life or prevent catastrophic failure.\n"
        "Examples: 'routine emergency operations video call' is video around 4, not emergency; "
        "'nightly database backup' is file around 2; 'ICU oxygen saturation fell to 82 percent' "
        "is critical_sensor around 7; 'evacuate now due to chemical leak' is emergency around 10.\n"
        "Choose the category yourself from: emergency, critical_sensor, video, file, background.\n\n"
        "CRITICAL REQUIREMENT: You must respond ONLY with a valid JSON object. Do not include markdown blocks like ```json.\n"
        "The JSON object must contain exactly four keys:\n"
        "1. \"category\": one of the allowed category strings\n"
        "2. \"criticality_score\": a number from 1.0 through 10.0 with one decimal place\n"
        "3. \"confidence\": a number from 0 through 1\n"
        "4. \"reason\": a brief, single-sentence explanation."
    )

    def __init__(self, client, model: str = "gemini-3.5-flash-lite") -> None:
        self._client = client
        self._model = model
        self._cache: dict[str, ClassificationResult] = {}
        self._local_classifier = RuleBasedDemoClassifier()

    def classify(self, text: str) -> ClassificationResult:
        cleaned = text.strip()
        if cleaned in self._cache:
            return self._cache[cleaned]

        result = self._local_classifier.classify_if_confident(cleaned)
        if result is None:
            try:
                result = self._classify_via_gemini(cleaned)
            except ClassifierUnavailableError:
                logger.warning("Gemini unavailable; using local demo fallback for this payload.")
                result = self._local_classifier.classify(cleaned)
        self._cache[cleaned] = result
        return result

    def classify_many(self, texts: list[str]) -> list[ClassificationResult]:
        missing = [text.strip() for text in texts if text.strip() not in self._cache]
        unresolved = []
        for text in missing:
            local_result = self._local_classifier.classify_if_confident(text)
            if local_result:
                self._cache[text] = local_result
            else:
                unresolved.append(text)
        if unresolved:
            try:
                self._cache.update(zip(unresolved, self._classify_many_via_gemini(unresolved)))
            except ClassifierUnavailableError:
                logger.warning("Gemini unavailable; using local demo fallback for unresolved payloads.")
                self._cache.update((text, self._local_classifier.classify(text)) for text in unresolved)
        return [self._cache[text.strip()] for text in texts]

    def _classify_via_gemini(self, text: str) -> ClassificationResult:
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
            return self._parse_result(json.loads(response.text))
        except Exception as error:
            logger.exception("Gemini classification failed")
            if "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error):
                raise ClassifierUnavailableError(
                    "Gemini quota is temporarily exhausted. Wait for the quota window to reset "
                    "or check your Gemini plan and billing details."
                ) from error
            raise ClassifierUnavailableError(
                "Gemini could not analyze this payload. Check GEMINI_API_KEY, GEMINI_MODEL, "
                "and API availability."
            ) from error

    def _classify_many_via_gemini(self, texts: list[str]) -> list[ClassificationResult]:
        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self._model,
                contents=(
                    "Analyze each network payload in this JSON array. Return one classification "
                    "object per payload in the same order:\n" + json.dumps(texts)
                ),
                config=types.GenerateContentConfig(
                    system_instruction=(
                        f"{self.SYSTEM_INSTRUCTION}\nFor batch input, return exactly one JSON object "
                        "with a 'classifications' array. Do not omit any payload."
                    ),
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            parsed = json.loads(response.text)
            classifications = parsed["classifications"]
            if not isinstance(classifications, list) or len(classifications) != len(texts):
                raise ValueError("Gemini returned the wrong number of classifications.")
            return [self._parse_result(item) for item in classifications]
        except Exception as error:
            logger.exception("Gemini batch classification failed")
            if "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error):
                raise ClassifierUnavailableError(
                    "Gemini quota is temporarily exhausted. Wait for the quota window to reset "
                    "or check your Gemini plan and billing details."
                ) from error
            raise ClassifierUnavailableError(
                "Gemini could not analyze the demo payloads. Check GEMINI_API_KEY, GEMINI_MODEL, "
                "and API availability."
            ) from error

    @staticmethod
    def _parse_result(parsed: dict[str, object]) -> ClassificationResult:
        category = parsed["category"]
        if category not in SUPPORTED_TRAFFIC_TYPES:
            raise ValueError("Gemini response contained an invalid category.")
        criticality_score = parsed["criticality_score"]
        if isinstance(criticality_score, bool) or not isinstance(criticality_score, (int, float)):
            raise ValueError("Gemini response contained an invalid criticality score.")
        if not 1 <= criticality_score <= 10:
            raise ValueError("Gemini criticality score must be between 1 and 10.")
        confidence = parsed["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("Gemini response contained an invalid confidence score.")
        if not 0 <= confidence <= 1:
            raise ValueError("Gemini confidence must be between 0 and 1.")
        reasoning = parsed["reason"]
        if not isinstance(reasoning, str) or not reasoning.strip():
            raise ValueError("Gemini response contained an invalid reason.")
        return ClassificationResult(
            category,
            round(float(confidence), 2),
            round(float(criticality_score), 1),
            reasoning.strip(),
            "gemini",
        )


def _build_default_classifier() -> BaseClassifier:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY is absent; using the offline rule-based demo classifier.")
        return RuleBasedDemoClassifier()
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        return GeminiClassifier(client, model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    except Exception as error:
        logger.exception("Could not initialize GeminiClassifier")
        raise ClassifierUnavailableError(
            "Gemini could not be initialized. Check GEMINI_API_KEY and the google-genai installation."
        ) from error


_classifier: BaseClassifier = _build_default_classifier()


def set_classifier(classifier: BaseClassifier) -> None:
    global _classifier
    _classifier = classifier


def classify_text(text: str) -> dict[str, float | str | int]:
    result = _classifier.classify(text)
    return {
        "category": result.category,
        "confidence": result.confidence,
        "criticality_score": result.criticality_score,
        "priority": result.criticality_score,
        "reasoning": result.reasoning,
        "provider": result.provider,
    }


def classify_texts(texts: list[str]) -> list[dict[str, float | str | int]]:
    if hasattr(_classifier, "classify_many"):
        results = _classifier.classify_many(texts)  # type: ignore[attr-defined]
    else:
        results = [_classifier.classify(text) for text in texts]
    return [
        {
            "category": result.category,
            "confidence": result.confidence,
            "criticality_score": result.criticality_score,
            "priority": result.criticality_score,
            "reasoning": result.reasoning,
            "provider": result.provider,
        }
        for result in results
    ]
