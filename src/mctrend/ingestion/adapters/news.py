"""News source adapter for narrative detection."""
import time
import httpx
from datetime import datetime, timezone
from .base import SourceAdapter, logger, retry_fetch

_DEFAULT_QUERY_TERMS = [
    "solana token launch",
    "memecoin crypto",
    "pump.fun token",
    "crypto market token",
]


class NewsAPIAdapter(SourceAdapter):
    """Fetch trending news from NewsAPI.org for narrative detection.

    Includes per-source rate-limit cooldown: after ``cooldown_after`` consecutive
    HTTP 429 responses the adapter stops making requests for ``cooldown_seconds``
    (with exponential backoff per episode, capped at ``max_cooldown_seconds``).
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 10.0,
        query_terms: list[str] | None = None,
        page_size: int = 10,
        signal_strength: float = 0.6,
        domains: str = "",
        cooldown_after: int = 2,
        cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 900.0,
    ):
        super().__init__(source_name="newsapi", source_type="news")
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://newsapi.org/v2"
        self.query_terms = query_terms or _DEFAULT_QUERY_TERMS
        self.page_size = page_size
        self.signal_strength = signal_strength
        self.domains = domains  # comma-separated domain filter (e.g. "coindesk.com")

        # Rate-limit cooldown state
        self._cooldown_after = cooldown_after
        self._cooldown_seconds = cooldown_seconds
        self._max_cooldown_seconds = max_cooldown_seconds
        self._consecutive_429s = 0
        self._cooldown_episodes = 0       # number of cooldown periods entered
        self._cooldown_until: float = 0.0  # monotonic timestamp; 0 = not in cooldown

        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_in_cooldown(self) -> bool:
        """Return True if the adapter is currently in rate-limit cooldown."""
        return time.monotonic() < self._cooldown_until

    def get_source_meta(self) -> dict:
        meta = super().get_source_meta()
        meta["in_rate_limit_cooldown"] = self.is_in_cooldown()
        meta["consecutive_429s"] = self._consecutive_429s
        remaining = max(0.0, self._cooldown_until - time.monotonic())
        meta["cooldown_remaining_seconds"] = round(remaining, 1) if remaining > 0 else 0.0
        return meta

    async def fetch(self) -> list[dict]:
        """Fetch top headlines and trending crypto/tech news."""
        if not self.api_key:
            logger.debug("newsapi_skipped_no_key")
            return []

        # Honour rate-limit cooldown: skip fetch silently during cooldown period
        if self.is_in_cooldown():
            remaining = round(self._cooldown_until - time.monotonic(), 1)
            logger.info(
                "newsapi_cooldown_active",
                cooldown_remaining_seconds=remaining,
                consecutive_429s=self._consecutive_429s,
            )
            return []

        try:
            client = await self._get_client()
            all_articles = []

            for query in self.query_terms:
                async def _do_fetch(q=query):
                    params = {
                        "q": q,
                        "sortBy": "publishedAt",
                        "pageSize": self.page_size,
                        "language": "en",
                        "apiKey": self.api_key,
                    }
                    if self.domains:
                        params["domains"] = self.domains
                    r = await client.get(f"{self.base_url}/everything", params=params)
                    r.raise_for_status()
                    return r.json().get("articles", [])

                articles = await retry_fetch(_do_fetch, self.source_name)
                all_articles.extend(articles)

            # Successful fetch: reset 429 counter
            self._consecutive_429s = 0
            self._mark_healthy()

            # Normalize and deduplicate by title
            events = []
            seen_titles: set[str] = set()
            for article in all_articles:
                title = article.get("title", "")
                if title in seen_titles or not title:
                    continue
                seen_titles.add(title)
                event = self._normalize_article(article)
                if event:
                    events.append(event)

            logger.info("newsapi_fetch_complete", article_count=len(events))
            return events

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                self._handle_429()
            else:
                self._mark_unhealthy(str(e))
                logger.error("newsapi_fetch_failed", status=e.response.status_code, error=str(e))
            return []
        except Exception as e:
            self._mark_unhealthy(str(e))
            logger.error("newsapi_fetch_failed", error=str(e))
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_429(self) -> None:
        """Record a 429 response and enter cooldown if threshold is reached."""
        self._consecutive_429s += 1
        self._mark_unhealthy("HTTP 429 Too Many Requests")
        logger.warning(
            "newsapi_rate_limited",
            consecutive_429s=self._consecutive_429s,
            cooldown_after=self._cooldown_after,
        )
        if self._consecutive_429s >= self._cooldown_after:
            self._cooldown_episodes += 1
            duration = min(
                self._cooldown_seconds * (2 ** (self._cooldown_episodes - 1)),
                self._max_cooldown_seconds,
            )
            self._cooldown_until = time.monotonic() + duration
            logger.warning(
                "newsapi_entering_cooldown",
                cooldown_seconds=round(duration, 1),
                cooldown_episode=self._cooldown_episodes,
            )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _normalize_article(self, article: dict) -> dict | None:
        """Convert news article to event signal dict."""
        try:
            title = article.get("title", "")
            description = article.get("description", "") or ""

            terms = self._extract_terms(title)
            if not terms:
                return None

            pub_at = article.get("publishedAt")
            if pub_at:
                published = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
            else:
                published = datetime.now(timezone.utc)

            source_name = article.get("source", {}).get("name", "unknown")

            return {
                "anchor_terms": terms[:5],
                "related_terms": terms[5:10],
                "description": title,
                "source_type": "news",
                "source_name": source_name,
                "signal_strength": self.signal_strength,
                "published_at": published.isoformat(),
                "url": article.get("url"),
                "raw_text": f"{title} {description}",
                # Pass raw title+description for relevance scoring in the pipeline
                "_title": title,
                "_description": description,
                "_source_name": source_name,
            }
        except Exception as e:
            logger.warning("newsapi_normalize_failed", error=str(e))
            return None

    def _extract_terms(self, text: str) -> list[str]:
        """Extract significant terms from text."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "during",
            "before", "after", "above", "below", "between", "under", "again",
            "further", "then", "once", "here", "there", "when", "where", "why",
            "how", "all", "each", "every", "both", "few", "more", "most", "other",
            "some", "such", "no", "nor", "not", "only", "own", "same", "so",
            "than", "too", "very", "just", "about", "up", "out", "new", "also",
            "and", "but", "or", "if", "this", "that", "it", "its", "what", "which",
            "who", "whom", "these", "those", "i", "me", "my", "we", "our", "you",
            "your", "he", "she", "they", "them", "his", "her", "their", "says",
            "said", "over", "still", "first", "last", "get", "got", "make",
        }

        words = text.replace("-", " ").replace("'", "").split()
        terms = []
        for word in words:
            clean = word.strip(".,!?:;\"'()[]{}").strip()
            if len(clean) >= 2 and clean.lower() not in stop_words:
                terms.append(clean.upper())

        seen: set[str] = set()
        unique = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        return unique

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
