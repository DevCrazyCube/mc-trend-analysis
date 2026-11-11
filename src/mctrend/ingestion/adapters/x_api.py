"""X (Twitter) adapter for emergent narrative detection.

Reference: docs/ingestion/x-emergent-narrative-detection.md

The X subsystem discovers emerging narratives/entities/topics from broad
source material, then correlates spikes with token launches.  It is
**not** a fixed-query crypto keyword scanner.

Polling mode only in this version.  The adapter uses a rotating pool of
broad discovery queries across multiple categories to maximise the
discovery surface within the X API v2 Recent Search budget.
"""

from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime, timezone

import httpx

from .base import SourceAdapter, logger, retry_fetch
from .ratelimit_state import RateLimitState, load_state_for_adapter

# ---------------------------------------------------------------------------
# Discovery query pool
# ---------------------------------------------------------------------------

# Broad, category-based queries designed to catch diverse emergent topics.
# These are NOT crypto keyword searches.  They probe wide surfaces so the
# entity extraction layer (Phase C) can discover what is spiking.
#
# Categories:
#   viral       — catch emerging viral content
#   breaking    — catch breaking news/events
#   crypto      — retain crypto-adjacent awareness without being narrow
#   culture     — meme/culture-driven movements
#   people      — person/org/brand narratives
#   reactions   — meta-signals of emerging attention

_DISCOVERY_QUERY_POOL: dict[str, list[str]] = {
    "viral": [
        '"going viral" lang:en -is:retweet',
        '"blowing up" lang:en -is:retweet',
        '"everyone is talking about" lang:en -is:retweet',
    ],
    "breaking": [
        '"breaking:" lang:en -is:retweet',
        '"just announced" lang:en -is:retweet',
        '"breaking news" lang:en -is:retweet',
    ],
    "crypto": [
        "solana lang:en -is:retweet",
        "pump.fun lang:en -is:retweet",
        "memecoin lang:en -is:retweet",
        "solana token launch lang:en -is:retweet",
    ],
    "culture": [
        "meme coin lang:en -is:retweet",
        "crypto meme lang:en -is:retweet",
        '"new meme" lang:en -is:retweet',
    ],
    "people": [
        '"just said" lang:en -is:retweet',
        '"is dead" lang:en -is:retweet',
        '"has been" arrested OR fired OR elected lang:en -is:retweet',
    ],
    "reactions": [
        '"this is huge" lang:en -is:retweet',
        '"can\'t believe" lang:en -is:retweet',
        '"no way" lang:en -is:retweet',
    ],
}

# Cashtag pattern: $ followed by 2-12 uppercase letters/digits
_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,11})\b")

# Hashtag pattern: # followed by letters/digits/underscores
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]{2,30})\b")

# Bot/spam heuristic thresholds
_MAX_HASHTAG_RATIO = 0.5       # reject if >50% of words are hashtags
_MAX_URL_RATIO = 0.4           # reject if >40% of words are URLs
_MIN_TEXT_LENGTH = 15           # reject very short tweets

# Engagement score weights (log-scale normalisation)
_ENGAGEMENT_W_RETWEETS = 0.4
_ENGAGEMENT_W_LIKES = 0.4
_ENGAGEMENT_W_REPLIES = 0.2
_ENGAGEMENT_NORMALISER = 10.0  # log1p(N)/log1p(NORMALISER) → approx 0–1


def _build_flat_query_pool(categories: dict[str, list[str]] | None = None) -> list[str]:
    """Flatten category map into a single ordered list for rotation."""
    cats = categories or _DISCOVERY_QUERY_POOL
    pool: list[str] = []
    for queries in cats.values():
        pool.extend(queries)
    return pool


