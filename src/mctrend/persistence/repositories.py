"""Repository classes for persisting and querying domain entities."""

import json
from typing import Any

from mctrend.persistence.database import Database

# Columns that store JSON-serialized data (lists or dicts).
_JSON_COLUMNS: set[str] = {
    "linked_narratives",
    "data_gaps",
    "data_sources",
    "anchor_terms",
    "related_terms",
    "entities",
    "sources",
    "match_signals",
    "og_signals",
    "risk_flags",
    "dimension_details",
    "dimension_scores",
    "reasoning",
    "re_eval_triggers",
    "history",
    "rejection_reasons",
}


def _serialize_row(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *data* with JSON-serializable columns dumped to strings."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in _JSON_COLUMNS and value is not None and not isinstance(value, str):
            out[key] = json.dumps(value)
        else:
            out[key] = value
    return out


def _deserialize_row(row: Any | None) -> dict[str, Any] | None:
    """Convert a sqlite3.Row to a plain dict, parsing JSON columns."""
    if row is None:
        return None
    data = dict(row)
    for key in _JSON_COLUMNS:
        if key in data and data[key] is not None:
            try:
                data[key] = json.loads(data[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return data


def _deserialize_rows(rows: list) -> list[dict[str, Any]]:
    """Convert a list of sqlite3.Row objects to plain dicts with parsed JSON."""
    return [_deserialize_row(r) for r in rows]


_ALLOWED_TABLES = frozenset({
    "tokens", "narratives", "token_narrative_links", "scored_tokens",
    "alerts", "alert_deliveries", "chain_snapshots", "source_gaps",
})


def _upsert(db: Database, table: str, data: dict[str, Any]) -> None:
    """Execute an INSERT OR REPLACE for the given table and data dict."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table!r}")
    serialized = _serialize_row(data)
    columns = list(serialized.keys())
    placeholders = ", ".join("?" for _ in columns)
    column_names = ", ".join(columns)
    values = [serialized[c] for c in columns]
    db.connection.execute(
        f"INSERT OR REPLACE INTO {table} ({column_names}) VALUES ({placeholders})",
        values,
    )
    db.connection.commit()


# ---------------------------------------------------------------------------
# TokenRepository
# ---------------------------------------------------------------------------


class TokenRepository:
    """Persistence operations for token records and chain snapshots."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, token: dict) -> None:
        """Upsert a token record by token_id."""
        _upsert(self.db, "tokens", token)

    def get_by_id(self, token_id: str) -> dict | None:
        """Return a token by its primary key, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM tokens WHERE token_id = ?", (token_id,)
        )
        return _deserialize_row(cursor.fetchone())

    def get_by_address(self, address: str) -> dict | None:
        """Return a token by its on-chain address, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM tokens WHERE address = ?", (address,)
        )
        return _deserialize_row(cursor.fetchone())

    def list_by_status(self, status: str, limit: int = 100) -> list[dict]:
        """Return tokens matching *status*, ordered by updated_at descending."""
        cursor = self.db.connection.execute(
            "SELECT * FROM tokens WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        )
        return _deserialize_rows(cursor.fetchall())

    def get_recent(self, hours: float = 8.0, limit: int = 500) -> list[dict]:
        """Return tokens created within the last *hours* hours."""
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = self.db.connection.execute(
            "SELECT * FROM tokens WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
            (cutoff, limit),
        )
        return _deserialize_rows(cursor.fetchall())

    def update_status(self, token_id: str, new_status: str, reason: str) -> None:
        """Update a token's status and log the transition reason in updated_at."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        self.db.connection.execute(
            "UPDATE tokens SET status = ?, updated_at = ? WHERE token_id = ?",
            (new_status, now, token_id),
        )
        self.db.connection.commit()

    def save_chain_snapshot(self, snapshot: dict) -> None:
        """Insert a chain snapshot record."""
        _upsert(self.db, "chain_snapshots", snapshot)

    def get_latest_snapshot(self, token_id: str) -> dict | None:
        """Return the most recent chain snapshot for a token, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM chain_snapshots WHERE token_id = ? "
            "ORDER BY sampled_at DESC LIMIT 1",
            (token_id,),
        )
        return _deserialize_row(cursor.fetchone())

    def prune_old_snapshots(self, older_than: str) -> int:
        """Delete chain snapshots older than *older_than* ISO timestamp.

        Retains the most recent snapshot per token regardless of age.
        Returns the number of rows deleted.
        """
        cursor = self.db.connection.execute(
            """
            DELETE FROM chain_snapshots
            WHERE sampled_at < ?
              AND snapshot_id NOT IN (
                  SELECT snapshot_id FROM chain_snapshots cs2
                  WHERE cs2.token_id = chain_snapshots.token_id
                  ORDER BY sampled_at DESC LIMIT 1
              )
            """,
            (older_than,),
        )
        self.db.connection.commit()
        return cursor.rowcount


# ---------------------------------------------------------------------------
# NarrativeRepository
# ---------------------------------------------------------------------------


class NarrativeRepository:
    """Persistence operations for narrative records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, narrative: dict) -> None:
        """Upsert a narrative record by narrative_id."""
        _upsert(self.db, "narratives", narrative)

    def get_by_id(self, narrative_id: str) -> dict | None:
        """Return a narrative by its primary key, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM narratives WHERE narrative_id = ?", (narrative_id,)
        )
        return _deserialize_row(cursor.fetchone())

    def get_active(self, states: list[str] | None = None, limit: int = 500) -> list[dict]:
        """Return narratives in the given states.

        Default states include both legacy (PEAKING) and new lifecycle states
        (WEAK, EMERGING, RISING, TRENDING, FADING) — everything except DEAD and MERGED.
        """
        if states is None:
            states = ["WEAK", "EMERGING", "RISING", "TRENDING", "FADING", "PEAKING"]
        placeholders = ", ".join("?" for _ in states)
        cursor = self.db.connection.execute(
            f"SELECT * FROM narratives WHERE state IN ({placeholders}) "
            "ORDER BY COALESCE(narrative_strength, attention_score, 0) DESC LIMIT ?",
            [*states, limit],
        )
        return _deserialize_rows(cursor.fetchall())

    def get_for_scoring(self, limit: int = 500) -> list[dict]:
        """Return narratives eligible for token scoring (EMERGING, RISING, TRENDING)."""
        states = ["EMERGING", "RISING", "TRENDING"]
        placeholders = ", ".join("?" for _ in states)
        cursor = self.db.connection.execute(
            f"SELECT * FROM narratives WHERE state IN ({placeholders}) "
            "ORDER BY COALESCE(narrative_strength, attention_score, 0) DESC LIMIT ?",
            [*states, limit],
        )
        return _deserialize_rows(cursor.fetchall())

    def update_fields(self, narrative_id: str, fields: dict[str, Any]) -> None:
        """Update specific fields on a narrative record."""
        if not fields:
            return
        serialized = _serialize_row(fields)
        set_clause = ", ".join(f"{k} = ?" for k in serialized)
        values = list(serialized.values()) + [narrative_id]
        self.db.connection.execute(
            f"UPDATE narratives SET {set_clause} WHERE narrative_id = ?",
            values,
        )
        self.db.connection.commit()

    def search_by_terms(self, terms: list[str], limit: int = 100) -> list[dict]:
        """Search narratives whose anchor_terms or related_terms contain any of *terms*."""
        conditions = []
        params: list[str] = []
        for term in terms:
            pattern = f"%{term}%"
            conditions.append("(anchor_terms LIKE ? OR related_terms LIKE ?)")
            params.extend([pattern, pattern])
        where_clause = " OR ".join(conditions)
        cursor = self.db.connection.execute(
            f"SELECT * FROM narratives WHERE {where_clause} LIMIT ?",
            [*params, limit],
        )
        return _deserialize_rows(cursor.fetchall())

    def update_state(self, narrative_id: str, new_state: str) -> None:
        """Update a narrative's lifecycle state."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        self.db.connection.execute(
            "UPDATE narratives SET state = ?, updated_at = ? WHERE narrative_id = ?",
            (new_state, now, narrative_id),
        )
        self.db.connection.commit()


# ---------------------------------------------------------------------------
# LinkRepository
# ---------------------------------------------------------------------------


class LinkRepository:
    """Persistence operations for token-narrative link records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, link: dict) -> None:
        """Upsert a token-narrative link by link_id."""
        _upsert(self.db, "token_narrative_links", link)

    def get_by_id(self, link_id: str) -> dict | None:
        """Return a link by its primary key, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM token_narrative_links WHERE link_id = ?", (link_id,)
        )
        return _deserialize_row(cursor.fetchone())

    def get_for_token(self, token_id: str) -> list[dict]:
        """Return all links for a given token."""
        cursor = self.db.connection.execute(
            "SELECT * FROM token_narrative_links WHERE token_id = ?", (token_id,)
        )
        return _deserialize_rows(cursor.fetchall())

    def get_for_narrative(self, narrative_id: str) -> list[dict]:
        """Return all links for a given narrative."""
        cursor = self.db.connection.execute(
            "SELECT * FROM token_narrative_links WHERE narrative_id = ?",
            (narrative_id,),
        )
        return _deserialize_rows(cursor.fetchall())

    def get_active_for_narrative(self, narrative_id: str) -> list[dict]:
        """Return active links for a given narrative (status = 'active')."""
        cursor = self.db.connection.execute(
            "SELECT * FROM token_narrative_links "
            "WHERE narrative_id = ? AND status = 'active'",
            (narrative_id,),
        )
        return _deserialize_rows(cursor.fetchall())


# ---------------------------------------------------------------------------
# ScoringRepository
# ---------------------------------------------------------------------------


class ScoringRepository:
    """Persistence operations for scored token records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, scored_token: dict) -> None:
        """Insert a scored token record."""
        _upsert(self.db, "scored_tokens", scored_token)

    def get_latest_for_link(self, link_id: str) -> dict | None:
        """Return the most recent score for a token-narrative link, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM scored_tokens WHERE link_id = ? "
            "ORDER BY scored_at DESC LIMIT 1",
            (link_id,),
        )
        return _deserialize_row(cursor.fetchone())

    def get_history_for_token(
        self, token_id: str, limit: int = 20
    ) -> list[dict]:
        """Return recent scored records for a token, newest first."""
        cursor = self.db.connection.execute(
            "SELECT * FROM scored_tokens WHERE token_id = ? "
            "ORDER BY scored_at DESC LIMIT ?",
            (token_id, limit),
        )
        return _deserialize_rows(cursor.fetchall())

    def prune_old_scored_tokens(self, older_than: str) -> int:
        """Delete scored_tokens records older than *older_than* ISO timestamp.

        Retains the most recent score per link_id regardless of age.
        Returns the number of rows deleted.
        """
        cursor = self.db.connection.execute(
            """
            DELETE FROM scored_tokens
            WHERE scored_at < ?
              AND score_id NOT IN (
                  SELECT score_id FROM scored_tokens st2
                  WHERE st2.link_id = scored_tokens.link_id
                  ORDER BY scored_at DESC LIMIT 1
              )
            """,
            (older_than,),
        )
        self.db.connection.commit()
        return cursor.rowcount


# ---------------------------------------------------------------------------
# AlertRepository
# ---------------------------------------------------------------------------


class AlertRepository:
    """Persistence operations for alert and alert-delivery records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, alert: dict) -> None:
        """Upsert an alert record by alert_id."""
        _upsert(self.db, "alerts", alert)

    def get_by_id(self, alert_id: str) -> dict | None:
        """Return an alert by its primary key, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
        )
        return _deserialize_row(cursor.fetchone())

    def get_active_for_token(self, token_id: str) -> dict | None:
        """Return the active alert for a token, or None."""
        cursor = self.db.connection.execute(
            "SELECT * FROM alerts WHERE token_id = ? AND status = 'ACTIVE' LIMIT 1",
            (token_id,),
        )
        return _deserialize_row(cursor.fetchone())

    def get_for_token(self, token_id: str, limit: int = 20) -> list[dict]:
        """Return all alerts for a token (active and retired), newest first."""
        cursor = self.db.connection.execute(
            "SELECT * FROM alerts WHERE token_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (token_id, limit),
        )
        return _deserialize_rows(cursor.fetchall())

    def get_active(self, limit: int = 100) -> list[dict]:
        """Return all active alerts, ordered by net_potential descending."""
        cursor = self.db.connection.execute(
            "SELECT * FROM alerts WHERE status = 'ACTIVE' "
            "ORDER BY net_potential DESC LIMIT ?",
            (limit,),
        )
        return _deserialize_rows(cursor.fetchall())

    def get_expired(self, now: str, limit: int = 100) -> list[dict]:
        """Return active alerts whose expires_at is at or before *now*."""
        cursor = self.db.connection.execute(
            "SELECT * FROM alerts WHERE expires_at <= ? AND status = 'ACTIVE' LIMIT ?",
            (now, limit),
        )
        return _deserialize_rows(cursor.fetchall())

    def purge_old_retired(self, older_than: str) -> int:
        """Delete retired/expired alerts older than *older_than* ISO timestamp.

        Returns the number of rows deleted.
        """
        cursor = self.db.connection.execute(
            "DELETE FROM alerts WHERE status IN ('RETIRED', 'EXPIRED') "
            "AND updated_at < ?",
            (older_than,),
        )
        self.db.connection.commit()
        return cursor.rowcount

    def retire(self, alert_id: str, reason: str, retired_at: str) -> None:
        """Retire an alert with a reason and timestamp."""
        self.db.connection.execute(
            "UPDATE alerts SET status = 'RETIRED', retirement_reason = ?, "
            "retired_at = ?, updated_at = ? WHERE alert_id = ?",
            (reason, retired_at, retired_at, alert_id),
        )
        self.db.connection.commit()

    def save_delivery(self, delivery: dict) -> None:
        """Insert an alert delivery record."""
        _upsert(self.db, "alert_deliveries", delivery)


# ---------------------------------------------------------------------------
# SourceGapRepository
# ---------------------------------------------------------------------------


class SourceGapRepository:
    """Persistence operations for source-gap records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def open_gap(self, gap: dict) -> None:
        """Record a new source gap."""
        _upsert(self.db, "source_gaps", gap)

    def close_gap(self, gap_id: str, ended_at: str) -> None:
        """Close an open source gap by setting its ended_at timestamp."""
        self.db.connection.execute(
            "UPDATE source_gaps SET ended_at = ? WHERE gap_id = ?",
            (ended_at, gap_id),
        )
        self.db.connection.commit()

    def close_open_gaps_for_source(self, source_name: str, ended_at: str) -> int:
        """Close all open gaps for *source_name*.

        Called when an adapter successfully fetches data after a period of failures.
        Returns the number of gaps closed.
        """
        cursor = self.db.connection.execute(
            "UPDATE source_gaps SET ended_at = ? "
            "WHERE source_name = ? AND ended_at IS NULL",
            (ended_at, source_name),
        )
        self.db.connection.commit()
        return cursor.rowcount

    def get_open_gaps(self) -> list[dict]:
        """Return all source gaps that have not yet been closed."""
        cursor = self.db.connection.execute(
            "SELECT * FROM source_gaps WHERE ended_at IS NULL"
        )
        return _deserialize_rows(cursor.fetchall())


