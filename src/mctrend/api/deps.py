"""FastAPI dependencies — database access and system state.

The API shares the Database instance opened by the runner.  On startup,
``set_db()`` is called once; all request handlers use ``get_db()``.

If the dashboard runs as a standalone process (no running pipeline), it
opens its own read-only database connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from mctrend.persistence.database import Database
    from mctrend.ingestion.adapters.pumpportal_ws import PumpPortalWebSocketAdapter

_db: "Database | None" = None
_ws_adapter: "PumpPortalWebSocketAdapter | None" = None
_pipeline_start_time: float | None = None
_cycle_stats: dict = {}
_competition_outcomes: dict = {}
_narrative_board: list = []


def set_db(db: "Database") -> None:
    global _db
    _db = db


def get_db() -> "Database":
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return _db


def set_ws_adapter(adapter: "PumpPortalWebSocketAdapter") -> None:
    global _ws_adapter
    _ws_adapter = adapter


def get_ws_adapter() -> "PumpPortalWebSocketAdapter | None":
    return _ws_adapter


def set_pipeline_start_time(t: float) -> None:
    global _pipeline_start_time
    _pipeline_start_time = t


def get_pipeline_start_time() -> float | None:
    return _pipeline_start_time


def update_cycle_stats(summary: dict) -> None:
    global _cycle_stats
    _cycle_stats = summary


def get_cycle_stats() -> dict:
    return _cycle_stats


def update_competition_outcomes(outcomes: dict) -> None:
    global _competition_outcomes
    _competition_outcomes = outcomes


def get_competition_outcomes() -> dict:
    return _competition_outcomes


def update_narrative_board(board: list) -> None:
    global _narrative_board
    _narrative_board = board


def get_narrative_board() -> list:
    return _narrative_board
