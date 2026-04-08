"""Unit tests for explain_rejection() in the alert classifier."""

import pytest

from mctrend.alerting.classifier import AlertThresholds, explain_rejection


def thresholds():
    return AlertThresholds()


def _codes(reasons):
    return [r["code"] for r in reasons]


# ---------------------------------------------------------------------------
# Base case: token clearly below watch — always has net_potential_below_watch
# ---------------------------------------------------------------------------

class TestBelowWatchThreshold:
    def test_below_watch_included(self):
        reasons = explain_rejection(
            net_potential=0.15, p_potential=0.30, p_failure=0.40,
            confidence=0.40, risk_flags=[], narrative_state="EMERGING",
        )
        assert "net_potential_below_watch" in _codes(reasons)

    def test_below_watch_gap_is_positive(self):
        reasons = explain_rejection(
            net_potential=0.20, p_potential=0.35, p_failure=0.40,
            confidence=0.40, risk_flags=[], narrative_state="EMERGING",
        )
        r = next(r for r in reasons if r["code"] == "net_potential_below_watch")
        assert r["gap"] > 0
        assert r["actual"] == 0.20
        assert r["threshold"] == 0.25

    def test_above_watch_no_below_watch_reason(self):
        # net_potential=0.30 is above watch (0.25); should NOT have below_watch reason
        reasons = explain_rejection(
            net_potential=0.30, p_potential=0.50, p_failure=0.60,
            confidence=0.40, risk_flags=[], narrative_state="EMERGING",
        )
        assert "net_potential_below_watch" not in _codes(reasons)

    def test_exactly_at_watch_threshold_not_flagged(self):
        # net_potential exactly at 0.25 is at threshold — NOT below it
        reasons = explain_rejection(
            net_potential=0.25, p_potential=0.50, p_failure=0.45,
            confidence=0.40, risk_flags=[], narrative_state="EMERGING",
        )
        assert "net_potential_below_watch" not in _codes(reasons)


# ---------------------------------------------------------------------------
# p_failure blocking higher tiers
# ---------------------------------------------------------------------------

class TestPFailureBlocking:
    def test_p_failure_too_high_for_hpw(self):
        # p_failure=0.55 >= 0.50 HPW threshold
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.55,
            confidence=0.60, risk_flags=[], narrative_state="EMERGING",
        )
        assert "p_failure_too_high_for_hpw" in _codes(reasons)

    def test_p_failure_below_hpw_threshold_not_flagged(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60, risk_flags=[], narrative_state="EMERGING",
        )
        assert "p_failure_too_high_for_hpw" not in _codes(reasons)

    def test_p_failure_too_high_for_pe(self):
        # p_failure=0.35 >= 0.30 PE threshold
        reasons = explain_rejection(
            net_potential=0.65, p_potential=0.80, p_failure=0.35,
            confidence=0.70, risk_flags=[], narrative_state="EMERGING",
        )
        assert "p_failure_too_high_for_pe" in _codes(reasons)

    def test_p_failure_below_pe_threshold_not_flagged(self):
        reasons = explain_rejection(
            net_potential=0.65, p_potential=0.80, p_failure=0.25,
            confidence=0.70, risk_flags=[], narrative_state="EMERGING",
        )
        assert "p_failure_too_high_for_pe" not in _codes(reasons)

    def test_gap_value_is_distance_above_threshold(self):
        # p_failure=0.55, threshold=0.50 → gap=0.05
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.55,
            confidence=0.60, risk_flags=[], narrative_state="EMERGING",
        )
        r = next(r for r in reasons if r["code"] == "p_failure_too_high_for_hpw")
        assert abs(r["gap"] - 0.05) < 0.001


# ---------------------------------------------------------------------------
# Confidence blocking higher tiers
# ---------------------------------------------------------------------------

class TestConfidenceFloors:
    def test_confidence_below_hpw_floor(self):
        # confidence=0.45 < 0.55 HPW floor
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.45, risk_flags=[], narrative_state="EMERGING",
        )
        assert "confidence_below_hpw_floor" in _codes(reasons)

    def test_confidence_at_hpw_floor_not_flagged(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.55, risk_flags=[], narrative_state="EMERGING",
        )
        assert "confidence_below_hpw_floor" not in _codes(reasons)

    def test_confidence_below_pe_floor(self):
        # confidence=0.60 < 0.65 PE floor
        reasons = explain_rejection(
            net_potential=0.65, p_potential=0.80, p_failure=0.25,
            confidence=0.60, risk_flags=[], narrative_state="EMERGING",
        )
        assert "confidence_below_pe_floor" in _codes(reasons)

    def test_confidence_gap_is_distance_below_floor(self):
        # confidence=0.45, floor=0.55 → gap=0.10
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.45, risk_flags=[], narrative_state="EMERGING",
        )
        r = next(r for r in reasons if r["code"] == "confidence_below_hpw_floor")
        assert abs(r["gap"] - 0.10) < 0.001


# ---------------------------------------------------------------------------
# Narrative state
# ---------------------------------------------------------------------------

