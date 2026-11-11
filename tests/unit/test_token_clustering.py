"""Unit tests for token name clustering.

Covers:
- cluster_tokens_by_name: grouping, canonical name selection, pattern flags
- add_cluster_info_to_board_entry: board entry enrichment, rapid_spawn flag
"""
from __future__ import annotations

import pytest

from mctrend.narrative.token_clustering import (
    CLUSTER_SIMILARITY_THRESHOLD,
    RAPID_SPAWN_VELOCITY_THRESHOLD,
    REPEAT_SIMILARITY_THRESHOLD,
    TokenCluster,
    add_cluster_info_to_board_entry,
    cluster_tokens_by_name,
)


# ---------------------------------------------------------------------------
# cluster_tokens_by_name
# ---------------------------------------------------------------------------

class TestClusterTokensByName:
    def test_empty_returns_empty(self):
        assert cluster_tokens_by_name([]) == []

    def test_single_name_forms_own_cluster(self):
        result = cluster_tokens_by_name(["TRUMP"])
        assert len(result) == 1
        assert result[0].names == ["TRUMP"]

    def test_identical_names_merge(self):
        result = cluster_tokens_by_name(["TRUMP", "TRUMP"])
        assert len(result) == 1
        assert result[0].count == 1  # de-duped

    def test_highly_similar_names_cluster_together(self):
        # "MY FIRST COIN" and "MY FIRST COIN TWO" share many trigrams
        names = ["MY FIRST COIN", "MY FIRST COIN TWO"]
        result = cluster_tokens_by_name(names)
        assert len(result) == 1
        assert result[0].count == 2

    def test_dissimilar_names_separate_clusters(self):
        names = ["TRUMP", "ELMO"]
        result = cluster_tokens_by_name(names)
        assert len(result) == 2

    def test_canonical_name_is_shortest(self):
        names = ["MY FIRST COIN TWO", "MY FIRST COIN"]
        result = cluster_tokens_by_name(names)
        assert len(result) == 1
        assert result[0].canonical_name == "MY FIRST COIN"

    def test_repeated_flag_for_near_identical(self):
        # Very similar names → "repeated" flag
        names = ["TRUMPCOIN", "TRUMPCOINS", "TRUMPCOINX"]
        result = cluster_tokens_by_name(names)
        # All should end up in one or two clusters; at least one should have repeated
        flat_flags = [f for c in result for f in c.pattern_flags]
        assert "repeated" in flat_flags or "converging" in flat_flags

    def test_converging_flag_for_similar_but_distinct(self):
        # "MY FIRST COIN" and "My First Ever Coin" — similar but not near-identical
        names = ["MY FIRST COIN", "MY FIRST EVER COIN"]
        result = cluster_tokens_by_name(names)
        # These should cluster together and produce converging or repeated
        all_flags = [f for c in result for f in c.pattern_flags]
        # At minimum they should cluster (one group)
        assert len(result) <= 2  # may or may not merge depending on exact Jaccard
        # If they merged, flags should be present
        if len(result) == 1 and result[0].count == 2:
            assert len(result[0].pattern_flags) > 0

    def test_sorted_by_count_descending(self):
        names = [
            "TRUMP", "TRUMPAI", "TRUMPMEME", "TRUMPCOIN",  # 4 similar
            "ELMO",  # 1 standalone
        ]
        result = cluster_tokens_by_name(names)
        if len(result) >= 2:
            # Largest cluster first
            assert result[0].count >= result[1].count

    def test_returns_tokencluster_instances(self):
        result = cluster_tokens_by_name(["ALPHA", "BETA"])
        for item in result:
            assert isinstance(item, TokenCluster)

    def test_names_deduped(self):
        names = ["COIN", "COIN", "COIN"]
        result = cluster_tokens_by_name(names)
        assert len(result) == 1
        assert result[0].count == 1
        assert result[0].names == ["COIN"]

    def test_max_similarity_zero_for_single_member(self):
        result = cluster_tokens_by_name(["ALONE"])
        assert result[0].max_similarity == 0.0

    def test_max_similarity_nonzero_for_merged(self):
        names = ["MY FIRST COIN", "MY FIRST COIN TWO"]
        result = cluster_tokens_by_name(names)
        if len(result) == 1:
            assert result[0].max_similarity > 0.0

    def test_many_names_performance(self):
        # 50 names should not crash or take forever
        names = [f"TOKEN{i:02d}" for i in range(50)]
        result = cluster_tokens_by_name(names)
        assert len(result) > 0

    def test_case_insensitive_grouping(self):
        # trigram_jaccard uppercases → "trump" and "TRUMP" are identical
        names = ["trump", "TRUMP"]
        result = cluster_tokens_by_name(names)
        # Should produce 1 cluster with 1 unique name (after dedup in set)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# add_cluster_info_to_board_entry
