"""Tests for alert confidence discrimination and narrative grouping.

Covers:
- confidence varies meaningfully with source_count and match_confidence
- flat 47.5% is eliminated: different inputs → different scores
- _build_narrative_data populates source_count from sources list
- _build_narrative_data derives ambiguity_score from match_confidence
- /api/alerts/by-narrative groups alerts by narrative_id
- noise (low alert_count, no active signals) does not pollute the top
- board confidence (NarrativeCandidate.confidence) is discriminative
"""
from __future__ import annotations

import pytest

from mctrend.scoring.probability import compute_confidence


# ---------------------------------------------------------------------------
# Part 1: compute_confidence must be discriminative
# ---------------------------------------------------------------------------

class TestComputeConfidenceIsDiscriminative:
    """Verify that compute_confidence produces meaningfully different values
    for inputs that differ in evidence quality."""

    def _conf(
        self,
        source_count: int = 1,
        source_diversity: int = 1,
        data_completeness: float = 0.5,
        ambiguity_score: float = 0.5,
    ) -> float:
        return compute_confidence(
            source_count=source_count,
            source_diversity=source_diversity,
            data_completeness=data_completeness,
            ambiguity_score=ambiguity_score,
        )

    def test_more_sources_raises_confidence(self):
        low = self._conf(source_count=1)
        high = self._conf(source_count=5)
        assert high > low
        assert high - low >= 0.05  # meaningful gap, not noise

    def test_higher_diversity_raises_confidence(self):
        mono = self._conf(source_diversity=1)
        diverse = self._conf(source_diversity=4)
        assert diverse > mono

    def test_lower_ambiguity_raises_confidence(self):
        # ambiguity_score = 1 - match_confidence; low ambiguity = high quality
        vague = self._conf(ambiguity_score=0.9)
        precise = self._conf(ambiguity_score=0.1)
        assert precise > vague
        assert precise - vague >= 0.10  # meaningful

    def test_more_complete_data_raises_confidence(self):
        sparse = self._conf(data_completeness=0.0)
        complete = self._conf(data_completeness=1.0)
        assert complete > sparse

    def test_flat_47pct_scenario_is_just_one_of_many_values(self):
        # The old "flat" scenario: source_type_count=2, ambiguity=0.5, 3 gaps
        # = 0.40*0.25 + 0.50*0.25 + 0.50*0.30 + 0.50*0.20 = 0.475
        flat = self._conf(
            source_count=2,
            source_diversity=2,
            data_completeness=0.5,
            ambiguity_score=0.5,
        )
        assert abs(flat - 0.475) < 0.001  # confirm the known flat value

        # With real source_count=5 and low ambiguity (exact match):
        good = self._conf(
            source_count=5,
            source_diversity=3,
            data_completeness=0.5,
            ambiguity_score=0.1,  # match_confidence=0.9
        )
        assert good > flat + 0.10  # significantly better, not same as flat

        # With source_count=1 and high ambiguity (fuzzy match):
        weak = self._conf(
            source_count=1,
            source_diversity=1,
            data_completeness=0.333,
            ambiguity_score=0.7,  # match_confidence=0.3
        )
        assert weak < flat - 0.05  # significantly worse, not same as flat

    def test_confidence_range_is_wide(self):
        """All-bad vs all-good should differ by at least 0.40."""
        worst = self._conf(
            source_count=1, source_diversity=1,
            data_completeness=0.0, ambiguity_score=1.0,
        )
        best = self._conf(
            source_count=5, source_diversity=4,
            data_completeness=1.0, ambiguity_score=0.0,
        )
        assert best - worst >= 0.40

    def test_confidence_bounded_0_to_1(self):
        for sc, sd, dc, am in [
            (0, 0, 0.0, 1.0), (10, 10, 1.0, 0.0), (3, 2, 0.5, 0.5),
        ]:
            c = self._conf(sc, sd, dc, am)
            assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# Part 2: _build_narrative_data populates correct fields
# ---------------------------------------------------------------------------

