"""Health and system status routes."""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from mctrend.api.auth import require_auth
from mctrend.api.deps import (
    get_competition_outcomes,
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


@router.get("/silence")
async def get_silence_explanation(
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Explain why the system produced zero alerts in the last cycle.

    Returns structured silence reasons so operators can distinguish between
    "nothing happened because the system is broken" and "nothing happened
    because no signal was strong enough" — the latter is expected behavior.
    """
    cycle_stats = get_cycle_stats()
    competition = get_competition_outcomes()

    # If no cycle has run yet
    if not cycle_stats:
        return {
            "silent": True,
            "reason": "no_cycle_completed",
            "detail": "No pipeline cycle has completed yet.",
            "silence_reasons": [],
            "last_cycle": None,
        }

    alerts_created = cycle_stats.get("alerts_created", 0)
    if alerts_created > 0:
        return {
            "silent": False,
            "reason": "alerts_were_created",
            "detail": f"{alerts_created} alert(s) created in cycle {cycle_stats.get('cycle')}.",
            "silence_reasons": [],
            "last_cycle": cycle_stats.get("cycle"),
        }

    # System is silent — explain why
    silence_reasons = []

    # Check: no tokens ingested
    if cycle_stats.get("tokens_ingested", 0) == 0 and cycle_stats.get("tokens_scored", 0) == 0:
        silence_reasons.append({
            "code": "no_tokens_available",
            "detail": "No tokens were ingested or scored this cycle.",
        })

    # Check: no narratives at alert-eligible states
    narrative_repo = NarrativeRepository(db)
    rising = narrative_repo.get_active(states=["RISING"])
    trending = narrative_repo.get_active(states=["TRENDING"])
    if not rising and not trending:
        all_states = {}
        for state in ["WEAK", "EMERGING", "RISING", "TRENDING", "FADING", "DEAD"]:
            count = len(narrative_repo.get_active(states=[state]))
            if count > 0:
                all_states[state] = count
        silence_reasons.append({
            "code": "no_narrative_reached_alert_eligibility",
            "detail": "No narrative is in RISING or TRENDING state. Alerts require RISING+.",
            "narrative_state_counts": all_states,
        })

    # Check: competition outcomes — all below threshold or outcompeted
    narr_outcomes = competition.get("narrative_outcomes", [])
    if narr_outcomes:
        winners = [n for n in narr_outcomes if n.get("competition_status") in ("winner", "no_contest")]
        if not winners:
            silence_reasons.append({
                "code": "no_narrative_won_competition",
                "detail": "All narratives were either outcompeted or below the strength threshold.",
                "narrative_count": len(narr_outcomes),
            })

    # Check: all candidates suppressed at token level
    tok_outcomes = competition.get("token_outcomes", [])
    if tok_outcomes:
        token_winners = [t for t in tok_outcomes if t.get("token_competition_status") == "winner"]
        if not token_winners:
            silence_reasons.append({
                "code": "all_token_candidates_suppressed",
                "detail": "All token candidates were suppressed during competition.",
            })

    # Check: suppressed count
    suppressed = cycle_stats.get("suppressed", 0)
    quality_gated = cycle_stats.get("quality_gated", 0)
    if suppressed > 0 or quality_gated > 0:
        silence_reasons.append({
            "code": "candidates_filtered",
            "detail": f"{quality_gated} quality-gated, {suppressed} suppressed by competition/gating.",
            "quality_gated": quality_gated,
            "suppressed": suppressed,
        })

    # Check: errors
    errors = cycle_stats.get("errors", [])
    if errors:
        silence_reasons.append({
            "code": "cycle_had_errors",
            "detail": f"Cycle encountered {len(errors)} error(s) that may have prevented alerts.",
            "errors": errors,
        })

    # Default: explain this is expected
    if not silence_reasons:
        silence_reasons.append({
            "code": "no_actionable_signal",
            "detail": "No signal met all thresholds. This is expected when no strong trend exists.",
        })

    return {
        "silent": True,
        "reason": "no_alerts_created",
        "detail": f"Cycle {cycle_stats.get('cycle')} completed with 0 alerts. "
                  "Silence is expected when no dominant signal exists.",
        "silence_reasons": silence_reasons,
        "last_cycle": cycle_stats.get("cycle"),
    }
