"""Tests for narrative quality scoring (Phase B).

Covers:
- compute_narrative_quality: full quality breakdown
- Individual sub-score functions
- Weight sum validation
- Edge cases: no evidence, spam, full evidence
"""
from __future__ import annotations

import pytest

from mctrend.narrative.quality_scorer import (
    W_ANTI_SPAM,
    W_SEMANTIC_GRAVITY,
    W_SOCIAL_SCALE,
    W_SOURCE_DIVERSITY,
    W_SOURCE_GRAVITY,
    W_VELOCITY,
    QualityBreakdown,
    compute_narrative_quality,
)
from mctrend.narrative.tier_classifier import NarrativeEvidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    acceleration: str = "flat",
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
        acceleration=acceleration,
    )


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        total = (
            W_SOURCE_GRAVITY + W_SOURCE_DIVERSITY + W_SOCIAL_SCALE
            + W_VELOCITY + W_SEMANTIC_GRAVITY + W_ANTI_SPAM
        )
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# compute_narrative_quality
# ---------------------------------------------------------------------------

class TestComputeNarrativeQuality:
    def test_returns_quality_breakdown(self):
        ev = _evidence("TRUMP", token_count=5)
        result = compute_narrative_quality(ev)
        assert isinstance(result, QualityBreakdown)
        assert hasattr(result, "total")
        assert hasattr(result, "source_gravity")
        assert hasattr(result, "social_scale")

    def test_total_in_range(self):
        ev = _evidence("ANYTHING", token_count=1)
        result = compute_narrative_quality(ev)
        assert 0.0 <= result.total <= 1.0

    def test_spam_has_low_quality(self):
        ev = _evidence("MY FIRST COIN", token_count=10)
        result = compute_narrative_quality(ev)
        # Anti-spam should be very low, dragging quality down
        assert result.anti_spam < 0.2
        assert result.total < 0.5

    def test_news_corroborated_has_high_source_gravity(self):
        ev = _evidence(
            "TRUMP", token_count=10,
            news_corr=True, news_articles=3, news_domains=2,
        )
        result = compute_narrative_quality(ev)
        assert result.source_gravity >= 0.9

    def test_x_strong_has_moderate_source_gravity(self):
        ev = _evidence(
            "TERM", token_count=5,
            x_corr=True, x_authors=10, x_engagement=200, x_posts=10,
        )
        result = compute_narrative_quality(ev)
        assert result.source_gravity >= 0.5

    def test_token_only_has_low_source_gravity(self):
        ev = _evidence("TERM", token_count=5)
        result = compute_narrative_quality(ev)
        assert result.source_gravity <= 0.2

    def test_multi_source_has_higher_diversity(self):
        ev_single = _evidence("TERM", token_count=5)
        ev_multi = _evidence(
            "TERM", token_count=5,
            x_corr=True, x_authors=3, x_engagement=50, x_posts=3,
            source_types={"token_stream", "social_media"},
        )
        r1 = compute_narrative_quality(ev_single)
        r2 = compute_narrative_quality(ev_multi)
        assert r2.source_diversity > r1.source_diversity

    def test_high_velocity_boosts_score(self):
        ev_slow = _evidence("TERM", token_count=5, velocity_5m=0)
        ev_fast = _evidence("TERM", token_count=5, velocity_5m=8)
        r1 = compute_narrative_quality(ev_slow)
        r2 = compute_narrative_quality(ev_fast)
        assert r2.velocity > r1.velocity
        assert r2.total > r1.total

    def test_acceleration_bonus(self):
        ev_flat = _evidence("TERM", token_count=5, velocity_5m=5, acceleration="flat")
        ev_accel = _evidence("TERM", token_count=5, velocity_5m=5, acceleration="increasing")
        r1 = compute_narrative_quality(ev_flat)
        r2 = compute_narrative_quality(ev_accel)
        assert r2.velocity >= r1.velocity

    def test_semantic_gravity_for_political_term(self):
        ev = _evidence("TRUMP", token_count=5)
        result = compute_narrative_quality(ev)
        assert result.semantic_gravity > 0.0
        assert len(result.matched_categories) > 0

    def test_no_semantic_gravity_for_random(self):
        ev = _evidence("BOOPYBOOP", token_count=5)
        result = compute_narrative_quality(ev)
        assert result.semantic_gravity == 0.0
        assert result.matched_categories == []

    def test_full_evidence_high_quality(self):
        """Best-case scenario: news, X, high gravity, fast velocity."""
        ev = _evidence(
            "TRUMP", token_count=20,
            news_corr=True, news_articles=5, news_domains=3,
            x_corr=True, x_authors=15, x_engagement=800, x_posts=20,
            source_types={"token_stream", "social_media", "news"},
            velocity_5m=8, velocity_15m=20, acceleration="increasing",
        )
        result = compute_narrative_quality(ev)
        assert result.total > 0.7
        assert result.source_gravity > 0.9
        assert result.source_diversity == 1.0
        assert result.social_scale > 0.5

    def test_social_scale_zero_without_x(self):
        ev = _evidence("TERM", token_count=5)
        result = compute_narrative_quality(ev)
        assert result.social_scale == 0.0

    def test_social_scale_scales_with_authors(self):
        ev_few = _evidence("TERM", token_count=5, x_corr=True, x_authors=2, x_engagement=10, x_posts=2)
        ev_many = _evidence("TERM", token_count=5, x_corr=True, x_authors=15, x_engagement=500, x_posts=15)
        r1 = compute_narrative_quality(ev_few)
        r2 = compute_narrative_quality(ev_many)
        assert r2.social_scale > r1.social_scale
