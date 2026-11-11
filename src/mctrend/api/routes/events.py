"""Server-Sent Events endpoint for live dashboard updates.

The dashboard subscribes to /api/events/stream and receives a stream of
newline-delimited JSON events as the system runs.  Each event is:

    data: {"type": "...", "payload": {...}}\n\n

Event types:
  cycle_complete   — emitted after each pipeline cycle
  new_token        — emitted when a new token is ingested
  new_alert        — emitted when an alert is created or updated
  source_health    — periodic source health snapshot
  ping             — keepalive every 15s
"""

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from mctrend.api.auth import require_auth
from mctrend.api.deps import get_cycle_stats, get_db, get_ws_adapter

router = APIRouter(prefix="/api/events", tags=["events"])

# Module-level broadcast queue — push events here from outside
_listeners: list[asyncio.Queue] = []


def broadcast(event_type: str, payload: dict):
    """Push an event to all connected SSE clients. Call from anywhere."""
    msg = json.dumps({"type": event_type, "payload": payload})
    dead = []
    for q in _listeners:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _listeners.remove(q)


async def _event_stream(request: Request) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _listeners.append(queue)
    try:
        # Initial snapshot on connect
        stats = get_cycle_stats()
        yield f"data: {json.dumps({'type': 'connected', 'payload': {'cycle_stats': stats}})}\n\n"

        ping_interval = 15.0
        last_ping = time.time()

        while True:
            if await request.is_disconnected():
                break

            try:
                msg = await asyncio.wait_for(queue.get(), timeout=ping_interval)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive ping
                if time.time() - last_ping >= ping_interval:
                    yield f"data: {json.dumps({'type': 'ping', 'payload': {}})}\n\n"
                    last_ping = time.time()
    finally:
        try:
            _listeners.remove(queue)
        except ValueError:
            pass


@router.get("/stream")
async def event_stream(request: Request, _: None = Depends(require_auth)):
    """SSE stream for live dashboard updates."""
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
