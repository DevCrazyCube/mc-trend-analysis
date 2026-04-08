"""Tests for the narrative intelligence engine.

Covers: velocity, strength, lifecycle state machine, quality gating,
alert eligibility (strict, no fallback), suppression reasons,
competition (narrative + token, strict winner-takes-all),
clustering, and winner explanations.

Reference: docs/intelligence/narrative-intelligence.md
"""

from datetime import datetime, timedelta, timezone

import pytest

from mctrend.narrative.intelligence import (
    LIFECYCLE_DEAD,
    LIFECYCLE_EMERGING,
    LIFECYCLE_FADING,
    LIFECYCLE_MERGED,
    LIFECYCLE_RISING,
    LIFECYCLE_TRENDING,
    LIFECYCLE_WEAK,
    SUPPRESSION_BELOW_MIN_STRENGTH,
    SUPPRESSION_BELOW_MIN_VELOCITY,
    SUPPRESSION_INSUFFICIENT_SOURCE_COUNT,
    SUPPRESSION_LOST_TO_STRONGER_NARRATIVE,
    SUPPRESSION_LOST_TO_STRONGER_TOKEN,
    SUPPRESSION_NARRATIVE_STATE_TOO_LOW,
    SUPPRESSION_NOT_TOP_IN_CLUSTER,
    SUPPRESSION_WINNER_MARGIN_NOT_MET,
    VELOCITY_ACCELERATING,
    VELOCITY_DECELERATING,
    VELOCITY_STABLE,
    VELOCITY_STALLED,
    NarrativeConfig,
    NarrativeIntelligence,
)


@pytest.fixture
def engine():
    return NarrativeIntelligence(NarrativeConfig())


@pytest.fixture
def now():
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_narrative(
    source_count=2,
    source_type="news",
    updated_minutes_ago=5,
    state="WEAK",
    velocity=None,
    strength=None,
    velocity_state=None,
    now=None,
    narrative_id="narr-test-1",
    anchor_terms=None,
    related_terms=None,
    entities=None,
):
    """Helper to build a narrative dict for testing."""
    if now is None:
        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    updated_at = (now - timedelta(minutes=updated_minutes_ago)).isoformat()
    sources = []
    for i in range(source_count):
        src_type = source_type if isinstance(source_type, str) else source_type[i % len(source_type)]
        sources.append({
            "source_id": f"src-{i}",
            "source_type": src_type,
            "source_name": f"source-{i}",
            "signal_strength": 0.6,
            "first_seen": (now - timedelta(minutes=20)).isoformat(),
            "last_updated": (now - timedelta(minutes=updated_minutes_ago)).isoformat(),
        })
    result = {
        "narrative_id": narrative_id,
        "anchor_terms": anchor_terms or ["TEST"],
        "related_terms": related_terms or [],
        "entities": entities or [],
        "sources": sources,
        "state": state,
        "updated_at": updated_at,
        "first_detected": (now - timedelta(hours=1)).isoformat(),
    }
    if velocity is not None:
        result["narrative_velocity"] = velocity
    if strength is not None:
        result["narrative_strength"] = strength
    if velocity_state is not None:
        result["velocity_state"] = velocity_state
    return result


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------


