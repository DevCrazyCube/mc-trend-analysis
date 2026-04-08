"""Normalize raw ingested data into canonical domain records."""

import uuid
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


def normalize_token(raw: dict) -> dict | None:
    """
    Normalize a raw token dict from any source into canonical TokenRecord fields.

    Required fields: address, name, deployed_by, launch_time.
    Missing optional fields are set to None and recorded in data_gaps.

    Returns None if required fields are missing.
    """
    address = raw.get("address")
    name = raw.get("name", "").strip()
    deployed_by = raw.get("deployed_by", "").strip()
    launch_time_raw = raw.get("launch_time")

    # Validate required fields
    if not address:
        logger.warning("normalize_token_rejected", reason="missing_address")
        return None
    if not name:
        logger.warning("normalize_token_rejected", reason="missing_name", address=address)
        return None

    # Parse launch time
    launch_time = _parse_timestamp(launch_time_raw)
    if launch_time is None:
        launch_time = datetime.now(timezone.utc)

    # Build data_gaps
    data_gaps = []
    if not deployed_by:
        deployed_by = "unknown"
        data_gaps.append("deployed_by")

    symbol = raw.get("symbol", "").strip() or name[:10]

    # Optional fields
    initial_liquidity_usd = _safe_float(raw.get("initial_liquidity_usd"))
    initial_holder_count = _safe_int(raw.get("initial_holder_count"))

    for field_name, value in [
        ("initial_liquidity_usd", initial_liquidity_usd),
        ("initial_holder_count", initial_holder_count),
    ]:
        if value is None:
            data_gaps.append(field_name)

    # Determine authority statuses
    mint_status = "unknown"
    freeze_status = "unknown"
    raw_meta = raw.get("raw", {}) if isinstance(raw.get("raw"), dict) else {}
    if raw_meta.get("mint_authority") is not None:
        mint_status = "renounced" if raw_meta["mint_authority"] is None else "active"
    if raw_meta.get("freeze_authority") is not None:
        freeze_status = "renounced" if raw_meta["freeze_authority"] is None else "active"

    now = datetime.now(timezone.utc)

    return {
        "token_id": str(uuid.uuid4()),
        "address": address.strip(),
        "name": name,
        "symbol": symbol,
        "description": raw.get("description"),
        "deployed_by": deployed_by,
        "launch_time": launch_time.isoformat(),
        "launch_platform": raw.get("launch_platform", "unknown"),
        "first_seen_by_system": now.isoformat(),
        "initial_liquidity_usd": initial_liquidity_usd,
        "initial_holder_count": initial_holder_count,
        "mint_authority_status": mint_status,
        "freeze_authority_status": freeze_status,
        "status": "new",
        "linked_narratives": [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "data_gaps": data_gaps,
        "data_sources": [raw.get("data_source", "unknown")],
    }


def normalize_event(raw: dict) -> dict | None:
    """
    Normalize a raw event/news signal into canonical EventRecord fields.

    Required: at least one anchor term.
    """
    anchor_terms = raw.get("anchor_terms", [])
    if not anchor_terms:
        logger.warning("normalize_event_rejected", reason="no_anchor_terms")
        return None

    # Clean terms
    anchor_terms = [t.strip().upper() for t in anchor_terms if t and len(t.strip()) >= 2]
    if not anchor_terms:
        return None

    related_terms = [t.strip().upper() for t in raw.get("related_terms", []) if t and len(t.strip()) >= 2]

    published_at = _parse_timestamp(raw.get("published_at"))
    now = datetime.now(timezone.utc)

    source = {
        "source_id": str(uuid.uuid4()),
        "source_type": raw.get("source_type", "unknown"),
        "source_name": raw.get("source_name", "unknown"),
        "signal_strength": _safe_float(raw.get("signal_strength")) or 0.5,
        "first_seen": (published_at or now).isoformat(),
        "last_updated": now.isoformat(),
        "raw_reference": raw.get("url"),
    }

    return {
        "narrative_id": str(uuid.uuid4()),
        "anchor_terms": anchor_terms,
        "related_terms": related_terms,
        "entities": raw.get("entities", []),
        "description": raw.get("description", " ".join(anchor_terms[:3])),
        "attention_score": _safe_float(raw.get("signal_strength")) or 0.5,
        "narrative_velocity": None,   # Unknown at ingestion time; scoring uses conservative default (0.4)
        "source_type_count": 1,
        "state": "WEAK",
        "sources": [source],
        "first_detected": (published_at or now).isoformat(),
        "peaked_at": None,
        "dead_at": None,
        "updated_at": now.isoformat(),
        "extraction_confidence": 0.6,
        "ambiguous": False,
        "data_gaps": [],
    }


def normalize_chain_snapshot(token_id: str, rpc_data: dict | None,
                             holder_data: dict | None) -> dict | None:
    """Normalize RPC + holder data into a ChainDataRecord / TokenChainSnapshot."""
    if rpc_data is None and holder_data is None:
        return None

    data_gaps = []
    now = datetime.now(timezone.utc)

    # Holder data
    holder_count = None
    top_5_pct = None
    top_10_pct = None

    if holder_data:
        top_accounts = holder_data.get("top_accounts", [])
        holder_count = holder_data.get("holder_count_estimated")
        if top_accounts:
            total_top = sum(a.get("amount", 0) for a in top_accounts)
            if total_top > 0:
                top_5_total = sum(a.get("amount", 0) for a in top_accounts[:5])
                top_10_total = sum(a.get("amount", 0) for a in top_accounts[:10])
                top_5_pct = top_5_total / total_top if total_top else None
                top_10_pct = top_10_total / total_top if total_top else None
    else:
        data_gaps.extend(["holder_count", "top_5_holder_pct", "top_10_holder_pct"])

    # RPC data
    mint_authority = None
    freeze_authority = None
    if rpc_data:
        mint_authority = rpc_data.get("mint_authority")
        freeze_authority = rpc_data.get("freeze_authority")
    else:
        data_gaps.extend(["mint_authority", "freeze_authority"])

    return {
        "snapshot_id": str(uuid.uuid4()),
        "token_id": token_id,
        "sampled_at": now.isoformat(),
        "holder_count": holder_count,
        "top_5_holder_pct": top_5_pct,
        "top_10_holder_pct": top_10_pct,
        "new_wallet_holder_pct": None,  # Requires deeper analysis
        "liquidity_usd": None,  # Requires DEX query
        "liquidity_locked": None,
        "liquidity_lock_hours": None,
        "liquidity_provider_count": None,
        "volume_1h_usd": None,
        "trade_count_1h": None,
        "unique_traders_1h": None,
        "deployer_known_bad": False,
        "deployer_prior_deployments": None,
        "data_source": "solana_rpc",
        "data_gaps": data_gaps,
    }


def merge_narratives(existing: dict, new_source: dict) -> dict:
    """
    Merge a new event signal into an existing narrative record.

    Updates attention score, adds or re-confirms source, updates lifecycle.
    When a source is re-confirmed (same source_name already exists), its
    ``last_updated`` timestamp is refreshed — this is critical for velocity
    computation which counts source updates within the velocity window.
    """
    existing_sources = existing.get("sources", [])
    new_source_name = new_source.get("source_name", "unknown")
    now = datetime.now(timezone.utc)

    # Check if this source already exists
    source_found = False
    for src in existing_sources:
        if src.get("source_name") == new_source_name:
            # Re-confirmation: refresh last_updated for velocity computation
            src["last_updated"] = now.isoformat()
            src["signal_strength"] = _safe_float(new_source.get("signal_strength")) or src.get("signal_strength", 0.5)
            source_found = True
            break

    if not source_found:
        source_entry = {
            "source_id": str(uuid.uuid4()),
            "source_type": new_source.get("source_type", "unknown"),
            "source_name": new_source_name,
            "signal_strength": _safe_float(new_source.get("signal_strength")) or 0.5,
            "first_seen": new_source.get("published_at", now.isoformat()),
            "last_updated": now.isoformat(),
            "raw_reference": new_source.get("url"),
        }
        existing_sources.append(source_entry)

    # Count distinct source types
    source_types = {s.get("source_type") for s in existing_sources}
    source_type_count = len(source_types)

    # Recalculate attention score: average of source signal strengths, boosted by diversity
    strengths = [s.get("signal_strength", 0.5) for s in existing_sources]
    avg_strength = sum(strengths) / len(strengths) if strengths else 0.5
    diversity_boost = min(source_type_count * 0.05, 0.20)
    attention = min(avg_strength + diversity_boost, 1.0)

    # Merge related terms
    existing_related = set(existing.get("related_terms", []))
    new_terms = new_source.get("anchor_terms", []) + new_source.get("related_terms", [])
    for t in new_terms:
        clean = t.strip().upper()
        if clean and clean not in set(existing.get("anchor_terms", [])):
            existing_related.add(clean)

    existing["sources"] = existing_sources
    existing["source_type_count"] = source_type_count
    existing["attention_score"] = round(attention, 4)
    existing["related_terms"] = list(existing_related)
    existing["updated_at"] = now.isoformat()

    return existing


# --- Utility functions ---

def _parse_timestamp(raw) -> datetime | None:
    """Parse various timestamp formats into UTC datetime."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, (int, float)):
        # Unix timestamp: seconds or milliseconds
        ts = raw / 1000 if raw > 1e12 else raw
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _safe_float(value) -> float | None:
    """Safely convert to float, return None on failure."""
    if value is None:
        return None
    try:
        result = float(value)
        return result if not (result != result) else None  # NaN check
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> int | None:
    """Safely convert to int, return None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
