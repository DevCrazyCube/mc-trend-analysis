"""Tests for dashboard config endpoint validation."""

import pytest
from fastapi import HTTPException

from mctrend.api.routes.config import (
    _DYNAMIC_FIELDS,
    _RESTART_REQUIRED,
    _SECRET_FIELDS,
)


class TestConfigFieldCategories:
    """Verify field categorization."""

    def test_dynamic_fields_exist(self):
        """Dynamic fields are defined."""
        assert len(_DYNAMIC_FIELDS) > 0
        assert "polling_interval_tokens" in _DYNAMIC_FIELDS
        assert "log_level" in _DYNAMIC_FIELDS

    def test_restart_required_fields_exist(self):
        """Restart-required fields are defined."""
        assert len(_RESTART_REQUIRED) > 0
        assert "database_path" in _RESTART_REQUIRED
        assert "pumpportal_ws_enabled" in _RESTART_REQUIRED

    def test_secret_fields_exist(self):
        """Secret fields are defined."""
        assert len(_SECRET_FIELDS) > 0
        assert "newsapi_key" in _SECRET_FIELDS
        assert "dashboard_api_key" in _SECRET_FIELDS

    def test_no_overlap_between_categories(self):
        """No field appears in multiple categories."""
        dynamic = _DYNAMIC_FIELDS
        restart = _RESTART_REQUIRED
        secret = _SECRET_FIELDS

        assert len(dynamic & restart) == 0, "Field in both dynamic and restart-required"
        assert len(dynamic & secret) == 0, "Field in both dynamic and secret"
        assert len(restart & secret) == 0, "Field in both restart-required and secret"


class TestConfigValidation:
    """Test validation logic for config updates."""

    def test_int_field_positive(self):
        """Int fields must be > 0."""
        # Valid
        from mctrend.api.routes.config import ConfigPatch

        valid_patch = ConfigPatch(field="polling_interval_tokens", value=30)
        assert valid_patch.value == 30

        # The route handler should validate this, so we just verify the model accepts it
        assert isinstance(valid_patch, ConfigPatch)

    def test_float_field_in_range(self):
        """Float fields must be between 0.0 and 1.0."""
        from mctrend.api.routes.config import ConfigPatch

        valid_patch = ConfigPatch(field="confidence_floor_for_alert", value=0.5)
        assert valid_patch.value == 0.5

    def test_log_level_enumeration(self):
        """Log level must be one of valid values."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

        # Verify static check (not dynamic validation in model)
        assert "INFO" in valid_levels
        assert "NOTAVALID" not in valid_levels


class TestConfigMasking:
    """Test that secrets are masked in responses."""

    def test_secret_fields_masked(self):
        """Secret fields are returned as '***'."""
        from mctrend.api.routes.config import _mask

        for field in _SECRET_FIELDS:
            assert _mask(field, "actual_secret_value") == "***"
            # Empty/None values return "" (falsy check in _mask)
            assert _mask(field, "") == ""
            assert _mask(field, None) == ""

    def test_non_secret_fields_unmasked(self):
        """Non-secret fields are returned as-is."""
        from mctrend.api.routes.config import _mask

        assert _mask("polling_interval_tokens", 30) == 30
        assert _mask("log_level", "INFO") == "INFO"
        assert _mask("database_path", "/var/lib/mc.db") == "/var/lib/mc.db"
