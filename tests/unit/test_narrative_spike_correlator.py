"""Unit tests for spike-to-token correlation and narrative event generation.

Covers:
- Name exact match
- Symbol exact match
- Cashtag exact match
- Partial name/symbol match
- Timing window filtering
- Spike-to-narrative event conversion
- No match returns empty
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mctrend.narrative.spike_correlator import (
    correlate_spike_with_tokens,
    spike_to_narrative_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spike(entity="TRUMP", entity_type="person", spike_ratio=10.0, spike_class="emerging"):
    return {
        "entity": entity,
        "entity_type": entity_type,
        "spike_ratio": spike_ratio,
        "spike_class": spike_class,
        "short_term_count": 15,
        "short_term_authors": 8,
        "short_term_rate": 0.5,
        "baseline_rate": 0.05,
        "total_count": 30,
        "first_seen_ago_seconds": 300.0,
    }


def _make_token(name="TRUMP", symbol="TRUMP", token_id="tok-1", hours_ago=1.0):
    launch = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "token_id": token_id,
        "name": name,
        "symbol": symbol,
        "address": "addr-" + token_id,
        "launch_time": launch,
    }


# ---------------------------------------------------------------------------
# correlate_spike_with_tokens
# ---------------------------------------------------------------------------


class TestCorrelateSpike:
    def test_name_exact_match(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [_make_token(name="TRUMP", symbol="TRMP")]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "name_exact"
        assert matches[0]["match_confidence"] == 0.95
        assert "name_match" in matches[0]["overlap_signals"]

    def test_symbol_exact_match(self):
        spike = _make_spike(entity="DOGE")
        tokens = [_make_token(name="DogeCoin", symbol="DOGE")]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "symbol_exact"
        assert matches[0]["match_confidence"] == 0.90

    def test_cashtag_exact_match(self):
        spike = _make_spike(entity="PEPE", entity_type="cashtag")
        tokens = [_make_token(name="PepeToken", symbol="PEPE")]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert len(matches) == 1
        # Could be symbol_exact or cashtag_exact depending on order
        assert matches[0]["match_confidence"] >= 0.90

    def test_name_contains_match(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [_make_token(name="TRUMPCOIN", symbol="TRPC")]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "name_contains"
        assert matches[0]["match_confidence"] == 0.70

    def test_no_match_returns_empty(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [_make_token(name="DOGECOIN", symbol="DOGE")]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert matches == []

    def test_timing_window_filters_old_tokens(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [_make_token(name="TRUMP", symbol="TRUMP", hours_ago=24.0)]
        matches = correlate_spike_with_tokens(spike, tokens, timing_window_hours=8.0)
        assert matches == []

    def test_timing_window_keeps_recent_tokens(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [_make_token(name="TRUMP", symbol="TRUMP", hours_ago=2.0)]
        matches = correlate_spike_with_tokens(spike, tokens, timing_window_hours=8.0)
        assert len(matches) == 1

    def test_timing_proximity_in_signals(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [_make_token(name="TRUMP", symbol="TRUMP", hours_ago=1.0)]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert "timing_proximity" in matches[0]["overlap_signals"]

    def test_multiple_token_matches(self):
        spike = _make_spike(entity="TRUMP")
        tokens = [
            _make_token(name="TRUMP", symbol="TRUMP", token_id="t1"),
            _make_token(name="TRUMPCOIN", symbol="TRPC", token_id="t2"),
        ]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert len(matches) == 2

    def test_empty_entity_returns_empty(self):
        spike = _make_spike(entity="")
        tokens = [_make_token()]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert matches == []

    def test_match_includes_spike_metadata(self):
        spike = _make_spike(entity="TRUMP", spike_ratio=12.5)
        tokens = [_make_token(name="TRUMP")]
        matches = correlate_spike_with_tokens(spike, tokens)
        assert matches[0]["spike_entity"] == "TRUMP"
        assert matches[0]["spike_ratio"] == 12.5
        assert matches[0]["spike_class"] == "emerging"


# ---------------------------------------------------------------------------
# spike_to_narrative_event
# ---------------------------------------------------------------------------


class TestSpikeToNarrativeEvent:
    def test_basic_structure(self):
        spike = _make_spike(entity="TRUMP", spike_ratio=10.0)
        event = spike_to_narrative_event(spike)
        assert event["anchor_terms"] == ["TRUMP"]
        assert event["source_type"] == "social_media"
        assert event["source_name"] == "x_spike_detection"
        assert "X spike" in event["description"]

    def test_signal_strength_bounded(self):
        spike = _make_spike(spike_ratio=100.0)
        event = spike_to_narrative_event(spike)
        assert event["signal_strength"] <= 1.0

    def test_signal_strength_increases_with_spike_ratio(self):
        low = spike_to_narrative_event(_make_spike(spike_ratio=3.0))
        high = spike_to_narrative_event(_make_spike(spike_ratio=15.0))
        assert high["signal_strength"] > low["signal_strength"]

    def test_match_boosts_signal(self):
        spike = _make_spike(spike_ratio=5.0)
        no_match = spike_to_narrative_event(spike)
        with_match = spike_to_narrative_event(spike, match={
            "match_confidence": 0.95,
        })
        assert with_match["signal_strength"] > no_match["signal_strength"]

    def test_entities_is_list(self):
        """entities must be a list for narrative compatibility (not X dict format)."""
        spike = _make_spike()
        event = spike_to_narrative_event(spike)
        assert isinstance(event["entities"], list)

    def test_spike_metadata_included(self):
        spike = _make_spike(entity="ELON", spike_ratio=20.0)
        event = spike_to_narrative_event(spike)
        meta = event["_spike_metadata"]
        assert meta["entity"] == "ELON"
        assert meta["spike_ratio"] == 20.0

    def test_has_published_at(self):
        event = spike_to_narrative_event(_make_spike())
        assert "published_at" in event
        # Should be parseable
        datetime.fromisoformat(event["published_at"])
