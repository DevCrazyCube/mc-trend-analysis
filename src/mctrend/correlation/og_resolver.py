"""Resolve which token in a namespace is most likely the original/canonical token.

Reference: docs/intelligence/og-token-resolution.md

OG resolution is triggered when two or more tokens are linked to the same
narrative.  Each candidate is scored across four signal categories (temporal
priority, name precision, cross-source mentions, deployer pattern) and ranked.

All weights and operational parameters come from configuration — see
``mctrend.config.settings.OGResolutionConfig``.
"""

from __future__ import annotations

import logging

from mctrend.config.settings import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load configurable values from settings
# ---------------------------------------------------------------------------

_settings = Settings.load()
_og_config = _settings.og_resolution

DEFAULT_WEIGHTS: dict[str, float] = {
    "temporal": _og_config.weights.temporal,
    "name_precision": _og_config.weights.name_precision,
    "cross_source": _og_config.weights.cross_source,
    "deployer": _og_config.weights.deployer,
}
DEFAULT_DECAY_MINUTES: float = _og_config.temporal_decay_minutes
DEFAULT_MAX_EXPECTED_MENTIONS: int = _og_config.max_expected_mentions


# ---------------------------------------------------------------------------
# Signal scoring functions
# ---------------------------------------------------------------------------


def compute_temporal_score(
    token_launch_minutes_after_first: float,
    decay_minutes: float | None = None,
) -> float:
    """First token gets 1.0, decays linearly to 0.0 at *decay_minutes*.

    Reference: docs/intelligence/og-token-resolution.md — Signal 1: Temporal Priority.
    """
    if decay_minutes is None:
        decay_minutes = DEFAULT_DECAY_MINUTES

    if token_launch_minutes_after_first <= 0:
        return 1.0
    return max(0.0, 1.0 - (token_launch_minutes_after_first / decay_minutes))


def compute_name_precision(match_confidence: float, match_method: str) -> float:
    """Higher for exact matches, lower for related terms.

    Reference: docs/intelligence/og-token-resolution.md — Signal 2: Name Precision.

    The method multiplier reflects how "direct" the match is.  The product of
    match_confidence (from the name-matching layer) and the multiplier gives
    the name-precision signal score.
    """
    method_multipliers: dict[str, float] = {
        "exact": 1.0,
        "abbreviation": 0.70,
        "related_term": 0.45,
        "semantic": 0.30,
        "none": 0.0,
    }
    multiplier = method_multipliers.get(match_method, 0.3)
    return match_confidence * multiplier


def _compute_cross_source_score(
    cross_source_mentions: int,
    max_expected_mentions: int | None = None,
) -> float:
    """Normalize cross-source mention count to [0, 1].

    Reference: docs/intelligence/og-token-resolution.md — Signal 3.
    ``cross_source_score = min(unique_source_mention_count / MAX_EXPECTED_MENTIONS, 1.0)``
    """
    if max_expected_mentions is None:
        max_expected_mentions = DEFAULT_MAX_EXPECTED_MENTIONS

    if cross_source_mentions <= 0:
        return 0.0
    return min(cross_source_mentions / max_expected_mentions, 1.0)


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


def resolve_og_candidates(
    candidates: list[dict],
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """Score and rank OG candidates for a single narrative namespace.

    Parameters
    ----------
    candidates
        Each dict must contain:
        - ``token_id``: str
        - ``launch_time_minutes_after_first``: float
        - ``match_confidence``: float
        - ``match_method``: str  ("exact" | "abbreviation" | "related_term" | "semantic" | "none")
        - ``cross_source_mentions``: int
        - ``deployer_score``: float  (0.5 = neutral, higher = more trustworthy)

    weights
        Optional override for the four signal weights.  Keys:
        ``temporal``, ``name_precision``, ``cross_source``, ``deployer``.
        Must sum to 1.0.  Falls back to configuration defaults.

    Returns
    -------
    list[dict]
        The same candidates sorted descending by ``og_score``, each
        annotated with ``og_score``, ``og_rank``, and ``og_signals``.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS

    scored: list[dict] = []

    for candidate in candidates:
        temporal = compute_temporal_score(
            candidate["launch_time_minutes_after_first"]
        )
        name_prec = compute_name_precision(
            candidate["match_confidence"], candidate["match_method"]
        )
        cross_src = _compute_cross_source_score(candidate["cross_source_mentions"])
        deployer = candidate["deployer_score"]

        og_score = (
            temporal * w["temporal"]
            + name_prec * w["name_precision"]
            + cross_src * w["cross_source"]
            + deployer * w["deployer"]
        )

        # --- Build signals ---
        og_signals: list[str] = []

        if candidate["launch_time_minutes_after_first"] <= 0:
            og_signals.append("first_in_namespace")
        elif candidate["launch_time_minutes_after_first"] > DEFAULT_DECAY_MINUTES * 0.5:
            og_signals.append("late_entry")

        if cross_src >= 0.6:
            og_signals.append("cross_source_confirmed")

        if candidate["match_method"] == "exact" and candidate["match_confidence"] >= 0.9:
            og_signals.append("strong_name_match")

        if deployer >= 0.7:
            og_signals.append("deployer_positive_history")
        elif deployer <= 0.3:
            og_signals.append("deployer_suspicious")

        annotated = dict(candidate)
        annotated["og_score"] = round(og_score, 6)
        annotated["og_signals"] = og_signals
        scored.append(annotated)

    # Sort descending by og_score
    scored.sort(key=lambda c: c["og_score"], reverse=True)

    # Detect namespace collision (multiple candidates with near-identical scores)
    if len(scored) >= 2:
        top_score = scored[0]["og_score"]
        for entry in scored[1:]:
            if abs(top_score - entry["og_score"]) < 0.10:
                if "namespace_collision" not in entry.get("og_signals", []):
                    entry["og_signals"].append("namespace_collision")
                if "namespace_collision" not in scored[0].get("og_signals", []):
                    scored[0]["og_signals"].append("namespace_collision")

    # Assign ranks (1-based)
    for rank, entry in enumerate(scored, start=1):
        entry["og_rank"] = rank

    return scored
