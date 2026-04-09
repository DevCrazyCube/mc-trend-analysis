"""Unit tests for X entity tracking and spike detection.

Covers:
- EntityState windowed counting and rate computation
- XEntityTracker update and candidate integration
- Spike detection with threshold, min_mentions, min_authors
- Spike classification
- Observation pruning
- Chronic entity exclusion
- Tracker summary
"""
from __future__ import annotations

import pytest

from mctrend.narrative.entity_extraction import CandidateEntity
from mctrend.narrative.entity_tracker import (
    EntityState,
    SpikeConfig,
    XEntityTracker,
    classify_spike,
)


# ---------------------------------------------------------------------------
# Spike classification
# ---------------------------------------------------------------------------


class TestClassifySpike:
    def test_not_spiking(self):
        assert classify_spike(1.5) == "not_spiking"

    def test_mild(self):
        assert classify_spike(3.0) == "mild"

    def test_emerging(self):
        assert classify_spike(8.0) == "emerging"

    def test_viral(self):
        assert classify_spike(20.0) == "viral"

    def test_boundary_mild(self):
        assert classify_spike(2.0) == "mild"

    def test_boundary_emerging(self):
        assert classify_spike(5.0) == "emerging"

    def test_boundary_viral(self):
        assert classify_spike(15.0) == "viral"


# ---------------------------------------------------------------------------
# EntityState
# ---------------------------------------------------------------------------


class TestEntityState:
    def test_add_observation(self):
        state = EntityState(canonical="TRUMP")
        state.add_observation(5, 3, 10.0, now=100.0)
        assert state.total_count == 5
        assert len(state.observations) == 1
        assert state.first_seen == 100.0
        assert state.last_seen == 100.0

    def test_multiple_observations(self):
        state = EntityState(canonical="TRUMP")
        state.add_observation(5, 3, 10.0, now=100.0)
        state.add_observation(3, 2, 5.0, now=200.0)
        assert state.total_count == 8
        assert len(state.observations) == 2
        assert state.last_seen == 200.0

    def test_mentions_in_window(self):
        state = EntityState(canonical="TRUMP")
        state.add_observation(5, 3, 10.0, now=100.0)
        state.add_observation(3, 2, 5.0, now=200.0)
        state.add_observation(7, 4, 15.0, now=300.0)
        # Window of 150 seconds from now=300 captures obs at 200 and 300
        assert state.mentions_in_window(150.0, now=300.0) == 10

    def test_mentions_in_window_all(self):
        state = EntityState(canonical="TRUMP")
        state.add_observation(5, 3, 10.0, now=100.0)
        state.add_observation(3, 2, 5.0, now=200.0)
        # Window of 200 captures both
        assert state.mentions_in_window(200.0, now=300.0) == 8

    def test_rate_in_window(self):
        state = EntityState(canonical="TRUMP")
        # 10 mentions in a 60-second window = 10/min
        state.add_observation(10, 5, 20.0, now=100.0)
        rate = state.rate_in_window(60.0, now=100.0)
        assert abs(rate - 10.0) < 0.01

    def test_rate_in_window_zero_mentions(self):
        state = EntityState(canonical="TRUMP")
        rate = state.rate_in_window(60.0, now=100.0)
        assert rate == 0.0

    def test_prune_observations(self):
        state = EntityState(canonical="TRUMP")
        state.add_observation(5, 3, 10.0, now=100.0)
        state.add_observation(3, 2, 5.0, now=200.0)
        state.add_observation(7, 4, 15.0, now=300.0)
        # Prune anything older than 150 seconds from now=300
        state.prune_observations(150.0, now=300.0)
        assert len(state.observations) == 2  # 200 and 300 survive

    def test_authors_in_window(self):
        state = EntityState(canonical="TRUMP")
        state.add_observation(5, 3, 10.0, now=100.0)
        state.add_observation(3, 2, 5.0, now=200.0)
        # Upper bound: 3 + 2 = 5
        assert state.authors_in_window(200.0, now=300.0) == 5


# ---------------------------------------------------------------------------
# XEntityTracker — update
# ---------------------------------------------------------------------------


