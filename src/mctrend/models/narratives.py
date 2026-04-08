"""Narrative domain models — event/narrative records and their source evidence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import NarrativeState


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class NarrativeSource(BaseModel):
    """A single piece of source evidence supporting a narrative.

    Each source links back to a specific external reference (tweet URL,
    article, Telegram message, etc.) and carries a signal-strength estimate.
    """

    model_config = ConfigDict(frozen=False)

    source_id: str = Field(default_factory=_uuid4, description="Unique identifier for this source entry.")
    narrative_id: str = Field(..., description="Narrative this source belongs to.")
    source_type: str = Field(..., description="Category of source (e.g. 'twitter', 'telegram', 'news').")
    source_name: str = Field(..., description="Human-readable source name or handle.")
    signal_strength: float = Field(..., ge=0.0, le=1.0, description="How strongly this source signals the narrative (0-1).")
    first_seen: datetime = Field(default_factory=_utcnow, description="When this source first referenced the narrative.")
    last_updated: datetime = Field(default_factory=_utcnow, description="Last time this source reference was refreshed.")
    raw_reference: Optional[str] = Field(default=None, description="URL or identifier for the original content.")


class EventRecord(BaseModel):
    """A detected narrative or event that tokens may be linked to.

    Narratives are the core organizing concept: tokens gain relevance by
    being linked to narratives, and narratives have their own lifecycle
    (EMERGING -> PEAKING -> DECLINING -> DEAD).
    """

    model_config = ConfigDict(frozen=False)

    narrative_id: str = Field(default_factory=_uuid4, description="Unique narrative identifier.")
    anchor_terms: list[str] = Field(..., min_length=1, description="Primary terms that define this narrative (at least one required).")
    related_terms: list[str] = Field(default_factory=list, description="Secondary or derivative terms associated with the narrative.")
    entities: list[dict] = Field(default_factory=list, description="Named entities extracted from the narrative context.")
    description: str = Field(..., description="Human-readable description of the narrative.")
    attention_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Current cross-source attention level (0-1).")
    narrative_velocity: float = Field(default=0.0, description="Rate of change of attention score.")
    source_type_count: int = Field(default=0, ge=0, description="Number of distinct source types referencing this narrative.")
    state: NarrativeState = Field(default=NarrativeState.EMERGING, description="Current lifecycle state.")
    sources: list[NarrativeSource] = Field(default_factory=list, description="Evidence sources backing this narrative.")
    first_detected: datetime = Field(default_factory=_utcnow, description="When the narrative was first detected.")
    peaked_at: Optional[datetime] = Field(default=None, description="When the narrative reached peak attention, if applicable.")
    dead_at: Optional[datetime] = Field(default=None, description="When the narrative was marked dead, if applicable.")
    updated_at: datetime = Field(default_factory=_utcnow, description="Last update timestamp.")
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence in the narrative extraction (0-1).")
    ambiguous: bool = Field(default=False, description="Whether the narrative terms are ambiguous or overloaded.")
    data_gaps: list[str] = Field(default_factory=list, description="Data that was expected but unavailable.")
