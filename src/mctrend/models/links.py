"""Token-narrative link domain models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import MatchMethod


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class TokenNarrativeLink(BaseModel):
    """Association between a token and a narrative, with match metadata.

    A token may be linked to multiple narratives and a narrative may have
    many linked tokens.  The ``match_method`` and ``match_confidence``
    describe *how* the link was established.  OG ranking fields track
    whether this token is considered the original token for its narrative.
    """

    model_config = ConfigDict(frozen=False)

    link_id: str = Field(default_factory=_uuid4, description="Unique identifier for this link.")
    token_id: str = Field(..., description="Token being linked.")
    narrative_id: str = Field(..., description="Narrative being linked to.")
    match_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the token-narrative match (0-1).")
    match_method: MatchMethod = Field(..., description="Method used to establish the match.")
    match_signals: list[str] = Field(default_factory=list, description="Specific signals that contributed to the match.")
    og_rank: Optional[int] = Field(default=None, description="OG rank among tokens in this narrative (1 = most likely OG).")
    og_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="OG likelihood score (0-1).")
    og_signals: list[str] = Field(default_factory=list, description="Signals supporting the OG determination.")
    created_at: datetime = Field(default_factory=_utcnow, description="When this link was created.")
    updated_at: datetime = Field(default_factory=_utcnow, description="Last update timestamp.")
    status: str = Field(default="active", description="Link status (e.g. 'active', 'invalidated').")