class TestVelocity:
    def test_velocity_with_sources_in_window(self, engine, now):
        """Sources updated within the 30-min window should count."""
        narrative = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        result = engine.compute_velocity(narrative, now)
        assert result["narrative_velocity"] > 0
        assert result["velocity_state"] != VELOCITY_STALLED

    def test_velocity_no_sources_in_window(self, engine, now):
        """Sources updated before the window → velocity 0, stalled."""
        narrative = _make_narrative(source_count=3, updated_minutes_ago=60, now=now)
        result = engine.compute_velocity(narrative, now)
        assert result["narrative_velocity"] == 0.0
        assert result["velocity_state"] == VELOCITY_STALLED

    def test_velocity_delta_positive(self, engine, now):
        """velocity_delta should be positive when current > previous."""
        narrative = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        narrative["narrative_velocity"] = 0.0
        result = engine.compute_velocity(narrative, now)
        assert result["velocity_delta"] > 0
        assert result["velocity_state"] == VELOCITY_ACCELERATING

    def test_velocity_delta_negative(self, engine, now):
        """velocity_delta should be negative when current < previous."""
        narrative = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        narrative["narrative_velocity"] = 0.5
        result = engine.compute_velocity(narrative, now)
        assert result["velocity_delta"] < 0
        assert result["velocity_state"] == VELOCITY_DECELERATING

    def test_velocity_stable(self, engine, now):
        """Nearly unchanged velocity → stable."""
        narrative = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        first = engine.compute_velocity(narrative, now)
        narrative["narrative_velocity"] = first["narrative_velocity"]
        result = engine.compute_velocity(narrative, now)
        assert result["velocity_state"] == VELOCITY_STABLE

    def test_velocity_returns_iso_timestamp(self, engine, now):
        narrative = _make_narrative(now=now)
        result = engine.compute_velocity(narrative, now)
        assert "velocity_updated_at" in result
        assert result["velocity_updated_at"] == now.isoformat()


# ---------------------------------------------------------------------------
# Strength
# ---------------------------------------------------------------------------


class TestStrength:
    def test_strength_range(self, engine, now):
        narrative = _make_narrative(source_count=5, updated_minutes_ago=1, now=now)
        narrative["narrative_velocity"] = 0.5
        strength = engine.compute_strength(narrative, now)
        assert 0.0 <= strength <= 1.0

    def test_strength_zero_sources(self, engine, now):
        narrative = _make_narrative(source_count=0, now=now)
        narrative["narrative_velocity"] = 0.0
        strength = engine.compute_strength(narrative, now)
        assert strength < 0.5

    def test_strength_increases_with_sources(self, engine, now):
        n1 = _make_narrative(source_count=1, updated_minutes_ago=5, now=now)
        n1["narrative_velocity"] = 0.1
        n3 = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        n3["narrative_velocity"] = 0.1
        assert engine.compute_strength(n3, now) > engine.compute_strength(n1, now)

    def test_strength_increases_with_velocity(self, engine, now):
        n_slow = _make_narrative(source_count=2, updated_minutes_ago=5, now=now)
        n_slow["narrative_velocity"] = 0.0
        n_fast = _make_narrative(source_count=2, updated_minutes_ago=5, now=now)
        n_fast["narrative_velocity"] = 0.4
        assert engine.compute_strength(n_fast, now) > engine.compute_strength(n_slow, now)

    def test_strength_diversity_boost(self, engine, now):
        n_single = _make_narrative(source_count=2, source_type="news", now=now)
        n_single["narrative_velocity"] = 0.1
        n_diverse = _make_narrative(source_count=2, source_type=["news", "twitter"], now=now)
        n_diverse["narrative_velocity"] = 0.1
        assert engine.compute_strength(n_diverse, now) > engine.compute_strength(n_single, now)

    def test_strength_decays_with_recency(self, engine, now):
        n_fresh = _make_narrative(source_count=2, updated_minutes_ago=5, now=now)
        n_fresh["narrative_velocity"] = 0.1
        n_stale = _make_narrative(source_count=2, updated_minutes_ago=100, now=now)
        n_stale["narrative_velocity"] = 0.1
        assert engine.compute_strength(n_fresh, now) > engine.compute_strength(n_stale, now)


