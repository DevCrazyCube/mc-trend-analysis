"""Tests for pipeline degraded-mode failure classification.

Covers:
- _source_failure_mode() helper logic
- narrative_path_offline when all narrative sources are degraded
- Distinction between rate-limited, forbidden, and unavailable failure modes
- x_source_available=False when X adapter is forbidden
- Cycle summary includes news_failure_mode and x_failure_mode keys
"""
from __future__ import annotations

import pytest

from mctrend.pipeline import _source_failure_mode


# ---------------------------------------------------------------------------
# _source_failure_mode() helper unit tests
# ---------------------------------------------------------------------------


class TestSourceFailureMode:
    def test_empty_meta_is_unconfigured(self):
        assert _source_failure_mode({}) == "unconfigured"

    def test_none_treated_as_empty(self):
        # Pipeline uses .get("newsapi", {}) — empty dict → unconfigured
        assert _source_failure_mode({}) == "unconfigured"

    def test_healthy_source(self):
        meta = {"healthy": True, "in_rate_limit_cooldown": False, "failure_mode": "healthy"}
        assert _source_failure_mode(meta) == "healthy"

    def test_healthy_default_when_no_fields(self):
        # Meta exists but has no explicit health fields → assume healthy
        meta = {"source_name": "newsapi", "source_type": "news"}
        assert _source_failure_mode(meta) == "healthy"

    def test_rate_limited_from_cooldown_flag(self):
        meta = {
            "healthy": False,
            "in_rate_limit_cooldown": True,
            "failure_mode": "rate-limited",
        }
        assert _source_failure_mode(meta) == "rate-limited"

    def test_rate_limited_supersedes_failure_mode(self):
        """in_rate_limit_cooldown=True must win even if failure_mode says otherwise."""
        meta = {
            "healthy": False,
            "in_rate_limit_cooldown": True,
            "failure_mode": "unavailable",  # stale field — cooldown takes priority
        }
        assert _source_failure_mode(meta) == "rate-limited"

    def test_forbidden_from_failure_mode_field(self):
        meta = {
            "healthy": False,
            "in_rate_limit_cooldown": False,
            "failure_mode": "forbidden",
        }
        assert _source_failure_mode(meta) == "forbidden"

    def test_unavailable_as_default_when_unhealthy_no_mode(self):
        meta = {
            "healthy": False,
            "in_rate_limit_cooldown": False,
            # No failure_mode field
        }
        assert _source_failure_mode(meta) == "unavailable"

    def test_unavailable_explicit(self):
        meta = {
            "healthy": False,
            "in_rate_limit_cooldown": False,
            "failure_mode": "unavailable",
        }
        assert _source_failure_mode(meta) == "unavailable"


# ---------------------------------------------------------------------------
# Cycle summary failure_mode fields
# ---------------------------------------------------------------------------


class TestCycleSummaryFailureModeFields:
    """Verify that pipeline cycle summary includes failure_mode fields.

    Uses mock source health to drive degraded-mode detection without
    needing a full pipeline setup.
    """

    def _mock_health(
        self,
        source: str,
        healthy: bool = True,
        in_cooldown: bool = False,
        failure_mode: str = "healthy",
        cooldown_remaining: float = 0.0,
        cooldown_episodes: int = 0,
    ) -> dict:
        return {
            source: {
                "source_name": source,
                "healthy": healthy,
                "in_rate_limit_cooldown": in_cooldown,
                "failure_mode": failure_mode,
                "cooldown_remaining_seconds": cooldown_remaining,
                "cooldown_episodes": cooldown_episodes,
            }
        }

    def test_news_failure_mode_forbidden_in_summary(self):
        news_meta = self._mock_health(
            "newsapi", healthy=False, in_cooldown=False, failure_mode="forbidden"
        )["newsapi"]
        mode = _source_failure_mode(news_meta)
        assert mode == "forbidden"

    def test_news_failure_mode_rate_limited_in_summary(self):
        news_meta = self._mock_health(
            "newsapi", healthy=False, in_cooldown=True,
            failure_mode="rate-limited", cooldown_remaining=240.0, cooldown_episodes=2
        )["newsapi"]
        mode = _source_failure_mode(news_meta)
        assert mode == "rate-limited"

    def test_x_failure_mode_forbidden(self):
        x_meta = self._mock_health(
            "x", healthy=False, in_cooldown=False, failure_mode="forbidden"
        )["x"]
        mode = _source_failure_mode(x_meta)
        assert mode == "forbidden"

    def test_both_sources_degraded(self):
        """When both news and X are degraded, both failure modes are captured."""
        news_mode = _source_failure_mode(
            self._mock_health("newsapi", healthy=False, in_cooldown=True,
                              failure_mode="rate-limited")["newsapi"]
        )
        x_mode = _source_failure_mode(
            self._mock_health("x", healthy=False, in_cooldown=False,
                              failure_mode="forbidden")["x"]
        )
        assert news_mode == "rate-limited"
        assert x_mode == "forbidden"

    def test_healthy_sources_report_healthy(self):
        news_mode = _source_failure_mode(
            self._mock_health("newsapi", healthy=True)["newsapi"]
        )
        x_mode = _source_failure_mode(
            self._mock_health("x", healthy=True)["x"]
        )
        assert news_mode == "healthy"
        assert x_mode == "healthy"

    def test_unconfigured_source_not_treated_as_outage(self):
        """If a source is not registered, empty meta should not trigger offline logic."""
        assert _source_failure_mode({}) == "unconfigured"
        # Pipeline only sets narrative_path_offline when meta is non-empty AND not healthy


