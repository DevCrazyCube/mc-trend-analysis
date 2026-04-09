"""Correlate spiking X entities with token launches.

Matches spiking entities (from XEntityTracker) against recently launched
tokens by name, symbol, and cashtag overlap.  Produces narrative-compatible
event dicts that feed into the standard normalization -> correlation flow.

All matching is deterministic.  No LLM.

Reference: docs/ingestion/x-emergent-narrative-detection.md
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from mctrend.normalization.normalizer import normalize_token_name

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Match types and their confidence levels
# ---------------------------------------------------------------------------

_MATCH_CONFIDENCE = {
    "name_exact": 0.95,
    "symbol_exact": 0.90,
    "cashtag_exact": 0.95,
    "name_contains": 0.70,
    "symbol_contains": 0.65,
}


def correlate_spike_with_tokens(
    spike: dict,
    tokens: list[dict],
    timing_window_hours: float = 8.0,
) -> list[dict]:
    """Match a spiking entity against recent tokens.

    Parameters
    ----------
    spike
        Spike record from XEntityTracker.detect_spikes().
        Expected keys: entity, entity_type, spike_ratio, spike_class.
    tokens
        List of token dicts from TokenRepository.
        Expected keys: token_id, name, symbol, address, launch_time.
    timing_window_hours
        Only consider tokens launched within this window of now.

    Returns
    -------
    list of match dicts, each containing:
        token_id, token_name, match_type, match_confidence,
        overlap_signals, spike metadata.
    """
    entity = spike.get("entity", "")
    if not entity:
        return []

    entity_norm = normalize_token_name(entity)
    entity_upper = entity.upper()

    now = datetime.now(timezone.utc)
    matches: list[dict] = []

    for token in tokens:
        token_name = token.get("name", "")
        token_symbol = token.get("symbol", "")
        token_name_norm = normalize_token_name(token_name)
        token_symbol_upper = token_symbol.upper().strip()

        # Timing filter
        launch_time_str = token.get("launch_time")
        if launch_time_str and timing_window_hours > 0:
            try:
                lt = datetime.fromisoformat(launch_time_str.replace("Z", "+00:00"))
                if lt.tzinfo is None:
                    lt = lt.replace(tzinfo=timezone.utc)
                hours_ago = (now - lt).total_seconds() / 3600.0
                if hours_ago > timing_window_hours:
                    continue
            except (ValueError, TypeError):
                pass  # Can't parse — don't exclude

        # Compute overlap signals
        overlap_signals: list[str] = []
        match_type: str | None = None
        match_confidence: float = 0.0

        # 1. Name exact match (normalized)
        if entity_norm and token_name_norm and entity_norm == token_name_norm:
            match_type = "name_exact"
            match_confidence = _MATCH_CONFIDENCE["name_exact"]
            overlap_signals.append("name_match")

        # 2. Symbol exact match
        elif entity_upper and token_symbol_upper and entity_upper == token_symbol_upper:
            match_type = "symbol_exact"
            match_confidence = _MATCH_CONFIDENCE["symbol_exact"]
            overlap_signals.append("symbol_match")

        # 3. Cashtag exact match (entity was originally a cashtag)
        elif spike.get("entity_type") == "cashtag" and entity_upper == token_symbol_upper:
            match_type = "cashtag_exact"
            match_confidence = _MATCH_CONFIDENCE["cashtag_exact"]
            overlap_signals.append("cashtag_match")

        # 4. Name contains entity
        elif entity_norm and token_name_norm and len(entity_norm) >= 3 and entity_norm in token_name_norm:
            match_type = "name_contains"
            match_confidence = _MATCH_CONFIDENCE["name_contains"]
            overlap_signals.append("name_partial_match")

        # 5. Symbol contains entity
        elif entity_upper and token_symbol_upper and len(entity_upper) >= 3 and entity_upper in token_symbol_upper:
            match_type = "symbol_contains"
            match_confidence = _MATCH_CONFIDENCE["symbol_contains"]
            overlap_signals.append("symbol_partial_match")

        if match_type is None:
            continue

        # Timing proximity signal
        if launch_time_str:
            overlap_signals.append("timing_proximity")

        matches.append({
            "token_id": token.get("token_id", ""),
            "token_name": token_name,
            "token_symbol": token_symbol,
            "match_type": match_type,
            "match_confidence": match_confidence,
            "overlap_signals": overlap_signals,
            "spike_entity": entity,
            "spike_ratio": spike.get("spike_ratio", 0.0),
            "spike_class": spike.get("spike_class", ""),
        })

        logger.info(
            "x_entity_linked_to_token",
            entity=entity,
            token_name=token_name,
            token_id=token.get("token_id", "")[:12],
            match_type=match_type,
            match_confidence=match_confidence,
            spike_ratio=spike.get("spike_ratio", 0.0),
        )

    return matches


def spike_to_narrative_event(spike: dict, match: dict | None = None) -> dict:
    """Convert a spike record into a narrative-compatible event dict.

    This allows spiking entities to enter the standard
    normalization -> narrative detection -> correlation flow.

    Parameters
    ----------
    spike
        Spike record from XEntityTracker.detect_spikes().
    match
        Optional token match from correlate_spike_with_tokens().
        If provided, the match confidence is used as signal strength.
    """
    entity = spike.get("entity", "UNKNOWN")
    spike_ratio = spike.get("spike_ratio", 1.0)
    spike_class = spike.get("spike_class", "unknown")

    # Signal strength: bounded by spike ratio (capped at 1.0)
    # Base 0.3, boosted by spike magnitude
    base_strength = 0.3
    spike_boost = min(spike_ratio / 20.0, 0.5)  # max 0.5 boost from spike
    match_boost = (match.get("match_confidence", 0.0) * 0.2) if match else 0.0
    signal_strength = min(1.0, base_strength + spike_boost + match_boost)

    now = datetime.now(timezone.utc)

    return {
        "anchor_terms": [entity],
        "related_terms": [],
        "description": f"X spike: {entity} ({spike_class}, {spike_ratio:.1f}x baseline)",
        "source_type": "social_media",
        "source_name": "x_spike_detection",
        "signal_strength": round(signal_strength, 3),
        "published_at": now.isoformat(),
        "url": "",
        "raw_text": "",
        "_title": f"X spike: {entity}",
        "_description": f"Spike ratio {spike_ratio:.1f}x, class={spike_class}",
        "_source_name": "x_spike_detection",
        "entities": [],  # Use list format for narrative compatibility
        "_spike_metadata": {
            "entity": entity,
            "entity_type": spike.get("entity_type", "topic"),
            "spike_ratio": spike_ratio,
            "spike_class": spike_class,
            "short_term_count": spike.get("short_term_count", 0),
            "short_term_authors": spike.get("short_term_authors", 0),
        },
    }
