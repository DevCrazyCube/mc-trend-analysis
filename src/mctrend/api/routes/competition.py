"""Competition outcome routes — dashboard visibility into winner selection."""

from fastapi import APIRouter, Depends

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_competition_outcomes

router = APIRouter(prefix="/api/competition", tags=["competition"])


@router.get("")
async def get_competition(
    _: None = Depends(require_auth),
):
    """Competition outcomes from the most recent pipeline cycle.

    Returns:
      - narrative_outcomes: per-narrative competition status, rank,
        suppression reasons, and winner explanations
      - token_outcomes: per-token competition status within each narrative,
        suppression reasons, and winner explanations
      - summary: aggregate counts (winners, suppressed, below_threshold)
    """
    outcomes = get_competition_outcomes()
    if not outcomes:
        return {
            "cycle": None,
            "started_at": None,
            "narrative_outcomes": [],
            "token_outcomes": [],
            "summary": {
                "narrative_winners": 0,
                "narrative_suppressed": 0,
                "narrative_below_threshold": 0,
                "token_winners": 0,
                "token_suppressed": 0,
            },
            "status": "no_cycle_completed",
        }

    narr = outcomes.get("narrative_outcomes", [])
    tok = outcomes.get("token_outcomes", [])

    return {
        "cycle": outcomes.get("cycle"),
        "started_at": outcomes.get("started_at"),
        "narrative_outcomes": narr,
        "token_outcomes": tok,
        "summary": {
            "narrative_winners": sum(
                1 for n in narr
                if n.get("competition_status") in ("winner", "no_contest")
            ),
            "narrative_suppressed": sum(
                1 for n in narr
                if n.get("competition_status") == "outcompeted"
            ),
            "narrative_below_threshold": sum(
                1 for n in narr
                if n.get("competition_status") == "below_threshold"
            ),
            "token_winners": sum(
                1 for t in tok
                if t.get("token_competition_status") == "winner"
            ),
            "token_suppressed": sum(
                1 for t in tok
                if t.get("token_competition_status") == "suppressed"
            ),
        },
        "status": "ok",
    }
