"""Accounting audit, health, and trace routes.

Route functions moved out of app.routes.accounting_routes without changing URL rules or endpoint names.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403


@accounting_bp.route("/")
@login_required
@role_required("OWNER", "ACCOUNTING")
def index():
    return redirect(url_for("accounting.journals"))


@accounting_bp.route("/data-health")
@login_required
@role_required("OWNER", "ACCOUNTING")
def data_health():
    report = get_data_health_report(current_user.branch_id)
    return render_template("accounting/data_health.html", report=report)


@accounting_bp.route("/data-health/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_data_health_csv():
    from app.services.accounting_export_service import build_data_health_export_response

    report = get_data_health_report(current_user.branch_id)
    return build_data_health_export_response(report)


@accounting_bp.route("/daily-closing")
@login_required
@role_required("OWNER", "ACCOUNTING")
def daily_closing():
    selected_date = request.args.get("date", "")
    report = get_daily_closing_report(current_user.branch_id, selected_date)
    return render_template("accounting/daily_closing.html", report=report)


@accounting_bp.route("/daily-closing/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_daily_closing_csv():
    from app.services.accounting_export_service import build_daily_closing_export_response

    selected_date = request.args.get("date", "")
    report = get_daily_closing_report(current_user.branch_id, selected_date)
    return build_daily_closing_export_response(report)



@accounting_bp.route("/expense-drilldown")
@login_required
@role_required("OWNER", "ACCOUNTING")
def expense_drilldown():
    from datetime import date
    from flask import request
    from app.services.accounting_expense_drilldown_service import build_expense_drilldown_report

    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = date_filter.start_date or default_start
    end_date = date_filter.end_date or today

    report = build_expense_drilldown_report(current_user.branch_id, start_date, end_date)
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("accounting.expense_drilldown"),
        reset_url=url_for("accounting.expense_drilldown"),
        title="Filter Beban",
        description="Custom tanggal untuk membaca beban posted dan sumber yang perlu dicek.",
    )
    return render_template("accounting/expense_drilldown.html", report=report, filter_bar=filter_bar)


@accounting_bp.route("/posting-status")
@login_required
@role_required("OWNER", "ACCOUNTING")
def posting_status():
    from app.services.accounting_posting_status_service import (
        build_accounting_posting_status_report,
        filter_accounting_posting_status_report,
    )

    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    status_filter = (request.args.get("status") or "ALL").upper().strip()
    allowed_statuses = ["ALL", "POSTED", "UNPOSTED", "WAITING", "BLOCKED", "NOT_REQUIRED"]
    if status_filter not in allowed_statuses:
        status_filter = "ALL"

    report = build_accounting_posting_status_report(current_user.branch_id)
    report = filter_accounting_posting_status_report(report, date_filter.start_date, date_filter.end_date, status_filter)
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("accounting.posting_status"),
        reset_url=url_for("accounting.posting_status"),
        title="Filter Status Posting",
        description="Filter sumber posting berdasarkan tanggal sumber dan status jurnal.",
        status_name="status",
        status_value=status_filter,
        status_options=[
            {"value": "ALL", "label": "Semua Status"},
            {"value": "POSTED", "label": "Sudah Posting"},
            {"value": "UNPOSTED", "label": "Belum Posting"},
            {"value": "WAITING", "label": "Menunggu"},
            {"value": "BLOCKED", "label": "Diblokir"},
            {"value": "NOT_REQUIRED", "label": "Tidak Perlu"},
        ],
    )
    return render_template("accounting/posting_status.html", report=report, filter_bar=filter_bar)



@accounting_bp.route("/order-to-cash-trace")
@login_required
@role_required("OWNER", "ACCOUNTING")
def order_to_cash_trace():
    selected_order_number = request.args.get("order_number", "").strip()
    report = get_order_to_cash_trace_report(current_user.branch_id, selected_order_number)
    return render_template("accounting/order_to_cash_trace.html", report=report)


@accounting_bp.route("/order-to-cash-trace/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_order_to_cash_trace_csv():
    from app.services.accounting_export_service import build_order_to_cash_trace_export_response

    selected_order_number = request.args.get("order_number", "").strip()
    report = get_order_to_cash_trace_report(current_user.branch_id, selected_order_number)
    return build_order_to_cash_trace_export_response(report)




# === PRODUCTION_AUDIT_TRACE_PRINT_ROUTES ===
@accounting_bp.route("/data-health/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_data_health():
    from app.services.accounting_print_service import build_data_health_print_context

    report = get_data_health_report(current_user.branch_id)
    context = build_data_health_print_context(current_user.branch_id, report)
    return render_template("accounting/print_data_health.html", **context)


@accounting_bp.route("/daily-closing/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_daily_closing():
    from app.services.accounting_print_service import build_daily_closing_print_context

    selected_date = request.args.get("date", "")
    report = get_daily_closing_report(current_user.branch_id, selected_date)
    context = build_daily_closing_print_context(current_user.branch_id, report)
    return render_template("accounting/print_daily_closing.html", **context)


@accounting_bp.route("/order-to-cash-trace/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_order_to_cash_trace():
    from app.services.accounting_print_service import build_order_to_cash_trace_print_context

    selected_order_number = request.args.get("order_number", "").strip()
    report = get_order_to_cash_trace_report(current_user.branch_id, selected_order_number)
    context = build_order_to_cash_trace_print_context(current_user.branch_id, report)
    return render_template("accounting/print_order_to_cash_trace.html", **context)
