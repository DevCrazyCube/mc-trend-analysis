"""Windowed entity tracking and spike detection for X emergent narratives.

Tracks mention counts per entity across time windows, computes baseline
rates, and detects spikes when short-term activity exceeds baseline by a
configurable threshold.

All state is in-memory per process with optional SQLite persistence for
cross-cycle continuity.  No LLM -- deterministic spike detection.

Reference: docs/ingestion/x-emergent-narrative-detection.md
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from mctrend.narrative.entity_extraction import CandidateEntity

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SpikeConfig:
    """Tunable parameters for spike detection."""
    spike_threshold: float = 3.0        # short_term / baseline ratio to flag spike
    min_mentions: int = 5               # minimum mentions in short-term window
    min_authors: int = 3                # minimum unique authors for spike
    short_term_window_seconds: float = 1800.0   # 30 minutes
    baseline_window_seconds: float = 21600.0     # 6 hours
    baseline_floor: float = 0.1         # minimum baseline rate (mentions/min)
    prune_after_seconds: float = 86400.0  # 24 hours


# ---------------------------------------------------------------------------
# Spike classification
# ---------------------------------------------------------------------------

def classify_spike(spike_ratio: float) -> str:
    """Classify a spike ratio into a human-readable level."""
    if spike_ratio < 2.0:
        return "not_spiking"
    if spike_ratio < 5.0:
        return "mild"
    if spike_ratio < 15.0:
        return "emerging"
    return "viral"


# ---------------------------------------------------------------------------
# Entity state
# ---------------------------------------------------------------------------

@dataclass
class EntityState:
    """Tracked state for a single entity across time windows."""
    canonical: str
    entity_type: str = "topic"
    first_seen: float = 0.0              # monotonic timestamp
    last_seen: float = 0.0               # monotonic timestamp
    # Windowed observations: list of (monotonic_time, mention_count, unique_authors, engagement)
    observations: list[tuple[float, int, int, float]] = field(default_factory=list)
    # Accumulated totals
    total_count: int = 0
    is_chronic: bool = False
    linked_narrative_id: str | None = None

    def add_observation(
        self,
        mention_count: int,
        unique_authors: int,
        engagement: float,
        now: float | None = None,
    ) -> None:
        """Record an observation from the current cycle."""
        t = now if now is not None else time.monotonic()
        self.observations.append((t, mention_count, unique_authors, engagement))
        self.total_count += mention_count
        self.last_seen = t
        if self.first_seen == 0.0:
            self.first_seen = t

    def prune_observations(self, max_age_seconds: float, now: float | None = None) -> None:
        """Remove observations older than max_age_seconds."""
        t = now if now is not None else time.monotonic()
        cutoff = t - max_age_seconds
        self.observations = [(ts, mc, ua, eng) for ts, mc, ua, eng in self.observations if ts >= cutoff]

    def mentions_in_window(self, window_seconds: float, now: float | None = None) -> int:
        """Count total mentions within a time window ending at now."""
        t = now if now is not None else time.monotonic()
        cutoff = t - window_seconds
        return sum(mc for ts, mc, _, _ in self.observations if ts >= cutoff)

    def authors_in_window(self, window_seconds: float, now: float | None = None) -> int:
        """Count total unique author slots within a time window.

        Note: this returns the sum of unique_authors per observation, which
        is an upper bound (same author may appear in multiple observations).
        For precise counting, the extraction layer should be used.
        """
        t = now if now is not None else time.monotonic()
        cutoff = t - window_seconds
        return sum(ua for ts, _, ua, _ in self.observations if ts >= cutoff)

    def rate_in_window(self, window_seconds: float, now: float | None = None) -> float:
        """Compute mentions per minute within a time window."""
        mentions = self.mentions_in_window(window_seconds, now)
        minutes = window_seconds / 60.0
        return mentions / minutes if minutes > 0 else 0.0


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class XEntityTracker:
    """Track entities across cycles, detect spikes.

    Call ``update()`` each cycle with the extracted candidates.
    Call ``detect_spikes()`` to get currently spiking entities.
    """

    def __init__(self, config: SpikeConfig | None = None):
        self.cfg = config or SpikeConfig()
        self._entities: dict[str, EntityState] = {}

    @property
    def tracked_count(self) -> int:
        return len(self._entities)

    def update(
        self,
        candidates: dict[str, CandidateEntity],
        now: float | None = None,
    ) -> None:
        """Ingest a batch of extracted candidates from one cycle.

        Creates new EntityState entries for unseen entities and adds
        observations for existing ones.
        """
        t = now if now is not None else time.monotonic()

        for canonical, cand in candidates.items():
            if canonical not in self._entities:
                self._entities[canonical] = EntityState(
                    canonical=canonical,
                    entity_type=cand.entity_type,
                    first_seen=t,
                )
                logger.debug(
                    "x_entity_tracking_started",
                    entity=canonical,
                    entity_type=cand.entity_type,
                )

            state = self._entities[canonical]
            state.add_observation(
                mention_count=cand.mention_count,
                unique_authors=cand.unique_authors,
                engagement=cand.engagement_total,
                now=t,
            )

    def detect_spikes(self, now: float | None = None) -> list[dict]:
        """Evaluate all tracked entities for spike conditions.

        Returns a list of spike records for entities that meet the
        spike threshold.
        """
        t = now if now is not None else time.monotonic()
        spikes: list[dict] = []

        for canonical, state in self._entities.items():
            if state.is_chronic:
                continue

            short_term_count = state.mentions_in_window(
                self.cfg.short_term_window_seconds, t,
            )
            short_term_authors = state.authors_in_window(
                self.cfg.short_term_window_seconds, t,
            )

            # Minimum thresholds
            if short_term_count < self.cfg.min_mentions:
                continue
            if short_term_authors < self.cfg.min_authors:
                continue

            # Compute rates
            short_term_rate = state.rate_in_window(
                self.cfg.short_term_window_seconds, t,
            )
            baseline_rate = state.rate_in_window(
                self.cfg.baseline_window_seconds, t,
            )
            effective_baseline = max(baseline_rate, self.cfg.baseline_floor)

            spike_ratio = short_term_rate / effective_baseline
            spike_class = classify_spike(spike_ratio)

            if spike_ratio >= self.cfg.spike_threshold:
                spike = {
                    "entity": canonical,
                    "entity_type": state.entity_type,
                    "spike_ratio": round(spike_ratio, 2),
                    "spike_class": spike_class,
                    "short_term_count": short_term_count,
                    "short_term_authors": short_term_authors,
                    "short_term_rate": round(short_term_rate, 4),
                    "baseline_rate": round(baseline_rate, 4),
                    "total_count": state.total_count,
                    "first_seen_ago_seconds": round(t - state.first_seen, 1),
                }
                spikes.append(spike)
                logger.info(
                    "x_spike_detected",
                    entity=canonical,
                    spike_ratio=round(spike_ratio, 2),
                    spike_class=spike_class,
                    short_term_count=short_term_count,
                    authors=short_term_authors,
                )
            else:
                if short_term_count >= self.cfg.min_mentions:
                    logger.debug(
                        "x_spike_not_strong_enough",
                        entity=canonical,
                        spike_ratio=round(spike_ratio, 2),
                        short_term_count=short_term_count,
                    )

        return spikes

    def prune(self, now: float | None = None) -> int:
        """Remove stale entities and old observations.

        Returns the number of entities pruned.
        """
        t = now if now is not None else time.monotonic()
        cutoff = t - self.cfg.prune_after_seconds
        pruned = 0

        stale_keys = [
            k for k, s in self._entities.items()
            if s.last_seen < cutoff
        ]
        for k in stale_keys:
            del self._entities[k]
            pruned += 1

        # Prune old observations from remaining entities
        for state in self._entities.values():
            state.prune_observations(self.cfg.baseline_window_seconds, t)

        if pruned:
            logger.debug("x_entities_pruned", count=pruned, remaining=len(self._entities))

        return pruned

    def get_state(self, canonical: str) -> EntityState | None:
        """Get tracked state for an entity (for testing/debugging)."""
        return self._entities.get(canonical)

    def mark_chronic(self, canonical: str) -> None:
        """Mark an entity as chronic (always-present, never spiking)."""
        if canonical in self._entities:
            self._entities[canonical].is_chronic = True

    def get_summary(self, now: float | None = None) -> dict:
        """Return summary metrics for the current tracker state."""
        t = now if now is not None else time.monotonic()
        active = sum(
            1 for s in self._entities.values()
            if s.mentions_in_window(self.cfg.short_term_window_seconds, t) > 0
        )
        return {
            "tracked_entities": len(self._entities),
            "active_in_short_window": active,
            "chronic_count": sum(1 for s in self._entities.values() if s.is_chronic),
        }
