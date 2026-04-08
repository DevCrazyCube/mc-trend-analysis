"""Narrative explorer routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_db
from mctrend.persistence.repositories import (
    LinkRepository,
    NarrativeRepository,
    TokenRepository,
)

router = APIRouter(prefix="/api/narratives", tags=["narratives"])


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
async def list_narratives(
    state: str | None = Query(None, description="Filter by state: EMERGING/PEAKING/DECLINING/DEAD"),
    limit: int = Query(50, le=200),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """List narratives, optionally filtered by state."""
    narrative_repo = NarrativeRepository(db)

    if state:
        narratives = narrative_repo.get_active(states=[state.upper()])
    else:
        cursor = db.connection.cursor()
        rows = cursor.execute(
            "SELECT * FROM narratives ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        narratives = [dict(r) for r in rows]

    result = []
    for n in narratives:
        n["anchor_terms"] = _safe_json(n.get("anchor_terms"))
        n["related_terms"] = _safe_json(n.get("related_terms"))
        n["entities"] = _safe_json(n.get("entities"))
        n["sources"] = _safe_json(n.get("sources"))
        n["data_gaps"] = _safe_json(n.get("data_gaps"))
        result.append(n)

    return {"narratives": result, "count": len(result)}


@router.get("/{narrative_id}")
async def get_narrative(
    narrative_id: str,
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Narrative detail — sources, linked tokens, OG ranking."""
    narrative_repo = NarrativeRepository(db)
    link_repo = LinkRepository(db)
    token_repo = TokenRepository(db)

    narrative = narrative_repo.get_by_id(narrative_id)
    if narrative is None:
        raise HTTPException(status_code=404, detail="Narrative not found")

    narrative["anchor_terms"] = _safe_json(narrative.get("anchor_terms"))
    narrative["related_terms"] = _safe_json(narrative.get("related_terms"))
    narrative["entities"] = _safe_json(narrative.get("entities"))
    narrative["sources"] = _safe_json(narrative.get("sources"))
    narrative["data_gaps"] = _safe_json(narrative.get("data_gaps"))

    # Linked tokens ordered by OG rank
    links = link_repo.get_active_for_narrative(narrative_id)
    enriched = []
    for link in links:
        link["match_signals"] = _safe_json(link.get("match_signals"))
        link["og_signals"] = _safe_json(link.get("og_signals"))
        token = token_repo.get_by_id(link.get("token_id", ""))
        if token:
            link["token_name"] = token.get("name")
            link["token_symbol"] = token.get("symbol")
            link["token_address"] = token.get("address")
            link["token_status"] = token.get("status")
            link["launch_time"] = token.get("launch_time")
        enriched.append(link)

    # Sort by OG rank ascending (None last)
    enriched.sort(key=lambda x: (x.get("og_rank") is None, x.get("og_rank") or 999))

    return {
        "narrative": narrative,
        "linked_tokens": enriched,
        "linked_token_count": len(enriched),
    }
