"""Tests for probability calculation functions."""

import pytest

from mctrend.scoring.probability import (
    compute_confidence,
    compute_net_potential,
    compute_p_failure,
    compute_p_potential,
)


class TestPPotential:
    def test_default_weights_sum(self):
        """All dimensions at 1.0 should yield exactly 1.0 (weights sum to 1)."""
        result = compute_p_potential(
            narrative_relevance=1.0, og_score=1.0, momentum_quality=1.0,
            attention_strength=1.0, timing_quality=1.0,
        )
        assert abs(result - 1.0) < 1e-6

    def test_all_zeros(self):
        result = compute_p_potential(
            narrative_relevance=0.0, og_score=0.0, momentum_quality=0.0,
            attention_strength=0.0, timing_quality=0.0,
        )
        assert result == 0.0

    def test_weighted_contribution(self):
        """Higher-weighted dimension should have more impact."""
        # NR has weight 0.25, TQ has weight 0.15
        result_nr = compute_p_potential(
            narrative_relevance=1.0, og_score=0.0, momentum_quality=0.0,
            attention_strength=0.0, timing_quality=0.0,
        )
        result_tq = compute_p_potential(
            narrative_relevance=0.0, og_score=0.0, momentum_quality=0.0,
            attention_strength=0.0, timing_quality=1.0,
        )
        assert result_nr > result_tq  # NR (0.25) > TQ (0.15)

    def test_custom_weights(self):
        """Custom weights should override defaults."""
        result = compute_p_potential(
            narrative_relevance=1.0, og_score=0.0, momentum_quality=0.0,
            attention_strength=0.0, timing_quality=0.0,
            weights={"nr": 1.0, "og": 0.0, "mq": 0.0, "as": 0.0, "tq": 0.0},
        )
        assert abs(result - 1.0) < 1e-6

    def test_result_clamped(self):
        result = compute_p_potential(
            narrative_relevance=0.5, og_score=0.5, momentum_quality=0.5,
            attention_strength=0.5, timing_quality=0.5,
        )
        assert 0.0 <= result <= 1.0


class TestPFailure:
    def test_all_risk_free(self):
        """No rug risk, perfect momentum/timing/OG, low liquidity risk => near 0."""
        result = compute_p_failure(
            rug_risk=0.0, momentum_quality=1.0, timing_quality=1.0,
            og_score=1.0, liquidity_risk=0.0,
        )
        assert result == 0.0

    def test_all_maximum_risk(self):
        """Max rug risk, zero momentum/timing/OG, max liquidity risk => near 1."""
        result = compute_p_failure(
            rug_risk=1.0, momentum_quality=0.0, timing_quality=0.0,
            og_score=0.0, liquidity_risk=1.0,
        )
        assert abs(result - 1.0) < 1e-6

    def test_derived_risks(self):
        """Fakeout = 1-mq, exhaustion = 1-tq, copycat = 1-og."""
        # If MQ=0.8, fakeout_risk=0.2; TQ=0.7, exhaust=0.3; OG=0.9, copycat=0.1
        result = compute_p_failure(
            rug_risk=0.0, momentum_quality=0.8, timing_quality=0.7,
            og_score=0.9, liquidity_risk=0.0,
        )
        # Only derived risks contribute: 0.2*0.25 + 0.3*0.20 + 0.1*0.10 = 0.12
        assert abs(result - 0.12) < 0.01

    def test_rug_risk_dominates(self):
        """High rug risk should strongly influence p_failure."""
        low_rug = compute_p_failure(
            rug_risk=0.1, momentum_quality=0.5, timing_quality=0.5,
            og_score=0.5, liquidity_risk=0.5,
        )
        high_rug = compute_p_failure(
            rug_risk=0.9, momentum_quality=0.5, timing_quality=0.5,
            og_score=0.5, liquidity_risk=0.5,
        )
        assert high_rug > low_rug
        # Rug risk has weight 0.35, so difference should be ~0.28
        assert abs(high_rug - low_rug - 0.28) < 0.01


class TestNetPotential:
    def test_formula(self):
        """net_potential = p_potential * (1 - p_failure)."""
        result = compute_net_potential(0.8, 0.3)
        assert abs(result - 0.56) < 1e-6

    def test_zero_failure(self):
        result = compute_net_potential(0.7, 0.0)
        assert abs(result - 0.7) < 1e-6

    def test_full_failure(self):
        result = compute_net_potential(0.9, 1.0)
        assert result == 0.0

    def test_clamped(self):
        result = compute_net_potential(0.5, 0.5)
        assert 0.0 <= result <= 1.0


class TestConfidence:
    def test_full_data(self):
        """Max sources, max diversity, complete data, no ambiguity => ~1.0."""
        result = compute_confidence(
            source_count=5, source_diversity=4,
            data_completeness=1.0, ambiguity_score=0.0,
        )
        assert abs(result - 1.0) < 1e-6

    def test_minimal_data(self):
        """Minimal sources, no diversity, incomplete, highly ambiguous => low."""
        result = compute_confidence(
            source_count=1, source_diversity=1,
            data_completeness=0.2, ambiguity_score=0.9,
        )
        assert result < 0.35

    def test_ambiguity_reduces_confidence(self):
        high_ambiguity = compute_confidence(
            source_count=3, source_diversity=2,
            data_completeness=0.8, ambiguity_score=0.9,
        )
        low_ambiguity = compute_confidence(
            source_count=3, source_diversity=2,
            data_completeness=0.8, ambiguity_score=0.1,
        )
        assert low_ambiguity > high_ambiguity

    def test_source_count_caps(self):
        """Sources beyond max_sources don't increase score further."""
        at_max = compute_confidence(
            source_count=5, source_diversity=2,
            data_completeness=0.8, ambiguity_score=0.5,
        )
        over_max = compute_confidence(
            source_count=20, source_diversity=2,
            data_completeness=0.8, ambiguity_score=0.5,
        )
        assert abs(at_max - over_max) < 1e-6
