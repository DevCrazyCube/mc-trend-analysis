"""Base class for all source adapters."""
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable
import structlog

logger = structlog.get_logger(__name__)

# Default retry delays for transient network failures (seconds)
DEFAULT_RETRY_DELAYS = (1.0, 2.0, 4.0)


def _is_retryable_default(exc: Exception) -> bool:
    """Default retryability predicate: retry on anything except HTTP 429 or 403.

    - HTTP 429 (Too Many Requests): rate-limit signal; handled by the caller's
      cooldown logic, not retried.
    - HTTP 403 (Forbidden): authorization/configuration failure; retrying is
      pointless and wastes API credits.  The caller must surface this as a
      configuration error.
    - All other exceptions (network errors, timeouts, 5xx) are transient and
      retried with exponential backoff.
    """
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code not in (403, 429)
    except ImportError:
        pass
    return True


async def retry_fetch(
    coro_func: Callable,
    source_name: str,
    delays: tuple = DEFAULT_RETRY_DELAYS,
    is_retryable: Callable[[Exception], bool] = _is_retryable_default,
):
    """Retry an async callable up to len(delays)+1 times with exponential backoff.

    *coro_func* must be a zero-argument async callable that either returns a
    non-empty list on success or raises an exception on failure.

    *is_retryable* is called with each exception; when it returns False the
    exception is re-raised immediately without further retry attempts.  The
    default predicate treats HTTP 429 as non-retryable — rate-limit responses
    should be handled by the caller's cooldown logic, not retried.

    Returns the first successful result, or raises the last exception after all
    attempts are exhausted.
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((*delays, None), start=1):
        try:
            result = await coro_func()
            if attempt > 1:
                logger.info("fetch_succeeded_after_retry",
                            source=source_name, attempt=attempt)
            return result
        except Exception as e:
            last_exc = e
            if not is_retryable(e):
                logger.warning(
                    "fetch_not_retryable",
                    source=source_name,
                    attempt=attempt,
                    error=str(e),
                )
                raise e
            logger.warning("fetch_attempt_failed",
                           source=source_name, attempt=attempt, error=str(e))
            if delay is not None:
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


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
            "last_successful_fetch": (
                self._last_successful_fetch.isoformat()
                if self._last_successful_fetch
                else None
            ),
            "consecutive_failures": self._consecutive_failures,
        }

    def _mark_healthy(self):
        self._healthy = True
        self._last_successful_fetch = datetime.now(timezone.utc)
        self._consecutive_failures = 0

    def _mark_unhealthy(self, error: str):
        self._healthy = False
        self._consecutive_failures += 1
        logger.warning(
            "source_unhealthy",
            source=self.source_name,
            error=error,
            consecutive_failures=self._consecutive_failures,
        )
