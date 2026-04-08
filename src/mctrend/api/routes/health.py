"""Health and system status routes."""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from mctrend.api.auth import require_auth
from mctrend.api.deps import (
    get_cycle_stats,
    get_db,
    get_pipeline_start_time,
    get_ws_adapter,
)
from mctrend.config.settings import Settings
from mctrend.persistence.repositories import (
    AlertRepository,
    NarrativeRepository,
    SourceGapRepository,
    TokenRepository,
)

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def get_health(
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Full system health — source status, cycle stats, open gaps."""
    token_repo = TokenRepository(db)
    narrative_repo = NarrativeRepository(db)
    alert_repo = AlertRepository(db)
    gap_repo = SourceGapRepository(db)

    # Token counts
    token_counts = {}
    for status in ["new", "linked", "scored", "alerted", "expired", "discarded"]:
        rows = token_repo.list_by_status(status)
        token_counts[status] = len(rows)

    # Narrative counts
    narrative_counts = {}
    for state in ["EMERGING", "PEAKING", "DECLINING", "DEAD"]:
        rows = narrative_repo.get_active(states=[state])
        narrative_counts[state] = len(rows)

    # Alerts
    active_alerts = alert_repo.get_active()

    # Source gaps
    open_gaps = gap_repo.get_open_gaps()

    # WS adapter health
    ws_adapter = get_ws_adapter()
    ws_health = ws_adapter.get_source_meta() if ws_adapter else {
        "ws_connected": False,
        "total_events_received": 0,
        "last_error": "adapter not registered",
    }

    # Uptime
    start_time = get_pipeline_start_time()
    uptime_seconds = round(time.time() - start_time) if start_time else None

    # DB size
    db_size_mb = round(db.get_size_bytes() / (1024 * 1024), 2)

    # Last cycle
    cycle_stats = get_cycle_stats()

    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "db_size_mb": db_size_mb,
        "token_counts": token_counts,
        "narrative_counts": narrative_counts,
        "active_alerts": len(active_alerts),
        "open_source_gaps": len(open_gaps),
        "source_gaps": [
            {
                "source": g.get("source_name"),
                "source_type": g.get("source_type"),
                "since": g.get("started_at"),
                "notes": g.get("notes"),
            }
            for g in open_gaps
        ],
        "ws_discovery": ws_health,
        "last_cycle": cycle_stats,
    }


@router.get("/sources")
async def get_source_health(
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Per-source health detail including recent source gaps."""
    gap_repo = SourceGapRepository(db)

    ws_adapter = get_ws_adapter()
    sources = {}

    if ws_adapter:
        meta = ws_adapter.get_source_meta()
        sources["pumpportal_ws"] = {
            "status": "connected" if meta.get("ws_connected") else "disconnected",
            "healthy": meta.get("healthy", False),
            "total_events": meta.get("total_events_received", 0),
            "reconnects": meta.get("reconnect_count", 0),
            "seconds_since_last_message": meta.get("seconds_since_last_message"),
            "queue_depth": meta.get("queue_depth", 0),
            "last_error": meta.get("last_error"),
        }
    else:
        sources["pumpportal_ws"] = {
            "status": "not_registered",
            "healthy": False,
            "note": "Set PUMPPORTAL_WS_ENABLED=true and restart to enable WebSocket discovery",
        }

    # Open gaps
    open_gaps = gap_repo.get_open_gaps()
    by_source = {}
    for gap in open_gaps:
        sn = gap.get("source_name", "unknown")
        by_source.setdefault(sn, []).append({
            "since": gap.get("started_at"),
            "notes": gap.get("notes"),
        })

    for sname, gaps in by_source.items():
        sources.setdefault(sname, {})["open_gaps"] = gaps

    return {"sources": sources}