class TestTrackerUpdate:
    def test_new_entity_creates_state(self):
        tracker = XEntityTracker()
        cand = CandidateEntity("TRUMP")
        cand.mention_count = 5
        cand.author_ids = {"a", "b", "c"}
        cand.engagement_total = 10.0
        tracker.update({"TRUMP": cand}, now=100.0)
        assert tracker.tracked_count == 1
        state = tracker.get_state("TRUMP")
        assert state is not None
        assert state.total_count == 5

    def test_existing_entity_accumulates(self):
        tracker = XEntityTracker()
        cand1 = CandidateEntity("TRUMP")
        cand1.mention_count = 5
        cand1.author_ids = {"a", "b"}
        tracker.update({"TRUMP": cand1}, now=100.0)

        cand2 = CandidateEntity("TRUMP")
        cand2.mention_count = 3
        cand2.author_ids = {"c"}
        tracker.update({"TRUMP": cand2}, now=200.0)

        state = tracker.get_state("TRUMP")
        assert state.total_count == 8
        assert len(state.observations) == 2

    def test_multiple_entities(self):
        tracker = XEntityTracker()
        cand_a = CandidateEntity("TRUMP")
        cand_a.mention_count = 5
        cand_b = CandidateEntity("BIDEN")
        cand_b.mention_count = 3
        tracker.update({"TRUMP": cand_a, "BIDEN": cand_b}, now=100.0)
        assert tracker.tracked_count == 2


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------


class TestSpikeDetection:
    def _make_tracker(self, **kwargs):
        defaults = dict(
            spike_threshold=3.0,
            min_mentions=5,
            min_authors=3,
            short_term_window_seconds=1800.0,
            baseline_window_seconds=21600.0,
            baseline_floor=0.1,
        )
        defaults.update(kwargs)
        cfg = SpikeConfig(**defaults)
        return XEntityTracker(config=cfg)

    def test_spike_detected_when_ratio_exceeds_threshold(self):
        tracker = self._make_tracker()
        # Add old baseline observations (low rate)
        state = EntityState(canonical="TRUMP", entity_type="person")
        # Baseline: 2 mentions spread over 6 hours (very low rate)
        state.add_observation(1, 1, 0.1, now=0.0)
        state.add_observation(1, 1, 0.1, now=10000.0)
        # Short-term spike: 10 mentions from 5 authors
        state.add_observation(10, 5, 50.0, now=20000.0)
        tracker._entities["TRUMP"] = state

        spikes = tracker.detect_spikes(now=20000.0)
        assert len(spikes) == 1
        assert spikes[0]["entity"] == "TRUMP"
        assert spikes[0]["spike_ratio"] >= 3.0

    def test_no_spike_below_threshold(self):
        tracker = self._make_tracker()
        state = EntityState(canonical="BORING")
        # Uniform rate: 5 mentions per observation, steady
        for t in range(0, 20000, 1000):
            state.add_observation(5, 4, 10.0, now=float(t))
        tracker._entities["BORING"] = state

        spikes = tracker.detect_spikes(now=20000.0)
        # Uniform rate => ratio ~1.0, below threshold
        spiking = [s for s in spikes if s["entity"] == "BORING"]
        assert len(spiking) == 0

    def test_below_min_mentions_not_spiking(self):
        tracker = self._make_tracker(min_mentions=10)
        state = EntityState(canonical="LOW")
        state.add_observation(3, 3, 5.0, now=1000.0)
        tracker._entities["LOW"] = state

        spikes = tracker.detect_spikes(now=1000.0)
        assert len(spikes) == 0

    def test_below_min_authors_not_spiking(self):
        tracker = self._make_tracker(min_authors=5)
        state = EntityState(canonical="BOT")
        state.add_observation(20, 2, 30.0, now=1000.0)
        tracker._entities["BOT"] = state

        spikes = tracker.detect_spikes(now=1000.0)
        assert len(spikes) == 0

    def test_chronic_entity_excluded(self):
        tracker = self._make_tracker()
        state = EntityState(canonical="CHRONIC")
        state.add_observation(50, 20, 100.0, now=1000.0)
        state.is_chronic = True
        tracker._entities["CHRONIC"] = state

        spikes = tracker.detect_spikes(now=1000.0)
        assert len(spikes) == 0

    def test_spike_record_structure(self):
        tracker = self._make_tracker()
        state = EntityState(canonical="ELON", entity_type="person")
        state.add_observation(20, 10, 50.0, now=1000.0)
        tracker._entities["ELON"] = state

        spikes = tracker.detect_spikes(now=1000.0)
        assert len(spikes) == 1
        spike = spikes[0]
        assert "entity" in spike
        assert "entity_type" in spike
        assert "spike_ratio" in spike
        assert "spike_class" in spike
        assert "short_term_count" in spike
        assert "short_term_authors" in spike
        assert "short_term_rate" in spike
        assert "baseline_rate" in spike
        assert "total_count" in spike
        assert "first_seen_ago_seconds" in spike

    def test_multiple_spikes_returned(self):
        tracker = self._make_tracker()
        for name in ["TRUMP", "ELON", "DOGE"]:
            state = EntityState(canonical=name)
            state.add_observation(20, 10, 50.0, now=1000.0)
            tracker._entities[name] = state

        spikes = tracker.detect_spikes(now=1000.0)
        entities = {s["entity"] for s in spikes}
        assert entities == {"TRUMP", "ELON", "DOGE"}

    def test_baseline_floor_prevents_inf(self):
        """When baseline is zero, floor prevents division by zero."""
        tracker = self._make_tracker(baseline_floor=0.5)
        state = EntityState(canonical="NEW")
        # Only short-term observation, no baseline history
        state.add_observation(10, 5, 20.0, now=1000.0)
        tracker._entities["NEW"] = state

        spikes = tracker.detect_spikes(now=1000.0)
        # Should not crash, spike_ratio uses floor
        for s in spikes:
            assert s["spike_ratio"] > 0


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    def test_stale_entities_removed(self):
        cfg = SpikeConfig(prune_after_seconds=100.0)
        tracker = XEntityTracker(config=cfg)
        state = EntityState(canonical="OLD")
        state.add_observation(5, 3, 10.0, now=0.0)
        state.last_seen = 0.0
        tracker._entities["OLD"] = state

        pruned = tracker.prune(now=200.0)
        assert pruned == 1
        assert tracker.tracked_count == 0

    def test_recent_entities_kept(self):
        cfg = SpikeConfig(prune_after_seconds=100.0)
        tracker = XEntityTracker(config=cfg)
        state = EntityState(canonical="FRESH")
        state.add_observation(5, 3, 10.0, now=150.0)
        tracker._entities["FRESH"] = state

        pruned = tracker.prune(now=200.0)
        assert pruned == 0
        assert tracker.tracked_count == 1

    def test_old_observations_pruned(self):
        cfg = SpikeConfig(baseline_window_seconds=100.0)
        tracker = XEntityTracker(config=cfg)
        state = EntityState(canonical="MIXED")
        state.add_observation(5, 3, 10.0, now=0.0)
        state.add_observation(3, 2, 5.0, now=150.0)
        state.add_observation(7, 4, 15.0, now=200.0)
        tracker._entities["MIXED"] = state

        tracker.prune(now=200.0)
        # Observation at 0.0 is older than baseline_window=100, should be pruned
        assert len(state.observations) == 2


