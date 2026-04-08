"""Simple bearer-token authentication for the dashboard API.

Designed for single-operator, local/VPS use.

If DASHBOARD_API_KEY is set in the environment, all API requests must
include:
    Authorization: Bearer <key>

If DASHBOARD_API_KEY is not set, the API is unrestricted with a startup
warning.  Sensitive config fields are always masked regardless.
"""

import os

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


def _get_api_key() -> str | None:
    return os.environ.get("DASHBOARD_API_KEY", "").strip() or None


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """FastAPI dependency — validates bearer token if a key is configured."""
    required_key = _get_api_key()
    if required_key is None:
        # No key configured — unrestricted access (operator chose this)
        return

    if credentials is None or credentials.credentials != required_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def auth_is_configured() -> bool:
    """Return True if a DASHBOARD_API_KEY is set."""
    return _get_api_key() is not None
