"""The classifier's narrative-state gates against the lifecycle the pipeline uses.

The narrative lifecycle is WEAK -> EMERGING -> RISING -> TRENDING -> FADING -> DEAD
(``mctrend.narrative.intelligence``), and the pipeline only lets a token alert
when its narrative is RISING or TRENDING (``ALERT_ELIGIBLE_STATES``).  The
classifier's gates were still written in the earlier names (EMERGING, PEAKING,
DECLINING), so for every narrative that could alert, the two top tiers and
take_profit_watch were out of reach.  These tests pin the two together.
"""

import pytest

from mctrend.alerting.classifier import classify_alert, explain_rejection
from mctrend.narrative.intelligence import ALERT_ELIGIBLE_STATES

# Comfortably inside each tier's thresholds (docs/alerting/alert-types.md).
POSSIBLE_ENTRY = dict(net_potential=0.70, p_potential=0.85, p_failure=0.15, confidence=0.80)
HIGH_POTENTIAL = dict(net_potential=0.50, p_potential=0.75, p_failure=0.40, confidence=0.60)
COOLED_OFF = dict(net_potential=0.40, p_potential=0.65, p_failure=0.40, confidence=0.60)


class TestTopTiersAreReachable:
    @pytest.mark.parametrize("state", sorted(ALERT_ELIGIBLE_STATES))
    def test_possible_entry_for_every_alert_eligible_state(self, state):
        assert classify_alert(**POSSIBLE_ENTRY, risk_flags=[], narrative_state=state) == (
            "possible_entry"
        )

    @pytest.mark.parametrize("state", sorted(ALERT_ELIGIBLE_STATES))
    def test_high_potential_watch_for_every_alert_eligible_state(self, state):
        assert classify_alert(**HIGH_POTENTIAL, risk_flags=[], narrative_state=state) == (
            "high_potential_watch"
        )

    @pytest.mark.parametrize("state", ["EMERGING", "PEAKING"])
    def test_earlier_state_names_still_count(self, state):
        """Rows written before the lifecycle change keep their meaning."""
        assert classify_alert(**POSSIBLE_ENTRY, risk_flags=[], narrative_state=state) == (
            "possible_entry"
        )

    @pytest.mark.parametrize("state", ["WEAK", "FADING", "DEAD", "DECLINING"])
    def test_states_that_are_not_active_stay_below_the_top_tiers(self, state):
        result = classify_alert(**POSSIBLE_ENTRY, risk_flags=[], narrative_state=state)
        assert result not in {"possible_entry", "high_potential_watch"}

    def test_state_is_compared_without_case(self):
        assert classify_alert(**POSSIBLE_ENTRY, risk_flags=[], narrative_state="trending") == (
            "possible_entry"
        )

    def test_a_blocking_flag_still_caps_a_trending_narrative(self):
        result = classify_alert(
            **POSSIBLE_ENTRY, risk_flags=["CRITICAL_RUG_RISK"], narrative_state="TRENDING"
        )
        assert result not in {"possible_entry", "high_potential_watch"}


class TestTakeProfitWatch:
    @pytest.mark.parametrize("state", ["TRENDING", "FADING", "PEAKING", "DECLINING"])
    def test_prior_high_tier_alert_at_or_past_the_peak(self, state):
        result = classify_alert(
            **COOLED_OFF,
            risk_flags=[],
            narrative_state=state,
            has_prior_alert=True,
            prior_alert_type="possible_entry",
        )
        assert result == "take_profit_watch"

    @pytest.mark.parametrize("state", ["EMERGING", "RISING"])
    def test_not_while_the_narrative_is_still_climbing(self, state):
        result = classify_alert(
            **COOLED_OFF,
            risk_flags=[],
            narrative_state=state,
            has_prior_alert=True,
            prior_alert_type="possible_entry",
        )
        assert result != "take_profit_watch"

    def test_not_without_a_prior_high_tier_alert(self):
        result = classify_alert(
            **COOLED_OFF,
            risk_flags=[],
            narrative_state="TRENDING",
            has_prior_alert=True,
            prior_alert_type="watch",
        )
        assert result != "take_profit_watch"


class TestExplainRejection:
    def _codes(self, state):
        reasons = explain_rejection(
            net_potential=0.20, p_potential=0.40, p_failure=0.50, confidence=0.40,
            risk_flags=[], narrative_state=state,
        )
        return {r["code"] for r in reasons}

    @pytest.mark.parametrize("state", sorted(ALERT_ELIGIBLE_STATES))
    def test_an_alert_eligible_state_is_not_reported_as_inactive(self, state):
        assert "narrative_state_not_active" not in self._codes(state)

    def test_a_fading_narrative_is_reported_as_inactive(self):
        assert "narrative_state_not_active" in self._codes("FADING")