# ---------------------------------------------------------------------------
# RejectedCandidateRepository
# ---------------------------------------------------------------------------


class RejectedCandidateRepository:
    """Persistence for scored tokens that were classified as 'ignore'.

    The table uses a compound primary key (token_id, narrative_id) so that
    only the most recent evaluation per token-narrative pair is kept.
    INSERT OR REPLACE naturally evicts the stale row on each re-score.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, candidate: dict) -> None:
        """Upsert a rejected candidate (INSERT OR REPLACE by token_id+narrative_id)."""
        cols = [
            "token_id", "narrative_id", "token_name", "token_symbol",
            "narrative_name", "score_id", "alert_type",
            "net_potential", "p_potential", "p_failure", "confidence_score",
            "watch_gap", "rejection_reasons", "dimension_scores",
            "risk_flags", "data_gaps", "rejected_at",
        ]
        values = []
        for col in cols:
            val = candidate.get(col)
            if col in _JSON_COLUMNS and val is not None and not isinstance(val, str):
                val = json.dumps(val)
            values.append(val)

        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        self.db.connection.execute(
            f"INSERT OR REPLACE INTO rejected_candidates ({col_names}) VALUES ({placeholders})",
            values,
        )
        self.db.connection.commit()

    def get_top_by_watch_gap(self, limit: int = 100) -> list[dict]:
        """Return candidates sorted by watch_gap ascending (closest to alert first).

        Only returns candidates where watch_gap >= 0 (i.e., truly below watch
        threshold).  Candidates above the watch threshold have been promoted to
        alerts and are excluded.
        """
        cursor = self.db.connection.execute(
            "SELECT * FROM rejected_candidates "
            "WHERE watch_gap >= 0 "
            "ORDER BY watch_gap ASC, net_potential DESC "
            "LIMIT ?",
            (limit,),
        )
        return _deserialize_rows(cursor.fetchall())

    def prune_old(self, older_than: str) -> int:
        """Delete rejected candidates last evaluated before *older_than* ISO timestamp.

        Returns the number of rows deleted.
        """
        cursor = self.db.connection.execute(
            "DELETE FROM rejected_candidates WHERE rejected_at < ?",
            (older_than,),
        )
        self.db.connection.commit()
        return cursor.rowcount
