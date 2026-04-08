"""SQLite database manager for the MC Trend Analysis persistence layer."""

import sqlite3
import structlog

logger = structlog.get_logger(__name__)

# Increment this whenever the schema changes. Startup validation checks this
# against the value stored in the schema_version table.
SCHEMA_VERSION = 2


class SchemaVersionError(RuntimeError):
    """Raised when the on-disk schema version does not match the expected version."""


class Database:
    """Manages the SQLite database connection and schema initialization."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create the database connection, enable WAL mode, and create all tables."""
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        # Enable WAL for concurrent reads during writes
        self.connection.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign key constraints (SQLite disables them by default)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_tables()
        self._check_schema_version()

    def close(self) -> None:
        """Close the database connection."""
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def get_size_bytes(self) -> int:
        """Return the current database file size in bytes."""
        import os
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0

    def cleanup_old_data(
        self,
        notification_max_age_days: int = 7,
        snapshot_max_age_days: int = 3,
    ) -> dict:
        """Delete old rows from unbounded tables.

        Args:
            notification_max_age_days: Delete notifications older than N days (default 7)
            snapshot_max_age_days: Delete snapshots older than N days (default 3)

        Returns:
            {"notifications_deleted": <int>, "snapshots_deleted": <int>}

        Call this periodically (e.g., once per day) to prevent unbounded growth.
        """
        import datetime

        cursor = self.connection.cursor()
        stats = {"notifications_deleted": 0, "snapshots_deleted": 0}

        # Delete old notifications
        cutoff_time = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=notification_max_age_days)
        ).isoformat()
        cursor.execute(
            "DELETE FROM operator_notifications WHERE created_at < ?",
            (cutoff_time,),
        )
        stats["notifications_deleted"] = cursor.rowcount

        # Delete old snapshots
        cutoff_time = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=snapshot_max_age_days)
        ).isoformat()
        cursor.execute(
            "DELETE FROM source_health_snapshots WHERE sampled_at < ?",
            (cutoff_time,),
        )
        stats["snapshots_deleted"] = cursor.rowcount

        self.connection.commit()
        logger.info("database_cleanup_completed", **stats)
        return stats

    def _check_schema_version(self) -> None:
        """Verify the on-disk schema version matches SCHEMA_VERSION.

        On a fresh database, writes SCHEMA_VERSION. On an existing database,
        raises SchemaVersionError if the version does not match — the operator
        must run a migration or wipe the database manually.
        """
        cursor = self.connection.cursor()
        row = cursor.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (SCHEMA_VERSION,),
            )
            self.connection.commit()
            logger.info("schema_version_initialized", version=SCHEMA_VERSION)
        elif row["version"] != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema version {row['version']} does not match "
                f"expected version {SCHEMA_VERSION}. "
                "Run a migration or remove the database file to reinitialize."
            )
        else:
            logger.debug("schema_version_ok", version=SCHEMA_VERSION)

    def _create_tables(self) -> None:
        """Create all tables and indices required by the system."""
        cursor = self.connection.cursor()

        # Schema version tracking — always created first
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token_id TEXT PRIMARY KEY,
                address TEXT UNIQUE NOT NULL,
                name TEXT,
                symbol TEXT,
                description TEXT,
                deployed_by TEXT,
                launch_time TEXT,
                launch_platform TEXT,
                first_seen_by_system TEXT NOT NULL,
                initial_liquidity_usd REAL,
                initial_holder_count INTEGER,
                mint_authority_status TEXT,
                freeze_authority_status TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                linked_narratives TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                data_gaps TEXT,
                data_sources TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chain_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                token_id TEXT NOT NULL REFERENCES tokens(token_id),
                sampled_at TEXT NOT NULL,
                holder_count INTEGER,
                top_5_holder_pct REAL CHECK(top_5_holder_pct IS NULL OR (top_5_holder_pct >= 0 AND top_5_holder_pct <= 1)),
                top_10_holder_pct REAL CHECK(top_10_holder_pct IS NULL OR (top_10_holder_pct >= 0 AND top_10_holder_pct <= 1)),
                new_wallet_holder_pct REAL CHECK(new_wallet_holder_pct IS NULL OR (new_wallet_holder_pct >= 0 AND new_wallet_holder_pct <= 1)),
                liquidity_usd REAL,
                liquidity_locked INTEGER,
                liquidity_lock_hours INTEGER,
                liquidity_provider_count INTEGER,
                volume_1h_usd REAL,
                trade_count_1h INTEGER,
                unique_traders_1h INTEGER,
                deployer_known_bad INTEGER CHECK(deployer_known_bad IS NULL OR deployer_known_bad IN (0, 1)),
                deployer_prior_deployments INTEGER,
                data_source TEXT,
                data_gaps TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS narratives (
                narrative_id TEXT PRIMARY KEY,
                anchor_terms TEXT NOT NULL,
                related_terms TEXT,
                entities TEXT,
                description TEXT,
                attention_score REAL CHECK(attention_score IS NULL OR (attention_score >= 0 AND attention_score <= 1)),
                narrative_velocity REAL,
                narrative_strength REAL CHECK(narrative_strength IS NULL OR (narrative_strength >= 0 AND narrative_strength <= 1)),
                velocity_delta REAL,
                velocity_state TEXT,
                velocity_updated_at TEXT,
                source_type_count INTEGER,
                state TEXT NOT NULL DEFAULT 'WEAK',
                sources TEXT,
                first_detected TEXT NOT NULL,
                peaked_at TEXT,
                dead_at TEXT,
                updated_at TEXT NOT NULL,
                extraction_confidence REAL CHECK(extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)),
                ambiguous INTEGER CHECK(ambiguous IS NULL OR ambiguous IN (0, 1)),
                cluster_id TEXT,
                merged_into TEXT,
                competition_status TEXT,
                competition_rank INTEGER,
                data_gaps TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_narrative_links (
                link_id TEXT PRIMARY KEY,
                token_id TEXT NOT NULL REFERENCES tokens(token_id),
                narrative_id TEXT NOT NULL REFERENCES narratives(narrative_id),
                match_confidence REAL CHECK(match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)),
                match_method TEXT,
                match_signals TEXT,
                og_rank INTEGER,
                og_score REAL CHECK(og_score IS NULL OR (og_score >= 0 AND og_score <= 1)),
                og_signals TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scored_tokens (
                score_id TEXT PRIMARY KEY,
                link_id TEXT NOT NULL REFERENCES token_narrative_links(link_id),
                token_id TEXT NOT NULL REFERENCES tokens(token_id),
                narrative_id TEXT NOT NULL REFERENCES narratives(narrative_id),
                scored_at TEXT NOT NULL,
                narrative_relevance REAL CHECK(narrative_relevance IS NULL OR (narrative_relevance >= 0 AND narrative_relevance <= 1)),
                og_score REAL CHECK(og_score IS NULL OR (og_score >= 0 AND og_score <= 1)),
                rug_risk REAL CHECK(rug_risk IS NULL OR (rug_risk >= 0 AND rug_risk <= 1)),
                momentum_quality REAL CHECK(momentum_quality IS NULL OR (momentum_quality >= 0 AND momentum_quality <= 1)),
                attention_strength REAL CHECK(attention_strength IS NULL OR (attention_strength >= 0 AND attention_strength <= 1)),
                timing_quality REAL CHECK(timing_quality IS NULL OR (timing_quality >= 0 AND timing_quality <= 1)),
                p_potential REAL,
                p_failure REAL,
                net_potential REAL,
                confidence_score REAL CHECK(confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
                risk_flags TEXT,
                data_gaps TEXT,
                dimension_details TEXT,
                data_freshness_status TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                token_id TEXT NOT NULL REFERENCES tokens(token_id),
                token_address TEXT NOT NULL,
                token_name TEXT,
                token_symbol TEXT,
                narrative_id TEXT REFERENCES narratives(narrative_id),
                narrative_name TEXT,
                link_id TEXT REFERENCES token_narrative_links(link_id),
                score_id TEXT REFERENCES scored_tokens(score_id),
                alert_type TEXT NOT NULL,
                net_potential REAL,
                p_potential REAL,
                p_failure REAL,
                confidence_score REAL,
                dimension_scores TEXT,
                risk_flags TEXT,
                reasoning TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                retired_at TEXT,
                retirement_reason TEXT,
                re_eval_triggers TEXT,
                history TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_deliveries (
                delivery_id TEXT PRIMARY KEY,
                alert_id TEXT NOT NULL REFERENCES alerts(alert_id),
                channel_type TEXT NOT NULL,
                channel_id TEXT,
                attempted_at TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_gaps (
                gap_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                notes TEXT
            )
        """)

        # Indices
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tokens_address ON tokens (address)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tokens_status ON tokens (status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_chain_snapshots_token_id "
            "ON chain_snapshots (token_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_chain_snapshots_sampled_at "
            "ON chain_snapshots (sampled_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_narratives_state ON narratives (state)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_narrative_links_token_id "
            "ON token_narrative_links (token_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_narrative_links_narrative_id "
            "ON token_narrative_links (narrative_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_scored_tokens_token_id "
            "ON scored_tokens (token_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_scored_tokens_scored_at "
            "ON scored_tokens (scored_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_token_id ON alerts (token_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_alert_type ON alerts (alert_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_deliveries_alert_id "
            "ON alert_deliveries (alert_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_deliveries_attempted_at "
            "ON alert_deliveries (attempted_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_gaps_source_name "
            "ON source_gaps (source_name)"
        )

        # --- Dashboard extension tables (schema v1-compatible additive) ----

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                holding_id TEXT PRIMARY KEY,
                token_address TEXT NOT NULL,
                token_name TEXT,
                token_symbol TEXT,
                status TEXT NOT NULL DEFAULT 'watching',
                size_sol REAL,
                avg_entry_price_sol REAL,
                current_price_sol REAL,
                realized_pnl_sol REAL,
                unrealized_pnl_sol REAL,
                conviction TEXT,
                exit_plan TEXT,
                notes TEXT,
                alert_id TEXT,
                linked_narrative TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_wallets (
                wallet_id TEXT PRIMARY KEY,
                address TEXT UNIQUE NOT NULL,
                label TEXT,
                notes TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operator_notifications (
                notification_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                severity TEXT NOT NULL DEFAULT 'info',
                source_name TEXT,
                reference_id TEXT,
                reference_type TEXT,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_health_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                healthy INTEGER NOT NULL,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                extra_meta TEXT,
                sampled_at TEXT NOT NULL
            )
        """)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_holdings_token_address "
            "ON holdings (token_address)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_holdings_status ON holdings (status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_operator_notifications_read "
            "ON operator_notifications (read)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_operator_notifications_created "
            "ON operator_notifications (created_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_health_snapshots_source "
            "ON source_health_snapshots (source_name)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_health_snapshots_sampled "
            "ON source_health_snapshots (sampled_at)"
        )

        # --- Rejection diagnostics (schema v1-compatible additive) -----------
        # Compound PK (token_id, narrative_id) keeps only the most recent
        # evaluation per token-narrative pair.  INSERT OR REPLACE on this pair
        # naturally evicts the stale row.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rejected_candidates (
                token_id TEXT NOT NULL,
                narrative_id TEXT NOT NULL,
                token_name TEXT,
                token_symbol TEXT,
                narrative_name TEXT,
                score_id TEXT,
                alert_type TEXT NOT NULL,
                net_potential REAL,
                p_potential REAL,
                p_failure REAL,
                confidence_score REAL,
                watch_gap REAL,
                rejection_reasons TEXT,
                dimension_scores TEXT,
                risk_flags TEXT,
                data_gaps TEXT,
                rejected_at TEXT NOT NULL,
                PRIMARY KEY (token_id, narrative_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rejected_candidates_watch_gap "
            "ON rejected_candidates (watch_gap ASC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rejected_candidates_rejected_at "
            "ON rejected_candidates (rejected_at)"
        )

        self.connection.commit()
