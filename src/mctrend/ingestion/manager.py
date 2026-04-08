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
        self._source_gaps: list[dict] = []

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
        """Record a source gap for tracking."""
        gap = {
            "gap_id": str(uuid.uuid4()),
            "source_type": adapter.source_type,
            "source_name": adapter.source_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._source_gaps.append(gap)
        logger.warning("source_gap_opened", **gap)

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
        return [g for g in self._source_gaps if g.get("ended_at") is None]

    async def close_all(self):
        """Close all adapter clients."""
        for adapter in self._token_adapters + self._event_adapters:
            if hasattr(adapter, "close"):
                await adapter.close()
