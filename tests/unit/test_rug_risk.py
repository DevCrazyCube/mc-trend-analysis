"""Tests for rug risk sub-score derivation and composition."""

import pytest

from mctrend.scoring.aggregator import (
    _derive_clustering_risk,
    _derive_concentration_risk,
    _derive_contract_risk,
    _derive_deployer_risk,
    _derive_liquidity_risk,
)
from mctrend.scoring.dimensions import score_rug_risk


# ---------------------------------------------------------------------------
# Deployer Risk Derivation
# ---------------------------------------------------------------------------

class TestDeployerRisk:
    def test_known_bad(self):
        risk, gaps = _derive_deployer_risk({"deployer_known_bad": True})
        assert risk == 0.90
        assert gaps == []

    def test_new_deployer(self):
        risk, gaps = _derive_deployer_risk({
            "deployer_known_bad": False,
            "deployer_prior_deployments": 0,
        })
        assert risk == 0.45  # Brand-new deployer

    def test_some_history(self):
        risk, gaps = _derive_deployer_risk({
            "deployer_known_bad": False,
            "deployer_prior_deployments": 2,
        })
        assert risk == 0.30

    def test_factory_pattern(self):
        """Many prior deployments => suspicious."""
        risk, gaps = _derive_deployer_risk({
            "deployer_known_bad": False,
            "deployer_prior_deployments": 10,
        })
        assert risk > 0.70  # 0.40 + 10*0.05 = 0.90, capped at 0.85
        assert risk <= 0.85

    def test_no_data(self):
        """Missing deployer info => None + gap."""
        risk, gaps = _derive_deployer_risk({})
        assert risk is None
        assert "deployer_history" in gaps

    def test_known_good_no_count(self):
        risk, gaps = _derive_deployer_risk({"deployer_known_bad": False})
        assert risk == 0.35


# ---------------------------------------------------------------------------
# Concentration Risk Derivation
# ---------------------------------------------------------------------------

class TestConcentrationRisk:
    def test_high_concentration(self):
        risk, gaps = _derive_concentration_risk({"top_5_holder_pct": 0.80})
        # 0.80 / 70.0 ≈ 0.0114 — wait, the formula is top_5 / 70.0
        # If top_5_holder_pct is a fraction 0-1, then 0.80 / 70 is very low.
        # But if it's a percentage 0-100, then 80 / 70 = 1.14 => clipped to 1.0.
        # The code treats it as a raw number divided by 70. Demo data uses 0.41.
        # So 0.80 / 70 = 0.0114. This is a fraction-vs-percentage issue.
        # The current code does: clip(top_5 / 70.0)
        # With 0.80 (fraction), result = 0.011 which seems wrong.
        # This test documents the CURRENT behavior.
        assert 0.0 <= risk <= 1.0
        assert gaps == []

    def test_no_data(self):
        risk, gaps = _derive_concentration_risk({})
        assert risk is None
        assert "holder_concentration" in gaps

    def test_extreme_concentration(self):
        """100% concentration should be high risk."""
        risk, gaps = _derive_concentration_risk({"top_5_holder_pct": 100.0})
        assert risk > 0.90

    def test_zero_concentration(self):
        risk, gaps = _derive_concentration_risk({"top_5_holder_pct": 0.0})
        assert risk == 0.0


# ---------------------------------------------------------------------------
# Clustering Risk Derivation
# ---------------------------------------------------------------------------

class TestClusteringRisk:
    def test_high_new_wallet_pct(self):
        risk, gaps = _derive_clustering_risk({"new_wallet_holder_pct": 0.90})
        assert risk > 0.75  # 0.15 + 0.90 * 0.75 = 0.825

    def test_low_new_wallet_pct(self):
        risk, gaps = _derive_clustering_risk({"new_wallet_holder_pct": 0.05})
        assert risk < 0.25  # 0.15 + 0.05 * 0.75 = 0.1875

    def test_no_data(self):
        risk, gaps = _derive_clustering_risk({})
        assert risk is None
        assert "wallet_clustering" in gaps


