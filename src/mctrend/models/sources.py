"""Source and social-data domain models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class SourceGap(BaseModel):
    """Records a period when a data source was unavailable.

    Used to adjust confidence scores and flag data gaps in downstream
    scoring.  An open gap (``ended_at is None``) means the source is
    still down.
    """

    model_config = ConfigDict(frozen=False)

    gap_id: str = Field(default_factory=_uuid4, description="Unique identifier for this gap record.")
    source_type: str = Field(..., description="Category of the source (e.g. 'twitter', 'chain_rpc').")
    source_name: str = Field(..., description="Specific source name or endpoint.")
    started_at: datetime = Field(default_factory=_utcnow, description="When the gap started.")
    ended_at: Optional[datetime] = Field(default=None, description="When the gap ended (None if still ongoing).")
    notes: Optional[str] = Field(default=None, description="Human-readable notes about the outage.")


class SocialRecord(BaseModel):
    """A point-in-time social-signal snapshot for a subject (token or narrative).

    Tracks mention counts, engagement, and estimated bot activity.  The
    ``reliability_tier`` maps to SourceTrustTier (1 = untrusted, 3 = relatively trusted).
    """

    model_config = ConfigDict(frozen=False)

    record_id: str = Field(default_factory=_uuid4, description="Unique identifier for this social record.")
    source_type: str = Field(..., description="Category of social source (e.g. 'twitter', 'telegram').")
    source_name: str = Field(..., description="Specific source name or handle.")
    sampled_at: datetime = Field(default_factory=_utcnow, description="When this social data was captured.")
    subject_type: str = Field(..., description="What this record is about ('token' or 'narrative').")
    subject_id: str = Field(..., description="ID of the token or narrative this record pertains to.")
    mention_count: Optional[int] = Field(default=None, ge=0, description="Number of mentions observed.")
    engagement_score: Optional[float] = Field(default=None, ge=0.0, description="Aggregate engagement metric.")
    unique_account_count: Optional[int] = Field(default=None, ge=0, description="Number of unique accounts mentioning the subject.")
    estimated_bot_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Estimated percentage of bot-driven activity (0-1).")
    data_gaps: list[str] = Field(default_factory=list, description="Data that was expected but unavailable.")
    reliability_tier: int = Field(default=1, ge=1, le=3, description="Trust tier of the source (1=untrusted, 2=verify, 3=trusted).")
