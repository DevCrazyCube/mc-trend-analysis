"""Tests for data normalization functions."""

import pytest
from datetime import datetime, timezone

from mctrend.normalization.normalizer import (
    _parse_timestamp,
    _safe_float,
    _safe_int,
    merge_narratives,
    normalize_event,
    normalize_token,
)


# ---------------------------------------------------------------------------
# Token Normalization
# ---------------------------------------------------------------------------

class TestNormalizeToken:
    def test_valid_token(self):
        raw = {
            "address": "ABC123",
            "name": "TestToken",
            "symbol": "TEST",
            "deployed_by": "DeployerWallet",
            "launch_time": "2026-01-01T00:00:00Z",
            "launch_platform": "pump.fun",
            "initial_liquidity_usd": 5000.0,
            "initial_holder_count": 10,
            "data_source": "pumpfun",
        }
        result = normalize_token(raw)
        assert result is not None
        assert result["address"] == "ABC123"
        assert result["name"] == "TestToken"
        assert result["symbol"] == "TEST"
        assert result["status"] == "new"
        assert result["deployed_by"] == "DeployerWallet"
        assert "token_id" in result
        assert isinstance(result["data_gaps"], list)

    def test_missing_address_rejected(self):
        raw = {"name": "NoAddress", "deployed_by": "wallet"}
        result = normalize_token(raw)
        assert result is None

    def test_missing_name_rejected(self):
        raw = {"address": "ABC123", "name": "", "deployed_by": "wallet"}
        result = normalize_token(raw)
        assert result is None

    def test_missing_deployer_marked_gap(self):
        raw = {"address": "ABC123", "name": "Test", "deployed_by": ""}
        result = normalize_token(raw)
        assert result is not None
        assert result["deployed_by"] == "unknown"
        assert "deployed_by" in result["data_gaps"]

    def test_missing_optional_fields_marked(self):
        raw = {"address": "ABC123", "name": "Test", "deployed_by": "wallet"}
        result = normalize_token(raw)
        assert "initial_liquidity_usd" in result["data_gaps"]
        assert "initial_holder_count" in result["data_gaps"]

    def test_symbol_defaults_to_name(self):
        raw = {"address": "ABC123", "name": "LongTokenName", "deployed_by": "w"}
        result = normalize_token(raw)
        assert result["symbol"] == "LongTokenN"  # name[:10]

    def test_whitespace_stripped(self):
        raw = {
            "address": "  ABC123  ",
            "name": "  Test  ",
            "deployed_by": "  wallet  ",
        }
        result = normalize_token(raw)
        assert result["address"] == "ABC123"
        assert result["name"] == "Test"

    def test_launch_time_fallback(self):
        """If launch_time is garbage, defaults to now."""
        raw = {"address": "ABC123", "name": "Test", "launch_time": "not-a-date"}
        result = normalize_token(raw)
        assert result is not None
        assert result["launch_time"] is not None


# ---------------------------------------------------------------------------
# Event Normalization
# ---------------------------------------------------------------------------

class TestNormalizeEvent:
    def test_valid_event(self):
        raw = {
            "anchor_terms": ["DEEPMIND", "AI"],
            "related_terms": ["GOOGLE", "GEMINI"],
            "description": "DeepMind breakthrough",
            "source_type": "news",
            "source_name": "newsapi",
            "signal_strength": 0.8,
        }
        result = normalize_event(raw)
        assert result is not None
        assert "DEEPMIND" in result["anchor_terms"]
        assert result["state"] == "WEAK"
        assert result["attention_score"] == 0.8

    def test_no_anchor_terms_rejected(self):
        raw = {"anchor_terms": [], "description": "empty"}
        result = normalize_event(raw)
        assert result is None

    def test_short_terms_filtered(self):
        """Terms shorter than 2 chars should be removed."""
        raw = {"anchor_terms": ["A", "OK", "GOOD"]}
        result = normalize_event(raw)
        assert result is not None
        assert "A" not in result["anchor_terms"]
        assert "OK" in result["anchor_terms"]

    def test_terms_uppercased(self):
        raw = {"anchor_terms": ["deepmind", "ai"]}
        result = normalize_event(raw)
        assert all(t.isupper() for t in result["anchor_terms"])

    def test_missing_signal_strength_defaults(self):
        raw = {"anchor_terms": ["TEST"]}
        result = normalize_event(raw)
        assert result["attention_score"] == 0.5