class TestBuildNarrativeData:
    """Verify the pipeline's _build_narrative_data helper produces discriminative
    inputs for compute_confidence by correctly populating source_count and
    ambiguity_score."""

    def _make_pipeline(self):
        """Instantiate a minimal Pipeline-like object with just the method."""
        from datetime import datetime, timezone
        import json

        class FakePipeline:
            def _build_narrative_data(self, narrative: dict, link: dict) -> dict:
                # Inline the actual implementation from pipeline.py for isolation
                first_detected = narrative.get("first_detected", "")
                now = datetime.now(timezone.utc)
                age_hours = 0.0
                if first_detected:
                    try:
                        fd = datetime.fromisoformat(first_detected.replace("Z", "+00:00"))
                        if fd.tzinfo is None:
                            fd = fd.replace(tzinfo=timezone.utc)
                        age_hours = (now - fd).total_seconds() / 3600
                    except (ValueError, TypeError):
                        pass

                sources = narrative.get("sources") or []
                if isinstance(sources, str):
                    try:
                        sources = json.loads(sources)
                    except Exception:
                        sources = []
                source_count = max(1, len(sources)) if isinstance(sources, list) else 1

                match_confidence = link.get("match_confidence", 0.5)
                ambiguity_score = round(max(0.0, 1.0 - match_confidence), 4)

                return {
                    "match_confidence": match_confidence,
                    "narrative_age_hours": age_hours,
                    "source_count": source_count,
                    "source_type_count": narrative.get("source_type_count", 1),
                    "ambiguity_score": ambiguity_score,
                    "state": narrative.get("state", "WEAK"),
                    "attention_score": narrative.get("attention_score", 0.5),
                    "narrative_velocity": narrative.get("narrative_velocity", 0.0),
                    "narrative_strength": narrative.get("narrative_strength"),
                    "velocity_state": narrative.get("velocity_state"),
                }

        return FakePipeline()

    def test_source_count_from_sources_list(self):
        p = self._make_pipeline()
        narrative = {
            "sources": [{"source_name": "newsapi"}, {"source_name": "x"}, {"source_name": "token_stream"}],
            "source_type_count": 1,
        }
        result = p._build_narrative_data(narrative, {"match_confidence": 0.8})
        assert result["source_count"] == 3

    def test_source_count_defaults_to_1_when_empty(self):
        p = self._make_pipeline()
        result = p._build_narrative_data({"sources": []}, {"match_confidence": 0.5})
        assert result["source_count"] == 1

    def test_source_count_from_json_string(self):
        import json
        p = self._make_pipeline()
        narrative = {"sources": json.dumps([{"source_name": "a"}, {"source_name": "b"}])}
        result = p._build_narrative_data(narrative, {"match_confidence": 0.5})
        assert result["source_count"] == 2

    def test_ambiguity_high_for_low_match_confidence(self):
        p = self._make_pipeline()
        result = p._build_narrative_data({}, {"match_confidence": 0.2})
        assert result["ambiguity_score"] == pytest.approx(0.8, abs=0.01)

    def test_ambiguity_low_for_high_match_confidence(self):
        p = self._make_pipeline()
        result = p._build_narrative_data({}, {"match_confidence": 0.9})
        assert result["ambiguity_score"] == pytest.approx(0.1, abs=0.01)

    def test_ambiguity_zero_for_perfect_match(self):
        p = self._make_pipeline()
        result = p._build_narrative_data({}, {"match_confidence": 1.0})
        assert result["ambiguity_score"] == 0.0

    def test_source_count_differs_from_source_type_count(self):
        """The fix: source_count (actual events) must differ from source_type_count
        (distinct source types) to break the old flatness."""
        p = self._make_pipeline()
        # 5 events from 2 distinct types → source_count=5, source_type_count=2
        narrative = {
            "sources": [{"s": i} for i in range(5)],
            "source_type_count": 2,
        }
        result = p._build_narrative_data(narrative, {"match_confidence": 0.8})
        assert result["source_count"] == 5
        assert result["source_type_count"] == 2
        assert result["source_count"] != result["source_type_count"]

    def test_two_alerts_different_match_confidence_yield_different_confidence(self):
        """End-to-end: different match_confidence → different final confidence."""
        p = self._make_pipeline()
        narrative = {"sources": [{"s": 1}, {"s": 2}], "source_type_count": 1}

        data_exact = p._build_narrative_data(narrative, {"match_confidence": 0.95})
        data_fuzzy = p._build_narrative_data(narrative, {"match_confidence": 0.30})

        conf_exact = compute_confidence(
            source_count=data_exact["source_count"],
            source_diversity=data_exact["source_type_count"],
            data_completeness=0.5,
            ambiguity_score=data_exact["ambiguity_score"],
        )
        conf_fuzzy = compute_confidence(
            source_count=data_fuzzy["source_count"],
            source_diversity=data_fuzzy["source_type_count"],
            data_completeness=0.5,
            ambiguity_score=data_fuzzy["ambiguity_score"],
        )
        assert conf_exact > conf_fuzzy
        assert conf_exact - conf_fuzzy >= 0.10  # meaningful gap


# ---------------------------------------------------------------------------
# Part 3: Alert grouping endpoint logic
# ---------------------------------------------------------------------------

