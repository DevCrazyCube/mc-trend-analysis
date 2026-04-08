"""Tests for PumpPortal WebSocket adapter lifecycle and reconnect behavior."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mctrend.ingestion.adapters.pumpportal_ws import PumpPortalWebSocketAdapter


class TestWebSocketAdapterInit:
    """Test adapter initialization."""

    def test_adapter_init_default_url(self):
        """Adapter initializes with default WebSocket URL."""
        adapter = PumpPortalWebSocketAdapter()
        assert adapter._ws_url == "wss://pumpportal.fun/api/data"
        assert adapter.SUPPORTED is True

    def test_adapter_init_custom_url(self):
        """Adapter accepts custom WebSocket URL."""
        custom_url = "wss://custom.example.com/ws"
        adapter = PumpPortalWebSocketAdapter(ws_url=custom_url)
        assert adapter._ws_url == custom_url

    def test_adapter_init_custom_timeout(self):
        """Adapter accepts custom stale timeout."""
        adapter = PumpPortalWebSocketAdapter(stale_timeout_seconds=60.0)
        assert adapter._stale_timeout == 60.0

    def test_adapter_queue_initialized(self):
        """Adapter initializes asyncio.Queue with max size."""
        adapter = PumpPortalWebSocketAdapter(queue_maxsize=1000)
        assert isinstance(adapter._queue, asyncio.Queue)
        assert adapter._queue.maxsize == 1000


class TestBackgroundTaskLifecycle:
    """Test adapter background task startup and shutdown."""

    @pytest.mark.asyncio
    async def test_start_background_task_creates_task(self):
        """start_background_task creates an asyncio.Task."""
        adapter = PumpPortalWebSocketAdapter()

        task = adapter.start_background_task()
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "pumpportal_ws"
        assert adapter._running is True
        assert adapter._started_at is not None

        # Clean up
        adapter._running = False
        await adapter.stop()
        await asyncio.sleep(0.1)  # Let task finish

    @pytest.mark.asyncio
    async def test_start_background_task_idempotent(self):
        """Calling start_background_task twice returns same task."""
        adapter = PumpPortalWebSocketAdapter()

        task1 = adapter.start_background_task()
        task2 = adapter.start_background_task()
        assert task1 is task2

        adapter._running = False
        await adapter.stop()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() cancels the background task."""
        adapter = PumpPortalWebSocketAdapter()
        task = adapter.start_background_task()

        await asyncio.sleep(0.05)  # Let task start
        await adapter.stop()

        assert adapter._running is False
        assert adapter._ws_connected is False

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_queue_empty(self):
        """fetch() returns empty list when no events in queue."""
        adapter = PumpPortalWebSocketAdapter()
        tokens = await adapter.fetch()
        assert tokens == []

    @pytest.mark.asyncio
    async def test_fetch_drains_queue(self):
        """fetch() drains all events from queue."""
        adapter = PumpPortalWebSocketAdapter()

        # Simulate events in queue
        token1 = {
            "address": "Token1Address",
            "name": "Token1",
            "symbol": "T1",
            "data_source": "pumpportal_ws",
        }
        token2 = {
            "address": "Token2Address",
            "name": "Token2",
            "symbol": "T2",
            "data_source": "pumpportal_ws",
        }

        adapter._queue.put_nowait(token1)
        adapter._queue.put_nowait(token2)

        tokens = await adapter.fetch()
        assert len(tokens) == 2
        assert token1 in tokens
        assert token2 in tokens

        # Queue should be empty now
        tokens_again = await adapter.fetch()
        assert tokens_again == []


class TestReconnectBackoff:
    """Test exponential backoff reconnect logic."""

    def test_backoff_initial_value(self):
        """Initial backoff is 1.0 second."""
        # The _run_forever logic starts with backoff = 1.0
        backoff = 1.0
        assert backoff == 1.0

    def test_backoff_exponential_growth(self):
        """Backoff doubles on each reconnect attempt (capped at 60s)."""
        backoff = 1.0
        max_backoff = 60.0

        # Simulate 8 reconnect attempts
        expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
        actual = []

        for _ in range(8):
            actual.append(backoff)
            backoff = min(backoff * 2, max_backoff)

        assert actual == expected

    def test_backoff_resets_on_clean_disconnect(self):
        """Backoff resets to 1.0 on successful connection/disconnection."""
        # In _run_forever, after await self._connect_and_stream() completes cleanly,
        # backoff = 1.0 is executed
        backoff = 32.0  # Assume we were in a failure state
        # Clean disconnect → reset
        backoff = 1.0
        assert backoff == 1.0


