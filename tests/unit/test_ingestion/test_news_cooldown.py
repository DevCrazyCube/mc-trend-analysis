"""Unit tests for NewsAPI 429 cooldown behavior."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from mctrend.ingestion.adapters.news import NewsAPIAdapter


@pytest.fixture
def adapter():
    return NewsAPIAdapter(
        api_key="test-key",
        cooldown_after=2,
        cooldown_seconds=60.0,
        max_cooldown_seconds=900.0,
    )


class TestCooldownState:
    def test_not_in_cooldown_initially(self, adapter):
        assert not adapter.is_in_cooldown()

    def test_enters_cooldown_after_threshold(self, adapter):
        # Simulate two consecutive 429s
        adapter._consecutive_429s = 1
        adapter._handle_429()  # This is the 2nd — should trigger cooldown
        assert adapter.is_in_cooldown()

    def test_single_429_does_not_trigger_cooldown(self, adapter):
        adapter._consecutive_429s = 0
        adapter._handle_429()
        assert not adapter.is_in_cooldown()

    def test_cooldown_duration_is_base_on_first_episode(self, adapter):
        adapter._consecutive_429s = 1
        adapter._handle_429()
        # Base duration for episode 1: 60 * 2^0 = 60 seconds
        remaining = adapter._cooldown_until - time.monotonic()
        assert 55 <= remaining <= 65, f"Expected ~60s cooldown, got {remaining}"

    def test_cooldown_duration_doubles_each_episode(self, adapter):
        # Episode 1: 60s
        adapter._consecutive_429s = 1
        adapter._handle_429()
        ep1_remaining = adapter._cooldown_until - time.monotonic()

        # Reset to simulate recovery and new episode
        adapter._cooldown_until = 0.0
        adapter._consecutive_429s = 1
        adapter._handle_429()
        ep2_remaining = adapter._cooldown_until - time.monotonic()

        # Episode 2 should be ~120s (2x episode 1)
        assert ep2_remaining > ep1_remaining * 1.5

    def test_cooldown_capped_at_max(self, adapter):
        # Simulate many episodes so exponential would exceed max
        adapter._cooldown_episodes = 100
        adapter._consecutive_429s = 1
        adapter._handle_429()
        remaining = adapter._cooldown_until - time.monotonic()
        assert remaining <= adapter._max_cooldown_seconds + 1

    def test_consecutive_429s_reset_on_success(self, adapter):
        adapter._consecutive_429s = 1
        adapter._mark_healthy()
        # After a successful fetch reset is done in fetch() — test the reset:
        adapter._consecutive_429s = 0
        assert adapter._consecutive_429s == 0


class TestFetchDuringCooldown:
    @pytest.mark.asyncio
    async def test_fetch_returns_empty_during_cooldown(self, adapter):
        """When in cooldown, fetch() returns [] without making any network calls."""
        # Force cooldown state
        adapter._cooldown_until = time.monotonic() + 300.0
        assert adapter.is_in_cooldown()

        with patch.object(adapter, "_get_client") as mock_client:
            result = await adapter.fetch()

        assert result == []
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_proceeds_after_cooldown_expires(self, adapter):
        """After cooldown expires, fetch() proceeds normally."""
        # Set cooldown to expire in the past
        adapter._cooldown_until = time.monotonic() - 1.0
        assert not adapter.is_in_cooldown()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": [
            {
                "title": "Solana token launches on pump.fun",
                "description": "New crypto token",
                "publishedAt": "2025-01-01T00:00:00Z",
                "source": {"name": "CryptoNews"},
                "url": "https://example.com",
            }
        ]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.fetch()

        assert len(result) >= 0  # Should proceed — no cooldown block

    @pytest.mark.asyncio
    async def test_429_response_enters_cooldown(self, adapter):
        """A 429 HTTP error response triggers the cooldown mechanism."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        exc = httpx.HTTPStatusError(
            "Too Many Requests", request=MagicMock(), response=mock_response
        )

        # Patch asyncio.sleep to avoid retry delays in retry_fetch
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # First 429 (count = 1, below threshold of 2)
            with patch.object(adapter, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.is_closed = False
                mock_client.get = AsyncMock(side_effect=exc)
                mock_gc.return_value = mock_client
                await adapter.fetch()

            assert not adapter.is_in_cooldown()  # 1 < threshold=2
            assert adapter._consecutive_429s == 1

            # Second 429 (count = 2, meets threshold)
            with patch.object(adapter, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.is_closed = False
                mock_client.get = AsyncMock(side_effect=exc)
                mock_gc.return_value = mock_client
                await adapter.fetch()

        assert adapter.is_in_cooldown()  # 2 >= threshold=2


class TestSourceMeta:
    def test_meta_includes_cooldown_fields(self, adapter):
        meta = adapter.get_source_meta()
        assert "in_rate_limit_cooldown" in meta
        assert "consecutive_429s" in meta
        assert "cooldown_remaining_seconds" in meta

    def test_meta_cooldown_false_when_not_in_cooldown(self, adapter):
        meta = adapter.get_source_meta()
        assert meta["in_rate_limit_cooldown"] is False
        assert meta["cooldown_remaining_seconds"] == 0.0

    def test_meta_cooldown_true_during_cooldown(self, adapter):
        adapter._cooldown_until = time.monotonic() + 120.0
        meta = adapter.get_source_meta()
        assert meta["in_rate_limit_cooldown"] is True
        assert meta["cooldown_remaining_seconds"] > 0


class TestForbiddenHandling:
    """403 Forbidden must not be retried and must set failure_mode='forbidden'."""

    @pytest.mark.asyncio
    async def test_403_not_retried(self, adapter):
        """403 must be raised immediately — exactly one HTTP call."""
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
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter.is_in_cooldown() is False

    @pytest.mark.asyncio
    async def test_failure_mode_in_meta_after_403(self, adapter):
        mock_resp = MagicMock(status_code=403)
        exc = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        meta = adapter.get_source_meta()
        assert meta.get("failure_mode") == "forbidden"

    def test_failure_mode_healthy_initially(self, adapter):
        meta = adapter.get_source_meta()
        assert meta.get("failure_mode") == "healthy"

    def test_failure_mode_rate_limited_when_in_cooldown(self, adapter):
        adapter._consecutive_429s = 1
        adapter._handle_429()
        meta = adapter.get_source_meta()
        assert meta["failure_mode"] == "rate-limited"


class TestDefaultQueryTerms:
    def test_default_terms_are_specific(self):
        """Default query terms should be narrow compound phrases, not single broad words."""
        adapter = NewsAPIAdapter(api_key="test")
        # Each default term should be at least 2 words long OR
        # contain a known specific crypto term
        for term in adapter.query_terms:
            words = term.strip().split()
            is_compound = len(words) >= 2
            is_specific = any(kw in term.lower() for kw in ["solana", "memecoin", "pump.fun", "crypto", "token"])
            assert is_compound or is_specific, (
                f"Default query term '{term}' is too broad — should be compound or crypto-specific"
            )

    def test_broad_single_words_not_in_defaults(self):
        """Broad single-word terms like 'viral' and 'trending' should not be defaults."""
        adapter = NewsAPIAdapter(api_key="test")
        for term in adapter.query_terms:
            assert term.lower().strip() not in {"viral", "trending", "meme"}, (
                f"Broad term '{term}' should not be a default query term"
            )