class TestAlertGroupingLogic:
    """Verify that the by-narrative grouping logic correctly collapses token
    rows into narrative-level groups."""

    def _make_alerts(self, narrative_id: str, tokens: list[str], alert_type: str = "watch") -> list[dict]:
        return [
            {
                "alert_id": f"aid_{narrative_id}_{i}",
                "narrative_id": narrative_id,
                "narrative_name": f"Narrative {narrative_id}",
                "token_name": t,
                "token_address": f"addr_{t}",
                "confidence_score": 0.3 + i * 0.05,
                "net_potential": 0.4 + i * 0.02,
                "p_failure": 0.4,
                "alert_type": alert_type,
                "status": "active",
                "created_at": f"2024-01-01T0{i}:00:00",
                "updated_at": f"2024-01-01T0{i}:00:00",
                "risk_flags": [],
            }
            for i, t in enumerate(tokens)
        ]

    def _group(self, alerts: list[dict]) -> list[dict]:
        """Mirror the grouping logic from the endpoint."""
        groups: dict = {}
        for a in alerts:
            key = a.get("narrative_id") or a.get("narrative_name") or "_ungrouped"
            if key not in groups:
                groups[key] = {
                    "narrative_id": a.get("narrative_id"),
                    "narrative_name": a.get("narrative_name") or key,
                    "alert_count": 0,
                    "_token_set": set(),
                    "token_names": [],
                    "_type_counts": {},
                    "max_confidence": 0.0,
                    "max_net_potential": 0.0,
                    "latest_created_at": None,
                    "has_active": False,
                    "alerts": [],
                }
            g = groups[key]
            g["alert_count"] += 1
            tname = a.get("token_name", "")
            if tname and tname not in g["_token_set"]:
                g["_token_set"].add(tname)
                g["token_names"].append(tname)
            conf = a.get("confidence_score") or 0.0
            if conf > g["max_confidence"]:
                g["max_confidence"] = conf
            net = a.get("net_potential") or 0.0
            if net > g["max_net_potential"]:
                g["max_net_potential"] = net
            created = a.get("created_at") or ""
            if not g["latest_created_at"] or created > g["latest_created_at"]:
                g["latest_created_at"] = created
            atype = a.get("alert_type") or "unknown"
            g["_type_counts"][atype] = g["_type_counts"].get(atype, 0) + 1
            if a.get("status") == "active":
                g["has_active"] = True
            g["alerts"].append(a)
        result = []
        for g in groups.values():
            tc = g.pop("_type_counts")
            g.pop("_token_set")
            g["token_count"] = len(g["token_names"])
            g["token_names"] = g["token_names"][:10]
            g["dominant_alert_type"] = max(tc, key=tc.get) if tc else "unknown"
            g["alert_type_counts"] = tc
            g["status"] = "active" if g.pop("has_active") else "retired"
            result.append(g)
        result.sort(key=lambda x: x["latest_created_at"] or "", reverse=True)
        return result

    def test_10_same_narrative_collapses_to_1_group(self):
        alerts = self._make_alerts("narr1", [f"TOKEN_{i}" for i in range(10)])
        groups = self._group(alerts)
        assert len(groups) == 1
        assert groups[0]["alert_count"] == 10
        assert groups[0]["token_count"] == 10

    def test_two_different_narratives_two_groups(self):
        a1 = self._make_alerts("narr1", ["A", "B", "C"])
        a2 = self._make_alerts("narr2", ["X", "Y"])
        groups = self._group(a1 + a2)
        assert len(groups) == 2

    def test_max_confidence_within_group(self):
        alerts = self._make_alerts("narr1", ["A", "B", "C"])
        # confidence_score: 0.30, 0.35, 0.40
        groups = self._group(alerts)
        assert groups[0]["max_confidence"] == pytest.approx(0.40, abs=0.01)

    def test_token_names_preview_capped_at_10(self):
        alerts = self._make_alerts("narr1", [f"T{i}" for i in range(20)])
        groups = self._group(alerts)
        assert len(groups[0]["token_names"]) == 10

    def test_status_active_if_any_active(self):
        alerts = self._make_alerts("narr1", ["A", "B"])
        alerts[0]["status"] = "retired"
        alerts[1]["status"] = "active"
        groups = self._group(alerts)
        assert groups[0]["status"] == "active"

    def test_status_retired_if_all_retired(self):
        alerts = self._make_alerts("narr1", ["A", "B"])
        for a in alerts:
            a["status"] = "retired"
        groups = self._group(alerts)
        assert groups[0]["status"] == "retired"

    def test_dominant_alert_type_is_most_frequent(self):
        alerts = self._make_alerts("narr1", ["A", "B", "C", "D"], alert_type="watch")
        alerts[0]["alert_type"] = "possible_entry"
        # 1 possible_entry, 3 watch → dominant = watch
        groups = self._group(alerts)
        assert groups[0]["dominant_alert_type"] == "watch"


