"""Search trends adapter for attention measurement."""
import httpx
from datetime import datetime, timezone
from .base import SourceAdapter, logger

class SerpAPITrendsAdapter(SourceAdapter):
    """Fetch Google Trends data via SerpAPI."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        super().__init__(source_name="serpapi_trends", source_type="search_trends")
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://serpapi.com/search"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def fetch(self) -> list[dict]:
        """Fetch current trending searches."""
        if not self.api_key:
            logger.debug("serpapi_skipped_no_key")
            return []

        try:
            client = await self._get_client()
            response = await client.get(
                self.base_url,
                params={"engine": "google_trends_trending_now", "frequency": "realtime",
                        "geo": "US", "api_key": self.api_key}
            )
            response.raise_for_status()
            data = response.json()

            self._mark_healthy()

            trends = []
            for item in data.get("trending_searches", data.get("realtime_searches", [])):
                trend = self._normalize_trend(item)
                if trend:
                    trends.append(trend)

            logger.info("serpapi_fetch_complete", trend_count=len(trends))
            return trends

        except Exception as e:
            self._mark_unhealthy(str(e))
            logger.error("serpapi_fetch_failed", error=str(e))
            return []

    def _normalize_trend(self, raw: dict) -> dict | None:
        """Convert trending search to event signal."""
        try:
            query = raw.get("query") or raw.get("title", {}).get("query", "")
            if not query:
                # Try to get from nested structure
                queries = raw.get("trend_keywords", [])
                if queries:
                    query = queries[0] if isinstance(queries[0], str) else str(queries[0])

            if not query or len(query) < 2:
                return None

            terms = [t.strip().upper() for t in query.split() if len(t.strip()) >= 2]

            return {
                "anchor_terms": terms[:5],
                "related_terms": [],
                "description": f"Trending search: {query}",
                "source_type": "search_trends",
                "source_name": "google_trends",
                "signal_strength": 0.7,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning("serpapi_normalize_failed", error=str(e))
            return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
