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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

from mctrend.alerting.engine import AlertEngine
from mctrend.config.settings import Settings
from mctrend.correlation.linker import CorrelationEngine
from mctrend.delivery.channels import ConsoleChannel, DeliveryRouter, TelegramChannel
from mctrend.ingestion.adapters.news import NewsAPIAdapter
from mctrend.ingestion.adapters.pumpfun import PumpFunAdapter
from mctrend.ingestion.adapters.trends import SerpAPITrendsAdapter
from mctrend.ingestion.manager import IngestionManager
from mctrend.normalization.normalizer import normalize_event, normalize_token
from mctrend.persistence.database import Database
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


def build_system(settings: Settings) -> tuple:
    """Build all system components from settings. Returns (pipeline, db)."""
    # Database
    db_path = settings.database_path
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    db = Database(db_path)
    db.initialize()

    # Ingestion
    ingestion = IngestionManager()

    if settings.pumpfun_api_url:
        ingestion.register_token_adapter(
            PumpFunAdapter(api_url=settings.pumpfun_api_url,
                           timeout=settings.external_api_timeout_seconds)
        )
    else:
        ingestion.register_token_adapter(
            PumpFunAdapter(timeout=settings.external_api_timeout_seconds)
        )

    if settings.newsapi_key:
        ingestion.register_event_adapter(
            NewsAPIAdapter(api_key=settings.newsapi_key,
                           timeout=settings.external_api_timeout_seconds)
        )

    if settings.serpapi_key:
        ingestion.register_event_adapter(
            SerpAPITrendsAdapter(api_key=settings.serpapi_key,
                                 timeout=settings.external_api_timeout_seconds)
        )

    # Correlation
    correlator = CorrelationEngine(
        min_confidence=settings.correlation.min_match_confidence
    )

    # Scoring — aggregator expects a plain dict; pass None to use built-in defaults
    scorer = ScoringAggregator(config=None)

    # Alert engine
    alert_repo = AlertRepository(db)
    alert_engine = AlertEngine(alert_repo=alert_repo)

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
    )

    return pipeline, db


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
    from mctrend.normalization.normalizer import normalize_chain_snapshot
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


async def run_once(settings: Settings, demo: bool = False):
    """Run a single processing cycle."""
    pipeline, db = build_system(settings)

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

    await pipeline.ingestion.close_all()
    await pipeline.delivery.close_all()
    db.close()


async def run_continuous(settings: Settings):
    """Run continuous polling loop."""
    pipeline, db = build_system(settings)

    shutdown = asyncio.Event()

    def handle_signal(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        shutdown.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("pipeline_starting_continuous",
                token_interval=settings.polling_interval_tokens,
                event_interval=settings.polling_interval_events)

    try:
        while not shutdown.is_set():
            summary = await pipeline.run_cycle()

            if summary.get("errors"):
                logger.warning("cycle_had_errors", errors=summary["errors"])

            # Wait for next cycle
            try:
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=settings.polling_interval_tokens
                )
            except asyncio.TimeoutError:
                pass  # Normal: timeout means we loop again
    finally:
        logger.info("pipeline_shutting_down")
        await pipeline.ingestion.close_all()
        await pipeline.delivery.close_all()
        db.close()


async def show_status(settings: Settings):
    """Show current system status."""
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


def main():
    parser = argparse.ArgumentParser(
        description="MC Trend Analysis — Real-time memecoin trend intelligence"
    )
    parser.add_argument("--once", action="store_true", help="Run single cycle and exit")
    parser.add_argument("--demo", action="store_true", help="Inject demo data for testing")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    args = parser.parse_args()

    settings = Settings.load(env_file=args.env)
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    if args.status:
        asyncio.run(show_status(settings))
    elif args.once or args.demo:
        asyncio.run(run_once(settings, demo=args.demo))
    else:
        asyncio.run(run_continuous(settings))


if __name__ == "__main__":
    main()
