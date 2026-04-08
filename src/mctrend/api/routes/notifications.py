"""Operator notification feed routes."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, le=200),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """List operator notifications."""
    cursor = db.connection.cursor()
    if unread_only:
        rows = cursor.execute(
            "SELECT * FROM operator_notifications WHERE read = 0 "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = cursor.execute(
            "SELECT * FROM operator_notifications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    notifications = [_row_to_dict(r) for r in rows]
    unread_count = cursor.execute(
        "SELECT COUNT(*) FROM operator_notifications WHERE read = 0"
    ).fetchone()[0]

    return {
        "notifications": notifications,
        "count": len(notifications),
        "unread_count": unread_count,
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Mark a notification as read."""
    cursor = db.connection.cursor()
    row = cursor.execute(
        "SELECT notification_id FROM operator_notifications WHERE notification_id = ?",
        (notification_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    cursor.execute(
        "UPDATE operator_notifications SET read = 1 WHERE notification_id = ?",
        (notification_id,),
    )
    db.connection.commit()
    return {"marked_read": notification_id}


@router.post("/read-all")
async def mark_all_read(
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Mark all notifications as read."""
    cursor = db.connection.cursor()
    cursor.execute("UPDATE operator_notifications SET read = 1 WHERE read = 0")
    db.connection.commit()
    return {"marked_read": cursor.rowcount}


@router.get("/delivery-logs")
async def get_delivery_logs(
    limit: int = Query(100, le=500),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Alert delivery history across all channels."""
    cursor = db.connection.cursor()
    rows = cursor.execute(
        """SELECT d.*, a.token_name, a.token_symbol, a.alert_type
           FROM alert_deliveries d
           LEFT JOIN alerts a ON a.alert_id = d.alert_id
           ORDER BY d.attempted_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return {
        "delivery_logs": [_row_to_dict(r) for r in rows],
        "count": len(rows),
    }
