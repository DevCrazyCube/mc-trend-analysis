"""Tests for the ScoringAggregator end-to-end scoring pipeline."""

import pytest

from mctrend.scoring.aggregator import ScoringAggregator


class TestScoringAggregator:
    def setup_method(self):
        self.scorer = ScoringAggregator(config=None)

    def _make_chain_data(self, **overrides):
        base = {
            "deployer_known_bad": False,
            "deployer_prior_deployments": 2,
            "mint_authority_status": "renounced",
            "freeze_authority_status": "renounced",
            "holder_count": 50,
            "top_5_holder_pct": 35.0,
            "top_10_holder_pct": 50.0,
            "liquidity_usd": 20_000,
            "liquidity_locked": True,
            "liquidity_lock_hours": 72,
            "liquidity_provider_count": 3,
            "volume_1h_usd": 10_000,
            "trade_count_1h": 100,
            "unique_traders_1h": 70,
        }
        base.update(overrides)
        return base

    def _make_narrative_data(self, **overrides):
        base = {
            "match_confidence": 0.90,
            "narrative_age_hours": 1.5,
            "source_type_count": 2,
            "state": "EMERGING",
            "attention_score": 0.7,
            "narrative_velocity": 0.5,
        }
        base.update(overrides)
        return base

    def _make_link_data(self, **overrides):
        base = {
            "og_rank": 1,
            "og_score": 0.8,
            "cross_source_mentions": 2,
            "match_method": "exact",
        }
        base.update(overrides)
        return base

    def test_full_scoring(self):
        """Complete scoring with good data produces expected structure."""
        result = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data=self._make_chain_data(),
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data=self._make_link_data(),
        )
        assert "score_id" in result
        assert "narrative_relevance" in result
        assert "og_score" in result
        assert "rug_risk" in result
        assert "momentum_quality" in result
        assert "attention_strength" in result
        assert "timing_quality" in result
        assert "p_potential" in result
        assert "p_failure" in result
        assert "net_potential" in result
        assert "confidence_score" in result
        assert isinstance(result["risk_flags"], list)
        assert isinstance(result["data_gaps"], list)

    def test_all_scores_bounded(self):
        """All dimension scores and probabilities should be in [0, 1]."""
        result = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data=self._make_chain_data(),
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data=self._make_link_data(),
        )
        for key in ["narrative_relevance", "og_score", "rug_risk",
                     "momentum_quality", "attention_strength", "timing_quality",
                     "p_potential", "p_failure", "net_potential", "confidence_score"]:
            assert 0.0 <= result[key] <= 1.0, f"{key}={result[key]} out of range"

    def test_net_potential_formula(self):
        """net_potential should equal p_potential * (1 - p_failure)."""
        result = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data=self._make_chain_data(),
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data=self._make_link_data(),
        )
        expected = result["p_potential"] * (1.0 - result["p_failure"])
        assert abs(result["net_potential"] - round(expected, 4)) < 0.001

    def test_missing_chain_data_produces_gaps(self):
        """Scoring with minimal chain data should produce data_gaps."""
        result = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data={},  # No chain data at all
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data=self._make_link_data(),
        )
        assert len(result["data_gaps"]) > 0

    def test_known_bad_deployer_raises_rug_risk(self):
        """Known bad deployer should significantly increase rug_risk."""
        good = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data=self._make_chain_data(deployer_known_bad=False),
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data=self._make_link_data(),
        )
        bad = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data=self._make_chain_data(deployer_known_bad=True),
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data=self._make_link_data(),
        )
        assert bad["rug_risk"] > good["rug_risk"]
        assert bad["p_failure"] > good["p_failure"]

    def test_none_og_score_handled(self):
        """None og_score in link_data should not crash."""
        result = self.scorer.score_token(
            token_id="tok1", narrative_id="nar1", link_id="link1",
            chain_data=self._make_chain_data(),
            narrative_data=self._make_narrative_data(),
            social_data=None,
            link_data={"og_rank": None, "og_score": None,
                       "cross_source_mentions": 0, "match_method": "exact"},
        )
        assert 0.0 <= result["og_score"] <= 1.0