# ---------------------------------------------------------------------------
# Lifecycle State Machine
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_weak_insufficient_sources(self, engine, now):
        n = _make_narrative(source_count=1, state="WEAK", now=now)
        n["narrative_strength"] = 0.3
        n["velocity_state"] = VELOCITY_STABLE
        assert engine.evaluate_state(n, now) == LIFECYCLE_WEAK

    def test_emerging_meets_thresholds(self, engine, now):
        n = _make_narrative(source_count=2, state="WEAK", now=now)
        n["narrative_strength"] = 0.25
        n["velocity_state"] = VELOCITY_STABLE
        assert engine.evaluate_state(n, now) == LIFECYCLE_EMERGING

    def test_rising_accelerating_with_strength(self, engine, now):
        n = _make_narrative(source_count=2, state="EMERGING", now=now)
        n["narrative_strength"] = 0.40
        n["velocity_state"] = VELOCITY_ACCELERATING
        assert engine.evaluate_state(n, now) == LIFECYCLE_RISING

    def test_trending_multi_source_strong(self, engine, now):
        n = _make_narrative(source_count=3, state="RISING", now=now)
        n["narrative_strength"] = 0.60
        n["velocity_state"] = VELOCITY_ACCELERATING
        assert engine.evaluate_state(n, now) == LIFECYCLE_TRENDING

    def test_trending_stable_velocity(self, engine, now):
        n = _make_narrative(source_count=3, state="RISING", now=now)
        n["narrative_strength"] = 0.60
        n["velocity_state"] = VELOCITY_STABLE
        assert engine.evaluate_state(n, now) == LIFECYCLE_TRENDING

    def test_fading_decelerating_weak(self, engine, now):
        n = _make_narrative(source_count=2, state="EMERGING", now=now)
        n["narrative_strength"] = 0.20
        n["velocity_state"] = VELOCITY_DECELERATING
        assert engine.evaluate_state(n, now) == LIFECYCLE_FADING

    def test_fading_stalled_from_trending(self, engine, now):
        n = _make_narrative(source_count=3, state="TRENDING", now=now)
        n["narrative_strength"] = 0.55
        n["velocity_state"] = VELOCITY_STALLED
        assert engine.evaluate_state(n, now) == LIFECYCLE_FADING

    def test_dead_low_strength(self, engine, now):
        n = _make_narrative(source_count=2, state="EMERGING", now=now)
        n["narrative_strength"] = 0.05
        n["velocity_state"] = VELOCITY_STALLED
        assert engine.evaluate_state(n, now) == LIFECYCLE_DEAD

    def test_dead_timeout(self, engine, now):
        n = _make_narrative(source_count=2, state="EMERGING", updated_minutes_ago=130, now=now)
        n["narrative_strength"] = 0.30
        n["velocity_state"] = VELOCITY_STABLE
        assert engine.evaluate_state(n, now) == LIFECYCLE_DEAD

    def test_dead_is_terminal(self, engine, now):
        n = _make_narrative(source_count=5, state="DEAD", now=now)
        n["narrative_strength"] = 0.90
        n["velocity_state"] = VELOCITY_ACCELERATING
        assert engine.evaluate_state(n, now) == LIFECYCLE_DEAD

    def test_merged_is_terminal(self, engine, now):
        n = _make_narrative(source_count=5, state="MERGED", now=now)
        n["narrative_strength"] = 0.90
        assert engine.evaluate_state(n, now) == LIFECYCLE_MERGED


# ---------------------------------------------------------------------------
# transition_narrative (full evaluation)
# ---------------------------------------------------------------------------


class TestTransitionNarrative:
    def test_returns_velocity_fields(self, engine, now):
        n = _make_narrative(source_count=2, now=now)
        result = engine.transition_narrative(n, now)
        assert "narrative_velocity" in result
        assert "velocity_delta" in result
        assert "velocity_state" in result
        assert "narrative_strength" in result

    def test_state_transition_logged(self, engine, now):
        n = _make_narrative(source_count=3, state="WEAK", updated_minutes_ago=5, now=now)
        result = engine.transition_narrative(n, now)
        if "state" in result:
            assert result["state"] != "WEAK"

    def test_dead_sets_dead_at(self, engine, now):
        n = _make_narrative(source_count=0, state="EMERGING", updated_minutes_ago=150, now=now)
        result = engine.transition_narrative(n, now)
        if result.get("state") == LIFECYCLE_DEAD:
            assert "dead_at" in result

    def test_attention_score_tracks_strength(self, engine, now):
        n = _make_narrative(source_count=2, now=now)
        result = engine.transition_narrative(n, now)
        assert result["attention_score"] == result["narrative_strength"]


