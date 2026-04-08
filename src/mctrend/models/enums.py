"""Enumerations used across the MC Trend Analysis domain models."""

from enum import Enum


class TokenStatus(str, Enum):
    """Lifecycle status of a tracked token."""

    NEW = "new"
    LINKED = "linked"
    SCORED = "scored"
    ALERTED = "alerted"
    EXPIRED = "expired"
    DISCARDED = "discarded"


class NarrativeState(str, Enum):
    """Current lifecycle state of a narrative."""

    EMERGING = "EMERGING"
    PEAKING = "PEAKING"
    DECLINING = "DECLINING"
    DEAD = "DEAD"


class AlertType(str, Enum):
    """Classification tier for an alert, from lowest to highest actionability."""

    IGNORE = "ignore"
    WATCH = "watch"
    VERIFY = "verify"
    HIGH_POTENTIAL_WATCH = "high_potential_watch"
    POSSIBLE_ENTRY = "possible_entry"
    TAKE_PROFIT_WATCH = "take_profit_watch"
    EXIT_RISK = "exit_risk"
    DISCARD = "discard"


class AlertStatus(str, Enum):
    """Whether an alert is currently active or has been retired."""

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MatchMethod(str, Enum):
    """How a token was matched to a narrative."""

    EXACT = "exact"
    ABBREVIATION = "abbreviation"
    RELATED_TERM = "related_term"
    SEMANTIC = "semantic"
    NONE = "none"


class DataFreshnessStatus(str, Enum):
    """Staleness classification of underlying data used in scoring."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


class SourceTrustTier(str, Enum):
    """Trust level assigned to a data source.

    tier_1: untrusted — data used only for cross-referencing.
    tier_2: verify_then_use — data usable after validation against another source.
    tier_3: relatively_trusted — data usable directly with standard caveats.
    """

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class RiskTier(str, Enum):
    """Qualitative risk classification derived from rug-risk scoring."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
