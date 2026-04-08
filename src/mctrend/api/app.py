"""FastAPI application — operator dashboard API.

Mount points:
  /api/health        — system health and source status
  /api/tokens        — token explorer
  /api/narratives    — narrative explorer
  /api/alerts        — alert center
  /api/candidates    — rejected candidate diagnostics
  /api/competition   — competition outcomes (winners, suppressed, reasons)
  /api/config        — configuration read/update
  /api/holdings      — manual holdings / positions
  /api/notifications — operator notification feed
  /api/events/stream — SSE live updates
  /                  — React dashboard (static files)
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mctrend.api.auth import auth_is_configured
from mctrend.api.routes import (
    alerts,
    candidates,
    competition,
    config,
    events,
    health,
    holdings,
    narratives,
    notifications,
    tokens,
)

logger = structlog.get_logger(__name__)

_STATIC_DIR = Path(__file__).parent.parent.parent.parent / "dashboard" / "dist"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="MC Trend Analysis — Operator Dashboard",
        description="Real-time memecoin trend intelligence operator console",
        version="0.2.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS — allow dashboard dev server on common ports during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router)
    app.include_router(tokens.router)
    app.include_router(narratives.router)
    app.include_router(alerts.router)
    app.include_router(candidates.router)
    app.include_router(competition.router)
    app.include_router(config.router)
    app.include_router(holdings.router)
    app.include_router(notifications.router)
    app.include_router(events.router)

    # Serve built dashboard if it exists
    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="dashboard")
        logger.info("dashboard_static_served", path=str(_STATIC_DIR))
    else:
        logger.info(
            "dashboard_static_not_found",
            expected_path=str(_STATIC_DIR),
            hint="Run 'cd dashboard && npm install && npm run build' to build the dashboard",
        )

    @app.on_event("startup")
    async def startup_event():
        if not auth_is_configured():
            logger.warning(
                "dashboard_auth_not_configured",
                note="Set DASHBOARD_API_KEY to require authentication for dashboard access",
            )

    return app
