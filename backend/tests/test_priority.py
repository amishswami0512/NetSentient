"""Tests for the deterministic priority engine (services/priority_service.py)."""
import pytest

from config import CATEGORY_PRIORITY_BOUNDS, LOW_CONFIDENCE_THRESHOLD
from services import priority_service

MAX_FACTORS = {
    "urgency": 1.0,
    "consequence": 1.0,
    "latency_sensitivity": 1.0,
    "reliability_requirement": 1.0,
}
MIN_FACTORS = {
    "urgency": 0.0,
    "consequence": 0.0,
    "latency_sensitivity": 0.0,
    "reliability_requirement": 0.0,
}


def test_raw_priority_is_ten_when_all_factors_are_maximal():
    assert priority_service.compute_raw_priority(MAX_FACTORS) == 10.0


def test_raw_priority_is_zero_when_all_factors_are_minimal():
    assert priority_service.compute_raw_priority(MIN_FACTORS) == 0.0


def test_raw_priority_intermediate_value_matches_weighted_formula():
    factors = {
        "urgency": 0.92,
        "consequence": 0.95,
        "latency_sensitivity": 0.88,
        "reliability_requirement": 0.93,
    }
    expected = 10 * (0.35 * 0.92 + 0.30 * 0.95 + 0.20 * 0.88 + 0.15 * 0.93)
    assert priority_service.compute_raw_priority(factors) == pytest.approx(expected)


def test_category_bounds_clamp_low_stakes_category_even_with_maximal_factors():
    # Background traffic should never reach a top-tier priority, even if
    # the semantic factors alone would suggest it.
    raw = priority_service.compute_raw_priority(MAX_FACTORS)
    clamped = priority_service.apply_category_bounds(raw, "background")
    lo, hi = CATEGORY_PRIORITY_BOUNDS["background"]
    assert clamped == hi
    assert clamped < 10.0


def test_category_bounds_clamp_safety_critical_category_even_with_minimal_factors():
    # Emergency-classified traffic should never fall below its safety floor.
    raw = priority_service.compute_raw_priority(MIN_FACTORS)
    clamped = priority_service.apply_category_bounds(raw, "emergency")
    lo, _hi = CATEGORY_PRIORITY_BOUNDS["emergency"]
    assert clamped == lo
    assert clamped > 0.0


def test_bounds_do_not_clamp_values_already_within_range():
    factors = {
        "urgency": 0.65,
        "consequence": 0.70,
        "latency_sensitivity": 0.55,
        "reliability_requirement": 0.75,
    }
    raw = priority_service.compute_raw_priority(factors)
    clamped = priority_service.apply_category_bounds(raw, "critical_sensor")
    assert clamped == raw  # well within critical_sensor's (1.0, 10.0) bounds


def test_score_high_confidence_uses_full_priority():
    result = priority_service.score(
        "critical_sensor",
        confidence=0.95,
        factors={
            "urgency": 0.92,
            "consequence": 0.95,
            "latency_sensitivity": 0.88,
            "reliability_requirement": 0.93,
        },
    )
    assert result["low_confidence"] is False
    assert result["priority"] > 8.0


def test_score_low_confidence_is_flagged_and_dampened():
    high_factors = {
        "urgency": 0.99,
        "consequence": 0.99,
        "latency_sensitivity": 0.99,
        "reliability_requirement": 0.99,
    }
    confident = priority_service.score("critical_sensor", confidence=0.9, factors=high_factors)
    uncertain = priority_service.score(
        "critical_sensor", confidence=LOW_CONFIDENCE_THRESHOLD - 0.05, factors=high_factors
    )

    assert uncertain["low_confidence"] is True
    assert confident["low_confidence"] is False
    # Same factors, but the uncertain classification must never exceed
    # the confident one -- confidence dampens, it never boosts.
    assert uncertain["priority"] < confident["priority"]


def test_low_confidence_never_produces_top_tier_priority_for_any_category():
    high_factors = {
        "urgency": 1.0,
        "consequence": 1.0,
        "latency_sensitivity": 1.0,
        "reliability_requirement": 1.0,
    }
    for category, (lo, hi) in CATEGORY_PRIORITY_BOUNDS.items():
        result = priority_service.score(category, confidence=0.1, factors=high_factors)
        assert result["low_confidence"] is True
        assert result["priority"] <= lo + (hi - lo) * 0.5 + 1e-9


def test_score_is_deterministic():
    factors = {
        "urgency": 0.4,
        "consequence": 0.4,
        "latency_sensitivity": 0.4,
        "reliability_requirement": 0.4,
    }
    first = priority_service.score("video", 0.8, factors)
    second = priority_service.score("video", 0.8, factors)
    assert first == second
