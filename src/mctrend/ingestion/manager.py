"""Ingestion manager: coordinates source adapters and produces normalized records."""
import asyncio
from datetime import datetime, timezone
from typing import Any
import uuid
import structlog

from .adapters.base import SourceAdapter

logger = structlog.get_logger(__name__)


class IngestionManager:
    """Orchestrates data ingestion from multiple sources."""

    def __init__(self):
        self._token_adapters: list[SourceAdapter] = []
        self._event_adapters: list[SourceAdapter] = []

        # Gaps that have been created this cycle and not yet drained
        self._pending_gaps: list[dict] = []

        # Sources for which a gap has been opened and not yet recovered.
        # Prevents opening a new gap every cycle during an ongoing outage.
        self._sources_with_open_gap: set[str] = set()

    def register_token_adapter(self, adapter: SourceAdapter):
        self._token_adapters.append(adapter)
        logger.info("adapter_registered", name=adapter.source_name, type="token")

    def register_event_adapter(self, adapter: SourceAdapter):
        self._event_adapters.append(adapter)
        logger.info("adapter_registered", name=adapter.source_name, type="event")

    async def fetch_tokens(self) -> list[dict]:
        """Fetch from all token adapters. Returns deduplicated token dicts."""
        all_tokens = []
        for adapter in self._token_adapters:
            tokens = await adapter.fetch()
            if not tokens and adapter.is_healthy() is False:
                self._record_source_gap(adapter)
            all_tokens.extend(tokens)

        return self._deduplicate_tokens(all_tokens)

    async def fetch_events(self) -> list[dict]:
        """Fetch from all event adapters. Returns event signal dicts."""
        all_events = []
        for adapter in self._event_adapters:
            events = await adapter.fetch()
            if not events and adapter.is_healthy() is False:
                self._record_source_gap(adapter)
            all_events.extend(events)

        return all_events

    def _deduplicate_tokens(self, tokens: list[dict]) -> list[dict]:
        """Deduplicate by address."""
        seen = {}
        for token in tokens:
            addr = token.get("address")
            if addr and addr not in seen:
                seen[addr] = token
            elif addr and addr in seen:
                # Merge: keep freshest data
                existing = seen[addr]
                for key, value in token.items():
                    if value is not None and existing.get(key) is None:
                        existing[key] = value
        return list(seen.values())

    def _record_source_gap(self, adapter: SourceAdapter):
        """Record a source gap for tracking.

        Only records a new gap if this source does not already have an open gap
        tracked in this process.  This prevents repeated gap records for the
        same continuous outage window.

        Gaps are deduped again in the pipeline against the persisted DB state
        so that restarts do not re-open gaps that were never closed.
        """
        source_name = adapter.source_name
        if source_name in self._sources_with_open_gap:
            # Gap already open for this source — do not create another
            return

        gap = {
            "gap_id": str(uuid.uuid4()),
            "source_type": adapter.source_type,
            "source_name": source_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._pending_gaps.append(gap)
        self._sources_with_open_gap.add(source_name)
        logger.warning("source_gap_opened", **gap)

    def mark_source_recovered(self, source_name: str) -> None:
        """Inform the manager that *source_name* has recovered.

        Called by the pipeline when it closes the DB-persisted gap for a
        source.  Allows a fresh gap to be recorded if the source fails again.
        """
        self._sources_with_open_gap.discard(source_name)

    def get_source_health(self) -> dict[str, dict]:
        """Get health status of all registered adapters, keyed by source_name."""
        health: dict[str, dict] = {}
        for adapter in self._token_adapters + self._event_adapters:
            meta = adapter.get_source_meta()
            health[adapter.source_name] = meta
        return health

    def get_source_health_list(self) -> list[dict]:
        """Get health status of all registered adapters as a list."""
        return list(self.get_source_health().values())

    def get_pending_gaps(self) -> list[dict]:
        """Return new source gaps created since the last call and drain the list.

        Draining ensures each gap is returned exactly once.  The pipeline is
        responsible for persisting them and deduplicating against the DB.
        """
        gaps = [g for g in self._pending_gaps if g.get("ended_at") is None]
        self._pending_gaps.clear()
        return gaps

    async def close_all(self):
        """Close all adapter clients."""
        for adapter in self._token_adapters + self._event_adapters:
            if hasattr(adapter, "close"):
                await adapter.close()
