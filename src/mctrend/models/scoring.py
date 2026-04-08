"""Scoring domain models — dimension scores, probability results, and scored tokens."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import DataFreshnessStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class DimensionScores(BaseModel):
    """The six scoring dimensions, each normalised to [0, 1].

    These dimensions are computed deterministically — never by an LLM.
    """

    model_config = ConfigDict(frozen=False)

    narrative_relevance: float = Field(..., ge=0.0, le=1.0, description="How strongly the token is linked to a live narrative.")
    og_score: float = Field(..., ge=0.0, le=1.0, description="Likelihood this token is the 'OG' for its narrative.")
    rug_risk: float = Field(..., ge=0.0, le=1.0, description="Assessed rug-pull risk (higher = riskier).")
    momentum_quality: float = Field(..., ge=0.0, le=1.0, description="Quality and sustainability of trading momentum.")
    attention_strength: float = Field(..., ge=0.0, le=1.0, description="Cross-source attention level for the token/narrative.")
    timing_quality: float = Field(..., ge=0.0, le=1.0, description="How well the token's timing aligns with narrative lifecycle.")


class ProbabilityResult(BaseModel):
    """Probability-based evaluation derived from dimension scores.

    All values are in [0, 1].  ``net_potential`` = p_potential - p_failure.
    ``confidence_score`` captures how much data was available for the estimate.
    """

    model_config = ConfigDict(frozen=False)

    p_potential: float = Field(..., ge=0.0, le=1.0, description="Estimated probability of meaningful upside potential.")
    p_failure: float = Field(..., ge=0.0, le=1.0, description="Estimated probability of failure or rug.")
    net_potential: float = Field(..., ge=0.0, le=1.0, description="p_potential minus p_failure, floored at 0.")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in the probability estimates given available data.")


class ScoredToken(BaseModel):
    """A fully scored token-narrative pair, ready for alert classification.

    Combines dimension scores and probability results with metadata about
    data freshness and any risk flags or gaps.
    """

    model_config = ConfigDict(frozen=False)

    score_id: str = Field(default_factory=_uuid4, description="Unique identifier for this scoring record.")
    link_id: str = Field(..., description="TokenNarrativeLink this score was computed for.")
    token_id: str = Field(..., description="Token being scored.")
    narrative_id: str = Field(..., description="Narrative the token is linked to.")
    scored_at: datetime = Field(default_factory=_utcnow, description="When this score was computed.")
    dimensions: DimensionScores = Field(..., description="Individual dimension scores.")
    probabilities: ProbabilityResult = Field(..., description="Derived probability result.")
    risk_flags: list[str] = Field(default_factory=list, description="Active risk flags (never suppressed in output).")
    data_gaps: list[str] = Field(default_factory=list, description="Data that was expected but unavailable.")
    dimension_details: dict = Field(default_factory=dict, description="Optional per-dimension detail payloads for transparency.")
    chain_data_age_minutes: Optional[int] = Field(default=None, description="Age of the chain data used, in minutes.")
    social_data_age_minutes: Optional[int] = Field(default=None, description="Age of the social data used, in minutes.")
    data_freshness_status: DataFreshnessStatus = Field(
        default=DataFreshnessStatus.FRESH,
        description="Overall freshness classification of underlying data.",
    )
