"""News source adapter for narrative detection."""
import httpx
from datetime import datetime, timezone
from .base import SourceAdapter, logger, retry_fetch

_DEFAULT_QUERY_TERMS = ["crypto", "meme", "viral", "trending"]


class NewsAPIAdapter(SourceAdapter):
    """Fetch trending news from NewsAPI.org for narrative detection."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 10.0,
        query_terms: list[str] | None = None,
        page_size: int = 10,
        signal_strength: float = 0.6,
    ):
        super().__init__(source_name="newsapi", source_type="news")
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://newsapi.org/v2"
        self.query_terms = query_terms or _DEFAULT_QUERY_TERMS
        self.page_size = page_size
        self.signal_strength = signal_strength
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def fetch(self) -> list[dict]:
        """Fetch top headlines and trending crypto/tech news."""
        if not self.api_key:
            logger.debug("newsapi_skipped_no_key")
            return []

        try:
            client = await self._get_client()
            all_articles = []

            for query in self.query_terms:
                async def _do_fetch(q=query):
                    r = await client.get(
                        f"{self.base_url}/everything",
                        params={"q": q, "sortBy": "publishedAt",
                                "pageSize": self.page_size, "language": "en",
                                "apiKey": self.api_key},
                    )
                    r.raise_for_status()
                    return r.json().get("articles", [])

                articles = await retry_fetch(_do_fetch, self.source_name)
                all_articles.extend(articles)

            self._mark_healthy()

            # Normalize and deduplicate by title
            events = []
            seen_titles = set()
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

        except Exception as e:
            self._mark_unhealthy(str(e))
            logger.error("newsapi_fetch_failed", error=str(e))
            return []

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

        seen = set()
        unique = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        return unique

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
