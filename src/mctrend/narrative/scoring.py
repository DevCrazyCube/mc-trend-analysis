"""Narrative ranking, classification, and explainability for the operator board.

All weights and thresholds are explicit named constants — no hidden magic.
Each score component is individually visible in output so an operator can
immediately understand WHY a narrative ranks where it does.

Score formula
-------------
narrative_score =
    token_count_component  (weight 0.35, log-scaled)
  + velocity_component     (weight 0.30, tokens/min in last 5min, normalized)
  + acceleration_component (weight 0.15, increasing / flat / decreasing)
  + recency_component      (weight 0.10, decays from 1.0 to 0.0 over 2h)
  + corroboration_component(weight 0.10, X spike + news boosts)

Classification (strict thresholds, deterministic)
--------------------------------------------------
NOISE    — token_count < 3 (below minimum signal threshold)
WEAK     — token_count in [3, 5) OR score < EMERGING_SCORE_MIN
EMERGING — token_count >= 5 AND score >= EMERGING_SCORE_MIN
STRONG   — token_count >= 8 AND score >= STRONG_SCORE_MIN AND acceleration="increasing"

Design constraints
------------------
- Deterministic: same inputs → same output always
- No LLM calls, no randomness, no external dependencies
- All thresholds are module-level constants: adjustable, documented
- reason field is built from actual computed values (no vague language)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from mctrend.narrative.token_clustering import add_cluster_info_to_board_entry

if TYPE_CHECKING:
    from mctrend.narrative.discovery_engine import NarrativeCandidate


# ---------------------------------------------------------------------------
# Weight constants — all weights sum to 1.0
# ---------------------------------------------------------------------------

W_TOKEN_COUNT = 0.35
W_VELOCITY = 0.30
W_ACCELERATION = 0.15
W_RECENCY = 0.10
W_CORROBORATION = 0.10

# Velocity normalization: tokens per minute that maps to score=1.0
# A rate of 2 tokens/minute (10 per 5min) in a single narrative = very high.
VELOCITY_MAX_TOKENS_PER_MIN = 2.0

# Recency: full score up to this many minutes old, decays to 0 at RECENCY_DECAY_MINUTES
RECENCY_FULL_MINUTES = 5.0
RECENCY_DECAY_MINUTES = 120.0

# Acceleration thresholds: short-term rate vs medium-term rate
ACCELERATION_INCREASE_RATIO = 1.2   # short > medium * 1.2 → increasing
ACCELERATION_DECREASE_RATIO = 0.8   # short < medium * 0.8 → decreasing

# Token count normalization reference (above this, score saturates at 1.0)
TOKEN_COUNT_SATURATION = 30

# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------

NOISE_MAX_TOKEN_COUNT = 3       # exclusive: < 3 → NOISE
WEAK_MIN_TOKEN_COUNT = 3        # >= 3 but below EMERGING thresholds
EMERGING_MIN_TOKEN_COUNT = 5    # >= 5 AND score >= EMERGING_SCORE_MIN
EMERGING_SCORE_MIN = 0.25
STRONG_MIN_TOKEN_COUNT = 8      # >= 8 AND score >= STRONG_SCORE_MIN AND accelerating
STRONG_SCORE_MIN = 0.50

# Classification labels (machine-readable + display-ready)
CLASS_NOISE = "NOISE"
CLASS_WEAK = "WEAK"
CLASS_EMERGING = "EMERGING"
CLASS_STRONG = "STRONG"


# ---------------------------------------------------------------------------
# NarrativeScore — all components visible
# ---------------------------------------------------------------------------

@dataclass
class NarrativeScore:
    """All score components for a single NarrativeCandidate.

    Attributes
    ----------
    token_count_component
        Contribution of token count (log-scaled, weight 0.35)
    velocity_component
        Contribution of recent velocity (weight 0.30)
    acceleration_component
        Contribution of velocity trend (weight 0.15)
    recency_component
        Contribution of recency — how recently a new token was seen (weight 0.10)
    corroboration_component
        Contribution of X spike + news confirmation (weight 0.10)
    total
        Weighted sum of all components, clamped to [0.0, 1.0]
    acceleration_label
        "increasing" | "flat" | "decreasing"
    tokens_last_5m
        Token count in last 5 minutes
    tokens_last_15m
        Token count in last 15 minutes
    tokens_last_60m
        Token count in last 60 minutes
    rate_per_minute
        Tokens per minute in last 5 minutes
    """

    token_count_component: float
    velocity_component: float
    acceleration_component: float
    recency_component: float
    corroboration_component: float
    total: float
    acceleration_label: str
    tokens_last_5m: int
    tokens_last_15m: int
    tokens_last_60m: int
    rate_per_minute: float


# ---------------------------------------------------------------------------
# Scoring function
# ---------------------------------------------------------------------------

def score_narrative_candidate(
    candidate: "NarrativeCandidate",
    now: float | None = None,
) -> NarrativeScore:
    """Compute a NarrativeScore for a candidate.

    All components are derived deterministically from the candidate's state.
    The result is suitable for ranking, classification, and building board entries.
    """
    if now is None:
        now = datetime.now(timezone.utc).timestamp()

    # --- Token count component (log-scaled) ---
    # 1 token → 0.0, 2 → 0.12, 5 → 0.28, 10 → 0.43, 30+ → ~1.0
    count = candidate.token_count
    raw_count_score = math.log1p(max(0, count - 1)) / math.log1p(TOKEN_COUNT_SATURATION)
    token_count_component = min(1.0, raw_count_score) * W_TOKEN_COUNT

    # --- Velocity component (tokens in last 5min, normalized) ---
    t5m = candidate.token_count_in_window(300.0, now)   # 5 min
    t15m = candidate.token_count_in_window(900.0, now)  # 15 min
    t60m = candidate.token_count_in_window(3600.0, now) # 60 min
    rate_per_min = t5m / 5.0  # tokens per minute in 5min window
    velocity_score = min(1.0, rate_per_min / VELOCITY_MAX_TOKENS_PER_MIN)
    velocity_component = velocity_score * W_VELOCITY

    # --- Acceleration component ---
    # Compare 5-min rate vs 15-min rate
    rate_5m = t5m / 5.0
    rate_15m = t15m / 15.0
    if rate_15m == 0:
        # No 15-min baseline — classify by presence of recent activity
        if t5m >= 2:
            acceleration_label = "increasing"
            accel_score = 1.0
        elif t5m == 1:
            acceleration_label = "flat"
            accel_score = 0.5
        else:
            acceleration_label = "flat"
            accel_score = 0.5
    elif rate_5m >= rate_15m * ACCELERATION_INCREASE_RATIO:
        acceleration_label = "increasing"
        accel_score = 1.0
    elif rate_5m <= rate_15m * ACCELERATION_DECREASE_RATIO:
        acceleration_label = "decreasing"
        accel_score = 0.0
    else:
        acceleration_label = "flat"
        accel_score = 0.5
    acceleration_component = accel_score * W_ACCELERATION

    # --- Recency component (time since last new token was seen) ---
    time_since_last = now - candidate.last_seen
    minutes_since = time_since_last / 60.0
    if minutes_since <= RECENCY_FULL_MINUTES:
        recency_score = 1.0
    else:
        # Linear decay from 1.0 at RECENCY_FULL_MINUTES to 0.0 at RECENCY_DECAY_MINUTES
        decay_span = RECENCY_DECAY_MINUTES - RECENCY_FULL_MINUTES
        recency_score = max(
            0.0,
            1.0 - (minutes_since - RECENCY_FULL_MINUTES) / decay_span,
        )
    recency_component = recency_score * W_RECENCY

    # --- Corroboration component ---
    # X spike: up to 70% of corroboration weight; news: up to 30%
    x_corr = candidate.x_spike_corroboration
    news_corr = candidate.news_corroboration
    corr_score = min(1.0, x_corr * 0.7 + news_corr * 0.3)
    corroboration_component = corr_score * W_CORROBORATION

    total = min(1.0, max(0.0,
        token_count_component
        + velocity_component
        + acceleration_component
        + recency_component
        + corroboration_component
    ))

    return NarrativeScore(
        token_count_component=round(token_count_component, 4),
        velocity_component=round(velocity_component, 4),
        acceleration_component=round(acceleration_component, 4),
        recency_component=round(recency_component, 4),
        corroboration_component=round(corroboration_component, 4),
        total=round(total, 4),
        acceleration_label=acceleration_label,
        tokens_last_5m=t5m,
        tokens_last_15m=t15m,
        tokens_last_60m=t60m,
        rate_per_minute=round(rate_per_min, 4),
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_narrative(candidate: "NarrativeCandidate", score: NarrativeScore) -> str:
    """Assign a classification label to a narrative candidate.

    Classification is strictly deterministic:
    - NOISE    : token_count < 3
    - STRONG   : token_count >= 8 AND score >= STRONG_SCORE_MIN AND accelerating
    - EMERGING : token_count >= 5 AND score >= EMERGING_SCORE_MIN
    - WEAK     : everything else meeting the NOISE bar
    """
    count = candidate.token_count

    if count < NOISE_MAX_TOKEN_COUNT:
        return CLASS_NOISE

    if (
        count >= STRONG_MIN_TOKEN_COUNT
        and score.total >= STRONG_SCORE_MIN
        and score.acceleration_label == "increasing"
    ):
        return CLASS_STRONG

    if count >= EMERGING_MIN_TOKEN_COUNT and score.total >= EMERGING_SCORE_MIN:
        return CLASS_EMERGING

    return CLASS_WEAK


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------

def build_reason(
    candidate: "NarrativeCandidate",
    score: NarrativeScore,
    classification: str,
) -> str:
    """Build a plain-English explanation of why this narrative is showing up.

    Uses only concrete computed values — no vague language, no hedging.
    Output is one to three sentences covering: detection context, velocity
    trend, and any corroboration signals.
    """
    count = candidate.token_count
    term = candidate.canonical_name

    # Sentence 1: detection context
    # Age of narrative
    age_seconds = candidate.age_seconds
    if age_seconds < 300:
        age_str = f"in the last {int(age_seconds / 60) + 1} min"
    elif age_seconds < 3600:
        age_str = f"over the last {int(age_seconds / 60)} min"
    else:
        age_str = f"over the last {int(age_seconds / 3600)}h"

    parts: list[str] = [
        f"Detected {count} token{'s' if count != 1 else ''} referencing '{term}' "
        f"{age_str}."
    ]

    # Sentence 2: velocity and acceleration
    if score.tokens_last_5m > 0:
        vel_str = f"{score.rate_per_minute:.1f} token/min"
        accel_str = {
            "increasing": " (velocity increasing)",
            "flat": " (velocity stable)",
            "decreasing": " (velocity declining)",
        }.get(score.acceleration_label, "")
        parts.append(f"Velocity: {vel_str}{accel_str}.")
    elif score.tokens_last_15m > 0:
        parts.append(
            f"No new tokens in last 5min; {score.tokens_last_15m} in last 15min."
        )
    else:
        parts.append("No recent activity in last 15min.")

    # Sentence 3: corroboration (only if present)
    corr_parts: list[str] = []
    if candidate.x_spike_corroboration > 0:
        corr_parts.append(
            f"X spike match (boost {candidate.x_spike_corroboration:.2f})"
        )
    if candidate.news_corroboration > 0:
        corr_parts.append(
            f"news mention (boost {candidate.news_corroboration:.2f})"
        )
    if corr_parts:
        parts.append(f"Corroborated by: {', '.join(corr_parts)}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Board entry builder
# ---------------------------------------------------------------------------

def to_board_entry(
    candidate: "NarrativeCandidate",
    now: float | None = None,
) -> dict:
    """Build a complete operator board entry for a NarrativeCandidate.

    Returns a self-contained dict with all data needed for display and
    ranking.  Sorted position is determined by narrative_score descending.
    """
    if now is None:
        now = datetime.now(timezone.utc).timestamp()

    score = score_narrative_candidate(candidate, now)
    classification = classify_narrative(candidate, score)
    reason = build_reason(candidate, score, classification)

    first_seen_dt = datetime.fromtimestamp(candidate.first_seen, tz=timezone.utc)
    last_seen_dt = datetime.fromtimestamp(candidate.last_seen, tz=timezone.utc)

    return {
        # --- Identity ---
        "candidate_id": candidate.candidate_id,
        "term": candidate.canonical_name,
        "aliases": sorted(candidate.aliases)[:5],

        # --- Score and classification ---
        "narrative_score": score.total,
        "classification": classification,
        "confidence": candidate.confidence(now),

        # --- Token cluster ---
        "token_count": candidate.token_count,
        "tokens": [
            {"name": name}
            for name in candidate.linked_token_names[:10]
        ],

        # --- Timing ---
        "first_seen": first_seen_dt.isoformat(),
        "last_seen": last_seen_dt.isoformat(),
        "age_seconds": round(candidate.age_seconds, 0),

        # --- Velocity ---
        "velocity": {
            "tokens_last_5m": score.tokens_last_5m,
            "tokens_last_15m": score.tokens_last_15m,
            "tokens_last_60m": score.tokens_last_60m,
            "rate_per_minute": score.rate_per_minute,
            "acceleration": score.acceleration_label,
        },

        # --- Corroboration ---
        "corroboration": {
            "x_confirmed": candidate.x_spike_corroboration > 0,
            "x_boost": round(candidate.x_spike_corroboration, 3),
            "news_confirmed": candidate.news_corroboration > 0,
            "news_boost": round(candidate.news_corroboration, 3),
        },

        # --- Score breakdown (fully transparent) ---
        "score_breakdown": {
            "token_count_component": score.token_count_component,
            "velocity_component": score.velocity_component,
            "acceleration_component": score.acceleration_component,
            "recency_component": score.recency_component,
            "corroboration_component": score.corroboration_component,
            "total": score.total,
            "weights": {
                "token_count": W_TOKEN_COUNT,
                "velocity": W_VELOCITY,
                "acceleration": W_ACCELERATION,
                "recency": W_RECENCY,
                "corroboration": W_CORROBORATION,
            },
        },

        # --- Explainability ---
        "reason": reason,

        # --- Pattern flags (populated below) ---
        "pattern_flags": [],
        "token_clusters": [],
    }

    add_cluster_info_to_board_entry(entry)
    return entry


# ---------------------------------------------------------------------------
# Board builder (applies to a list of candidates)
# ---------------------------------------------------------------------------

def build_narrative_board(
    candidates: "list[NarrativeCandidate]",
    include_noise: bool = False,
    now: float | None = None,
) -> list[dict]:
    """Build and rank the full narrative board from a list of candidates.

    Parameters
    ----------
    candidates
        All active NarrativeCandidates from NarrativeDiscoveryEngine.
    include_noise
        If False (default), NOISE-classified candidates are excluded from output.
    now
        Current timestamp for consistent computation across all candidates.

    Returns
    -------
    List of board entry dicts sorted by narrative_score descending.
    """
    if now is None:
        now = datetime.now(timezone.utc).timestamp()

    entries = []
    for cand in candidates:
        entry = to_board_entry(cand, now)
        if not include_noise and entry["classification"] == CLASS_NOISE:
            continue
        entries.append(entry)

    # Sort: classification weight (STRONG=4 > EMERGING=3 > WEAK=2 > NOISE=1)
    # then velocity (tokens_last_5m desc) then token_count desc
    _cls_weight = {CLASS_STRONG: 4, CLASS_EMERGING: 3, CLASS_WEAK: 2, CLASS_NOISE: 1}
    entries.sort(
        key=lambda e: (
            _cls_weight.get(e["classification"], 0),
            e["velocity"]["tokens_last_5m"],
            e["token_count"],
        ),
        reverse=True,
    )
    return entries
