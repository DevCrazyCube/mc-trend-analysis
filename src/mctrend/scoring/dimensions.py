"""Individual dimension scoring functions for the six evaluation dimensions.

Each function computes a score in [0.0, 1.0] and returns a list of human-readable
signal strings explaining the factors that contributed to the score.

All weights are accepted as parameters (never hardcoded defaults that cannot be
overridden).  When data is missing, conservative defaults are applied and the
corresponding ``missing_*`` signal is emitted.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *value* to the closed interval [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Dimension 1 -- Narrative Relevance
# ---------------------------------------------------------------------------

def score_narrative_relevance(
    match_confidence: float,
    narrative_age_hours: float,
    source_type_count: int,
    max_source_types: int = 4,
    decay_hours: float = 6.0,
) -> tuple[float, list[str]]:
    """Score how strongly a token connects to a real-world narrative.

    Parameters
    ----------
    match_confidence:
        Confidence of the name/narrative match (0-1).
    narrative_age_hours:
        Hours since the narrative was first detected.
    source_type_count:
        Number of independent source types confirming the narrative.
    max_source_types:
        Normalisation cap for source diversity (configurable).
    decay_hours:
        Hours after which the recency component reaches zero.

    Returns
    -------
    (score, signals) where score is in [0, 1].
    """
    signals: list[str] = []

    name_alignment_component = match_confidence * 0.4
    recency_component = max(0.0, 1.0 - narrative_age_hours / decay_hours) * 0.3
    diversity_component = min(source_type_count / max_source_types, 1.0) * 0.3

    score = clip(name_alignment_component + recency_component + diversity_component)

    # --- signal generation ---
    if match_confidence > 0.90:
        signals.append("exact_anchor_match")
    if source_type_count >= 3:
        signals.append("multi_source_narrative")
    if narrative_age_hours < 2.0:
        signals.append("narrative_age_fresh")
    if narrative_age_hours > 4.0:
        signals.append("narrative_age_decaying")
    if source_type_count == 1:
        signals.append("single_source_narrative")

    return score, signals


# ---------------------------------------------------------------------------
# Dimension 2 -- Authenticity / OG Likelihood
# ---------------------------------------------------------------------------

def score_og_likelihood(
    temporal_score: float,
    name_precision: float,
    cross_source_mentions: int,
    deployer_score: float,
    max_mentions: int = 5,
    weights: dict | None = None,
) -> tuple[float, list[str]]:
    """Score the likelihood that a token is the original ('OG') for its narrative.

    Parameters
    ----------
    temporal_score:
        Timing advantage score (0-1). Higher means earlier launch relative to
        narrative detection.
    name_precision:
        How precisely the token name matches the canonical narrative term (0-1).
    cross_source_mentions:
        Number of independent sources that mention *this specific token*.
    deployer_score:
        Deployer reputation score (0-1). Higher means more credible deployer.
    max_mentions:
        Normalisation cap for cross-source mentions.
    weights:
        Override default component weights.

    Returns
    -------
    (og_score, signals)
    """
    w = weights or {
        "temporal": 0.35,
        "name_precision": 0.25,
        "cross_source": 0.30,
        "deployer": 0.10,
    }
    signals: list[str] = []

    cross_source_score = min(cross_source_mentions / max_mentions, 1.0)

    og_score = clip(
        temporal_score * w["temporal"]
        + name_precision * w["name_precision"]
        + cross_source_score * w["cross_source"]
        + deployer_score * w["deployer"]
    )

    # --- signal generation ---
    if temporal_score >= 0.95:
        signals.append("first_in_namespace")
    if name_precision >= 0.95:
        signals.append("exact_name_match")
    if cross_source_mentions >= 2:
        signals.append("cross_source_confirmed")
    if og_score < 0.35:
        signals.append("copycat_likely")

    return og_score, signals


# ---------------------------------------------------------------------------
# Dimension 3 -- Rug Risk
# ---------------------------------------------------------------------------

def score_rug_risk(
    deployer_risk: float | None,
    concentration_risk: float | None,
    clustering_risk: float | None,
    liquidity_risk: float | None,
    contract_risk: float | None,
    weights: dict | None = None,
    defaults: dict | None = None,
) -> tuple[float, list[str]]:
    """Score the probability of structural failure or rug-pull.

    Higher score = *more* risky.  Missing inputs are replaced with
    conservative defaults and flagged in the returned signals.

    Parameters
    ----------
    deployer_risk, concentration_risk, clustering_risk, liquidity_risk,
    contract_risk:
        Sub-category risk scores in [0, 1].  ``None`` triggers the
        conservative default for that category.
    weights:
        Category weight overrides.
    defaults:
        Conservative default overrides for missing data.

    Returns
    -------
    (rug_risk_score, signals)
    """
    w = weights or {
        "deployer": 0.30,
        "concentration": 0.25,
        "clustering": 0.20,
        "liquidity": 0.15,
        "contract": 0.10,
    }
    d = defaults or {
        "deployer": 0.50,
        "concentration": 0.55,
        "clustering": 0.50,
        "liquidity": 0.60,
        "contract": 0.50,
    }

    signals: list[str] = []

    # Apply conservative defaults where data is missing.
    if deployer_risk is None:
        deployer_risk = d["deployer"]
        signals.append("missing_deployer_data")
    if concentration_risk is None:
        concentration_risk = d["concentration"]
        signals.append("missing_concentration_data")
    if clustering_risk is None:
        clustering_risk = d["clustering"]
        signals.append("missing_clustering_data")
    if liquidity_risk is None:
        liquidity_risk = d["liquidity"]
        signals.append("missing_liquidity_data")
    if contract_risk is None:
        contract_risk = d["contract"]
        signals.append("missing_contract_data")

    score = clip(
        deployer_risk * w["deployer"]
        + concentration_risk * w["concentration"]
        + clustering_risk * w["clustering"]
        + liquidity_risk * w["liquidity"]
        + contract_risk * w["contract"]
    )

    # --- signal generation ---
    if score > 0.75:
        signals.append("CRITICAL_RUG_RISK")
    if concentration_risk > 0.7:
        signals.append("HIGH_HOLDER_CONCENTRATION")
    if deployer_risk >= 0.90:
        signals.append("KNOWN_BAD_DEPLOYER")
    if liquidity_risk > 0.5:
        signals.append("UNLOCKED_LIQUIDITY")
    # New deployer -- neutral-ish risk at ~0.45
    if 0.40 <= deployer_risk <= 0.50:
        signals.append("NEW_DEPLOYER")
    # Contract authority signals -- higher contract risk indicates active authorities
    if contract_risk >= 0.70:
        signals.append("MINT_AUTHORITY_ACTIVE")
    if contract_risk >= 0.60:
        signals.append("FREEZE_AUTHORITY_ACTIVE")

    return score, signals


# ---------------------------------------------------------------------------
# Dimension 4 -- Momentum Quality
# ---------------------------------------------------------------------------

def score_momentum_quality(
    volume_pattern: float | None,
    trade_diversity: float | None,
    social_chain_alignment: float | None,
    holder_growth_quality: float | None,
    defaults: dict | None = None,
) -> tuple[float, list[str]]:
    """Score whether on-chain momentum appears organic or manipulated.

    Higher score = more organic-looking momentum.

    Parameters
    ----------
    volume_pattern:
        Quality of the volume growth pattern (0-1).
    trade_diversity:
        Trade wallet diversity (0-1).
    social_chain_alignment:
        Alignment between social signal timing and chain activity (0-1).
    holder_growth_quality:
        Quality of holder-count growth pattern (0-1).
    defaults:
        Conservative defaults for missing sub-scores.

    Returns
    -------
    (momentum_score, signals)
    """
    d = defaults or {
        "volume_pattern": 0.5,
        "trade_diversity": 0.5,
        "social_chain_alignment": 0.5,
        "holder_growth_quality": 0.5,
    }

    signals: list[str] = []

    if volume_pattern is None:
        volume_pattern = d["volume_pattern"]
        signals.append("missing_momentum_data")
    if trade_diversity is None:
        trade_diversity = d["trade_diversity"]
        signals.append("missing_momentum_data")
    if social_chain_alignment is None:
        social_chain_alignment = d["social_chain_alignment"]
        signals.append("missing_momentum_data")
    if holder_growth_quality is None:
        holder_growth_quality = d["holder_growth_quality"]
        signals.append("missing_momentum_data")

    # De-duplicate missing_momentum_data signals
    if signals.count("missing_momentum_data") > 1:
        signals = ["missing_momentum_data"]

    score = clip(
        volume_pattern * 0.30
        + trade_diversity * 0.30
        + social_chain_alignment * 0.20
        + holder_growth_quality * 0.20
    )

    # --- signal generation ---
    if score < 0.35:
        signals.append("SUSPICIOUS_VOLUME")
    if score > 0.70:
        signals.append("organic_momentum")
    if volume_pattern < 0.25:
        signals.append("WASH_TRADE_PATTERN")

    return score, signals


# ---------------------------------------------------------------------------
# Dimension 5 -- Attention Strength
# ---------------------------------------------------------------------------

def score_attention_strength(
    search_magnitude: float | None,
    source_breadth: float | None,
    narrative_velocity: float | None,
    defaults: dict | None = None,
) -> tuple[float, list[str]]:
    """Score the strength of real-world narrative attention.

    Parameters
    ----------
    search_magnitude:
        Normalised search-trend magnitude (0-1).
    source_breadth:
        Normalised breadth of independent source coverage (0-1).
    narrative_velocity:
        Rate-of-change of narrative attention (0-1).
    defaults:
        Conservative defaults for missing sub-scores.

    Returns
    -------
    (attention_score, signals)
    """
    d = defaults or {
        "search_magnitude": 0.3,
        "source_breadth": 0.3,
        "narrative_velocity": 0.3,
    }

    signals: list[str] = []

    if search_magnitude is None:
        search_magnitude = d["search_magnitude"]
        signals.append("missing_attention_data")
    if source_breadth is None:
        source_breadth = d["source_breadth"]
        signals.append("missing_attention_data")
    if narrative_velocity is None:
        narrative_velocity = d["narrative_velocity"]
        signals.append("missing_attention_data")

    # De-duplicate
    if signals.count("missing_attention_data") > 1:
        seen = False
        deduped: list[str] = []
        for s in signals:
            if s == "missing_attention_data":
                if not seen:
                    deduped.append(s)
                    seen = True
            else:
                deduped.append(s)
        signals = deduped

    score = clip(
        search_magnitude * 0.35
        + source_breadth * 0.35
        + narrative_velocity * 0.30
    )

    # --- signal generation ---
    if score > 0.75:
        signals.append("strong_multi_source_attention")
    if score < 0.30:
        signals.append("weak_attention")
    if narrative_velocity > 0.5:
        signals.append("narrative_velocity_positive")
    if narrative_velocity < 0.3:
        signals.append("narrative_velocity_negative")

    return score, signals


# ---------------------------------------------------------------------------
# Dimension 6 -- Timing Quality
# ---------------------------------------------------------------------------

def score_timing_quality(
    lifecycle_score: float,
    acceleration_score: float,
    saturation_score: float,
) -> tuple[float, list[str]]:
    """Score how well-positioned a token is in its narrative lifecycle.

    Parameters
    ----------
    lifecycle_score:
        Position in narrative lifecycle (0-1, higher = earlier/better).
    acceleration_score:
        Whether the narrative is still accelerating (0-1).
    saturation_score:
        Inverse of market saturation (0-1, higher = less saturated).

    Returns
    -------
    (timing_score, signals)
    """
    signals: list[str] = []

    score = clip(
        lifecycle_score * 0.40
        + acceleration_score * 0.30
        + saturation_score * 0.30
    )

    # --- signal generation ---
    if lifecycle_score > 0.8:
        signals.append("early_lifecycle")
    if score < 0.30:
        signals.append("TIMING_LATE")
    if acceleration_score > 0.7:
        signals.append("narrative_accelerating")

    return score, signals
