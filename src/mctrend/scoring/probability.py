"""Probability calculations that combine dimension scores into composite estimates.

All formulas follow ``docs/intelligence/probability-framework.md``.  Weights are
accepted as parameters so they can be tuned without code changes.
"""

from __future__ import annotations

from .dimensions import clip


# ---------------------------------------------------------------------------
# P_potential
# ---------------------------------------------------------------------------

def compute_p_potential(
    narrative_relevance: float,
    og_score: float,
    momentum_quality: float,
    attention_strength: float,
    timing_quality: float,
    weights: dict | None = None,
) -> float:
    """Weighted combination of positive-signal dimensions.

    Default weights (from probability-framework.md):
        NR 0.25, OG 0.20, MQ 0.20, AS 0.20, TQ 0.15
    """
    w = weights or {"nr": 0.25, "og": 0.20, "mq": 0.20, "as": 0.20, "tq": 0.15}
    return clip(
        narrative_relevance * w["nr"]
        + og_score * w["og"]
        + momentum_quality * w["mq"]
        + attention_strength * w["as"]
        + timing_quality * w["tq"]
    )


# ---------------------------------------------------------------------------
# P_failure
# ---------------------------------------------------------------------------

def compute_p_failure(
    rug_risk: float,
    momentum_quality: float,
    timing_quality: float,
    og_score: float,
    liquidity_risk: float = 0.5,
    weights: dict | None = None,
) -> float:
    """Weighted combination of failure-indicator dimensions.

    Derived sub-risks:
        - Fakeout risk  = 1 - momentum_quality
        - Exhaustion risk = 1 - timing_quality
        - Copycat risk   = 1 - og_score

    Default weights (from probability-framework.md):
        RR 0.35, FR 0.25, ER 0.20, CR 0.10, LR 0.10
    """
    w = weights or {"rr": 0.35, "fr": 0.25, "er": 0.20, "cr": 0.10, "lr": 0.10}
    fakeout_risk = 1.0 - momentum_quality
    exhaustion_risk = 1.0 - timing_quality
    copycat_risk = 1.0 - og_score
    return clip(
        rug_risk * w["rr"]
        + fakeout_risk * w["fr"]
        + exhaustion_risk * w["er"]
        + copycat_risk * w["cr"]
        + liquidity_risk * w["lr"]
    )


# ---------------------------------------------------------------------------
# Net potential
# ---------------------------------------------------------------------------

def compute_net_potential(p_potential: float, p_failure: float) -> float:
    """Opportunity strength discounted by failure probability.

    ``net_potential = P_potential * (1 - P_failure)``
    """
    return clip(p_potential * (1.0 - p_failure))


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def compute_confidence(
    source_count: int,
    source_diversity: int,
    data_completeness: float,
    ambiguity_score: float,
    max_sources: int = 5,
    max_diversity: int = 4,
    weights: dict | None = None,
) -> float:
    """Quality of the evidence underlying the probability estimates.

    A high confidence score means the data quality is good, *not* that the
    token is good.  A low confidence score means we are estimating with
    limited information.

    Parameters
    ----------
    source_count:
        Number of independent data sources available.
    source_diversity:
        Number of distinct source *types* (e.g. on-chain, social, search).
    data_completeness:
        Fraction of required dimension data that was available (0-1).
    ambiguity_score:
        Degree of ambiguity in narrative matching / OG resolution (0-1).
    max_sources:
        Normalisation ceiling for source count.
    max_diversity:
        Normalisation ceiling for source diversity.
    weights:
        Component weight overrides.
    """
    w = weights or {"count": 0.25, "diversity": 0.25, "completeness": 0.30, "ambiguity": 0.20}
    sc = min(source_count / max_sources, 1.0)
    sd = min(source_diversity / max_diversity, 1.0)
    return clip(
        sc * w["count"]
        + sd * w["diversity"]
        + data_completeness * w["completeness"]
        + (1.0 - ambiguity_score) * w["ambiguity"]
    )
