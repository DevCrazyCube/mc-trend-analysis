"""Narrative quality score — deterministic multi-factor 0.0–1.0 metric.

Combines six sub-scores into a single quality metric that answers:
"How confident should we be that this narrative represents a real-world
attention shift rather than token-stream noise?"

Sub-scores
----------
source_gravity  — weight of evidence sources (news > X > token-only)
source_diversity — how many distinct source types contribute evidence
social_scale    — X author diversity, post count, engagement depth
velocity        — token spawn rate (higher = more attention)
semantic_gravity — topic relevance to real-world categories
anti_spam       — inverse spam likelihood

All weights and thresholds are module-level constants.
All logic is deterministic — no LLM, no randomness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mctrend.narrative.tier_classifier import (
    NarrativeEvidence,
    compute_anti_spam_score,
    compute_semantic_gravity,
)


# ---------------------------------------------------------------------------
# Sub-score weights (must sum to 1.0)
# ---------------------------------------------------------------------------

W_SOURCE_GRAVITY = 0.25
W_SOURCE_DIVERSITY = 0.15
W_SOCIAL_SCALE = 0.20
W_VELOCITY = 0.15
W_SEMANTIC_GRAVITY = 0.15
W_ANTI_SPAM = 0.10

# Sanity: weights sum to 1.0
assert abs(
    W_SOURCE_GRAVITY + W_SOURCE_DIVERSITY + W_SOCIAL_SCALE
    + W_VELOCITY + W_SEMANTIC_GRAVITY + W_ANTI_SPAM - 1.0
) < 1e-9


# ---------------------------------------------------------------------------
# Source gravity thresholds
# ---------------------------------------------------------------------------

# News evidence scores highest (external reality)
SOURCE_GRAVITY_NEWS = 1.0
# X with sufficient author diversity
SOURCE_GRAVITY_X_STRONG = 0.7
# X with minimal evidence
SOURCE_GRAVITY_X_WEAK = 0.3
# Token-stream only (no external)
SOURCE_GRAVITY_TOKEN_ONLY = 0.1

# Minimum X metrics for "strong" social evidence
X_STRONG_AUTHORS_FOR_QUALITY = 5
X_STRONG_ENGAGEMENT_FOR_QUALITY = 100

# Social scale normalization references
SOCIAL_AUTHOR_SATURATION = 20      # 20+ authors → score 1.0
SOCIAL_ENGAGEMENT_SATURATION = 1000  # 1000+ total engagement → score 1.0
SOCIAL_POST_SATURATION = 20         # 20+ posts → score 1.0

# Velocity normalization
VELOCITY_5M_SATURATION = 10   # 10+ tokens in 5 min → score 1.0
VELOCITY_15M_SATURATION = 25  # 25+ tokens in 15 min → score 1.0

# News diversity bonus
NEWS_MULTI_DOMAIN_BONUS = 0.15  # bonus if 2+ news domains


# ---------------------------------------------------------------------------
# Quality sub-scores
# ---------------------------------------------------------------------------

@dataclass
class QualityBreakdown:
    """All sub-scores composing the narrative quality metric."""

    source_gravity: float
    source_diversity: float
    social_scale: float
    velocity: float
    semantic_gravity: float
    anti_spam: float
    total: float
    matched_categories: list[str]


def _score_source_gravity(evidence: NarrativeEvidence) -> float:
    """Score based on the highest-weight evidence source available."""
    if evidence.has_news_corroboration or evidence.news_article_count >= 1:
        base = SOURCE_GRAVITY_NEWS
        # Multi-domain news is even stronger
        if evidence.news_domain_count >= 2:
            base = min(1.0, base + NEWS_MULTI_DOMAIN_BONUS)
        return base

    if evidence.has_x_corroboration:
        if (
            evidence.x_author_count >= X_STRONG_AUTHORS_FOR_QUALITY
            and evidence.x_total_engagement >= X_STRONG_ENGAGEMENT_FOR_QUALITY
        ):
            return SOURCE_GRAVITY_X_STRONG
        return SOURCE_GRAVITY_X_WEAK

    return SOURCE_GRAVITY_TOKEN_ONLY


def _score_source_diversity(evidence: NarrativeEvidence) -> float:
    """Score based on how many distinct source types contribute evidence.

    1 source type → 0.3
    2 source types → 0.7
    3+ source types → 1.0
    """
    count = len(evidence.source_types)
    if count >= 3:
        return 1.0
    if count == 2:
        return 0.7
    if count == 1:
        return 0.3
    return 0.0


def _score_social_scale(evidence: NarrativeEvidence) -> float:
    """Score based on X evidence depth: author diversity, engagement, post count.

    Each component is log-scaled and normalized independently, then averaged.
    Returns 0.0 if no X evidence at all.
    """
    if not evidence.has_x_corroboration and evidence.x_post_count == 0:
        return 0.0

    # Author diversity (log-scaled)
    author_score = min(
        1.0,
        math.log1p(evidence.x_author_count) / math.log1p(SOCIAL_AUTHOR_SATURATION),
    )

    # Engagement depth (log-scaled)
    engagement_score = min(
        1.0,
        math.log1p(evidence.x_total_engagement) / math.log1p(SOCIAL_ENGAGEMENT_SATURATION),
    )

    # Post count (log-scaled)
    post_score = min(
        1.0,
        math.log1p(evidence.x_post_count) / math.log1p(SOCIAL_POST_SATURATION),
    )

    # Weighted average: authors matter most (diversity signal), then engagement
    return author_score * 0.4 + engagement_score * 0.35 + post_score * 0.25


def _score_velocity(evidence: NarrativeEvidence) -> float:
    """Score based on token spawn velocity.

    Uses both 5-minute and 15-minute windows; takes the max
    (some narratives have burst patterns, others are sustained).
    """
    v5 = min(1.0, evidence.velocity_tokens_5m / VELOCITY_5M_SATURATION)
    v15 = min(1.0, evidence.velocity_tokens_15m / VELOCITY_15M_SATURATION)

    # Acceleration bonus
    accel_bonus = 0.0
    if evidence.acceleration == "increasing":
        accel_bonus = 0.1

    return min(1.0, max(v5, v15) + accel_bonus)


def _score_semantic_gravity(evidence: NarrativeEvidence) -> tuple[float, list[str]]:
    """Score based on real-world topic category relevance."""
    return compute_semantic_gravity(evidence.canonical_name)


def _score_anti_spam(evidence: NarrativeEvidence) -> float:
    """Score how likely this is NOT spam."""
    return compute_anti_spam_score(
        evidence.canonical_name,
        evidence.token_names,
        evidence.x_spike_corroboration,
        evidence.news_corroboration,
    )


# ---------------------------------------------------------------------------
# Main quality score function
# ---------------------------------------------------------------------------

def compute_narrative_quality(evidence: NarrativeEvidence) -> QualityBreakdown:
    """Compute the narrative quality score from evidence.

    Returns a QualityBreakdown with all sub-scores and the weighted total.
    The total is clamped to [0.0, 1.0].
    """
    source_gravity = _score_source_gravity(evidence)
    source_diversity = _score_source_diversity(evidence)
    social_scale = _score_social_scale(evidence)
    velocity = _score_velocity(evidence)
    semantic_gravity, matched_categories = _score_semantic_gravity(evidence)
    anti_spam = _score_anti_spam(evidence)

    total = (
        source_gravity * W_SOURCE_GRAVITY
        + source_diversity * W_SOURCE_DIVERSITY
        + social_scale * W_SOCIAL_SCALE
        + velocity * W_VELOCITY
        + semantic_gravity * W_SEMANTIC_GRAVITY
        + anti_spam * W_ANTI_SPAM
    )
    total = round(min(1.0, max(0.0, total)), 4)

    return QualityBreakdown(
        source_gravity=round(source_gravity, 4),
        source_diversity=round(source_diversity, 4),
        social_scale=round(social_scale, 4),
        velocity=round(velocity, 4),
        semantic_gravity=round(semantic_gravity, 4),
        anti_spam=round(anti_spam, 4),
        total=total,
        matched_categories=matched_categories,
    )
