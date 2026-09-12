"""Deterministic priority engine.

Converts the four semantic factors (from services/semantic_service.py,
either real Gemini analysis or the deterministic fallback) into a
final 0-10 priority. Pure arithmetic -- no network calls, no Gemini,
no randomness. Same inputs always produce the same output.
"""
import math
from typing import Any

from config import CATEGORY_PRIORITY_BOUNDS, LOW_CONFIDENCE_THRESHOLD, PRIORITY_WEIGHTS


def compute_raw_priority(factors: dict[str, float]) -> float:
    """Weighted sum of the four semantic factors, scaled to 0-10.

    This is the transparent formula from config.PRIORITY_WEIGHTS, with
    no category-based clamping applied yet -- see apply_category_bounds.
    Rounded to 6 decimal places to absorb float summation noise (e.g.
    0.35+0.30+0.20+0.15 landing on 0.9999999999999998 instead of exactly
    1.0) -- otherwise all-maximal factors could yield 9.999999999999998
    instead of the exact 10 the formula is meant to produce.
    """
    weighted = sum(PRIORITY_WEIGHTS[key] * factors[key] for key in PRIORITY_WEIGHTS)
    return round(10.0 * weighted, 6)


def apply_category_bounds(priority: float, category: str) -> float:
    """Clamp into the category's safety bound range (config.CATEGORY_PRIORITY_BOUNDS).

    A guardrail, not the primary mechanism: within its bounds, the
    semantic factors still fully determine where a given item lands.
    """
    lo, hi = CATEGORY_PRIORITY_BOUNDS[category]
    return max(lo, min(hi, priority))


def score(category: str, confidence: float, factors: dict[str, float]) -> dict[str, Any]:
    """Compute the final priority for a semantic analysis result.

    Returns {"priority": float, "low_confidence": bool}.

    Confidence ("how certain is the classification") is never
    multiplied into priority ("how important is this traffic") -- they
    measure different things. Instead, a below-threshold confidence
    dampens priority conservatively: it's capped at the midpoint of
    whatever category's bound range it was classified into, so an
    uncertain guess can never reach the top of that tier. It is never
    bumped up to emergency-level priority just because the guess
    happened to be "emergency".
    """
    raw = compute_raw_priority(factors)
    bounded = apply_category_bounds(raw, category)

    low_confidence = confidence < LOW_CONFIDENCE_THRESHOLD
    if low_confidence:
        lo, hi = CATEGORY_PRIORITY_BOUNDS[category]
        conservative_cap = lo + (hi - lo) * 0.5
        # Floor to 1 decimal so the *displayed* (rounded) priority below
        # can never round back up past the intended cap (e.g. a raw cap
        # of 8.75 must never surface as 8.8).
        conservative_cap = math.floor(conservative_cap * 10) / 10
        bounded = min(bounded, conservative_cap)

    return {
        "priority": round(bounded, 1),
        "low_confidence": low_confidence,
    }
