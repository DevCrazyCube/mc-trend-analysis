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
from starlette.exceptions import HTTPException as StarletteHTTPException

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


class DashboardFiles(StaticFiles):
    """The built dashboard, with a fallback for its client-side routes.

    The dashboard is a single-page app: ``/alerts`` or ``/tokens`` are routes
    inside ``index.html``, not files.  Without a fallback a reload on such a
    page, or a link to it, is a 404.  A path that is not a file, is not under
    ``/api`` and has no file extension gets ``index.html``; a missing asset
    (``/assets/x.js``) and an unknown API path stay a 404.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not _is_client_route(path):
                raise
            return await super().get_response("index.html", scope)


def _is_client_route(path: str) -> bool:
    """True for a path the dashboard's own router should handle."""
    path = path.replace("\\", "/").strip("/")
    if path == "api" or path.startswith("api/"):
        return False
    last = path.rsplit("/", 1)[-1]
    return "." not in last


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
        app.mount("/", DashboardFiles(directory=str(_STATIC_DIR), html=True), name="dashboard")
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