class XAPIAdapter(SourceAdapter):
    """Fetch narrative signals from X (Twitter) via API v2 Recent Search.

    **Discovery mode:** Each cycle selects a rotating subset of broad
    discovery queries from a configurable category pool.  The real
    intelligence lives in entity extraction from the results, not in
    what we search for.

    **Rate-limit handling:** Same exponential-backoff cooldown pattern as
    :class:`NewsAPIAdapter`.  Cooldown state is persisted to disk via
    :class:`RateLimitState` so that process restarts respect active
    rate-limit windows.

    **Output:** Event dicts compatible with ``normalize_event()``, using
    ``source_type="social_media"`` to distinguish X signals from news.
    """

    def __init__(
        self,
        bearer_token: str | None = None,
        timeout: float = 10.0,
        discovery_categories: dict[str, list[str]] | None = None,
        queries_per_cycle: int = 10,
        max_requests_per_cycle: int = 10,
        signal_strength: float = 0.5,
        cooldown_after: int = 2,
        cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 900.0,
        state_path: str | os.PathLike | None = None,
    ):
        super().__init__(source_name="x", source_type="social_media")
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.base_url = "https://api.x.com/2"
        self.signal_strength = signal_strength

        # Discovery query pool and rotation
        self._query_pool = _build_flat_query_pool(discovery_categories)
        self._queries_per_cycle = min(queries_per_cycle, len(self._query_pool))
        self.max_requests_per_cycle = max_requests_per_cycle
        self._cycle_index: int = 0  # rotation counter

        # Rate-limit cooldown policy
        self._cooldown_after = cooldown_after
        self._cooldown_seconds = cooldown_seconds
        self._max_cooldown_seconds = max_cooldown_seconds

        # Persistent state
        self._state_path = state_path
        self._persisted: RateLimitState | None = load_state_for_adapter(
            state_path, source_name="x"
        )

        # Process-local state
        self._consecutive_429s: int = 0
        self._cooldown_episodes: int = 0
        self._cooldown_until: float = 0.0  # monotonic timestamp
        self._failure_mode: str = "healthy"  # healthy | rate-limited | forbidden | unavailable

        if self._persisted is not None:
            self._consecutive_429s = self._persisted.consecutive_429s
            self._cooldown_episodes = self._persisted.cooldown_episodes
            remaining = self._persisted.cooldown_remaining_seconds()
            if remaining > 0.0:
                self._cooldown_until = time.monotonic() + remaining
                self._healthy = False
                logger.warning(
                    "x_cooldown_restored_from_state",
                    cooldown_remaining_seconds=round(remaining, 1),
                    cooldown_episodes=self._cooldown_episodes,
                    state_path=str(state_path),
                )

        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Discovery query rotation
    # ------------------------------------------------------------------

    def _select_queries_for_cycle(self) -> list[str]:
        """Select the next subset of discovery queries via round-robin rotation.

        Each cycle advances the rotation index, ensuring different queries
        are used on successive cycles.  This maximises the discovery surface
        across cycles while staying within the per-cycle API budget.
        """
        pool_size = len(self._query_pool)
        if pool_size == 0:
            return []

        n = min(self._queries_per_cycle, pool_size, self.max_requests_per_cycle)
        start = self._cycle_index % pool_size
        self._cycle_index += n

        # Wrap-around selection
        if start + n <= pool_size:
            return self._query_pool[start:start + n]
        else:
            return self._query_pool[start:] + self._query_pool[:n - (pool_size - start)]

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
        meta["cooldown_episodes"] = self._cooldown_episodes
        # Computed failure_mode: rate-limited supersedes other states when cooldown active
        meta["failure_mode"] = "rate-limited" if self.is_in_cooldown() else self._failure_mode
        return meta

    async def fetch(self) -> list[dict]:
        """Fetch recent tweets from the rotating discovery query pool.

        Returns event dicts compatible with ``normalize_event()``.
        """
        if not self.bearer_token:
            logger.debug("x_skipped_no_token")
            return []

        if self.is_in_cooldown():
            remaining = round(self._cooldown_until - time.monotonic(), 1)
            logger.info(
                "x_cooldown_active",
                cooldown_remaining_seconds=remaining,
                consecutive_429s=self._consecutive_429s,
                cooldown_episodes=self._cooldown_episodes,
            )
            return []

        try:
            client = await self._get_client()
            all_tweets: list[dict] = []
            requests_made = 0

            cycle_queries = self._select_queries_for_cycle()

            for query in cycle_queries:
                if requests_made >= self.max_requests_per_cycle:
                    break

                async def _do_fetch(q=query):
                    params = {
                        "query": q,
                        "max_results": 10,
                        "tweet.fields": "created_at,public_metrics,author_id,entities",
                        "expansions": "author_id",
                        "user.fields": "username,public_metrics",
                    }
                    headers = {"Authorization": f"Bearer {self.bearer_token}"}
                    r = await client.get(
                        f"{self.base_url}/tweets/search/recent",
                        params=params,
                        headers=headers,
                    )
                    r.raise_for_status()
                    return r.json()

                # retry_fetch re-raises 429 immediately (non-retryable)
                response = await retry_fetch(_do_fetch, self.source_name)
                requests_made += 1

                tweets = response.get("data", [])

                # Build author lookup from includes
                users_by_id: dict[str, dict] = {}
                for user in response.get("includes", {}).get("users", []):
                    users_by_id[user["id"]] = user

                for tweet in tweets:
                    tweet["_user"] = users_by_id.get(tweet.get("author_id", ""), {})
                    all_tweets.append(tweet)

            # Successful cycle: reset rate-limit state
            self._consecutive_429s = 0
            self._failure_mode = "healthy"
            self._mark_healthy()
            self._persist_state(cleared=True)

            # Filter and normalise
            events = self._process_tweets(all_tweets)

            logger.info(
                "x_fetch_complete",
                raw_count=len(all_tweets),
                events_produced=len(events),
                requests_made=requests_made,
                queries_used=len(cycle_queries),
            )
            return events

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                self._failure_mode = "rate-limited"
                self._handle_429()
            elif e.response.status_code == 403:
                self._handle_403()
            else:
                self._failure_mode = "unavailable"
                self._mark_unhealthy(str(e))
                logger.error(
                    "x_source_unavailable",
                    status=e.response.status_code,
                    error=str(e),
                )
            return []
        except Exception as e:
            self._failure_mode = "unavailable"
            self._mark_unhealthy(str(e))
            logger.error("x_source_unavailable", error=str(e))
            return []

    # ------------------------------------------------------------------
    # Tweet processing
    # ------------------------------------------------------------------

    def _process_tweets(self, raw_tweets: list[dict]) -> list[dict]:
        """Filter spam, deduplicate, and normalise tweets into event dicts."""
        seen_ids: set[str] = set()
        seen_texts: set[str] = set()
        events: list[dict] = []
        filtered_count = 0

        for tweet in raw_tweets:
            tweet_id = tweet.get("id", "")

            # Deduplicate by ID
            if tweet_id in seen_ids:
                filtered_count += 1
                continue
            seen_ids.add(tweet_id)

            text = tweet.get("text", "")

            # Deduplicate by text (catches multi-account spam)
            text_fingerprint = text.strip().lower()
            if text_fingerprint in seen_texts:
                filtered_count += 1
                continue
            seen_texts.add(text_fingerprint)

            # Spam/bot filtering
            if self._is_spam_tweet(tweet):
                filtered_count += 1
                continue

            event = self._normalize_tweet(tweet)
            if event is not None:
                events.append(event)
            else:
                filtered_count += 1

        if filtered_count:
            logger.info("x_items_filtered", count=filtered_count)

        return events

    def _is_spam_tweet(self, tweet: dict) -> bool:
        """Deterministic spam/bot heuristics. Returns True to reject."""
        text = tweet.get("text", "")

        # Too short
        if len(text.strip()) < _MIN_TEXT_LENGTH:
            return True

        words = text.split()
        if not words:
            return True

        # Too many hashtags relative to content
        hashtag_count = sum(1 for w in words if w.startswith("#"))
        if hashtag_count / len(words) > _MAX_HASHTAG_RATIO:
            return True

        # Too many URLs relative to content
        url_count = sum(1 for w in words if w.startswith("http"))
        if url_count / len(words) > _MAX_URL_RATIO:
            return True

        # Author heuristic: zero followers with high following (likely bot)
        user = tweet.get("_user", {})
        user_metrics = user.get("public_metrics", {})
        followers = user_metrics.get("followers_count", -1)
        following = user_metrics.get("following_count", 0)
        if followers == 0 and following > 100:
            return True

        return False

    def _normalize_tweet(self, tweet: dict) -> dict | None:
        """Convert a tweet into an event dict for the pipeline."""
        text = tweet.get("text", "")
        if not text.strip():
            return None

        # Extract cashtags as anchor terms
        cashtags = _CASHTAG_RE.findall(text)
        cashtag_terms = [ct.upper() for ct in cashtags]

        # Extract hashtags as related terms
        hashtags = _HASHTAG_RE.findall(text)
        hashtag_terms = [ht.upper() for ht in hashtags]

        # Extract general terms (same approach as NewsAPI adapter)
        general_terms = self._extract_terms(text)

        # Build anchor_terms: cashtags first, then top general terms
        anchor_terms = list(dict.fromkeys(cashtag_terms + general_terms[:5]))[:5]
        if not anchor_terms:
            return None  # No usable terms

        # Build related_terms: hashtags + remaining general terms
        related_terms = list(dict.fromkeys(
            hashtag_terms + general_terms[5:10]
        ))[:10]

        # Compute engagement score
        metrics = tweet.get("public_metrics", {})
        engagement = self._compute_engagement_score(metrics)

        # Signal strength: base * engagement multiplier
        signal_strength = min(1.0, self.signal_strength + engagement * 0.5)

        # Timestamp
        created_at = tweet.get("created_at")
        if created_at:
            try:
                published = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                published = datetime.now(timezone.utc)
        else:
            published = datetime.now(timezone.utc)

        # Author
        user = tweet.get("_user", {})
        author = user.get("username", "unknown")
        author_display = f"@{author}"

        # Tweet URL
        tweet_id = tweet.get("id", "")
        url = f"https://x.com/{author}/status/{tweet_id}" if tweet_id else ""

        # Truncated description
        description = text[:120].replace("\n", " ").strip()
        if len(text) > 120:
            description += "..."

        return {
            "anchor_terms": anchor_terms,
            "related_terms": related_terms,
            "description": description,
            "source_type": "social_media",
            "source_name": author_display,
            "signal_strength": round(signal_strength, 3),
            "published_at": published.isoformat(),
            "url": url,
            "raw_text": text,
            "_title": description,
            "_description": "",
            "_source_name": author_display,
            # X-specific metadata
            "entities": {
                "cashtags": cashtag_terms,
                "hashtags": hashtag_terms,
                "urls": [
                    u.get("expanded_url", u.get("url", ""))
                    for u in (tweet.get("entities", {}).get("urls", []))
                ],
            },
            "_engagement_score": round(engagement, 3),
            "_metrics": {
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "replies": metrics.get("reply_count", 0),
            },
        }

    def _compute_engagement_score(self, metrics: dict) -> float:
        """Compute normalised engagement score from tweet public_metrics.

        Uses log-scale to compress viral outliers:
        score = w_rt * log1p(retweets) + w_likes * log1p(likes)
              + w_replies * log1p(replies)
        Normalised against a reference value so typical tweets score 0.0-1.0.
        """
        retweets = max(0, metrics.get("retweet_count", 0))
        likes = max(0, metrics.get("like_count", 0))
        replies = max(0, metrics.get("reply_count", 0))

        raw = (
            _ENGAGEMENT_W_RETWEETS * math.log1p(retweets)
            + _ENGAGEMENT_W_LIKES * math.log1p(likes)
            + _ENGAGEMENT_W_REPLIES * math.log1p(replies)
        )
        return min(1.0, raw / math.log1p(_ENGAGEMENT_NORMALISER))

    def _extract_terms(self, text: str) -> list[str]:
        """Extract significant terms from text (same as NewsAPI adapter)."""
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
            "rt", "via", "like", "just",
        }

        # Strip URLs and mentions before term extraction
        cleaned = re.sub(r"https?://\S+", "", text)
        cleaned = re.sub(r"@\w+", "", cleaned)
        # Strip cashtags/hashtags (already captured separately)
        cleaned = re.sub(r"[$#]\w+", "", cleaned)

        words = cleaned.replace("-", " ").replace("'", "").split()
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

    # ------------------------------------------------------------------
    # Rate-limit handling (same pattern as NewsAPIAdapter)
    # ------------------------------------------------------------------

    def _handle_403(self) -> None:
        """Handle HTTP 403 Forbidden -- authorization/configuration failure.

        403 is NOT retried (handled upstream by retry_fetch predicate) and does
        NOT enter rate-limit cooldown.  It is a permanent signal that the
        bearer token is missing, expired, or lacks Recent Search access.
        """
        self._failure_mode = "forbidden"
        self._mark_unhealthy("HTTP 403 Forbidden")
        logger.warning(
            "x_forbidden",
            hint=(
                "X API returned 403 Forbidden. "
                "Check X_API_BEARER_TOKEN is valid and the app has 'Read' permission "
                "with access to the v2 Recent Search endpoint. "
                "See: https://developer.twitter.com/en/portal/dashboard"
            ),
        )

    def _handle_429(self) -> None:
        """Record a 429 response and enter cooldown."""
        self._consecutive_429s += 1
        self._mark_unhealthy("HTTP 429 Too Many Requests")
        logger.warning(
            "x_rate_limited",
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
                "x_entering_cooldown",
                cooldown_seconds=round(duration, 1),
                cooldown_episode=self._cooldown_episodes,
            )
            self._persist_state(duration_seconds=duration)
        else:
            self._persist_state()

    def _persist_state(
        self,
        duration_seconds: float | None = None,
        cleared: bool = False,
    ) -> None:
        """Write current rate-limit state to disk."""
        if self._persisted is None or not self._state_path:
            return
        self._persisted.consecutive_429s = self._consecutive_429s
        self._persisted.cooldown_episodes = self._cooldown_episodes
        if cleared:
            self._persisted.reset()
        elif duration_seconds is not None:
            self._persisted.enter_cooldown(duration_seconds)
        try:
            self._persisted.save(self._state_path)
        except Exception as exc:
            logger.warning("x_state_persist_failed", error=str(exc))

    async def check_auth(self) -> tuple[bool, str]:
        """Make a minimal API call to verify the bearer token is authorized.

        Returns ``(True, reason)`` when the token is usable (even if
        rate-limited), ``(False, reason)`` when the token is invalid or lacks
        access.  Consumes one API call / one search result.
        """
        if not self.bearer_token:
            return False, "no bearer token configured"
        try:
            client = await self._get_client()
            params = {
                "query": "lang:en -is:retweet",
                "max_results": 1,
                "tweet.fields": "id",
            }
            headers = {"Authorization": f"Bearer {self.bearer_token}"}
            r = await client.get(
                f"{self.base_url}/tweets/search/recent",
                params=params,
                headers=headers,
            )
            r.raise_for_status()
            return True, "authorized"
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code == 429:
                return True, "rate-limited (token is valid)"
            if code == 403:
                return False, "forbidden -- token lacks Recent Search access"
            if code == 401:
                return False, "unauthorized -- token is invalid"
            return False, f"HTTP {code}"
        except Exception as e:
            return False, f"unreachable ({e})"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