# ---------------------------------------------------------------------------
# Quality Gating
# ---------------------------------------------------------------------------


class TestQualityGating:
    def test_weak_not_eligible(self, engine):
        n = {"state": LIFECYCLE_WEAK, "sources": [{"s": 1}], "narrative_strength": 0.3}
        assert engine.is_scoring_eligible(n) is False

    def test_emerging_eligible(self, engine):
        n = {"state": LIFECYCLE_EMERGING, "sources": [{"s": 1}, {"s": 2}], "narrative_strength": 0.25}
        assert engine.is_scoring_eligible(n) is True

    def test_rising_eligible(self, engine):
        n = {"state": LIFECYCLE_RISING, "sources": [{"s": 1}, {"s": 2}], "narrative_strength": 0.40}
        assert engine.is_scoring_eligible(n) is True

    def test_trending_eligible(self, engine):
        n = {"state": LIFECYCLE_TRENDING, "sources": [{"s": 1}, {"s": 2}, {"s": 3}], "narrative_strength": 0.60}
        assert engine.is_scoring_eligible(n) is True

    def test_fading_not_eligible(self, engine):
        n = {"state": LIFECYCLE_FADING, "sources": [{"s": 1}, {"s": 2}], "narrative_strength": 0.20}
        assert engine.is_scoring_eligible(n) is False

    def test_dead_not_eligible(self, engine):
        n = {"state": LIFECYCLE_DEAD, "sources": [{"s": 1}], "narrative_strength": 0.1}
        assert engine.is_scoring_eligible(n) is False

    def test_insufficient_sources_blocks(self, engine):
        n = {"state": LIFECYCLE_EMERGING, "sources": [{"s": 1}], "narrative_strength": 0.30}
        assert engine.is_scoring_eligible(n) is False

    def test_low_strength_blocks(self, engine):
        n = {"state": LIFECYCLE_EMERGING, "sources": [{"s": 1}, {"s": 2}], "narrative_strength": 0.10}
        assert engine.is_scoring_eligible(n) is False


# ---------------------------------------------------------------------------
# Alert Eligibility (strict, NO fallback)
# ---------------------------------------------------------------------------


class TestAlertEligibility:
    def test_rising_eligible(self, engine):
        n = {"state": LIFECYCLE_RISING}
        assert engine.is_alert_eligible(n) is True

    def test_trending_eligible(self, engine):
        n = {"state": LIFECYCLE_TRENDING}
        assert engine.is_alert_eligible(n) is True

    def test_emerging_never_eligible(self, engine):
        """EMERGING is never alert-eligible. No fallback. System prefers silence."""
        n = {"state": LIFECYCLE_EMERGING}
        assert engine.is_alert_eligible(n) is False

    def test_weak_never_eligible(self, engine):
        n = {"state": LIFECYCLE_WEAK}
        assert engine.is_alert_eligible(n) is False

    def test_fading_not_eligible(self, engine):
        n = {"state": LIFECYCLE_FADING}
        assert engine.is_alert_eligible(n) is False

    def test_dead_not_eligible(self, engine):
        n = {"state": LIFECYCLE_DEAD}
        assert engine.is_alert_eligible(n) is False


# ---------------------------------------------------------------------------
# Suppression Reasons (structured, machine-readable)
# ---------------------------------------------------------------------------


