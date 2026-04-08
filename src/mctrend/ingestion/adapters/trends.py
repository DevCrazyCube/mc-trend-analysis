"""Search trends adapter for attention measurement.

NOTE: This adapter is currently unsupported.

SerpAPI's ``google_trends_trending_now`` endpoint (``frequency=realtime``) was
discontinued by SerpAPI.  Requests return HTTP 400 with the message:
"Search for Daily or Realtime trends is discontinued."

The adapter is kept in the codebase for future replacement when a viable
trends API becomes available.  It will never make network calls and will
always return an empty list.

To use a different trends source, implement a new SourceAdapter and register
it in runner.py instead.
"""

from datetime import datetime, timezone
from .base import SourceAdapter, logger


class SerpAPITrendsAdapter(SourceAdapter):
    """Google Trends adapter via SerpAPI — CURRENTLY UNSUPPORTED.

    The upstream API endpoint this adapter relied on has been discontinued.
    ``fetch()`` returns an empty list immediately without any network call.
    """

    #: Signals to build_system() and status output that this adapter is
    #: non-functional regardless of configuration.
    SUPPORTED = False
    UNSUPPORTED_REASON = (
        "SerpAPI google_trends_trending_now endpoint discontinued (HTTP 400). "
        "No viable replacement configured."
    )

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 10.0,
        geo: str = "US",
        signal_strength: float = 0.7,
    ):
        super().__init__(source_name="serpapi_trends", source_type="search_trends")
        self.api_key = api_key
        self.timeout = timeout
        self.geo = geo
        self.signal_strength = signal_strength

    async def fetch(self) -> list[dict]:
        """Return empty list immediately — adapter is unsupported."""
        logger.warning(
            "serpapi_trends_unsupported",
            reason=self.UNSUPPORTED_REASON,
        )
        return []

    async def close(self):
        pass
