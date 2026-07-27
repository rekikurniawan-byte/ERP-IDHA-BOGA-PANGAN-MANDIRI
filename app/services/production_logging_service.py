from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from flask import g, has_request_context


_CONFIGURED_ATTR = "_idha_boga_production_logging_configured"


def _level_from_config(value: Any) -> int:
    name = str(value or "INFO").upper().strip()
    return getattr(logging, name, logging.INFO)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


def configure_production_logging(app) -> None:
    """Configure rotating app/error logs for Gunicorn/Nginx production runtime.

    This is intentionally lightweight: it creates the log directory if needed,
    adds one general app log and one error-only log, and avoids duplicate handlers
    when Flask reloads in local development.
    """
    if getattr(app, _CONFIGURED_ATTR, False):
        return

    log_root = Path(app.config.get("LOG_ROOT") or "instance/logs").resolve()
    log_root.mkdir(parents=True, exist_ok=True)

    level = _level_from_config(app.config.get("LOG_LEVEL"))
    max_bytes = int(app.config.get("LOG_MAX_BYTES") or (10 * 1024 * 1024))
    backup_count = int(app.config.get("LOG_BACKUP_COUNT") or 10)

    request_id_filter = RequestIdFilter()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_log = Path(app.config.get("APP_LOG_FILE") or (log_root / "app.log")).resolve()
    error_log = Path(app.config.get("ERROR_LOG_FILE") or (log_root / "error.log")).resolve()
    app_log.parent.mkdir(parents=True, exist_ok=True)
    error_log.parent.mkdir(parents=True, exist_ok=True)

    app_handler = RotatingFileHandler(app_log, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    app_handler.setLevel(level)
    app_handler.setFormatter(formatter)
    app_handler.addFilter(request_id_filter)

    error_handler = RotatingFileHandler(error_log, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(request_id_filter)

    app.logger.setLevel(level)
    app.logger.addHandler(app_handler)
    app.logger.addHandler(error_handler)

    # Keep Werkzeug/Gunicorn signals visible in app.log without forcing noisy debug output.
    logging.getLogger("werkzeug").setLevel(level)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    setattr(app, _CONFIGURED_ATTR, True)
