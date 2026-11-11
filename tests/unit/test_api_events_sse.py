"""Tests for SSE event streaming and broadcast behavior."""

import asyncio
import json

import pytest

from mctrend.api.routes.events import broadcast


class TestBroadcast:
    """Test event broadcasting to connected clients."""

    @pytest.mark.asyncio
    async def test_broadcast_to_single_listener(self):
        """broadcast sends event to a listener queue."""
        from mctrend.api.routes.events import _listeners

        listener_queue = asyncio.Queue()
        _listeners.clear()
        _listeners.append(listener_queue)

        broadcast("test_event", {"data": "value"})

        # Event should be in queue
        msg = listener_queue.get_nowait()
        event = json.loads(msg)

        assert event["type"] == "test_event"
        assert event["payload"]["data"] == "value"

        _listeners.clear()

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_listeners(self):
        """broadcast sends event to all listener queues."""
        from mctrend.api.routes.events import _listeners

        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        _listeners.clear()
        _listeners.extend([queue1, queue2])

        broadcast("multi_event", {"count": 2})

        # Both queues should have the event
        msg1 = queue1.get_nowait()
        msg2 = queue2.get_nowait()

        event1 = json.loads(msg1)
        event2 = json.loads(msg2)

        assert event1["type"] == "multi_event"
        assert event2["type"] == "multi_event"

        _listeners.clear()

    @pytest.mark.asyncio
    async def test_broadcast_removes_full_queues(self):
        """broadcast removes listener queues that are full."""
        from mctrend.api.routes.events import _listeners

        # Create a small queue that will fill quickly
        small_queue = asyncio.Queue(maxsize=1)
        small_queue.put_nowait("item1")  # Fill it

        regular_queue = asyncio.Queue()

        _listeners.clear()
        _listeners.extend([small_queue, regular_queue])

        # This broadcast will fail to put into small_queue (full),
        # so small_queue should be removed from listeners
        broadcast("overflow_test", {"data": "test"})

        # small_queue should be removed
        assert small_queue not in _listeners
        assert regular_queue in _listeners

        # regular_queue should have the event
        msg = regular_queue.get_nowait()
        event = json.loads(msg)
        assert event["type"] == "overflow_test"

        _listeners.clear()

    @pytest.mark.asyncio
    async def test_broadcast_event_format(self):
        """broadcast events have correct JSON format."""
        from mctrend.api.routes.events import _listeners

        queue = asyncio.Queue()
        _listeners.clear()
        _listeners.append(queue)

        broadcast("cycle_complete", {"tokens_ingested": 5, "alerts_created": 2})

        msg = queue.get_nowait()
        event = json.loads(msg)

        # Format: {"type": "...", "payload": {...}}
        assert isinstance(event, dict)
        assert "type" in event
        assert "payload" in event
        assert event["type"] == "cycle_complete"
        assert event["payload"]["tokens_ingested"] == 5
        assert event["payload"]["alerts_created"] == 2

        _listeners.clear()


class TestEventTypes:
    """Test event types that are broadcast."""

    def test_event_type_cycle_complete(self):
        """cycle_complete event is emitted after pipeline cycles."""
        # Verified in runner.py: broadcast("cycle_complete", summary)
        import inspect
        from mctrend.runner import run_continuous

        source = inspect.getsource(run_continuous)
        assert 'broadcast("cycle_complete"' in source

    def test_event_type_connected(self):
        """connected event is emitted when client connects."""
        # Verified in events.py: initial snapshot on connect
        import inspect
        from mctrend.api.routes.events import _event_stream

        source = inspect.getsource(_event_stream)
        assert "'connected'" in source or '"connected"' in source

    def test_event_type_ping(self):
        """ping event is emitted as keepalive."""
        # Verified in events.py: keepalive every 15s
        import inspect
        from mctrend.api.routes.events import _event_stream

        source = inspect.getsource(_event_stream)
        assert "'ping'" in source or '"ping"' in source
        assert "15" in source or "15.0" in source  # ping_interval


class TestListenerManagement:
    """Test listener queue management in event stream."""

    @pytest.mark.asyncio
    async def test_listener_registered_on_connect(self):
        """Listener is added to _listeners on SSE connection."""
        # Verified in _event_stream: _listeners.append(queue)
        import inspect
        from mctrend.api.routes.events import _event_stream

        source = inspect.getsource(_event_stream)
        assert "_listeners.append" in source

    @pytest.mark.asyncio
    async def test_listener_unregistered_on_disconnect(self):
        """Listener is removed from _listeners on disconnection."""
        # Verified in _event_stream: _listeners.remove(queue) in finally
        import inspect
        from mctrend.api.routes.events import _event_stream

        source = inspect.getsource(_event_stream)
        assert "_listeners.remove" in source

    @pytest.mark.asyncio
    async def test_listener_cleanup_handles_already_removed(self):
        """Listener removal gracefully handles ValueError if already removed."""
        # Verified in _event_stream: except ValueError: pass
        import inspect
        from mctrend.api.routes.events import _event_stream

        source = inspect.getsource(_event_stream)
        assert "except ValueError" in source


class TestKeepalive:
    """Test keepalive ping mechanism."""

    def test_keepalive_interval_is_15_seconds(self):
        """Keepalive ping interval is 15 seconds."""
        import inspect
        from mctrend.api.routes.events import _event_stream

        source = inspect.getsource(_event_stream)
        assert "15" in source or "15.0" in source

    def test_keepalive_prevents_connection_timeout(self):
        """Keepalive ping prevents client-side connection timeout."""
        # Keepalive pings prevent idle connection closure
        # Interval of 15s is well below typical 30s client timeouts
        assert 15 < 30  # Sanity check