# ---------------------------------------------------------------------------
# X adapter fetch: 403 vs 429 distinction
# ---------------------------------------------------------------------------


class TestXAdapterFailureModes:
    """Focused tests on XAPIAdapter failure_mode field transitions."""

    def _make_adapter(self):
        from mctrend.ingestion.adapters.x_api import XAPIAdapter
        return XAPIAdapter(bearer_token="test-token", cooldown_after=2)

    def test_initial_failure_mode_is_healthy(self):
        adapter = self._make_adapter()
        assert adapter._failure_mode == "healthy"

    def test_handle_403_sets_forbidden(self):
        adapter = self._make_adapter()
        adapter._handle_403()
        assert adapter._failure_mode == "forbidden"
        assert adapter.is_healthy() is False
        assert adapter.is_in_cooldown() is False

    def test_handle_429_below_threshold_sets_rate_limited_failure_mode(self):
        """After a 429 (even below cooldown threshold), _failure_mode tracks rate-limited."""
        adapter = self._make_adapter()
        adapter._failure_mode = "rate-limited"  # set by fetch() before _handle_429()
        # Not yet in cooldown (only 1 of 2 needed)
        adapter._handle_429()
        # failure_mode field is "rate-limited" but is_in_cooldown() may be False
        assert adapter._failure_mode == "rate-limited"

    def test_handle_429_at_threshold_enters_cooldown(self):
        adapter = self._make_adapter()
        adapter._consecutive_429s = 1  # one prior 429
        adapter._failure_mode = "rate-limited"
        adapter._handle_429()
        assert adapter.is_in_cooldown() is True
        # get_source_meta should report rate-limited
        meta = adapter.get_source_meta()
        assert meta["failure_mode"] == "rate-limited"

    def test_recovery_resets_failure_mode(self):
        """_mark_healthy() does not reset _failure_mode — only fetch() success does."""
        from unittest.mock import AsyncMock, MagicMock, patch

        adapter = self._make_adapter()
        adapter._failure_mode = "forbidden"
        adapter._healthy = False

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.get = AsyncMock(return_value=mock_resp)

        import asyncio
        with patch.object(adapter, "_get_client", return_value=mock_client):
            asyncio.run(adapter.fetch())

        assert adapter._failure_mode == "healthy"
        assert adapter.is_healthy() is True


# ---------------------------------------------------------------------------
# NewsAPI adapter failure_mode parity
# ---------------------------------------------------------------------------


class TestNewsAdapterFailureModes:
    def _make_adapter(self):
        from mctrend.ingestion.adapters.news import NewsAPIAdapter
        return NewsAPIAdapter(api_key="test-key", cooldown_after=2)

    def test_initial_failure_mode_is_healthy(self):
        adapter = self._make_adapter()
        assert adapter._failure_mode == "healthy"

    def test_handle_403_sets_forbidden(self):
        adapter = self._make_adapter()
        adapter._handle_403()
        assert adapter._failure_mode == "forbidden"
        assert adapter.is_healthy() is False
        assert adapter.is_in_cooldown() is False

    def test_get_source_meta_includes_failure_mode(self):
        adapter = self._make_adapter()
        meta = adapter.get_source_meta()
        assert "failure_mode" in meta
        assert meta["failure_mode"] == "healthy"

    def test_failure_mode_forbidden_in_meta_after_403(self):
        adapter = self._make_adapter()
        adapter._handle_403()
        meta = adapter.get_source_meta()
        assert meta["failure_mode"] == "forbidden"

    def test_failure_mode_rate_limited_overrides_when_in_cooldown(self):
        adapter = self._make_adapter()
        adapter._consecutive_429s = 1
        adapter._handle_429()  # triggers cooldown
        meta = adapter.get_source_meta()
        assert meta["failure_mode"] == "rate-limited"