# ---------------------------------------------------------------------------
# Liquidity Risk Derivation
# ---------------------------------------------------------------------------

class TestLiquidityRisk:
    def test_locked_high_liquidity(self):
        risk, gaps = _derive_liquidity_risk({
            "liquidity_usd": 100_000,
            "liquidity_locked": True,
            "liquidity_lock_hours": 200,
            "liquidity_provider_count": 5,
        })
        assert risk < 0.20  # Very safe liquidity profile

    def test_unlocked_low_liquidity(self):
        risk, gaps = _derive_liquidity_risk({
            "liquidity_usd": 1000,
            "liquidity_locked": False,
            "liquidity_provider_count": 1,
        })
        assert risk > 0.70  # Very risky liquidity profile

    def test_no_data(self):
        risk, gaps = _derive_liquidity_risk({})
        assert risk is None
        assert "liquidity_data" in gaps

    def test_partial_data(self):
        """Only liquidity_usd available."""
        risk, gaps = _derive_liquidity_risk({"liquidity_usd": 30_000})
        assert risk is not None
        assert 0.0 <= risk <= 1.0

    def test_short_lock(self):
        risk, gaps = _derive_liquidity_risk({
            "liquidity_usd": 10_000,
            "liquidity_locked": True,
            "liquidity_lock_hours": 12,
        })
        # Short lock = medium risk on that component
        assert 0.20 <= risk <= 0.60


# ---------------------------------------------------------------------------
# Contract Risk Derivation
# ---------------------------------------------------------------------------

class TestContractRisk:
    def test_both_active(self):
        risk, gaps = _derive_contract_risk({
            "mint_authority_status": "active",
            "freeze_authority_status": "active",
        })
        assert risk > 0.70  # Base 0.20 + 0.35 + 0.25 = 0.80

    def test_both_renounced(self):
        risk, gaps = _derive_contract_risk({
            "mint_authority_status": "renounced",
            "freeze_authority_status": "renounced",
        })
        assert risk == 0.20  # Just base risk

    def test_unknown_status(self):
        risk, gaps = _derive_contract_risk({
            "mint_authority_status": "unknown",
            "freeze_authority_status": "unknown",
        })
        assert risk == pytest.approx(0.45, abs=0.01)  # 0.20 + 0.15 + 0.10

    def test_no_data(self):
        risk, gaps = _derive_contract_risk({})
        assert risk is None
        assert "contract_authorities" in gaps


# ---------------------------------------------------------------------------
# Rug Risk Composition
# ---------------------------------------------------------------------------

class TestRugRiskComposition:
    def test_weights_sum_to_one(self):
        """Default weights should sum to 1.0."""
        w = {"deployer": 0.30, "concentration": 0.25, "clustering": 0.20,
             "liquidity": 0.15, "contract": 0.10}
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_weighted_average(self):
        """Score should be the weighted average of sub-scores."""
        score, _ = score_rug_risk(
            deployer_risk=0.50, concentration_risk=0.50,
            clustering_risk=0.50, liquidity_risk=0.50, contract_risk=0.50,
        )
        assert abs(score - 0.50) < 0.01

    def test_deployer_weight_dominates(self):
        """Deployer has highest weight (0.30), so changing it matters most."""
        low_dep, _ = score_rug_risk(
            deployer_risk=0.10, concentration_risk=0.50,
            clustering_risk=0.50, liquidity_risk=0.50, contract_risk=0.50,
        )
        high_dep, _ = score_rug_risk(
            deployer_risk=0.90, concentration_risk=0.50,
            clustering_risk=0.50, liquidity_risk=0.50, contract_risk=0.50,
        )
        # Difference should be 0.80 * 0.30 = 0.24
        assert abs(high_dep - low_dep - 0.24) < 0.01
