"""Tests for individual dimension scoring functions."""

import pytest

from mctrend.scoring.dimensions import (
    clip,
    score_attention_strength,
    score_momentum_quality,
    score_narrative_relevance,
    score_og_likelihood,
    score_rug_risk,
    score_timing_quality,
)


# ---------------------------------------------------------------------------
# clip()
# ---------------------------------------------------------------------------

class TestClip:
    def test_within_range(self):
        assert clip(0.5) == 0.5

    def test_below_range(self):
        assert clip(-0.5) == 0.0

    def test_above_range(self):
        assert clip(1.5) == 1.0

    def test_at_boundaries(self):
        assert clip(0.0) == 0.0
        assert clip(1.0) == 1.0

    def test_custom_range(self):
        assert clip(5, lo=2, hi=8) == 5
        assert clip(1, lo=2, hi=8) == 2
        assert clip(10, lo=2, hi=8) == 8


# ---------------------------------------------------------------------------
# Narrative Relevance
# ---------------------------------------------------------------------------

class TestNarrativeRelevance:
    def test_perfect_match_fresh_multi_source(self):
        """Exact match, brand-new narrative, 4 source types => high score."""
        score, signals = score_narrative_relevance(
            match_confidence=1.0,
            narrative_age_hours=0.0,
            source_type_count=4,
        )
        assert score > 0.85
        assert "exact_anchor_match" in signals
        assert "narrative_age_fresh" in signals

    def test_weak_match_old_single_source(self):
        """Weak match, old narrative, single source => low score."""
        score, signals = score_narrative_relevance(
            match_confidence=0.2,
            narrative_age_hours=10.0,
            source_type_count=1,
        )
        assert score < 0.30
        assert "single_source_narrative" in signals
        assert "narrative_age_decaying" in signals

    def test_score_bounded_0_1(self):
        score, _ = score_narrative_relevance(
            match_confidence=0.0, narrative_age_hours=100.0, source_type_count=0
        )
        assert 0.0 <= score <= 1.0

    def test_decay_hours_configurable(self):
        """Faster decay => lower score for same age."""
        score_fast, _ = score_narrative_relevance(
            match_confidence=0.8, narrative_age_hours=3.0,
            source_type_count=2, decay_hours=3.0,
        )
        score_slow, _ = score_narrative_relevance(
            match_confidence=0.8, narrative_age_hours=3.0,
            source_type_count=2, decay_hours=12.0,
        )
        assert score_slow > score_fast

    def test_multi_source_signal(self):
        _, signals = score_narrative_relevance(
            match_confidence=0.5, narrative_age_hours=1.0, source_type_count=3,
        )
        assert "multi_source_narrative" in signals


# ---------------------------------------------------------------------------
# OG Likelihood
# ---------------------------------------------------------------------------

