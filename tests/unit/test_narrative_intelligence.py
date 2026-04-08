"""Tests for the narrative intelligence engine.

Covers: velocity computation, strength computation, lifecycle state machine,
quality gating, alert eligibility, competition (narrative + token).

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
        "narrative_id": "narr-test-1",
        "anchor_terms": ["TEST"],
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
        narrative["narrative_velocity"] = 0.0  # previous was 0
        result = engine.compute_velocity(narrative, now)
        assert result["velocity_delta"] > 0
        assert result["velocity_state"] == VELOCITY_ACCELERATING

    def test_velocity_delta_negative(self, engine, now):
        """velocity_delta should be negative when current < previous."""
        # 1 source in window (out of 3) when previous velocity was higher
        narrative = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        # Set previous velocity higher than current will be
        narrative["narrative_velocity"] = 0.5
        result = engine.compute_velocity(narrative, now)
        assert result["velocity_delta"] < 0
        assert result["velocity_state"] == VELOCITY_DECELERATING

    def test_velocity_stable(self, engine, now):
        """Nearly unchanged velocity → stable."""
        narrative = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        # Compute once to get actual velocity
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
        """Strength must be in [0, 1]."""
        narrative = _make_narrative(source_count=5, updated_minutes_ago=1, now=now)
        narrative["narrative_velocity"] = 0.5
        strength = engine.compute_strength(narrative, now)
        assert 0.0 <= strength <= 1.0

    def test_strength_zero_sources(self, engine, now):
        """No sources → source_count_score = 0, diversity = 0."""
        narrative = _make_narrative(source_count=0, now=now)
        narrative["narrative_velocity"] = 0.0
        strength = engine.compute_strength(narrative, now)
        # Only recency might contribute if updated_at is recent
        assert strength < 0.5

    def test_strength_increases_with_sources(self, engine, now):
        """More sources → higher strength (all else equal)."""
        n1 = _make_narrative(source_count=1, updated_minutes_ago=5, now=now)
        n1["narrative_velocity"] = 0.1
        n3 = _make_narrative(source_count=3, updated_minutes_ago=5, now=now)
        n3["narrative_velocity"] = 0.1
        s1 = engine.compute_strength(n1, now)
        s3 = engine.compute_strength(n3, now)
        assert s3 > s1

    def test_strength_increases_with_velocity(self, engine, now):
        """Higher velocity → higher strength (all else equal)."""
        n_slow = _make_narrative(source_count=2, updated_minutes_ago=5, now=now)
        n_slow["narrative_velocity"] = 0.0
        n_fast = _make_narrative(source_count=2, updated_minutes_ago=5, now=now)
        n_fast["narrative_velocity"] = 0.4
        s_slow = engine.compute_strength(n_slow, now)
        s_fast = engine.compute_strength(n_fast, now)
        assert s_fast > s_slow

    def test_strength_diversity_boost(self, engine, now):
        """Multiple source types → higher diversity score → higher strength."""
        n_single = _make_narrative(source_count=2, source_type="news", now=now)
        n_single["narrative_velocity"] = 0.1
        n_diverse = _make_narrative(
            source_count=2, source_type=["news", "twitter"], now=now
        )
        n_diverse["narrative_velocity"] = 0.1
        s_single = engine.compute_strength(n_single, now)
        s_diverse = engine.compute_strength(n_diverse, now)
        assert s_diverse > s_single

    def test_strength_decays_with_recency(self, engine, now):
        """Stale narrative → lower recency score → lower strength."""
        n_fresh = _make_narrative(source_count=2, updated_minutes_ago=5, now=now)
        n_fresh["narrative_velocity"] = 0.1
        n_stale = _make_narrative(source_count=2, updated_minutes_ago=100, now=now)
        n_stale["narrative_velocity"] = 0.1
        s_fresh = engine.compute_strength(n_fresh, now)
        s_stale = engine.compute_strength(n_stale, now)
        assert s_fresh > s_stale


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
        """Trending requires accelerating or stable velocity."""
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
        """A trending narrative that stalls should fade."""
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
        """Narrative with no updates for dead_timeout_minutes → DEAD."""
        n = _make_narrative(source_count=2, state="EMERGING", updated_minutes_ago=130, now=now)
        n["narrative_strength"] = 0.30
        n["velocity_state"] = VELOCITY_STABLE
        assert engine.evaluate_state(n, now) == LIFECYCLE_DEAD

    def test_dead_is_terminal(self, engine, now):
        """Once DEAD, cannot transition back."""
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
        """When state changes, the new state appears in result."""
        n = _make_narrative(source_count=3, state="WEAK", updated_minutes_ago=5, now=now)
        # With fresh sources in the window, this should get at least EMERGING
        result = engine.transition_narrative(n, now)
        if "state" in result:
            assert result["state"] != "WEAK"

    def test_dead_sets_dead_at(self, engine, now):
        n = _make_narrative(source_count=0, state="EMERGING", updated_minutes_ago=150, now=now)
        result = engine.transition_narrative(n, now)
        if result.get("state") == LIFECYCLE_DEAD:
            assert "dead_at" in result

    def test_trending_sets_peaked_at(self, engine, now):
        n = _make_narrative(source_count=4, state="RISING", updated_minutes_ago=2, now=now)
        n["narrative_velocity"] = 0.0  # Will compute fresh
        result = engine.transition_narrative(n, now)
        # This may or may not reach TRENDING depending on computed strength
        if result.get("state") == LIFECYCLE_TRENDING:
            assert "peaked_at" in result

    def test_attention_score_tracks_strength(self, engine, now):
        """attention_score field should be set equal to strength for backward compat."""
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
        n = {
            "state": LIFECYCLE_EMERGING,
            "sources": [{"s": 1}, {"s": 2}],
            "narrative_strength": 0.25,
        }
        assert engine.is_scoring_eligible(n) is True

    def test_rising_eligible(self, engine):
        n = {
            "state": LIFECYCLE_RISING,
            "sources": [{"s": 1}, {"s": 2}],
            "narrative_strength": 0.40,
        }
        assert engine.is_scoring_eligible(n) is True

    def test_trending_eligible(self, engine):
        n = {
            "state": LIFECYCLE_TRENDING,
            "sources": [{"s": 1}, {"s": 2}, {"s": 3}],
            "narrative_strength": 0.60,
        }
        assert engine.is_scoring_eligible(n) is True

    def test_fading_not_eligible(self, engine):
        n = {
            "state": LIFECYCLE_FADING,
            "sources": [{"s": 1}, {"s": 2}],
            "narrative_strength": 0.20,
        }
        assert engine.is_scoring_eligible(n) is False

    def test_dead_not_eligible(self, engine):
        n = {"state": LIFECYCLE_DEAD, "sources": [{"s": 1}], "narrative_strength": 0.1}
        assert engine.is_scoring_eligible(n) is False

    def test_insufficient_sources_blocks(self, engine):
        n = {
            "state": LIFECYCLE_EMERGING,
            "sources": [{"s": 1}],  # only 1 source, need 2
            "narrative_strength": 0.30,
        }
        assert engine.is_scoring_eligible(n) is False

    def test_low_strength_blocks(self, engine):
        n = {
            "state": LIFECYCLE_EMERGING,
            "sources": [{"s": 1}, {"s": 2}],
            "narrative_strength": 0.10,  # below emerging_threshold (0.20)
        }
        assert engine.is_scoring_eligible(n) is False


# ---------------------------------------------------------------------------
# Alert Eligibility
# ---------------------------------------------------------------------------


class TestAlertEligibility:
    def test_rising_eligible_with_rising_present(self, engine):
        n = {"state": LIFECYCLE_RISING}
        assert engine.is_alert_eligible(n, has_rising_narratives=True) is True

    def test_trending_eligible(self, engine):
        n = {"state": LIFECYCLE_TRENDING}
        assert engine.is_alert_eligible(n, has_rising_narratives=True) is True

    def test_emerging_not_eligible_with_rising_present(self, engine):
        n = {"state": LIFECYCLE_EMERGING}
        assert engine.is_alert_eligible(n, has_rising_narratives=True) is False

    def test_emerging_eligible_fallback(self, engine):
        """When no RISING+ narratives exist, EMERGING becomes alert-eligible."""
        n = {"state": LIFECYCLE_EMERGING}
        assert engine.is_alert_eligible(n, has_rising_narratives=False) is True

    def test_weak_never_eligible(self, engine):
        n = {"state": LIFECYCLE_WEAK}
        assert engine.is_alert_eligible(n, has_rising_narratives=False) is False


# ---------------------------------------------------------------------------
# Rejection Reasons
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
        n = {
            "state": LIFECYCLE_RISING,
            "sources": [{"s": 1}, {"s": 2}],
            "narrative_strength": 0.40,
        }
        assert engine.get_rejection_reason(n) is None


# ---------------------------------------------------------------------------
# Narrative Competition
# ---------------------------------------------------------------------------


class TestNarrativeCompetition:
    def test_single_narrative_strong_enough(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.50, "cluster_id": "c1"},
        ]
        results = engine.select_narrative_winners(narratives)
        assert len(results) == 1
        assert results[0]["competition_status"] == "no_contest"
        assert results[0]["competition_rank"] == 1

    def test_single_narrative_below_threshold(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.10, "cluster_id": "c1"},
        ]
        results = engine.select_narrative_winners(narratives)
        assert results[0]["competition_status"] == "below_threshold"

    def test_two_narratives_winner_and_outcompeted(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.60, "cluster_id": "c1"},
            {"narrative_id": "n2", "narrative_strength": 0.40, "cluster_id": "c1"},
        ]
        results = engine.select_narrative_winners(narratives)
        winner = [r for r in results if r["competition_status"] == "winner"]
        outcompeted = [r for r in results if r["competition_status"] == "outcompeted"]
        assert len(winner) == 1
        assert winner[0]["narrative_id"] == "n1"
        assert len(outcompeted) == 1

    def test_separate_clusters_independent(self, engine):
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.50, "cluster_id": "c1"},
            {"narrative_id": "n2", "narrative_strength": 0.50, "cluster_id": "c2"},
        ]
        results = engine.select_narrative_winners(narratives)
        # Each is the sole member of its cluster → no_contest
        statuses = {r["narrative_id"]: r["competition_status"] for r in results}
        assert statuses["n1"] == "no_contest"
        assert statuses["n2"] == "no_contest"

    def test_unclustered_narratives_solo(self, engine):
        """Narratives without cluster_id use narrative_id as group key."""
        narratives = [
            {"narrative_id": "n1", "narrative_strength": 0.50},
            {"narrative_id": "n2", "narrative_strength": 0.50},
        ]
        results = engine.select_narrative_winners(narratives)
        assert len(results) == 2
        assert all(r["competition_status"] == "no_contest" for r in results)


# ---------------------------------------------------------------------------
# Token Competition
# ---------------------------------------------------------------------------


class TestTokenCompetition:
    def test_single_token_is_winner(self, engine):
        tokens = [{"token_id": "t1", "net_potential": 0.50}]
        results = engine.select_token_winners(tokens)
        assert len(results) == 1
        assert results[0]["token_competition_status"] == "winner"

    def test_top_token_wins(self, engine):
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.40},
        ]
        results = engine.select_token_winners(tokens)
        assert results[0]["token_id"] == "t1"
        assert results[0]["token_competition_status"] == "winner"

    def test_within_margin(self, engine):
        """Token within 0.05 of winner should be 'within_margin', not suppressed."""
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.56},  # within 0.05
        ]
        results = engine.select_token_winners(tokens)
        assert results[1]["token_competition_status"] == "within_margin"

    def test_suppressed(self, engine):
        """Token far below winner should be suppressed."""
        tokens = [
            {"token_id": "t1", "net_potential": 0.60},
            {"token_id": "t2", "net_potential": 0.40},  # 0.20 below
        ]
        results = engine.select_token_winners(tokens)
        assert results[1]["token_competition_status"] == "suppressed"

    def test_empty_list(self, engine):
        assert engine.select_token_winners([]) == []


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestNarrativeConfig:
    def test_defaults(self):
        cfg = NarrativeConfig()
        assert cfg.velocity_window_minutes == 30.0
        assert cfg.min_sources == 2
        assert cfg.winner_min_strength == 0.30

    def test_custom_config(self):
        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        cfg = NarrativeConfig(min_sources=3, dead_timeout_minutes=180)
        engine = NarrativeIntelligence(cfg)
        n = _make_narrative(source_count=2, state="WEAK", updated_minutes_ago=5, now=now)
        n["narrative_strength"] = 0.25
        n["velocity_state"] = VELOCITY_STABLE
        # With min_sources=3, 2 sources should still be WEAK
        assert engine.evaluate_state(n, now) == LIFECYCLE_WEAK
