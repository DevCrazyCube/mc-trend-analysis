"""Tests for alert classification and state transitions."""

import pytest

from mctrend.alerting.classifier import AlertThresholds, classify_alert


class TestClassifyAlert:
    """Test alert classification rules from docs/alerting/alert-types.md."""

    def setup_method(self):
        self.thresholds = AlertThresholds()

    # ----- Discard -----

    def test_discard_known_bad_deployer(self):
        """Discard flag triggers immediate discard."""
        result = classify_alert(
            net_potential=0.80, p_potential=0.90, p_failure=0.10,
            confidence=0.90, risk_flags=["KNOWN_BAD_DEPLOYER"],
        )
        assert result == "discard"

    def test_discard_high_p_failure(self):
        """P_failure >= 0.80 => discard."""
        result = classify_alert(
            net_potential=0.50, p_potential=0.80, p_failure=0.80,
            confidence=0.70, risk_flags=[],
        )
        assert result == "discard"

    def test_discard_boundary_p_failure(self):
        """Boundary: p_failure exactly 0.80 => discard (conservative)."""
        result = classify_alert(
            net_potential=0.50, p_potential=0.80, p_failure=0.80,
            confidence=0.70, risk_flags=[],
        )
        assert result == "discard"

    def test_discard_low_net_potential(self):
        """net_potential < 0.10 => discard."""
        result = classify_alert(
            net_potential=0.05, p_potential=0.20, p_failure=0.50,
            confidence=0.70, risk_flags=[],
        )
        assert result == "discard"

    # ----- Exit Risk -----

    def test_exit_risk_with_prior_alert(self):
        """P_failure >= 0.65 + prior alert => exit_risk."""
        result = classify_alert(
            net_potential=0.40, p_potential=0.60, p_failure=0.65,
            confidence=0.60, risk_flags=[],
            has_prior_alert=True, prior_alert_type="possible_entry",
        )
        assert result == "exit_risk"

    def test_no_exit_risk_without_prior(self):
        """P_failure >= 0.65 but no prior alert => NOT exit_risk."""
        result = classify_alert(
            net_potential=0.40, p_potential=0.60, p_failure=0.65,
            confidence=0.60, risk_flags=[],
            has_prior_alert=False,
        )
        assert result != "exit_risk"

    # ----- Possible Entry -----

    def test_possible_entry(self):
        """Meets all criteria: high net, low failure, high confidence, active narrative."""
        result = classify_alert(
            net_potential=0.70, p_potential=0.85, p_failure=0.20,
            confidence=0.75, risk_flags=[],
            narrative_state="EMERGING",
        )
        assert result == "possible_entry"

    def test_possible_entry_boundary_net(self):
        """net_potential exactly 0.60 => meets (>=)."""
        result = classify_alert(
            net_potential=0.60, p_potential=0.80, p_failure=0.15,
            confidence=0.70, risk_flags=[],
            narrative_state="PEAKING",
        )
        assert result == "possible_entry"

    def test_possible_entry_blocked_by_p_failure_boundary(self):
        """p_failure exactly 0.30 => does NOT meet (< required, boundary fails)."""
        result = classify_alert(
            net_potential=0.70, p_potential=0.85, p_failure=0.30,
            confidence=0.75, risk_flags=[],
            narrative_state="EMERGING",
        )
        assert result != "possible_entry"

    def test_possible_entry_blocked_by_critical_risk(self):
        """Blocking flag caps at verify."""
        result = classify_alert(
            net_potential=0.70, p_potential=0.85, p_failure=0.20,
            confidence=0.75, risk_flags=["CRITICAL_RUG_RISK"],
            narrative_state="EMERGING",
        )
        assert result != "possible_entry"
        assert result != "high_potential_watch"

    def test_possible_entry_wrong_narrative_state(self):
        """Narrative DECLINING => cannot be possible_entry."""
        result = classify_alert(
            net_potential=0.70, p_potential=0.85, p_failure=0.20,
            confidence=0.75, risk_flags=[],
            narrative_state="DECLINING",
        )
        assert result != "possible_entry"

    # ----- High Potential Watch -----

    def test_high_potential_watch(self):
        result = classify_alert(
            net_potential=0.50, p_potential=0.70, p_failure=0.35,
            confidence=0.60, risk_flags=[],
            narrative_state="EMERGING",
        )
        assert result == "high_potential_watch"

    def test_hpw_boundary_confidence(self):
        """confidence exactly 0.55 => meets (>=)."""
        result = classify_alert(
            net_potential=0.50, p_potential=0.70, p_failure=0.35,
            confidence=0.55, risk_flags=[],
            narrative_state="EMERGING",
        )
        assert result == "high_potential_watch"

    def test_hpw_p_failure_boundary(self):
        """p_failure exactly 0.50 => does NOT meet (< required)."""
        result = classify_alert(
            net_potential=0.50, p_potential=0.70, p_failure=0.50,
            confidence=0.60, risk_flags=[],
            narrative_state="EMERGING",
        )
        assert result != "high_potential_watch"

    # ----- Take Profit Watch -----

    def test_take_profit_watch(self):
        """Prior high-tier alert + narrative PEAKING => take_profit_watch."""
        result = classify_alert(
            net_potential=0.40, p_potential=0.60, p_failure=0.40,
            confidence=0.50, risk_flags=[],
            narrative_state="PEAKING",
            has_prior_alert=True, prior_alert_type="possible_entry",
        )
        assert result == "take_profit_watch"

    def test_take_profit_requires_prior_high_tier(self):
        """Prior watch alert => NOT take_profit_watch."""
        result = classify_alert(
            net_potential=0.40, p_potential=0.60, p_failure=0.40,
            confidence=0.50, risk_flags=[],
            narrative_state="PEAKING",
            has_prior_alert=True, prior_alert_type="watch",
        )
        assert result != "take_profit_watch"

    # ----- Verify -----

    def test_verify(self):
        """Meaningful signal but low confidence => verify."""
        result = classify_alert(
            net_potential=0.40, p_potential=0.60, p_failure=0.40,
            confidence=0.40, risk_flags=[],
            narrative_state="EMERGING",
        )
        assert result == "verify"

    def test_verify_confidence_boundary(self):
        """confidence exactly 0.55 => does NOT trigger verify (needs < 0.55)."""
        # With confidence=0.55 and net=0.40, this would be hpw if confidence
        # threshold met, but hpw also needs net>=0.45. With net=0.40 it falls
        # through to verify check where confidence must be < 0.55.
        result = classify_alert(
            net_potential=0.40, p_potential=0.60, p_failure=0.40,
            confidence=0.55, risk_flags=[],
            narrative_state="DECLINING",
        )
        # confidence is not < 0.55, so not verify. Net < 0.45 so not hpw.
        # Net >= 0.25 so watch.
        assert result == "watch"

    # ----- Watch -----

    def test_watch(self):
        result = classify_alert(
            net_potential=0.30, p_potential=0.50, p_failure=0.50,
            confidence=0.60, risk_flags=[],
            narrative_state="DECLINING",
        )
        assert result == "watch"

    # ----- Ignore -----

    def test_ignore(self):
        """Below all thresholds => ignore."""
        result = classify_alert(
            net_potential=0.15, p_potential=0.30, p_failure=0.50,
            confidence=0.60, risk_flags=[],
        )
        assert result == "ignore"


