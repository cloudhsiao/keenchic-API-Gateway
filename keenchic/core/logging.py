from __future__ import annotations

import logging
import sys

import structlog

_VALID_FORMATS = {"text", "json"}
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_DEFAULT_FORMAT = "text"
_DEFAULT_LEVEL = "INFO"


def configure_logging(log_format: str, log_level: str) -> None:
    """Initialise structlog for the application.

    Args:
        log_format: "text" (ConsoleRenderer) or "json" (JSONRenderer).
                    Falls back to "text" with a warning on invalid values.
        log_level:  Standard level name (DEBUG/INFO/WARNING/ERROR, case-insensitive).
                    Falls back to "INFO" with a warning on invalid values.
    """
    fmt = log_format.strip().lower()
    if fmt not in _VALID_FORMATS:
        fmt = _DEFAULT_FORMAT
        _warn_fallback("LOG_FORMAT", log_format, _DEFAULT_FORMAT)

    lvl_str = log_level.strip().upper()
    if lvl_str not in _VALID_LEVELS:
        lvl_str = _DEFAULT_LEVEL
        _warn_fallback("LOG_LEVEL", log_level, _DEFAULT_LEVEL)

    log_level_int = getattr(logging, lvl_str)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level_int,
    )

    renderer = (
        structlog.dev.ConsoleRenderer()
        if fmt == "text"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _warn_fallback(env_var: str, received: str, fallback: str) -> None:
    logging.warning(
        "Invalid %s value %r — falling back to %r", env_var, received, fallback
    )
