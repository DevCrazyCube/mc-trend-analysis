"""Persistent rate-limit state for source adapters.

Stores cooldown state to disk so that process restarts respect rate-limit
windows that were active before the restart.

Wall-clock time (UTC ISO strings) is used for persistence so that the state
is meaningful across process boundaries — unlike ``time.monotonic()`` which
is process-local and resets on restart.

On startup the adapter loads state from disk, computes how much cooldown
remains, and sets a process-local deadline accordingly.  When no state file
exists (fresh install or explicitly cleared) the adapter starts uninhibited.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RateLimitState:
    """Serialisable snapshot of a source's rate-limit history."""

    source_name: str
    # Wall-clock ISO timestamp; None when not in cooldown
    cooldown_until_utc: Optional[str] = None
    consecutive_429s: int = 0
    cooldown_episodes: int = 0
    last_429_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | os.PathLike) -> None:
        """Write state to *path* as JSON.  Creates parent dirs if needed."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
        logger.debug(
            "ratelimit_state_saved",
            source=self.source_name,
            cooldown_until_utc=self.cooldown_until_utc,
            cooldown_episodes=self.cooldown_episodes,
        )

    @classmethod
    def load(cls, path: str | os.PathLike) -> "RateLimitState":
        """Load state from *path*.

        Returns a fresh (unconstrained) state if the file doesn't exist,
        is unreadable, or is malformed.
        """
        p = Path(path)
        if not p.exists():
            return cls(source_name="unknown")
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return cls(**data)
        except Exception as exc:
            logger.warning(
                "ratelimit_state_load_failed",
                path=str(path),
                error=str(exc),
            )
            return cls(source_name="unknown")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def cooldown_remaining_seconds(self) -> float:
        """Seconds of cooldown remaining as of now (0.0 if none active)."""
        if not self.cooldown_until_utc:
            return 0.0
        try:
            until = datetime.fromisoformat(self.cooldown_until_utc)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            remaining = (until - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, remaining)
        except (ValueError, TypeError):
            return 0.0

    def is_in_cooldown(self) -> bool:
        """True if the persisted cooldown deadline is still in the future."""
        return self.cooldown_remaining_seconds() > 0.0

    def enter_cooldown(self, duration_seconds: float) -> None:
        """Record that a cooldown of *duration_seconds* has been entered."""
        now = datetime.now(timezone.utc)
        deadline = now.timestamp() + duration_seconds
        self.cooldown_until_utc = datetime.fromtimestamp(
            deadline, tz=timezone.utc
        ).isoformat()
        self.last_429_at = now.isoformat()

    def reset(self) -> None:
        """Clear all rate-limit state (called on successful recovery)."""
        self.cooldown_until_utc = None
        self.consecutive_429s = 0
        self.last_429_at = None
        # Preserve cooldown_episodes — it is cumulative history, not reset on recovery


def load_state_for_adapter(
    state_path: str | os.PathLike | None,
    source_name: str,
) -> "RateLimitState | None":
    """Load persisted state for *source_name* from *state_path*, or return None.

    Returns None when *state_path* is not configured (empty string / None),
    indicating that persistence is disabled for this adapter.
    """
    if not state_path:
        return None
    state = RateLimitState.load(state_path)
    # Backfill source_name in case the file predates this field
    state.source_name = source_name
    return state
