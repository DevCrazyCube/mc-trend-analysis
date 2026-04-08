"""Core narrative intelligence engine.

Computes velocity, strength, manages lifecycle state machine, quality gating,
competition/winner selection, clustering, and suppression diagnostics.

Reference: docs/intelligence/narrative-intelligence.md

Design principles:
  - No fallback behavior: alerts require RISING+ narratives, period.
  - Strict winner-takes-all: one winner per group, all others suppressed.
  - Every suppression has a machine-readable reason.
  - Every winner has a full justification breakdown.
  - Silence is preferred over weak signals.

All thresholds are configurable via NarrativeConfig (no hardcoded values).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Suppression reason codes (machine-readable, stored in database)
# ---------------------------------------------------------------------------

SUPPRESSION_LOST_TO_STRONGER_NARRATIVE = "lost_to_stronger_narrative"
SUPPRESSION_LOST_TO_STRONGER_TOKEN = "lost_to_stronger_token"
SUPPRESSION_BELOW_MIN_STRENGTH = "below_min_strength"
SUPPRESSION_BELOW_MIN_VELOCITY = "below_min_velocity"
SUPPRESSION_INSUFFICIENT_SOURCE_COUNT = "insufficient_source_count"
SUPPRESSION_INSUFFICIENT_SOURCE_DIVERSITY = "insufficient_source_diversity"
SUPPRESSION_NOT_TOP_IN_CLUSTER = "not_top_in_cluster"
SUPPRESSION_WINNER_MARGIN_NOT_MET = "winner_margin_not_met"
SUPPRESSION_NARRATIVE_STATE_TOO_LOW = "narrative_state_too_low"
SUPPRESSION_NARRATIVE_DEAD = "narrative_dead"
SUPPRESSION_NARRATIVE_FADING = "narrative_fading"


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

    # Clustering thresholds
    cluster_term_overlap_pct: float = 0.50
    cluster_token_overlap_min: int = 2
    cluster_min_source_diversity: int = 1


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

# Alert-eligible states — RISING or higher, NO fallback.
# If no narrative meets this bar, the system emits nothing. This is by design.
ALERT_ELIGIBLE_STATES = frozenset({LIFECYCLE_RISING, LIFECYCLE_TRENDING})


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

    def is_alert_eligible(self, narrative: dict) -> bool:
        """Whether a narrative is strong enough for alert generation.

        Strict rule: RISING or TRENDING only. No fallback to EMERGING.
        If no narrative meets this bar, the system emits nothing.
        """
        state = narrative.get("state", LIFECYCLE_WEAK)
        return state in ALERT_ELIGIBLE_STATES

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

    def get_suppression_reasons(self, narrative: dict) -> list[dict]:
        """Return structured, machine-readable suppression reasons for a narrative.

        Each reason is a dict with: code, actual, threshold, detail.
        Returns an empty list if the narrative has no suppression reasons.
        """
        reasons: list[dict] = []
        state = narrative.get("state", LIFECYCLE_WEAK)
        sources = narrative.get("sources") or []
        strength = narrative.get("narrative_strength", 0.0) or 0.0
        velocity = narrative.get("narrative_velocity", 0.0) or 0.0
        velocity_state = narrative.get("velocity_state", "stalled")
        source_types = {s.get("source_type") for s in sources if s.get("source_type")}

        if state == LIFECYCLE_DEAD:
            reasons.append({
                "code": SUPPRESSION_NARRATIVE_DEAD,
                "actual": state,
                "threshold": "non-terminal",
                "detail": "Narrative is dead and cannot generate alerts",
            })
            return reasons

        if state == LIFECYCLE_FADING:
            reasons.append({
                "code": SUPPRESSION_NARRATIVE_FADING,
                "actual": state,
                "threshold": "RISING+",
                "detail": "Narrative is fading and below alert threshold",
            })

        if state not in ALERT_ELIGIBLE_STATES:
            reasons.append({
                "code": SUPPRESSION_NARRATIVE_STATE_TOO_LOW,
                "actual": state,
                "threshold": "RISING or TRENDING",
                "detail": f"State {state} is below alert eligibility (RISING+)",
            })

        if len(sources) < self.cfg.min_sources:
            reasons.append({
                "code": SUPPRESSION_INSUFFICIENT_SOURCE_COUNT,
                "actual": len(sources),
                "threshold": self.cfg.min_sources,
                "detail": f"{len(sources)} sources < minimum {self.cfg.min_sources}",
            })

        if strength < self.cfg.winner_min_strength:
            reasons.append({
                "code": SUPPRESSION_BELOW_MIN_STRENGTH,
                "actual": round(strength, 4),
                "threshold": self.cfg.winner_min_strength,
                "detail": f"strength {strength:.4f} < winner minimum {self.cfg.winner_min_strength}",
            })

        if velocity == 0.0 or velocity_state == VELOCITY_STALLED:
            reasons.append({
                "code": SUPPRESSION_BELOW_MIN_VELOCITY,
                "actual": round(velocity, 6),
                "threshold": "> 0",
                "detail": f"velocity {velocity:.6f} is stalled (no events in window)",
            })

        if len(source_types) < self.cfg.cluster_min_source_diversity:
            reasons.append({
                "code": SUPPRESSION_INSUFFICIENT_SOURCE_DIVERSITY,
                "actual": len(source_types),
                "threshold": self.cfg.cluster_min_source_diversity,
                "detail": f"{len(source_types)} source types < minimum {self.cfg.cluster_min_source_diversity}",
            })

        return reasons

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def cluster_narratives(
        self,
        narratives: list[dict],
        token_links: dict[str, list[str]] | None = None,
    ) -> dict[str, str]:
        """Deterministic narrative clustering based on term overlap and token overlap.

        Parameters
        ----------
        narratives
            List of narrative dicts with narrative_id, anchor_terms, related_terms.
        token_links
            Optional mapping of narrative_id -> list of token_ids linked to it.
            Used for token-overlap clustering.

        Returns
        -------
        dict[str, str]
            Mapping of narrative_id -> cluster_id.  Narratives in the same cluster
            share the same cluster_id (the narrative_id of the first member found).
        """
        if not narratives:
            return {}

        if token_links is None:
            token_links = {}

        # Build a union-find for clustering
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for n in narratives:
            nid = n.get("narrative_id", "")
            parent[nid] = nid

        # 1. Term and entity overlap
        # Uses max(len) as denominator to avoid false merges from tiny term sets.
        # A single shared term out of 1 would give 100% on min-denominator;
        # max-denominator requires both sides to share a meaningful fraction.
        for i, n1 in enumerate(narratives):
            terms1 = {t.upper() for t in (n1.get("anchor_terms") or [])}
            all_terms1 = terms1 | {t.upper() for t in (n1.get("related_terms") or [])}
            nid1 = n1.get("narrative_id", "")
            if not terms1:
                continue

            for j in range(i + 1, len(narratives)):
                n2 = narratives[j]
                terms2 = {t.upper() for t in (n2.get("anchor_terms") or [])}
                all_terms2 = terms2 | {t.upper() for t in (n2.get("related_terms") or [])}
                nid2 = n2.get("narrative_id", "")
                if not terms2:
                    continue

                # Check anchor term overlap (max-denominator to prevent single-term merges)
                overlap = len(terms1 & terms2)
                max_size = max(len(terms1), len(terms2))
                if overlap >= 2 and max_size > 0 and overlap / max_size >= self.cfg.cluster_term_overlap_pct:
                    union(nid1, nid2)
                    continue

                # Check broader term overlap (anchor + related, max-denominator)
                broad_overlap = len(all_terms1 & all_terms2)
                broad_max = max(len(all_terms1), len(all_terms2))
                if broad_overlap >= 2 and broad_max > 0 and broad_overlap / broad_max >= self.cfg.cluster_term_overlap_pct:
                    union(nid1, nid2)
                    continue

                # Check shared entity names (name + type must match)
                entities1 = {
                    (e.get("name", "").upper(), e.get("type", ""))
                    for e in (n1.get("entities") or [])
                    if e.get("name")
                }
                entities2 = {
                    (e.get("name", "").upper(), e.get("type", ""))
                    for e in (n2.get("entities") or [])
                    if e.get("name")
                }
                if entities1 and entities2 and len(entities1 & entities2) >= 1:
                    union(nid1, nid2)
                    continue

        # 2. Token overlap: >= cluster_token_overlap_min shared linked tokens
        narrative_ids = [n.get("narrative_id", "") for n in narratives]
        for i, nid1 in enumerate(narrative_ids):
            tokens1 = set(token_links.get(nid1, []))
            if len(tokens1) < self.cfg.cluster_token_overlap_min:
                continue
            for j in range(i + 1, len(narrative_ids)):
                nid2 = narrative_ids[j]
                tokens2 = set(token_links.get(nid2, []))
                if len(tokens1 & tokens2) >= self.cfg.cluster_token_overlap_min:
                    union(nid1, nid2)

        # Build result mapping
        return {nid: find(nid) for nid in parent}

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
          - competition_status: "winner" | "outcompeted" | "no_contest" | "below_threshold"
          - competition_rank: int (1 = winner)
          - suppression_reasons: list[dict] (structured reasons for non-winners)
          - winner_explanation: dict (for winners only — full strength breakdown)

        Strict winner-takes-all: only rank 1 in each group is the winner.
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

            winner_strength = (group[0].get("narrative_strength", 0.0) or 0.0) if group else 0.0

            for rank, n in enumerate(group, start=1):
                annotated = dict(n)
                strength = n.get("narrative_strength", 0.0) or 0.0

                if len(group) == 1:
                    if strength >= self.cfg.winner_min_strength:
                        annotated["competition_status"] = "no_contest"
                        annotated["suppression_reasons"] = []
                        annotated["winner_explanation"] = self._build_winner_explanation(
                            n, group, rank,
                        )
                    else:
                        annotated["competition_status"] = "below_threshold"
                        annotated["suppression_reasons"] = [{
                            "code": SUPPRESSION_BELOW_MIN_STRENGTH,
                            "actual": round(strength, 4),
                            "threshold": self.cfg.winner_min_strength,
                            "detail": f"strength {strength:.4f} < winner minimum {self.cfg.winner_min_strength}",
                        }]
                elif rank == 1 and strength >= self.cfg.winner_min_strength:
                    annotated["competition_status"] = "winner"
                    annotated["suppression_reasons"] = []
                    annotated["winner_explanation"] = self._build_winner_explanation(
                        n, group, rank,
                    )
                elif strength < self.cfg.winner_min_strength:
                    annotated["competition_status"] = "below_threshold"
                    annotated["suppression_reasons"] = [{
                        "code": SUPPRESSION_BELOW_MIN_STRENGTH,
                        "actual": round(strength, 4),
                        "threshold": self.cfg.winner_min_strength,
                        "detail": f"strength {strength:.4f} < winner minimum {self.cfg.winner_min_strength}",
                    }]
                else:
                    annotated["competition_status"] = "outcompeted"
                    annotated["suppression_reasons"] = [
                        {
                            "code": SUPPRESSION_LOST_TO_STRONGER_NARRATIVE,
                            "actual": round(strength, 4),
                            "threshold": round(winner_strength, 4),
                            "detail": f"lost to narrative with strength {winner_strength:.4f} (delta {winner_strength - strength:.4f})",
                        },
                        {
                            "code": SUPPRESSION_NOT_TOP_IN_CLUSTER,
                            "actual": rank,
                            "threshold": 1,
                            "detail": f"rank {rank} of {len(group)} in cluster",
                        },
                    ]

                annotated["competition_rank"] = rank
                results.append(annotated)

        return results

    def select_token_winners(
        self,
        scored_tokens: list[dict],
    ) -> list[dict]:
        """Select winner tokens within a narrative — strict winner-takes-all.

        Sort by net_potential descending.  Index 0 is the winner.
        All others are suppressed — no override, no margin pass-through.

        Tokens close to the winner (within ``token_competition_margin``) get an
        additional informational suppression code so operators can see near-misses.

        Input: list of scored token dicts with at least net_potential and token_id.
        Returns the same list annotated with:
          - token_competition_status: "winner" | "suppressed"
          - suppression_reasons: list[dict]
          - winner_explanation: dict (for winner only)
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
                # Winner: rank 1, no suppression
                annotated["token_competition_status"] = "winner"
                annotated["suppression_reasons"] = []
                annotated["winner_explanation"] = {
                    "net_potential": round(score, 4),
                    "rank": 1,
                    "total_competitors": len(sorted_tokens),
                    "margin_over_second": round(
                        score - (sorted_tokens[1].get("net_potential", 0.0) or 0.0), 4
                    ) if len(sorted_tokens) > 1 else None,
                }
            else:
                # Suppressed: every non-winner token, no exceptions
                annotated["token_competition_status"] = "suppressed"
                delta = winner_score - score
                suppression = [{
                    "code": SUPPRESSION_LOST_TO_STRONGER_TOKEN,
                    "actual": round(score, 4),
                    "threshold": round(winner_score, 4),
                    "detail": f"net_potential {score:.4f} < winner {winner_score:.4f} (delta {delta:.4f})",
                }]
                if delta <= self.cfg.token_competition_margin:
                    suppression.append({
                        "code": SUPPRESSION_WINNER_MARGIN_NOT_MET,
                        "actual": round(delta, 4),
                        "threshold": self.cfg.token_competition_margin,
                        "detail": f"within margin {self.cfg.token_competition_margin} but strict winner-takes-all enforced",
                    })
                annotated["suppression_reasons"] = suppression

            results.append(annotated)

        return results

    # ------------------------------------------------------------------
    # Winner Explanation (Requirement 5)
    # ------------------------------------------------------------------

    def _build_winner_explanation(
        self,
        narrative: dict,
        group: list[dict],
        rank: int,
    ) -> dict:
        """Build a full 'why this won' explanation for a narrative winner."""
        sources = narrative.get("sources") or []
        source_count = len(sources)
        strength = narrative.get("narrative_strength", 0.0) or 0.0
        velocity = narrative.get("narrative_velocity", 0.0) or 0.0
        velocity_state = narrative.get("velocity_state", "unknown")
        source_types = {s.get("source_type") for s in sources if s.get("source_type")}

        # Compute sub-score contributions
        sc_score = min(source_count / self.cfg.max_source_count, 1.0) if self.cfg.max_source_count > 0 else 0.0
        vel_score = min(max(velocity, 0.0) / self.cfg.max_velocity, 1.0) if self.cfg.max_velocity > 0 else 0.0
        div_score = min(len(source_types) / self.cfg.max_source_types, 1.0) if self.cfg.max_source_types > 0 else 0.0

        explanation = {
            "narrative_strength": round(strength, 4),
            "strength_breakdown": {
                "source_count_contribution": round(sc_score * self.cfg.strength_w_source_count, 4),
                "velocity_contribution": round(vel_score * self.cfg.strength_w_velocity, 4),
                "recency_contribution": round(
                    strength
                    - sc_score * self.cfg.strength_w_source_count
                    - vel_score * self.cfg.strength_w_velocity
                    - div_score * self.cfg.strength_w_diversity,
                    4,
                ),
                "diversity_contribution": round(div_score * self.cfg.strength_w_diversity, 4),
            },
            "velocity": round(velocity, 6),
            "velocity_state": velocity_state,
            "source_count": source_count,
            "source_types": sorted(source_types),
            "source_diversity": len(source_types),
            "cluster_size": len(group),
            "rank": rank,
        }

        # Runner-up comparison
        if len(group) > 1 and rank == 1:
            runner_up = group[1]
            runner_strength = runner_up.get("narrative_strength", 0.0) or 0.0
            explanation["runner_up"] = {
                "narrative_id": runner_up.get("narrative_id"),
                "strength": round(runner_strength, 4),
                "strength_difference": round(strength - runner_strength, 4),
                "margin_of_victory": round(
                    (strength - runner_strength) / strength if strength > 0 else 0.0, 4
                ),
            }
            explanation["competing_narratives"] = len(group)

        return explanation

    def build_token_winner_explanation(
        self,
        winner: dict,
        all_tokens: list[dict],
    ) -> dict:
        """Build a full 'why this won' explanation for a token winner."""
        score = winner.get("net_potential", 0.0) or 0.0
        explanation = {
            "token_id": winner.get("token_id"),
            "net_potential": round(score, 4),
            "rank": 1,
            "total_competitors": len(all_tokens),
        }

        if len(all_tokens) > 1:
            sorted_by_score = sorted(
                all_tokens,
                key=lambda x: x.get("net_potential", 0.0) or 0.0,
                reverse=True,
            )
            if len(sorted_by_score) > 1:
                runner_score = sorted_by_score[1].get("net_potential", 0.0) or 0.0
                explanation["runner_up"] = {
                    "token_id": sorted_by_score[1].get("token_id"),
                    "net_potential": round(runner_score, 4),
                    "score_difference": round(score - runner_score, 4),
                }

        return explanation


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