class TestAlertStateTransitions:
    """Test how alert types change when scores shift."""

    def test_upgrade_watch_to_possible_entry(self):
        """Token improving from watch-level to possible_entry-level."""
        initial = classify_alert(
            net_potential=0.30, p_potential=0.50, p_failure=0.50,
            confidence=0.60, risk_flags=[], narrative_state="EMERGING",
        )
        assert initial == "watch"

        upgraded = classify_alert(
            net_potential=0.70, p_potential=0.85, p_failure=0.15,
            confidence=0.75, risk_flags=[], narrative_state="EMERGING",
        )
        assert upgraded == "possible_entry"

    def test_downgrade_on_risk_increase(self):
        """Good token develops high p_failure => exit_risk."""
        initial = classify_alert(
            net_potential=0.65, p_potential=0.80, p_failure=0.20,
            confidence=0.70, risk_flags=[], narrative_state="EMERGING",
        )
        assert initial == "possible_entry"

        degraded = classify_alert(
            net_potential=0.30, p_potential=0.60, p_failure=0.70,
            confidence=0.70, risk_flags=[],
            narrative_state="DECLINING",
            has_prior_alert=True, prior_alert_type="possible_entry",
        )
        assert degraded == "exit_risk"

    def test_narrative_death_removes_entry(self):
        """Narrative going DEAD should prevent possible_entry."""
        alive = classify_alert(
            net_potential=0.65, p_potential=0.80, p_failure=0.20,
            confidence=0.70, risk_flags=[], narrative_state="EMERGING",
        )
        assert alive == "possible_entry"

        dead = classify_alert(
            net_potential=0.65, p_potential=0.80, p_failure=0.20,
            confidence=0.70, risk_flags=[], narrative_state="DEAD",
        )
        assert dead != "possible_entry"
