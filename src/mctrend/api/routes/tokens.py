"""Token explorer routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_db
from mctrend.persistence.repositories import (
    AlertRepository,
    LinkRepository,
    NarrativeRepository,
    ScoringRepository,
    TokenRepository,
)

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _safe_json(val):
    if val is None:
        return val
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


@router.get("")
async def list_tokens(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(_DEFAULT_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """List tokens with optional status filter."""
    token_repo = TokenRepository(db)

    if status:
        tokens = token_repo.list_by_status(status, limit=limit)
    else:
        # All statuses — raw query
        cursor = db.connection.cursor()
        rows = cursor.execute(
            "SELECT * FROM tokens ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        tokens = [dict(r) for r in rows]

    result = []
    for t in tokens:
        t["data_gaps"] = _safe_json(t.get("data_gaps"))
        t["data_sources"] = _safe_json(t.get("data_sources"))
        t["linked_narratives"] = _safe_json(t.get("linked_narratives"))
        result.append(t)

    return {"tokens": result, "count": len(result)}


@router.get("/{token_id}")
async def get_token(
    token_id: str,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Full token detail — chain snapshot, links, scores, alerts."""
    token_repo = TokenRepository(db)
    link_repo = LinkRepository(db)
    scoring_repo = ScoringRepository(db)
    alert_repo = AlertRepository(db)
    narrative_repo = NarrativeRepository(db)

    # Try by token_id first, then by address
    token = token_repo.get_by_id(token_id)
    if token is None:
        token = token_repo.get_by_address(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")

    tid = token["token_id"]
    token["data_gaps"] = _safe_json(token.get("data_gaps"))
    token["data_sources"] = _safe_json(token.get("data_sources"))
    token["linked_narratives"] = _safe_json(token.get("linked_narratives"))

    # Latest chain snapshot
    snapshot = token_repo.get_latest_snapshot(tid)
    if snapshot:
        snapshot["data_gaps"] = _safe_json(snapshot.get("data_gaps"))

    # Narrative links
    links = link_repo.get_for_token(tid)
    enriched_links = []
    for link in links:
        link["match_signals"] = _safe_json(link.get("match_signals"))
        link["og_signals"] = _safe_json(link.get("og_signals"))
        narrative = narrative_repo.get_by_id(link.get("narrative_id", ""))
        if narrative:
            link["narrative_description"] = narrative.get("description")
            link["narrative_state"] = narrative.get("state")
        enriched_links.append(link)

    # Latest score per link
    scores = []
    for link in links:
        lid = link.get("link_id", "")
        cursor = db.connection.cursor()
        row = cursor.execute(
            "SELECT * FROM scored_tokens WHERE link_id = ? "
            "ORDER BY scored_at DESC LIMIT 1",
            (lid,),
        ).fetchone()
        if row:
            s = dict(row)
            s["risk_flags"] = _safe_json(s.get("risk_flags"))
            s["data_gaps"] = _safe_json(s.get("data_gaps"))
            s["dimension_details"] = _safe_json(s.get("dimension_details"))
            scores.append(s)

    # Alerts for this token
    alerts = alert_repo.get_for_token(tid)
    for a in alerts:
        a["dimension_scores"] = _safe_json(a.get("dimension_scores"))
        a["risk_flags"] = _safe_json(a.get("risk_flags"))
        a["re_eval_triggers"] = _safe_json(a.get("re_eval_triggers"))
        a["history"] = _safe_json(a.get("history"))

    return {
        "token": token,
        "chain_snapshot": snapshot,
        "links": enriched_links,
        "scores": scores,
        "alerts": alerts,
    }
