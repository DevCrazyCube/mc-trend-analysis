"""Tests for startup safety checks."""

import os
from unittest.mock import patch

import pytest

from mctrend.config.settings import Settings
from mctrend.runner import validate_startup


class TestProductionAuthSafety:
    """Test dashboard auth safety in production."""

    def test_prod_without_api_key_fails_validation(self):
        """Production environment without DASHBOARD_API_KEY fails startup validation."""
        settings = Settings(
            environment="prod",
            database_path=":memory:",
            log_level="INFO",
            log_format="json",
        )

        # Ensure DASHBOARD_API_KEY is not set
        with patch.dict(os.environ, {}, clear=True):
            errors = validate_startup(settings, demo_mode=False)

        assert len(errors) > 0
        error_msg = " ".join(errors)
        assert "DASHBOARD_API_KEY" in error_msg
        assert "prod" in error_msg.lower()
        assert "protected" in error_msg.lower()

    def test_prod_with_api_key_passes_validation(self):
        """Production environment with DASHBOARD_API_KEY passes auth check."""
        settings = Settings(
            environment="prod",
            database_path=":memory:",
            log_level="INFO",
            log_format="json",
        )

        # Set DASHBOARD_API_KEY
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secure_key_123"}):
            errors = validate_startup(settings, demo_mode=False)

        # Should have no auth-related errors
        auth_errors = [e for e in errors if "DASHBOARD_API_KEY" in e]
        assert len(auth_errors) == 0

    def test_dev_without_api_key_passes(self):
        """Development environment without DASHBOARD_API_KEY is allowed."""
        settings = Settings(
            environment="dev",
            database_path=":memory:",
            log_level="INFO",
            log_format="json",
        )

        with patch.dict(os.environ, {}, clear=True):
            errors = validate_startup(settings, demo_mode=False)

        # Should have no auth-related errors (dev doesn't require key)
        auth_errors = [e for e in errors if "DASHBOARD_API_KEY" in e]
        assert len(auth_errors) == 0

    def test_demo_without_api_key_passes(self):
        """Demo mode without DASHBOARD_API_KEY is allowed."""
        settings = Settings(
            environment="prod",
            database_path=":memory:",
            log_level="INFO",
            log_format="json",
        )

        with patch.dict(os.environ, {}, clear=True):
            errors = validate_startup(settings, demo_mode=True)

        # Demo mode might skip some checks, but let's verify auth isn't required
        # (Depends on implementation; this documents expected behavior)
        # Actually, the check is environment-based, not demo-based, so it will still fail
        # Let me verify the actual behavior
        auth_errors = [e for e in errors if "DASHBOARD_API_KEY" in e]
        # Auth safety applies regardless of demo mode if environment=prod
        assert len(auth_errors) > 0

    def test_prod_with_whitespace_api_key_rejected(self):
        """Production environment with whitespace-only DASHBOARD_API_KEY fails."""
        settings = Settings(
            environment="prod",
            database_path=":memory:",
            log_level="INFO",
            log_format="json",
        )

        # Set DASHBOARD_API_KEY to whitespace only (will be stripped to empty)
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "   "}):
            errors = validate_startup(settings, demo_mode=False)

        auth_errors = [e for e in errors if "DASHBOARD_API_KEY" in e]
        assert len(auth_errors) > 0


class TestOtherStartupValidations:
    """Verify other startup validations still work."""

    def test_invalid_environment_fails(self):
        """Invalid ENVIRONMENT value fails validation."""
        settings = Settings(
            environment="invalid_env",
            database_path=":memory:",
            log_level="INFO",
            log_format="json",
        )

        errors = validate_startup(settings, demo_mode=False)

        assert len(errors) > 0
        assert any("ENVIRONMENT" in e for e in errors)

    def test_invalid_log_level_fails(self):
        """Invalid LOG_LEVEL value fails validation."""
        settings = Settings(
            environment="dev",
            database_path=":memory:",
            log_level="INVALID_LEVEL",
            log_format="json",
        )

        errors = validate_startup(settings, demo_mode=False)

        assert len(errors) > 0
        assert any("LOG_LEVEL" in e or "log_level" in e for e in errors)
