"""Solana RPC adapter for fetching on-chain token data."""
import httpx
from datetime import datetime, timezone
from .base import SourceAdapter, logger

class SolanaRPCAdapter(SourceAdapter):
    """Fetch on-chain data for tokens via Solana JSON-RPC."""

    def __init__(self, rpc_url: str, timeout: float = 10.0):
        super().__init__(source_name="solana_rpc", source_type="on_chain")
        self.rpc_url = rpc_url
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def fetch(self) -> list[dict]:
        """Not used directly - use fetch_token_data instead."""
        return []

    async def fetch_token_data(self, token_address: str) -> dict | None:
        """Fetch account info and basic token data for a specific token."""
        try:
            client = await self._get_client()

            # Get token account info
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getAccountInfo",
                "params": [token_address, {"encoding": "jsonParsed"}]
            }
            response = await client.post(self.rpc_url, json=payload)
            response.raise_for_status()
            result = response.json().get("result", {})

            self._mark_healthy()

            if not result or not result.get("value"):
                return None

            account = result["value"]
            data = account.get("data", {})
            parsed = data.get("parsed", {}) if isinstance(data, dict) else {}
            info = parsed.get("info", {}) if isinstance(parsed, dict) else {}

            return {
                "address": token_address,
                "owner": account.get("owner"),
                "lamports": account.get("lamports"),
                "supply": info.get("supply"),
                "decimals": info.get("decimals"),
                "mint_authority": info.get("mintAuthority"),
                "freeze_authority": info.get("freezeAuthority"),
                "sampled_at": datetime.now(timezone.utc).isoformat(),
                "data_source": "solana_rpc",
            }
        except Exception as e:
            self._mark_unhealthy(str(e))
            logger.error("solana_rpc_fetch_failed", token=token_address, error=str(e))
            return None

    async def fetch_token_holders(self, token_address: str) -> dict | None:
        """Fetch largest token holders for concentration analysis."""
        try:
            client = await self._get_client()
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [token_address]
            }
            response = await client.post(self.rpc_url, json=payload)
            response.raise_for_status()
            result = response.json().get("result", {})

            self._mark_healthy()

            accounts = result.get("value", [])
            if not accounts:
                return None

            total_in_top = sum(float(a.get("uiAmount", 0) or 0) for a in accounts)
            top_5 = accounts[:5]
            top_5_amount = sum(float(a.get("uiAmount", 0) or 0) for a in top_5)
            top_10 = accounts[:10]
            top_10_amount = sum(float(a.get("uiAmount", 0) or 0) for a in top_10)

            # We'd need total supply to get percentages - estimate from what we have
            # This is approximate; real implementation would fetch supply separately
            return {
                "address": token_address,
                "holder_count_estimated": len(accounts),
                "top_accounts": [
                    {"address": a.get("address"), "amount": float(a.get("uiAmount", 0) or 0)}
                    for a in accounts
                ],
                "top_5_total": top_5_amount,
                "top_10_total": top_10_amount,
                "sampled_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            self._mark_unhealthy(str(e))
            logger.error("solana_holder_fetch_failed", token=token_address, error=str(e))
            return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
