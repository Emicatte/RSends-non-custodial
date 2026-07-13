"""Shared save/restore for the logging tests.

setup_logging() mutates global logging state (root handlers/level, third-party
logger levels, and — since the uvicorn-routing fix — the uvicorn loggers'
handlers/propagate). Single-source the list and the restore so the two logging
test modules can't drift (a logger added to setup_logging but restored in only
one file would leak its level into the rest of the suite).
"""

import logging
from contextlib import contextmanager

# Every logger whose level, handlers, or propagate setup_logging touches.
TOUCHED_LOGGERS = [
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "sqlalchemy.engine",
    "alembic",
    "httpx",
    "httpcore",
    "httpcore.http11",
]


@contextmanager
def restore_logging_state():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_level_named = {n: logging.getLogger(n).level for n in TOUCHED_LOGGERS}
    saved_handlers_named = {
        n: logging.getLogger(n).handlers[:] for n in TOUCHED_LOGGERS
    }
    saved_propagate = {n: logging.getLogger(n).propagate for n in TOUCHED_LOGGERS}
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        for n in TOUCHED_LOGGERS:
            lg = logging.getLogger(n)
            lg.setLevel(saved_level_named[n])
            lg.handlers[:] = saved_handlers_named[n]
            lg.propagate = saved_propagate[n]
