"""Unit tests for the 4-signal confidence scorer."""
import pytest

from backend.services.confidence_scorer import (
    compute_confidence,
    compute_confidence_explanation,
    should_route_to_review,
    validate_cross_field,
    validate_format,
)


class TestComputeConfidence:
    def test_all_perfect(self):
        score = compute_confidence(1.0, 1.0, True, True)
        assert score == 1.0

    def test_all_worst(self):
        score = compute_confidence(0.0, 0.0, False, False)
        # 0.50*0 + 0.20*0 + 0.20*0.3 + 0.10*0.2 = 0.08
        assert score == pytest.approx(0.08, abs=0.001)

    def test_weights_sum_to_one(self):
        # With all signals at 1.0 and both booleans True, score should be 1.0
        score = compute_confidence(1.0, 1.0, True, True)
        assert score == pytest.approx(1.0)

    def test_typical_high_confidence(self):
        score = compute_confidence(0.95, 0.90, True, True)
        expected = 0.50 * 0.95 + 0.20 * 0.90 + 0.20 * 1.0 + 0.10 * 1.0
        assert score == pytest.approx(expected, abs=0.001)

    def test_format_failure_reduces_score(self):
        with_valid = compute_confidence(0.9, 0.9, True, True)
        without_valid = compute_confidence(0.9, 0.9, False, True)
        assert with_valid > without_valid

    def test_clamps_input(self):
        score = compute_confidence(1.5, -0.3, True, True)
        expected = 0.50 * 1.0 + 0.20 * 0.0 + 0.20 * 1.0 + 0.10 * 1.0
        assert score == pytest.approx(expected, abs=0.001)


class TestConfidenceExplanation:
    def test_returns_all_signals(self):
        result = compute_confidence_explanation(0.9, 0.8, True, True)
        assert "final_score" in result
        assert "signals" in result
        assert len(result["signals"]) == 4

    def test_final_score_matches_compute(self):
        result = compute_confidence_explanation(0.85, 0.75, False, True)
        direct = compute_confidence(0.85, 0.75, False, True)
        assert result["final_score"] == direct


class TestValidateFormat:
    def test_valid_date(self):
        assert validate_format("effective_date", "2024-01-15") is True

    def test_invalid_date(self):
        assert validate_format("effective_date", "Jan 15 2024") is False

    def test_valid_npi(self):
        assert validate_format("npi", "1234567890") is True

    def test_invalid_npi(self):
        assert validate_format("npi", "12345") is False

    def test_valid_currency(self):
        assert validate_format("capitation_rate", "$142.75") is True

    def test_empty_value_invalid(self):
        assert validate_format("any_field", "") is False

    def test_none_value_invalid(self):
        assert validate_format("any_field", None) is False

    def test_generic_nonempty_valid(self):
        assert validate_format("contract_type", "Provider Agreement") is True


class TestValidateCrossField:
    def test_effective_before_expiration(self):
        result = {"effective_date": "2024-01-01", "expiration_date": "2025-12-31"}
        assert validate_cross_field("effective_date", "2024-01-01", result) is True

    def test_effective_after_expiration(self):
        result = {"effective_date": "2026-01-01", "expiration_date": "2025-12-31"}
        assert validate_cross_field("effective_date", "2026-01-01", result) is False

    def test_positive_pmpm(self):
        assert validate_cross_field("capitation_pmpm", "142.75", {}) is True

    def test_negative_pmpm(self):
        assert validate_cross_field("capitation_pmpm", "-5.00", {}) is False

    def test_nonempty_parties(self):
        assert validate_cross_field("parties", [{"name": "A"}], {}) is True

    def test_empty_parties(self):
        assert validate_cross_field("parties", [], {}) is False

    def test_positive_term_months(self):
        assert validate_cross_field("term_months", 24, {}) is True

    def test_zero_term_months(self):
        assert validate_cross_field("term_months", 0, {}) is False


class TestReviewRouting:
    def test_critical_always_routes(self):
        thresholds = {"critical_financial": {"always_review": True}}
        assert should_route_to_review("drg_terms", "critical_financial", 0.99, thresholds) is True

    def test_low_confidence_routes(self):
        thresholds = {"important_structural": {"auto_approve_threshold": 0.92}}
        assert should_route_to_review("effective_date", "important_structural", 0.80, thresholds) is True

    def test_high_confidence_auto_approves(self):
        thresholds = {"important_structural": {"auto_approve_threshold": 0.92}}
        assert should_route_to_review("effective_date", "important_structural", 0.95, thresholds) is False

    def test_unknown_class_uses_default_threshold(self):
        assert should_route_to_review("unknown", "unknown", 0.90, {}) is True
