"""Delivery channel implementations."""

import asyncio
import hashlib
import hmac
import json
import uuid
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from .formatter import format_alert_telegram, format_alert_text, format_alert_json

logger = structlog.get_logger(__name__)

# Retry settings for transient delivery failures
_RETRY_DELAYS = (1.0, 2.0, 4.0)  # seconds between attempts


class DeliveryChannel(ABC):
    """Base class for alert delivery channels."""

    def __init__(self, channel_type: str, channel_id: str):
        self.channel_type = channel_type
        self.channel_id = channel_id

    @abstractmethod
    async def deliver(self, alert: dict) -> dict:
        """
        Deliver an alert. Returns delivery log dict:
        {delivery_id, alert_id, channel_type, channel_id, attempted_at, status, failure_reason}
        """
        ...

    def _make_delivery_log(self, alert_id: str, status: str,
                           failure_reason: str | None = None) -> dict:
        return {
            "delivery_id": str(uuid.uuid4()),
            "alert_id": alert_id,
            "channel_type": self.channel_type,
            "channel_id": self.channel_id,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "failure_reason": failure_reason,
        }


class ConsoleChannel(DeliveryChannel):
    """Deliver alerts to console/stdout."""

    def __init__(self):
        super().__init__(channel_type="console", channel_id="stdout")

    async def deliver(self, alert: dict) -> dict:
        alert_id = alert.get("alert_id", "unknown")
        try:
            text = format_alert_text(alert)
            print("\n" + text + "\n")
            logger.info("alert_delivered", channel="console", alert_id=alert_id)
            return self._make_delivery_log(alert_id, "delivered")
        except Exception as e:
            logger.error("console_delivery_failed", error=str(e))
            return self._make_delivery_log(alert_id, "failed", str(e))


