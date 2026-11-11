"""Unit tests for the X (Twitter) API adapter.

Covers:
- Tweet normalisation: cashtag extraction, hashtag extraction, term extraction
- Engagement scoring: log-scale normalisation
- Spam/bot filtering: short text, hashtag ratio, URL ratio, zero-follower bots
- Deduplication: by tweet ID and by text fingerprint
- Rate-limit cooldown: same pattern as NewsAPI (429 handling, persistence)
- Fetch behaviour: cooldown skips, empty bearer token skips
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mctrend.ingestion.adapters.x_api import (
    XAPIAdapter,
    _DISCOVERY_QUERY_POOL,
    _ENGAGEMENT_NORMALISER,
    _build_flat_query_pool,
)
from mctrend.ingestion.adapters.ratelimit_state import RateLimitState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter():
    """Adapter with no bearer token (useful for unit-level processing tests)."""
    return XAPIAdapter(
        bearer_token="test-token",
        cooldown_after=2,
        cooldown_seconds=60.0,
        max_cooldown_seconds=900.0,
    )


def _make_tweet(
    tweet_id: str = "123",
    text: str = "Check out $MOONDOG on Solana! #memecoin #solana",
    retweets: int = 10,
    likes: int = 50,
    replies: int = 5,
    author_id: str = "user1",
    username: str = "crypto_trader",
    followers: int = 500,
    following: int = 100,
    created_at: str = "2025-01-01T12:00:00Z",
) -> dict:
    """Build a minimal tweet dict matching X API v2 format."""
    return {
        "id": tweet_id,
        "text": text,
        "author_id": author_id,
        "created_at": created_at,
        "public_metrics": {
            "retweet_count": retweets,
            "like_count": likes,
            "reply_count": replies,
        },
        "entities": {"urls": []},
        "_user": {
            "id": author_id,
            "username": username,
            "public_metrics": {
                "followers_count": followers,
                "following_count": following,
            },
        },
    }


# ---------------------------------------------------------------------------
# Cashtag extraction
# ---------------------------------------------------------------------------


class TestCashtagExtraction:
    def test_single_cashtag_becomes_anchor_term(self, adapter):
        tweet = _make_tweet(text="Buy $MOONDOG now! Great Solana project")
        event = adapter._normalize_tweet(tweet)
        assert event is not None
        assert "MOONDOG" in event["anchor_terms"]

    def test_multiple_cashtags(self, adapter):
        tweet = _make_tweet(text="$SOL vs $MOONDOG battle on pump.fun")
        event = adapter._normalize_tweet(tweet)
        assert "SOL" in event["anchor_terms"]
        assert "MOONDOG" in event["anchor_terms"]

    def test_cashtag_case_normalised_to_upper(self, adapter):
        tweet = _make_tweet(text="$moonDog is the next big thing")
        event = adapter._normalize_tweet(tweet)
        assert "MOONDOG" in event["anchor_terms"]

    def test_no_cashtag_falls_back_to_general_terms(self, adapter):
        tweet = _make_tweet(text="Solana memecoin launches are crazy today")
        event = adapter._normalize_tweet(tweet)
        assert event is not None
        assert len(event["anchor_terms"]) > 0

    def test_dollar_sign_only_not_extracted(self, adapter):
        tweet = _make_tweet(text="$ is not a cashtag but SOLANA is a term")
        event = adapter._normalize_tweet(tweet)
        # "$" alone should not produce a cashtag
        for term in event.get("anchor_terms", []):
            assert term != ""

    def test_cashtag_in_entities_metadata(self, adapter):
        tweet = _make_tweet(text="$BRAVADO launch $SOL chain")
        event = adapter._normalize_tweet(tweet)
        assert "BRAVADO" in event["entities"]["cashtags"]
        assert "SOL" in event["entities"]["cashtags"]


# ---------------------------------------------------------------------------
# Hashtag extraction → related_terms
# ---------------------------------------------------------------------------


class TestHashtagExtraction:
    def test_hashtags_become_related_terms(self, adapter):
        tweet = _make_tweet(text="$MOONDOG #solana #memecoin #pump")
        event = adapter._normalize_tweet(tweet)
        assert "SOLANA" in event["related_terms"]
        assert "MEMECOIN" in event["related_terms"]

    def test_hashtags_in_entities_metadata(self, adapter):
        tweet = _make_tweet(text="$SOL #DeFi #Solana token")
        event = adapter._normalize_tweet(tweet)
        assert "DEFI" in event["entities"]["hashtags"]
        assert "SOLANA" in event["entities"]["hashtags"]


# ---------------------------------------------------------------------------
# Engagement scoring
# ---------------------------------------------------------------------------


class TestEngagementScoring:
    def test_zero_engagement_scores_zero(self, adapter):
        metrics = {"retweet_count": 0, "like_count": 0, "reply_count": 0}
        score = adapter._compute_engagement_score(metrics)
        assert score == 0.0

    def test_moderate_engagement(self, adapter):
        metrics = {"retweet_count": 3, "like_count": 5, "reply_count": 1}
        score = adapter._compute_engagement_score(metrics)
        assert 0.0 < score < 1.0

    def test_high_engagement_capped_at_one(self, adapter):
        metrics = {"retweet_count": 100000, "like_count": 500000, "reply_count": 50000}
        score = adapter._compute_engagement_score(metrics)
        assert score == 1.0

    def test_engagement_uses_log_scale(self, adapter):
        low = {"retweet_count": 1, "like_count": 1, "reply_count": 1}
        high = {"retweet_count": 100, "like_count": 100, "reply_count": 100}
        score_low = adapter._compute_engagement_score(low)
        score_high = adapter._compute_engagement_score(high)
        # Log scale compresses the difference
        ratio = score_high / score_low if score_low > 0 else float("inf")
        assert ratio < 100, "Log scale should compress 100x engagement difference"

    def test_signal_strength_increases_with_engagement(self, adapter):
        tweet_low = _make_tweet(retweets=0, likes=0, replies=0)
        tweet_high = _make_tweet(retweets=100, likes=500, replies=50)
        event_low = adapter._normalize_tweet(tweet_low)
        event_high = adapter._normalize_tweet(tweet_high)
        assert event_high["signal_strength"] > event_low["signal_strength"]

    def test_signal_strength_capped_at_one(self, adapter):
        tweet = _make_tweet(retweets=999999, likes=999999, replies=999999)
        event = adapter._normalize_tweet(tweet)
        assert event["signal_strength"] <= 1.0

    def test_negative_metrics_treated_as_zero(self, adapter):
        metrics = {"retweet_count": -5, "like_count": -10, "reply_count": -3}
        score = adapter._compute_engagement_score(metrics)
        assert score == 0.0

    def test_missing_metrics_treated_as_zero(self, adapter):
        score = adapter._compute_engagement_score({})
        assert score == 0.0


# ---------------------------------------------------------------------------
# Spam / bot filtering
# ---------------------------------------------------------------------------


class TestSpamFiltering:
    def test_short_text_rejected(self, adapter):
        tweet = _make_tweet(text="Buy now!")
        assert adapter._is_spam_tweet(tweet) is True

    def test_normal_text_passes(self, adapter):
        tweet = _make_tweet(text="$MOONDOG is launching on Solana pump.fun today, exciting!")
        assert adapter._is_spam_tweet(tweet) is False

    def test_too_many_hashtags_rejected(self, adapter):
        tweet = _make_tweet(text="#a #b #c #d #e #f #g #h #i #j real")
        assert adapter._is_spam_tweet(tweet) is True

    def test_too_many_urls_rejected(self, adapter):
        tweet = _make_tweet(
            text="http://a.com http://b.com http://c.com http://d.com check"
        )
        assert adapter._is_spam_tweet(tweet) is True

    def test_zero_follower_bot_rejected(self, adapter):
        tweet = _make_tweet(text="Amazing $SOL token launch today on Solana!", followers=0, following=200)
        assert adapter._is_spam_tweet(tweet) is True

    def test_zero_follower_low_following_passes(self, adapter):
        tweet = _make_tweet(
            text="Just discovered $MOONDOG on Solana today!", followers=0, following=10
        )
        assert adapter._is_spam_tweet(tweet) is False

    def test_empty_text_rejected(self, adapter):
        tweet = _make_tweet(text="")
        assert adapter._is_spam_tweet(tweet) is True


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_duplicate_tweet_id_filtered(self, adapter):
        tweets = [
            _make_tweet(tweet_id="111", text="$SOL is pumping on Solana network!"),
            _make_tweet(tweet_id="111", text="$SOL is pumping on Solana network!"),
        ]
        events = adapter._process_tweets(tweets)
        assert len(events) == 1

    def test_duplicate_text_different_ids_filtered(self, adapter):
        tweets = [
            _make_tweet(tweet_id="111", text="$MOONDOG launch on pump.fun Solana", username="user_a"),
            _make_tweet(tweet_id="222", text="$MOONDOG launch on pump.fun Solana", username="user_b"),
        ]
        events = adapter._process_tweets(tweets)
        assert len(events) == 1

    def test_different_tweets_both_kept(self, adapter):
        tweets = [
            _make_tweet(tweet_id="111", text="$SOL pumping today on the Solana chain!"),
            _make_tweet(tweet_id="222", text="$MOONDOG new launch on pump.fun Solana"),
        ]
        events = adapter._process_tweets(tweets)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# Tweet normalisation output format
# ---------------------------------------------------------------------------


class TestNormalisationOutput:
    def test_output_has_required_fields(self, adapter):
        tweet = _make_tweet()
        event = adapter._normalize_tweet(tweet)
        assert event is not None
        required = [
            "anchor_terms", "related_terms", "description", "source_type",
            "source_name", "signal_strength", "published_at", "url",
            "raw_text", "_title", "_description", "_source_name",
        ]
        for field in required:
            assert field in event, f"Missing field: {field}"

    def test_source_type_is_social_media(self, adapter):
        tweet = _make_tweet()
        event = adapter._normalize_tweet(tweet)
        assert event["source_type"] == "social_media"

    def test_source_name_has_at_prefix(self, adapter):
        tweet = _make_tweet(username="degen_trader")
        event = adapter._normalize_tweet(tweet)
        assert event["source_name"] == "@degen_trader"

    def test_description_truncated_at_120(self, adapter):
        long_text = "A" * 200
        tweet = _make_tweet(text=f"$SOL {long_text}")
        event = adapter._normalize_tweet(tweet)
        assert len(event["description"]) <= 124  # 120 + "..."

    def test_url_format(self, adapter):
        tweet = _make_tweet(tweet_id="456", username="trader")
        event = adapter._normalize_tweet(tweet)
        assert event["url"] == "https://x.com/trader/status/456"

    def test_empty_text_returns_none(self, adapter):
        tweet = _make_tweet(text="   ")
        event = adapter._normalize_tweet(tweet)
        assert event is None

    def test_no_usable_terms_returns_none(self, adapter):
        # Only stop words
        tweet = _make_tweet(text="the is are was were been being have has")
        event = adapter._normalize_tweet(tweet)
        assert event is None

    def test_published_at_parsed_from_created_at(self, adapter):
        tweet = _make_tweet(created_at="2025-06-15T08:30:00Z")
        event = adapter._normalize_tweet(tweet)
        parsed = datetime.fromisoformat(event["published_at"])
        assert parsed.year == 2025
        assert parsed.month == 6

    def test_engagement_metadata_preserved(self, adapter):
        tweet = _make_tweet(retweets=10, likes=50, replies=5)
        event = adapter._normalize_tweet(tweet)
        assert "_engagement_score" in event
        assert event["_metrics"]["likes"] == 50
        assert event["_metrics"]["retweets"] == 10
        assert event["_metrics"]["replies"] == 5


# ---------------------------------------------------------------------------
# Rate-limit cooldown
# ---------------------------------------------------------------------------


class TestXCooldown:
    def test_not_in_cooldown_initially(self, adapter):
        assert not adapter.is_in_cooldown()

    def test_single_429_does_not_trigger_cooldown(self, adapter):
        adapter._consecutive_429s = 0
        adapter._handle_429()
        assert not adapter.is_in_cooldown()

    def test_second_429_enters_cooldown(self, adapter):
        adapter._consecutive_429s = 1
        adapter._handle_429()
        assert adapter.is_in_cooldown()

    def test_cooldown_duration_doubles_per_episode(self, adapter):
        # Episode 1
        adapter._consecutive_429s = 1
        adapter._handle_429()
        first_until = adapter._cooldown_until
        first_remaining = first_until - time.monotonic()

        # Reset for episode 2
        adapter._cooldown_until = 0.0
        adapter._consecutive_429s = 1
        adapter._handle_429()
        second_until = adapter._cooldown_until
        second_remaining = second_until - time.monotonic()

        assert second_remaining > first_remaining * 1.5  # roughly 2x

    def test_cooldown_capped_at_max(self, adapter):
        adapter._cooldown_episodes = 10  # Many episodes → would exceed max
        adapter._consecutive_429s = 1
        adapter._handle_429()
        remaining = adapter._cooldown_until - time.monotonic()
        assert remaining <= adapter._max_cooldown_seconds + 1.0

    def test_get_source_meta_includes_cooldown_info(self, adapter):
        meta = adapter.get_source_meta()
        assert "in_rate_limit_cooldown" in meta
        assert "consecutive_429s" in meta
        assert "cooldown_remaining_seconds" in meta
        assert "cooldown_episodes" in meta


# ---------------------------------------------------------------------------
# Fetch behaviour
# ---------------------------------------------------------------------------


class TestFetchBehaviour:
    @pytest.mark.asyncio
    async def test_fetch_returns_empty_without_bearer_token(self):
        adapter = XAPIAdapter(bearer_token="")
        result = await adapter.fetch()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_in_cooldown(self, adapter):
        adapter._cooldown_until = time.monotonic() + 300
        with patch.object(adapter, "_get_client") as mock_client:
            result = await adapter.fetch()
        assert result == []
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_processes_api_response(self, adapter):
        api_response = {
            "data": [
                {
                    "id": "t1",
                    "text": "$MOONDOG launching on Solana pump.fun today!",
                    "author_id": "u1",
                    "created_at": "2025-01-01T12:00:00Z",
                    "public_metrics": {
                        "retweet_count": 5,
                        "like_count": 20,
                        "reply_count": 3,
                    },
                    "entities": {"urls": []},
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "u1",
                        "username": "sol_trader",
                        "public_metrics": {
                            "followers_count": 1000,
                            "following_count": 200,
                        },
                    }
                ]
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            events = await adapter.fetch()

        assert len(events) == 1
        assert "MOONDOG" in events[0]["anchor_terms"]
        assert events[0]["source_type"] == "social_media"

    @pytest.mark.asyncio
    async def test_fetch_resets_429_counter_on_success(self, adapter):
        adapter._consecutive_429s = 1

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter._consecutive_429s == 0

    @pytest.mark.asyncio
    async def test_fetch_handles_429_response(self, adapter):
        adapter._consecutive_429s = 1  # One prior 429 → next triggers cooldown
        mock_resp = MagicMock(status_code=429)
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.fetch()

        assert result == []
        assert adapter.is_in_cooldown()

    @pytest.mark.asyncio
    async def test_fetch_respects_max_requests_per_cycle(self):
        adapter = XAPIAdapter(
            bearer_token="test",
            max_requests_per_cycle=2,
            queries_per_cycle=5,
            discovery_categories={"test": ["q1", "q2", "q3", "q4"]},
        )

        call_count = 0

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        async def _counting_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = _counting_get

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert call_count == 2  # max_requests_per_cycle=2


# ---------------------------------------------------------------------------
# Persistent cooldown state
# ---------------------------------------------------------------------------


class TestXPersistentCooldown:
    def test_adapter_restores_cooldown_from_state(self, tmp_path):
        state_path = tmp_path / "x_state.json"
        state = RateLimitState(source_name="x", cooldown_episodes=2)
        state.enter_cooldown(300.0)
        state.save(state_path)

        adapter = XAPIAdapter(
            bearer_token="test",
            state_path=str(state_path),
        )
        assert adapter.is_in_cooldown()
        assert adapter._cooldown_episodes == 2

    def test_adapter_starts_clear_when_cooldown_expired(self, tmp_path):
        state_path = tmp_path / "x_state.json"
        state = RateLimitState(source_name="x", cooldown_episodes=1)
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        state.cooldown_until_utc = past.isoformat()
        state.save(state_path)

        adapter = XAPIAdapter(bearer_token="test", state_path=str(state_path))
        assert not adapter.is_in_cooldown()

    def test_adapter_starts_clear_without_state_file(self, tmp_path):
        state_path = tmp_path / "nonexistent.json"
        adapter = XAPIAdapter(bearer_token="test", state_path=str(state_path))
        assert not adapter.is_in_cooldown()

    @pytest.mark.asyncio
    async def test_429_persists_state(self, tmp_path):
        state_path = tmp_path / "x_state.json"
        adapter = XAPIAdapter(
            bearer_token="test",
            cooldown_after=2,
            cooldown_seconds=60.0,
            state_path=str(state_path),
        )
        adapter._consecutive_429s = 1

        mock_resp = MagicMock(status_code=429)
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert state_path.exists()
        saved = RateLimitState.load(state_path)
        assert saved.is_in_cooldown()

    @pytest.mark.asyncio
    async def test_successful_fetch_clears_state(self, tmp_path):
        state_path = tmp_path / "x_state.json"
        state = RateLimitState(source_name="x", consecutive_429s=2, cooldown_episodes=1)
        state.save(state_path)

        adapter = XAPIAdapter(
            bearer_token="test",
            state_path=str(state_path),
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        saved = RateLimitState.load(state_path)
        assert saved.consecutive_429s == 0
        assert saved.cooldown_until_utc is None


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------


class TestTermExtraction:
    def test_stop_words_removed(self, adapter):
        terms = adapter._extract_terms("the is are have been this that")
        assert len(terms) == 0

    def test_urls_stripped_before_extraction(self, adapter):
        terms = adapter._extract_terms("Check https://example.com/token for more")
        url_terms = [t for t in terms if "HTTPS" in t or "EXAMPLE" in t or "COM" in t]
        assert len(url_terms) == 0

    def test_mentions_stripped(self, adapter):
        terms = adapter._extract_terms("Thanks @crypto_whale for the tip")
        assert "CRYPTO_WHALE" not in terms

    def test_meaningful_terms_extracted(self, adapter):
        terms = adapter._extract_terms("Solana memecoin launch today")
        assert "SOLANA" in terms
        assert "MEMECOIN" in terms
        assert "LAUNCH" in terms

    def test_deduplication(self, adapter):
        terms = adapter._extract_terms("token TOKEN Token different")
        token_count = sum(1 for t in terms if t == "TOKEN")
        assert token_count == 1


# ---------------------------------------------------------------------------
# 403 Forbidden handling
# ---------------------------------------------------------------------------


class TestForbiddenHandling:
    @pytest.mark.asyncio
    async def test_403_returns_empty_without_retry(self, adapter):
        """403 must not be retried — exactly one HTTP call made."""
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=mock_resp)
        call_count = 0

        async def _once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise exc

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = _once

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.fetch()

        assert result == []
        assert call_count == 1, "403 must not be retried"

    @pytest.mark.asyncio
    async def test_403_sets_failure_mode_forbidden(self, adapter):
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter._failure_mode == "forbidden"

    @pytest.mark.asyncio
    async def test_403_does_not_enter_cooldown(self, adapter):
        """403 is a config failure, not a rate limit — must not enter cooldown."""
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter.is_in_cooldown() is False

    @pytest.mark.asyncio
    async def test_403_marks_source_unhealthy(self, adapter):
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter.is_healthy() is False

    @pytest.mark.asyncio
    async def test_failure_mode_in_source_meta_after_403(self, adapter):
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        meta = adapter.get_source_meta()
        assert "failure_mode" in meta
        assert meta["failure_mode"] == "forbidden"

    @pytest.mark.asyncio
    async def test_failure_mode_healthy_initially(self, adapter):
        meta = adapter.get_source_meta()
        assert meta["failure_mode"] == "healthy"

    @pytest.mark.asyncio
    async def test_failure_mode_resets_to_healthy_after_recovery(self, adapter):
        """After a successful fetch, failure_mode must reset to 'healthy'."""
        # Simulate a prior 403
        adapter._failure_mode = "forbidden"
        adapter._healthy = False

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter._failure_mode == "healthy"
        assert adapter.is_healthy() is True

    @pytest.mark.asyncio
    async def test_200_empty_data_marks_healthy(self, adapter):
        """200 response with empty data list should still mark source as healthy."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.fetch()

        assert result == []
        assert adapter.is_healthy() is True
        assert adapter._failure_mode == "healthy"

    @pytest.mark.asyncio
    async def test_failure_mode_rate_limited_when_in_cooldown(self, adapter):
        """When in cooldown, get_source_meta() must report failure_mode='rate-limited'."""
        adapter._consecutive_429s = 1
        adapter._handle_429()  # triggers cooldown (threshold=2 reached with pre-seed)
        # pre-seed was _consecutive_429s=1, handle_429 increments to 2 → cooldown
        meta = adapter.get_source_meta()
        assert meta["failure_mode"] == "rate-limited"