class TestNarrativeState:
    def test_inactive_narrative_state_flagged(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60, risk_flags=[], narrative_state="DECLINING",
        )
        assert "narrative_state_not_active" in _codes(reasons)

    def test_active_emerging_not_flagged(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60, risk_flags=[], narrative_state="EMERGING",
        )
        assert "narrative_state_not_active" not in _codes(reasons)

    def test_active_peaking_not_flagged(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60, risk_flags=[], narrative_state="PEAKING",
        )
        assert "narrative_state_not_active" not in _codes(reasons)

    def test_dead_narrative_flagged(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60, risk_flags=[], narrative_state="DEAD",
        )
        assert "narrative_state_not_active" in _codes(reasons)


# ---------------------------------------------------------------------------
# Risk flags
# ---------------------------------------------------------------------------

class TestRiskFlags:
    def test_blocking_flag_reported(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60,
            risk_flags=["CRITICAL_RUG_RISK"],
            narrative_state="EMERGING",
        )
        assert "blocking_flag_caps_at_verify" in _codes(reasons)

    def test_discard_flag_reported(self):
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.40,
            confidence=0.60,
            risk_flags=["KNOWN_BAD_DEPLOYER"],
            narrative_state="EMERGING",
        )
        assert "discard_flag_active" in _codes(reasons)

    def test_no_flags_no_flag_reasons(self):
        reasons = explain_rejection(
            net_potential=0.20, p_potential=0.35, p_failure=0.40,
            confidence=0.40, risk_flags=[], narrative_state="EMERGING",
        )
        flag_codes = [r["code"] for r in reasons
                      if "flag" in r["code"]]
        assert flag_codes == []


# ---------------------------------------------------------------------------
# Data gaps → missing_required_enrichment
# ---------------------------------------------------------------------------

class TestDataGaps:
    def test_known_enrichment_gap_reported(self):
        reasons = explain_rejection(
            net_potential=0.20, p_potential=0.35, p_failure=0.50,
            confidence=0.35, risk_flags=[], narrative_state="EMERGING",
            data_gaps=["holder_concentration", "liquidity_data"],
        )
        enrichment_reasons = [r for r in reasons
                              if r["code"] == "missing_required_enrichment"]
        assert len(enrichment_reasons) == 2

    def test_unknown_gap_not_reported_as_enrichment(self):
        reasons = explain_rejection(
            net_potential=0.20, p_potential=0.35, p_failure=0.50,
            confidence=0.35, risk_flags=[], narrative_state="EMERGING",
            data_gaps=["some_random_gap"],
        )
        assert "missing_required_enrichment" not in _codes(reasons)

    def test_empty_data_gaps_no_enrichment_reason(self):
        reasons = explain_rejection(
            net_potential=0.20, p_potential=0.35, p_failure=0.50,
            confidence=0.35, risk_flags=[], narrative_state="EMERGING",
            data_gaps=[],
        )
        assert "missing_required_enrichment" not in _codes(reasons)


# ---------------------------------------------------------------------------
# Custom thresholds respected
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_custom_watch_min_changes_below_watch(self):
        custom = AlertThresholds(watch_min_net_potential=0.30)
        # 0.27 is above default 0.25 but below custom 0.30
        reasons = explain_rejection(
            net_potential=0.27, p_potential=0.45, p_failure=0.40,
            confidence=0.40, risk_flags=[], thresholds=custom,
        )
        assert "net_potential_below_watch" in _codes(reasons)

    def test_custom_hpw_p_failure_threshold(self):
        custom = AlertThresholds(hpw_max_p_failure=0.40)
        # p_failure=0.45 is below default 0.50 but above custom 0.40
        reasons = explain_rejection(
            net_potential=0.50, p_potential=0.70, p_failure=0.45,
            confidence=0.60, risk_flags=[], thresholds=custom,
        )
        assert "p_failure_too_high_for_hpw" in _codes(reasons)


# ---------------------------------------------------------------------------
# Result structure validation
# ---------------------------------------------------------------------------

class TestReasonStructure:
    def test_each_reason_has_required_keys(self):
        reasons = explain_rejection(
            net_potential=0.15, p_potential=0.30, p_failure=0.55,
            confidence=0.45, risk_flags=["CRITICAL_RUG_RISK"],
            narrative_state="DECLINING",
            data_gaps=["holder_concentration"],
        )
        assert len(reasons) > 0
        for r in reasons:
            assert "code" in r, f"Missing 'code' in {r}"
            assert "tier" in r, f"Missing 'tier' in {r}"
            assert "actual" in r, f"Missing 'actual' in {r}"
            assert "threshold" in r, f"Missing 'threshold' in {r}"
            assert "gap" in r, f"Missing 'gap' in {r}"

    def test_empty_when_all_thresholds_exceeded(self):
        # A perfectly-qualifying token (above all thresholds) produces no reasons
        # for net_potential / p_failure / confidence.  It would only have reasons
        # if it has risk flags or non-active narrative.
        reasons = explain_rejection(
            net_potential=0.70, p_potential=0.85, p_failure=0.15,
            confidence=0.75, risk_flags=[], narrative_state="EMERGING",
        )
        actionable = [r for r in reasons if r["code"] not in (
            "missing_required_enrichment", "discard_flag_active",
            "blocking_flag_caps_at_verify", "narrative_state_not_active",
        )]
        assert actionable == []