class TestOGLikelihood:
    def test_clear_og(self):
        """First token, exact name, cross-source confirmed => high OG score."""
        score, signals = score_og_likelihood(
            temporal_score=1.0,
            name_precision=1.0,
            cross_source_mentions=5,
            deployer_score=0.8,
        )
        assert score > 0.85
        assert "first_in_namespace" in signals
        assert "exact_name_match" in signals
        assert "cross_source_confirmed" in signals

    def test_copycat(self):
        """Late token, imprecise name, no cross-source => low OG."""
        score, signals = score_og_likelihood(
            temporal_score=0.1,
            name_precision=0.3,
            cross_source_mentions=0,
            deployer_score=0.2,
        )
        assert score < 0.35
        assert "copycat_likely" in signals

    def test_custom_weights(self):
        """Custom weights should change the result."""
        score_default, _ = score_og_likelihood(
            temporal_score=1.0, name_precision=0.0,
            cross_source_mentions=0, deployer_score=0.0,
        )
        score_custom, _ = score_og_likelihood(
            temporal_score=1.0, name_precision=0.0,
            cross_source_mentions=0, deployer_score=0.0,
            weights={"temporal": 0.80, "name_precision": 0.10,
                     "cross_source": 0.05, "deployer": 0.05},
        )
        assert score_custom > score_default

    def test_score_bounded(self):
        score, _ = score_og_likelihood(
            temporal_score=0.0, name_precision=0.0,
            cross_source_mentions=0, deployer_score=0.0,
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Rug Risk
# ---------------------------------------------------------------------------

class TestRugRisk:
    def test_all_high_risk(self):
        """All sub-categories at maximum risk => very high rug score."""
        score, signals = score_rug_risk(
            deployer_risk=0.95,
            concentration_risk=0.95,
            clustering_risk=0.95,
            liquidity_risk=0.95,
            contract_risk=0.95,
        )
        assert score > 0.90
        assert "CRITICAL_RUG_RISK" in signals

    def test_all_low_risk(self):
        """All sub-categories low risk => low rug score."""
        score, signals = score_rug_risk(
            deployer_risk=0.10,
            concentration_risk=0.10,
            clustering_risk=0.10,
            liquidity_risk=0.10,
            contract_risk=0.10,
        )
        assert score < 0.15
        assert "CRITICAL_RUG_RISK" not in signals

    def test_missing_data_uses_conservative_defaults(self):
        """All None inputs => conservative defaults applied, flagged."""
        score, signals = score_rug_risk(
            deployer_risk=None,
            concentration_risk=None,
            clustering_risk=None,
            liquidity_risk=None,
            contract_risk=None,
        )
        # Conservative defaults are all ~0.50-0.60, so weighted score should be moderate
        assert 0.40 <= score <= 0.65
        assert "missing_deployer_data" in signals
        assert "missing_concentration_data" in signals
        assert "missing_clustering_data" in signals
        assert "missing_liquidity_data" in signals
        assert "missing_contract_data" in signals

    def test_custom_defaults(self):
        """Custom conservative defaults override the built-in ones."""
        score_default, _ = score_rug_risk(
            deployer_risk=None, concentration_risk=None,
            clustering_risk=None, liquidity_risk=None, contract_risk=None,
        )
        score_high, _ = score_rug_risk(
            deployer_risk=None, concentration_risk=None,
            clustering_risk=None, liquidity_risk=None, contract_risk=None,
            defaults={
                "deployer": 0.90, "concentration": 0.90,
                "clustering": 0.90, "liquidity": 0.90, "contract": 0.90,
            },
        )
        assert score_high > score_default

    def test_known_bad_deployer_signal(self):
        _, signals = score_rug_risk(
            deployer_risk=0.90, concentration_risk=0.3,
            clustering_risk=0.3, liquidity_risk=0.3, contract_risk=0.3,
        )
        assert "KNOWN_BAD_DEPLOYER" in signals

    def test_partial_missing_data(self):
        """Some data available, some missing => only missing flagged."""
        score, signals = score_rug_risk(
            deployer_risk=0.20,
            concentration_risk=None,
            clustering_risk=0.30,
            liquidity_risk=None,
            contract_risk=0.15,
        )
        assert "missing_deployer_data" not in signals
        assert "missing_concentration_data" in signals
        assert "missing_liquidity_data" in signals
        assert "missing_clustering_data" not in signals


# ---------------------------------------------------------------------------
# Momentum Quality
# ---------------------------------------------------------------------------

class TestMomentumQuality:
    def test_organic_momentum(self):
        score, signals = score_momentum_quality(
            volume_pattern=0.85, trade_diversity=0.80,
            social_chain_alignment=0.75, holder_growth_quality=0.80,
        )
        assert score > 0.70
        assert "organic_momentum" in signals

    def test_suspicious_momentum(self):
        score, signals = score_momentum_quality(
            volume_pattern=0.10, trade_diversity=0.15,
            social_chain_alignment=0.10, holder_growth_quality=0.15,
        )
        assert score < 0.35
        assert "SUSPICIOUS_VOLUME" in signals
        assert "WASH_TRADE_PATTERN" in signals

    def test_all_missing_uses_defaults(self):
        score, signals = score_momentum_quality(
            volume_pattern=None, trade_diversity=None,
            social_chain_alignment=None, holder_growth_quality=None,
        )
        # All defaults are 0.5 => 0.5 * (0.3+0.3+0.2+0.2) = 0.5
        assert abs(score - 0.5) < 0.01
        assert "missing_momentum_data" in signals
        # Should be deduplicated
        assert signals.count("missing_momentum_data") == 1


# ---------------------------------------------------------------------------
# Attention Strength
# ---------------------------------------------------------------------------

class TestAttentionStrength:
    def test_strong_attention(self):
        score, signals = score_attention_strength(
            search_magnitude=0.9, source_breadth=0.9, narrative_velocity=0.8,
        )
        assert score > 0.75
        assert "strong_multi_source_attention" in signals

    def test_weak_attention(self):
        score, signals = score_attention_strength(
            search_magnitude=0.1, source_breadth=0.1, narrative_velocity=0.1,
        )
        assert score < 0.30
        assert "weak_attention" in signals

    def test_missing_defaults(self):
        score, signals = score_attention_strength(
            search_magnitude=None, source_breadth=None, narrative_velocity=None,
        )
        assert 0.0 <= score <= 1.0
        assert "missing_attention_data" in signals
        # Deduplicated
        assert signals.count("missing_attention_data") == 1


# ---------------------------------------------------------------------------
# Timing Quality
# ---------------------------------------------------------------------------

class TestTimingQuality:
    def test_early_lifecycle(self):
        score, signals = score_timing_quality(
            lifecycle_score=0.95, acceleration_score=0.8, saturation_score=0.9,
        )
        assert score > 0.80
        assert "early_lifecycle" in signals

    def test_late_timing(self):
        score, signals = score_timing_quality(
            lifecycle_score=0.10, acceleration_score=0.15, saturation_score=0.10,
        )
        assert score < 0.30
        assert "TIMING_LATE" in signals

    def test_score_bounded(self):
        score, _ = score_timing_quality(
            lifecycle_score=0.0, acceleration_score=0.0, saturation_score=0.0,
        )
        assert score == 0.0
        score2, _ = score_timing_quality(
            lifecycle_score=1.0, acceleration_score=1.0, saturation_score=1.0,
        )
        assert score2 == 1.0