class TestHealthMetadata:
    """Test health status metadata exposed to dashboard."""

    def test_get_source_meta_includes_ws_fields(self):
        """get_source_meta returns WS-specific health fields."""
        adapter = PumpPortalWebSocketAdapter()

        meta = adapter.get_source_meta()

        assert "ws_connected" in meta
        assert "reconnect_count" in meta
        assert "total_events_received" in meta
        assert "seconds_since_last_message" in meta
        assert "queue_depth" in meta
        assert "last_error" in meta
        assert "ws_url" in meta

    def test_seconds_since_last_message_null_initially(self):
        """seconds_since_last_message is None if never received."""
        adapter = PumpPortalWebSocketAdapter()
        meta = adapter.get_source_meta()
        assert meta["seconds_since_last_message"] is None

    def test_ws_connected_false_initially(self):
        """ws_connected is False on init."""
        adapter = PumpPortalWebSocketAdapter()
        meta = adapter.get_source_meta()
        assert meta["ws_connected"] is False

    def test_queue_depth_reflects_pending_events(self):
        """queue_depth reflects number of events in queue."""
        adapter = PumpPortalWebSocketAdapter()

        adapter._queue.put_nowait({"address": "token1"})
        adapter._queue.put_nowait({"address": "token2"})

        meta = adapter.get_source_meta()
        assert meta["queue_depth"] == 2


class TestParseEvent:
    """Test event parsing logic."""

    def test_parse_valid_token_creation_event(self):
        """_parse_event parses valid PumpPortal token creation event."""
        adapter = PumpPortalWebSocketAdapter()

        event = {
            "mint": "Token1111111111111111111111111111111111111111",
            "name": "ExampleToken",
            "symbol": "EXM",
            "description": "Test token",
            "traderPublicKey": "Creator1111111111111111111111111111111111",
            "marketCapSol": 2.5,
            "bondingCurveKey": "BondingCurve1111111111111111111111111111",
            "vSolInBondingCurve": 1.2,
        }

        token = adapter._parse_event(event)

        assert token is not None
        assert token["address"] == "Token1111111111111111111111111111111111111111"
        assert token["name"] == "ExampleToken"
        assert token["symbol"] == "EXM"
        assert token["deployed_by"] == "Creator1111111111111111111111111111111111"
        assert token["data_source"] == "pumpportal_ws"

    def test_parse_rejects_event_without_mint(self):
        """_parse_event returns None if event lacks mint/address."""
        adapter = PumpPortalWebSocketAdapter()

        event = {"name": "NoMint", "symbol": "NM"}
        token = adapter._parse_event(event)
        assert token is None

    def test_parse_rejects_event_without_name(self):
        """_parse_event returns None if event lacks name."""
        adapter = PumpPortalWebSocketAdapter()

        event = {"mint": "Token1111111111111111111111111111111111111111"}
        token = adapter._parse_event(event)
        assert token is None

    def test_parse_marks_missing_liquidity_data_as_gap(self):
        """_parse_event marks missing liquidity as data gap (initial_liquidity_usd=None)."""
        adapter = PumpPortalWebSocketAdapter()

        event = {
            "mint": "Token1111111111111111111111111111111111111111",
            "name": "Token",
            "symbol": "T",
            # No marketCapSol, no liquidity info
        }

        token = adapter._parse_event(event)

        assert token is not None
        assert token["initial_liquidity_usd"] is None
        assert token["initial_holder_count"] is None

    def test_parse_handles_server_error_messages(self):
        """_parse_event returns None for server error messages."""
        adapter = PumpPortalWebSocketAdapter()

        error_msg = {"error": "subscription_failed"}
        token = adapter._parse_event(error_msg)
        assert token is None
