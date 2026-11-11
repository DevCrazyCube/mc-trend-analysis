"""Tests for serving the built dashboard and for the health view's narrative counts."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mctrend.api.app import DashboardFiles, _is_client_route
from mctrend.api.routes.health import (
    LEGACY_NARRATIVE_STATES,
    NARRATIVE_LIFECYCLE_STATES,
    count_narratives_by_state,
)

INDEX_HTML = "<!doctype html><title>dashboard</title><div id=root></div>"


@pytest.fixture
def client(tmp_path):
    """An app shaped like the real one: an API route, then the dashboard at /."""
    (tmp_path / "index.html").write_text(INDEX_HTML)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")

    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    app.mount("/", DashboardFiles(directory=str(tmp_path), html=True), name="dashboard")
    return TestClient(app)


class TestDashboardFiles:
    def test_root_serves_index(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.text == INDEX_HTML

    def test_real_file_is_served_as_itself(self, client):
        response = client.get("/assets/app.js")
        assert response.status_code == 200
        assert response.text == "console.log('app')"

    @pytest.mark.parametrize(
        "path",
        ["/alerts", "/tokens", "/narratives", "/feed", "/holdings", "/config", "/alerts/"],
    )
    def test_client_route_gets_index(self, client, path):
        """A reload on a dashboard page, or a link to one, opens the dashboard."""
        response = client.get(path)
        assert response.status_code == 200
        assert response.text == INDEX_HTML

    def test_nested_client_route_gets_index(self, client):
        response = client.get("/tokens/abc123")
        assert response.status_code == 200
        assert response.text == INDEX_HTML

    def test_missing_asset_stays_404(self, client):
        """A missing script must not come back as HTML with a 200."""
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/favicon.ico").status_code == 404

    def test_api_route_still_answers(self, client):
        response = client.get("/api/ping")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_unknown_api_path_stays_404(self, client):
        """An unknown API path is an error for the caller, never the dashboard."""
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert INDEX_HTML not in response.text


class TestIsClientRoute:
    @pytest.mark.parametrize("path", ["alerts", "tokens/abc", "/narratives/", "feed"])
    def test_page_paths(self, path):
        assert _is_client_route(path) is True

    @pytest.mark.parametrize(
        "path",
        ["api", "api/alerts", "/api/health/sources", "assets/app.js", "favicon.ico", "a/b.css"],
    )
    def test_api_and_file_paths(self, path):
        assert _is_client_route(path) is False


class FakeNarrativeRepo:
    """Stands in for NarrativeRepository: only get_active(states=[one state])."""

    def __init__(self, by_state):
        self.by_state = by_state

    def get_active(self, states=None, limit=500):
        return [{"state": s} for s in states or [] for _ in range(self.by_state.get(s, 0))]


class TestCountNarrativesByState:
    def test_every_lifecycle_state_is_reported_also_at_zero(self):
        counts = count_narratives_by_state(FakeNarrativeRepo({}))
        assert list(counts) == NARRATIVE_LIFECYCLE_STATES
        assert set(counts.values()) == {0}

    def test_current_states_are_counted(self):
        """WEAK, RISING, TRENDING and FADING were missing from the health view."""
        repo = FakeNarrativeRepo({"WEAK": 4, "RISING": 2, "TRENDING": 3, "FADING": 1})
        counts = count_narratives_by_state(repo)
        assert counts["WEAK"] == 4
        assert counts["RISING"] == 2
        assert counts["TRENDING"] == 3
        assert counts["FADING"] == 1
        assert counts["EMERGING"] == 0
        assert counts["DEAD"] == 0

    def test_legacy_states_only_when_rows_exist(self):
        counts = count_narratives_by_state(FakeNarrativeRepo({"TRENDING": 1}))
        for state in LEGACY_NARRATIVE_STATES:
            assert state not in counts

        counts = count_narratives_by_state(FakeNarrativeRepo({"PEAKING": 2}))
        assert counts["PEAKING"] == 2
        assert "DECLINING" not in counts