class TestSuppressionReasons:
    def test_dead_narrative(self, engine):
        n = {"state": LIFECYCLE_DEAD, "sources": [], "narrative_strength": 0.0}
        reasons = engine.get_suppression_reasons(n)
        codes = [r["code"] for r in reasons]
        assert "narrative_dead" in codes

    def test_emerging_below_alert_threshold(self, engine):
        n = {
            "state": LIFECYCLE_EMERGING,
            "sources": [{"source_type": "news"}, {"source_type": "news"}],
            "narrative_strength": 0.25,
            "narrative_velocity": 0.1,
            "velocity_state": "stable",
        }
        reasons = engine.get_suppression_reasons(n)
        codes = [r["code"] for r in reasons]
        assert SUPPRESSION_NARRATIVE_STATE_TOO_LOW in codes

    def test_stalled_velocity(self, engine):
        n = {
            "state": LIFECYCLE_WEAK,
            "sources": [{"source_type": "news"}],
            "narrative_strength": 0.10,
            "narrative_velocity": 0.0,
            "velocity_state": "stalled",
        }
        reasons = engine.get_suppression_reasons(n)
        codes = [r["code"] for r in reasons]
        assert SUPPRESSION_BELOW_MIN_VELOCITY in codes

    def test_insufficient_sources(self, engine):
        n = {
            "state": LIFECYCLE_WEAK,
            "sources": [{"source_type": "news"}],
            "narrative_strength": 0.20,
            "narrative_velocity": 0.1,
            "velocity_state": "stable",
        }
        reasons = engine.get_suppression_reasons(n)
        codes = [r["code"] for r in reasons]
        assert SUPPRESSION_INSUFFICIENT_SOURCE_COUNT in codes

    def test_below_min_strength(self, engine):
        n = {
            "state": LIFECYCLE_EMERGING,
            "sources": [{"source_type": "news"}, {"source_type": "twitter"}],
            "narrative_strength": 0.10,
            "narrative_velocity": 0.1,
            "velocity_state": "stable",
        }
        reasons = engine.get_suppression_reasons(n)
        codes = [r["code"] for r in reasons]
        assert SUPPRESSION_BELOW_MIN_STRENGTH in codes

    def test_all_reasons_have_required_fields(self, engine):
        """Every suppression reason must have code, actual, threshold, detail."""
        n = {
            "state": LIFECYCLE_WEAK,
            "sources": [],
            "narrative_strength": 0.0,
            "narrative_velocity": 0.0,
            "velocity_state": "stalled",
        }
        reasons = engine.get_suppression_reasons(n)
        assert len(reasons) > 0
        for r in reasons:
            assert "code" in r
            assert "actual" in r
            assert "threshold" in r
            assert "detail" in r

    def test_rising_no_suppression_for_state(self, engine):
        """RISING narratives should not have state-related suppression."""
        n = {
            "state": LIFECYCLE_RISING,
            "sources": [{"source_type": "news"}, {"source_type": "twitter"}],
            "narrative_strength": 0.50,
            "narrative_velocity": 0.2,
            "velocity_state": "accelerating",
        }
        reasons = engine.get_suppression_reasons(n)
        codes = [r["code"] for r in reasons]
        assert SUPPRESSION_NARRATIVE_STATE_TOO_LOW not in codes


# ---------------------------------------------------------------------------
# Rejection Reasons (backward compat)
# ---------------------------------------------------------------------------


class TestRejectionReasons:
    def test_dead_reason(self, engine):
        n = {"state": LIFECYCLE_DEAD, "sources": [], "narrative_strength": 0.0}
        assert engine.get_rejection_reason(n) == "narrative_dead"

    def test_merged_reason(self, engine):
        n = {"state": LIFECYCLE_MERGED, "sources": [], "narrative_strength": 0.0}
        assert engine.get_rejection_reason(n) == "narrative_merged"

    def test_weak_insufficient_sources(self, engine):
        n = {"state": LIFECYCLE_WEAK, "sources": [{"s": 1}], "narrative_strength": 0.3}
        reason = engine.get_rejection_reason(n)
        assert reason is not None
        assert "insufficient_sources" in reason

    def test_fading_reason(self, engine):
        n = {"state": LIFECYCLE_FADING, "sources": [{"s": 1}, {"s": 2}], "narrative_strength": 0.2}
        assert engine.get_rejection_reason(n) == "narrative_fading"

    def test_eligible_no_reason(self, engine):
        n = {"state": LIFECYCLE_RISING, "sources": [{"s": 1}, {"s": 2}], "narrative_strength": 0.40}
        assert engine.get_rejection_reason(n) is None