class TelegramChannel(DeliveryChannel):
    """Deliver alerts via Telegram Bot API with exponential backoff retry."""

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0):
        super().__init__(channel_type="telegram", channel_id=chat_id)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def deliver(self, alert: dict) -> dict:
        alert_id = alert.get("alert_id", "unknown")
        last_error: str = ""

        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                client = await self._get_client()
                text = format_alert_telegram(alert)

                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                response = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })

                if response.status_code == 200:
                    logger.info("alert_delivered", channel="telegram",
                                alert_id=alert_id, chat_id=self.chat_id,
                                attempt=attempt)
                    return self._make_delivery_log(alert_id, "delivered")

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.warning("telegram_delivery_attempt_failed",
                               attempt=attempt, reason=last_error,
                               alert_id=alert_id)

            except Exception as e:
                last_error = str(e)
                logger.warning("telegram_delivery_attempt_error",
                               attempt=attempt, error=last_error,
                               alert_id=alert_id)

            if delay is not None:
                await asyncio.sleep(delay)

        logger.error("telegram_delivery_failed_all_attempts",
                     alert_id=alert_id, last_error=last_error)
        return self._make_delivery_log(alert_id, "failed", last_error)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class WebhookChannel(DeliveryChannel):
    """Deliver alerts via HTTP webhook POST.

    When a ``secret`` is provided, each request is signed with HMAC-SHA256
    and the signature is included in the ``X-Signature-256`` header. Receivers
    can verify authenticity by computing HMAC-SHA256(secret, body) and
    comparing it to the header value.
    """

    def __init__(self, url: str, secret: str = "",
                 extra_headers: dict | None = None, timeout: float = 10.0):
        super().__init__(channel_type="webhook", channel_id=url)
        self.url = url
        self.secret = secret
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _sign_payload(self, body: bytes) -> str:
        """Return HMAC-SHA256 hex digest of *body* using the configured secret."""
        return hmac.new(
            self.secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def deliver(self, alert: dict) -> dict:
        alert_id = alert.get("alert_id", "unknown")
        last_error: str = ""

        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                client = await self._get_client()
                payload = format_alert_json(alert)
                body = json.dumps(payload).encode("utf-8")

                headers = {"Content-Type": "application/json", **self.extra_headers}
                if self.secret:
                    headers["X-Signature-256"] = f"sha256={self._sign_payload(body)}"

                response = await client.post(
                    self.url,
                    content=body,
                    headers=headers,
                )

                if 200 <= response.status_code < 300:
                    logger.info("alert_delivered", channel="webhook",
                                alert_id=alert_id, attempt=attempt)
                    return self._make_delivery_log(alert_id, "delivered")

                last_error = f"HTTP {response.status_code}"
                # 4xx errors are not retried — they indicate a client-side problem
                if 400 <= response.status_code < 500:
                    logger.error("webhook_delivery_client_error",
                                 alert_id=alert_id, status=response.status_code)
                    return self._make_delivery_log(alert_id, "failed", last_error)

                logger.warning("webhook_delivery_attempt_failed",
                               attempt=attempt, reason=last_error, alert_id=alert_id)

            except Exception as e:
                last_error = str(e)
                logger.warning("webhook_delivery_attempt_error",
                               attempt=attempt, error=last_error, alert_id=alert_id)

            if delay is not None:
                await asyncio.sleep(delay)

        logger.error("webhook_delivery_failed_all_attempts",
                     alert_id=alert_id, last_error=last_error)
        return self._make_delivery_log(alert_id, "failed", last_error)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class DeliveryRouter:
    """Routes alerts to configured channels with rate limiting and deduplication.

    Delivery records are returned from ``deliver_alert()`` and must be persisted
    by the caller (pipeline or alert engine) to survive restarts.
    """

    # Alert types that get immediate push delivery
    PUSH_TYPES = {"possible_entry", "high_potential_watch", "take_profit_watch", "exit_risk"}
    # Alert types that bypass rate limits
    BYPASS_RATE_LIMIT_TYPES = {"exit_risk"}

    def __init__(self, rate_limit_per_10min: int = 6):
        self._channels: list[DeliveryChannel] = []
        self._rate_limit = rate_limit_per_10min
        self._recent_deliveries: deque = deque(maxlen=200)
        # (alert_id, alert_type) tuples — persisted caller-side; in-memory dedup
        # covers within-session duplicates. Cross-restart dedup is handled by
        # the alert engine checking alert_deliveries table before routing.
        self._delivered_alert_states: set = set()

    def add_channel(self, channel: DeliveryChannel):
        self._channels.append(channel)
        logger.info("delivery_channel_added",
                    type=channel.channel_type, id=channel.channel_id)

    def seed_delivered_states(self, delivered_states: set[tuple[str, str]]) -> None:
        """Pre-populate delivered state from persisted delivery records.

        Call this at startup with (alert_id, alert_type) tuples loaded from
        the alert_deliveries table to prevent re-delivery after restart.
        """
        self._delivered_alert_states.update(delivered_states)
        logger.info("delivery_dedup_seeded", count=len(delivered_states))

    async def deliver_alert(self, alert: dict) -> list[dict]:
        """Route an alert to appropriate channels. Returns delivery logs.

        Logs must be persisted by the caller. Rate-limited alerts are logged
        with status='rate_limited' rather than silently dropped.
        """
        alert_id = alert.get("alert_id", "")
        alert_type = alert.get("alert_type", "")

        # Deduplication: don't re-deliver same alert+type combo
        state_key = (alert_id, alert_type)
        if state_key in self._delivered_alert_states:
            logger.debug("delivery_skipped_duplicate", alert_id=alert_id, type=alert_type)
            return []

        # Check if this type warrants delivery
        if alert_type not in self.PUSH_TYPES:
            logger.debug("delivery_skipped_non_push", alert_id=alert_id, type=alert_type)
            return []

        # Rate limiting (except for exit_risk)
        if alert_type not in self.BYPASS_RATE_LIMIT_TYPES:
            now = datetime.now(timezone.utc)
            recent_count = sum(
                1 for t in self._recent_deliveries
                if (now - t).total_seconds() < 600
            )
            if recent_count >= self._rate_limit:
                logger.warning("delivery_rate_limited", alert_id=alert_id,
                               recent_count=recent_count, limit=self._rate_limit)
                # Return a rate_limited log record instead of silently dropping.
                # The pipeline persists this so the operator can see dropped alerts.
                return [{
                    "delivery_id": str(uuid.uuid4()),
                    "alert_id": alert_id,
                    "channel_type": "all",
                    "channel_id": "all",
                    "attempted_at": now.isoformat(),
                    "status": "rate_limited",
                    "failure_reason": "rate_limit_exceeded",
                }]

        # Deliver to all channels
        logs = []
        for channel in self._channels:
            log = await channel.deliver(alert)
            logs.append(log)

        # Track delivery in-memory
        self._delivered_alert_states.add(state_key)
        self._recent_deliveries.append(datetime.now(timezone.utc))

        return logs

    async def close_all(self):
        for channel in self._channels:
            if hasattr(channel, "close"):
                await channel.close()
