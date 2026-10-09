"""Routes untuk halaman status dan manajemen Tugas Otomatis (Penjadwal)."""
from __future__ import annotations

import logging
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.routes.settings_routes import settings_bp
from app.services.scheduler_service import (
    get_heartbeat_status,
    get_job,
    get_scheduled_jobs_status,
    list_job_runs,
    run_job_now,
)
from app.utils.decorators import role_required

logger = logging.getLogger(__name__)


@settings_bp.route("/jobs", methods=["GET"])
@role_required("OWNER", "ADMIN")
def scheduled_jobs():
    """Halaman status tugas otomatis dan riwayat 50 eksekusi terakhir."""
    status_filter = request.args.get("status") or None
    job_key_filter = request.args.get("job_key") or None

    jobs_summary = get_scheduled_jobs_status()
    runs = [
        run
        for run in list_job_runs(job_key=job_key_filter, status=status_filter, limit=200)
        if run.branch_id in (None, current_user.branch_id)
    ][:50]
    heartbeat = get_heartbeat_status()

    return render_template(
        "settings/scheduled_jobs.html",
        jobs=jobs_summary,
        runs=runs,
        heartbeat=heartbeat,
        current_status=status_filter,
        current_job_key=job_key_filter,
    )


@settings_bp.route("/jobs/<key>/run", methods=["POST"])
@role_required("OWNER", "ADMIN")
def run_scheduled_job_manual(key):
    """Pemicu manual tugas otomatis melalui antarmuka web."""
    job = get_job(key)
    if job is None:
        flash(f"Tugas '{key}' tidak terdaftar.", "warning")
        return redirect(url_for("settings.scheduled_jobs"))
    # Tugas per cabang selalu dijalankan untuk cabang pengguna sendiri -- jangan
    # percaya branch_id dari form (admin cabang lain bisa menjalankan punya orang).
    branch_id = current_user.branch_id if job.get("per_branch", True) else None
    period_key = (request.form.get("period_key") or "").strip() or None
    force = request.form.get("force") in ("1", "true", "True", "on")
    force_reason = request.form.get("force_reason") or None

    try:
        run = run_job_now(
            key=key,
            branch_id=branch_id,
            period_key=period_key,
            user=current_user,
            force=force,
            force_reason=force_reason,
        )
        if run.status == "SUCCESS":
            flash(f"Tugas '{key}' berhasil dijalankan (Periode: {run.period_key}).", "success")
        elif run.status == "FAILED":
            flash(f"Tugas '{key}' selesai dengan status GAGAL: {run.message}", "danger")
        else:
            flash(f"Tugas '{key}' selesai dengan status {run.status}.", "info")
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Eksekusi manual job %s gagal", key)
        flash(f"Terjadi kesalahan saat menjalankan tugas: {exc}", "danger")

    return redirect(url_for("settings.scheduled_jobs"))
