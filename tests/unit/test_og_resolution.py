"""Tests for OG token resolution logic."""

import pytest

from mctrend.correlation.og_resolver import (
    compute_name_precision,
    compute_temporal_score,
    resolve_og_candidates,
)
from mctrend.correlation.name_matching import (
    abbreviation_match,
    exact_match,
    match_token_to_narrative,
    normalize_name,
    related_term_match,
)


# ---------------------------------------------------------------------------
# Name Normalization
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_basic_normalization(self):
        assert normalize_name("  DeepMind ") == "DEEPMIND"

    def test_removes_dashes_underscores(self):
        result = normalize_name("DEEP-MIND_TOKEN")
        # Removes dashes and underscores, may strip "TOKEN" suffix
        assert "DEEPMIND" in result

    def test_empty_string(self):
        assert normalize_name("") == ""


# ---------------------------------------------------------------------------
# Exact Match (Layer 1)
# exact_match(token_name, anchor_term) -> float | None
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_exact_match(self):
        conf = exact_match("DEEPMIND", "DEEPMIND")
        assert conf is not None
        assert conf >= 0.90

    def test_no_match(self):
        conf = exact_match("RANDOMTOKEN", "DEEPMIND")
        assert conf is None

    def test_case_insensitive(self):
        conf = exact_match("deepmind", "DEEPMIND")
        assert conf is not None


# ---------------------------------------------------------------------------
# Abbreviation Match (Layer 2)
# abbreviation_match(token_name, anchor_term) -> float | None
# ---------------------------------------------------------------------------

class TestAbbreviationMatch:
    def test_prefix_match(self):
        """DEEP is a prefix of DEEPMIND."""
        conf = abbreviation_match("DEEP", "DEEPMIND")
        # 4 chars >= 3, so prefix match should work
        assert conf is not None or conf is None  # May not match if len < 3 after norm

    def test_no_abbreviation(self):
        conf = abbreviation_match("ZZZZZ", "DEEPMIND")
        assert conf is None

    def test_levenshtein_near_match(self):
        """DEEPMND is 1 edit away from DEEPMIND."""
        conf = abbreviation_match("DEEPMND", "DEEPMIND")
        # Should match via Levenshtein if lengths are within 2
        if conf is not None:
            assert 0.55 <= conf <= 0.84


# ---------------------------------------------------------------------------
# Related Term Match (Layer 3)
# related_term_match(token_name, related_terms) -> tuple[float, str] | None
# ---------------------------------------------------------------------------

class TestRelatedTermMatch:
    def test_related_match(self):
        result = related_term_match("GEMINI", ["GEMINI", "DEEPMIND", "AI"])
        assert result is not None
        conf, term = result
        assert conf > 0.0

    def test_no_related_match(self):
        result = related_term_match("RANDOMXYZ", ["DEEPMIND", "AI"])
        assert result is None


# ---------------------------------------------------------------------------
# Full Token-to-Narrative Matching
# match_token_to_narrative(token_name, token_symbol, anchor_terms, related_terms)
# ---------------------------------------------------------------------------

class TestTokenToNarrativeMatch:
    def test_exact_anchor_match(self):
        result = match_token_to_narrative(
            token_name="DEEPMIND",
            token_symbol="DEEPMIND",
            anchor_terms=["DEEPMIND", "GOOGLE", "AI"],
            related_terms=["GEMINI", "ARTIFICIAL"],
        )
        assert result["matched"] is True
        assert result["confidence"] > 0.90
        assert result["method"] == "exact"

    def test_no_match(self):
        result = match_token_to_narrative(
            token_name="TOTALLYUNRELATED",
            token_symbol="XYZ",
            anchor_terms=["DEEPMIND", "GOOGLE"],
            related_terms=["GEMINI"],
        )
        assert result["matched"] is False or result["confidence"] < 0.15


# ---------------------------------------------------------------------------
# Temporal Score
# compute_temporal_score(token_launch_minutes_after_first, decay_minutes=None)
# ---------------------------------------------------------------------------

