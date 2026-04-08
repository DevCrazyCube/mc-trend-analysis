"""Alert domain models — alerts, history entries, and lifecycle tracking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import AlertStatus, AlertType
from .scoring import DimensionScores


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class AlertHistoryEntry(BaseModel):
    """A single state-transition record within an alert's history.

    Every status change is logged with previous state, new state,
    timestamp, and reason — per the "all state transitions are logged" rule.
    """

    model_config = ConfigDict(frozen=False)

    timestamp: datetime = Field(default_factory=_utcnow, description="When this transition occurred.")
    previous_type: Optional[AlertType] = Field(default=None, description="Alert type before the transition (None for initial creation).")
    new_type: AlertType = Field(..., description="Alert type after the transition.")
    previous_net_potential: Optional[float] = Field(default=None, description="Net potential before the transition.")
    new_net_potential: float = Field(..., description="Net potential after the transition.")
    change_reason: str = Field(..., description="Human-readable reason for the change.")
    trigger: str = Field(..., description="What triggered this re-evaluation (e.g. 'scheduled_rescore', 'chain_event').")


class Alert(BaseModel):
    """A structured, probability-based alert for a token-narrative pair.

    Alerts carry full context: token identity, narrative context, scores,
    risk flags, and complete transition history.  Risk flags are **never**
    suppressed or hidden in any delivery format.
    """

    model_config = ConfigDict(frozen=False)

    alert_id: str = Field(default_factory=_uuid4, description="Unique alert identifier.")
    token_id: str = Field(..., description="Token this alert concerns.")
    token_address: str = Field(..., description="On-chain address of the token.")
    token_name: str = Field(..., description="Human-readable token name.")
    token_symbol: str = Field(..., description="Token ticker symbol.")
    narrative_id: str = Field(..., description="Narrative the token is linked to.")
    narrative_name: str = Field(..., description="Human-readable narrative name.")
    link_id: str = Field(..., description="TokenNarrativeLink identifier.")
    score_id: str = Field(..., description="ScoredToken identifier this alert is based on.")
    alert_type: AlertType = Field(..., description="Classification tier of this alert.")
    net_potential: float = Field(..., description="Net potential score (p_potential - p_failure).")
    p_potential: float = Field(..., ge=0.0, le=1.0, description="Probability of meaningful upside.")
    p_failure: float = Field(..., ge=0.0, le=1.0, description="Probability of failure or rug.")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in the probability estimates.")
    dimension_scores: DimensionScores = Field(..., description="Full dimension score breakdown.")
    risk_flags: list[str] = Field(default_factory=list, description="Active risk flags — always visible, never suppressed.")
    reasoning: str = Field(..., description="Human-readable explanation of the alert classification.")
    status: AlertStatus = Field(default=AlertStatus.ACTIVE, description="Whether the alert is active or retired.")
    created_at: datetime = Field(default_factory=_utcnow, description="When the alert was created.")
    updated_at: datetime = Field(default_factory=_utcnow, description="Last update timestamp.")
    expires_at: datetime = Field(..., description="When the alert expires if not re-evaluated.")
    retired_at: Optional[datetime] = Field(default=None, description="When the alert was retired, if applicable.")
    retirement_reason: Optional[str] = Field(default=None, description="Why the alert was retired.")
    re_eval_triggers: list[str] = Field(default_factory=list, description="Conditions that should trigger re-evaluation.")
    history: list[AlertHistoryEntry] = Field(default_factory=list, description="Complete state transition history.")
