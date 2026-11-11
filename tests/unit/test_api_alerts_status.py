"""Tests for the alert routes' status filter.

Alerts are stored with an upper-case status (the alert engine writes ACTIVE,
retirement writes RETIRED), while the routes take ``status=active`` /
``status=retired`` and report a lower-case group status.  These tests pin that
the two meet.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mctrend.api.deps import get_db
from mctrend.api.routes import alerts as alerts_routes
from mctrend.persistence.database import Database


def _alert(alert_id: str, status: str, narrative: str, updated_at: str) -> dict:
    return {
        "alert_id": alert_id,
        "token_id": f"token-{alert_id}",
        "token_address": f"ADDR{alert_id}",
        "token_name": f"TOKEN{alert_id}",
        "narrative_name": narrative,
        "alert_type": "watch",
        "net_potential": 0.3,
        "confidence_score": 0.7,
        "status": status,
        "created_at": updated_at,
        "updated_at": updated_at,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)

    db = Database(str(tmp_path / "alerts.db"))
    db.initialize()
    # These rows stand alone: no token, narrative or score rows behind them.
    db.connection.execute("PRAGMA foreign_keys = OFF")

    rows = [
        _alert("1", "ACTIVE", "alpha", "2026-01-01T00:00:01+00:00"),
        _alert("2", "RETIRED", "alpha", "2026-01-01T00:00:02+00:00"),
        _alert("3", "RETIRED", "beta", "2026-01-01T00:00:03+00:00"),
        _alert("4", "EXPIRED", "beta", "2026-01-01T00:00:04+00:00"),
        # The column default is lower-case; a row written that way still counts.
        _alert("5", "active", "gamma", "2026-01-01T00:00:05+00:00"),
    ]
    for row in rows:
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        db.connection.execute(
            f"INSERT INTO alerts ({columns}) VALUES ({marks})", list(row.values())
        )
    db.connection.commit()

    app = FastAPI()
    app.include_router(alerts_routes.router)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    db.close()


def _ids(payload: dict) -> set[str]:
    return {a["alert_id"] for a in payload["alerts"]}


class TestListAlerts:
    def test_no_filter_returns_every_alert(self, client):
        payload = client.get("/api/alerts").json()
        assert _ids(payload) == {"1", "2", "3", "4", "5"}
        assert payload["count"] == 5

    def test_active_filter_finds_stored_upper_case_rows(self, client):
        payload = client.get("/api/alerts?status=active").json()
        assert _ids(payload) == {"1", "5"}

    def test_retired_filter_finds_retired_and_expired(self, client):
        payload = client.get("/api/alerts?status=retired").json()
        assert _ids(payload) == {"2", "3", "4"}

    def test_filter_value_is_not_case_sensitive(self, client):
        assert _ids(client.get("/api/alerts?status=ACTIVE").json()) == {"1", "5"}

    def test_newest_first_and_limit(self, client):
        payload = client.get("/api/alerts?limit=2").json()
        assert [a["alert_id"] for a in payload["alerts"]] == ["5", "4"]


class TestAlertsByNarrative:
    def _groups(self, client, query=""):
        payload = client.get(f"/api/alerts/by-narrative{query}").json()
        return {g["narrative_name"]: g for g in payload["groups"]}

    def test_group_with_an_active_alert_is_active(self, client):
        groups = self._groups(client)
        assert groups["alpha"]["status"] == "active"
        assert groups["alpha"]["alert_count"] == 2
        assert groups["gamma"]["status"] == "active"

    def test_group_without_an_active_alert_is_retired(self, client):
        assert self._groups(client)["beta"]["status"] == "retired"

    def test_active_filter_keeps_only_active_alerts(self, client):
        groups = self._groups(client, "?status=active")
        assert set(groups) == {"alpha", "gamma"}
        assert groups["alpha"]["alert_count"] == 1

    def test_retired_filter_keeps_only_retired_alerts(self, client):
        groups = self._groups(client, "?status=retired")
        assert set(groups) == {"alpha", "beta"}
        assert groups["alpha"]["alert_count"] == 1
        assert groups["beta"]["alert_count"] == 2
        assert groups["beta"]["status"] == "retired"