# ---------------------------------------------------------------------------
# Discovery query pool and rotation
# ---------------------------------------------------------------------------


class TestDiscoveryQueryPool:
    def test_default_pool_has_multiple_categories(self):
        assert len(_DISCOVERY_QUERY_POOL) >= 4
        for cat, queries in _DISCOVERY_QUERY_POOL.items():
            assert len(queries) >= 1, f"Category '{cat}' is empty"

    def test_build_flat_query_pool(self):
        pool = _build_flat_query_pool()
        total = sum(len(qs) for qs in _DISCOVERY_QUERY_POOL.values())
        assert len(pool) == total

    def test_custom_categories(self):
        custom = {"test": ["q1", "q2"], "other": ["q3"]}
        pool = _build_flat_query_pool(custom)
        assert pool == ["q1", "q2", "q3"]

    def test_no_hardcoded_crypto_keywords_in_defaults(self):
        """Discovery pool should NOT contain narrow crypto search phrases."""
        pool = _build_flat_query_pool()
        narrow = [
            "solana memecoin launch",
            "pump.fun token",
            "$SOL token launch",
            "solana token CA",
        ]
        for q in pool:
            assert q not in narrow, f"Narrow crypto query still in pool: {q}"


class TestQueryRotation:
    def test_rotation_selects_correct_count(self):
        adapter = XAPIAdapter(
            bearer_token="test",
            discovery_categories={"a": ["q1", "q2", "q3", "q4", "q5"]},
            queries_per_cycle=3,
        )
        selected = adapter._select_queries_for_cycle()
        assert len(selected) == 3

    def test_rotation_advances_each_cycle(self):
        adapter = XAPIAdapter(
            bearer_token="test",
            discovery_categories={"a": ["q1", "q2", "q3", "q4", "q5"]},
            queries_per_cycle=2,
        )
        batch1 = adapter._select_queries_for_cycle()
        batch2 = adapter._select_queries_for_cycle()
        assert batch1 != batch2, "Successive cycles should use different queries"

    def test_rotation_wraps_around(self):
        adapter = XAPIAdapter(
            bearer_token="test",
            discovery_categories={"a": ["q1", "q2", "q3"]},
            queries_per_cycle=2,
        )
        # Cycle 1: q1, q2
        batch1 = adapter._select_queries_for_cycle()
        assert batch1 == ["q1", "q2"]
        # Cycle 2: q3, q1 (wraps)
        batch2 = adapter._select_queries_for_cycle()
        assert batch2 == ["q3", "q1"]

    def test_queries_per_cycle_capped_by_pool_size(self):
        adapter = XAPIAdapter(
            bearer_token="test",
            discovery_categories={"a": ["q1", "q2"]},
            queries_per_cycle=10,
        )
        selected = adapter._select_queries_for_cycle()
        assert len(selected) == 2

    def test_empty_pool_returns_empty(self):
        adapter = XAPIAdapter(
            bearer_token="test",
            discovery_categories={"a": []},
            queries_per_cycle=5,
        )
        selected = adapter._select_queries_for_cycle()
        assert selected == []

    def test_adapter_no_longer_accepts_query_terms(self):
        """The old query_terms parameter must not be accepted."""
        import inspect
        sig = inspect.signature(XAPIAdapter.__init__)
        assert "query_terms" not in sig.parameters
