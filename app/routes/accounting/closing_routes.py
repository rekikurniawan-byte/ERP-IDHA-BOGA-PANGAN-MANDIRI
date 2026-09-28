"""Accounting period closing routes.

Route functions moved out of app.routes.accounting_routes without changing URL rules or endpoint names.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403
from app.routes.accounting_routes import _reserve_accounting_idempotency
from app.routes.accounting_routes import _journal_total_credit, _journal_total_debit


# === PRODUCTION_PERIOD_CLOSING_RETAINED_EARNINGS_ROUTES ===
@accounting_bp.route("/period-closing")
@login_required
@role_required("OWNER", "ACCOUNTING")
def period_closing():
    from datetime import date
    from app.services.period_closing_service import get_period_closing_preview

    today = date.today()
    selected_year = request.args.get("year", today.year)
    selected_month = request.args.get("month", today.month)
    preview = get_period_closing_preview(current_user.branch_id, selected_year, selected_month)
    year_options = list(range(today.year - 3, today.year + 2))
    month_options = [
        (1, "Januari"), (2, "Februari"), (3, "Maret"), (4, "April"),
        (5, "Mei"), (6, "Juni"), (7, "Juli"), (8, "Agustus"),
        (9, "September"), (10, "Oktober"), (11, "November"), (12, "Desember"),
    ]
    return render_template(
        "accounting/period_closing.html",
        preview=preview,
        year_options=year_options,
        month_options=month_options,
        post_idempotency_key=uuid4().hex,
    )


@accounting_bp.route("/period-closing/post", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def post_period_closing_route():
    from datetime import datetime
    from app.services.period_closing_service import post_period_closing

    selected_year = request.form.get("year")
    selected_month = request.form.get("month")
    closing_date_raw = (request.form.get("closing_date") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_PERIOD_CLOSING_POST",
        {
            "year": selected_year,
            "month": selected_month,
            "closing_date": closing_date_raw,
            "notes": notes,
        },
        default_endpoint="accounting.period_closing",
    )
    if idempotency_response:
        return idempotency_response

    try:
        closing_date = datetime.strptime(closing_date_raw, "%Y-%m-%d").date() if closing_date_raw else None
        closing = post_period_closing(
            branch_id=current_user.branch_id,
            year=selected_year,
            month=selected_month,
            closing_date=closing_date,
            notes=notes,
            created_by=current_user.id,
            commit=True,
        )
        mark_idempotency_completed(
            idempotency_record,
            reference_type="PERIOD_CLOSING",
            reference_id=closing.id,
            response_payload={"closing_id": closing.id, "closing_number": closing.closing_number},
            commit=True,
        )
        flash(f"Closing periode {closing.closing_number} berhasil diposting ke 3002 Laba Ditahan.", "success")
        return redirect(url_for("accounting.period_closing_detail", closing_id=closing.id))
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:2484")
        flash(str(exc), "danger")
        return redirect(url_for("accounting.period_closing", year=selected_year, month=selected_month))


@accounting_bp.route("/period-closing/<int:closing_id>")
@login_required
@role_required("OWNER", "ACCOUNTING")
def period_closing_detail(closing_id):
    from app.models.accounting import PeriodClosing

    closing = PeriodClosing.query.get_or_404(closing_id)
    if closing.branch_id != current_user.branch_id:
        return redirect(url_for("accounting.period_closing"))
    journal = closing.journal
    total_debit = _journal_total_debit(journal) if journal else 0
    total_credit = _journal_total_credit(journal) if journal else 0
    return render_template(
        "accounting/period_closing_detail.html",
        closing=closing,
        journal=journal,
        total_debit=total_debit,
        total_credit=total_credit,
        is_balanced=round(total_debit, 2) == round(total_credit, 2),
    )
