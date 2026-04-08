"""Delivery channel implementations."""

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
    """Deliver alerts via Telegram Bot API."""

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
                            alert_id=alert_id, chat_id=self.chat_id)
                return self._make_delivery_log(alert_id, "delivered")
            else:
                reason = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.error("telegram_delivery_failed", reason=reason)
                return self._make_delivery_log(alert_id, "failed", reason)

        except Exception as e:
            logger.error("telegram_delivery_error", error=str(e))
            return self._make_delivery_log(alert_id, "failed", str(e))

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class WebhookChannel(DeliveryChannel):
    """Deliver alerts via HTTP webhook POST."""

    def __init__(self, url: str, headers: dict | None = None, timeout: float = 10.0):
        super().__init__(channel_type="webhook", channel_id=url)
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def deliver(self, alert: dict) -> dict:
        alert_id = alert.get("alert_id", "unknown")
        try:
            client = await self._get_client()
            payload = format_alert_json(alert)

            response = await client.post(self.url, json=payload, headers=self.headers)

            if 200 <= response.status_code < 300:
                logger.info("alert_delivered", channel="webhook", alert_id=alert_id)
                return self._make_delivery_log(alert_id, "delivered")
            else:
                reason = f"HTTP {response.status_code}"
                return self._make_delivery_log(alert_id, "failed", reason)

        except Exception as e:
            logger.error("webhook_delivery_error", error=str(e))
            return self._make_delivery_log(alert_id, "failed", str(e))

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class DeliveryRouter:
    """Routes alerts to configured channels with rate limiting and deduplication."""

    # Alert types that get immediate push delivery
    PUSH_TYPES = {"possible_entry", "high_potential_watch", "take_profit_watch", "exit_risk"}
    # Alert types that bypass rate limits
    BYPASS_RATE_LIMIT_TYPES = {"exit_risk"}

    def __init__(self, rate_limit_per_10min: int = 6):
        self._channels: list[DeliveryChannel] = []
        self._rate_limit = rate_limit_per_10min
        self._recent_deliveries: deque = deque(maxlen=100)
        self._delivered_alert_states: set = set()  # (alert_id, alert_type) tuples

    def add_channel(self, channel: DeliveryChannel):
        self._channels.append(channel)
        logger.info("delivery_channel_added", type=channel.channel_type, id=channel.channel_id)

    async def deliver_alert(self, alert: dict) -> list[dict]:
        """
        Route an alert to appropriate channels. Returns delivery logs.
        Applies rate limiting and deduplication.
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
            # Count recent deliveries in last 10 minutes
            recent_count = sum(
                1 for t in self._recent_deliveries
                if (now - t).total_seconds() < 600
            )
            if recent_count >= self._rate_limit:
                logger.warning("delivery_rate_limited", alert_id=alert_id,
                               recent_count=recent_count)
                return [{"alert_id": alert_id, "status": "rate_limited",
                         "channel_type": "all", "channel_id": "all",
                         "attempted_at": now.isoformat(),
                         "delivery_id": str(uuid.uuid4()),
                         "failure_reason": "rate_limit_exceeded"}]

        # Deliver to all channels
        logs = []
        for channel in self._channels:
            log = await channel.deliver(alert)
            logs.append(log)

        # Track delivery
        self._delivered_alert_states.add(state_key)
        self._recent_deliveries.append(datetime.now(timezone.utc))

        return logs

    async def close_all(self):
        for channel in self._channels:
            if hasattr(channel, "close"):
                await channel.close()
