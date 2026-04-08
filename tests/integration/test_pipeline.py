"""Integration test: full pipeline from demo data to alerts."""

import os
import tempfile

import pytest
import pytest_asyncio

from mctrend.config.settings import Settings
from mctrend.runner import build_system, inject_demo_data


@pytest.fixture
def temp_db():
    """Create a temporary database path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test.db")


@pytest.fixture
def settings(temp_db):
    """Settings with no external API keys and temp database."""
    return Settings(
        database_path=temp_db,
        pumpfun_api_url="",
        newsapi_key="",
        serpapi_key="",
        telegram_bot_token="",
        telegram_chat_id="",
        log_level="WARNING",
        log_format="console",
    )


class TestPipelineIntegration:
    def test_build_system(self, settings):
        """System builds without errors."""
        pipeline, db = build_system(settings)
        assert pipeline is not None
        assert db is not None
        db.close()

    def test_demo_data_injection(self, settings):
        """Demo data is injected correctly."""
        pipeline, db = build_system(settings)
        inject_demo_data(pipeline)

        tokens = pipeline.token_repo.list_by_status("new")
        assert len(tokens) >= 3  # At least DEEPMIND, MOONDOG, BRAVADO

        narratives = pipeline.narrative_repo.get_active(states=["EMERGING"])
        assert len(narratives) >= 3

        db.close()

    @pytest.mark.asyncio
    async def test_full_cycle(self, settings):
        """Full pipeline cycle processes demo data end-to-end."""
        pipeline, db = build_system(settings)
        inject_demo_data(pipeline)

        summary = await pipeline.run_cycle()

        assert summary["errors"] == []
        assert summary["links_created"] >= 2
        assert summary["tokens_scored"] >= 2
        assert summary["alerts_created"] >= 1

        # Verify alerts exist in DB
        active_alerts = pipeline.alert_repo.get_active()
        assert len(active_alerts) >= 1

        # Verify all alerts have required fields
        for alert in active_alerts:
            assert alert["alert_type"] in {
                "possible_entry", "high_potential_watch", "take_profit_watch",
                "verify", "watch", "exit_risk", "discard",
            }
            assert alert["net_potential"] is not None
            assert alert["p_potential"] is not None
            assert alert["p_failure"] is not None
            assert alert["confidence_score"] is not None
            assert alert["risk_flags"] is not None
            assert alert["reasoning"] is not None
            assert alert["token_name"] is not None
            assert alert["narrative_name"] is not None

        await pipeline.ingestion.close_all()
        await pipeline.delivery.close_all()
        db.close()

    @pytest.mark.asyncio
    async def test_idempotent_cycle(self, settings):
        """Running a second cycle doesn't duplicate data."""
        pipeline, db = build_system(settings)
        inject_demo_data(pipeline)

        summary1 = await pipeline.run_cycle()
        summary2 = await pipeline.run_cycle()

        # Second cycle should have fewer/no new links (tokens already linked)
        assert summary2["links_created"] == 0
        assert summary2["errors"] == []

        await pipeline.ingestion.close_all()
        await pipeline.delivery.close_all()
        db.close()

    @pytest.mark.asyncio
    async def test_stats_after_cycle(self, settings):
        """Pipeline stats reflect completed work."""
        pipeline, db = build_system(settings)
        inject_demo_data(pipeline)

        await pipeline.run_cycle()
        stats = pipeline.get_stats()

        assert stats["cycles_completed"] == 1
        assert stats["total_tokens_processed"] >= 2
        assert stats["total_alerts_generated"] >= 1
        assert isinstance(stats["source_health"], dict)

        await pipeline.ingestion.close_all()
        await pipeline.delivery.close_all()
        db.close()