# ---------------------------------------------------------------------------
# Narrative Competition (with suppression reasons & winner explanations)
# ---------------------------------------------------------------------------


class TestNarrativeCompetition:
    def test_single_narrative_strong_enough(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.50, "cluster_id": "c1",
             "sources": [{"source_type": "news"}, {"source_type": "twitter"}],
             "narrative_velocity": 0.1, "velocity_state": "stable"},
        ]
        results = engine.select_narrative_winners(narratives)
        assert len(results) == 1
        assert results[0]["competition_status"] == "no_contest"
        assert results[0]["competition_rank"] == 1
        assert "winner_explanation" in results[0]
        assert results[0]["suppression_reasons"] == []

    def test_single_narrative_below_threshold(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.10, "cluster_id": "c1"},
        ]
        results = engine.select_narrative_winners(narratives)
        assert results[0]["competition_status"] == "below_threshold"
        reasons = results[0]["suppression_reasons"]
        assert len(reasons) >= 1
        assert reasons[0]["code"] == SUPPRESSION_BELOW_MIN_STRENGTH

    def test_two_narratives_winner_and_outcompeted(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.60, "cluster_id": "c1",
             "sources": [{"source_type": "news"}], "narrative_velocity": 0.1, "velocity_state": "stable"},
            {"narrative_id": "n2", "narrative_strength": 0.40, "cluster_id": "c1"},
        ]
        results = engine.select_narrative_winners(narratives)
        winner = [r for r in results if r["competition_status"] == "winner"]
        outcompeted = [r for r in results if r["competition_status"] == "outcompeted"]
        assert len(winner) == 1
        assert winner[0]["narrative_id"] == "n1"
        assert "winner_explanation" in winner[0]
        assert len(outcompeted) == 1
        # Outcompeted must have structured suppression reasons
        oc_codes = [r["code"] for r in outcompeted[0]["suppression_reasons"]]
        assert SUPPRESSION_LOST_TO_STRONGER_NARRATIVE in oc_codes
        assert SUPPRESSION_NOT_TOP_IN_CLUSTER in oc_codes

    def test_winner_explanation_has_runner_up(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.60, "cluster_id": "c1",
             "sources": [{"source_type": "news"}], "narrative_velocity": 0.1, "velocity_state": "stable"},
            {"narrative_id": "n2", "narrative_strength": 0.40, "cluster_id": "c1"},
        ]
        results = engine.select_narrative_winners(narratives)
        winner = [r for r in results if r["competition_status"] == "winner"][0]
        explanation = winner["winner_explanation"]
        assert "runner_up" in explanation
        assert explanation["runner_up"]["narrative_id"] == "n2"
        assert explanation["runner_up"]["strength_difference"] == 0.20
        assert "competing_narratives" in explanation
        assert explanation["competing_narratives"] == 2

    def test_separate_clusters_independent(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.50, "cluster_id": "c1",
             "sources": [{"source_type": "news"}], "narrative_velocity": 0.1, "velocity_state": "stable"},
            {"narrative_id": "n2", "narrative_strength": 0.50, "cluster_id": "c2",
             "sources": [{"source_type": "news"}], "narrative_velocity": 0.1, "velocity_state": "stable"},
        ]
        results = engine.select_narrative_winners(narratives)
        statuses = {r["narrative_id"]: r["competition_status"] for r in results}
        assert statuses["n1"] == "no_contest"
        assert statuses["n2"] == "no_contest"

    def test_unclustered_narratives_solo(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.50,
             "sources": [{"source_type": "news"}], "narrative_velocity": 0.1, "velocity_state": "stable"},
            {"narrative_id": "n2", "narrative_strength": 0.50,
             "sources": [{"source_type": "news"}], "narrative_velocity": 0.1, "velocity_state": "stable"},
        ]
        results = engine.select_narrative_winners(narratives)
        assert len(results) == 2
        assert all(r["competition_status"] == "no_contest" for r in results)