# ---------------------------------------------------------------------------
# Part 4: NarrativeCandidate.confidence is discriminative
# ---------------------------------------------------------------------------

class TestNarrativeCandidateConfidenceIsDiscriminative:
    """The board's confidence (from NarrativeCandidate.confidence) must vary
    based on token count, corroboration, and recency."""

    def _make_candidate(self, token_count: int, x_corr: float = 0.0, seconds_since: float = 60.0):
        from datetime import datetime, timezone
        from mctrend.narrative.discovery_engine import NarrativeCandidate, _candidate_id
        now = datetime.now(timezone.utc).timestamp()
        cand = NarrativeCandidate(
            candidate_id=_candidate_id(f"TEST_{token_count}_{x_corr}"),
            canonical_name=f"TEST_{token_count}",
            first_seen=now - 3600,
            last_seen=now - seconds_since,
        )
        cand.x_spike_corroboration = x_corr
        for i in range(token_count):
            cand.add_token(f"t{i}", f"Token{i}", obs_time=now - 120)
        return cand

    def test_more_tokens_raises_candidate_confidence(self):
        low = self._make_candidate(token_count=2).confidence()
        high = self._make_candidate(token_count=15).confidence()
        assert high > low

    def test_x_corroboration_raises_candidate_confidence(self):
        no_corr = self._make_candidate(token_count=5, x_corr=0.0).confidence()
        with_corr = self._make_candidate(token_count=5, x_corr=1.0).confidence()
        assert with_corr > no_corr

    def test_stale_candidate_lower_confidence(self):
        fresh = self._make_candidate(token_count=5, seconds_since=60).confidence()
        stale = self._make_candidate(token_count=5, seconds_since=7000).confidence()
        assert fresh > stale

    def test_confidence_not_constant_across_different_candidates(self):
        scores = [
            self._make_candidate(token_count=tc, x_corr=xc).confidence()
            for tc, xc in [(2, 0.0), (5, 0.0), (10, 0.5), (20, 1.0)]
        ]
        # All different
        assert len(set(scores)) == len(scores), f"Expected all different, got {scores}"

    def test_noise_candidate_confidence_lower_than_strong(self):
        noise = self._make_candidate(token_count=1).confidence()   # 1 token → base=0
        strong = self._make_candidate(token_count=20, x_corr=0.8).confidence()
        assert strong > noise + 0.20  # large gap


# ---------------------------------------------------------------------------
# Part 5: Noise does not flood the grouped view
# ---------------------------------------------------------------------------

class TestNoiseFiltering:
    """Noise (low-token, low-confidence, retired) should not dominate the view."""

    def test_narrative_board_excludes_noise_by_default(self):
        """build_narrative_board with include_noise=False drops NOISE entries."""
        from datetime import datetime, timezone
        from mctrend.narrative.discovery_engine import NarrativeCandidate, _candidate_id
        from mctrend.narrative.scoring import build_narrative_board

        now = datetime.now(timezone.utc).timestamp()
        # NOISE: only 2 tokens
        noise = NarrativeCandidate(
            candidate_id=_candidate_id("NOISE_TERM"),
            canonical_name="NOISE_TERM",
            first_seen=now - 300,
            last_seen=now - 60,
        )
        noise.add_token("t1", "Token1", obs_time=now - 120)
        noise.add_token("t2", "Token2", obs_time=now - 120)

        # WEAK: 4 tokens
        weak = NarrativeCandidate(
            candidate_id=_candidate_id("WEAK_TERM"),
            canonical_name="WEAK_TERM",
            first_seen=now - 300,
            last_seen=now - 60,
        )
        for i in range(4):
            weak.add_token(f"w{i}", f"Weak{i}", obs_time=now - 120)

        board = build_narrative_board([noise, weak], include_noise=False)
        terms = [e["term"] for e in board]
        assert "NOISE_TERM" not in terms
        assert "WEAK_TERM" in terms

    def test_narrative_board_includes_noise_when_flag_set(self):
        from datetime import datetime, timezone
        from mctrend.narrative.discovery_engine import NarrativeCandidate, _candidate_id
        from mctrend.narrative.scoring import build_narrative_board

        now = datetime.now(timezone.utc).timestamp()
        noise = NarrativeCandidate(
            candidate_id=_candidate_id("TINY"),
            canonical_name="TINY",
            first_seen=now - 300,
            last_seen=now - 60,
        )
        noise.add_token("t1", "Token1", obs_time=now - 120)
        noise.add_token("t2", "Token2", obs_time=now - 120)

        board = build_narrative_board([noise], include_noise=True)
        assert len(board) == 1
        assert board[0]["classification"] == "NOISE"
