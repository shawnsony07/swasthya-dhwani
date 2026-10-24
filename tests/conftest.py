"""Shared pytest fixtures/config for the swasthya test suite."""
from __future__ import annotations

import logging

import structlog


def _configure_structlog_for_stdlib_capture() -> None:
    """Route structlog through stdlib logging so caplog can see our events.

    Without this, structlog's default PrintLoggerFactory never touches the
    stdlib `logging` module, so `caplog` (which hooks stdlib logging) would
    see nothing and privacy assertions on log content would pass vacuously.
    """
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.render_to_log_kwargs,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


_configure_structlog_for_stdlib_capture()
