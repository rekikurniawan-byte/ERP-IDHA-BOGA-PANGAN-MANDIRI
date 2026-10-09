import hashlib
from pathlib import Path
from uuid import uuid4

import click
from flask import Flask, g, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from app.extensions import db, migrate, login_manager, csrf, limiter
from app.services.production_logging_service import configure_production_logging
from app.services.slow_query_logger_service import init_slow_query_logging
from app.services.ttl_cache_service import get_cached_value
from app.utils.roles import role_in

# The four internal roles after the Blueprint V2 consolidation. role_in() also
# matches retired roles (FINANCE, ACCOUNTING, ...) through their successor.
INTERNAL_ROLES = ("OWNER", "ADMIN", "DAPUR", "PENGANTAR")


def _static_asset_fingerprint(flask_app: Flask, relative_path: str) -> str:
    """Short content hash used as a cache-busting query string.

    Computed once at startup instead of per-request since static assets
    do not change while the process is running.
    """
    asset_path = Path(flask_app.static_folder) / relative_path
    try:
        digest = hashlib.sha1(asset_path.read_bytes()).hexdigest()
    except OSError:
        return "0"
    return digest[:10]


def _current_user_has_role(roles) -> bool:
    """Template membership test: does the signed-in user hold any of `roles`?

    Reads through app/utils/roles.py, so a list naming a retired role such as
    ACCOUNTING also matches ADMIN. Plain membership -- unlike role_required()
    there is no OWNER bypass, so every existing `role in [...]` check keeps
    its exact meaning apart from the retired-role mapping.
    """
    from flask_login import current_user

    if not current_user.is_authenticated:
        return False
    return role_in(current_user.role, roles)


