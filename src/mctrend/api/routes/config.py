"""Configuration read/update routes.

Only non-sensitive, dynamic settings are exposed for in-dashboard editing.
Secrets (API keys, tokens) are masked and cannot be updated via the API.
Restart-required settings are clearly labeled.

Write operations validate the new values before applying.  Settings are
written to the running process memory only — a restart is required for
any restart-required field to take permanent effect.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from mctrend.api.auth import require_auth

router = APIRouter(prefix="/api/config", tags=["config"])

# Settings that can be changed at runtime without restart
_DYNAMIC_FIELDS = {
    "polling_interval_tokens",
    "polling_interval_events",
    "alert_rate_limit_per_10min",
    "max_token_age_hours",
    "confidence_floor_for_alert",
    "news_signal_strength",
    "pumpfun_fetch_limit",
    "news_page_size",
    "log_level",
}

# Fields that require restart to take effect
_RESTART_REQUIRED = {
    "environment",
    "database_path",
    "solana_rpc_url",
    "pumpfun_api_url",
    "log_format",
    "pumpportal_ws_enabled",
    "pumpportal_ws_url",
    "pumpportal_ws_stale_timeout_seconds",
    "dashboard_port",
    "dashboard_host",
}

# Fields that are masked (secrets) — shown as "***" in GET responses
_SECRET_FIELDS = {
    "newsapi_key",
    "serpapi_key",
    "twitter_bearer_token",
    "telegram_bot_token",
    "telegram_chat_id",
    "webhook_url",
    "webhook_secret",
    "dashboard_api_key",
}

_runtime_overrides: dict[str, Any] = {}


def _mask(key: str, value: Any) -> Any:
    if key in _SECRET_FIELDS:
        return "***" if value else ""
    return value


@router.get("")
async def get_config(_: None = Depends(require_auth)):
    """Return current effective configuration with secrets masked."""
    from mctrend.config.settings import Settings

    # Load fresh from environment
    settings = Settings.load()
    data = settings.model_dump(
        exclude={
            "potential_weights", "failure_weights", "rug_risk_category_weights",
            "rug_risk_missing_data_defaults", "confidence_weights",
            "og_resolution", "correlation", "alert_thresholds", "alert_expiry_minutes",
        }
    )

    # Apply runtime overrides
    data.update(_runtime_overrides)

    # Mask secrets
    masked = {k: _mask(k, v) for k, v in data.items()}

    # Annotate each field with metadata
    result = {}
    for k, v in masked.items():
        result[k] = {
            "value": v,
            "dynamic": k in _DYNAMIC_FIELDS,
            "restart_required": k in _RESTART_REQUIRED,
            "secret": k in _SECRET_FIELDS,
        }

    return {"config": result}


@router.get("/weights")
async def get_weights(_: None = Depends(require_auth)):
    """Return scoring weights and thresholds (read-only)."""
    from mctrend.config.settings import Settings

    settings = Settings.load()
    return {
        "potential_weights": settings.potential_weights.model_dump(),
        "failure_weights": settings.failure_weights.model_dump(),
        "rug_risk_category_weights": settings.rug_risk_category_weights.model_dump(),
        "confidence_weights": settings.confidence_weights.model_dump(),
        "alert_thresholds": settings.alert_thresholds.model_dump(),
        "alert_expiry_minutes": settings.alert_expiry_minutes.model_dump(),
        "note": "Weight changes require code-level config or environment variable updates.",
    }


class ConfigPatch(BaseModel):
    field: str
    value: Any


@router.patch("")
async def patch_config(
    patch: ConfigPatch,
    _: None = Depends(require_auth),
):
    """Update a single dynamic config field at runtime.

    Only fields listed as dynamic=true may be updated.
    Secrets cannot be updated via the API.
    """
    field = patch.field

    if field in _SECRET_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' is a secret field. Update it in your .env file and restart.",
        )

    if field not in _DYNAMIC_FIELDS and field not in _RESTART_REQUIRED:
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' is not a recognized configurable field.",
        )

    if field in _RESTART_REQUIRED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{field}' requires a restart. "
                "Update it in your .env file and restart the system."
            ),
        )

    # Validate type
    value = patch.value
    int_fields = {
        "polling_interval_tokens", "polling_interval_events",
        "alert_rate_limit_per_10min", "max_token_age_hours",
        "pumpfun_fetch_limit", "news_page_size",
    }
    float_fields = {"confidence_floor_for_alert", "news_signal_strength"}

    try:
        if field in int_fields:
            value = int(value)
            if value <= 0:
                raise ValueError("Must be > 0")
        elif field in float_fields:
            value = float(value)
            if not (0.0 <= value <= 1.0):
                raise ValueError("Must be between 0.0 and 1.0")
        elif field == "log_level":
            value = str(value).upper()
            if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                raise ValueError("Invalid log level")
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid value for '{field}': {e}")

    _runtime_overrides[field] = value

    return {
        "updated": field,
        "new_value": value,
        "note": "Applied in memory. Persists until restart unless added to .env.",
    }
