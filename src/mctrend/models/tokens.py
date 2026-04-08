"""Token domain models — on-chain token records and periodic chain snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import TokenStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class TokenRecord(BaseModel):
    """Core representation of a token tracked by the system.

    Every field that may be unavailable at discovery time is Optional and
    recorded in ``data_gaps`` when missing, following the conservative-default
    rule (missing data is never treated as zero or best-case).
    """

    model_config = ConfigDict(frozen=False)

    token_id: str = Field(default_factory=_uuid4, description="Unique identifier for this token record.")
    chain: str = Field(default="solana", description="Blockchain the token lives on.")
    address: str = Field(..., description="On-chain token address.")
    name: str = Field(..., description="Human-readable token name.")
    symbol: str = Field(..., description="Ticker symbol.")
    description: Optional[str] = Field(default=None, description="Token description from metadata, if available.")
    deployed_by: str = Field(..., description="Deployer wallet address.")
    launch_time: datetime = Field(..., description="On-chain deployment timestamp.")
    launch_platform: str = Field(..., description="Platform the token was launched on (e.g. 'pump.fun').")
    first_seen_by_system: datetime = Field(default_factory=_utcnow, description="When the system first ingested this token.")
    initial_liquidity_usd: Optional[float] = Field(default=None, description="Liquidity at launch in USD, if known.")
    initial_holder_count: Optional[int] = Field(default=None, description="Holder count at launch, if known.")
    initial_supply: Optional[int] = Field(default=None, description="Total supply at launch, if known.")
    mint_authority_status: str = Field(default="unknown", description="Status of mint authority (e.g. 'revoked', 'active', 'unknown').")
    freeze_authority_status: str = Field(default="unknown", description="Status of freeze authority (e.g. 'revoked', 'active', 'unknown').")
    status: TokenStatus = Field(default=TokenStatus.NEW, description="Current lifecycle status.")
    linked_narratives: list[str] = Field(default_factory=list, description="Narrative IDs this token is linked to.")
    created_at: datetime = Field(default_factory=_utcnow, description="Record creation timestamp.")
    updated_at: datetime = Field(default_factory=_utcnow, description="Last update timestamp.")
    data_gaps: list[str] = Field(default_factory=list, description="Fields that were unavailable and defaulted conservatively.")
    data_sources: list[str] = Field(default_factory=list, description="Sources that contributed data for this record.")


class TokenChainSnapshot(BaseModel):
    """Point-in-time on-chain metrics for a token.

    Captured periodically to feed scoring dimensions (momentum, rug risk,
    holder distribution).  Missing fields are recorded in ``data_gaps``.
    """

    model_config = ConfigDict(frozen=False)

    snapshot_id: str = Field(default_factory=_uuid4, description="Unique snapshot identifier.")
    token_id: str = Field(..., description="Token this snapshot belongs to.")
    sampled_at: datetime = Field(default_factory=_utcnow, description="When the snapshot was taken.")

    # Holder metrics
    holder_count: Optional[int] = Field(default=None, description="Total holder count.")
    top_5_holder_pct: Optional[float] = Field(default=None, description="Percentage of supply held by top 5 wallets.")
    top_10_holder_pct: Optional[float] = Field(default=None, description="Percentage of supply held by top 10 wallets.")
    new_wallet_holder_pct: Optional[float] = Field(default=None, description="Percentage of holders that are new wallets.")

    # Liquidity metrics
    liquidity_usd: Optional[float] = Field(default=None, description="Current liquidity in USD.")
    liquidity_locked: Optional[bool] = Field(default=None, description="Whether liquidity is locked.")
    liquidity_lock_hours: Optional[int] = Field(default=None, description="Hours of lock remaining, if locked.")
    liquidity_provider_count: Optional[int] = Field(default=None, description="Number of unique liquidity providers.")

    # Trading activity metrics
    volume_1h_usd: Optional[float] = Field(default=None, description="Trading volume in the last hour (USD).")
    trade_count_1h: Optional[int] = Field(default=None, description="Number of trades in the last hour.")
    unique_traders_1h: Optional[int] = Field(default=None, description="Unique trader wallets in the last hour.")

    # Deployer reputation
    deployer_known_bad: bool = Field(default=False, description="Whether the deployer is on a known-bad list.")
    deployer_prior_deployments: Optional[int] = Field(default=None, description="Number of prior token deployments by this deployer.")

    data_source: str = Field(..., description="Source that provided this snapshot (e.g. 'helius', 'birdeye').")
    data_gaps: list[str] = Field(default_factory=list, description="Fields that were unavailable in this snapshot.")