# ---------------------------------------------------------------------------
# Mark chronic
# ---------------------------------------------------------------------------


class TestMarkChronic:
    def test_mark_chronic(self):
        tracker = XEntityTracker()
        state = EntityState(canonical="SPAM")
        tracker._entities["SPAM"] = state
        tracker.mark_chronic("SPAM")
        assert tracker.get_state("SPAM").is_chronic is True

    def test_mark_chronic_nonexistent_no_error(self):
        tracker = XEntityTracker()
        tracker.mark_chronic("MISSING")  # should not crash


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestTrackerSummary:
    def test_summary_structure(self):
        tracker = XEntityTracker()
        summary = tracker.get_summary(now=100.0)
        assert "tracked_entities" in summary
        assert "active_in_short_window" in summary
        assert "chronic_count" in summary

    def test_summary_counts(self):
        cfg = SpikeConfig(short_term_window_seconds=60.0)
        tracker = XEntityTracker(config=cfg)
        active = EntityState(canonical="ACTIVE")
        active.add_observation(5, 3, 10.0, now=95.0)
        stale = EntityState(canonical="STALE")
        stale.add_observation(5, 3, 10.0, now=0.0)
        chronic = EntityState(canonical="CHRONIC")
        chronic.is_chronic = True

        tracker._entities = {"ACTIVE": active, "STALE": stale, "CHRONIC": chronic}
        summary = tracker.get_summary(now=100.0)
        assert summary["tracked_entities"] == 3
        assert summary["active_in_short_window"] == 1  # only ACTIVE
        assert summary["chronic_count"] == 1