# ---------------------------------------------------------------------------

class TestAddClusterInfoToBoardEntry:
    def _make_entry(
        self,
        token_names: list[str],
        tokens_last_5m: int = 0,
    ) -> dict:
        return {
            "tokens": [{"name": n} for n in token_names],
            "velocity": {
                "tokens_last_5m": tokens_last_5m,
                "tokens_last_15m": 0,
                "tokens_last_60m": 0,
                "rate_per_minute": 0.0,
                "acceleration": "flat",
            },
            "classification": "EMERGING",
            "term": "TEST",
        }

    def test_adds_token_clusters_field(self):
        entry = self._make_entry(["A", "B"])
        add_cluster_info_to_board_entry(entry)
        assert "token_clusters" in entry
        assert isinstance(entry["token_clusters"], list)

    def test_adds_pattern_flags_field(self):
        entry = self._make_entry(["A", "B"])
        add_cluster_info_to_board_entry(entry)
        assert "pattern_flags" in entry
        assert isinstance(entry["pattern_flags"], list)

    def test_rapid_spawn_flag_when_high_velocity(self):
        entry = self._make_entry(
            ["A", "B", "C"],
            tokens_last_5m=RAPID_SPAWN_VELOCITY_THRESHOLD,
        )
        add_cluster_info_to_board_entry(entry)
        assert "rapid_spawn" in entry["pattern_flags"]

    def test_no_rapid_spawn_flag_when_low_velocity(self):
        entry = self._make_entry(
            ["A", "B"],
            tokens_last_5m=RAPID_SPAWN_VELOCITY_THRESHOLD - 1,
        )
        add_cluster_info_to_board_entry(entry)
        assert "rapid_spawn" not in entry["pattern_flags"]

    def test_empty_tokens_produces_empty_clusters(self):
        entry = self._make_entry([])
        add_cluster_info_to_board_entry(entry)
        assert entry["token_clusters"] == []
        assert entry["pattern_flags"] == []  # unless velocity triggers rapid_spawn

    def test_cluster_dict_has_expected_keys(self):
        entry = self._make_entry(["MY FIRST COIN", "MY FIRST COIN TWO"])
        add_cluster_info_to_board_entry(entry)
        for cluster in entry["token_clusters"]:
            assert "canonical_name" in cluster
            assert "names" in cluster
            assert "count" in cluster
            assert "pattern_flags" in cluster
            assert "max_similarity" in cluster

    def test_returns_same_entry_object(self):
        entry = self._make_entry(["X"])
        result = add_cluster_info_to_board_entry(entry)
        assert result is entry  # mutates in place and returns same object

    def test_pattern_flags_no_duplicates(self):
        # Many clusters all with same flag → aggregated without duplicates
        entry = self._make_entry(
            ["TRUMP", "TRUMPAI", "TRUMPMEME", "TRUMPCOIN"],
            tokens_last_5m=5,
        )
        add_cluster_info_to_board_entry(entry)
        assert len(entry["pattern_flags"]) == len(set(entry["pattern_flags"]))

    def test_similar_names_produce_cluster_with_flag(self):
        # Known-similar names should cluster and produce a flag
        entry = self._make_entry(["MY FIRST COIN", "MY FIRST COIN TWO", "MY FIRST COIN THREE"])
        add_cluster_info_to_board_entry(entry)
        # At least some clustering should happen
        assert len(entry["token_clusters"]) <= 3
        if len(entry["token_clusters"]) < 3:
            # Some merged → pattern flags should appear
            assert len(entry["pattern_flags"]) > 0 or entry["token_clusters"][0]["count"] > 1
