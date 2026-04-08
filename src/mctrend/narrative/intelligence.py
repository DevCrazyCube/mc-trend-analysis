"""Core narrative intelligence engine.

Computes velocity, strength, manages lifecycle state machine, quality gating,
and competition/winner selection.

Reference: docs/intelligence/narrative-intelligence.md

All thresholds are configurable via NarrativeConfig (no hardcoded values).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class NarrativeConfig:
    """All configurable thresholds for narrative intelligence.

    Every value has a documented default.  Override via Settings or constructor.
    """

    # Velocity
    velocity_window_minutes: float = 30.0
    max_velocity: float = 0.5  # events/min for normalization

    # Strength weights
    strength_w_source_count: float = 0.30
    strength_w_velocity: float = 0.35
    strength_w_recency: float = 0.25
    strength_w_diversity: float = 0.10
    max_source_count: int = 5
    recency_decay_minutes: float = 120.0
    max_source_types: int = 4

    # Lifecycle thresholds
    min_sources: int = 2
    weak_threshold: float = 0.15
    emerging_threshold: float = 0.20
    rising_threshold: float = 0.35
    trending_threshold: float = 0.55
    trending_min_sources: int = 3
    fading_threshold: float = 0.25
    dead_threshold: float = 0.10
    dead_timeout_minutes: float = 120.0

    # Competition
    winner_min_strength: float = 0.30
    token_competition_margin: float = 0.05


# ---------------------------------------------------------------------------
# Velocity states
# ---------------------------------------------------------------------------

VELOCITY_ACCELERATING = "accelerating"
VELOCITY_STABLE = "stable"
VELOCITY_DECELERATING = "decelerating"
VELOCITY_STALLED = "stalled"

# ---------------------------------------------------------------------------
# Lifecycle states (ordered by quality)
# ---------------------------------------------------------------------------

LIFECYCLE_WEAK = "WEAK"
LIFECYCLE_EMERGING = "EMERGING"
LIFECYCLE_RISING = "RISING"
LIFECYCLE_TRENDING = "TRENDING"
LIFECYCLE_FADING = "FADING"
LIFECYCLE_DEAD = "DEAD"
LIFECYCLE_MERGED = "MERGED"

# Scoring-eligible states
SCORING_ELIGIBLE_STATES = frozenset({LIFECYCLE_EMERGING, LIFECYCLE_RISING, LIFECYCLE_TRENDING})

# Alert-eligible states (narratives must be at least this strong for alerts)
ALERT_ELIGIBLE_STATES = frozenset({LIFECYCLE_RISING, LIFECYCLE_TRENDING})

# Fallback: if no RISING+ narratives exist, allow EMERGING
ALERT_FALLBACK_STATES = frozenset({LIFECYCLE_EMERGING, LIFECYCLE_RISING, LIFECYCLE_TRENDING})


# ---------------------------------------------------------------------------
# NarrativeIntelligence
# ---------------------------------------------------------------------------

class NarrativeIntelligence:
    """Evaluates and manages narrative quality each pipeline cycle.

    Stateless — all state lives on the narrative records in the database.
    Each method takes narrative data and returns updated data.
    """

    def __init__(self, config: NarrativeConfig | None = None) -> None:
        self.cfg = config or NarrativeConfig()

    # ------------------------------------------------------------------
    # Velocity
    # ------------------------------------------------------------------

    def compute_velocity(
        self,
        narrative: dict,
        now: datetime | None = None,
    ) -> dict:
        """Compute narrative velocity from source timestamps.

        Counts source updates within the velocity window and computes
        events-per-minute.  Also computes velocity_delta from previous value.

        Returns a dict of fields to merge into the narrative record:
          narrative_velocity, velocity_delta, velocity_state, velocity_updated_at
        """
        if now is None:
            now = datetime.now(timezone.utc)

        window_seconds = self.cfg.velocity_window_minutes * 60.0
        cutoff = now.timestamp() - window_seconds

        sources = narrative.get("sources") or []
        events_in_window = 0
        for src in sources:
            last_updated = src.get("last_updated") or src.get("first_seen")
            if last_updated:
                ts = _parse_ts(last_updated)
                if ts is not None and ts >= cutoff:
                    events_in_window += 1

        velocity = events_in_window / self.cfg.velocity_window_minutes if self.cfg.velocity_window_minutes > 0 else 0.0

        previous_velocity = narrative.get("narrative_velocity")
        if previous_velocity is not None and isinstance(previous_velocity, (int, float)):
            velocity_delta = velocity - previous_velocity
        else:
            velocity_delta = 0.0

        # Classify velocity state
        if velocity == 0.0:
            velocity_state = VELOCITY_STALLED
        elif velocity_delta > 0.01:
            velocity_state = VELOCITY_ACCELERATING
        elif velocity_delta < -0.01:
            velocity_state = VELOCITY_DECELERATING
        else:
            velocity_state = VELOCITY_STABLE

        return {
            "narrative_velocity": round(velocity, 6),
            "velocity_delta": round(velocity_delta, 6),
            "velocity_state": velocity_state,
            "velocity_updated_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # Strength
    # ------------------------------------------------------------------

    def compute_strength(
        self,
        narrative: dict,
        now: datetime | None = None,
    ) -> float:
        """Compute narrative strength from source count, velocity, recency, diversity.

        Returns a float in [0, 1].
        """
        if now is None:
            now = datetime.now(timezone.utc)

        sources = narrative.get("sources") or []
        source_count = len(sources)

        # Source count score
        sc_score = min(source_count / self.cfg.max_source_count, 1.0)

        # Velocity score
        velocity = narrative.get("narrative_velocity")
        if velocity is not None and isinstance(velocity, (int, float)):
            vel_score = min(max(velocity, 0.0) / self.cfg.max_velocity, 1.0)
        else:
            vel_score = 0.0

        # Recency score — minutes since last source update
        last_update = narrative.get("updated_at")
        if last_update:
            ts = _parse_ts(last_update)
            if ts is not None:
                minutes_since = (now.timestamp() - ts) / 60.0
                rec_score = max(0.0, 1.0 - minutes_since / self.cfg.recency_decay_minutes)
            else:
                rec_score = 0.0
        else:
            rec_score = 0.0

        # Diversity score
        source_types = {s.get("source_type") for s in sources if s.get("source_type")}
        div_score = min(len(source_types) / self.cfg.max_source_types, 1.0)

        strength = (
            sc_score * self.cfg.strength_w_source_count
            + vel_score * self.cfg.strength_w_velocity
            + rec_score * self.cfg.strength_w_recency
            + div_score * self.cfg.strength_w_diversity
        )

        return round(max(0.0, min(1.0, strength)), 4)

    # ------------------------------------------------------------------
    # Lifecycle State Machine
    # ------------------------------------------------------------------

    def evaluate_state(
        self,
        narrative: dict,
        now: datetime | None = None,
    ) -> str:
        """Determine the correct lifecycle state for a narrative.

        Uses current velocity, strength, source count, and recency.
        Returns the new state string.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        current_state = narrative.get("state", LIFECYCLE_WEAK)

        # DEAD and MERGED are terminal
        if current_state == LIFECYCLE_DEAD:
            return LIFECYCLE_DEAD
        if current_state == LIFECYCLE_MERGED:
            return LIFECYCLE_MERGED

        sources = narrative.get("sources") or []
        source_count = len(sources)
        strength = narrative.get("narrative_strength")
        if strength is None:
            strength = self.compute_strength(narrative, now)

        velocity_state = narrative.get("velocity_state", VELOCITY_STALLED)

        # Check dead timeout
        last_update_str = narrative.get("updated_at")
        if last_update_str:
            ts = _parse_ts(last_update_str)
            if ts is not None:
                minutes_since = (now.timestamp() - ts) / 60.0
                if minutes_since >= self.cfg.dead_timeout_minutes:
                    return LIFECYCLE_DEAD

        # Check thresholds from highest to lowest
        if strength < self.cfg.dead_threshold:
            return LIFECYCLE_DEAD

        # TRENDING: high velocity + multi-source + strong
        if (
            velocity_state in (VELOCITY_ACCELERATING, VELOCITY_STABLE)
            and source_count >= self.cfg.trending_min_sources
            and strength >= self.cfg.trending_threshold
        ):
            return LIFECYCLE_TRENDING

        # RISING: accelerating velocity + sufficient sources + strong enough
        if (
            velocity_state == VELOCITY_ACCELERATING
            and source_count >= self.cfg.min_sources
            and strength >= self.cfg.rising_threshold
        ):
            return LIFECYCLE_RISING

        # FADING: decelerating or weak
        if velocity_state == VELOCITY_DECELERATING and strength < self.cfg.fading_threshold:
            return LIFECYCLE_FADING

        if velocity_state == VELOCITY_STALLED and current_state in (LIFECYCLE_RISING, LIFECYCLE_TRENDING):
            return LIFECYCLE_FADING

        # EMERGING: meets minimum thresholds
        if source_count >= self.cfg.min_sources and strength >= self.cfg.emerging_threshold:
            return LIFECYCLE_EMERGING

        # WEAK: below minimum
        return LIFECYCLE_WEAK

    def transition_narrative(
        self,
        narrative: dict,
        now: datetime | None = None,
    ) -> dict:
        """Full narrative evaluation: compute velocity, strength, state.

        Returns a dict of ALL fields to merge into the narrative record.
        Does NOT mutate the input dict.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # 1. Compute velocity
        velocity_fields = self.compute_velocity(narrative, now)
        # Temporarily merge for strength computation
        temp = {**narrative, **velocity_fields}

        # 2. Compute strength
        strength = self.compute_strength(temp, now)
        temp["narrative_strength"] = strength

        # 3. Evaluate state
        new_state = self.evaluate_state(temp, now)
        old_state = narrative.get("state", LIFECYCLE_WEAK)

        result = {
            **velocity_fields,
            "narrative_strength": strength,
            "attention_score": strength,  # backward compat: attention_score tracks strength
        }

        if new_state != old_state:
            result["state"] = new_state
            logger.info(
                "narrative_state_transition",
                narrative_id=narrative.get("narrative_id"),
                previous_state=old_state,
                new_state=new_state,
                strength=strength,
                velocity=velocity_fields["narrative_velocity"],
                velocity_state=velocity_fields["velocity_state"],
                source_count=len(narrative.get("sources") or []),
                reason=_transition_reason(old_state, new_state, temp),
            )

            if new_state == LIFECYCLE_DEAD:
                result["dead_at"] = now.isoformat()
            if new_state == LIFECYCLE_TRENDING and old_state != LIFECYCLE_TRENDING:
                result["peaked_at"] = now.isoformat()

        return result

    # ------------------------------------------------------------------
    # Quality Gating
    # ------------------------------------------------------------------

    def is_scoring_eligible(self, narrative: dict) -> bool:
        """Whether a narrative meets minimum quality for token scoring."""
        state = narrative.get("state", LIFECYCLE_WEAK)
        if state not in SCORING_ELIGIBLE_STATES:
            return False

        sources = narrative.get("sources") or []
        if len(sources) < self.cfg.min_sources:
            return False

        strength = narrative.get("narrative_strength", 0.0) or 0.0
        if strength < self.cfg.emerging_threshold:
            return False

        return True

    def is_alert_eligible(self, narrative: dict, has_rising_narratives: bool = True) -> bool:
        """Whether a narrative is strong enough for alert generation.

        If has_rising_narratives is True (there exist RISING+ narratives in
        this cycle), require RISING or higher.  Otherwise fall back to EMERGING.
        """
        state = narrative.get("state", LIFECYCLE_WEAK)
        if has_rising_narratives:
            return state in ALERT_ELIGIBLE_STATES
        return state in ALERT_FALLBACK_STATES

    def get_rejection_reason(self, narrative: dict) -> str | None:
        """Return a human-readable reason why a narrative is not scoring-eligible, or None."""
        state = narrative.get("state", LIFECYCLE_WEAK)
        sources = narrative.get("sources") or []
        strength = narrative.get("narrative_strength", 0.0) or 0.0

        if state == LIFECYCLE_DEAD:
            return "narrative_dead"
        if state == LIFECYCLE_MERGED:
            return "narrative_merged"
        if state == LIFECYCLE_WEAK:
            if len(sources) < self.cfg.min_sources:
                return f"insufficient_sources: {len(sources)} < {self.cfg.min_sources}"
            if strength < self.cfg.emerging_threshold:
                return f"strength_below_emerging: {strength:.3f} < {self.cfg.emerging_threshold}"
            return "state_weak"
        if state == LIFECYCLE_FADING:
            return "narrative_fading"
        return None

    # ------------------------------------------------------------------
    # Competition
    # ------------------------------------------------------------------

    def select_narrative_winners(
        self,
        narratives: list[dict],
    ) -> list[dict]:
        """Select winner narratives from a list.

        Groups by cluster_id (or treats each narrative as its own group).
        Returns all narratives annotated with:
          - competition_status: "winner" | "outcompeted" | "no_contest"
          - competition_rank: int (1 = winner)

        Narratives not meeting winner_min_strength get competition_status = "below_threshold".
        """
        # Group by cluster_id
        groups: dict[str, list[dict]] = {}
        for n in narratives:
            cluster = n.get("cluster_id") or n.get("narrative_id", "")
            groups.setdefault(cluster, []).append(n)

        results = []
        for _cluster_id, group in groups.items():
            # Sort by strength descending
            group.sort(key=lambda x: x.get("narrative_strength", 0.0) or 0.0, reverse=True)

            for rank, n in enumerate(group, start=1):
                annotated = dict(n)
                strength = n.get("narrative_strength", 0.0) or 0.0

                if len(group) == 1:
                    if strength >= self.cfg.winner_min_strength:
                        annotated["competition_status"] = "no_contest"
                    else:
                        annotated["competition_status"] = "below_threshold"
                elif rank == 1 and strength >= self.cfg.winner_min_strength:
                    annotated["competition_status"] = "winner"
                elif strength < self.cfg.winner_min_strength:
                    annotated["competition_status"] = "below_threshold"
                else:
                    annotated["competition_status"] = "outcompeted"

                annotated["competition_rank"] = rank
                results.append(annotated)

        return results

    def select_token_winners(
        self,
        scored_tokens: list[dict],
    ) -> list[dict]:
        """Select winner tokens within a narrative.

        Input: list of scored token dicts with at least net_potential and token_id.
        Returns the same list annotated with:
          - token_competition_status: "winner" | "within_margin" | "suppressed"

        Sorted by net_potential descending. The top token is the winner.
        Others within token_competition_margin of the winner are "within_margin".
        """
        if not scored_tokens:
            return []

        sorted_tokens = sorted(
            scored_tokens,
            key=lambda x: x.get("net_potential", 0.0) or 0.0,
            reverse=True,
        )

        winner_score = sorted_tokens[0].get("net_potential", 0.0) or 0.0

        results = []
        for i, t in enumerate(sorted_tokens):
            annotated = dict(t)
            score = t.get("net_potential", 0.0) or 0.0
            if i == 0:
                annotated["token_competition_status"] = "winner"
            elif winner_score - score <= self.cfg.token_competition_margin:
                annotated["token_competition_status"] = "within_margin"
            else:
                annotated["token_competition_status"] = "suppressed"
            results.append(annotated)

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(value) -> float | None:
    """Parse an ISO timestamp string to a Unix timestamp (seconds). Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None
    return None


def _transition_reason(old_state: str, new_state: str, narrative: dict) -> str:
    """Generate a human-readable reason for a state transition."""
    strength = narrative.get("narrative_strength", 0.0)
    vel_state = narrative.get("velocity_state", "unknown")
    source_count = len(narrative.get("sources") or [])

    if new_state == LIFECYCLE_DEAD:
        return f"strength={strength:.3f} or timeout reached"
    if new_state == LIFECYCLE_FADING:
        return f"velocity={vel_state}, strength={strength:.3f} declining"
    if new_state == LIFECYCLE_TRENDING:
        return f"velocity={vel_state}, strength={strength:.3f}, sources={source_count}"
    if new_state == LIFECYCLE_RISING:
        return f"velocity={vel_state}, strength={strength:.3f}, sources={source_count}"
    if new_state == LIFECYCLE_EMERGING:
        return f"meets min thresholds: strength={strength:.3f}, sources={source_count}"
    if new_state == LIFECYCLE_WEAK:
        return f"below min thresholds: strength={strength:.3f}, sources={source_count}"
    return f"{old_state}->{new_state}"
