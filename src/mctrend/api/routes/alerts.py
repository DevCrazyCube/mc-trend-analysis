"""Alert center routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_db
from mctrend.persistence.repositories import AlertRepository, TokenRepository

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _safe_json(val):
    if val is None:
        return val
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


def _enrich_alert(a: dict) -> dict:
    a["dimension_scores"] = _safe_json(a.get("dimension_scores"))
    a["risk_flags"] = _safe_json(a.get("risk_flags"))
    a["re_eval_triggers"] = _safe_json(a.get("re_eval_triggers"))
    a["history"] = _safe_json(a.get("history"))
    return a


@router.get("")
async def list_alerts(
    status: str | None = Query(None, description="active / retired"),
    alert_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """List alerts with optional filters."""
    alert_repo = AlertRepository(db)

    if status == "active":
        alerts = alert_repo.get_active()
    elif status == "retired":
        cursor = db.connection.cursor()
        rows = cursor.execute(
            "SELECT * FROM alerts WHERE status = 'retired' "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        alerts = [dict(r) for r in rows]
    else:
        cursor = db.connection.cursor()
        rows = cursor.execute(
            "SELECT * FROM alerts ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        alerts = [dict(r) for r in rows]

    if alert_type:
        alerts = [a for a in alerts if a.get("alert_type") == alert_type]

    return {
        "alerts": [_enrich_alert(a) for a in alerts],
        "count": len(alerts),
    }


@router.get("/by-narrative")
async def list_alerts_by_narrative(
    status: str | None = Query(None, description="active / retired"),
    limit: int = Query(50, le=200),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Alerts grouped by narrative — one row per narrative cluster.

    Each group contains:
    - narrative_id, narrative_name
    - alert_count, token_count (distinct tokens in group)
    - max_confidence, max_net_potential
    - dominant_alert_type (most common type)
    - token_names (preview, up to 10)
    - latest_created_at
    - status (active if any alert is active)
    - alerts (full child list, enriched)

    Sorted by latest_created_at descending.
    """
    cursor = db.connection.cursor()

    if status == "active":
        rows = cursor.execute(
            "SELECT * FROM alerts WHERE status = 'active' "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit * 20,),
        ).fetchall()
    elif status == "retired":
        rows = cursor.execute(
            "SELECT * FROM alerts WHERE status = 'retired' "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit * 20,),
        ).fetchall()
    else:
        rows = cursor.execute(
            "SELECT * FROM alerts ORDER BY updated_at DESC LIMIT ?",
            (limit * 20,),
        ).fetchall()

    alerts = [_enrich_alert(dict(r)) for r in rows]

    # Group by narrative_id; fall back to narrative_name when id absent
    groups: dict[str, dict] = {}
    for a in alerts:
        key = a.get("narrative_id") or a.get("narrative_name") or "_ungrouped"
        if key not in groups:
            groups[key] = {
                "narrative_id": a.get("narrative_id"),
                "narrative_name": a.get("narrative_name") or key,
                "alert_count": 0,
                "token_names": [],
                "_token_set": set(),
                "_type_counts": {},
                "max_confidence": 0.0,
                "max_net_potential": 0.0,
                "latest_created_at": None,
                "has_active": False,
                "alerts": [],
            }
        g = groups[key]
        g["alert_count"] += 1

        tname = a.get("token_name") or a.get("token_address", "")
        if tname and tname not in g["_token_set"]:
            g["_token_set"].add(tname)
            g["token_names"].append(tname)

        conf = a.get("confidence_score") or 0.0
        if conf > g["max_confidence"]:
            g["max_confidence"] = round(conf, 4)

        net = a.get("net_potential") or 0.0
        if net > g["max_net_potential"]:
            g["max_net_potential"] = round(net, 4)

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
        # dominant type = most frequent
        type_counts = g.pop("_type_counts")
        g.pop("_token_set")
        g["token_count"] = len(g["token_names"])
        g["token_names"] = g["token_names"][:10]  # cap preview
        g["dominant_alert_type"] = max(type_counts, key=type_counts.get) if type_counts else "unknown"
        g["alert_type_counts"] = type_counts
        g["status"] = "active" if g.pop("has_active") else "retired"
        result.append(g)

    result.sort(key=lambda g: g["latest_created_at"] or "", reverse=True)
    return {"groups": result[:limit], "count": len(result)}


@router.get("/{alert_id}")
async def get_alert(
    alert_id: str,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Alert detail with full reasoning and delivery history."""
    alert_repo = AlertRepository(db)
    token_repo = TokenRepository(db)

    cursor = db.connection.cursor()
    row = cursor.execute(
        "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert = _enrich_alert(dict(row))

    # Delivery logs
    delivery_rows = cursor.execute(
        "SELECT * FROM alert_deliveries WHERE alert_id = ? ORDER BY attempted_at",
        (alert_id,),
    ).fetchall()
    deliveries = [dict(r) for r in delivery_rows]

    # Token detail
    token = token_repo.get_by_id(alert.get("token_id", ""))
    if token:
        token["data_gaps"] = _safe_json(token.get("data_gaps"))
        token["data_sources"] = _safe_json(token.get("data_sources"))

    return {
        "alert": alert,
        "deliveries": deliveries,
        "token": token,
    }
