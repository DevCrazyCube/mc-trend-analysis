"""
Structured logging setup using ``structlog``.

Provides two public helpers:

- ``configure_logging(level, log_format)`` — call once at application startup.
- ``get_logger(name)`` — obtain a bound logger for a module.

Default output format is JSON (one object per line), suitable for machine
consumption by log aggregation systems.  A human-friendly ``console`` format
is available for local development.

Reference: docs/implementation/current-approach.md — Monitoring and Observability.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
) -> None:
    """Initialise structured logging for the entire application.

    Parameters
    ----------
    level:
        Python log-level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``,
        ``CRITICAL``).
    log_format:
        ``"json"`` for machine-readable JSON lines (the default), or
        ``"console"`` for coloured, human-readable output during development.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processors applied to every log event.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "console":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a ``structlog`` bound logger identified by *name*.

    Typical usage::

        from mctrend.utils.logging import get_logger

        logger = get_logger(__name__)
        logger.info("pipeline_started", source="pumpfun")

    The returned logger respects the level and format configured by a prior
    call to :func:`configure_logging`.  If ``configure_logging`` has not been
    called yet, structlog falls back to stdlib defaults.
    """
    return structlog.get_logger(name)
