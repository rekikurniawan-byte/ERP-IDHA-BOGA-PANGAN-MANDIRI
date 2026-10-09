"""Halaman Invoice Otomatis (Fase 6): pratinjau, penerbitan manual, dan riwayat."""
from app.routes.finance_routes import *  # noqa: F401,F403


@finance_bp.route("/auto-invoices")
@role_required("OWNER", "ADMIN")
def auto_invoices():
    from datetime import date, timedelta

    from app.models.finance import Invoice
    from app.services.auto_invoice_service import (
        AUTO_INVOICE_TAG,
        PERIOD_INVOICE_SOURCE,
        plan_invoices,
    )
    from app.utils.clock import today_wib

    today = today_wib()
    date_value = (request.args.get("date") or "").strip()
    try:
        cutoff_date = date.fromisoformat(date_value) if date_value else today + timedelta(days=1)
    except ValueError:
        flash("Tanggal tidak valid; menampilkan pratinjau besok.", "warning")
        cutoff_date = today + timedelta(days=1)

    plans = plan_invoices(current_user.branch_id, cutoff_date)
    pending = [p for p in plans if p["already_issued"] is None]
    billable = [p for p in pending if p["lines"] and p["total"] > 0]
    ready = [p for p in billable if not p["error"]]
    problems = [p for p in billable if p["error"]]
    empty = [p for p in pending if not (p["lines"] and p["total"] > 0)]
    issued = [p for p in plans if p["already_issued"] is not None]

    recent = (
        Invoice.query.filter(
            Invoice.branch_id == current_user.branch_id,
            Invoice.source_type == PERIOD_INVOICE_SOURCE,
            Invoice.notes.like(f"{AUTO_INVOICE_TAG}%"),
        )
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .limit(30)
        .all()
    )

    return render_template(
        "finance/auto_invoices.html",
        cutoff_date=cutoff_date,
        today=today,
        plans=plans,
        ready=ready,
        problems=problems,
        empty=empty,
        issued=issued,
        ready_total=sum(p["total"] for p in ready),
        recent=recent,
        can_issue_now=cutoff_date <= today,
    )


@finance_bp.route("/auto-invoices/issue", methods=["POST"])
@role_required("OWNER", "ADMIN")
def issue_auto_invoices():
    from app.services.scheduler_service import run_job_now

    date_value = (request.form.get("date") or "").strip()
    try:
        run = run_job_now(
            key="auto_period_invoices",
            branch_id=current_user.branch_id,
            period_key=date_value or None,
            user=current_user,
        )
    except (ValueError, PermissionError) as error:
        flash(str(error), "warning")
        return redirect(url_for("finance.auto_invoices", date=date_value or None))

    if run.status == "SUCCESS":
        flash(f"Invoice otomatis hari potong {run.period_key} selesai diproses.", "success")
    else:
        flash(f"Penerbitan invoice gagal: {run.message}", "danger")
    return redirect(url_for("finance.auto_invoices", date=date_value or None))
