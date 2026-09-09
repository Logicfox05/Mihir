from __future__ import annotations

import logging
import sys

import structlog

from .config import get_settings


def setup_logging() -> None:
    s = get_settings()
    # Replies contain Hindi, Gujarati and emoji. A Windows console or a redirected log file often
    # defaults to cp1252, where writing that text raises - and because the log line is written while
    # a message is being processed, the customer would get "service unavailable" instead of a reply.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    level = getattr(logging, s.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for noisy in ("httpx", "httpcore", "apscheduler", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    renderer = structlog.dev.ConsoleRenderer() if s.is_dev else structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
