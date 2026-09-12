"""Thin wrapper around the Gemini API for semantic traffic analysis.

This module's only job is: given a traffic description, ask Gemini for
a structured semantic analysis and hand back a plain dict, or None if
anything at all went wrong. It never raises, never blocks indefinitely,
and never decides priority or routing -- that's semantic_service.py and
priority_service.py's job. Gemini provides understanding; this module
just fetches it safely.
"""
import concurrent.futures
import logging

from pydantic import BaseModel, Field

from config import Config, SUPPORTED_TRAFFIC_TYPES

logger = logging.getLogger(__name__)

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini-call")

SYSTEM_INSTRUCTION = (
    "You are a semantic network traffic analysis engine. Analyze the meaning "
    "and operational importance of a traffic description. Evaluate urgency, "
    "consequence of delay, latency sensitivity, and reliability requirements. "
    "Do not determine network routing yourself. Return only the requested "
    "structured JSON, with no markdown formatting.\n\n"
    "Definitions:\n"
    "- urgency: how quickly must this traffic be delivered? "
    "'Emergency evacuation alert' is extremely high; 'daily analytics upload' is very low.\n"
    "- consequence: what happens if this traffic is delayed or lost? "
    "'Autonomous vehicle collision warning' is extremely high; 'cloud backup' is low.\n"
    "- latency_sensitivity: does this require near-real-time delivery? "
    "'Emergency control signal' is extremely high; 'software update' is low.\n"
    "- reliability_requirement: how important is guaranteed successful delivery? "
    "'Safety shutdown command' is extremely high; 'video stream' is moderate; "
    "'background analytics' is low.\n\n"
    f"category must be exactly one of: {', '.join(SUPPORTED_TRAFFIC_TYPES)}.\n\n"
    "Analyze the complete semantic context, not just keywords. Similar words can "
    "mean very different things: 'critical software update' is not automatically "
    "emergency; 'live emergency response video feed' is very different from 'live "
    "gaming stream'; 'routine temperature reading' is very different from "
    "'temperature exceeded fire safety threshold'. Judge the actual situation "
    "described, not surface-level word matches.\n\n"
    "The description may be phrased casually or in plain language, not "
    "necessarily as formal technical alert syntax -- do not lower your "
    "confidence just because the phrasing is informal or conversational. "
    "'Person got bit by a dog and did not get rabies vaccination' clearly "
    "describes a real medical emergency and should be analyzed with the same "
    "confidence as if it were phrased 'Health monitor alert: dog bite, rabies "
    "vaccination status unknown'. Reserve low confidence for cases where WHAT "
    "is happening is genuinely unclear (e.g. a single word with no situational "
    "context, like 'data' or 'update' on its own), not for clear situations "
    "that happen to be phrased informally."
)


class SemanticAnalysis(BaseModel):
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: float = Field(ge=0.0, le=1.0)
    consequence: float = Field(ge=0.0, le=1.0)
    latency_sensitivity: float = Field(ge=0.0, le=1.0)
    reliability_requirement: float = Field(ge=0.0, le=1.0)
    reason: str


def _call_gemini(client, text: str, model: str, timeout_seconds: float):
    from google.genai import types

    return client.models.generate_content(
        model=model,
        contents=f"Traffic description: '{text}'",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.1,
            seed=42,
            response_mime_type="application/json",
            response_schema=SemanticAnalysis,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        ),
    )


def analyze(text: str, client, model: str | None = None, timeout_seconds: float | None = None) -> dict | None:
    """Ask Gemini to semantically analyze `text`. Returns a plain dict of
    SemanticAnalysis fields, or None on any failure (bad key, timeout,
    network error, malformed/invalid response). Never raises.
    """
    model = model or Config.GEMINI_MODEL
    timeout_seconds = timeout_seconds if timeout_seconds is not None else Config.GEMINI_TIMEOUT_SECONDS

    future = _EXECUTOR.submit(_call_gemini, client, text, model, timeout_seconds)
    try:
        # Belt-and-suspenders: the SDK's own http_options.timeout should
        # already bound the network call, but this wrapper-level timeout
        # guarantees this function never blocks the request thread
        # indefinitely regardless of SDK behavior.
        response = future.result(timeout=timeout_seconds + 1.0)
    except concurrent.futures.TimeoutError:
        logger.warning("Gemini call timed out after %.1fs", timeout_seconds)
        future.cancel()
        return None
    except Exception:
        logger.exception("Gemini call failed")
        return None

    try:
        parsed = response.parsed
        if not isinstance(parsed, SemanticAnalysis):
            # response_schema didn't yield a validated instance (e.g.
            # malformed JSON, missing fields) -- fall back to manual
            # parsing/validation as a last resort.
            import json

            parsed = SemanticAnalysis.model_validate(json.loads(response.text))
    except Exception:
        logger.exception("Gemini returned an invalid/unparseable response")
        return None

    return parsed.model_dump()
