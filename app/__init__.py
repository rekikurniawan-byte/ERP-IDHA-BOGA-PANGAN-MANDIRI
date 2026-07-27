from uuid import uuid4

from flask import Flask, g, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from app.extensions import db, migrate, login_manager, csrf, limiter
from app.services.production_logging_service import configure_production_logging
from app.services.slow_query_logger_service import init_slow_query_logging
from app.services.ttl_cache_service import get_cached_value


def create_app():
    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)

    if flask_app.config.get("PROXY_HEADERS_ENABLED"):
        flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    configure_production_logging(flask_app)

    db.init_app(flask_app)
    init_slow_query_logging(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    csrf.init_app(flask_app)
    limiter.init_app(flask_app)

    from app.routes.auth_routes import auth_bp
    from app.routes.dashboard_routes import dashboard_bp
    from app.routes.master_routes import master_bp
    from app.routes.operational_routes import operational_bp
    from app.routes.production_routes import production_bp
    from app.routes.delivery_routes import delivery_bp
    from app.routes.canteen_routes import canteen_bp
    from app.routes.logistics_routes import logistics_bp
    from app.routes.finance_routes import finance_bp
    from app.routes.accounting_routes import accounting_bp
    from app.routes.hr_routes import hr_bp
    from app.routes.settings_routes import settings_bp
    from app.routes.costing_routes import costing_bp
    from app.routes.sop_routes import sop_bp
    from app.routes.health_routes import health_bp
    from app.routes.field_transaction_routes import field_transaction_bp
    from app.routes.prediction_routes import prediction_bp

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(dashboard_bp)
    flask_app.register_blueprint(master_bp)
    flask_app.register_blueprint(operational_bp)
    flask_app.register_blueprint(production_bp)
    flask_app.register_blueprint(delivery_bp)
    flask_app.register_blueprint(canteen_bp)
    flask_app.register_blueprint(logistics_bp)
    flask_app.register_blueprint(finance_bp)
    flask_app.register_blueprint(accounting_bp)
    flask_app.register_blueprint(hr_bp)
    flask_app.register_blueprint(settings_bp)
    flask_app.register_blueprint(costing_bp)
    flask_app.register_blueprint(sop_bp)
    flask_app.register_blueprint(health_bp)
    flask_app.register_blueprint(field_transaction_bp)
    flask_app.register_blueprint(prediction_bp)


    @flask_app.before_request
    def attach_request_id():
        incoming_request_id = str(request.headers.get("X-Request-ID") or "").strip()
        g.request_id = incoming_request_id[:128] if incoming_request_id else uuid4().hex


    @flask_app.after_request
    def add_security_headers(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers.setdefault("X-Request-ID", request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        content_security_policy = flask_app.config.get("CONTENT_SECURITY_POLICY")
        if content_security_policy:
            header_name = (
                "Content-Security-Policy-Report-Only"
                if flask_app.config.get("CONTENT_SECURITY_POLICY_REPORT_ONLY")
                else "Content-Security-Policy"
            )
            response.headers.setdefault(header_name, content_security_policy)
        if flask_app.config.get("IS_PRODUCTION"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


    @flask_app.context_processor
    def inject_company_settings():
        try:
            from flask_login import current_user
            from app.services.company_settings_service import get_company_settings

            if current_user.is_authenticated:
                return {
                    "global_company_settings": get_cached_value(
                        ("company_settings", current_user.branch_id),
                        lambda: get_company_settings(current_user.branch_id),
                        ttl_seconds=30,
                    )
                }
        except Exception:
            flask_app.logger.exception("Gagal memuat company settings global.")

        return {"global_company_settings": {}}

    @flask_app.context_processor
    def inject_live_reminder_badge():
        try:
            from flask_login import current_user
            from app.services.live_reminder_service import build_live_reminder_badge_summary

            if current_user.is_authenticated and current_user.role in ["OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR"]:
                return {
                    "global_live_reminder_badge": get_cached_value(
                        ("live_reminder_badge", current_user.branch_id, current_user.role),
                        lambda: build_live_reminder_badge_summary(
                            current_user.branch_id,
                            due_days=7,
                        ),
                        ttl_seconds=30,
                    )
                }
        except Exception:
            flask_app.logger.exception("Gagal memuat live reminder badge global.")

        return {
            "global_live_reminder_badge": {
                "total": 0,
                "critical": 0,
                "warning": 0,
                "info": 0,
                "badge_class": "bg-success-subtle text-success border",
                "icon": "bi-check2-circle",
                "label": "Aman",
                "top_sections": [],
                "action_url": "#",
                "read_only": True,
            }
        }

    @flask_app.context_processor
    def inject_persistent_notification_badge():
        try:
            from flask_login import current_user
            from app.services.notification_service import count_unread_notifications

            if current_user.is_authenticated and current_user.role in ["OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR"]:
                summary = get_cached_value(
                    ("persistent_notification_badge", current_user.branch_id, current_user.role, current_user.id),
                    lambda: count_unread_notifications(branch_id=current_user.branch_id, user=current_user),
                    ttl_seconds=30,
                )
                total = summary.get("total", 0)
                if summary.get("critical", 0) > 0:
                    badge_class = "bg-danger-subtle text-danger border"
                    icon = "bi-exclamation-triangle"
                    label = "Kritis"
                elif summary.get("warning", 0) > 0:
                    badge_class = "bg-warning-subtle text-warning border"
                    icon = "bi-exclamation-circle"
                    label = "Perlu Dicek"
                elif total > 0:
                    badge_class = "bg-info-subtle text-info border"
                    icon = "bi-bell"
                    label = "Unread"
                else:
                    badge_class = "bg-success-subtle text-success border"
                    icon = "bi-check2-circle"
                    label = "Aman"
                return {
                    "global_persistent_notification_badge": {
                        **summary,
                        "badge_class": badge_class,
                        "icon": icon,
                        "label": label,
                    }
                }
        except Exception:
            flask_app.logger.exception("Gagal memuat persistent notification badge global.")

        return {
            "global_persistent_notification_badge": {
                "total": 0,
                "critical": 0,
                "warning": 0,
                "info": 0,
                "badge_class": "bg-success-subtle text-success border",
                "icon": "bi-check2-circle",
                "label": "Aman",
            }
        }

    @flask_app.template_filter("rupiah")
    def rupiah(value):
        try:
            value = float(value or 0)
            return "Rp {:,.0f}".format(value).replace(",", ".")
        except (ValueError, TypeError):
            return "Rp 0"


    @flask_app.template_filter("qty")
    def qty(value):
        try:
            number = round(float(value or 0), 4)

            if number.is_integer():
                return str(int(number))

            return f"{number:.4f}".rstrip("0").rstrip(".")
        except (ValueError, TypeError):
            return "0"


    @flask_app.errorhandler(CSRFError)
    def csrf_error(error):
        try:
            db.session.rollback()
        except Exception:
            flask_app.logger.exception("Rollback session gagal setelah CSRF error.")
        return render_template("errors/400_csrf.html"), 400

    @flask_app.errorhandler(403)
    def forbidden_error(error):
        return render_template("errors/403.html"), 403

    @flask_app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    @flask_app.errorhandler(500)
    def internal_server_error(error):
        try:
            db.session.rollback()
        except Exception:
            flask_app.logger.exception("Rollback session gagal setelah internal server error.")
        return render_template("errors/500.html"), 500

    return flask_app
