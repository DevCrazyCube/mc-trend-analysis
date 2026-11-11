"""Token name clustering for narrative grouping.

Groups token names by trigram Jaccard similarity so that variants like
"MY FIRST COIN", "MY FIRST COIN TWO", "My First Ever Coin" collapse into
a single cluster under a canonical representative name.

This is purely a display/grouping layer.  It does not affect scoring,
classification, or the NarrativeDiscoveryEngine.  The NarrativeDiscoveryEngine
already handles canonical term merging — this module handles the case where
a board entry's token list contains tokens whose *names* are textually similar
enough to be presented as a cluster rather than individual items.

API
---
cluster_tokens_by_name(token_names) → list[TokenCluster]
    Group a flat list of token names into clusters.

add_cluster_info_to_board_entry(entry) → entry (mutated in place)
    Compute clusters from entry["tokens"], attach pattern_flags.

Design
------
- Threshold 0.40: names sharing ~40% of trigrams → same cluster
- Threshold 0.90: names sharing ~90% of trigrams → repeated-name pattern
- Single-pass greedy: O(N²) but N is typically <30 tokens per candidate
- Deterministic: same input → same clusters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from mctrend.narrative.entity_extraction import trigram_jaccard


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

CLUSTER_SIMILARITY_THRESHOLD = 0.40   # minimum Jaccard for same cluster
REPEAT_SIMILARITY_THRESHOLD = 0.90    # threshold for "repeated name" flag
RAPID_SPAWN_VELOCITY_THRESHOLD = 3    # tokens_last_5m for rapid spawn flag


# ---------------------------------------------------------------------------
# TokenCluster
# ---------------------------------------------------------------------------

@dataclass
class TokenCluster:
    """A group of token names that share a common narrative theme.

    Attributes
    ----------
    canonical_name
        Shortest name in the cluster (used as representative label).
    names
        All token names in this cluster, de-duplicated.
    count
        Number of distinct token names.
    pattern_flags
        List of pattern strings: "repeated", "converging"
        ("rapid_spawn" is added at board-entry level using velocity data).
    max_similarity
        Highest pairwise Jaccard similarity within the cluster (0→1).
    """
    canonical_name: str
    names: list[str]
    count: int
    pattern_flags: list[str] = field(default_factory=list)
    max_similarity: float = 0.0


# ---------------------------------------------------------------------------
# Core clustering
# ---------------------------------------------------------------------------

def cluster_tokens_by_name(token_names: list[str]) -> list[TokenCluster]:
    """Group token names by trigram Jaccard similarity.

    Uses a single-pass greedy algorithm: each name is either merged into an
    existing cluster (if similarity >= CLUSTER_SIMILARITY_THRESHOLD with any
    member) or starts a new cluster.

    Returns clusters sorted by count descending.
    """
    if not token_names:
        return []

    clusters: list[list[str]] = []

    for name in token_names:
        best_cluster_idx: int | None = None
        best_sim = 0.0

        for i, cluster_members in enumerate(clusters):
            # Compare against all members; take best match
            for member in cluster_members:
                sim = trigram_jaccard(name, member)
                if sim >= CLUSTER_SIMILARITY_THRESHOLD and sim > best_sim:
                    best_sim = sim
                    best_cluster_idx = i

        if best_cluster_idx is not None:
            clusters[best_cluster_idx].append(name)
        else:
            clusters.append([name])

    result: list[TokenCluster] = []
    for members in clusters:
        # Canonical name: shortest first, alpha second
        canonical = sorted(members, key=lambda n: (len(n), n))[0]

        # Compute max pairwise similarity within cluster
        max_sim = 0.0
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                s = trigram_jaccard(members[i], members[j])
                if s > max_sim:
                    max_sim = s

        # Pattern flags
        flags: list[str] = []
        if max_sim >= REPEAT_SIMILARITY_THRESHOLD:
            flags.append("repeated")         # near-identical names
        elif max_sim >= CLUSTER_SIMILARITY_THRESHOLD and len(members) > 1:
            flags.append("converging")       # similar but distinct names

        result.append(TokenCluster(
            canonical_name=canonical,
            names=sorted(set(members)),
            count=len(set(members)),
            pattern_flags=flags,
            max_similarity=round(max_sim, 3),
        ))

    result.sort(key=lambda c: c.count, reverse=True)
    return result


# ---------------------------------------------------------------------------
# Board entry enrichment
# ---------------------------------------------------------------------------

def add_cluster_info_to_board_entry(entry: dict) -> dict:
    """Compute token name clusters and attach pattern_flags to a board entry.

    Mutates ``entry`` in place; returns it for convenience.

    Adds:
    - entry["token_clusters"] — list of cluster dicts
    - entry["pattern_flags"] — aggregated list: "repeated", "converging",
      "rapid_spawn" (if velocity warrants it)

    Does not change existing fields.
    """
    token_names = [t["name"] for t in entry.get("tokens", []) if t.get("name")]
    clusters = cluster_tokens_by_name(token_names)

    # Aggregate pattern flags across all clusters
    all_flags: list[str] = []
    seen: set[str] = set()
    for c in clusters:
        for flag in c.pattern_flags:
            if flag not in seen:
                all_flags.append(flag)
                seen.add(flag)

    # rapid_spawn: high velocity = multiple tokens appearing in a short window
    vel = entry.get("velocity", {})
    if vel.get("tokens_last_5m", 0) >= RAPID_SPAWN_VELOCITY_THRESHOLD:
        if "rapid_spawn" not in seen:
            all_flags.append("rapid_spawn")

    entry["token_clusters"] = [
        {
            "canonical_name": c.canonical_name,
            "names": c.names,
            "count": c.count,
            "pattern_flags": c.pattern_flags,
            "max_similarity": c.max_similarity,
        }
        for c in clusters
    ]
    entry["pattern_flags"] = all_flags
    return entry
