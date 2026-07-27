import logging
from flask import Blueprint, jsonify

from app.services.production_runtime_health_service import build_healthz_payload, build_readiness_payload

logger = logging.getLogger(__name__)


health_bp = Blueprint("health", __name__)


def _is_admin_request():
    """Check if the current request is from an authenticated OWNER/ADMIN user."""
    try:
        from flask_login import current_user

        if current_user and current_user.is_authenticated:
            return getattr(current_user, "role", None) in ("OWNER", "ADMIN")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/health_routes.py:16")
        pass
    return False


@health_bp.route("/healthz")
def healthz():
    full_payload = build_healthz_payload()

    if _is_admin_request():
        return jsonify(full_payload), 200

    status = "ok" if full_payload.get("status") == "ok" else "error"
    return jsonify({"status": status}), 200


@health_bp.route("/readiness")
def readiness():
    full_payload = build_readiness_payload()

    if _is_admin_request():
        status_code = 200 if full_payload.get("status") == "ready" else 503
        return jsonify(full_payload), status_code

    status = "ready" if full_payload.get("status") == "ready" else "not_ready"
    status_code = 200 if status == "ready" else 503
    return jsonify({"status": status}), status_code
