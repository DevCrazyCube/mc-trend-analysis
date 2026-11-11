"""Tests for database retention/cleanup policies."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from mctrend.persistence.database import Database


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize()
        yield db
        db.close()


class TestCleanupOldData:
    """Test retention/cleanup for unbounded tables."""

    def test_cleanup_deletes_old_notifications(self, temp_db):
        """cleanup_old_data deletes notifications older than N days."""
        cursor = temp_db.connection.cursor()

        # Create notifications: one new, one old
        now = datetime.now(timezone.utc).isoformat()
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        cursor.execute(
            """INSERT INTO operator_notifications
               (notification_id, category, title, body, severity, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("notif_new", "test", "New", "Body", "info", now),
        )
        cursor.execute(
            """INSERT INTO operator_notifications
               (notification_id, category, title, body, severity, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("notif_old", "test", "Old", "Body", "info", old_time),
        )
        temp_db.connection.commit()

        # Cleanup with 7-day retention
        result = temp_db.cleanup_old_data(notification_max_age_days=7)

        # Should delete 1 notification (the 10-day-old one)
        assert result["notifications_deleted"] == 1

        # Verify: new notification exists, old one is gone
        row_new = cursor.execute(
            "SELECT notification_id FROM operator_notifications WHERE notification_id = ?",
            ("notif_new",),
        ).fetchone()
        row_old = cursor.execute(
            "SELECT notification_id FROM operator_notifications WHERE notification_id = ?",
            ("notif_old",),
        ).fetchone()

        assert row_new is not None
        assert row_old is None

    def test_cleanup_deletes_old_snapshots(self, temp_db):
        """cleanup_old_data deletes snapshots older than N days."""
        cursor = temp_db.connection.cursor()

        # Create snapshots: one new, one old
        now = datetime.now(timezone.utc).isoformat()
        old_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        cursor.execute(
            """INSERT INTO source_health_snapshots
               (snapshot_id, source_name, healthy, consecutive_failures, sampled_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("snap_new", "pumpportal_ws", 1, 0, now),
        )
        cursor.execute(
            """INSERT INTO source_health_snapshots
               (snapshot_id, source_name, healthy, consecutive_failures, sampled_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("snap_old", "pumpportal_ws", 0, 3, old_time),
        )
        temp_db.connection.commit()

        # Cleanup with 3-day retention
        result = temp_db.cleanup_old_data(snapshot_max_age_days=3)

        # Should delete 1 snapshot (the 5-day-old one)
        assert result["snapshots_deleted"] == 1

        # Verify: new snapshot exists, old one is gone
        row_new = cursor.execute(
            "SELECT snapshot_id FROM source_health_snapshots WHERE snapshot_id = ?",
            ("snap_new",),
        ).fetchone()
        row_old = cursor.execute(
            "SELECT snapshot_id FROM source_health_snapshots WHERE snapshot_id = ?",
            ("snap_old",),
        ).fetchone()

        assert row_new is not None
        assert row_old is None

    def test_cleanup_returns_stats(self, temp_db):
        """cleanup_old_data returns deletion counts."""
        result = temp_db.cleanup_old_data()

        assert isinstance(result, dict)
        assert "notifications_deleted" in result
        assert "snapshots_deleted" in result
        assert isinstance(result["notifications_deleted"], int)
        assert isinstance(result["snapshots_deleted"], int)

    def test_cleanup_with_custom_retention_days(self, temp_db):
        """cleanup_old_data respects custom retention periods."""
        cursor = temp_db.connection.cursor()

        # Create notifications at different ages
        now = datetime.now(timezone.utc).isoformat()
        day3 = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        day5 = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        for i, time in enumerate([now, day3, day5]):
            cursor.execute(
                """INSERT INTO operator_notifications
                   (notification_id, category, title, body, severity, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"notif_{i}", "test", "Title", "Body", "info", time),
            )
        temp_db.connection.commit()

        # Cleanup with 4-day retention (should delete day5 only)
        result = temp_db.cleanup_old_data(notification_max_age_days=4)
        assert result["notifications_deleted"] == 1

    def test_cleanup_idempotent(self, temp_db):
        """cleanup_old_data can be called multiple times safely."""
        result1 = temp_db.cleanup_old_data()
        result2 = temp_db.cleanup_old_data()

        # Both should succeed, second call deletes 0 rows
        assert result2["notifications_deleted"] == 0
        assert result2["snapshots_deleted"] == 0
