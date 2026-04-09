"""Unit tests for the token-stream narrative discovery engine.

Covers:
- _split_token_name_into_terms: camelCase, specials, separators
- _extract_terms_from_token: symbol + name extraction
- TokenStreamNarrativeExtractor: single term, multi-term, noise filtering,
  min_token_occurrences, deduplication
- NarrativeCandidate: token linking, confidence, emergence_score, prune
- NarrativeDiscoveryEngine: process_token_batch, apply_x_corroboration,
  get_emerging_candidates, prune, get_summary
- candidate_to_narrative_event: structure and signal strength
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mctrend.narrative.discovery_engine import (
    NarrativeCandidate,
    NarrativeDiscoveryEngine,
    TokenStreamNarrativeExtractor,
    _candidate_id,
    _extract_terms_from_token,
    _split_token_name_into_terms,
    candidate_to_narrative_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _ago(hours: float = 0.0, minutes: float = 0.0) -> float:
    return _now_ts() - hours * 3600 - minutes * 60


def _token(
    name: str = "TRUMP",
    symbol: str = "TRUMP",
    token_id: str | None = None,
    hours_ago: float = 0.5,
) -> dict:
    tid = token_id or f"tok-{name.lower()}"
    launch = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).isoformat()
    return {"token_id": tid, "name": name, "symbol": symbol, "launch_time": launch}


# ---------------------------------------------------------------------------
# _split_token_name_into_terms
# ---------------------------------------------------------------------------

class TestSplitTokenName:
    def test_space_separated(self):
        assert _split_token_name_into_terms("TRUMP COIN") == ["TRUMP", "COIN"]

    def test_camel_case(self):
        result = _split_token_name_into_terms("TrumpCoin")
        assert "TRUMP" in result
        assert "COIN" in result

    def test_leading_dollar(self):
        result = _split_token_name_into_terms("$TRUMP")
        assert "TRUMP" in result

    def test_hyphen_separator(self):
        result = _split_token_name_into_terms("TRUMP-COIN")
        assert "TRUMP" in result
        assert "COIN" in result

    def test_single_word_all_caps(self):
        result = _split_token_name_into_terms("DOGWIF")
        assert result == ["DOGWIF"]

    def test_empty_string(self):
        assert _split_token_name_into_terms("") == []

    def test_deduplicates_within_name(self):
        # "MOON MOON" should produce ["MOON"] not ["MOON", "MOON"]
        result = _split_token_name_into_terms("MOON MOON")
        assert result.count("MOON") == 1

    def test_underscore_separator(self):
        result = _split_token_name_into_terms("TRUMP_COIN")
        assert "TRUMP" in result
        assert "COIN" in result

    def test_acronym_camel(self):
        # "NFTCoin" → ["NFT", "COIN"]
        result = _split_token_name_into_terms("NFTCoin")
        assert "NFT" in result or "NFTCOIN" in result


# ---------------------------------------------------------------------------
# _extract_terms_from_token
# ---------------------------------------------------------------------------

class TestExtractTermsFromToken:
    def test_symbol_extracted(self):
        token = {"token_id": "t1", "name": "Some Token", "symbol": "TRUMP"}
        pairs = _extract_terms_from_token(token)
        canonicals = [c for c, _ in pairs]
        assert "TRUMP" in canonicals

    def test_name_words_extracted(self):
        token = {"token_id": "t1", "name": "PEPE COIN", "symbol": "PP"}
        pairs = _extract_terms_from_token(token)
        canonicals = [c for c, _ in pairs]
        assert "PEPE" in canonicals

    def test_no_duplicate_canonicals(self):
        token = {"token_id": "t1", "name": "TRUMP", "symbol": "TRUMP"}
        pairs = _extract_terms_from_token(token)
        canonicals = [c for c, _ in pairs]
        assert len(canonicals) == len(set(canonicals))

    def test_empty_token(self):
        token = {"token_id": "t1", "name": "", "symbol": ""}
        pairs = _extract_terms_from_token(token)
        assert pairs == []

    def test_min_length_filtering(self):
        # Single-character symbols should not appear
        token = {"token_id": "t1", "name": "A COIN", "symbol": "A"}
        pairs = _extract_terms_from_token(token)
        canonicals = [c for c, _ in pairs]
        assert "A" not in canonicals


# ---------------------------------------------------------------------------
# _candidate_id
# ---------------------------------------------------------------------------

class TestCandidateId:
    def test_deterministic(self):
        assert _candidate_id("TRUMP") == _candidate_id("TRUMP")

    def test_different_names_produce_different_ids(self):
        assert _candidate_id("TRUMP") != _candidate_id("DOGE")

    def test_prefix(self):
        assert _candidate_id("TRUMP").startswith("nc-")

    def test_length_fixed(self):
        # "nc-" + 12 chars = 15
        assert len(_candidate_id("TRUMP")) == 15


# ---------------------------------------------------------------------------
# TokenStreamNarrativeExtractor
# ---------------------------------------------------------------------------

class TestTokenStreamExtractor:
    def setup_method(self):
        self.extractor = TokenStreamNarrativeExtractor()

    def test_single_term_two_tokens(self):
        # "TRUMP MANIA" splits into ["TRUMP", "MANIA"] so TRUMP appears in both t1 and t2
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        result = self.extractor.extract_from_tokens(tokens)
        assert "TRUMP" in result

    def test_single_token_not_returned(self):
        tokens = [_token("TRUMP", "TRUMP", "t1")]
        result = self.extractor.extract_from_tokens(tokens)
        assert "TRUMP" not in result

    def test_noise_term_filtered(self):
        # "COIN" is in TOKEN_NOISE_TERMS
        tokens = [
            _token("SOME COIN", "SC1", "t1"),
            _token("OTHER COIN", "SC2", "t2"),
        ]
        result = self.extractor.extract_from_tokens(tokens)
        assert "COIN" not in result

    def test_token_ids_in_result(self):
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        result = self.extractor.extract_from_tokens(tokens)
        assert "TRUMP" in result
        _, token_ids = result["TRUMP"]
        assert "t1" in token_ids
        assert "t2" in token_ids

    def test_same_token_not_double_counted(self):
        """A single token appearing twice in the list must only be counted once."""
        token = _token("TRUMP", "TRUMP", "t1")
        result = self.extractor.extract_from_tokens([token, token])
        # "TRUMP" appears from only one distinct token_id
        assert "TRUMP" not in result

    def test_configurable_min_occurrences(self):
        extractor = TokenStreamNarrativeExtractor(min_token_occurrences=3)
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP2", "TR2", "t2"),
        ]
        result = extractor.extract_from_tokens(tokens)
        assert "TRUMP" not in result  # only 2 tokens, need 3

    def test_empty_token_list(self):
        assert self.extractor.extract_from_tokens([]) == {}

    def test_min_term_length_respected(self):
        extractor = TokenStreamNarrativeExtractor(min_term_length=4)
        tokens = [
            _token("AI", "AI", "t1"),
            _token("AI STUFF", "AIS", "t2"),
        ]
        result = extractor.extract_from_tokens(tokens)
        assert "AI" not in result  # length 2 < 4


# ---------------------------------------------------------------------------
# NarrativeCandidate
# ---------------------------------------------------------------------------

class TestNarrativeCandidate:
    def _make(self) -> NarrativeCandidate:
        return NarrativeCandidate(
            candidate_id="nc-test",
            canonical_name="TRUMP",
            first_seen=_now_ts(),
            last_seen=_now_ts(),
        )

    def test_add_token_increases_count(self):
        c = self._make()
        c.add_token("t1", "Trump Token")
        assert c.token_count == 1

    def test_add_token_deduplicates(self):
        c = self._make()
        c.add_token("t1", "Trump Token")
        result = c.add_token("t1", "Trump Token")
        assert result is False
        assert c.token_count == 1

    def test_add_token_returns_true_for_new(self):
        c = self._make()
        assert c.add_token("t1", "Trump Token") is True

    def test_confidence_zero_for_single_token(self):
        c = self._make()
        c.add_token("t1", "Trump Token")
        assert c.confidence() == 0.0

    def test_confidence_above_zero_for_two_tokens(self):
        c = self._make()
        c.add_token("t1", "Trump Token")
        c.add_token("t2", "Trump II")
        assert c.confidence() > 0.0

    def test_confidence_increases_with_more_tokens(self):
        c1 = self._make()
        c2 = self._make()
        for i in range(2):
            c1.add_token(f"t{i}", f"token {i}")
        for i in range(10):
            c2.add_token(f"t{i}", f"token {i}")
        assert c2.confidence() > c1.confidence()

    def test_confidence_bounded_0_1(self):
        c = self._make()
        for i in range(100):
            c.add_token(f"t{i}", f"name{i}")
            c.x_spike_corroboration = 1.0
            c.news_corroboration = 1.0
        assert 0.0 <= c.confidence() <= 1.0

    def test_x_corroboration_boosts_confidence(self):
        c1 = self._make()
        c2 = self._make()
        for cand in (c1, c2):
            cand.add_token("t1", "T1")
            cand.add_token("t2", "T2")
        c2.add_x_corroboration(spike_ratio=10.0, match_confidence=0.9)
        assert c2.confidence() > c1.confidence()

    def test_x_corroboration_non_destructive(self):
        c = self._make()
        c.add_x_corroboration(5.0, 0.9)
        first = c.x_spike_corroboration
        c.add_x_corroboration(3.0, 0.5)  # lower boost
        assert c.x_spike_corroboration == first  # max preserved

    def test_x_corroboration_updates_if_higher(self):
        c = self._make()
        c.add_x_corroboration(5.0, 0.5)
        low = c.x_spike_corroboration
        c.add_x_corroboration(20.0, 1.0)  # higher boost
        assert c.x_spike_corroboration > low

    def test_recency_decay_reduces_confidence(self):
        now = _now_ts()
        c_fresh = NarrativeCandidate(
            candidate_id="nc-1",
            canonical_name="TRUMP",
            first_seen=now - 100,
            last_seen=now - 100,
        )
        c_stale = NarrativeCandidate(
            candidate_id="nc-2",
            canonical_name="TRUMP",
            first_seen=now - 7200,
            last_seen=now - 7200,  # exactly 2h ago → recency_factor = 0
        )
        # Use explicit obs_time so last_seen is NOT updated to now by add_token
        c_fresh.add_token("t1", "T1", obs_time=now - 100)
        c_fresh.add_token("t2", "T2", obs_time=now - 90)
        c_stale.add_token("t1", "T1", obs_time=now - 7200)
        c_stale.add_token("t2", "T2", obs_time=now - 7100)
        assert c_fresh.confidence(now) > c_stale.confidence(now)

    def test_emergence_score_zero_on_no_recent_tokens(self):
        now = _now_ts()
        c = NarrativeCandidate(
            candidate_id="nc-test",
            canonical_name="TRUMP",
            first_seen=now - 7200,
            last_seen=now - 7200,
        )
        # All observations outside the short window (30min)
        c.add_token("t1", "T1", obs_time=now - 7200)
        assert c.token_count_in_window(1800.0, now) == 0
        assert c.emergence_score(short_window=1800.0, now=now) == 0.0

    def test_emergence_score_bounded(self):
        c = self._make()
        for i in range(20):
            c.add_token(f"t{i}", f"n{i}", obs_time=_now_ts() - 60)
        score = c.emergence_score()
        assert 0.0 <= score <= 1.0

    def test_token_count_in_window_respects_cutoff(self):
        now = _now_ts()
        c = NarrativeCandidate(
            candidate_id="nc-1",
            canonical_name="TRUMP",
            first_seen=now,
            last_seen=now,
        )
        # 2 tokens 10 hours ago (outside 30min window)
        c.add_token("t1", "T1", obs_time=now - 36000)
        c.add_token("t2", "T2", obs_time=now - 36000)
        # 1 token 5 minutes ago (inside 30min window)
        c.add_token("t3", "T3", obs_time=now - 300)

        assert c.token_count_in_window(1800.0, now) == 1

    def test_prune_observations_removes_old(self):
        now = _now_ts()
        c = NarrativeCandidate(
            candidate_id="nc-1",
            canonical_name="TRUMP",
            first_seen=now - 90000,
            last_seen=now,
        )
        c.add_token("t1", "T1", obs_time=now - 90000)  # old
        c.add_token("t2", "T2", obs_time=now - 100)    # recent
        c.prune_observations(max_age_seconds=86400.0, now=now)
        # old observation pruned
        assert c.token_count_in_window(86400.0, now) == 1

    def test_to_dict_structure(self):
        c = self._make()
        c.add_token("t1", "T1")
        c.add_token("t2", "T2")
        d = c.to_dict()
        assert d["canonical_name"] == "TRUMP"
        assert "confidence" in d
        assert "emergence_score" in d
        assert "token_count" in d
        assert d["token_count"] == 2


# ---------------------------------------------------------------------------
# NarrativeDiscoveryEngine
# ---------------------------------------------------------------------------

class TestNarrativeDiscoveryEngine:
    def setup_method(self):
        self.engine = NarrativeDiscoveryEngine(min_confidence=0.0)

    def test_process_batch_creates_candidate(self):
        # TRUMP in t1 (symbol) and t2 (name "TRUMP MANIA" → splits to ["TRUMP", "MANIA"])
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        new_links = self.engine.process_token_batch(tokens)
        assert new_links >= 2  # at least t1 and t2 linked to TRUMP
        assert "TRUMP" in self.engine._candidates

    def test_process_batch_empty_no_error(self):
        assert self.engine.process_token_batch([]) == 0

    def test_process_batch_deduplicates_token_links(self):
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        self.engine.process_token_batch(tokens)
        first_count = self.engine._candidates["TRUMP"].token_count
        # Process same batch again — all token IDs already linked
        self.engine.process_token_batch(tokens)
        assert self.engine._candidates["TRUMP"].token_count == first_count

    def test_single_token_not_candidate(self):
        # Only one distinct token has "TRUMP" — below min_token_occurrences=2
        tokens = [_token("TRUMP", "TRUMP", "t1"), _token("OTHER", "OTH", "t2")]
        self.engine.process_token_batch(tokens)
        assert "TRUMP" not in self.engine._candidates

    def test_noise_term_not_candidate(self):
        tokens = [
            _token("BITCOIN ALPHA", "BTA", "t1"),
            _token("BITCOIN BETA", "BTB", "t2"),
        ]
        self.engine.process_token_batch(tokens)
        assert "BITCOIN" not in self.engine._candidates

    def test_x_corroboration_boosts_existing_candidate(self):
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        self.engine.process_token_batch(tokens)
        assert "TRUMP" in self.engine._candidates
        before = self.engine._candidates["TRUMP"].x_spike_corroboration
        spikes = [{"entity": "TRUMP", "spike_ratio": 10.0, "spike_class": "emerging"}]
        boosted = self.engine.apply_x_corroboration(spikes)
        assert boosted > 0
        assert self.engine._candidates["TRUMP"].x_spike_corroboration > before

    def test_x_corroboration_ignores_unmatched_spike(self):
        tokens = [
            _token("PEPE", "PEPE", "t1"),
            _token("PEPE2", "PP2", "t2"),
        ]
        self.engine.process_token_batch(tokens)
        spikes = [{"entity": "DOGECOIN", "spike_ratio": 10.0}]
        boosted = self.engine.apply_x_corroboration(spikes)
        assert boosted == 0

    def test_get_emerging_candidates_returns_qualifying(self):
        engine = NarrativeDiscoveryEngine(min_confidence=0.0)
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        engine.process_token_batch(tokens)
        result = engine.get_emerging_candidates(min_token_count=2)
        assert any(c.canonical_name == "TRUMP" for c in result)

    def test_get_emerging_candidates_sorted_by_confidence(self):
        engine = NarrativeDiscoveryEngine(min_confidence=0.0)
        # Build two candidates with different token counts
        tokens_trump = [_token(f"TRUMP{i}", "TRUMP", f"tt{i}") for i in range(5)]
        tokens_pepe = [
            _token("PEPE", "PEPE", "tp1"),
            _token("PEPE2", "PP", "tp2"),
        ]
        engine.process_token_batch(tokens_trump + tokens_pepe)
        result = engine.get_emerging_candidates()
        if len(result) >= 2:
            assert result[0].confidence() >= result[1].confidence()

    def test_prune_removes_stale_candidates(self):
        old_time = _now_ts() - 90000  # 25h ago — beyond default 24h window
        engine = NarrativeDiscoveryEngine(decay_window_seconds=86400.0)

        # Manually insert a stale candidate
        cand = NarrativeCandidate(
            candidate_id="nc-stale",
            canonical_name="STALE",
            first_seen=old_time,
            last_seen=old_time,
        )
        engine._candidates["STALE"] = cand

        removed = engine.prune()
        assert removed == 1
        assert "STALE" not in engine._candidates

    def test_prune_keeps_recent_candidates(self):
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP MANIA", "TRM", "t2"),
        ]
        self.engine.process_token_batch(tokens)
        assert "TRUMP" in self.engine._candidates
        removed = self.engine.prune()
        assert removed == 0
        assert "TRUMP" in self.engine._candidates

    def test_get_summary_structure(self):
        tokens = [
            _token("TRUMP", "TRUMP", "t1"),
            _token("TRUMP2", "TRM", "t2"),
        ]
        self.engine.process_token_batch(tokens)
        summary = self.engine.get_summary()
        assert "token_stream_candidates_total" in summary
        assert "token_stream_candidates_emerging" in summary
        assert "token_stream_top_candidates" in summary

    def test_accumulates_across_multiple_batches(self):
        # Batch 1 has t1 with TRUMP (only 1 token — not yet a candidate)
        batch1 = [_token("TRUMP", "TRUMP", "t1")]
        self.engine.process_token_batch(batch1)
        assert "TRUMP" not in self.engine._candidates  # only 1 token so far

        # Batch 2 combines previous + new token; now TRUMP has t1+t2 — becomes candidate
        batch2 = [_token("TRUMP", "TRUMP", "t1"), _token("TRUMP MANIA", "TRM", "t2")]
        self.engine.process_token_batch(batch2)
        assert "TRUMP" in self.engine._candidates

    def test_x_corroboration_empty_spikes_no_error(self):
        self.engine.apply_x_corroboration([])
        # No error, no candidates created


# ---------------------------------------------------------------------------
# candidate_to_narrative_event
# ---------------------------------------------------------------------------

class TestCandidateToNarrativeEvent:
    def _make_candidate(self, token_count: int = 3) -> NarrativeCandidate:
        now = _now_ts()
        c = NarrativeCandidate(
            candidate_id=_candidate_id("TRUMP"),
            canonical_name="TRUMP",
            first_seen=now - 1800,
            last_seen=now,
        )
        for i in range(token_count):
            c.add_token(f"t{i}", f"Trump{i}", obs_time=now - i * 60)
        c.add_alias("$TRUMP")
        return c

    def test_source_type_is_token_stream(self):
        event = candidate_to_narrative_event(self._make_candidate())
        assert event["source_type"] == "token_stream"

    def test_source_name_is_token_stream_discovery(self):
        event = candidate_to_narrative_event(self._make_candidate())
        assert event["source_name"] == "token_stream_discovery"

    def test_anchor_terms_contains_canonical(self):
        event = candidate_to_narrative_event(self._make_candidate())
        assert "TRUMP" in event["anchor_terms"]

    def test_signal_strength_bounded(self):
        event = candidate_to_narrative_event(self._make_candidate())
        assert 0.0 <= event["signal_strength"] <= 1.0

    def test_signal_strength_increases_with_token_count(self):
        low = candidate_to_narrative_event(self._make_candidate(token_count=2))
        high = candidate_to_narrative_event(self._make_candidate(token_count=10))
        assert high["signal_strength"] > low["signal_strength"]

    def test_entities_is_list(self):
        """entities must be a list for clustering compatibility."""
        event = candidate_to_narrative_event(self._make_candidate())
        assert isinstance(event["entities"], list)

    def test_published_at_parseable(self):
        event = candidate_to_narrative_event(self._make_candidate())
        dt = datetime.fromisoformat(event["published_at"])
        assert dt is not None

    def test_has_candidate_metadata(self):
        event = candidate_to_narrative_event(self._make_candidate())
        meta = event["_candidate_metadata"]
        assert meta["canonical_name"] == "TRUMP"
        assert meta["token_count"] >= 2
        assert "candidate_id" in meta

    def test_x_corroboration_in_description(self):
        c = self._make_candidate()
        c.add_x_corroboration(10.0, 0.9)
        event = candidate_to_narrative_event(c)
        assert "X spike" in event["description"]

    def test_no_x_corroboration_in_description(self):
        c = self._make_candidate()
        event = candidate_to_narrative_event(c)
        assert "X spike" not in event["description"]

    def test_anchor_terms_no_duplicates(self):
        event = candidate_to_narrative_event(self._make_candidate())
        assert len(event["anchor_terms"]) == len(set(event["anchor_terms"]))

    def test_related_terms_excludes_anchor_terms(self):
        event = candidate_to_narrative_event(self._make_candidate())
        anchor_set = set(event["anchor_terms"])
        for rt in event["related_terms"]:
            assert rt not in anchor_set
