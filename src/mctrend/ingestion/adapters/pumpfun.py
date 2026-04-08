"""Pump.fun token ingestion adapter. Fetches newly launched tokens."""
import httpx
from datetime import datetime, timezone
from .base import SourceAdapter, logger, retry_fetch


class PumpFunAdapter(SourceAdapter):
    """Fetches new token launches from Pump.fun API.

    NOTE: The public Pump.fun frontend API (``frontend-api-v2.pump.fun``) has
    no documented SLA and returns 503 frequently in production.  This adapter
    is structurally correct but depends on an unreliable public endpoint.

    Status label: ``enabled-unreliable`` — adapter is registered and attempts
    fetches, but failures are expected and do not indicate a system bug.
    Set ``PUMPFUN_API_URL`` to override with a private/paid endpoint.
    """

    #: Public endpoint is functional but unreliable (no SLA, frequent 503).
    SUPPORTED = True
    RELIABILITY_NOTE = (
        "Public endpoint frontend-api-v2.pump.fun has no SLA and returns 503 "
        "intermittently. Failures are expected. Set PUMPFUN_API_URL to use a "
        "private or paid endpoint."
    )

    def __init__(self, api_url: str | None = None, timeout: float = 10.0,
                 fetch_limit: int = 50):
        super().__init__(source_name="pump.fun", source_type="token_launch_platform")
        self.api_url = api_url or "https://frontend-api-v2.pump.fun"
        self.timeout = timeout
        self.fetch_limit = fetch_limit
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def fetch(self) -> list[dict]:
        """Fetch recent token launches with retry. Returns normalized dicts."""
        async def _do_fetch():
            client = await self._get_client()
            response = await client.get(
                f"{self.api_url}/coins",
                params={"offset": 0, "limit": self.fetch_limit,
                        "sort": "creation_time", "order": "DESC",
                        "includeNsfw": "false"},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await retry_fetch(_do_fetch, self.source_name)
            self._mark_healthy()

            tokens = []
            items = data if isinstance(data, list) else data.get("items", data.get("coins", []))
            for item in items:
                token = self._normalize_token(item)
                if token:
                    tokens.append(token)

            logger.info("pumpfun_fetch_complete", token_count=len(tokens))
            return tokens

        except Exception as e:
            self._mark_unhealthy(str(e))
            logger.error("pumpfun_fetch_failed", error=str(e))
            return []

    def _normalize_token(self, raw: dict) -> dict | None:
        """Convert raw Pump.fun API response to normalized token dict."""
        try:
            # Pump.fun API fields vary but common patterns:
            address = raw.get("mint") or raw.get("address") or raw.get("token_address")
            if not address:
                return None

            name = raw.get("name", "")
            symbol = raw.get("symbol", "")
            if not name and not symbol:
                return None

            # Parse timestamp
            created_ts = raw.get("created_timestamp") or raw.get("creation_time") or raw.get("created_at")
            if isinstance(created_ts, (int, float)):
                launch_time = datetime.fromtimestamp(created_ts / 1000 if created_ts > 1e12 else created_ts, tz=timezone.utc)
            elif isinstance(created_ts, str):
                launch_time = datetime.fromisoformat(created_ts.replace("Z", "+00:00"))
            else:
                launch_time = datetime.now(timezone.utc)

            deployer = raw.get("creator") or raw.get("deployer") or raw.get("creator_address") or "unknown"

            return {
                "address": address,
                "name": name,
                "symbol": symbol,
                "description": raw.get("description"),
                "deployed_by": deployer,
                "launch_time": launch_time.isoformat(),
                "launch_platform": "pump.fun",
                "initial_liquidity_usd": raw.get("usd_market_cap") or raw.get("market_cap_usd"),
                "initial_holder_count": raw.get("holder_count"),
                "data_source": "pump.fun",
                "raw": raw,  # keep raw for debugging
            }
        except Exception as e:
            logger.warning("pumpfun_normalize_failed", error=str(e))
            return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
