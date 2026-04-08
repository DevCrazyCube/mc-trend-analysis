"""
Application settings loaded from environment variables with validated defaults.

All configurable weights, thresholds, and operational parameters live here.
No scoring weight, alert threshold, or rate limit should be hardcoded in
application code — they must be read from this settings module.

Reference docs:
  - docs/intelligence/probability-framework.md  (dimension & failure weights)
  - docs/alerting/alert-types.md                (classification thresholds)
  - docs/intelligence/rug-risk-framework.md     (rug category weights & defaults)
  - docs/alerting/notification-strategy.md      (rate limits)
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Sub-models for structured groups of weights / thresholds
# ---------------------------------------------------------------------------


class PotentialWeights(BaseModel):
    """Weights for P_potential dimensions (must sum to 1.0).

    Reference: docs/intelligence/probability-framework.md — P_potential table.
    """

    narrative_relevance: float = Field(0.25, ge=0.0, le=1.0)
    og_score: float = Field(0.20, ge=0.0, le=1.0)
    momentum_quality: float = Field(0.20, ge=0.0, le=1.0)
    attention_strength: float = Field(0.20, ge=0.0, le=1.0)
    timing_quality: float = Field(0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> PotentialWeights:
        total = (
            self.narrative_relevance
            + self.og_score
            + self.momentum_quality
            + self.attention_strength
            + self.timing_quality
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"P_potential weights must sum to 1.0, got {total:.6f}")
        return self


class FailureWeights(BaseModel):
    """Weights for P_failure components (must sum to 1.0).

    Reference: docs/intelligence/probability-framework.md — P_failure table.
    """

    rug_risk: float = Field(0.35, ge=0.0, le=1.0)
    fakeout_risk: float = Field(0.25, ge=0.0, le=1.0)
    exhaustion_risk: float = Field(0.20, ge=0.0, le=1.0)
    copycat_capture_risk: float = Field(0.10, ge=0.0, le=1.0)
    liquidity_risk: float = Field(0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> FailureWeights:
        total = (
            self.rug_risk
            + self.fakeout_risk
            + self.exhaustion_risk
            + self.copycat_capture_risk
            + self.liquidity_risk
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"P_failure weights must sum to 1.0, got {total:.6f}")
        return self


class RugRiskCategoryWeights(BaseModel):
    """Weights for rug risk sub-categories (must sum to 1.0).

    Reference: docs/intelligence/rug-risk-framework.md — Combining Category Scores.
    """

    deployer: float = Field(0.30, ge=0.0, le=1.0)
    concentration: float = Field(0.25, ge=0.0, le=1.0)
    clustering: float = Field(0.20, ge=0.0, le=1.0)
    liquidity: float = Field(0.15, ge=0.0, le=1.0)
    contract: float = Field(0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> RugRiskCategoryWeights:
        total = (
            self.deployer
            + self.concentration
            + self.clustering
            + self.liquidity
            + self.contract
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Rug risk category weights must sum to 1.0, got {total:.6f}")
        return self


class RugRiskMissingDataDefaults(BaseModel):
    """Conservative default scores applied when data for a rug risk category is unavailable.

    Reference: docs/intelligence/rug-risk-framework.md — Missing Data Policy.
    Missing data is never zero — it is treated as weak-to-moderate risk.
    """

    deployer: float = Field(0.50, ge=0.0, le=1.0)
    concentration: float = Field(0.55, ge=0.0, le=1.0)
    clustering: float = Field(0.50, ge=0.0, le=1.0)
    liquidity: float = Field(0.60, ge=0.0, le=1.0)
    contract: float = Field(0.50, ge=0.0, le=1.0)


class OGResolutionWeights(BaseModel):
    """Weights for OG token resolution scoring (must sum to 1.0).

    Reference: docs/intelligence/og-token-resolution.md — Step 3: Compute OG Score.
    """

    temporal: float = Field(0.35, ge=0.0, le=1.0)
    name_precision: float = Field(0.25, ge=0.0, le=1.0)
    cross_source: float = Field(0.30, ge=0.0, le=1.0)
    deployer: float = Field(0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> OGResolutionWeights:
        total = self.temporal + self.name_precision + self.cross_source + self.deployer
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"OG resolution weights must sum to 1.0, got {total:.6f}")
        return self


class OGResolutionConfig(BaseModel):
    """Operational parameters for OG token resolution.

    Reference: docs/intelligence/og-token-resolution.md.
    """

    temporal_decay_minutes: float = Field(
        30.0, gt=0, description="Minutes after first token at which temporal score reaches 0"
    )
    max_expected_mentions: int = Field(
        5, gt=0, description="Cross-source mention count that yields score of 1.0"
    )
    weights: OGResolutionWeights = Field(default_factory=OGResolutionWeights)


class CorrelationConfig(BaseModel):
    """Configuration for the correlation / name-matching engine.

    Reference: docs/intelligence/narrative-linking.md.
    """

    min_match_confidence: float = Field(
        0.15,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for a token-narrative link",
    )
    strip_suffixes: list[str] = Field(
        default_factory=lambda: [
            "COIN", "TOKEN", "INU", "SOL", "2", "V2", "V3", "FI", "AI", "MOON", "DAO",
        ],
        description="Common token name suffixes to strip during normalization",
    )


class ConfidenceWeights(BaseModel):
    """Weights for the confidence_score formula (must sum to 1.0).

    Reference: docs/intelligence/probability-framework.md — confidence_score.
    """

    source_count: float = Field(0.25, ge=0.0, le=1.0)
    source_diversity: float = Field(0.25, ge=0.0, le=1.0)
    data_completeness: float = Field(0.30, ge=0.0, le=1.0)
    ambiguity: float = Field(0.20, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> ConfidenceWeights:
        total = (
            self.source_count + self.source_diversity + self.data_completeness + self.ambiguity
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Confidence weights must sum to 1.0, got {total:.6f}")
        return self


# ---------------------------------------------------------------------------
# Alert classification thresholds
# ---------------------------------------------------------------------------


class AlertThresholdEntry(BaseModel):
    """Threshold values that must be met for a given alert type to be assigned."""

    min_net_potential: float = Field(ge=0.0, le=1.0)
    max_p_failure: float = Field(ge=0.0, le=1.0)
    min_confidence: float = Field(ge=0.0, le=1.0)


class AlertThresholds(BaseModel):
    """Classification thresholds for each alert tier.

    Reference: docs/alerting/alert-types.md — Classification Thresholds.
    """

    possible_entry: AlertThresholdEntry = Field(
        default_factory=lambda: AlertThresholdEntry(
            min_net_potential=0.60,
            max_p_failure=0.30,
            min_confidence=0.65,
        )
    )
    high_potential_watch: AlertThresholdEntry = Field(
        default_factory=lambda: AlertThresholdEntry(
            min_net_potential=0.45,
            max_p_failure=0.50,
            min_confidence=0.55,
        )
    )
    take_profit_watch: AlertThresholdEntry = Field(
        default_factory=lambda: AlertThresholdEntry(
            min_net_potential=0.35,
            max_p_failure=1.0,
            min_confidence=0.0,
        )
    )
    verify: AlertThresholdEntry = Field(
        default_factory=lambda: AlertThresholdEntry(
            min_net_potential=0.35,
            max_p_failure=1.0,
            min_confidence=0.0,
        )
    )
    watch: AlertThresholdEntry = Field(
        default_factory=lambda: AlertThresholdEntry(
            min_net_potential=0.25,
            max_p_failure=1.0,
            min_confidence=0.0,
        )
    )
    exit_risk_p_failure_threshold: float = Field(
        0.65,
        ge=0.0,
        le=1.0,
        description="P_failure threshold that triggers exit-risk for an active alert",
    )
    discard_p_failure_threshold: float = Field(
        0.80,
        ge=0.0,
        le=1.0,
        description="P_failure threshold that triggers discard",
    )
    discard_net_potential_ceiling: float = Field(
        0.10,
        ge=0.0,
        le=1.0,
        description="net_potential below which a token is discarded regardless of P_failure",
    )


class AlertExpiryMinutes(BaseModel):
    """Expiry windows for each alert type, in minutes.

    Reference: docs/alerting/alert-types.md — per-type expiry definitions.
    """

    possible_entry: int = Field(60, gt=0)
    high_potential_watch: int = Field(120, gt=0)
    take_profit_watch: int = Field(30, gt=0)
    verify: int = Field(120, gt=0)
    watch: int = Field(240, gt=0)
    exit_risk: int = Field(15, gt=0)


# ---------------------------------------------------------------------------
# Top-level settings
# ---------------------------------------------------------------------------


class Settings(BaseModel):
    """Central configuration for the MC Trend Analysis system.

    Constructed via ``Settings.load()`` which reads a ``.env`` file (if present)
    and then pulls values from environment variables, falling back to the
    documented defaults.

    No weight, threshold, or operational parameter should be hardcoded outside
    this class.  See docs/rules/engineering-rules.md Rule 2.
    """

    # -- Environment ----------------------------------------------------------
    environment: str = Field(
        "demo",
        description="Deployment environment: 'demo', 'dev', or 'prod'",
    )

    # -- Data source URLs / keys ---------------------------------------------
    solana_rpc_url: str = Field(
        "https://api.mainnet-beta.solana.com",
        description="Solana JSON-RPC endpoint (required for on-chain data)",
    )
    pumpfun_api_url: str = Field(
        "",
        description="Pump.fun API base URL (optional, falls back to on-chain monitoring)",
    )
    newsapi_key: str = Field("", description="NewsAPI.org API key")
    serpapi_key: str = Field("", description="SerpAPI key for Google Trends data")
    twitter_bearer_token: str = Field("", description="X/Twitter API bearer token")

    # -- Delivery channels ----------------------------------------------------
    telegram_bot_token: str = Field("", description="Telegram Bot API token")
    telegram_chat_id: str = Field("", description="Telegram chat ID for alert delivery")
    webhook_url: str = Field("", description="Webhook URL for alert delivery")
    webhook_secret: str = Field(
        "",
        description="HMAC secret for webhook request signing (X-Signature-256 header)",
    )

    # -- Storage --------------------------------------------------------------
    database_path: str = Field(
        "data/mctrend.db",
        description="Path to the SQLite database file",
    )

    # -- Logging --------------------------------------------------------------
    log_level: str = Field("INFO", description="Python log level name")
    log_format: str = Field("json", description="Log format: 'json' or 'console'")

    # -- Polling intervals (seconds) ------------------------------------------
    polling_interval_tokens: int = Field(
        30, gt=0, description="Seconds between token-launch polling cycles"
    )
    polling_interval_events: int = Field(
        300, gt=0, description="Seconds between narrative/event polling cycles"
    )

    # -- Alert operational parameters -----------------------------------------
    alert_rate_limit_per_10min: int = Field(
        6, gt=0, description="Max push alerts per 10-minute window per channel"
    )
    max_token_age_hours: int = Field(
        4, gt=0, description="Tokens older than this are excluded from scoring"
    )
    confidence_floor_for_alert: float = Field(
        0.25,
        ge=0.0,
        le=1.0,
        description="Minimum confidence_score to emit any alert",
    )

    # -- Ingestion adapter parameters -----------------------------------------
    news_query_terms: list[str] = Field(
        default_factory=lambda: ["crypto", "meme", "viral", "trending"],
        description="Search query terms for NewsAPI adapter",
    )
    news_page_size: int = Field(
        10, gt=0, description="Articles per query for NewsAPI adapter"
    )
    news_signal_strength: float = Field(
        0.6, ge=0.0, le=1.0, description="Default signal strength for news events"
    )
    trends_geo: str = Field("US", description="Geographic filter for Google Trends adapter")
    trends_signal_strength: float = Field(
        0.7, ge=0.0, le=1.0, description="Default signal strength for trend events"
    )
    pumpfun_fetch_limit: int = Field(
        50, gt=0, description="Number of tokens to fetch per Pump.fun API call"
    )

    # -- External call defaults -----------------------------------------------
    external_api_timeout_seconds: float = Field(
        10.0, gt=0, description="Default timeout for external API calls"
    )
    database_query_timeout_seconds: float = Field(
        5.0, gt=0, description="Default timeout for database queries"
    )
    max_expected_sources: int = Field(
        5, gt=0, description="Normalizer for source_count_score in confidence calculation"
    )

    # -- Retention / pruning --------------------------------------------------
    chain_snapshot_retention_hours: int = Field(
        48, gt=0, description="Hours before old chain snapshots are pruned"
    )
    scored_token_retention_hours: int = Field(
        72, gt=0, description="Hours before old scored_token records are pruned"
    )
    retired_alert_retention_hours: int = Field(
        168, gt=0, description="Hours before retired/expired alerts are purged (7 days)"
    )
    alert_history_max_entries: int = Field(
        50, gt=0, description="Max lifecycle history entries retained per alert"
    )

    # -- Scoring weights ------------------------------------------------------
    potential_weights: PotentialWeights = Field(default_factory=PotentialWeights)
    failure_weights: FailureWeights = Field(default_factory=FailureWeights)
    rug_risk_category_weights: RugRiskCategoryWeights = Field(
        default_factory=RugRiskCategoryWeights
    )
    rug_risk_missing_data_defaults: RugRiskMissingDataDefaults = Field(
        default_factory=RugRiskMissingDataDefaults
    )
    confidence_weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)

    # -- Correlation / OG resolution -------------------------------------------
    og_resolution: OGResolutionConfig = Field(default_factory=OGResolutionConfig)
    correlation: CorrelationConfig = Field(default_factory=CorrelationConfig)

    # -- Alert classification -------------------------------------------------
    alert_thresholds: AlertThresholds = Field(default_factory=AlertThresholds)
    alert_expiry_minutes: AlertExpiryMinutes = Field(default_factory=AlertExpiryMinutes)

    # -----------------------------------------------------------------------
    # Factory
    # -----------------------------------------------------------------------

    @classmethod
    def load(cls, env_file: str | Path | None = ".env") -> Settings:
        """Create a ``Settings`` instance from environment variables.

        If *env_file* exists it is loaded first (via ``python-dotenv``); then
        every field is resolved from the corresponding upper-case environment
        variable, falling back to the default declared above.

        Nested weight/threshold objects use the documented defaults and are not
        individually overridable via env vars — change them through
        configuration files or constructor arguments when non-default values are
        needed.
        """
        if env_file is not None:
            load_dotenv(dotenv_path=str(env_file), override=False)

        import os

        env = os.environ

        return cls(
            environment=env.get("ENVIRONMENT", cls.model_fields["environment"].default),
            solana_rpc_url=env.get(
                "SOLANA_RPC_URL", cls.model_fields["solana_rpc_url"].default
            ),
            pumpfun_api_url=env.get(
                "PUMPFUN_API_URL", cls.model_fields["pumpfun_api_url"].default
            ),
            newsapi_key=env.get("NEWSAPI_KEY", cls.model_fields["newsapi_key"].default),
            serpapi_key=env.get("SERPAPI_KEY", cls.model_fields["serpapi_key"].default),
            twitter_bearer_token=env.get(
                "TWITTER_BEARER_TOKEN", cls.model_fields["twitter_bearer_token"].default
            ),
            telegram_bot_token=env.get(
                "TELEGRAM_BOT_TOKEN", cls.model_fields["telegram_bot_token"].default
            ),
            telegram_chat_id=env.get(
                "TELEGRAM_CHAT_ID", cls.model_fields["telegram_chat_id"].default
            ),
            webhook_url=env.get("WEBHOOK_URL", cls.model_fields["webhook_url"].default),
            webhook_secret=env.get(
                "WEBHOOK_SECRET", cls.model_fields["webhook_secret"].default
            ),
            database_path=env.get(
                "DATABASE_PATH", cls.model_fields["database_path"].default
            ),
            log_level=env.get("LOG_LEVEL", cls.model_fields["log_level"].default),
            log_format=env.get("LOG_FORMAT", cls.model_fields["log_format"].default),
            polling_interval_tokens=int(
                env.get(
                    "POLLING_INTERVAL_TOKENS",
                    cls.model_fields["polling_interval_tokens"].default,
                )
            ),
            polling_interval_events=int(
                env.get(
                    "POLLING_INTERVAL_EVENTS",
                    cls.model_fields["polling_interval_events"].default,
                )
            ),
            alert_rate_limit_per_10min=int(
                env.get(
                    "ALERT_RATE_LIMIT_PER_10MIN",
                    cls.model_fields["alert_rate_limit_per_10min"].default,
                )
            ),
            max_token_age_hours=int(
                env.get(
                    "MAX_TOKEN_AGE_HOURS",
                    cls.model_fields["max_token_age_hours"].default,
                )
            ),
            confidence_floor_for_alert=float(
                env.get(
                    "CONFIDENCE_FLOOR_FOR_ALERT",
                    cls.model_fields["confidence_floor_for_alert"].default,
                )
            ),
            news_signal_strength=float(
                env.get(
                    "NEWS_SIGNAL_STRENGTH",
                    cls.model_fields["news_signal_strength"].default,
                )
            ),
            trends_signal_strength=float(
                env.get(
                    "TRENDS_SIGNAL_STRENGTH",
                    cls.model_fields["trends_signal_strength"].default,
                )
            ),
            trends_geo=env.get("TRENDS_GEO", cls.model_fields["trends_geo"].default),
            pumpfun_fetch_limit=int(
                env.get(
                    "PUMPFUN_FETCH_LIMIT",
                    cls.model_fields["pumpfun_fetch_limit"].default,
                )
            ),
            news_page_size=int(
                env.get("NEWS_PAGE_SIZE", cls.model_fields["news_page_size"].default)
            ),
            chain_snapshot_retention_hours=int(
                env.get(
                    "CHAIN_SNAPSHOT_RETENTION_HOURS",
                    cls.model_fields["chain_snapshot_retention_hours"].default,
                )
            ),
            scored_token_retention_hours=int(
                env.get(
                    "SCORED_TOKEN_RETENTION_HOURS",
                    cls.model_fields["scored_token_retention_hours"].default,
                )
            ),
            retired_alert_retention_hours=int(
                env.get(
                    "RETIRED_ALERT_RETENTION_HOURS",
                    cls.model_fields["retired_alert_retention_hours"].default,
                )
            ),
            alert_history_max_entries=int(
                env.get(
                    "ALERT_HISTORY_MAX_ENTRIES",
                    cls.model_fields["alert_history_max_entries"].default,
                )
            ),
        )
