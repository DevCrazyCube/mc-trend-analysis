"""API route for rejected candidate diagnostics."""

import json

from fastapi import APIRouter, Depends, Query

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_db
from mctrend.persistence.repositories import RejectedCandidateRepository

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


def _safe_json(val):
    if val is None:
        return val
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


def _enrich(c: dict) -> dict:
    c["rejection_reasons"] = _safe_json(c.get("rejection_reasons"))
    c["dimension_scores"] = _safe_json(c.get("dimension_scores"))
    c["risk_flags"] = _safe_json(c.get("risk_flags"))
    c["data_gaps"] = _safe_json(c.get("data_gaps"))
    return c


@router.get("")
async def list_rejected_candidates(
    limit: int = Query(100, le=500, description="Max candidates to return"),
    _: None = Depends(require_auth),
    db=Depends(get_db),
):
    """Top rejected candidates sorted by proximity to the watch alert threshold.

    Returns tokens that were scored but classified as 'ignore', sorted by
    watch_gap ascending — i.e., the tokens closest to crossing the alert
    threshold appear first.

    Each record includes:
    - net_potential, p_failure, confidence_score, dimension_scores
    - watch_gap: how far below the watch threshold (0.25 net_potential)
    - rejection_reasons: structured list of per-tier blocking conditions
    - data_gaps: missing data that limited scoring quality
    """
    repo = RejectedCandidateRepository(db)
    candidates = repo.get_top_by_watch_gap(limit=limit)
    return {
        "candidates": [_enrich(c) for c in candidates],
        "count": len(candidates),
        "watch_threshold": 0.25,
    }
