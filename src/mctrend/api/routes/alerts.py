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
