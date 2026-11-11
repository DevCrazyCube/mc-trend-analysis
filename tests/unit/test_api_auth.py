"""Tests for dashboard API authentication."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from mctrend.api.auth import auth_is_configured, require_auth


class TestAuthIsConfigured:
    def test_auth_configured_when_key_set(self):
        """auth_is_configured returns True when DASHBOARD_API_KEY is set."""
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret123"}):
            assert auth_is_configured() is True

    def test_auth_not_configured_when_empty(self):
        """auth_is_configured returns False when DASHBOARD_API_KEY is empty."""
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}, clear=False):
            assert auth_is_configured() is False

    def test_auth_not_configured_when_missing(self):
        """auth_is_configured returns False when DASHBOARD_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Reload to ensure env is clean
            assert auth_is_configured() is False


class TestRequireAuth:
    def test_allows_access_when_no_key_configured(self):
        """require_auth allows access when no key is configured."""
        with patch.dict(os.environ, {}, clear=True):
            # Should not raise
            require_auth(credentials=None)

    def test_denies_access_when_credentials_missing_and_key_set(self):
        """require_auth denies access when credentials are missing but key is configured."""
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret123"}):
            with pytest.raises(HTTPException) as exc_info:
                require_auth(credentials=None)
            assert exc_info.value.status_code == 401
            assert "Invalid or missing API key" in exc_info.value.detail

    def test_denies_access_when_token_incorrect(self):
        """require_auth denies access when token does not match configured key."""
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "correct_key"}):
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong_key")
            with pytest.raises(HTTPException) as exc_info:
                require_auth(credentials=creds)
            assert exc_info.value.status_code == 401
            assert "Invalid or missing API key" in exc_info.value.detail

    def test_allows_access_when_token_correct(self):
        """require_auth allows access when token matches configured key."""
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "correct_key"}):
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="correct_key")
            # Should not raise
            require_auth(credentials=creds)

    def test_strips_whitespace_from_key(self):
        """require_auth strips whitespace from configured key."""
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": "  secret123  "}):
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret123")
            # Should not raise — whitespace stripped
            require_auth(credentials=creds)
