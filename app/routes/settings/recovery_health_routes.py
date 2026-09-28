"""Settings recovery and health routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.settings_routes import *  # noqa: F401,F403


@settings_bp.route("/recovery-center")
@role_required("OWNER", "ADMIN")
def recovery_center():
    try:
        branch_id = None if getattr(current_user, "role", None) == "OWNER" else getattr(current_user, "branch_id", None)
        report = build_recovery_center_report(branch_id=branch_id)
    except Exception as exc:
        current_app.logger.exception("Recovery Center final polish report failed")
        report = build_empty_recovery_center_report(str(exc))
        flash("Recovery Center gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/recovery_center.html", report=report)


@settings_bp.route("/system-health")
@role_required("OWNER", "ADMIN")
def system_health():
    try:
        health = build_system_health_report()
    except Exception as exc:
        current_app.logger.exception("Kesehatan Sistem read-only report failed")
        health = build_empty_system_health_report(str(exc))
        flash("Kesehatan Sistem gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/system_health.html", health=health)


@settings_bp.route("/atomic-transaction-map")
@role_required("OWNER")
def atomic_transaction_map():
    report = build_atomic_transaction_audit_map()
    return render_template("settings/atomic_transaction_map.html", report=report)


@settings_bp.route("/atomic-smoke-simulation")
@role_required("OWNER")
def atomic_smoke_simulation():
    try:
        report = run_atomic_failure_injection_smoke()
    except Exception as exc:
        current_app.logger.exception("Atomic smoke simulation failed")
        report = build_empty_atomic_failure_injection_report(str(exc))
        flash("Atomic smoke simulation gagal dijalankan. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/atomic_smoke_simulation.html", report=report)




@settings_bp.route("/visual-sweep")
@role_required("OWNER", "ADMIN")
def visual_sweep():
    try:
        report = build_visual_sweep_report()
    except Exception as exc:
        current_app.logger.exception("PRODUCTION Visual Sweep failed")
        report = build_empty_visual_sweep_report(str(exc))
        flash("Visual Sweep gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/visual_sweep.html", report=report)


@settings_bp.route("/final-visual-qa")
@role_required("OWNER", "ADMIN")
def final_visual_browser_qa():
    try:
        report = build_final_visual_browser_qa_report()
    except Exception as exc:
        current_app.logger.exception("PRODUCTION Final Visual Browser QA failed")
        report = build_empty_final_visual_browser_qa_report(str(exc))
        flash("Final Visual Browser QA gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/final_visual_browser_qa.html", report=report)
