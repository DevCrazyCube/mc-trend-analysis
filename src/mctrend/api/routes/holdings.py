"""Holdings / manual positions routes.

Holdings are manually managed — this is not a broker integration.
Labels clearly indicate manual tracking status.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_db

router = APIRouter(prefix="/api/holdings", tags=["holdings"])

_VALID_STATUSES = {"watching", "entered", "trimmed", "exited", "invalidated"}
_VALID_CONVICTIONS = {"low", "medium", "high", "very_high"}


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


@router.get("")
async def list_holdings(
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """List all holdings (manual position tracking)."""
    cursor = db.connection.cursor()
    rows = cursor.execute(
        "SELECT * FROM holdings ORDER BY created_at DESC"
    ).fetchall()
    return {
        "holdings": [_row_to_dict(r) for r in rows],
        "count": len(rows),
        "note": "Manual tracking — not broker-connected.",
    }


class HoldingCreate(BaseModel):
    token_address: str
    token_name: str | None = None
    token_symbol: str | None = None
    status: str = "watching"
    size_sol: float | None = None
    avg_entry_price_sol: float | None = None
    conviction: str | None = None
    exit_plan: str | None = None
    notes: str | None = None
    alert_id: str | None = None
    linked_narrative: str | None = None


@router.post("")
async def create_holding(
    body: HoldingCreate,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Create a new manual holding entry."""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_VALID_STATUSES)}",
        )
    if body.conviction and body.conviction not in _VALID_CONVICTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"conviction must be one of {sorted(_VALID_CONVICTIONS)}",
        )

    now = datetime.now(timezone.utc).isoformat()
    holding_id = str(uuid.uuid4())

    cursor = db.connection.cursor()
    cursor.execute(
        """INSERT INTO holdings
           (holding_id, token_address, token_name, token_symbol, status,
            size_sol, avg_entry_price_sol, conviction, exit_plan, notes,
            alert_id, linked_narrative, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            holding_id, body.token_address, body.token_name, body.token_symbol,
            body.status, body.size_sol, body.avg_entry_price_sol,
            body.conviction, body.exit_plan, body.notes,
            body.alert_id, body.linked_narrative, now, now,
        ),
    )
    db.connection.commit()

    row = cursor.execute(
        "SELECT * FROM holdings WHERE holding_id = ?", (holding_id,)
    ).fetchone()
    return {"holding": _row_to_dict(row)}


class HoldingUpdate(BaseModel):
    status: str | None = None
    size_sol: float | None = None
    avg_entry_price_sol: float | None = None
    current_price_sol: float | None = None
    realized_pnl_sol: float | None = None
    unrealized_pnl_sol: float | None = None
    conviction: str | None = None
    exit_plan: str | None = None
    notes: str | None = None


@router.put("/{holding_id}")
async def update_holding(
    holding_id: str,
    body: HoldingUpdate,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Update a holding."""
    cursor = db.connection.cursor()
    row = cursor.execute(
        "SELECT * FROM holdings WHERE holding_id = ?", (holding_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Holding not found")

    if body.status and body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_VALID_STATUSES)}",
        )
    if body.conviction and body.conviction not in _VALID_CONVICTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"conviction must be one of {sorted(_VALID_CONVICTIONS)}",
        )

    now = datetime.now(timezone.utc).isoformat()
    existing = _row_to_dict(row)

    cursor.execute(
        """UPDATE holdings SET
           status = ?,
           size_sol = ?,
           avg_entry_price_sol = ?,
           current_price_sol = ?,
           realized_pnl_sol = ?,
           unrealized_pnl_sol = ?,
           conviction = ?,
           exit_plan = ?,
           notes = ?,
           updated_at = ?
           WHERE holding_id = ?""",
        (
            body.status or existing["status"],
            body.size_sol if body.size_sol is not None else existing.get("size_sol"),
            body.avg_entry_price_sol if body.avg_entry_price_sol is not None else existing.get("avg_entry_price_sol"),
            body.current_price_sol if body.current_price_sol is not None else existing.get("current_price_sol"),
            body.realized_pnl_sol if body.realized_pnl_sol is not None else existing.get("realized_pnl_sol"),
            body.unrealized_pnl_sol if body.unrealized_pnl_sol is not None else existing.get("unrealized_pnl_sol"),
            body.conviction or existing.get("conviction"),
            body.exit_plan if body.exit_plan is not None else existing.get("exit_plan"),
            body.notes if body.notes is not None else existing.get("notes"),
            now,
            holding_id,
        ),
    )
    db.connection.commit()

    row = cursor.execute(
        "SELECT * FROM holdings WHERE holding_id = ?", (holding_id,)
    ).fetchone()
    return {"holding": _row_to_dict(row)}


@router.delete("/{holding_id}")
async def delete_holding(
    holding_id: str,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Delete a holding entry."""
    cursor = db.connection.cursor()
    row = cursor.execute(
        "SELECT holding_id FROM holdings WHERE holding_id = ?", (holding_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Holding not found")

    cursor.execute("DELETE FROM holdings WHERE holding_id = ?", (holding_id,))
    db.connection.commit()
    return {"deleted": holding_id}


# --- Tracked wallets ---

@router.get("/wallets/list")
async def list_wallets(
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """List tracked wallets."""
    cursor = db.connection.cursor()
    rows = cursor.execute(
        "SELECT * FROM tracked_wallets ORDER BY created_at DESC"
    ).fetchall()
    return {"wallets": [_row_to_dict(r) for r in rows]}


class WalletCreate(BaseModel):
    address: str
    label: str | None = None
    notes: str | None = None


@router.post("/wallets")
async def add_wallet(
    body: WalletCreate,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Add a wallet address to track."""
    if not body.address or len(body.address) < 32:
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    now = datetime.now(timezone.utc).isoformat()
    wallet_id = str(uuid.uuid4())

    cursor = db.connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO tracked_wallets (wallet_id, address, label, notes, active, created_at) "
            "VALUES (?,?,?,?,1,?)",
            (wallet_id, body.address, body.label, body.notes, now),
        )
        db.connection.commit()
    except Exception:
        raise HTTPException(status_code=409, detail="Wallet address already tracked")

    row = cursor.execute(
        "SELECT * FROM tracked_wallets WHERE wallet_id = ?", (wallet_id,)
    ).fetchone()
    return {"wallet": _row_to_dict(row)}


@router.delete("/wallets/{wallet_id}")
async def remove_wallet(
    wallet_id: str,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Remove a tracked wallet."""
    cursor = db.connection.cursor()
    row = cursor.execute(
        "SELECT wallet_id FROM tracked_wallets WHERE wallet_id = ?", (wallet_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Wallet not found")

    cursor.execute("DELETE FROM tracked_wallets WHERE wallet_id = ?", (wallet_id,))
    db.connection.commit()
    return {"deleted": wallet_id}