# ---------------------------------------------------------------------------
# Narrative Merging
# ---------------------------------------------------------------------------

class TestMergeNarratives:
    def test_new_source_added(self):
        existing = {
            "narrative_id": "n1",
            "anchor_terms": ["DEEPMIND"],
            "related_terms": ["AI"],
            "sources": [
                {"source_name": "newsapi", "source_type": "news",
                 "signal_strength": 0.7},
            ],
            "source_type_count": 1,
            "attention_score": 0.7,
        }
        new_source = {
            "source_name": "serpapi",
            "source_type": "search_trends",
            "signal_strength": 0.9,
            "anchor_terms": ["GOOGLE"],
            "related_terms": [],
        }
        result = merge_narratives(existing, new_source)
        assert len(result["sources"]) == 2
        assert result["source_type_count"] == 2
        assert result["attention_score"] > 0.7  # Boosted by diversity

    def test_duplicate_source_not_added(self):
        existing = {
            "narrative_id": "n1",
            "anchor_terms": ["DEEPMIND"],
            "related_terms": [],
            "sources": [
                {"source_name": "newsapi", "source_type": "news",
                 "signal_strength": 0.7},
            ],
            "source_type_count": 1,
            "attention_score": 0.7,
        }
        new_source = {"source_name": "newsapi", "source_type": "news"}
        result = merge_narratives(existing, new_source)
        assert len(result["sources"]) == 1

    def test_related_terms_expanded(self):
        existing = {
            "narrative_id": "n1",
            "anchor_terms": ["DEEPMIND"],
            "related_terms": ["AI"],
            "sources": [],
            "source_type_count": 0,
            "attention_score": 0.5,
        }
        new_source = {
            "source_name": "new",
            "anchor_terms": ["GEMINI"],
            "related_terms": ["NEURAL"],
        }
        result = merge_narratives(existing, new_source)
        assert "GEMINI" in result["related_terms"]
        assert "NEURAL" in result["related_terms"]


# ---------------------------------------------------------------------------
# Timestamp Parsing
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_iso_format(self):
        result = _parse_timestamp("2026-01-01T12:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_iso_with_z(self):
        result = _parse_timestamp("2026-01-01T12:00:00Z")
        assert result is not None

    def test_unix_seconds(self):
        result = _parse_timestamp(1700000000)
        assert result is not None

    def test_unix_milliseconds(self):
        result = _parse_timestamp(1700000000000)
        assert result is not None
        # Should be same as seconds version
        result_s = _parse_timestamp(1700000000)
        assert abs((result - result_s).total_seconds()) < 1

    def test_datetime_passthrough(self):
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = _parse_timestamp(dt)
        assert result == dt

    def test_naive_datetime_gets_utc(self):
        dt = datetime(2026, 1, 1)
        result = _parse_timestamp(dt)
        assert result.tzinfo == timezone.utc

    def test_none_returns_none(self):
        assert _parse_timestamp(None) is None

    def test_garbage_returns_none(self):
        assert _parse_timestamp("not-a-date") is None
        assert _parse_timestamp([1, 2, 3]) is None


# ---------------------------------------------------------------------------
# Safe Type Conversions
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_valid(self):
        assert _safe_float(42.5) == 42.5
        assert _safe_float("3.14") == 3.14
        assert _safe_float(0) == 0.0

    def test_none(self):
        assert _safe_float(None) is None

    def test_garbage(self):
        assert _safe_float("abc") is None
        assert _safe_float([]) is None

    def test_nan_returns_none(self):
        assert _safe_float(float("nan")) is None


class TestSafeInt:
    def test_valid(self):
        assert _safe_int(42) == 42
        assert _safe_int("100") == 100
        assert _safe_int(3.7) == 3

    def test_none(self):
        assert _safe_int(None) is None

    def test_garbage(self):
        assert _safe_int("abc") is None
