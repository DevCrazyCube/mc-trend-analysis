"""Scoring aggregator -- combines all dimension scores into a ScoredToken result.

The ``ScoringAggregator`` is the main entry point for the scoring engine.  It
accepts raw data dicts (chain, narrative, social, link) and produces a fully
populated result dict that can be used to construct a
``mctrend.models.scoring.ScoredToken``.

All weights and thresholds are configurable via the *config* dict passed at
construction time.  Nothing is hardcoded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .dimensions import (
    clip,
    score_attention_strength,
    score_momentum_quality,
    score_narrative_relevance,
    score_og_likelihood,
    score_rug_risk,
    score_timing_quality,
)
from .probability import (
    compute_confidence,
    compute_net_potential,
    compute_p_failure,
    compute_p_potential,
)


# ---------------------------------------------------------------------------
# Sub-risk derivation helpers
# ---------------------------------------------------------------------------

def _derive_deployer_risk(chain_data: dict) -> tuple[float | None, list[str]]:
    """Compute deployer risk sub-score from raw chain data.

    Uses deployer_known_bad and deployer_prior_deployments to estimate risk.
    See ``docs/intelligence/rug-risk-framework.md`` Category 1.

    Returns (risk_score_or_None, data_gaps).
    """
    gaps: list[str] = []
    deployer_known_bad = chain_data.get("deployer_known_bad")
    deployer_prior = chain_data.get("deployer_prior_deployments")

    # If we have no deployer information at all, return None so the dimension
    # function will apply its own conservative default.
    if deployer_known_bad is None and deployer_prior is None:
        gaps.append("deployer_history")
        return None, gaps

    # Known bad deployer is the strongest single signal.
    if deployer_known_bad is True:
        return 0.90, gaps

    # Derive from deployment history.
    if deployer_prior is not None:
        if deployer_prior == 0:
            # Brand new deployer -- neutral-ish risk.
            return 0.45, gaps
        elif deployer_prior <= 3:
            # Some history, not necessarily bad.
            return 0.30, gaps
        else:
            # Many prior deployments -- factory pattern is suspicious.
            return clip(0.40 + deployer_prior * 0.05, hi=0.85), gaps

    # deployer_known_bad is explicitly False but no deployment count.
    return 0.35, gaps


def _derive_concentration_risk(chain_data: dict) -> tuple[float | None, list[str]]:
    """Compute holder-concentration risk from top-holder percentages.

    Uses the formula from ``docs/intelligence/rug-risk-framework.md`` Category 2:
        ``concentration_score = clip(top5_pct / 70, 0, 1)``
    """
    gaps: list[str] = []
    top_5 = chain_data.get("top_5_holder_pct")

    if top_5 is None:
        gaps.append("holder_concentration")
        return None, gaps

    # top_5 is a percentage (0-100).  Normalise against 70%.
    return clip(top_5 / 70.0), gaps


def _derive_clustering_risk(chain_data: dict) -> tuple[float | None, list[str]]:
    """Estimate wallet-clustering risk from available heuristics.

    Full graph analysis is expensive; for initial scoring use the
    ``new_wallet_holder_pct`` proxy.  See rug-risk-framework Category 3.
    """
    gaps: list[str] = []
    new_wallet_pct = chain_data.get("new_wallet_holder_pct")

    if new_wallet_pct is None:
        gaps.append("wallet_clustering")
        return None, gaps

    # High proportion of new-wallet holders is a clustering/sybil proxy.
    # new_wallet_pct is 0-1 (fraction).
    # Map: 0% new wallets -> 0.15, 100% new wallets -> 0.90
    return clip(0.15 + new_wallet_pct * 0.75), gaps


def _derive_liquidity_risk(chain_data: dict) -> tuple[float | None, list[str]]:
    """Compute liquidity risk from lock status, amount, and provider count.

    See rug-risk-framework Category 4.
    """
    gaps: list[str] = []
    liquidity_usd = chain_data.get("liquidity_usd")
    liquidity_locked = chain_data.get("liquidity_locked")
    liquidity_lock_hours = chain_data.get("liquidity_lock_hours")
    provider_count = chain_data.get("liquidity_provider_count")

    # If we have no liquidity data at all, return None.
    if liquidity_usd is None and liquidity_locked is None and provider_count is None:
        gaps.append("liquidity_data")
        return None, gaps

    risk_components: list[float] = []
    component_weights: list[float] = []

    # --- Liquidity amount risk ---
    if liquidity_usd is not None:
        # Very low liquidity (< $5k) is high risk; > $50k is low risk.
        if liquidity_usd < 5_000:
            amount_risk = 0.85
        elif liquidity_usd < 20_000:
            amount_risk = 0.55
        elif liquidity_usd < 50_000:
            amount_risk = 0.30
        else:
            amount_risk = 0.15
        risk_components.append(amount_risk)
        component_weights.append(0.35)

    # --- Lock status risk ---
    if liquidity_locked is not None:
        if liquidity_locked:
            if liquidity_lock_hours is not None:
                if liquidity_lock_hours < 24:
                    lock_risk = 0.50  # Short lock -- medium risk.
                elif liquidity_lock_hours < 168:  # < 1 week
                    lock_risk = 0.25
                else:
                    lock_risk = 0.10  # Long lock.
            else:
                lock_risk = 0.30  # Locked but unknown duration.
        else:
            lock_risk = 0.80  # Entirely unlocked.
        risk_components.append(lock_risk)
        component_weights.append(0.40)

    # --- Provider diversity risk ---
    if provider_count is not None:
        if provider_count <= 1:
            provider_risk = 0.75  # Single provider -- single point of removal.
        elif provider_count <= 3:
            provider_risk = 0.40
        else:
            provider_risk = 0.15
        risk_components.append(provider_risk)
        component_weights.append(0.25)

    if not risk_components:
        gaps.append("liquidity_data")
        return None, gaps

    # Weighted average of available components, re-normalised.
    total_weight = sum(component_weights)
    liquidity_risk = sum(r * w for r, w in zip(risk_components, component_weights)) / total_weight
    return clip(liquidity_risk), gaps


def _derive_contract_risk(chain_data: dict) -> tuple[float | None, list[str]]:
    """Estimate contract anomaly risk from authority statuses.

    Uses mint_authority_status and freeze_authority_status from the token record.
    See rug-risk-framework Category 5.
    """
    gaps: list[str] = []
    mint_auth = chain_data.get("mint_authority_status")
    freeze_auth = chain_data.get("freeze_authority_status")

    if mint_auth is None and freeze_auth is None:
        gaps.append("contract_authorities")
        return None, gaps

    risk = 0.20  # Base: standard token with renounced authorities is low risk.

    if mint_auth is not None:
        if mint_auth == "active":
            risk += 0.35
        elif mint_auth == "unknown":
            risk += 0.15  # Conservative for unknown.
        # "revoked" adds nothing.

    if freeze_auth is not None:
        if freeze_auth == "active":
            risk += 0.25
        elif freeze_auth == "unknown":
            risk += 0.10
        # "revoked" adds nothing.

    return clip(risk), gaps


# ---------------------------------------------------------------------------
# Attention / timing derivation helpers
# ---------------------------------------------------------------------------

def _derive_attention_inputs(
    narrative_data: dict,
    social_data: dict | None,
) -> dict[str, float | None]:
    """Extract attention sub-scores from narrative and social data."""
    social = social_data or {}

    search_magnitude = narrative_data.get("attention_score")
    source_breadth: float | None = None
    narrative_velocity = narrative_data.get("narrative_velocity")

    source_type_count = narrative_data.get("source_type_count")
    if source_type_count is not None:
        # Normalise against 4 source types.
        source_breadth = clip(source_type_count / 4.0)

    # Social data may override / enrich.
    if "search_magnitude" in social:
        search_magnitude = social["search_magnitude"]
    if "source_breadth" in social:
        source_breadth = social["source_breadth"]
    if "narrative_velocity" in social:
        narrative_velocity = social["narrative_velocity"]

    return {
        "search_magnitude": search_magnitude,
        "source_breadth": source_breadth,
        "narrative_velocity": narrative_velocity,
    }


def _derive_timing_inputs(narrative_data: dict) -> dict[str, float]:
    """Derive timing quality sub-scores from narrative lifecycle data.

    Returns lifecycle_score, acceleration_score, saturation_score --
    all with conservative defaults when data is missing.
    """
    state = narrative_data.get("state", "EMERGING")
    narrative_velocity = narrative_data.get("narrative_velocity")
    narrative_age_hours = narrative_data.get("narrative_age_hours", 0.0)
    competing_tokens = narrative_data.get("competing_token_count", 1)

    # --- lifecycle score ---
    # Early in narrative = high.  Map age to [0, 1] where 0h -> 1.0, 12h+ -> ~0.1.
    lifecycle_score = clip(1.0 - narrative_age_hours / 12.0, lo=0.05)
    # State-based adjustments.
    state_upper = state.upper() if isinstance(state, str) else str(state).upper()
    if state_upper == "DEAD":
        lifecycle_score = min(lifecycle_score, 0.10)
    elif state_upper == "DECLINING":
        lifecycle_score = min(lifecycle_score, 0.35)
    elif state_upper == "PEAKING":
        lifecycle_score = min(lifecycle_score, 0.55)

    # --- acceleration score ---
    if narrative_velocity is not None:
        acceleration_score = clip(narrative_velocity)
    else:
        acceleration_score = 0.4  # Conservative default.

    # --- saturation score (inverse of market saturation) ---
    if competing_tokens <= 1:
        saturation_score = 0.90
    elif competing_tokens <= 3:
        saturation_score = 0.65
    elif competing_tokens <= 8:
        saturation_score = 0.40
    else:
        saturation_score = clip(0.20 - (competing_tokens - 8) * 0.02, lo=0.05)

    return {
        "lifecycle_score": lifecycle_score,
        "acceleration_score": acceleration_score,
        "saturation_score": saturation_score,
    }


def _derive_momentum_inputs(
    chain_data: dict,
    social_data: dict | None,
) -> dict[str, float | None]:
    """Extract momentum quality sub-scores from chain and social data."""
    social = social_data or {}

    volume_pattern = chain_data.get("volume_pattern")
    trade_diversity = chain_data.get("trade_diversity")
    holder_growth_quality = chain_data.get("holder_growth_quality")

    # Derive trade_diversity from unique_traders_1h / trade_count_1h when not
    # provided directly.
    if trade_diversity is None:
        unique_traders = chain_data.get("unique_traders_1h")
        trade_count = chain_data.get("trade_count_1h")
        if unique_traders is not None and trade_count is not None and trade_count > 0:
            trade_diversity = clip(unique_traders / trade_count)

    social_chain_alignment = social.get("social_chain_alignment")

    return {
        "volume_pattern": volume_pattern,
        "trade_diversity": trade_diversity,
        "social_chain_alignment": social_chain_alignment,
        "holder_growth_quality": holder_growth_quality,
    }


# ---------------------------------------------------------------------------
# Data-completeness helper
# ---------------------------------------------------------------------------

_REQUIRED_DIMENSIONS = 6


def _compute_data_completeness(data_gaps: list[str]) -> float:
    """Fraction of dimension data that was available.

    Each gap entry roughly corresponds to one missing dimension input.
    Clamp so that a huge number of gaps doesn't produce negative completeness.
    """
    gap_count = len(data_gaps)
    return clip(1.0 - gap_count / _REQUIRED_DIMENSIONS, lo=0.0)


# ---------------------------------------------------------------------------
# ScoringAggregator
# ---------------------------------------------------------------------------

class ScoringAggregator:
    """Combines all dimension scores into a ScoredToken result dict.

    Parameters
    ----------
    config : dict | None
        Optional weight / threshold overrides.  Supported keys:

        - ``"p_potential_weights"``   -- weights for P_potential formula
        - ``"p_failure_weights"``     -- weights for P_failure formula
        - ``"confidence_weights"``    -- weights for confidence formula
        - ``"og_weights"``            -- weights for OG likelihood dimension
        - ``"rug_weights"``           -- weights for rug-risk dimension
        - ``"rug_defaults"``          -- conservative defaults for missing rug data
        - ``"narrative_decay_hours"`` -- decay parameter for narrative recency
        - ``"narrative_max_source_types"`` -- normalisation cap
        - ``"og_max_mentions"``       -- normalisation cap for cross-source mentions
        - ``"confidence_max_sources"``   -- normalisation cap
        - ``"confidence_max_diversity"`` -- normalisation cap
    """

    def __init__(self, config: dict | None = None) -> None:
        self._cfg = config or {}

    # -- convenience accessors for configured weights ---------------------

    def _get(self, key: str, default: Any = None) -> Any:
        return self._cfg.get(key, default)

    # -- public API -------------------------------------------------------

    def score_token(
        self,
        token_id: str,
        narrative_id: str,
        link_id: str,
        chain_data: dict,
        narrative_data: dict,
        social_data: dict | None,
        link_data: dict,
    ) -> dict:
        """Main scoring entry point.

        Parameters
        ----------
        token_id : str
            Unique token identifier.
        narrative_id : str
            Unique narrative identifier.
        link_id : str
            TokenNarrativeLink identifier.
        chain_data : dict
            On-chain snapshot data (holder counts, liquidity, deployer info, etc.).
        narrative_data : dict
            Narrative record data (match_confidence, narrative_age_hours,
            source_type_count, state, attention_score, narrative_velocity, etc.).
        social_data : dict | None
            Social-signal data.  May be ``None`` or empty when unavailable.
        link_data : dict
            Token-narrative-link data (og_rank, og_score, cross_source_mentions,
            match_confidence, etc.).

        Returns
        -------
        dict
            A dict suitable for constructing a ``ScoredToken`` model, containing
            all dimension scores, probability values, risk flags, data gaps,
            and dimension details.
        """
        all_risk_flags: list[str] = []
        all_data_gaps: list[str] = []
        dimension_details: dict[str, Any] = {}

        # =================================================================
        # 1. Narrative Relevance
        # =================================================================
        nr_match_confidence = narrative_data.get(
            "match_confidence", link_data.get("match_confidence", 0.0)
        )
        nr_age = narrative_data.get("narrative_age_hours", 0.0)
        nr_source_count = narrative_data.get("source_type_count", 1)

        nr_score, nr_signals = score_narrative_relevance(
            match_confidence=nr_match_confidence,
            narrative_age_hours=nr_age,
            source_type_count=nr_source_count,
            max_source_types=self._get("narrative_max_source_types", 4),
            decay_hours=self._get("narrative_decay_hours", 6.0),
        )
        all_risk_flags.extend(nr_signals)
        dimension_details["narrative_relevance"] = {
            "score": nr_score,
            "signals": nr_signals,
            "match_confidence": nr_match_confidence,
            "narrative_age_hours": nr_age,
            "source_type_count": nr_source_count,
        }

        # =================================================================
        # 2. OG Likelihood
        # =================================================================
        og_temporal = link_data.get("og_score") if link_data.get("og_score") is not None else 0.5
        og_name_precision = link_data.get("name_precision") if link_data.get("name_precision") is not None else nr_match_confidence
        og_cross_mentions = link_data.get("cross_source_mentions") or 0
        og_deployer = chain_data.get("deployer_reputation") if chain_data.get("deployer_reputation") is not None else 0.5

        og_score, og_signals = score_og_likelihood(
            temporal_score=og_temporal,
            name_precision=og_name_precision,
            cross_source_mentions=og_cross_mentions,
            deployer_score=og_deployer,
            max_mentions=self._get("og_max_mentions", 5),
            weights=self._get("og_weights"),
        )
        all_risk_flags.extend(og_signals)
        dimension_details["og_likelihood"] = {
            "score": og_score,
            "signals": og_signals,
            "temporal_score": og_temporal,
            "name_precision": og_name_precision,
            "cross_source_mentions": og_cross_mentions,
            "deployer_score": og_deployer,
        }

        # =================================================================
        # 3. Rug Risk  (sub-scores derived from chain data)
        # =================================================================
        deployer_risk, dep_gaps = _derive_deployer_risk(chain_data)
        concentration_risk, conc_gaps = _derive_concentration_risk(chain_data)
        clustering_risk, clust_gaps = _derive_clustering_risk(chain_data)
        liquidity_risk, liq_gaps = _derive_liquidity_risk(chain_data)
        contract_risk, cont_gaps = _derive_contract_risk(chain_data)

        all_data_gaps.extend(dep_gaps + conc_gaps + clust_gaps + liq_gaps + cont_gaps)

        rr_score, rr_signals = score_rug_risk(
            deployer_risk=deployer_risk,
            concentration_risk=concentration_risk,
            clustering_risk=clustering_risk,
            liquidity_risk=liquidity_risk,
            contract_risk=contract_risk,
            weights=self._get("rug_weights"),
            defaults=self._get("rug_defaults"),
        )
        all_risk_flags.extend(rr_signals)
        dimension_details["rug_risk"] = {
            "score": rr_score,
            "signals": rr_signals,
            "deployer_risk": deployer_risk,
            "concentration_risk": concentration_risk,
            "clustering_risk": clustering_risk,
            "liquidity_risk": liquidity_risk,
            "contract_risk": contract_risk,
        }

        # =================================================================
        # 4. Momentum Quality
        # =================================================================
        momentum_inputs = _derive_momentum_inputs(chain_data, social_data)

        mq_score, mq_signals = score_momentum_quality(
            volume_pattern=momentum_inputs["volume_pattern"],
            trade_diversity=momentum_inputs["trade_diversity"],
            social_chain_alignment=momentum_inputs["social_chain_alignment"],
            holder_growth_quality=momentum_inputs["holder_growth_quality"],
        )
        all_risk_flags.extend(mq_signals)
        dimension_details["momentum_quality"] = {
            "score": mq_score,
            "signals": mq_signals,
            **momentum_inputs,
        }

        # =================================================================
        # 5. Attention Strength
        # =================================================================
        attention_inputs = _derive_attention_inputs(narrative_data, social_data)

        as_score, as_signals = score_attention_strength(
            search_magnitude=attention_inputs["search_magnitude"],
            source_breadth=attention_inputs["source_breadth"],
            narrative_velocity=attention_inputs["narrative_velocity"],
        )
        all_risk_flags.extend(as_signals)
        dimension_details["attention_strength"] = {
            "score": as_score,
            "signals": as_signals,
            **attention_inputs,
        }

        # =================================================================
        # 6. Timing Quality
        # =================================================================
        timing_inputs = _derive_timing_inputs(narrative_data)

        tq_score, tq_signals = score_timing_quality(
            lifecycle_score=timing_inputs["lifecycle_score"],
            acceleration_score=timing_inputs["acceleration_score"],
            saturation_score=timing_inputs["saturation_score"],
        )
        all_risk_flags.extend(tq_signals)
        dimension_details["timing_quality"] = {
            "score": tq_score,
            "signals": tq_signals,
            **timing_inputs,
        }

        # =================================================================
        # 7. Probability framework
        # =================================================================

        # Compute the raw liquidity risk value for P_failure.
        # Use the derived liquidity_risk from rug sub-scores if available,
        # otherwise fall back to the rug-risk framework's conservative default.
        p_failure_liquidity_risk = liquidity_risk if liquidity_risk is not None else 0.60

        p_potential = compute_p_potential(
            narrative_relevance=nr_score,
            og_score=og_score,
            momentum_quality=mq_score,
            attention_strength=as_score,
            timing_quality=tq_score,
            weights=self._get("p_potential_weights"),
        )

        p_failure = compute_p_failure(
            rug_risk=rr_score,
            momentum_quality=mq_score,
            timing_quality=tq_score,
            og_score=og_score,
            liquidity_risk=p_failure_liquidity_risk,
            weights=self._get("p_failure_weights"),
        )

        net_potential = compute_net_potential(p_potential, p_failure)

        # =================================================================
        # 8. Confidence
        # =================================================================
        source_count = narrative_data.get("source_count", nr_source_count)
        source_diversity = narrative_data.get("source_type_count", 1)
        data_completeness = _compute_data_completeness(all_data_gaps)
        ambiguity_score = narrative_data.get("ambiguity_score", 0.5)
        if narrative_data.get("ambiguous") is True:
            ambiguity_score = max(ambiguity_score, 0.7)

        confidence = compute_confidence(
            source_count=source_count,
            source_diversity=source_diversity,
            data_completeness=data_completeness,
            ambiguity_score=ambiguity_score,
            max_sources=self._get("confidence_max_sources", 5),
            max_diversity=self._get("confidence_max_diversity", 4),
            weights=self._get("confidence_weights"),
        )

        # =================================================================
        # 9. Assemble result
        # =================================================================
        return {
            "score_id": str(uuid.uuid4()),
            "link_id": link_id,
            "token_id": token_id,
            "narrative_id": narrative_id,
            "scored_at": datetime.now(timezone.utc).isoformat(),
            # Dimension scores
            "narrative_relevance": round(nr_score, 4),
            "og_score": round(og_score, 4),
            "rug_risk": round(rr_score, 4),
            "momentum_quality": round(mq_score, 4),
            "attention_strength": round(as_score, 4),
            "timing_quality": round(tq_score, 4),
            # Probability framework
            "p_potential": round(p_potential, 4),
            "p_failure": round(p_failure, 4),
            "net_potential": round(net_potential, 4),
            "confidence_score": round(confidence, 4),
            # Supporting data
            "risk_flags": all_risk_flags,
            "data_gaps": all_data_gaps,
            "dimension_details": dimension_details,
        }