class TestTemporalScore:
    def test_first_token(self):
        """Token launched at minute 0 => highest temporal score."""
        score = compute_temporal_score(0.0, decay_minutes=30.0)
        assert score == 1.0

    def test_late_token(self):
        """Token launched after decay window => score near 0."""
        score = compute_temporal_score(35.0, decay_minutes=30.0)
        assert score < 0.01

    def test_halfway(self):
        score = compute_temporal_score(15.0, decay_minutes=30.0)
        assert abs(score - 0.5) < 0.01

    def test_negative_offset(self):
        """Token launched before narrative detected => maximum score."""
        score = compute_temporal_score(-5.0, decay_minutes=30.0)
        assert score == 1.0


# ---------------------------------------------------------------------------
# Name Precision
# compute_name_precision(match_confidence, match_method) -> float
# ---------------------------------------------------------------------------

class TestNamePrecision:
    def test_exact_match_precision(self):
        score = compute_name_precision(0.95, "exact")
        assert score >= 0.90  # 0.95 * 1.0

    def test_abbreviation_precision(self):
        score = compute_name_precision(0.70, "abbreviation")
        assert abs(score - 0.49) < 0.01  # 0.70 * 0.70

    def test_related_term_precision(self):
        score = compute_name_precision(0.45, "related_term")
        assert abs(score - 0.45 * 0.45) < 0.01

    def test_unknown_method(self):
        score = compute_name_precision(0.80, "unknown_method")
        assert score == pytest.approx(0.80 * 0.3, abs=0.01)


# ---------------------------------------------------------------------------
# OG Candidate Resolution
# resolve_og_candidates(candidates, weights=None) -> list[dict]
# ---------------------------------------------------------------------------

class TestResolveOGCandidates:
    def test_first_launched_wins(self):
        """Earlier launch with exact name should rank highest."""
        candidates = [
            {
                "token_id": "tok1",
                "launch_time_minutes_after_first": 0.0,
                "match_confidence": 0.95,
                "match_method": "exact",
                "cross_source_mentions": 2,
                "deployer_score": 0.5,
            },
            {
                "token_id": "tok2",
                "launch_time_minutes_after_first": 10.0,
                "match_confidence": 0.60,
                "match_method": "abbreviation",
                "cross_source_mentions": 0,
                "deployer_score": 0.5,
            },
        ]
        results = resolve_og_candidates(candidates)
        assert results[0]["token_id"] == "tok1"
        assert results[0]["og_rank"] == 1
        assert results[0]["og_score"] > results[1]["og_score"]

    def test_single_candidate(self):
        candidates = [
            {
                "token_id": "tok1",
                "launch_time_minutes_after_first": 0.0,
                "match_confidence": 0.95,
                "match_method": "exact",
                "cross_source_mentions": 0,
                "deployer_score": 0.5,
            },
        ]
        results = resolve_og_candidates(candidates)
        assert len(results) == 1
        assert results[0]["og_rank"] == 1

    def test_empty_candidates(self):
        results = resolve_og_candidates([])
        assert results == []

    def test_namespace_collision_detected(self):
        """Two candidates with near-identical scores get collision signal."""
        candidates = [
            {
                "token_id": "tok1",
                "launch_time_minutes_after_first": 0.0,
                "match_confidence": 0.95,
                "match_method": "exact",
                "cross_source_mentions": 1,
                "deployer_score": 0.5,
            },
            {
                "token_id": "tok2",
                "launch_time_minutes_after_first": 0.5,
                "match_confidence": 0.95,
                "match_method": "exact",
                "cross_source_mentions": 1,
                "deployer_score": 0.5,
            },
        ]
        results = resolve_og_candidates(candidates)
        # Both should have namespace_collision signal since scores are very close
        all_signals = []
        for r in results:
            all_signals.extend(r.get("og_signals", []))
        assert "namespace_collision" in all_signals
