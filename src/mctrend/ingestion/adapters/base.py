"""Base class for all source adapters."""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
import structlog

logger = structlog.get_logger(__name__)

class SourceAdapter(ABC):
    """Base interface for all ingestion source adapters."""

    def __init__(self, source_name: str, source_type: str):
        self.source_name = source_name
        self.source_type = source_type
        self._healthy = True
        self._last_successful_fetch: datetime | None = None
        self._consecutive_failures = 0

    @abstractmethod
    async def fetch(self) -> list[dict]:
        """Fetch records from source. Returns empty list on failure. Never raises."""
        ...

    def is_healthy(self) -> bool:
        return self._healthy

    def get_source_meta(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "healthy": self._healthy,
            "last_successful_fetch": self._last_successful_fetch.isoformat() if self._last_successful_fetch else None,
            "consecutive_failures": self._consecutive_failures,
        }

    def _mark_healthy(self):
        self._healthy = True
        self._last_successful_fetch = datetime.now(timezone.utc)
        self._consecutive_failures = 0

    def _mark_unhealthy(self, error: str):
        self._healthy = False
        self._consecutive_failures += 1
        logger.warning("source_unhealthy", source=self.source_name, error=error,
                       consecutive_failures=self._consecutive_failures)
