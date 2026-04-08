"""Tests for persistent rate-limit state and startup cooldown restoration.

Covers:
- RateLimitState save/load round-trip
- Cooldown survives restart (deadline still in future → adapter starts in cooldown)
- Expired cooldown allows fetch (deadline in past → adapter starts unblocked)
- 429 response immediately enters cooldown (no same-cycle retries)
- Successful fetch clears persisted state
- retry_fetch does not retry on 429 (non-retryable policy)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mctrend.ingestion.adapters.ratelimit_state import RateLimitState
from mctrend.ingestion.adapters.news import NewsAPIAdapter
from mctrend.ingestion.adapters.base import retry_fetch


# ---------------------------------------------------------------------------
# RateLimitState unit tests
# ---------------------------------------------------------------------------


class TestRateLimitStatePersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        path = tmp_path / "state.json"
        state = RateLimitState(
            source_name="newsapi",
            consecutive_429s=2,
            cooldown_episodes=1,
        )
        state.enter_cooldown(300.0)
        state.save(path)

        loaded = RateLimitState.load(path)
        assert loaded.source_name == "newsapi"
        assert loaded.consecutive_429s == 2
        assert loaded.cooldown_episodes == 1
        assert loaded.cooldown_until_utc is not None

    def test_load_returns_fresh_state_when_file_missing(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        state = RateLimitState.load(path)
        assert state.cooldown_until_utc is None
        assert state.consecutive_429s == 0

    def test_load_returns_fresh_state_on_corrupt_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("not-json!!")
        state = RateLimitState.load(path)
        assert state.cooldown_until_utc is None

    def test_cooldown_remaining_positive_when_deadline_future(self):
        state = RateLimitState(source_name="newsapi")
        state.enter_cooldown(300.0)
        assert state.cooldown_remaining_seconds() > 290.0

    def test_cooldown_remaining_zero_when_deadline_past(self):
        state = RateLimitState(source_name="newsapi")
        past_dt = datetime.now(timezone.utc) - timedelta(seconds=5)
        state.cooldown_until_utc = past_dt.isoformat()
        assert state.cooldown_remaining_seconds() == 0.0

    def test_is_in_cooldown_true_when_deadline_future(self):
        state = RateLimitState(source_name="newsapi")
        state.enter_cooldown(120.0)
        assert state.is_in_cooldown()

    def test_is_in_cooldown_false_when_no_deadline(self):
        state = RateLimitState(source_name="newsapi")
        assert not state.is_in_cooldown()

    def test_reset_clears_cooldown_preserves_episodes(self):
        state = RateLimitState(source_name="newsapi", cooldown_episodes=3)
        state.enter_cooldown(60.0)
        state.consecutive_429s = 2
        state.reset()
        assert state.cooldown_until_utc is None
        assert state.consecutive_429s == 0
        assert state.last_429_at is None
        # Episodes are historical — not cleared on reset
        assert state.cooldown_episodes == 3

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "state.json"
        state = RateLimitState(source_name="newsapi")
        state.save(path)
        assert path.exists()


# ---------------------------------------------------------------------------
# NewsAPIAdapter startup cooldown restoration
# ---------------------------------------------------------------------------


class TestCooldownRestoredOnStartup:
    def test_adapter_starts_in_cooldown_when_state_has_future_deadline(self, tmp_path):
        """If the persisted state shows cooldown is still active, adapter starts blocked."""
        state_path = tmp_path / "state.json"
        state = RateLimitState(source_name="newsapi", cooldown_episodes=1)
        state.enter_cooldown(300.0)  # 5 minutes remaining
        state.save(state_path)

        adapter = NewsAPIAdapter(api_key="test-key", state_path=str(state_path))
        assert adapter.is_in_cooldown(), "Adapter should be in cooldown from persisted state"
        remaining = adapter._cooldown_until - time.monotonic()
        assert remaining > 290, f"Expected >290s remaining, got {remaining:.1f}"

    def test_adapter_starts_clear_when_state_has_expired_deadline(self, tmp_path):
        """If persisted cooldown has expired, adapter starts unblocked."""
        state_path = tmp_path / "state.json"
        state = RateLimitState(source_name="newsapi", cooldown_episodes=1)
        # Set a deadline that is already in the past
        past_dt = datetime.now(timezone.utc) - timedelta(seconds=10)
        state.cooldown_until_utc = past_dt.isoformat()
        state.save(state_path)

        adapter = NewsAPIAdapter(api_key="test-key", state_path=str(state_path))
        assert not adapter.is_in_cooldown(), "Adapter should not be in cooldown (deadline expired)"

    def test_adapter_starts_clear_when_no_state_file(self, tmp_path):
        """No state file → adapter starts fresh."""
        state_path = tmp_path / "nonexistent.json"
        adapter = NewsAPIAdapter(api_key="test-key", state_path=str(state_path))
        assert not adapter.is_in_cooldown()

    def test_adapter_starts_clear_when_state_path_is_none(self):
        """state_path=None disables persistence; adapter always starts fresh."""
        adapter = NewsAPIAdapter(api_key="test-key", state_path=None)
        assert not adapter.is_in_cooldown()

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_cooldown_restored(self, tmp_path):
        """Fetch must not make HTTP calls when cooldown was restored from state file."""
        state_path = tmp_path / "state.json"
        state = RateLimitState(source_name="newsapi", cooldown_episodes=1)
        state.enter_cooldown(300.0)
        state.save(state_path)

        adapter = NewsAPIAdapter(api_key="test-key", state_path=str(state_path))
        with patch.object(adapter, "_get_client") as mock_client:
            result = await adapter.fetch()

        assert result == []
        mock_client.assert_not_called()

    def test_restored_cooldown_episodes_preserved(self, tmp_path):
        """Cooldown episode count is restored so backoff continues correctly."""
        state_path = tmp_path / "state.json"
        state = RateLimitState(
            source_name="newsapi",
            cooldown_episodes=3,
            consecutive_429s=2,
        )
        state.enter_cooldown(60.0)
        state.save(state_path)

        adapter = NewsAPIAdapter(api_key="test-key", state_path=str(state_path))
        assert adapter._cooldown_episodes == 3
        assert adapter._consecutive_429s == 2


# ---------------------------------------------------------------------------
# 429 handling: immediate cooldown, state persisted
# ---------------------------------------------------------------------------


class TestImmediateCooldownOn429:
    @pytest.mark.asyncio
    async def test_single_429_does_not_trigger_cooldown_at_threshold_2(self, tmp_path):
        """First 429 increments counter but does not enter cooldown (threshold=2)."""
        state_path = tmp_path / "state.json"
        adapter = NewsAPIAdapter(
            api_key="test-key",
            cooldown_after=2,
            cooldown_seconds=60.0,
            state_path=str(state_path),
        )
        mock_resp = MagicMock(status_code=429)
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter._consecutive_429s == 1
        assert not adapter.is_in_cooldown()

    @pytest.mark.asyncio
    async def test_second_429_enters_cooldown_immediately(self, tmp_path):
        """Second consecutive 429 enters cooldown on the same cycle."""
        state_path = tmp_path / "state.json"
        adapter = NewsAPIAdapter(
            api_key="test-key",
            cooldown_after=2,
            cooldown_seconds=60.0,
            state_path=str(state_path),
        )
        adapter._consecutive_429s = 1  # Pre-seed: one prior 429
        mock_resp = MagicMock(status_code=429)
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(side_effect=exc)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.fetch()

        assert adapter.is_in_cooldown()

    @pytest.mark.asyncio
    async def test_429_state_persisted_to_disk(self, tmp_path):
        """When cooldown is entered, state is written to the state file."""
        state_path = tmp_path / "state.json"
        adapter = NewsAPIAdapter(
            api_key="test-key",
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

        assert state_path.exists(), "State file must be written when cooldown is entered"
        saved = RateLimitState.load(state_path)
        assert saved.is_in_cooldown(), "Persisted state must show active cooldown"

    @pytest.mark.asyncio
    async def test_successful_fetch_clears_persisted_state(self, tmp_path):
        """After a successful fetch, the state file is cleared."""
        state_path = tmp_path / "state.json"
        # Pre-seed with active cooldown state (expired so fetch proceeds)
        state = RateLimitState(source_name="newsapi", cooldown_episodes=1, consecutive_429s=2)
        state.save(state_path)

        adapter = NewsAPIAdapter(
            api_key="test-key",
            cooldown_after=2,
            cooldown_seconds=60.0,
            state_path=str(state_path),
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": []}
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
# retry_fetch: 429 is non-retryable
# ---------------------------------------------------------------------------


class TestRetryFetchNonRetryable429:
    @pytest.mark.asyncio
    async def test_429_raises_immediately_without_retry(self):
        """retry_fetch must re-raise 429 on the first attempt without sleeping."""
        mock_resp = MagicMock(status_code=429)
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)
        call_count = 0

        async def _failing():
            nonlocal call_count
            call_count += 1
            raise exc

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError):
                await retry_fetch(_failing, "newsapi")

        assert call_count == 1, "429 must not be retried — should raise on first attempt"
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_error_is_retried(self):
        """A network/transport error is still retried."""
        call_count = 0

        async def _transient_fail():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.NetworkError("connection reset")
            return ["ok"]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await retry_fetch(_transient_fail, "newsapi", delays=(0.0, 0.0))

        assert call_count == 3
        assert result == ["ok"]

    @pytest.mark.asyncio
    async def test_5xx_error_is_retried(self):
        """HTTP 503 (server error) should be retried."""
        call_count = 0
        mock_resp_503 = MagicMock(status_code=503)
        exc_503 = httpx.HTTPStatusError("503", request=MagicMock(), response=mock_resp_503)

        async def _server_error():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise exc_503
            return ["ok"]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await retry_fetch(_transient_fail := _server_error, "newsapi", delays=(0.0,))

        assert call_count == 2
        assert result == ["ok"]


# ---------------------------------------------------------------------------
# Source gap lifecycle
# ---------------------------------------------------------------------------


class TestSourceGapLifecycle:
    """Tests for single gap per outage period."""

    def _make_adapter(self, source_name="newsapi", source_type="news", healthy=False):
        from mctrend.ingestion.adapters.base import SourceAdapter
        adapter = MagicMock(spec=SourceAdapter)
        adapter.source_name = source_name
        adapter.source_type = source_type
        adapter.is_healthy.return_value = healthy
        return adapter

    def test_gap_created_on_first_failure(self):
        from mctrend.ingestion.manager import IngestionManager
        manager = IngestionManager()
        adapter = self._make_adapter()
        manager._record_source_gap(adapter)
        gaps = manager.get_pending_gaps()
        assert len(gaps) == 1
        assert gaps[0]["source_name"] == "newsapi"

    def test_second_call_same_source_does_not_create_second_gap(self):
        from mctrend.ingestion.manager import IngestionManager
        manager = IngestionManager()
        adapter = self._make_adapter()
        manager._record_source_gap(adapter)
        # Drain the first gap
        manager.get_pending_gaps()
        # Second call during same outage
        manager._record_source_gap(adapter)
        gaps = manager.get_pending_gaps()
        assert gaps == [], "No new gap while source is still in open-gap state"

    def test_gap_can_reopen_after_recovery(self):
        from mctrend.ingestion.manager import IngestionManager
        manager = IngestionManager()
        adapter = self._make_adapter()

        # First outage
        manager._record_source_gap(adapter)
        manager.get_pending_gaps()

        # Source recovers
        manager.mark_source_recovered("newsapi")

        # New outage — a fresh gap should be created
        manager._record_source_gap(adapter)
        gaps = manager.get_pending_gaps()
        assert len(gaps) == 1, "Fresh gap should be created after recovery"

    def test_get_pending_gaps_drains_list(self):
        from mctrend.ingestion.manager import IngestionManager
        manager = IngestionManager()
        adapter = self._make_adapter()
        manager._record_source_gap(adapter)
        first = manager.get_pending_gaps()
        second = manager.get_pending_gaps()
        assert len(first) == 1
        assert second == [], "Gaps must be drained after first get_pending_gaps call"

    def test_different_sources_each_get_own_gap(self):
        from mctrend.ingestion.manager import IngestionManager
        manager = IngestionManager()
        a1 = self._make_adapter("newsapi", "news")
        a2 = self._make_adapter("pumpfun", "token")
        manager._record_source_gap(a1)
        manager._record_source_gap(a2)
        gaps = manager.get_pending_gaps()
        source_names = {g["source_name"] for g in gaps}
        assert source_names == {"newsapi", "pumpfun"}

    def test_repeated_failures_same_source_yield_single_gap(self):
        from mctrend.ingestion.manager import IngestionManager
        manager = IngestionManager()
        adapter = self._make_adapter()
        # Simulate 5 consecutive cycles with source unhealthy
        for _ in range(5):
            manager._record_source_gap(adapter)
        gaps = manager.get_pending_gaps()
        assert len(gaps) == 1, "Only one gap created for an uninterrupted outage"