# ---------------------------------------------------------------------------
# Token Competition (strict winner-takes-all)
# ---------------------------------------------------------------------------


class TestTokenCompetition:
    def test_single_token_is_winner(self, engine):
        tokens = [{"token_id": "t1", "net_potential": 0.50}]
        results = engine.select_token_winners(tokens)
        assert len(results) == 1
        assert results[0]["token_competition_status"] == "winner"
        assert results[0]["suppression_reasons"] == []

    def test_top_token_wins(self, engine):
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.40},
        ]
        results = engine.select_token_winners(tokens)
        assert results[0]["token_id"] == "t1"
        assert results[0]["token_competition_status"] == "winner"

    def test_within_margin_is_suppressed(self, engine):
        """Strict winner-takes-all: even tokens within margin are suppressed."""
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.56},  # within 0.05 margin
        ]
        results = engine.select_token_winners(tokens)
        assert results[1]["token_competition_status"] == "suppressed"
        # Must include winner_margin_not_met reason
        codes = [r["code"] for r in results[1]["suppression_reasons"]]
        assert SUPPRESSION_LOST_TO_STRONGER_TOKEN in codes
        assert SUPPRESSION_WINNER_MARGIN_NOT_MET in codes

    def test_far_below_suppressed(self, engine):
        """Token far below winner should be suppressed."""
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.40},
        ]
        results = engine.select_token_winners(tokens)
        assert results[1]["token_competition_status"] == "suppressed"
        codes = [r["code"] for r in results[1]["suppression_reasons"]]
        assert SUPPRESSION_LOST_TO_STRONGER_TOKEN in codes

    def test_winner_has_explanation(self, engine):
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.40},
        ]
        results = engine.select_token_winners(tokens)
        winner = results[0]
        assert "winner_explanation" in winner
        assert winner["winner_explanation"]["rank"] == 1
        assert winner["winner_explanation"]["total_competitors"] == 2
        assert winner["winner_explanation"]["margin_over_second"] == 0.20

    def test_empty_list(self, engine):
        assert engine.select_token_winners([]) == []

    def test_suppression_reasons_always_present(self, engine):
        """Every non-winner token must have suppression_reasons."""
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.55},
            {"token_id": "t3", "net_potential": 0.30},
        ]
        results = engine.select_token_winners(tokens)
        for r in results[1:]:
            assert r["token_competition_status"] == "suppressed"
            assert len(r["suppression_reasons"]) >= 1


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


