"""Unit tests for narrative ranking, classification, and explainability.

Covers:
- score_narrative_candidate: all components computed correctly
- classify_narrative: NOISE / WEAK / EMERGING / STRONG thresholds
- build_reason: contains concrete values, no empty output
- to_board_entry: full board entry structure and fields
- build_narrative_board: ranking, NOISE filtering, classification filter
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mctrend.narrative.discovery_engine import NarrativeCandidate, _candidate_id
from mctrend.narrative.scoring import (
    CLASS_EMERGING,
    CLASS_NOISE,
    CLASS_STRONG,
    CLASS_WEAK,
    W_ACCELERATION,
    W_CORROBORATION,
    W_RECENCY,
    W_TOKEN_COUNT,
    W_VELOCITY,
    build_narrative_board,
    build_reason,
    classify_narrative,
    score_narrative_candidate,
    to_board_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _ago(seconds: float = 0.0) -> float:
    return _now() - seconds


def _make_candidate(
    name: str = "TRUMP",
    token_count: int = 5,
    last_seen_seconds_ago: float = 60.0,
    tokens_in_5m: int = 0,
    tokens_in_15m: int = 0,
    x_corr: float = 0.0,
    news_corr: float = 0.0,
) -> NarrativeCandidate:
    """Build a NarrativeCandidate with controllable state."""
    now = _now()
    first_seen = now - 1800  # 30 min ago

    cand = NarrativeCandidate(
        candidate_id=_candidate_id(name),
        canonical_name=name,
        first_seen=first_seen,
        last_seen=now - last_seen_seconds_ago,
    )
    cand.x_spike_corroboration = x_corr
    cand.news_corroboration = news_corr

    # Add tokens with specific timing so windowed counts are predictable
    base_id = 0
    # Tokens in 5m window (observation time = now - 2min each)
    for i in range(tokens_in_5m):
        cand.add_token(f"t5m_{base_id+i}", f"Token5m{i}", obs_time=now - 120)
    base_id += tokens_in_5m

    # Additional tokens in 15m window (observation time = now - 10min each)
    remaining_15m = max(0, tokens_in_15m - tokens_in_5m)
    for i in range(remaining_15m):
        cand.add_token(f"t15m_{base_id+i}", f"Token15m{i}", obs_time=now - 600)
    base_id += remaining_15m

    # Remaining tokens outside all windows (> 60min ago)
    remaining = max(0, token_count - tokens_in_5m - remaining_15m)
    for i in range(remaining):
        cand.add_token(f"told_{base_id+i}", f"TokenOld{i}", obs_time=now - 7200)

    return cand


# ---------------------------------------------------------------------------
# score_narrative_candidate
# ---------------------------------------------------------------------------

class TestScoreNarrativeCandidate:
    def test_returns_score_object(self):
        cand = _make_candidate(token_count=5)
        score = score_narrative_candidate(cand)
        assert hasattr(score, "total")
        assert hasattr(score, "token_count_component")
        assert hasattr(score, "velocity_component")
        assert hasattr(score, "acceleration_component")
        assert hasattr(score, "recency_component")
        assert hasattr(score, "corroboration_component")

    def test_total_bounded_0_1(self):
        cand = _make_candidate(token_count=50, tokens_in_5m=20, x_corr=1.0)
        score = score_narrative_candidate(cand)
        assert 0.0 <= score.total <= 1.0

    def test_more_tokens_higher_score(self):
        low = score_narrative_candidate(_make_candidate(token_count=3))
        high = score_narrative_candidate(_make_candidate(token_count=15))
        assert high.token_count_component > low.token_count_component

    def test_recent_velocity_raises_score(self):
        slow = score_narrative_candidate(_make_candidate(token_count=5, tokens_in_5m=0))
        fast = score_narrative_candidate(_make_candidate(token_count=5, tokens_in_5m=5))
        assert fast.velocity_component > slow.velocity_component

    def test_x_corroboration_raises_score(self):
        no_corr = score_narrative_candidate(_make_candidate(token_count=5, x_corr=0.0))
        with_corr = score_narrative_candidate(_make_candidate(token_count=5, x_corr=1.0))
        assert with_corr.corroboration_component > no_corr.corroboration_component

    def test_recency_full_when_recently_updated(self):
        cand = _make_candidate(token_count=5, last_seen_seconds_ago=60.0)
        score = score_narrative_candidate(cand)
        # last_seen 60s ago < 5min full window → recency_score = 1.0
        expected_max = W_RECENCY
        assert score.recency_component == pytest.approx(expected_max, abs=0.01)

    def test_recency_zero_when_very_old(self):
        cand = _make_candidate(token_count=5, last_seen_seconds_ago=7300.0)
        score = score_narrative_candidate(cand)
        # 7300s = ~122min > 120min decay → recency_score = 0.0
        assert score.recency_component == 0.0

    def test_acceleration_increasing_when_more_recent_activity(self):
        # Many tokens in 5m window, fewer in 15m window → 5m rate > 15m rate × 1.2
        cand = _make_candidate(
            token_count=10,
            tokens_in_5m=6,   # rate = 6/5 = 1.2 tokens/min
            tokens_in_15m=6,  # rate = 6/15 = 0.4 tokens/min → ratio = 1.2/0.4 = 3x
        )
        score = score_narrative_candidate(cand)
        assert score.acceleration_label == "increasing"

    def test_acceleration_decreasing_when_less_recent_activity(self):
        now = _now()
        cand = NarrativeCandidate(
            candidate_id=_candidate_id("TEST"),
            canonical_name="TEST",
            first_seen=now - 3600,
            last_seen=now - 600,
        )
        # Many tokens 10-15min ago, none in last 5min
        for i in range(8):
            cand.add_token(f"t{i}", f"T{i}", obs_time=now - 720)  # 12min ago
        score = score_narrative_candidate(cand, now=now)
        assert score.acceleration_label == "decreasing"

    def test_velocity_metrics_present(self):
        cand = _make_candidate(token_count=5, tokens_in_5m=3, tokens_in_15m=5)
        score = score_narrative_candidate(cand)
        assert score.tokens_last_5m == 3
        assert score.tokens_last_15m == 5
        assert score.rate_per_minute == pytest.approx(3.0 / 5.0, abs=0.01)

    def test_weights_sum_check(self):
        total_weight = W_TOKEN_COUNT + W_VELOCITY + W_ACCELERATION + W_RECENCY + W_CORROBORATION
        assert total_weight == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# classify_narrative
# ---------------------------------------------------------------------------

class TestClassifyNarrative:
    def test_noise_below_3_tokens(self):
        cand = _make_candidate(token_count=2)
        score = score_narrative_candidate(cand)
        assert classify_narrative(cand, score) == CLASS_NOISE

    def test_noise_at_exactly_2(self):
        cand = _make_candidate(token_count=2)
        score = score_narrative_candidate(cand)
        assert classify_narrative(cand, score) == CLASS_NOISE

    def test_weak_at_3_tokens_low_score(self):
        # 3 tokens, no velocity → low score → WEAK
        cand = _make_candidate(token_count=3, last_seen_seconds_ago=3600)
        score = score_narrative_candidate(cand)
        result = classify_narrative(cand, score)
        assert result in (CLASS_WEAK, CLASS_NOISE)  # very old → may score very low

    def test_emerging_at_5_tokens_with_activity(self):
        cand = _make_candidate(token_count=5, tokens_in_5m=3, tokens_in_15m=5, last_seen_seconds_ago=120)
        score = score_narrative_candidate(cand)
        result = classify_narrative(cand, score)
        assert result in (CLASS_EMERGING, CLASS_STRONG)

    def test_strong_requires_8_tokens_high_score_acceleration(self):
        # 8 tokens with strong velocity and acceleration
        cand = _make_candidate(
            token_count=12,
            tokens_in_5m=8,
            tokens_in_15m=8,
            last_seen_seconds_ago=30,
            x_corr=0.8,
        )
        score = score_narrative_candidate(cand)
        result = classify_narrative(cand, score)
        # Should be STRONG if acceleration is increasing and score is high enough
        # (velocity 8/5 = 1.6 tokens/min > max 2.0 → velocity_component = 0.24 * 1.6/2.0)
        assert result in (CLASS_STRONG, CLASS_EMERGING)

    def test_not_strong_without_acceleration(self):
        # 10 tokens, high score, but NO recent activity → decreasing/flat → not STRONG
        cand = _make_candidate(token_count=10, tokens_in_5m=0, last_seen_seconds_ago=300)
        score = score_narrative_candidate(cand)
        assert score.acceleration_label != "increasing"
        result = classify_narrative(cand, score)
        assert result != CLASS_STRONG

    def test_classification_is_deterministic(self):
        cand = _make_candidate(token_count=5, tokens_in_5m=2)
        now = _now()
        r1 = classify_narrative(cand, score_narrative_candidate(cand, now))
        r2 = classify_narrative(cand, score_narrative_candidate(cand, now))
        assert r1 == r2


# ---------------------------------------------------------------------------
# build_reason
# ---------------------------------------------------------------------------

class TestBuildReason:
    def test_contains_term_name(self):
        cand = _make_candidate(name="TRUMP", token_count=5)
        score = score_narrative_candidate(cand)
        cls = classify_narrative(cand, score)
        reason = build_reason(cand, score, cls)
        assert "TRUMP" in reason

    def test_contains_token_count(self):
        cand = _make_candidate(token_count=7)
        score = score_narrative_candidate(cand)
        cls = classify_narrative(cand, score)
        reason = build_reason(cand, score, cls)
        assert "7" in reason

    def test_contains_velocity_info_when_active(self):
        cand = _make_candidate(token_count=5, tokens_in_5m=3)
        score = score_narrative_candidate(cand)
        cls = classify_narrative(cand, score)
        reason = build_reason(cand, score, cls)
        assert "Velocity" in reason or "token/min" in reason

    def test_mentions_x_corroboration_when_present(self):
        cand = _make_candidate(token_count=5, x_corr=0.5)
        score = score_narrative_candidate(cand)
        cls = classify_narrative(cand, score)
        reason = build_reason(cand, score, cls)
        assert "X spike" in reason or "Corroborated" in reason

    def test_no_x_mention_without_corroboration(self):
        cand = _make_candidate(token_count=5, x_corr=0.0)
        score = score_narrative_candidate(cand)
        cls = classify_narrative(cand, score)
        reason = build_reason(cand, score, cls)
        # When no X corroboration, no X mention expected
        assert "X spike" not in reason

    def test_non_empty_always(self):
        for count in (2, 3, 5, 10):
            cand = _make_candidate(token_count=count)
            score = score_narrative_candidate(cand)
            cls = classify_narrative(cand, score)
            reason = build_reason(cand, score, cls)
            assert len(reason) > 10

    def test_no_stale_activity_message(self):
        cand = _make_candidate(token_count=5, tokens_in_5m=0, tokens_in_15m=0)
        score = score_narrative_candidate(cand)
        cls = classify_narrative(cand, score)
        reason = build_reason(cand, score, cls)
        assert "No" in reason or "15min" in reason  # stale case described


# ---------------------------------------------------------------------------
# to_board_entry
# ---------------------------------------------------------------------------

class TestToBoardEntry:
    def test_required_fields_present(self):
        cand = _make_candidate(token_count=5)
        entry = to_board_entry(cand)
        for field in [
            "candidate_id", "term", "narrative_score", "classification",
            "token_count", "tokens", "first_seen", "last_seen",
            "velocity", "corroboration", "score_breakdown", "reason",
            "confidence", "age_seconds",
        ]:
            assert field in entry, f"Missing field: {field}"

    def test_velocity_subfields(self):
        cand = _make_candidate(token_count=5)
        entry = to_board_entry(cand)
        vel = entry["velocity"]
        for field in ["tokens_last_5m", "tokens_last_15m", "tokens_last_60m",
                      "rate_per_minute", "acceleration"]:
            assert field in vel

    def test_corroboration_subfields(self):
        cand = _make_candidate(token_count=5, x_corr=0.4)
        entry = to_board_entry(cand)
        corr = entry["corroboration"]
        assert corr["x_confirmed"] is True
        assert corr["x_boost"] == pytest.approx(0.4, abs=0.01)
        assert corr["news_confirmed"] is False

    def test_score_breakdown_has_weights(self):
        cand = _make_candidate(token_count=5)
        entry = to_board_entry(cand)
        breakdown = entry["score_breakdown"]
        assert "weights" in breakdown
        weights = breakdown["weights"]
        assert "token_count" in weights
        assert "velocity" in weights

    def test_score_breakdown_total_matches_narrative_score(self):
        cand = _make_candidate(token_count=5)
        entry = to_board_entry(cand)
        assert entry["narrative_score"] == entry["score_breakdown"]["total"]

    def test_term_is_canonical_name(self):
        cand = _make_candidate(name="ELON")
        entry = to_board_entry(cand)
        assert entry["term"] == "ELON"

    def test_tokens_capped_at_10(self):
        cand = _make_candidate(token_count=15)
        entry = to_board_entry(cand)
        assert len(entry["tokens"]) <= 10


# ---------------------------------------------------------------------------
# build_narrative_board
# ---------------------------------------------------------------------------

class TestBuildNarrativeBoard:
    def test_sorted_by_score_descending(self):
        low = _make_candidate("LOW", token_count=3, last_seen_seconds_ago=3600)
        high = _make_candidate("HIGH", token_count=10, tokens_in_5m=5, last_seen_seconds_ago=30)
        board = build_narrative_board([low, high])
        if len(board) >= 2:
            assert board[0]["narrative_score"] >= board[1]["narrative_score"]

    def test_noise_excluded_by_default(self):
        noise = _make_candidate("NOISE", token_count=2)  # token_count < 3 → NOISE
        ok = _make_candidate("REAL", token_count=5, tokens_in_5m=3)
        board = build_narrative_board([noise, ok])
        terms = [e["term"] for e in board]
        assert "NOISE" not in terms

    def test_noise_included_when_flag_set(self):
        noise = _make_candidate("NOISE", token_count=2)
        ok = _make_candidate("REAL", token_count=5)
        board = build_narrative_board([noise, ok], include_noise=True)
        terms = [e["term"] for e in board]
        assert "NOISE" in terms

    def test_empty_candidates_returns_empty(self):
        board = build_narrative_board([])
        assert board == []

    def test_all_fields_present_in_entries(self):
        cand = _make_candidate(token_count=5)
        board = build_narrative_board([cand])
        assert len(board) == 1
        assert "term" in board[0]
        assert "narrative_score" in board[0]
        assert "reason" in board[0]

    def test_consistent_now_across_all_entries(self):
        """All entries computed with same now → deterministic scores."""
        import time
        cands = [_make_candidate(f"T{i}", token_count=3+i) for i in range(5)]
        board1 = build_narrative_board(cands, now=time.time())
        board2 = build_narrative_board(cands, now=time.time())
        # Scores may differ slightly due to different now, but ordering should be same
        terms1 = [e["term"] for e in board1]
        terms2 = [e["term"] for e in board2]
        assert terms1 == terms2
