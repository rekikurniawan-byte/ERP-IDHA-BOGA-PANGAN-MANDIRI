"""SQLAlchemy slow-query logging hooks."""

from __future__ import annotations

import logging
import time

from flask import g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_INSTALLED = False


def _compact_statement(statement: str, limit: int = 500) -> str:
    compact = " ".join(str(statement or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def init_slow_query_logging(app):
    """Install process-wide SQLAlchemy hooks once.

    The hook intentionally logs SQL text without parameter values so customer,
    credential, or transaction values are not written to application logs.
    """
    global _INSTALLED
    if _INSTALLED or not app.config.get("SLOW_QUERY_LOGGING_ENABLED", True):
        return

    threshold_ms = int(app.config.get("SLOW_QUERY_THRESHOLD_MS", 500) or 500)

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_stack = conn.info.get("query_start_time") or []
        if not start_stack:
            return
        elapsed_ms = (time.perf_counter() - start_stack.pop()) * 1000
        if elapsed_ms < threshold_ms:
            return

        request_id = getattr(g, "request_id", None) if has_request_context() else None
        endpoint = request.endpoint if has_request_context() else None
        logger.warning(
            "Slow SQL query %.2f ms endpoint=%s request_id=%s sql=%s",
            elapsed_ms,
            endpoint,
            request_id,
            _compact_statement(statement),
        )

    _INSTALLED = True