class TestClustering:
    def test_term_overlap_clusters(self, engine):
        """Narratives with overlapping anchor terms should cluster together."""
        n1 = _make_narrative(narrative_id="n1", anchor_terms=["DEEPMIND", "AI", "GOOGLE"])
        n2 = _make_narrative(narrative_id="n2", anchor_terms=["DEEPMIND", "AI", "BREAKTHROUGH"])
        result = engine.cluster_narratives([n1, n2])
        assert result["n1"] == result["n2"]

    def test_no_overlap_separate(self, engine):
        """Narratives with no term overlap remain in separate clusters."""
        n1 = _make_narrative(narrative_id="n1", anchor_terms=["DEEPMIND", "AI"])
        n2 = _make_narrative(narrative_id="n2", anchor_terms=["MOONDOG", "SPACE"])
        result = engine.cluster_narratives([n1, n2])
        assert result["n1"] != result["n2"]

    def test_single_term_overlap_no_cluster(self, engine):
        """Single shared anchor term must NOT trigger clustering (false merge guard)."""
        n1 = _make_narrative(narrative_id="n1", anchor_terms=["AI", "HEALTHCARE"])
        n2 = _make_narrative(narrative_id="n2", anchor_terms=["AI", "MEMECOINS"])
        result = engine.cluster_narratives([n1, n2])
        assert result["n1"] != result["n2"]

    def test_token_overlap_clusters(self, engine):
        """Narratives sharing >= 2 linked tokens should cluster."""
        n1 = _make_narrative(narrative_id="n1", anchor_terms=["FOO"])
        n2 = _make_narrative(narrative_id="n2", anchor_terms=["BAR"])
        token_links = {
            "n1": ["t1", "t2", "t3"],
            "n2": ["t2", "t3", "t4"],
        }
        result = engine.cluster_narratives([n1, n2], token_links)
        assert result["n1"] == result["n2"]

    def test_single_token_overlap_not_enough(self, engine):
        """1 shared token is below cluster_token_overlap_min=2."""
        n1 = _make_narrative(narrative_id="n1", anchor_terms=["FOO"])
        n2 = _make_narrative(narrative_id="n2", anchor_terms=["BAR"])
        token_links = {
            "n1": ["t1", "t2"],
            "n2": ["t2", "t3"],
        }
        result = engine.cluster_narratives([n1, n2], token_links)
        assert result["n1"] != result["n2"]

    def test_entity_overlap_clusters(self, engine):
        """Narratives sharing a named entity should cluster."""
        n1 = _make_narrative(
            narrative_id="n1", anchor_terms=["FOO"],
            entities=[{"name": "Google", "type": "ORG"}],
        )
        n2 = _make_narrative(
            narrative_id="n2", anchor_terms=["BAR"],
            entities=[{"name": "Google", "type": "ORG"}],
        )
        result = engine.cluster_narratives([n1, n2])
        assert result["n1"] == result["n2"]

    def test_related_terms_overlap(self, engine):
        """Broad term overlap (anchor+related) should cluster."""
        n1 = _make_narrative(
            narrative_id="n1", anchor_terms=["FOO"],
            related_terms=["DEEPMIND", "AI", "GOOGLE"],
        )
        n2 = _make_narrative(
            narrative_id="n2", anchor_terms=["BAR"],
            related_terms=["DEEPMIND", "AI", "BREAKTHROUGH"],
        )
        result = engine.cluster_narratives([n1, n2])
        assert result["n1"] == result["n2"]

    def test_transitive_clustering(self, engine):
        """If A clusters with B and B clusters with C, all three should share a cluster."""
        # Each adjacent pair shares >= 2 terms with sufficient overlap ratio
        n1 = _make_narrative(narrative_id="n1", anchor_terms=["DEEPMIND", "AI", "RESEARCH"])
        n2 = _make_narrative(narrative_id="n2", anchor_terms=["DEEPMIND", "AI", "GOOGLE"])
        n3 = _make_narrative(narrative_id="n3", anchor_terms=["DEEPMIND", "GOOGLE", "GEMINI"])
        result = engine.cluster_narratives([n1, n2, n3])
        assert result["n1"] == result["n2"] == result["n3"]

    def test_empty_narratives(self, engine):
        assert engine.cluster_narratives([]) == {}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestNarrativeConfig:
    def test_defaults(self):
        cfg = NarrativeConfig()
        assert cfg.velocity_window_minutes == 30.0
        assert cfg.min_sources == 2
        assert cfg.winner_min_strength == 0.30
        assert cfg.cluster_term_overlap_pct == 0.50

    def test_custom_config(self):
        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        cfg = NarrativeConfig(min_sources=3, dead_timeout_minutes=180)
        engine = NarrativeIntelligence(cfg)
        n = _make_narrative(source_count=2, state="WEAK", updated_minutes_ago=5, now=now)
        n["narrative_strength"] = 0.25
        n["velocity_state"] = VELOCITY_STABLE
        assert engine.evaluate_state(n, now) == LIFECYCLE_WEAK
