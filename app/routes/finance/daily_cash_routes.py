"""Daily cash reconciliation routes."""

from datetime import date, datetime

from app.utils.clock import today_wib

from app.routes.finance_routes import *  # noqa: F401,F403
from app.services.branch_module_service import WARUNG
from app.utils.decorators import module_required
from app.services.daily_cash_service import (
    build_reference_totals,
    get_daily_cash,
    get_last_closing_balance,
    list_daily_cash,
    save_daily_cash,
)


@finance_bp.route("/daily-cash", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
@module_required(WARUNG)
def daily_cash():
    today = today_wib()
    selected_date = today

    if request.method == "POST":
        cash_date_raw = (request.form.get("cash_date") or "").strip()
        try:
            selected_date = datetime.strptime(cash_date_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Tanggal kas harian tidak valid.", "warning")
            return redirect(url_for("finance.daily_cash"))

        record, is_new = save_daily_cash(
            branch_id=current_user.branch_id,
            created_by=current_user.id,
            cash_date=selected_date,
            opening_balance=request.form.get("opening_balance"),
            cash_sales=request.form.get("cash_sales"),
            debt_payments=request.form.get("debt_payments"),
            other_income=request.form.get("other_income"),
            expenses=request.form.get("expenses"),
            actual_cash=request.form.get("actual_cash"),
            status=request.form.get("status"),
            notes=(request.form.get("notes") or "").strip(),
        )
        action = "dibuat" if is_new else "diperbarui"
        flash(f"Rekap kas harian {record.cash_date.strftime('%d-%m-%Y')} berhasil {action}.", "success")
        return redirect(url_for("finance.daily_cash_detail", cash_id=record.id))

    records = list_daily_cash(current_user.branch_id)
    return render_template(
        "finance/daily_cash.html",
        records=records,
        today=today,
        suggested_opening=get_last_closing_balance(current_user.branch_id, selected_date),
        reference=build_reference_totals(current_user.branch_id, selected_date),
    )


@finance_bp.route("/daily-cash/<int:cash_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
@module_required(WARUNG)
def daily_cash_detail(cash_id):
    record = get_daily_cash(current_user.branch_id, cash_id)
    if not record:
        abort(404)
    return render_template(
        "finance/daily_cash_detail.html",
        record=record,
        reference=build_reference_totals(current_user.branch_id, record.cash_date),
    )