def create_app():
    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)

    flask_app.config["CSS_ASSET_VERSION"] = _static_asset_fingerprint(flask_app, "css/style.css")
    flask_app.config["JS_ASSET_VERSION"] = _static_asset_fingerprint(flask_app, "js/main.js")
    flask_app.config["CONTROLS_JS_ASSET_VERSION"] = _static_asset_fingerprint(flask_app, "js/controls.js")

    # Lets templates build conditional page_header()/macro action lists with
    # `{% do actions.append(...) %}` instead of verbose `{% set x = x + [...] %}`.
    flask_app.jinja_env.add_extension("jinja2.ext.do")

    # Templates decide what to show through the same role table the routes
    # use, so a menu can never be hidden from a role that is allowed in.
    flask_app.jinja_env.globals["has_role"] = _current_user_has_role

    # Istilah bisnis per cabang ("Client", "Sub Client", ...), diatur OWNER di
    # Pengaturan Perusahaan. Lihat app/utils/terms.py.
    from app.utils.terms import term

    flask_app.jinja_env.globals["term"] = term

    # Modul per cabang (Warung, Hutang Pekerja): menu hanya tampil kalau
    # modulnya nyala, sama dengan penjaga module_required di rutenya.
    from app.services.branch_module_service import module_enabled

    flask_app.jinja_env.globals["module_enabled"] = module_enabled

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
    from app.routes.portal_routes import portal_bp
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
    from app.routes.customer_success_routes import customer_success_bp
    from app.routes.credit_routes import credit_bp
    from app.routes.public_routes import public_bp
    from app.routes.location_photo_routes import location_photo_bp
    from app.routes.account_routes import account_bp
    from app.routes.menu_photo_routes import menu_photo_bp

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(dashboard_bp)
    flask_app.register_blueprint(portal_bp)
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
    flask_app.register_blueprint(customer_success_bp)
    flask_app.register_blueprint(credit_bp)
    flask_app.register_blueprint(public_bp)
    flask_app.register_blueprint(location_photo_bp)
    flask_app.register_blueprint(account_bp)
    flask_app.register_blueprint(menu_photo_bp)


    @flask_app.before_request
    def attach_request_id():
        incoming_request_id = str(request.headers.get("X-Request-ID") or "").strip()
        g.request_id = incoming_request_id[:128] if incoming_request_id else uuid4().hex


    @flask_app.before_request
    def run_daily_credit_sweep():
        """Penyapu harian (kontrak lalu kredit), dipicu permintaan internal pertama tiap hari.

        Aplikasi ini tidak punya penjadwal. Gerbang order tidak bergantung
        pada penyapu (gerbang selalu menghitung ulang), jadi kalau langkah ini
        gagal, order tetap aman -- yang tertunda hanya catatan status dan
        notifikasinya. Karena itu kegagalan dicatat di log, tidak menggagalkan
        permintaan pengguna. Server juga bisa menjalankan `flask credit-sweep`.
        """
        if flask_app.config.get("TESTING") or request.endpoint in (None, "static"):
            return
        try:
            from datetime import date as _date

            from flask_login import current_user
            from app.services.credit_account_service import run_daily_sweep_if_due

            if not current_user.is_authenticated or not role_in(current_user.role, INTERNAL_ROLES):
                return
            branch_id = current_user.branch_id
            get_cached_value(
                ("credit_daily_sweep", branch_id, _date.today().isoformat()),
                lambda: run_daily_sweep_if_due(branch_id) or {},
                ttl_seconds=3600,
            )
        except Exception:
            # run_daily_sweep_if_due sudah me-rollback transaksinya sendiri.
            flask_app.logger.exception("Penyapu harian gagal; gerbang order tetap aktif.")


    @flask_app.cli.command("credit-sweep")
    def credit_sweep_command():
        """Jalankan penyapu harian (kontrak lalu kredit) untuk semua cabang (untuk penjadwal server)."""
        from app.services.credit_account_service import sweep_all_branches

        for branch_id, result in sweep_all_branches().items():
            contracts = result["contracts"]
            print(
                f"Cabang {branch_id}: {contracts['expired']} kontrak berakhir, {contracts['reminders']} kontrak hampir habis, "
                f"{result['checked']} akun kredit diperiksa, {len(result['escalated'])} naik status."
            )

    @flask_app.cli.command("bootstrap")
    @click.option("--branch-code", required=True, help="Kode cabang pertama, mis. PUSAT.")
    @click.option("--branch-name", required=True, help="Nama cabang pertama.")
    @click.option("--owner-username", required=True, help="Username OWNER pertama.")
    @click.option("--owner-name", default="Owner", help="Nama lengkap OWNER.")
    def bootstrap_command(branch_code, branch_name, owner_username, owner_name):
        """Isi awal database baru: COA acuan, cabang pertama, OWNER pertama (aman diulang).

        Password OWNER dibaca dari BOOTSTRAP_OWNER_PASSWORD, atau ditanyakan.
        """
        import os
        import sys

        from app.services.bootstrap_service import BootstrapError, bootstrap_company

        password = os.getenv("BOOTSTRAP_OWNER_PASSWORD") or click.prompt(
            "Password OWNER", hide_input=True, confirmation_prompt=True
        )
        try:
            result = bootstrap_company(
                branch_code=branch_code,
                branch_name=branch_name,
                owner_username=owner_username,
                owner_full_name=owner_name,
                owner_password=password,
            )
        except BootstrapError as error:
            print(f"FAIL {error}")
            sys.exit(1)
        print(f"COA: {len(result['accounts_created'])} akun ditambahkan.")
        print(f"Cabang {result['branch'].name}: {'dibuat' if result['branch_created'] else 'sudah ada'}.")
        print(f"OWNER {result['owner'].username}: {'dibuat' if result['owner_created'] else 'sudah ada, tidak diubah'}.")

    @flask_app.cli.command("backup-full")
    def backup_full_command():
        """Backup penuh (database + lampiran) lalu verifikasi isinya (untuk penjadwal server)."""
        import sys

        from app.services.backup_service import create_full_backup_package, verify_full_backup_package

        try:
            backup = create_full_backup_package(created_by="SCHEDULER")
        except Exception as error:  # noqa: BLE001 - penjadwal harus melihat pesan yang jelas
            print(f"FAIL backup tidak dibuat: {error}")
            sys.exit(1)
        result = verify_full_backup_package(backup["path"])
        print(f"{result['status']} {backup['name']} ({backup['size_bytes']} byte)")
        for error in result.get("errors", []):
            print(f"  ERROR {error}")
        if result["status"] != "PASS":
            sys.exit(1)

    @flask_app.cli.command("ops-check")
    def ops_check_command():
        """Cek kesiapan produksi. Keluar dengan kode 1 kalau ada FAIL."""
        import sys

        from app.services.readiness_service import FAIL, run_readiness_checks

        checks = run_readiness_checks()
        for check in checks:
            print(f"[{check.status}] {check.name}: {check.message}")
        failed = sum(1 for check in checks if check.status == FAIL)
        print()
        print(f"{len(checks)} cek, {failed} FAIL.")
        if failed:
            sys.exit(1)

    @flask_app.cli.group("jobs")
    def jobs_group():
        """Perintah penjadwal tugas otomatis PT Idha Boga."""
        pass

    @jobs_group.command("tick")
    def jobs_tick_command():
        """Jalankan semua tugas otomatis yang jatuh tempo (dipanggil tiap 5 menit oleh OS)."""
        import sys
        from app.services.scheduler_service import run_due_jobs

        runs = run_due_jobs()
        failed = [r for r in runs if r.status == "FAILED"]
        print(f"Tick selesai: {len(runs)} dieksekusi, {len(failed)} gagal.")
        for r in runs:
            branch_info = f"cabang {r.branch_id}" if r.branch_id else "global"
            print(f"- [{r.status}] {r.job_key} ({branch_info}, periode {r.period_key}): {r.message or 'OK'}")
        if failed:
            sys.exit(1)

    @jobs_group.command("list")
    def jobs_list_command():
        """Tampilkan daftar tugas otomatis yang terdaftar."""
        from app.services.scheduler_service import list_jobs

        jobs = list_jobs()
        print(f"Daftar tugas otomatis ({len(jobs)} terdaftar):")
        for j in jobs:
            sched = j["schedule"]
            sched_str = f"Harian {sched.get('time')} WIB" if sched.get("type") == "daily" else f"Tiap {sched.get('minutes')} menit"
            branch_str = "per-cabang" if j.get("per_branch") else "global"
            status_str = "aktif" if j.get("enabled") else "nonaktif"
            print(f"- {j['key']} | {j['label']} | {sched_str} | {branch_str} | {status_str}")

    @jobs_group.command("run")
    @click.argument("key")
    @click.option("--branch", "branch_id", type=int, default=None, help="ID cabang (opsional).")
    @click.option("--period", "period_key", default=None, help="Kunci periode, mis. '2026-10-08' (opsional).")
    @click.option("--force", is_flag=True, default=False, help="Paksa jalan ulang periode SUCCESS (khusus OWNER).")
    @click.option("--reason", "force_reason", default=None, help="Alasan bila memakai --force.")
    def jobs_run_command(key, branch_id, period_key, force, force_reason):
        """Jalankan satu tugas otomatis secara manual."""
        import sys
        from app.services.scheduler_service import run_job_now

        try:
            run = run_job_now(
                key=key,
                branch_id=branch_id,
                period_key=period_key,
                force=force,
                force_reason=force_reason,
            )
            branch_info = f"cabang {run.branch_id}" if run.branch_id else "global"
            print(f"[{run.status}] {run.job_key} ({branch_info}, periode {run.period_key}): {run.message or 'OK'}")
            if run.status == "FAILED":
                sys.exit(1)
        except Exception as error:
            print(f"GAGAL: {error}")
            sys.exit(1)


    @flask_app.after_request
    def add_security_headers(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers.setdefault("X-Request-ID", request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(self)")
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
            # Pengunjung (beranda, masuk, daftar): identitas cabang utama.
            from app.services.public_site_service import main_branch_id

            branch_id = get_cached_value(("public_branch_id",), main_branch_id, ttl_seconds=300)
            if branch_id:
                return {
                    "global_company_settings": get_cached_value(
                        ("company_settings", branch_id),
                        lambda: get_company_settings(branch_id),
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
            from app.services.live_reminder_service import allowed_reminder_sections, build_live_reminder_badge_summary
            from app.utils.roles import effective_role

            if current_user.is_authenticated and role_in(current_user.role, INTERNAL_ROLES):
                allowed = allowed_reminder_sections(current_user)
                if not allowed:
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

                eff_role = effective_role(current_user.role)
                if eff_role == "PENGANTAR":
                    cache_key = ("live_reminder_badge", current_user.branch_id, eff_role, current_user.id)
                else:
                    cache_key = ("live_reminder_badge", current_user.branch_id, eff_role)

                return {
                    "global_live_reminder_badge": get_cached_value(
                        cache_key,
                        lambda: build_live_reminder_badge_summary(
                            current_user.branch_id,
                            user=current_user,
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

            if current_user.is_authenticated and role_in(current_user.role, INTERNAL_ROLES):
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

    @flask_app.context_processor
    def inject_work_queue():
        """Angka di grup menu "Antrean Kerja" (OWNER/ADMIN)."""
        empty = {"portal_orders": 0, "payment_proofs": 0, "refunds": 0, "approvals": 0, "total": 0}
        try:
            from flask_login import current_user
            from app.services.work_queue_service import work_queue_counts

            if current_user.is_authenticated and role_in(current_user.role, ("OWNER", "ADMIN")):
                return {
                    "global_work_queue": get_cached_value(
                        ("work_queue", current_user.branch_id),
                        lambda: work_queue_counts(current_user.branch_id),
                        ttl_seconds=10,
                    )
                }
        except Exception:
            flask_app.logger.exception("Gagal memuat antrean kerja.")
        return {"global_work_queue": empty}

    @flask_app.context_processor
    def inject_scheduler_warning():
        try:
            from flask_login import current_user
            from app.services.scheduler_service import get_scheduler_warning

            if current_user.is_authenticated and role_in(current_user.role, ("OWNER", "ADMIN")):
                from app.services.auto_invoice_service import unresolved_failure_count

                warning = get_cached_value(
                    ("scheduler_warning",),
                    get_scheduler_warning,
                    ttl_seconds=30,
                )
                branch_id = current_user.branch_id
                failures = get_cached_value(
                    ("auto_invoice_failures", branch_id),
                    lambda: unresolved_failure_count(branch_id),
                    ttl_seconds=30,
                )
                return {"scheduler_warning": warning, "auto_invoice_failures": failures}
        except Exception:
            flask_app.logger.exception("Gagal memuat status peringatan penjadwal.")
        return {"scheduler_warning": None, "auto_invoice_failures": 0}

    @flask_app.context_processor
    def inject_portal_feature_flags():
        return {"global_portal_enabled": bool(flask_app.config.get("PORTAL_ENABLED", False))}

    @flask_app.context_processor
    def inject_asset_versions():
        return {
            "css_asset_version": flask_app.config["CSS_ASSET_VERSION"],
            "js_asset_version": flask_app.config["JS_ASSET_VERSION"],
            "controls_js_asset_version": flask_app.config["CONTROLS_JS_ASSET_VERSION"],
        }

    @flask_app.template_filter("rupiah")
    def rupiah(value):
        try:
            value = float(value or 0)
            return "Rp {:,.0f}".format(value).replace(",", ".")
        except (ValueError, TypeError):
            return "Rp 0"

    @flask_app.template_filter("rupiah_short")
    def rupiah_short(value):
        """Angka ringkas untuk label grafik yang sempit: 3.366.500 -> 3,4 jt."""
        try:
            value = float(value or 0)
        except (ValueError, TypeError):
            return "0"
        size = abs(value)
        if size >= 1_000_000_000:
            text = f"{value / 1_000_000_000:.1f} M"
        elif size >= 1_000_000:
            text = f"{value / 1_000_000:.1f} jt"
        elif size >= 1_000:
            text = f"{value / 1_000:.0f} rb"
        else:
            text = f"{value:.0f}"
        return text.replace(".", ",")


    @flask_app.template_filter("qty")
    def qty(value):
        try:
            number = round(float(value or 0), 4)

            if number.is_integer():
                return str(int(number))

            return f"{number:.4f}".rstrip("0").rstrip(".")
        except (ValueError, TypeError):
            return "0"

    from app.utils.labels import event_label, role_label, status_label
    from app.utils.clock import format_wib, today_wib

    flask_app.add_template_filter(status_label, "status_label")
    flask_app.add_template_filter(event_label, "event_label")
    flask_app.add_template_filter(role_label, "role_label")
    flask_app.add_template_filter(format_wib, "wib")
    flask_app.jinja_env.globals["today_wib"] = today_wib
    from app.services.location_photo_service import can_manage as can_manage_location_photos, location_photos
    flask_app.jinja_env.globals["location_photos_for"] = location_photos
    flask_app.jinja_env.globals["can_manage_location_photos"] = can_manage_location_photos


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
