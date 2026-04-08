"""
CLI entrypoint and main runner for the MC Trend Analysis system.

Usage:
    python -m mctrend.runner              # Run continuous polling loop
    python -m mctrend.runner --once       # Run single cycle and exit
    python -m mctrend.runner --status     # Show system status and exit
    python -m mctrend.runner --demo       # Run with synthetic demo data
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

from mctrend.alerting.engine import AlertEngine
from mctrend.config.settings import Settings
from mctrend.correlation.linker import CorrelationEngine
from mctrend.delivery.channels import ConsoleChannel, DeliveryRouter, TelegramChannel
from mctrend.ingestion.adapters.news import NewsAPIAdapter
from mctrend.ingestion.adapters.pumpfun import PumpFunAdapter
from mctrend.ingestion.adapters.pumpportal_ws import PumpPortalWebSocketAdapter
from mctrend.ingestion.adapters.solana_rpc import SolanaRPCAdapter
from mctrend.ingestion.adapters.trends import SerpAPITrendsAdapter
from mctrend.ingestion.manager import IngestionManager
from mctrend.normalization.normalizer import normalize_event, normalize_token
from mctrend.persistence.database import Database, SchemaVersionError
from mctrend.persistence.repositories import (
    AlertRepository,
    NarrativeRepository,
    SourceGapRepository,
    TokenRepository,
)
from mctrend.pipeline import Pipeline
from mctrend.scoring.aggregator import ScoringAggregator
from mctrend.utils.logging import configure_logging

logger = structlog.get_logger(__name__)

_VALID_ENVIRONMENTS = {"demo", "dev", "prod"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


# ---------------------------------------------------------------------------
# Startup validation (D-1, D-2)
# ---------------------------------------------------------------------------


def _source_status_map(settings: Settings, demo_mode: bool) -> dict[str, str]:
    """Return a mapping of source name → status label.

    Labels:
      demo-disabled   — live adapter suppressed because --demo mode is active
      enabled         — adapter will be registered and will attempt fetches
      unsupported     — adapter code exists but upstream API is non-functional
      disabled        — no API key / config provided
    """
    status: dict[str, str] = {}

    if demo_mode:
        status["pump.fun"] = "demo-disabled"
        status["pumpportal_ws"] = "demo-disabled"
        status["solana_rpc"] = "demo-disabled"
        status["newsapi"] = "demo-disabled"
        status["serpapi_trends"] = "demo-disabled"
    else:
        # pumpportal_ws — primary discovery path
        if settings.pumpportal_ws_enabled:
            status["pumpportal_ws"] = "enabled (WebSocket real-time discovery)"
        else:
            status["pumpportal_ws"] = (
                "disabled (set PUMPPORTAL_WS_ENABLED=true to enable real-time discovery)"
            )
        # pump.fun REST — only registered when PUMPFUN_API_URL is explicitly set
        if settings.pumpfun_api_url:
            status["pump.fun"] = "enabled-unreliable"
        else:
            status["pump.fun"] = (
                "unsupported (default endpoint non-functional — "
                "set PUMPFUN_API_URL to a token listing REST API)"
            )
        # solana_rpc — enabled (public RPC, rate-limited but usable)
        status["solana_rpc"] = "enabled"
        # newsapi
        status["newsapi"] = "enabled" if settings.newsapi_key else "disabled (NEWSAPI_KEY not set)"
        # serpapi_trends — API discontinued regardless of key
        status["serpapi_trends"] = "unsupported (SerpAPI endpoint discontinued)"

    # Delivery channels
    if settings.telegram_bot_token and settings.telegram_chat_id:
        status["telegram_delivery"] = "enabled"
    else:
        status["telegram_delivery"] = "disabled (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)"

    if settings.webhook_url:
        status["webhook_delivery"] = "enabled"

    return status


def validate_startup(settings: Settings, demo_mode: bool = False) -> list[str]:
    """Validate settings and system preconditions before startup.

    Returns a list of error strings. An empty list means all checks passed.
    Failures are printed with clear messages so operators can fix them quickly.
    """
    errors: list[str] = []

    # Environment
    if settings.environment not in _VALID_ENVIRONMENTS:
        errors.append(
            f"ENVIRONMENT={settings.environment!r} is not valid. "
            f"Must be one of: {sorted(_VALID_ENVIRONMENTS)}"
        )

    # Dashboard auth safety in production
    if settings.environment == "prod":
        dashboard_api_key = os.environ.get("DASHBOARD_API_KEY", "").strip()
        if not dashboard_api_key:
            errors.append(
                "DASHBOARD_API_KEY is not set, but ENVIRONMENT=prod. "
                "In production, the dashboard API MUST be protected by a strong API key. "
                "Set DASHBOARD_API_KEY to a secure random value (e.g., 32+ char, alphanumeric+symbols). "
                "Without this, the dashboard will be publicly accessible and anyone can read/modify system config."
            )

    # Log level
    if settings.log_level.upper() not in _VALID_LOG_LEVELS:
        errors.append(
            f"LOG_LEVEL={settings.log_level!r} is not valid. "
            f"Must be one of: {sorted(_VALID_LOG_LEVELS)}"
        )

    # Database path writable
    db_path = Path(settings.database_path)
    db_dir = db_path.parent if db_path.parent != Path(".") else Path(".")
    if db_dir != Path(".") and not db_dir.exists():
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(
                f"Cannot create database directory {db_dir}: {e}. "
                "Ensure the directory is writable."
            )
    elif db_path.exists() and not os.access(db_path, os.W_OK):
        errors.append(
            f"Database file {db_path} is not writable. "
            "Check file permissions."
        )

    source_status = _source_status_map(settings, demo_mode)
    logger.info(
        "startup_source_check",
        environment=settings.environment,
        demo_mode=demo_mode,
        source_status=source_status,
    )

    return errors


# ---------------------------------------------------------------------------
# System builder
# ---------------------------------------------------------------------------


def build_system(settings: Settings, demo_mode: bool = False) -> tuple:
    """Build all system components from settings. Returns (pipeline, db).

    When *demo_mode* is True, no live external adapters are registered.
    Ingestion is a no-op — the pipeline runs only on data injected by
    ``inject_demo_data()``.  No HTTP calls are made during the cycle.
    """
    # Database
    db_path = settings.database_path
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    db = Database(db_path)
    db.initialize()

    # Ingestion
    ingestion = IngestionManager()

    ws_adapter: PumpPortalWebSocketAdapter | None = None

    if demo_mode:
        # Demo mode: no live adapters registered → zero external HTTP calls.
        # All data comes from inject_demo_data() called before run_cycle().
        logger.info("demo_mode_no_live_adapters")
    else:
        # Live adapters — register in order of reliability.

        # PumpPortal WebSocket: primary real-time discovery path.
        if settings.pumpportal_ws_enabled:
            ws_adapter = PumpPortalWebSocketAdapter(
                ws_url=settings.pumpportal_ws_url,
                stale_timeout_seconds=settings.pumpportal_ws_stale_timeout_seconds,
            )
            ingestion.register_token_adapter(ws_adapter)
            logger.info(
                "pumpportal_ws_adapter_registered",
                url=settings.pumpportal_ws_url,
            )
        else:
            logger.info(
                "pumpportal_ws_disabled",
                hint="Set PUMPPORTAL_WS_ENABLED=true to enable real-time token discovery",
            )

        # Pump.fun REST: only register when an explicit URL is configured.
        # The default public endpoint is non-functional (persistent 503).
        if settings.pumpfun_api_url:
            ingestion.register_token_adapter(
                PumpFunAdapter(
                    api_url=settings.pumpfun_api_url,
                    timeout=settings.external_api_timeout_seconds,
                    fetch_limit=settings.pumpfun_fetch_limit,
                )
            )
        elif not settings.pumpportal_ws_enabled:
            # Neither WS nor REST discovery is configured
            logger.warning(
                "live_token_discovery_unavailable",
                reason=(
                    "No token discovery source configured. "
                    "Set PUMPPORTAL_WS_ENABLED=true for real-time WebSocket discovery, "
                    "or PUMPFUN_API_URL to a working token listing REST API."
                ),
            )

        # SolanaRPC — for on-chain enrichment; public endpoint, rate-limited.
        ingestion.register_token_adapter(
            SolanaRPCAdapter(
                rpc_url=settings.solana_rpc_url,
                timeout=settings.external_api_timeout_seconds,
            )
        )

        if settings.newsapi_key:
            ingestion.register_event_adapter(
                NewsAPIAdapter(
                    api_key=settings.newsapi_key,
                    timeout=settings.external_api_timeout_seconds,
                    query_terms=settings.news_query_terms,
                    page_size=settings.news_page_size,
                    signal_strength=settings.news_signal_strength,
                )
            )

        # SerpAPI trends: adapter is marked SUPPORTED=False (API discontinued).
        # Do not register regardless of whether a key is set.
        if settings.serpapi_key:
            logger.warning(
                "serpapi_key_set_but_adapter_unsupported",
                reason=SerpAPITrendsAdapter.UNSUPPORTED_REASON,
            )

    # Correlation
    correlator = CorrelationEngine(
        min_confidence=settings.correlation.min_match_confidence
    )

    # Scoring — aggregator expects a plain dict; pass None to use built-in defaults
    scorer = ScoringAggregator(config=None)

    # Alert engine
    alert_repo = AlertRepository(db)
    alert_engine = AlertEngine(
        alert_repo=alert_repo,
        history_max_entries=settings.alert_history_max_entries,
    )

    # Delivery
    delivery = DeliveryRouter(rate_limit_per_10min=settings.alert_rate_limit_per_10min)
    delivery.add_channel(ConsoleChannel())

    if settings.telegram_bot_token and settings.telegram_chat_id:
        delivery.add_channel(
            TelegramChannel(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                timeout=settings.external_api_timeout_seconds,
            )
        )

    # Pipeline
    pipeline = Pipeline(
        db=db,
        ingestion=ingestion,
        correlator=correlator,
        scorer=scorer,
        alert_engine=alert_engine,
        delivery=delivery,
        settings=settings,
    )

    return pipeline, db, ws_adapter


# ---------------------------------------------------------------------------
# Demo data injection
# ---------------------------------------------------------------------------


def inject_demo_data(pipeline: Pipeline):
    """Inject synthetic demo data to demonstrate the system without live APIs."""
    now = datetime.now(timezone.utc)

    logger.info("injecting_demo_data")

    # Create some narratives
    narratives = [
        {
            "anchor_terms": ["DEEPMIND", "GOOGLE", "AI"],
            "related_terms": ["GEMINI", "ARTIFICIAL", "INTELLIGENCE"],
            "description": "Google DeepMind announces major AI breakthrough",
            "source_type": "news",
            "source_name": "demo_news",
            "signal_strength": 0.85,
            "published_at": now.isoformat(),
        },
        {
            "anchor_terms": ["MOONDOG", "SPACE", "DOG"],
            "related_terms": ["BALLOON", "NASA", "VIRAL"],
            "description": "Viral video of dog in space balloon experiment",
            "source_type": "search_trends",
            "source_name": "demo_trends",
            "signal_strength": 0.78,
            "published_at": now.isoformat(),
        },
        {
            "anchor_terms": ["BRAVADO", "BOXING", "CHAMPION"],
            "related_terms": ["FIGHT", "KNOCKOUT", "VIRAL"],
            "description": "Boxing championship viral victory moment",
            "source_type": "news",
            "source_name": "demo_news",
            "signal_strength": 0.72,
            "published_at": now.isoformat(),
        },
    ]

    for raw_event in narratives:
        normalized = normalize_event(raw_event)
        if normalized:
            pipeline.narrative_repo.save(normalized)

    # Create tokens that match these narratives
    tokens = [
        {
            "address": "DEMO1111111111111111111111111111111111111111",
            "name": "DEEPMIND",
            "symbol": "DEEPMIND",
            "description": "The original DeepMind token",
            "deployed_by": "DemoDeployer1111111111111111111111111111111",
            "launch_time": (now - timedelta(minutes=8)).isoformat(),
            "launch_platform": "pump.fun",
            "initial_liquidity_usd": 4200.0,
            "initial_holder_count": 47,
            "data_source": "demo",
        },
        {
            "address": "DEMO2222222222222222222222222222222222222222",
            "name": "DMIND",
            "symbol": "DMIND",
            "description": "DeepMind copycat",
            "deployed_by": "DemoDeployer2222222222222222222222222222222",
            "launch_time": (now - timedelta(minutes=3)).isoformat(),
            "launch_platform": "pump.fun",
            "initial_liquidity_usd": 1500.0,
            "initial_holder_count": 12,
            "data_source": "demo",
        },
        {
            "address": "DEMO3333333333333333333333333333333333333333",
            "name": "MOONDOG",
            "symbol": "MOONDOG",
            "description": "To the moon, dog!",
            "deployed_by": "DemoDeployer3333333333333333333333333333333",
            "launch_time": (now - timedelta(minutes=11)).isoformat(),
            "launch_platform": "pump.fun",
            "initial_liquidity_usd": 5800.0,
            "initial_holder_count": 89,
            "data_source": "demo",
        },
        {
            "address": "DEMO4444444444444444444444444444444444444444",
            "name": "BRAVADO",
            "symbol": "BRAVADO",
            "description": "Victory moment token",
            "deployed_by": "BadDeployer444444444444444444444444444444444",
            "launch_time": (now - timedelta(minutes=5)).isoformat(),
            "launch_platform": "pump.fun",
            "initial_liquidity_usd": 800.0,
            "initial_holder_count": 15,
            "data_source": "demo",
        },
    ]

    for raw_token in tokens:
        normalized = normalize_token(raw_token)
        if normalized:
            pipeline.token_repo.save(normalized)

    # Add some chain snapshots with varied risk profiles
    import uuid

    snapshots = [
        {  # DEEPMIND - moderate risk
            "token_id_lookup": "DEMO1111111111111111111111111111111111111111",
            "holder_count": 47,
            "top_5_holder_pct": 0.41,
            "top_10_holder_pct": 0.58,
            "liquidity_usd": 4200.0,
            "liquidity_locked": False,
            "volume_1h_usd": 8400.0,
            "trade_count_1h": 127,
            "unique_traders_1h": 89,
        },
        {  # MOONDOG - lower risk
            "token_id_lookup": "DEMO3333333333333333333333333333333333333333",
            "holder_count": 89,
            "top_5_holder_pct": 0.28,
            "top_10_holder_pct": 0.42,
            "liquidity_usd": 5800.0,
            "liquidity_locked": True,
            "liquidity_lock_hours": 48,
            "volume_1h_usd": 12000.0,
            "trade_count_1h": 245,
            "unique_traders_1h": 178,
        },
        {  # BRAVADO - high risk
            "token_id_lookup": "DEMO4444444444444444444444444444444444444444",
            "holder_count": 15,
            "top_5_holder_pct": 0.82,
            "top_10_holder_pct": 0.95,
            "liquidity_usd": 800.0,
            "liquidity_locked": False,
            "volume_1h_usd": 500.0,
            "trade_count_1h": 20,
            "unique_traders_1h": 8,
        },
    ]

    for snap_data in snapshots:
        token = pipeline.token_repo.get_by_address(snap_data.pop("token_id_lookup"))
        if token:
            snapshot = {
                "snapshot_id": str(uuid.uuid4()),
                "token_id": token["token_id"],
                "sampled_at": now.isoformat(),
                "data_source": "demo",
                "data_gaps": [],
                "deployer_known_bad": False,
                "deployer_prior_deployments": None,
                **{k: snap_data.get(k) for k in [
                    "holder_count", "top_5_holder_pct", "top_10_holder_pct",
                    "new_wallet_holder_pct", "liquidity_usd", "liquidity_locked",
                    "liquidity_lock_hours", "liquidity_provider_count",
                    "volume_1h_usd", "trade_count_1h", "unique_traders_1h",
                ]},
            }
            pipeline.token_repo.save_chain_snapshot(snapshot)

    logger.info("demo_data_injected", tokens=len(tokens), narratives=len(narratives))


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------


async def run_once(settings: Settings, demo: bool = False):
    """Run a single processing cycle.

    When *demo* is True, no live adapters are registered and only synthetic
    data (injected by ``inject_demo_data``) is processed.
    """
    pipeline, db, ws_adapter = build_system(settings, demo_mode=demo)

    # Start WS adapter if registered
    if ws_adapter is not None:
        ws_adapter.start_background_task()
        # Brief settle time so first cycle has some events
        await asyncio.sleep(2)

    if demo:
        inject_demo_data(pipeline)

    summary = await pipeline.run_cycle()

    print("\n--- Cycle Summary ---")
    for key, value in summary.items():
        if key != "errors" or value:
            print(f"  {key}: {value}")

    stats = pipeline.get_stats()
    print("\n--- System Stats ---")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    if ws_adapter is not None:
        await ws_adapter.stop()
    await pipeline.ingestion.close_all()
    await pipeline.delivery.close_all()
    db.close()


async def run_continuous(settings: Settings, dashboard: bool = False):
    """Run continuous polling loop with graceful shutdown on SIGINT/SIGTERM."""
    from mctrend.api import deps as api_deps

    pipeline, db, ws_adapter = build_system(settings)

    # Register DB and WS adapter with the API layer
    api_deps.set_db(db)
    api_deps.set_pipeline_start_time(time.time())
    if ws_adapter is not None:
        api_deps.set_ws_adapter(ws_adapter)

    # Start WebSocket adapter background task
    if ws_adapter is not None:
        ws_adapter.start_background_task()
        logger.info("pumpportal_ws_started")

    # Shutdown flag — set by signal handlers; cycle completes before exit
    shutdown = asyncio.Event()

    def handle_signal(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        shutdown.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info(
        "pipeline_starting_continuous",
        environment=settings.environment,
        token_interval=settings.polling_interval_tokens,
        event_interval=settings.polling_interval_events,
        dashboard=dashboard,
    )

    tasks = []

    # Start dashboard server if requested
    if dashboard:
        import uvicorn
        from mctrend.api.app import create_app

        app = create_app()

        config = uvicorn.Config(
            app,
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            log_level="warning",  # suppress uvicorn noise; use structlog
            access_log=False,
        )
        server = uvicorn.Server(config)
        tasks.append(asyncio.create_task(server.serve(), name="dashboard_server"))
        logger.info(
            "dashboard_starting",
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            url=f"http://{settings.dashboard_host}:{settings.dashboard_port}",
        )
        print(
            f"\n  Dashboard: http://{settings.dashboard_host}:{settings.dashboard_port}\n"
        )

    from mctrend.api.routes.events import broadcast

    try:
        while not shutdown.is_set():
            summary = await pipeline.run_cycle()

            # Update dashboard cycle stats and broadcast
            api_deps.update_cycle_stats(summary)
            broadcast("cycle_complete", summary)

            if summary.get("errors"):
                logger.warning("cycle_had_errors", errors=summary["errors"])

            # Wait for next cycle — interruptible by shutdown signal
            try:
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=settings.polling_interval_tokens,
                )
            except asyncio.TimeoutError:
                pass  # Normal: timeout means we loop again
    finally:
        logger.info("pipeline_shutting_down", reason="signal_received")
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if ws_adapter is not None:
            await ws_adapter.stop()
        await pipeline.ingestion.close_all()
        await pipeline.delivery.close_all()
        db.close()
        logger.info("pipeline_stopped")


async def show_status(settings: Settings):
    """Show current system status including DB size."""
    db_path = settings.database_path
    if not Path(db_path).exists():
        print(f"Database not found at {db_path}. System has not been run yet.")
        return

    db = Database(db_path)
    db.initialize()

    token_repo = TokenRepository(db)
    narrative_repo = NarrativeRepository(db)
    alert_repo = AlertRepository(db)
    gap_repo = SourceGapRepository(db)

    print("=== MC Trend Analysis System Status ===\n")
    print(f"  Environment: {settings.environment}")
    print(f"  Database:    {db_path}")
    db_size_mb = db.get_size_bytes() / (1024 * 1024)
    print(f"  DB size:     {db_size_mb:.2f} MB\n")

    # Token counts by status
    for status in ["new", "linked", "scored", "alerted", "expired", "discarded"]:
        count = len(token_repo.list_by_status(status))
        if count > 0:
            print(f"  Tokens ({status}): {count}")

    # Active narratives
    for state in ["EMERGING", "PEAKING", "DECLINING", "DEAD"]:
        narratives = narrative_repo.get_active(states=[state])
        if narratives:
            print(f"  Narratives ({state}): {len(narratives)}")

    # Active alerts
    active_alerts = alert_repo.get_active()
    print(f"\n  Active alerts: {len(active_alerts)}")
    for alert in active_alerts[:10]:
        atype = alert.get("alert_type", "?")
        name = alert.get("token_name", "?")
        net = alert.get("net_potential", 0)
        print(f"    [{atype}] {name} net_potential={net:.2f}")

    # Source gaps
    gaps = gap_repo.get_open_gaps()
    if gaps:
        print(f"\n  Open source gaps: {len(gaps)}")
        for gap in gaps:
            print(f"    {gap.get('source_name')} since {gap.get('started_at')}")

    db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="MC Trend Analysis — Real-time memecoin trend intelligence"
    )
    parser.add_argument("--once", action="store_true", help="Run single cycle and exit")
    parser.add_argument("--demo", action="store_true", help="Inject demo data for testing")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start operator dashboard API server alongside the pipeline",
    )
    parser.add_argument("--env", default=".env", help="Path to .env file")
    args = parser.parse_args()

    settings = Settings.load(env_file=args.env)
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    logger.info("system_starting", environment=settings.environment)

    # Run startup validation — fail fast with clear diagnostics
    errors = validate_startup(settings, demo_mode=args.demo)
    if errors:
        print("\n[STARTUP VALIDATION FAILED]", file=sys.stderr)
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        print("\nFix the above errors before starting the system.", file=sys.stderr)
        sys.exit(1)

    try:
        if args.status:
            asyncio.run(show_status(settings))
        elif args.once or args.demo:
            asyncio.run(run_once(settings, demo=args.demo))
        else:
            asyncio.run(run_continuous(settings, dashboard=args.dashboard))
    except SchemaVersionError as e:
        print(f"\n[SCHEMA VERSION ERROR] {e}", file=sys.stderr)
        print(
            "Remove the database file and restart, or apply a migration.",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as e:
        logger.exception("fatal_error", error=str(e))
        sys.exit(3)


if __name__ == "__main__":
    main()
