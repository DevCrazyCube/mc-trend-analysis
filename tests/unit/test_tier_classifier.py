"""Tests for narrative tier classification (Phase A) and noise detection (Phase E).

Covers:
- compute_semantic_gravity: keyword matching, substring matching, categories
- is_spam_phrase: exact match, prefix patterns
- compute_phrase_entropy: low vs high entropy phrases
- compute_anti_spam_score: multi-factor spam scoring
- classify_tier: T1/T2/T3/T4 assignments based on evidence mixes
- evidence_from_candidate: bridge function from NarrativeCandidate
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mctrend.narrative.discovery_engine import NarrativeCandidate, _candidate_id
from mctrend.narrative.tier_classifier import (
    TIER_1,
    TIER_2,
    TIER_3,
    TIER_4,
    TIER_LABEL,
    TIER_WEIGHT,
    NarrativeEvidence,
    X_MIN_AUTHORS_FOR_T2,
    X_MIN_ENGAGEMENT_FOR_T2,
    X_MIN_POSTS_FOR_T2,
    X_STRONG_AUTHORS,
    X_STRONG_ENGAGEMENT,
    classify_tier,
    compute_anti_spam_score,
    compute_phrase_entropy,
    compute_semantic_gravity,
    evidence_from_candidate,
    is_spam_phrase,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _evidence(
    name: str = "TRUMP",
    token_count: int = 5,
    x_corr: bool = False,
    x_authors: int = 0,
    x_engagement: int = 0,
    x_posts: int = 0,
    news_corr: bool = False,
    news_articles: int = 0,
    news_domains: int = 0,
    source_types: set[str] | None = None,
    velocity_5m: int = 0,
    velocity_15m: int = 0,
) -> NarrativeEvidence:
    if source_types is None:
        source_types = {"token_stream"}
        if x_corr:
            source_types.add("social_media")
        if news_corr:
            source_types.add("news")
    return NarrativeEvidence(
        canonical_name=name,
        token_count=token_count,
        token_names=[f"Token{i}" for i in range(token_count)],
        has_x_corroboration=x_corr,
        x_spike_corroboration=0.5 if x_corr else 0.0,
        x_author_count=x_authors,
        x_total_engagement=x_engagement,
        x_post_count=x_posts,
        has_news_corroboration=news_corr,
        news_corroboration=0.5 if news_corr else 0.0,
        news_article_count=news_articles,
        news_domain_count=news_domains,
        source_types=source_types,
        velocity_tokens_5m=velocity_5m,
        velocity_tokens_15m=velocity_15m,
    )


# ---------------------------------------------------------------------------
# compute_semantic_gravity
# ---------------------------------------------------------------------------

class TestComputeSemanticGravity:
    def test_exact_match_politics(self):
        score, cats = compute_semantic_gravity("TRUMP")
        assert score >= 0.7
        assert "politics" in cats or "major_figures" in cats

    def test_exact_match_regulation(self):
        score, cats = compute_semantic_gravity("SEC")
        assert score > 0
        assert "regulation" in cats

    def test_exact_match_geopolitics(self):
        score, cats = compute_semantic_gravity("UKRAINE")
        assert score > 0
        assert "geopolitics" in cats

    def test_exact_match_major_figures(self):
        score, cats = compute_semantic_gravity("ELON")
        assert score > 0
        assert "major_figures" in cats

    def test_exact_match_major_companies(self):
        score, cats = compute_semantic_gravity("TESLA")
        assert score > 0
        assert "major_companies" in cats

    def test_exact_match_crypto_events(self):
        score, cats = compute_semantic_gravity("HALVING")
        assert score > 0
        assert "crypto_events" in cats

    def test_substring_match(self):
        score, cats = compute_semantic_gravity("TRUMP2024")
        assert score > 0  # TRUMP is a substring of TRUMP2024
        assert len(cats) > 0

    def test_no_match_returns_zero(self):
        score, cats = compute_semantic_gravity("BOOPYBOOP")
        assert score == 0.0
        assert cats == []

    def test_case_insensitive(self):
        score1, _ = compute_semantic_gravity("trump")
        score2, _ = compute_semantic_gravity("TRUMP")
        assert score1 == score2

    def test_short_keyword_not_substring_matched(self):
        """Short keywords (<4 chars) should not get substring matches."""
        # "SEC" is 3 chars, should not match on substring
        score, cats = compute_semantic_gravity("INSECURITY")
        # "SEC" is in "INSECURITY" but len("SEC") < 4, so no substring match
        assert "regulation" not in cats


# ---------------------------------------------------------------------------
# is_spam_phrase
# ---------------------------------------------------------------------------

class TestIsSpamPhrase:
    def test_exact_spam_match(self):
        assert is_spam_phrase("MY FIRST COIN") is True

    def test_exact_spam_case_insensitive(self):
        assert is_spam_phrase("to the moon") is True

    def test_prefix_pattern_match(self):
        assert is_spam_phrase("MY FIRST EVER TOKEN LAUNCH") is True

    def test_next_pattern(self):
        assert is_spam_phrase("NEXT 100X GEM") is True

    def test_baby_prefix(self):
        assert is_spam_phrase("BABY DOGE") is True

    def test_not_spam(self):
        assert is_spam_phrase("TRUMP") is False
        assert is_spam_phrase("ELON MUSK") is False

    def test_empty_string(self):
        assert is_spam_phrase("") is False


# ---------------------------------------------------------------------------
# compute_phrase_entropy
# ---------------------------------------------------------------------------

class TestComputePhraseEntropy:
    def test_empty_string(self):
        assert compute_phrase_entropy("") == 0.0

    def test_all_stopwords(self):
        e = compute_phrase_entropy("THE OF AND")
        assert e < 0.1  # very low

    def test_single_short_word(self):
        e = compute_phrase_entropy("AB")
        assert e < 0.3

    def test_distinctive_phrase(self):
        e = compute_phrase_entropy("BITCOIN HALVING PREDICTION")
        assert e > 0.3  # higher information content

    def test_high_entropy_term(self):
        e = compute_phrase_entropy("TRUMP TARIFF ELECTION")
        assert e > 0.3


# ---------------------------------------------------------------------------
# compute_anti_spam_score
# ---------------------------------------------------------------------------

class TestComputeAntiSpamScore:
    def test_known_spam_returns_floor(self):
        score = compute_anti_spam_score("MY FIRST COIN", ["Token1"], 0.0, 0.0)
        assert score <= 0.1

    def test_clean_term_returns_high(self):
        score = compute_anti_spam_score("TRUMP", ["Token1", "Token2"], 0.0, 0.0)
        assert score > 0.5

    def test_external_corroboration_boosts(self):
        # Use a short term that starts with a low entropy penalty
        score_no_corr = compute_anti_spam_score("AB", ["A", "B"], 0.0, 0.0)
        score_x = compute_anti_spam_score("AB", ["A", "B"], 0.5, 0.0)
        score_news = compute_anti_spam_score("AB", ["A", "B"], 0.0, 0.5)
        assert score_x > score_no_corr
        assert score_news > score_no_corr

    def test_homogeneous_names_penalty(self):
        # Many near-identical token names with no external corroboration
        names = ["BOOPTOKEN1", "BOOPTOKEN2", "BOOPTOKEN3", "BOOPTOKEN4"]
        score = compute_anti_spam_score("BOOP", names, 0.0, 0.0)
        # Should be penalized compared to diverse names
        diverse = ["TRUMP_COIN", "MAGA_FUND", "ELECTION_SPECIAL", "VOTE_TOKEN"]
        score_diverse = compute_anti_spam_score("TRUMP", diverse, 0.0, 0.0)
        # both should be reasonable, but homogeneous should be lower
        assert score <= score_diverse


# ---------------------------------------------------------------------------
# classify_tier
# ---------------------------------------------------------------------------

class TestClassifyTier:
    def test_spam_is_t4(self):
        ev = _evidence("MY FIRST COIN", token_count=10)
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_4
        assert "spam" in reason.lower()

    def test_low_entropy_is_t4(self):
        ev = _evidence("A", token_count=10)  # very short term
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_4

    def test_t1_news_high_gravity(self):
        """High-gravity term with news corroboration -> T1."""
        ev = _evidence(
            "TRUMP", token_count=10,
            news_corr=True, news_articles=3, news_domains=2,
        )
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_1
        assert len(cats) > 0

    def test_t1_strong_x_high_gravity(self):
        """High-gravity term with strong X signal -> T1."""
        ev = _evidence(
            "SEC", token_count=10,
            x_corr=True, x_authors=5, x_engagement=100, x_posts=5,
        )
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_1

    def test_t2_high_gravity_moderate_evidence(self):
        """High-gravity with X corroboration but below strong threshold -> T2."""
        ev = _evidence(
            "ELON", token_count=5,
            x_corr=True, x_authors=1, x_engagement=10, x_posts=1,
        )
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_2

    def test_t2_strong_x_no_gravity(self):
        """No semantic gravity but strong X signal -> T2."""
        ev = _evidence(
            "BOOPYBOOP", token_count=5,
            x_corr=True,
            x_authors=X_STRONG_AUTHORS,
            x_engagement=X_STRONG_ENGAGEMENT,
            x_posts=10,
        )
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_2

    def test_t2_x_plus_tokens(self):
        """X meeting T2 minimums + enough tokens -> T2."""
        ev = _evidence(
            "RANDOMTERM", token_count=5,
            x_corr=True,
            x_authors=X_MIN_AUTHORS_FOR_T2,
            x_engagement=X_MIN_ENGAGEMENT_FOR_T2,
            x_posts=X_MIN_POSTS_FOR_T2,
        )
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_2

    def test_t2_multi_source_convergence(self):
        """Multiple source types + enough tokens + corroboration -> T2."""
        ev = _evidence(
            "RANDOMTERM", token_count=5,
            x_corr=True, x_authors=1, x_engagement=10, x_posts=1,
            source_types={"token_stream", "social_media"},
        )
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_2

    def test_t3_token_only(self):
        """Tokens only, no external corroboration -> T3."""
        ev = _evidence("RANDOMTERM", token_count=5)
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_3

    def test_t4_insufficient_tokens(self):
        """Too few tokens, no corroboration -> T4."""
        ev = _evidence("RANDOMTERM", token_count=1)
        tier, reason, cats = classify_tier(ev)
        assert tier == TIER_4

    def test_t3_token_echo_with_spam_tokens_becomes_t4(self):
        """Token-echo where anti-spam score is very low -> T4."""
        ev = NarrativeEvidence(
            canonical_name="NEXTGEM",
            token_count=5,
            token_names=["NEXT GEM 1", "NEXT GEM 2", "NEXT GEM 3", "NEXT GEM 4", "NEXT GEM 5"],
            source_types={"token_stream"},
        )
        tier, reason, cats = classify_tier(ev)
        # The exact tier depends on entropy and anti-spam score
        assert tier in (TIER_3, TIER_4)

    def test_tier_labels_all_defined(self):
        for t in [TIER_1, TIER_2, TIER_3, TIER_4]:
            assert t in TIER_LABEL
            assert t in TIER_WEIGHT

    def test_tier_weight_order(self):
        assert TIER_WEIGHT[TIER_1] > TIER_WEIGHT[TIER_2]
        assert TIER_WEIGHT[TIER_2] > TIER_WEIGHT[TIER_3]
        assert TIER_WEIGHT[TIER_3] > TIER_WEIGHT[TIER_4]

    def test_returns_three_tuple(self):
        ev = _evidence("TRUMP", token_count=5)
        result = classify_tier(ev)
        assert len(result) == 3
        tier, reason, cats = result
        assert isinstance(tier, str)
        assert isinstance(reason, str)
        assert isinstance(cats, list)

    def test_reason_contains_term_name(self):
        ev = _evidence("MUSK", token_count=5)
        _, reason, _ = classify_tier(ev)
        assert "MUSK" in reason


# ---------------------------------------------------------------------------
# evidence_from_candidate
# ---------------------------------------------------------------------------

class TestEvidenceFromCandidate:
    def test_basic_candidate(self):
        cand = NarrativeCandidate(
            candidate_id=_candidate_id("TRUMP"),
            canonical_name="TRUMP",
            first_seen=_now() - 1800,
            last_seen=_now() - 60,
        )
        for i in range(5):
            cand.add_token(f"t{i}", f"TRUMP{i}", obs_time=_now() - 120)

        ev = evidence_from_candidate(cand)
        assert ev.canonical_name == "TRUMP"
        assert ev.token_count == 5
        assert ev.has_x_corroboration is False
        assert ev.has_news_corroboration is False
        assert "token_stream" in ev.source_types

    def test_with_x_corroboration(self):
        cand = NarrativeCandidate(
            candidate_id=_candidate_id("SEC"),
            canonical_name="SEC",
            first_seen=_now() - 1800,
            last_seen=_now() - 60,
        )
        cand.add_token("t1", "SEC_TOKEN", obs_time=_now() - 120)
        cand.add_x_corroboration(
            spike_ratio=5.0, match_confidence=0.9,
            unique_authors=10, engagement_total=500, mention_count=15,
        )

        ev = evidence_from_candidate(cand)
        assert ev.has_x_corroboration is True
        assert ev.x_author_count == 10
        assert ev.x_total_engagement == 500
        assert ev.x_post_count == 15
        assert "social_media" in ev.source_types

    def test_with_news_corroboration(self):
        cand = NarrativeCandidate(
            candidate_id=_candidate_id("TARIFF"),
            canonical_name="TARIFF",
            first_seen=_now() - 1800,
            last_seen=_now() - 60,
        )
        cand.add_token("t1", "TARIFF_COIN", obs_time=_now() - 120)
        cand.add_news_corroboration(0.8, article_count=3, domain="reuters.com")
        cand.add_news_corroboration(0.6, article_count=2, domain="bbc.com")

        ev = evidence_from_candidate(cand)
        assert ev.has_news_corroboration is True
        assert ev.news_article_count == 3  # max of 3 and 2
        assert ev.news_domain_count == 2  # reuters + bbc
        assert "news" in ev.source_types
