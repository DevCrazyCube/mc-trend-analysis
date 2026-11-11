"""PumpPortal WebSocket adapter — real-time token discovery.

Connects to wss://pumpportal.fun/api/data and subscribes to new token
creation events via the documented ``subscribeNewToken`` method.

The adapter runs as a background asyncio task. The pipeline calls
``fetch()`` each cycle to drain buffered events from the queue.

Reference:
  https://pumpportal.fun/data-api/real-time-data
  One connection, multiplex all subscriptions on it.

Design:
  - Exponential backoff reconnect: 1s → 2s → 4s → 8s → 16s → 32s → 60s cap
  - Stale-stream detection: if no message arrives within STALE_TIMEOUT, reconnect
  - Health exposed via get_source_meta() for dashboard
  - Non-functional stream is reported honestly in source status
"""

import asyncio
import json
import time
from datetime import datetime, timezone

import structlog

from .base import SourceAdapter

logger = structlog.get_logger(__name__)

_WS_URL = "wss://pumpportal.fun/api/data"
_SUBSCRIBE_MSG = {"method": "subscribeNewToken"}
_DEFAULT_STALE_TIMEOUT = 120.0   # seconds without a message before reconnect
_MAX_BACKOFF = 60.0               # maximum reconnect delay in seconds


class PumpPortalWebSocketAdapter(SourceAdapter):
    """Real-time token discovery via PumpPortal WebSocket.

    Usage in build_system():
        adapter = PumpPortalWebSocketAdapter()
        ingestion.register_token_adapter(adapter)
        adapter.start_background_task()   # call once after event loop is running

    The pipeline calls fetch() each cycle; it drains whatever arrived since
    the last call.  If the stream is down, fetch() returns an empty list and
    source health reflects the failure — never raises.
    """

    SUPPORTED = True

    def __init__(
        self,
        ws_url: str = _WS_URL,
        stale_timeout_seconds: float = _DEFAULT_STALE_TIMEOUT,
        queue_maxsize: int = 2000,
    ):
        super().__init__(
            source_name="pumpportal_ws",
            source_type="token_launch_platform",
        )
        self._ws_url = ws_url
        self._stale_timeout = stale_timeout_seconds
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task | None = None
        self._running = False

        # Health tracking beyond the base class
        self._ws_connected = False
        self._reconnect_count = 0
        self._total_events_received = 0
        self._last_message_at: float | None = None
        self._last_error: str | None = None
        self._started_at: float | None = None

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def start_background_task(self) -> asyncio.Task:
        """Start the background WebSocket listener. Call once after loop starts."""
        if self._task is not None and not self._task.done():
            return self._task
        self._running = True
        self._started_at = time.time()
        self._task = asyncio.create_task(self._run_forever(), name="pumpportal_ws")
        logger.info("pumpportal_ws_task_started", url=self._ws_url)
        return self._task

    async def stop(self):
        """Cancel the background task and drain the queue."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._ws_connected = False
        logger.info("pumpportal_ws_task_stopped")

    async def fetch(self) -> list[dict]:
        """Drain the event queue — return all buffered token events.

        Called by IngestionManager each cycle. Never raises.
        """
        tokens = []
        try:
            while True:
                tokens.append(self._queue.get_nowait())
        except asyncio.QueueEmpty:
            pass

        if tokens:
            self._mark_healthy()
            logger.info("pumpportal_ws_drained", count=len(tokens))
        return tokens

    def get_source_meta(self) -> dict:
        """Extended health metadata for dashboard display."""
        meta = super().get_source_meta()
        seconds_since = (
            round(time.time() - self._last_message_at, 1)
            if self._last_message_at is not None
            else None
        )
        meta.update({
            "ws_connected": self._ws_connected,
            "reconnect_count": self._reconnect_count,
            "total_events_received": self._total_events_received,
            "seconds_since_last_message": seconds_since,
            "queue_depth": self._queue.qsize(),
            "last_error": self._last_error,
            "ws_url": self._ws_url,
        })
        return meta

    # -----------------------------------------------------------------------
    # Background task
    # -----------------------------------------------------------------------

    async def _run_forever(self):
        """Reconnect loop — keeps running until stop() is called."""
        backoff = 1.0
        while self._running:
            try:
                await self._connect_and_stream()
                # Clean disconnect — reset backoff
                backoff = 1.0
            except asyncio.CancelledError:
                logger.info("pumpportal_ws_cancelled")
                break
            except Exception as exc:
                self._last_error = str(exc)
                self._ws_connected = False
                self._mark_unhealthy(str(exc))
                logger.warning(
                    "pumpportal_ws_disconnected",
                    error=str(exc),
                    reconnect_in_seconds=backoff,
                )

            if not self._running:
                break

            await asyncio.sleep(backoff)
            self._reconnect_count += 1
            backoff = min(backoff * 2, _MAX_BACKOFF)

        self._ws_connected = False

    async def _connect_and_stream(self):
        """Single connection lifetime: connect → subscribe → read until closed/stale."""
        import websockets  # import here so package absence gives a clear error at runtime

        logger.info("pumpportal_ws_connecting", url=self._ws_url)

        async with websockets.connect(
            self._ws_url,
            ping_interval=20,
            ping_timeout=15,
            close_timeout=5,
        ) as ws:
            self._ws_connected = True
            self._last_message_at = time.time()
            logger.info("pumpportal_ws_connected")

            # Subscribe immediately after connect
            await ws.send(json.dumps(_SUBSCRIBE_MSG))
            logger.info("pumpportal_ws_subscribed", method=_SUBSCRIBE_MSG["method"])

            while self._running:
                # Stale-stream check
                if self._last_message_at is not None:
                    elapsed = time.time() - self._last_message_at
                    if elapsed > self._stale_timeout:
                        logger.warning(
                            "pumpportal_ws_stale_stream",
                            seconds_elapsed=round(elapsed, 1),
                        )
                        raise TimeoutError(
                            f"No message for {elapsed:.0f}s — assuming stale stream"
                        )

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                except asyncio.TimeoutError:
                    # No message in 10s — loop back to stale check
                    continue

                self._last_message_at = time.time()
                self._total_events_received += 1

                try:
                    data = json.loads(raw)
                    token = self._parse_event(data)
                    if token is not None:
                        try:
                            self._queue.put_nowait(token)
                        except asyncio.QueueFull:
                            logger.warning("pumpportal_ws_queue_full",
                                           queue_size=self._queue.qsize())
                            # Drop oldest to make room
                            try:
                                self._queue.get_nowait()
                                self._queue.put_nowait(token)
                            except asyncio.QueueEmpty:
                                pass
                except json.JSONDecodeError:
                    logger.debug("pumpportal_ws_non_json_message",
                                 preview=str(raw)[:100])
                except Exception as parse_exc:
                    logger.warning("pumpportal_ws_parse_error",
                                   error=str(parse_exc),
                                   preview=str(raw)[:200])

        self._ws_connected = False

    def _parse_event(self, data: dict) -> dict | None:
        """Parse a PumpPortal subscribeNewToken event into the raw token shape.

        PumpPortal event schema (from docs):
        {
            "mint": "...",
            "name": "Token Name",
            "symbol": "SYM",
            "description": "...",
            "uri": "...",
            "traderPublicKey": "...",
            "initialBuy": 0.0,
            "bondingCurveKey": "...",
            "vSolInBondingCurve": ...,
            "vTokensInBondingCurve": ...,
            "marketCapSol": ...,
        }

        Returns None if the event is not a usable token creation event.
        """
        if not isinstance(data, dict):
            return None

        # Subscription acknowledgements and other control messages
        if "error" in data:
            logger.warning("pumpportal_ws_server_error", msg=data.get("error"))
            return None

        mint = data.get("mint") or data.get("address")
        name = (data.get("name") or "").strip()

        if not mint or not name:
            # Not a token creation event (may be subscription ack etc.)
            return None

        deployer = (
            data.get("traderPublicKey")
            or data.get("creator")
            or data.get("deployer")
            or "unknown"
        )

        # Market cap in SOL → rough USD approximation is not available here;
        # leave initial_liquidity_usd as None (data_gap).  The Solana RPC
        # enrichment pass will fill in chain data later.
        market_cap_sol = data.get("marketCapSol")

        return {
            "address": mint,
            "name": name,
            "symbol": (data.get("symbol") or name[:10]).strip(),
            "description": data.get("description"),
            "deployed_by": deployer,
            "launch_time": datetime.now(timezone.utc).isoformat(),
            "launch_platform": "pump.fun",
            "initial_liquidity_usd": None,   # data gap — enriched by SolanaRPC
            "initial_holder_count": None,    # data gap
            "market_cap_sol": market_cap_sol,
            "bonding_curve_key": data.get("bondingCurveKey"),
            "v_sol_in_bonding_curve": data.get("vSolInBondingCurve"),
            "data_source": "pumpportal_ws",
            "raw": {k: v for k, v in data.items()
                    if k not in ("description",)},  # keep raw minus large text
        }

    async def close(self):
        """Alias for stop() — called by IngestionManager.close_all()."""
        await self.stop()
