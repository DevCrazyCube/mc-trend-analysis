"""SQLite database manager for the MC Trend Analysis persistence layer."""

import sqlite3


class Database:
    """Manages the SQLite database connection and schema initialization."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create the database connection, enable WAL mode, and create all tables."""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def close(self) -> None:
        """Close the database connection."""
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _create_tables(self) -> None:
        """Create all tables and indices required by the system."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token_id TEXT PRIMARY KEY,
                address TEXT UNIQUE,
                name TEXT,
                symbol TEXT,
                description TEXT,
                deployed_by TEXT,
                launch_time TEXT,
                launch_platform TEXT,
                first_seen_by_system TEXT,
                initial_liquidity_usd REAL,
                initial_holder_count INTEGER,
                mint_authority_status TEXT,
                freeze_authority_status TEXT,
                status TEXT,
                linked_narratives TEXT,
                created_at TEXT,
                updated_at TEXT,
                data_gaps TEXT,
                data_sources TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chain_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                token_id TEXT,
                sampled_at TEXT,
                holder_count INTEGER,
                top_5_holder_pct REAL,
                top_10_holder_pct REAL,
                new_wallet_holder_pct REAL,
                liquidity_usd REAL,
                liquidity_locked INTEGER,
                liquidity_lock_hours INTEGER,
                liquidity_provider_count INTEGER,
                volume_1h_usd REAL,
                trade_count_1h INTEGER,
                unique_traders_1h INTEGER,
                deployer_known_bad INTEGER,
                deployer_prior_deployments INTEGER,
                data_source TEXT,
                data_gaps TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS narratives (
                narrative_id TEXT PRIMARY KEY,
                anchor_terms TEXT,
                related_terms TEXT,
                entities TEXT,
                description TEXT,
                attention_score REAL,
                narrative_velocity REAL,
                source_type_count INTEGER,
                state TEXT,
                sources TEXT,
                first_detected TEXT,
                peaked_at TEXT,
                dead_at TEXT,
                updated_at TEXT,
                extraction_confidence REAL,
                ambiguous INTEGER,
                data_gaps TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_narrative_links (
                link_id TEXT PRIMARY KEY,
                token_id TEXT,
                narrative_id TEXT,
                match_confidence REAL,
                match_method TEXT,
                match_signals TEXT,
                og_rank INTEGER,
                og_score REAL,
                og_signals TEXT,
                created_at TEXT,
                updated_at TEXT,
                status TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scored_tokens (
                score_id TEXT PRIMARY KEY,
                link_id TEXT,
                token_id TEXT,
                narrative_id TEXT,
                scored_at TEXT,
                narrative_relevance REAL,
                og_score REAL,
                rug_risk REAL,
                momentum_quality REAL,
                attention_strength REAL,
                timing_quality REAL,
                p_potential REAL,
                p_failure REAL,
                net_potential REAL,
                confidence_score REAL,
                risk_flags TEXT,
                data_gaps TEXT,
                dimension_details TEXT,
                data_freshness_status TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                token_id TEXT,
                token_address TEXT,
                token_name TEXT,
                token_symbol TEXT,
                narrative_id TEXT,
                narrative_name TEXT,
                link_id TEXT,
                score_id TEXT,
                alert_type TEXT,
                net_potential REAL,
                p_potential REAL,
                p_failure REAL,
                confidence_score REAL,
                dimension_scores TEXT,
                risk_flags TEXT,
                reasoning TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
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
                alert_id TEXT,
                channel_type TEXT,
                channel_id TEXT,
                attempted_at TEXT,
                status TEXT,
                failure_reason TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_gaps (
                gap_id TEXT PRIMARY KEY,
                source_type TEXT,
                source_name TEXT,
                started_at TEXT,
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
            "CREATE INDEX IF NOT EXISTS idx_alerts_token_id ON alerts (token_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_alert_type ON alerts (alert_type)"
        )

        self.connection.commit()
