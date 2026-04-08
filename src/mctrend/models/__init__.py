"""Domain models for MC Trend Analysis.

Re-exports all model classes and enumerations for convenient access::

    from mctrend.models import TokenRecord, Alert, DimensionScores
"""

from .enums import (
    AlertStatus,
    AlertType,
    DataFreshnessStatus,
    MatchMethod,
    NarrativeState,
    RiskTier,
    SourceTrustTier,
    TokenStatus,
)
from .tokens import TokenChainSnapshot, TokenRecord
from .narratives import EventRecord, NarrativeSource
from .scoring import DimensionScores, ProbabilityResult, ScoredToken
from .alerts import Alert, AlertHistoryEntry
from .links import TokenNarrativeLink
from .sources import SocialRecord, SourceGap

__all__ = [
    # Enums
    "AlertStatus",
    "AlertType",
    "DataFreshnessStatus",
    "MatchMethod",
    "NarrativeState",
    "RiskTier",
    "SourceTrustTier",
    "TokenStatus",
    # Tokens
    "TokenRecord",
    "TokenChainSnapshot",
    # Narratives
    "NarrativeSource",
    "EventRecord",
    # Scoring
    "DimensionScores",
    "ProbabilityResult",
    "ScoredToken",
    # Alerts
    "AlertHistoryEntry",
    "Alert",
    # Links
    "TokenNarrativeLink",
    # Sources
    "SourceGap",
    "SocialRecord",
]
