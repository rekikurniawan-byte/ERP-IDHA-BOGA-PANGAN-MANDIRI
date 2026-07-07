from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required

from app.models.accounting import Account, Journal, JournalDetail
from app.utils.decorators import role_required
from app.services.data_health_service import get_data_health_report
from app.services.daily_closing_service import get_daily_closing_report
from app.services.order_to_cash_trace_service import get_order_to_cash_trace_report
from app.services.audit_log_service import record_audit_log
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context


accounting_bp = Blueprint("accounting", __name__, url_prefix="/accounting")


def _journal_total_debit(journal):
    return sum(float(detail.debit or 0) for detail in journal.details)


def _journal_total_credit(journal):
    return sum(float(detail.credit or 0) for detail in journal.details)


def _journal_is_balanced(journal):
    return round(_journal_total_debit(journal), 2) == round(_journal_total_credit(journal), 2)


def _redirect_after_accounting_post(default_endpoint="accounting.journals"):
    next_url = (request.form.get("next") or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for(default_endpoint))


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


@accounting_bp.route("/journals")
@login_required
@role_required("OWNER", "ACCOUNTING")
def journals():
    journals = Journal.query.order_by(
        Journal.journal_date.desc(),
        Journal.id.desc()
    ).all()

    journals_data = []

    for journal in journals:
        total_debit = _journal_total_debit(journal)
        total_credit = _journal_total_credit(journal)

        journals_data.append({
            "journal": journal,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "is_balanced": round(total_debit, 2) == round(total_credit, 2),
        })

    total_journal = len(journals)
    balanced_count = len([row for row in journals_data if row["is_balanced"]])
    unbalanced_count = total_journal - balanced_count

    return render_template(
        "accounting/journal_index.html",
        journals=journals_data,
        total_journal=total_journal,
        balanced_count=balanced_count,
        unbalanced_count=unbalanced_count
    )


@accounting_bp.route("/journals/<int:journal_id>")
@login_required
@role_required("OWNER", "ACCOUNTING", "FINANCE")
def journal_detail(journal_id):
    from app.services.field_transaction_service import find_field_transaction_linked_source

    journal = Journal.query.get_or_404(journal_id)

    total_debit = _journal_total_debit(journal)
    total_credit = _journal_total_credit(journal)
    is_balanced = round(total_debit, 2) == round(total_credit, 2)
    field_transaction_link = find_field_transaction_linked_source(
        "JOURNAL",
        journal.id,
        branch_id=current_user.branch_id,
    )

    return render_template(
        "accounting/journal_detail.html",
        journal=journal,
        total_debit=total_debit,
        total_credit=total_credit,
        is_balanced=is_balanced,
        field_transaction_link=field_transaction_link,
    )


# === PRODUCTION_ACCOUNTING_CSV_EXPORT_ROUTES ===
@accounting_bp.route("/journals/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_journals_csv():
    from app.services.accounting_export_service import build_journal_summary_export_response

    return build_journal_summary_export_response()


@accounting_bp.route("/journal-details/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_journal_details_csv():
    from datetime import date
    from app.services.accounting_export_service import build_journal_details_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    return build_journal_details_export_response(start_date=start_date, end_date=end_date)


# === PRODUCTION_ACCOUNTING_PRINT_PDF_CORE_ROUTES ===
@accounting_bp.route("/journals/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_journals():
    from app.services.accounting_print_service import build_journal_summary_print_context

    context = build_journal_summary_print_context(current_user.branch_id)
    return render_template("accounting/print_journals.html", **context)


@accounting_bp.route("/journals/<int:journal_id>/print")
@login_required
@role_required("OWNER", "ACCOUNTING", "FINANCE")
def print_journal_detail(journal_id):
    from app.services.accounting_print_service import build_journal_detail_print_context

    journal = Journal.query.get_or_404(journal_id)
    context = build_journal_detail_print_context(current_user.branch_id, journal)
    return render_template("accounting/print_journal_detail.html", **context)


# === PATCH_GENERATE_PERIOD_INVOICE_JOURNAL ===
def _generate_journal_number(journal_date):
    prefix = f"JRN-{journal_date.strftime('%Y%m%d')}"
    counter = Journal.query.filter(Journal.journal_number.like(f"{prefix}-%")).count() + 1

    while True:
        journal_number = f"{prefix}-{counter:03d}"
        existing = Journal.query.filter_by(journal_number=journal_number).first()

        if not existing:
            return journal_number

        counter += 1


def _get_active_account_by_code(account_code):
    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _build_invoice_journal_amounts(invoice):
    catering_total = 0
    warung_total = 0
    other_total = 0

    for item in invoice.items:
        item_type = str(item.item_type or "").upper()
        subtotal = float(item.subtotal or 0)

        if item_type in ["CATERING", "REVISION_INCREASE"]:
            catering_total += subtotal
        elif item_type in ["WARUNG_DEBT", "WARUNG"]:
            warung_total += subtotal
        else:
            other_total += subtotal

    return {
        "catering_total": catering_total,
        "warung_total": warung_total,
        "other_total": other_total,
        "total_credit": catering_total + warung_total + other_total,
        "total_debit": float(invoice.total_amount or 0),
    }


@accounting_bp.route("/journals/generate-period-invoice", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_period_invoice_journals():
    # ACCOUNTING10B_ALIGN_MANUAL_INVOICE_GENERATOR
    from flask import flash, redirect, url_for
    from flask_login import current_user
    from app.extensions import db
    from app.models.finance import Invoice
    from app.services.accounting_service import create_invoice_journal_for_invoice

    invoices = Invoice.query.filter(
        Invoice.source_type.in_(["PERIOD_INVOICE", "DAILY_ORDER", "MANUAL_BILLING_RECAP"])
    ).order_by(
        Invoice.invoice_date.asc(),
        Invoice.id.asc()
    ).all()

    created_count = 0
    skipped_count = 0
    skipped_cancelled_count = 0

    try:
        for invoice in invoices:
            status = str(getattr(invoice, "status", "") or "").upper()

            if status == "CANCELLED":
                skipped_count += 1
                skipped_cancelled_count += 1
                continue

            success, message, journal = create_invoice_journal_for_invoice(
                invoice=invoice,
                created_by=current_user.id,
                commit=False
            )

            if success:
                created_count += 1
            else:
                skipped_count += 1

        db.session.commit()

        if created_count > 0:
            record_audit_log(
                module="ACCOUNTING",
                event_type="JOURNAL_BATCH_PERIOD_INVOICE_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=None,
                description=f"Batch jurnal invoice dibuat: {created_count} jurnal, {skipped_count} dilewati.",
                metadata={"created_count": created_count, "skipped_count": skipped_count, "generator": "invoice_revenue_split_4001_4002"},
            )
            flash(
                f"Berhasil membuat {created_count} jurnal invoice melalui service accounting 4001/4002. "
                f"Skip {skipped_count} invoice.",
                "success"
            )
        else:
            if skipped_cancelled_count > 0:
                flash(
                    f"Tidak ada jurnal invoice baru. Skip {skipped_count} invoice, termasuk "
                    f"{skipped_cancelled_count} invoice cancelled.",
                    "info"
                )
            else:
                flash(
                    "Tidak ada jurnal invoice baru yang dibuat. Semua invoice periode/harian mungkin sudah dijurnal.",
                    "info"
                )

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal membuat jurnal invoice 4001/4002: {error}", "danger")

    return _redirect_after_accounting_post()


# === PATCH_GENERATE_PAYMENT_JOURNAL ===
@accounting_bp.route("/journals/generate-payment", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_payment_journals():
    # ACCOUNTING11C_ALIGN_MANUAL_PAYMENT_GENERATOR
    from flask import flash, redirect, url_for
    from flask_login import current_user
    from app.extensions import db
    from app.models.finance import Payment
    from app.services.accounting_service import create_payment_journal_for_payment

    payments = Payment.query.order_by(
        Payment.payment_date.asc(),
        Payment.id.asc()
    ).all()

    created_count = 0
    skipped_count = 0

    try:
        for payment in payments:
            success, message, journal = create_payment_journal_for_payment(
                payment=payment,
                created_by=current_user.id,
                commit=False
            )

            if success:
                created_count += 1
            else:
                skipped_count += 1

        db.session.commit()

        if created_count > 0:
            record_audit_log(
                module="ACCOUNTING",
                event_type="JOURNAL_BATCH_PAYMENT_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=None,
                description=f"Batch jurnal pembayaran dibuat: {created_count} jurnal, {skipped_count} dilewati.",
                metadata={"created_count": created_count, "skipped_count": skipped_count, "generator": "payment"},
            )
            flash(
                f"Berhasil membuat {created_count} jurnal pembayaran melalui service accounting. "
                f"Skip {skipped_count} payment.",
                "success"
            )
        else:
            flash(
                "Tidak ada jurnal pembayaran baru yang perlu dibuat. Semua payment mungkin sudah dijurnal.",
                "info"
            )

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal generate jurnal pembayaran: {error}", "danger")

    return _redirect_after_accounting_post()


# ACCOUNTING1B_REPORTS_ROUTE
def _accounting1b_parse_date(value, default_value):
    from datetime import datetime

    if not value:
        return default_value

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return default_value


def _accounting1b_money_value(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _accounting1b_trial_balance_side(account_type, debit, credit):
    account_type = str(account_type or "").upper()

    debit = _accounting1b_money_value(debit)
    credit = _accounting1b_money_value(credit)

    if account_type in ["ASSET", "EXPENSE", "COGS", "COST", "HPP"]:
        balance = debit - credit
        if balance >= 0:
            return balance, 0
        return 0, abs(balance)

    balance = credit - debit
    if balance >= 0:
        return 0, balance
    return abs(balance), 0


def _build_accounting1b_reports_data(start_date=None, end_date=None):
    from datetime import date
    from app.models.accounting import Account, Journal, JournalDetail

    today = date.today()

    if not start_date:
        start_date = date(today.year, today.month, 1)

    if not end_date:
        end_date = today

    accounts = Account.query.filter_by(is_active=True).order_by(Account.account_code.asc()).all()

    journals = Journal.query.filter(
        Journal.journal_date >= start_date,
        Journal.journal_date <= end_date
    ).order_by(
        Journal.journal_date.asc(),
        Journal.id.asc()
    ).all()

    journal_ids = [journal.id for journal in journals]

    details = []

    if journal_ids:
        details = JournalDetail.query.join(
            Journal, JournalDetail.journal_id == Journal.id
        ).join(
            Account, JournalDetail.account_id == Account.id
        ).filter(
            Journal.id.in_(journal_ids)
        ).order_by(
            Journal.journal_date.asc(),
            Journal.id.asc(),
            JournalDetail.id.asc()
        ).all()

    account_map = {}

    for account in accounts:
        account_map[account.id] = {
            "account": account,
            "details": [],
            "period_debit": 0,
            "period_credit": 0,
            "trial_debit": 0,
            "trial_credit": 0,
        }

    for detail in details:
        if detail.account_id not in account_map:
            continue

        debit = _accounting1b_money_value(detail.debit)
        credit = _accounting1b_money_value(detail.credit)

        account_map[detail.account_id]["details"].append(detail)
        account_map[detail.account_id]["period_debit"] += debit
        account_map[detail.account_id]["period_credit"] += credit

    ledger_rows = []
    trial_rows = []

    total_period_debit = 0
    total_period_credit = 0
    total_trial_debit = 0
    total_trial_credit = 0

    revenue_total = 0
    expense_total = 0

    for account_id, row in account_map.items():
        account = row["account"]
        period_debit = row["period_debit"]
        period_credit = row["period_credit"]

        trial_debit, trial_credit = _accounting1b_trial_balance_side(
            account.account_type,
            period_debit,
            period_credit
        )

        row["trial_debit"] = trial_debit
        row["trial_credit"] = trial_credit

        if period_debit > 0 or period_credit > 0 or row["details"]:
            ledger_rows.append(row)

        if period_debit > 0 or period_credit > 0 or trial_debit > 0 or trial_credit > 0:
            trial_rows.append(row)

        total_period_debit += period_debit
        total_period_credit += period_credit
        total_trial_debit += trial_debit
        total_trial_credit += trial_credit

        account_type = str(account.account_type or "").upper()

        if account_type == "REVENUE":
            revenue_total += max(period_credit - period_debit, 0)

        if account_type in ["EXPENSE", "COGS", "COST", "HPP"]:
            expense_total += max(period_debit - period_credit, 0)

    net_income = revenue_total - expense_total

    return {
        "start_date": start_date,
        "end_date": end_date,
        "journals": journals,
        "ledger_rows": ledger_rows,
        "trial_rows": trial_rows,
        "journal_count": len(journals),
        "detail_count": len(details),
        "total_period_debit": total_period_debit,
        "total_period_credit": total_period_credit,
        "total_trial_debit": total_trial_debit,
        "total_trial_credit": total_trial_credit,
        "is_period_balanced": round(total_period_debit, 2) == round(total_period_credit, 2),
        "is_trial_balanced": round(total_trial_debit, 2) == round(total_trial_credit, 2),
        "revenue_total": revenue_total,
        "expense_total": expense_total,
        "net_income": net_income,
    }


@accounting_bp.route("/reports")
@login_required
@role_required("OWNER", "ACCOUNTING")
def reports():
    from datetime import date
    from flask import request

    today = date.today()
    default_start = date(today.year, today.month, 1)
    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    start_date = date_filter.start_date or default_start
    end_date = date_filter.end_date or today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("accounting.reports"),
        reset_url=url_for("accounting.reports"),
        title="Filter Laporan Akuntansi",
        description="Custom tanggal untuk neraca saldo, buku besar, laba rugi, dan detail jurnal.",
    )

    return render_template(
        "accounting/reports.html",
        data=data,
        filter_bar=filter_bar,
    )


@accounting_bp.route("/reports/trial-balance/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_trial_balance_csv():
    from datetime import date
    from app.services.accounting_export_service import build_trial_balance_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    return build_trial_balance_export_response(data)


@accounting_bp.route("/reports/general-ledger/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_general_ledger_csv():
    from datetime import date
    from app.services.accounting_export_service import build_general_ledger_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    return build_general_ledger_export_response(data)


@accounting_bp.route("/reports/income-summary/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_income_summary_csv():
    from datetime import date
    from app.services.accounting_export_service import build_income_summary_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    return build_income_summary_export_response(data)


@accounting_bp.route("/reports/trial-balance/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_trial_balance():
    from datetime import date
    from app.services.accounting_print_service import build_trial_balance_print_context

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    context = build_trial_balance_print_context(current_user.branch_id, data)
    return render_template("accounting/print_trial_balance.html", **context)


@accounting_bp.route("/reports/general-ledger/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_general_ledger():
    from datetime import date
    from app.services.accounting_print_service import build_general_ledger_print_context

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    context = build_general_ledger_print_context(current_user.branch_id, data)
    return render_template("accounting/print_general_ledger.html", **context)


@accounting_bp.route("/reports/income-summary/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_income_summary():
    from datetime import date
    from app.services.accounting_print_service import build_income_summary_print_context

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    context = build_income_summary_print_context(current_user.branch_id, data)
    return render_template("accounting/print_income_summary.html", **context)


# ACCOUNTING2B_COA_MAPPING_ROUTE
def _accounting2b_money_value(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _accounting2b_find_source_account_refs():
    import re
    from pathlib import Path
    from collections import defaultdict

    code_refs = defaultdict(list)

    patterns = [
        r'_get_active_account_by_code\(["\'](\d+)["\']\)',
        r'get_active_account_by_code\(["\'](\d+)["\']\)',
        r'account_code\s*=\s*["\'](\d+)["\']',
        r'filter_by\(account_code\s*=\s*["\'](\d+)["\']',
    ]

    for file in Path("app").rglob("*.py"):
        file_name = str(file).lower()

        if "backup" in file_name or "__pycache__" in file_name:
            continue

        text_file = file.read_text(encoding="utf-8", errors="ignore")
        lines = text_file.splitlines()

        for idx, line in enumerate(lines, start=1):
            for pattern in patterns:
                matches = re.findall(pattern, line)

                for code in matches:
                    code_refs[code].append({
                        "file": str(file),
                        "line_number": idx,
                        "line": line.strip(),
                    })

    return dict(code_refs)


def _build_accounting2b_coa_mapping_data():
    from collections import defaultdict
    from sqlalchemy import text
    from app.extensions import db
    from app.models.accounting import Account

    accounts = Account.query.order_by(Account.account_code.asc()).all()

    account_lookup = {
        account.account_code: account
        for account in accounts
    }

    usage_rows = db.session.execute(text("""
        SELECT
            a.id AS account_id,
            a.account_code,
            a.account_name,
            a.account_type,
            a.is_active,
            COUNT(jd.id) AS detail_count,
            SUM(COALESCE(jd.debit, 0)) AS debit_total,
            SUM(COALESCE(jd.credit, 0)) AS credit_total
        FROM accounts a
        LEFT JOIN journal_details jd ON jd.account_id = a.id
        GROUP BY a.id, a.account_code, a.account_name, a.account_type, a.is_active
        ORDER BY a.account_code ASC
    """)).mappings().all()

    usage_by_code = {}

    for row in usage_rows:
        usage_by_code[row["account_code"]] = {
            "detail_count": int(row["detail_count"] or 0),
            "debit_total": _accounting2b_money_value(row["debit_total"]),
            "credit_total": _accounting2b_money_value(row["credit_total"]),
            "is_used": int(row["detail_count"] or 0) > 0,
        }

    mapping_plan = [
        {
            "stage": "SUDAH BERJALAN",
            "module": "Finance",
            "event": "Invoice catering proyek/harian + warung",
            "debit_codes": ["1004"],
            "credit_codes": ["4001", "4002", "4003", "4004"],
            "note": "PRODUCTION: invoice periode masuk 4001, invoice order harian masuk 4002. Piutang bertambah, pendapatan diakui.",
            "risk": "LOCKED",
        },
        {
            "stage": "SUDAH BERJALAN",
            "module": "Finance",
            "event": "Pembayaran invoice",
            "debit_codes": ["1001", "1002"],
            "credit_codes": ["1004"],
            "note": "Sudah berjalan. CASH masuk Kas, transfer idealnya masuk Bank 1.",
            "risk": "LOCKED",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Logistik",
            "event": "Pembelian barang tunai",
            "debit_codes": ["1006"],
            "credit_codes": ["1001", "1002"],
            "note": "Persediaan bahan baku bertambah, kas/bank berkurang.",
            "risk": "AMAN JIKA NOMINAL PEMBELIAN VALID",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Logistik",
            "event": "Pembelian barang kredit",
            "debit_codes": ["1006"],
            "credit_codes": ["2002"],
            "note": "Persediaan bertambah, hutang supplier bertambah.",
            "risk": "AMAN JIKA STATUS CREDIT SUDAH JELAS",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Produksi",
            "event": "Pemakaian bahan untuk produksi",
            "debit_codes": ["5001"],
            "credit_codes": ["1006"],
            "note": "Biaya bahan baku bertambah, persediaan bahan baku berkurang.",
            "risk": "BUTUH NILAI HARGA POKOK BARANG",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Logistik",
            "event": "Barang rusak / selisih stok keluar",
            "debit_codes": ["5002"],
            "credit_codes": ["1006"],
            "note": "Biaya operasional dapur bertambah, persediaan berkurang.",
            "risk": "BUTUH NILAI HARGA POKOK BARANG",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Warung",
            "event": "Hutang pekerja warung",
            "debit_codes": ["1005"],
            "credit_codes": ["4003"],
            "note": "Piutang karyawan bertambah, pendapatan warung diakui.",
            "risk": "AMAN JIKA HUTANG PEKERJA DIANGGAP PIUTANG KARYAWAN",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Warung",
            "event": "Pembayaran hutang pekerja",
            "debit_codes": ["1001"],
            "credit_codes": ["1005"],
            "note": "Kas bertambah, piutang karyawan berkurang.",
            "risk": "AMAN JIKA PAYMENT DEBT SUDAH FINAL",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "SDM",
            "event": "Pengakuan gaji karyawan",
            "debit_codes": ["5004"],
            "credit_codes": ["2003"],
            "note": "Gaji karyawan menjadi beban, hutang gaji bertambah.",
            "risk": "BUTUH MODUL GAJI",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "SDM",
            "event": "Pembayaran gaji",
            "debit_codes": ["2003"],
            "credit_codes": ["1001", "1002"],
            "note": "Hutang gaji berkurang, kas/bank berkurang.",
            "risk": "BUTUH MODUL GAJI",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Aset",
            "event": "Pembelian aset tetap",
            "debit_codes": ["1101", "1102", "1103"],
            "credit_codes": ["1001", "1002", "2001"],
            "note": "Aset tetap bertambah, kas/bank/hutang usaha berubah sesuai cara bayar.",
            "risk": "BUTUH MODUL ASET",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Aset",
            "event": "Penyusutan aset tetap",
            "debit_codes": ["5012"],
            "credit_codes": ["2101", "2102", "2103"],
            "note": "Beban penyusutan bertambah, akumulasi penyusutan bertambah.",
            "risk": "BUTUH MODUL ASET DAN UMUR MANFAAT",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Pajak",
            "event": "Pengakuan pajak",
            "debit_codes": ["5009"],
            "credit_codes": ["2004", "2005", "2006"],
            "note": "Beban pajak bertambah, hutang pajak bertambah.",
            "risk": "BUTUH ATURAN PAJAK BISNIS",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Owner",
            "event": "Setoran modal pemilik",
            "debit_codes": ["1001", "1002"],
            "credit_codes": ["3001"],
            "note": "Kas/bank bertambah, modal pemilik bertambah.",
            "risk": "JURNAL MANUAL OWNER",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Owner",
            "event": "Prive pemilik",
            "debit_codes": ["3003"],
            "credit_codes": ["1001", "1002"],
            "note": "Prive bertambah, kas/bank berkurang.",
            "risk": "JURNAL MANUAL OWNER",
        },
    ]

    def account_info(code):
        account = account_lookup.get(code)

        if not account:
            return {
                "code": code,
                "name": "AKUN BELUM ADA",
                "type": "-",
                "exists": False,
            }

        return {
            "code": account.account_code,
            "name": account.account_name,
            "type": account.account_type,
            "exists": True,
        }

    enriched_mapping = []

    proposed_by_account = defaultdict(list)

    for item in mapping_plan:
        debit_accounts = [account_info(code) for code in item["debit_codes"]]
        credit_accounts = [account_info(code) for code in item["credit_codes"]]

        for code in item["debit_codes"]:
            proposed_by_account[code].append(f"Debit: {item['event']}")

        for code in item["credit_codes"]:
            proposed_by_account[code].append(f"Credit: {item['event']}")

        enriched = dict(item)
        enriched["debit_accounts"] = debit_accounts
        enriched["credit_accounts"] = credit_accounts
        enriched["missing_accounts"] = [
            account for account in debit_accounts + credit_accounts
            if not account["exists"]
        ]

        enriched_mapping.append(enriched)

    accounts_by_type = defaultdict(list)

    for account in accounts:
        usage = usage_by_code.get(account.account_code, {
            "detail_count": 0,
            "debit_total": 0,
            "credit_total": 0,
            "is_used": False,
        })

        accounts_by_type[str(account.account_type or "UNKNOWN").upper()].append({
            "account": account,
            "usage": usage,
            "proposed": proposed_by_account.get(account.account_code, []),
        })

    used_count = sum(
        1 for row in usage_by_code.values()
        if row["is_used"]
    )

    unused_count = len(accounts) - used_count

    source_refs = _accounting2b_find_source_account_refs()

    source_code_accounts = []

    for code, refs in sorted(source_refs.items()):
        source_code_accounts.append({
            "code": code,
            "account": account_info(code),
            "refs": refs,
        })

    missing_accounts = []

    for item in enriched_mapping:
        for account in item["missing_accounts"]:
            missing_accounts.append({
                "event": item["event"],
                "code": account["code"],
            })

    return {
        "accounts": accounts,
        "accounts_by_type": dict(accounts_by_type),
        "usage_by_code": usage_by_code,
        "mapping_plan": enriched_mapping,
        "source_code_accounts": source_code_accounts,
        "missing_accounts": missing_accounts,
        "summary": {
            "total_accounts": len(accounts),
            "used_accounts": used_count,
            "unused_accounts": unused_count,
            "mapping_events": len(enriched_mapping),
            "source_code_account_count": len(source_code_accounts),
            "missing_account_count": len(missing_accounts),
        }
    }


@accounting_bp.route("/coa-mapping")
@login_required
@role_required("OWNER", "ACCOUNTING")
def coa_mapping():
    data = _build_accounting2b_coa_mapping_data()

    return render_template(
        "accounting/coa_mapping.html",
        data=data
    )


# ACCOUNTING2E_PROCUREMENT_JOURNAL_GENERATOR
def _accounting2e_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _accounting2e_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting2e_procurement_amount(procurement):
    amount = _accounting2e_float(getattr(procurement, "total_amount", 0))

    if amount > 0:
        return amount

    total = 0

    for item in getattr(procurement, "items", []) or []:
        total += _accounting2e_float(getattr(item, "subtotal", 0))

    return total


def _accounting2e_purchase_credit_account(procurement):
    purchase_type = str(getattr(procurement, "purchase_type", "") or "").upper()

    if purchase_type == "CASH":
        return _accounting2e_get_account("1001"), "Kas"

    if purchase_type == "CREDIT":
        return _accounting2e_get_account("2002"), "Hutang Supplier"

    if purchase_type in ["TRANSFER", "BANK"]:
        return _accounting2e_get_account("1002"), "Bank 1"

    return None, "UNKNOWN"


def _build_accounting2e_procurement_candidates():
    from app.models.logistics import Procurement
    from app.models.accounting import Journal

    procurements = Procurement.query.order_by(
        Procurement.procurement_date.asc(),
        Procurement.id.asc()
    ).all()

    candidates = []

    for procurement in procurements:
        existing = Journal.query.filter_by(
            reference_type="PROCUREMENT",
            reference_id=procurement.id
        ).first()

        amount = _accounting2e_procurement_amount(procurement)
        credit_account, credit_label = _accounting2e_purchase_credit_account(procurement)

        candidates.append({
            "procurement": procurement,
            "amount": amount,
            "purchase_type": str(procurement.purchase_type or "").upper(),
            "credit_account": credit_account,
            "credit_label": credit_label,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and amount > 0
                and credit_account is not None
            ),
        })

    return candidates


def _generate_accounting2e_procurement_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_inventory = _accounting2e_get_account("1006")

    missing_accounts = []

    if not acc_inventory:
        missing_accounts.append("1006 - Persediaan Bahan Baku")

    candidates = _build_accounting2e_procurement_candidates()

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    for candidate in candidates:
        procurement = candidate["procurement"]
        amount = candidate["amount"]
        credit_account = candidate["credit_account"]
        purchase_type = candidate["purchase_type"]

        if candidate["existing_journal"]:
            skipped.append({
                "procurement": procurement,
                "reason": "Sudah ada jurnal",
            })
            continue

        if amount <= 0:
            skipped.append({
                "procurement": procurement,
                "reason": "Nominal pembelian tidak valid",
            })
            continue

        if credit_account is None:
            skipped.append({
                "procurement": procurement,
                "reason": f"Tipe pembelian belum didukung: {purchase_type}",
            })
            continue

        journal = Journal(
            journal_number=_generate_journal_number(procurement.procurement_date),
            journal_date=procurement.procurement_date,
            reference_type="PROCUREMENT",
            reference_id=procurement.id,
            description=f"Jurnal pembelian barang {procurement.procurement_number} - {purchase_type}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_inventory.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=credit_account.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "procurement": procurement,
            "amount": amount,
            "debit_account": acc_inventory,
            "credit_account": credit_account,
        })

    if commit:
        db.session.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


@accounting_bp.route("/journals/generate-procurement", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_procurement_journals():
    from flask import flash, redirect, url_for
    from flask_login import current_user
    from app.extensions import db

    try:
        result = _generate_accounting2e_procurement_journals(
            created_by_id=current_user.id,
            commit=True
        )

        if result["errors"]:
            for error in result["errors"]:
                flash(error, "danger")

            db.session.rollback()
            return _redirect_after_accounting_post()

        created_count = len(result["created"])
        skipped_count = len(result["skipped"])

        if created_count > 0:
            record_audit_log(
                module="ACCOUNTING",
                event_type="JOURNAL_BATCH_PROCUREMENT_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=None,
                description=f"Batch jurnal pembelian dibuat: {created_count} jurnal, {skipped_count} dilewati.",
                metadata={"created_count": created_count, "skipped_count": skipped_count, "generator": "procurement"},
            )
            flash(f"{created_count} jurnal pembelian berhasil dibuat. {skipped_count} data dilewati.", "success")
        else:
            flash("Tidak ada jurnal pembelian baru yang dibuat. Semua data mungkin sudah dijurnal.", "info")

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal generate jurnal pembelian: {error}", "danger")

    return _redirect_after_accounting_post()


# ACCOUNTING3B_OPENING_BALANCE_ROUTE
def _accounting3b_float(value):
    try:
        if value is None:
            return 0

        value = str(value).strip()

        if value == "":
            return 0

        value = value.replace("Rp", "").replace(" ", "")

        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")
        elif "," in value:
            value = value.replace(",", ".")
        else:
            value = value.replace(".", "") if value.count(".") > 1 else value

        return float(value or 0)
    except Exception:
        return 0


def _accounting3b_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting3b_account_balance(account_code):
    from app.models.accounting import JournalDetail

    account = _accounting3b_get_account(account_code)

    if not account:
        return 0

    details = JournalDetail.query.filter_by(account_id=account.id).all()

    debit = sum(float(detail.debit or 0) for detail in details)
    credit = sum(float(detail.credit or 0) for detail in details)

    account_type = str(account.account_type or "").upper()

    if account_type in ["ASSET", "EXPENSE"]:
        return debit - credit

    return credit - debit


def _accounting3b_existing_opening_journal():
    from app.models.accounting import Journal

    return Journal.query.filter_by(
        reference_type="SALDO_AWAL"
    ).first()


def _build_accounting3b_opening_balance_data():
    from app.models.accounting import Account, JournalDetail

    asset_fields = [
        {"name": "cash", "code": "1001", "label": "Kas"},
        {"name": "bank1", "code": "1002", "label": "Bank 1"},
        {"name": "bank2", "code": "1003", "label": "Bank 2"},
        {"name": "receivable", "code": "1004", "label": "Piutang Usaha Awal"},
        {"name": "inventory", "code": "1006", "label": "Persediaan Bahan Baku"},
        {"name": "equipment", "code": "1101", "label": "Peralatan Dapur"},
        {"name": "vehicle", "code": "1102", "label": "Kendaraan Operasional"},
        {"name": "building", "code": "1103", "label": "Bangunan / Dapur"},
    ]

    liability_fields = [
        {"name": "ap_usaha", "code": "2001", "label": "Hutang Usaha Awal"},
        {"name": "ap_supplier", "code": "2002", "label": "Hutang Supplier Awal"},
    ]

    current_balances = []

    for code in ["1001", "1002", "1003", "1004", "1006", "1101", "1102", "1103", "2001", "2002", "3001"]:
        account = _accounting3b_get_account(code)

        if not account:
            continue

        current_balances.append({
            "account": account,
            "balance": _accounting3b_account_balance(code),
        })

    cash_balance = _accounting3b_account_balance("1001")
    suggested_cash = abs(cash_balance) if cash_balance < 0 else 0

    existing = _accounting3b_existing_opening_journal()

    return {
        "asset_fields": asset_fields,
        "liability_fields": liability_fields,
        "current_balances": current_balances,
        "cash_balance": cash_balance,
        "suggested_cash": suggested_cash,
        "existing_opening_journal": existing,
    }


def _generate_accounting3b_opening_balance_journal(form_data, created_by_id, commit=True):
    from datetime import datetime, date
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    existing = _accounting3b_existing_opening_journal()

    if existing:
        return {
            "journal": None,
            "details": [],
            "errors": [f"Jurnal saldo awal sudah ada: {existing.journal_number}"],
        }

    try:
        journal_date = datetime.strptime(form_data.get("journal_date"), "%Y-%m-%d").date()
    except Exception:
        journal_date = date.today()

    asset_fields = [
        ("cash", "1001", "Kas"),
        ("bank1", "1002", "Bank 1"),
        ("bank2", "1003", "Bank 2"),
        ("receivable", "1004", "Piutang Usaha Awal"),
        ("inventory", "1006", "Persediaan Bahan Baku"),
        ("equipment", "1101", "Peralatan Dapur"),
        ("vehicle", "1102", "Kendaraan Operasional"),
        ("building", "1103", "Bangunan / Dapur"),
    ]

    liability_fields = [
        ("ap_usaha", "2001", "Hutang Usaha Awal"),
        ("ap_supplier", "2002", "Hutang Supplier Awal"),
    ]

    entries = []
    errors = []

    total_debit = 0
    total_liability_credit = 0

    for field_name, account_code, label in asset_fields:
        amount = _accounting3b_float(form_data.get(field_name))

        if amount < 0:
            errors.append(f"Nominal {label} tidak boleh minus.")
            continue

        if amount > 0:
            account = _accounting3b_get_account(account_code)

            if not account:
                errors.append(f"Akun {account_code} - {label} tidak ditemukan/aktif.")
                continue

            entries.append({
                "account": account,
                "debit": amount,
                "credit": 0,
                "label": label,
            })

            total_debit += amount

    for field_name, account_code, label in liability_fields:
        amount = _accounting3b_float(form_data.get(field_name))

        if amount < 0:
            errors.append(f"Nominal {label} tidak boleh minus.")
            continue

        if amount > 0:
            account = _accounting3b_get_account(account_code)

            if not account:
                errors.append(f"Akun {account_code} - {label} tidak ditemukan/aktif.")
                continue

            entries.append({
                "account": account,
                "debit": 0,
                "credit": amount,
                "label": label,
            })

            total_liability_credit += amount

    if total_debit <= 0:
        errors.append("Minimal isi salah satu saldo aset awal, misalnya Kas atau Bank.")

    modal_amount = total_debit - total_liability_credit

    if modal_amount < 0:
        errors.append("Total hutang awal lebih besar dari total aset awal. Modal pemilik menjadi minus, tahan dulu.")

    if modal_amount > 0:
        modal_account = _accounting3b_get_account("3001")

        if not modal_account:
            errors.append("Akun 3001 - Modal Pemilik tidak ditemukan/aktif.")
        else:
            entries.append({
                "account": modal_account,
                "debit": 0,
                "credit": modal_amount,
                "label": "Modal Pemilik",
            })

    final_debit = sum(float(entry["debit"] or 0) for entry in entries)
    final_credit = sum(float(entry["credit"] or 0) for entry in entries)

    if round(final_debit, 2) != round(final_credit, 2):
        errors.append(f"Jurnal saldo awal tidak balance. Debit {final_debit}, Credit {final_credit}.")

    if errors:
        return {
            "journal": None,
            "details": entries,
            "errors": errors,
        }

    description = "Jurnal saldo awal / modal pemilik"

    journal = Journal(
        journal_number=_generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type="SALDO_AWAL",
        reference_id=0,
        description=description,
        created_by=created_by_id
    )

    db.session.add(journal)
    db.session.flush()

    created_details = []

    for entry in entries:
        detail = JournalDetail(
            journal_id=journal.id,
            account_id=entry["account"].id,
            debit=float(entry["debit"] or 0),
            credit=float(entry["credit"] or 0)
        )

        db.session.add(detail)
        created_details.append(detail)

    if commit:
        db.session.commit()

    return {
        "journal": journal,
        "details": created_details,
        "errors": [],
    }


@accounting_bp.route("/opening-balance", methods=["GET", "POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def opening_balance():
    from flask import request, flash, redirect, url_for
    from flask_login import current_user
    from app.extensions import db

    if request.method == "POST":
        try:
            result = _generate_accounting3b_opening_balance_journal(
                form_data=request.form,
                created_by_id=current_user.id,
                commit=True
            )

            if result["errors"]:
                for error in result["errors"]:
                    flash(error, "danger")

                db.session.rollback()
                return redirect(url_for("accounting.opening_balance"))

            journal = result["journal"]
            record_audit_log(
                module="ACCOUNTING",
                event_type="OPENING_BALANCE_JOURNAL_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=journal.id,
                description=f"Jurnal saldo awal dibuat: {journal.journal_number}.",
                metadata={"journal_number": journal.journal_number, "journal_date": journal.journal_date},
            )
            flash(f"Jurnal saldo awal berhasil dibuat: {journal.journal_number}", "success")
            return redirect(url_for("accounting.journal_detail", journal_id=journal.id))

        except Exception as error:
            db.session.rollback()
            flash(f"Gagal membuat jurnal saldo awal: {error}", "danger")
            return redirect(url_for("accounting.opening_balance"))

    data = _build_accounting3b_opening_balance_data()

    return render_template(
        "accounting/opening_balance.html",
        data=data
    )


# ACCOUNTING4B_HPP_PRODUCTION_GENERATOR
def _accounting4b_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _accounting4b_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting4b_get_item_average_cost(item_id):
    from app.extensions import db
    from sqlalchemy import text

    row = db.session.execute(text("""
        SELECT
            SUM(COALESCE(qty, 0)) AS total_qty,
            SUM(COALESCE(subtotal, 0)) AS total_value
        FROM procurement_items
        WHERE item_id = :item_id
    """), {"item_id": item_id}).mappings().first()

    total_qty = _accounting4b_float(row["total_qty"] if row else 0)
    total_value = _accounting4b_float(row["total_value"] if row else 0)

    if total_qty <= 0 or total_value <= 0:
        return {
            "total_qty": total_qty,
            "total_value": total_value,
            "avg_cost": 0,
        }

    return {
        "total_qty": total_qty,
        "total_value": total_value,
        "avg_cost": total_value / total_qty,
    }


def _build_accounting4b_hpp_candidates():
    from app.extensions import db
    from app.models.accounting import Journal
    from app.models.master import Item
    from app.models.logistics import StockMovement

    movements = StockMovement.query.filter_by(
        reference_type="PEMAKAIAN_PRODUKSI",
        movement_type="OUT"
    ).order_by(
        StockMovement.movement_date.asc(),
        StockMovement.id.asc()
    ).all()

    candidates = []

    for movement in movements:
        item = Item.query.get(movement.item_id)
        cost_info = _accounting4b_get_item_average_cost(movement.item_id)

        usage_qty = _accounting4b_float(movement.qty)
        avg_cost = _accounting4b_float(cost_info.get("avg_cost"))
        amount = round(usage_qty * avg_cost, 2)

        existing = Journal.query.filter_by(
            reference_type="HPP_PRODUKSI",
            reference_id=movement.id
        ).first()

        candidates.append({
            "movement": movement,
            "item": item,
            "usage_qty": usage_qty,
            "avg_cost": avg_cost,
            "amount": amount,
            "cost_info": cost_info,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and usage_qty > 0
                and avg_cost > 0
                and amount > 0
            ),
        })

    return candidates


def _generate_accounting4b_hpp_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_hpp = _accounting4b_get_account("5001")
    acc_inventory = _accounting4b_get_account("1006")

    missing_accounts = []

    if not acc_hpp:
        missing_accounts.append("5001 - Biaya Bahan Baku")

    if not acc_inventory:
        missing_accounts.append("1006 - Persediaan Bahan Baku")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting4b_hpp_candidates()

    for candidate in candidates:
        movement = candidate["movement"]
        item = candidate["item"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "movement": movement,
                "reason": "Sudah ada jurnal HPP",
            })
            continue

        if candidate["usage_qty"] <= 0:
            skipped.append({
                "movement": movement,
                "reason": "Qty pemakaian tidak valid",
            })
            continue

        if candidate["avg_cost"] <= 0:
            skipped.append({
                "movement": movement,
                "reason": "Harga rata-rata item belum tersedia",
            })
            continue

        if amount <= 0:
            skipped.append({
                "movement": movement,
                "reason": "Nominal HPP tidak valid",
            })
            continue

        item_name = item.item_name if item else f"Item #{movement.item_id}"

        journal = Journal(
            journal_number=_generate_journal_number(movement.movement_date),
            journal_date=movement.movement_date,
            reference_type="HPP_PRODUKSI",
            reference_id=movement.id,
            description=f"Jurnal HPP pemakaian produksi {item_name} - Stock Movement #{movement.id}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_hpp.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_inventory.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "movement": movement,
            "item": item,
            "amount": amount,
            "avg_cost": candidate["avg_cost"],
            "usage_qty": candidate["usage_qty"],
            "debit_account": acc_hpp,
            "credit_account": acc_inventory,
        })

    if commit:
        db.session.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


@accounting_bp.route("/journals/generate-hpp-production", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_hpp_production_journals():
    from flask import flash, redirect, url_for
    from flask_login import current_user
    from app.extensions import db

    try:
        result = _generate_accounting4b_hpp_journals(
            created_by_id=current_user.id,
            commit=True
        )

        if result["errors"]:
            for error in result["errors"]:
                flash(error, "danger")

            db.session.rollback()
            return _redirect_after_accounting_post()

        created_count = len(result["created"])
        skipped_count = len(result["skipped"])

        if created_count > 0:
            record_audit_log(
                module="ACCOUNTING",
                event_type="JOURNAL_BATCH_HPP_PRODUCTION_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=None,
                description=f"Batch jurnal HPP produksi dibuat: {created_count} jurnal, {skipped_count} dilewati.",
                metadata={"created_count": created_count, "skipped_count": skipped_count, "generator": "hpp_production"},
            )
            flash(f"{created_count} jurnal HPP produksi berhasil dibuat. {skipped_count} data dilewati.", "success")
        else:
            flash("Tidak ada jurnal HPP produksi baru yang dibuat. Semua data mungkin sudah dijurnal atau belum punya harga.", "info")

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal generate jurnal HPP produksi: {error}", "danger")

    return _redirect_after_accounting_post()


# ACCOUNTING7C_WARUNG_PAYMENT_CORRECTION_GENERATOR
def _accounting7c_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _accounting7c_to_date(value):
    from datetime import date, datetime

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        value = value.strip()

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass

    raise ValueError(f"Format tanggal payment warung tidak valid: {value}")


def _accounting7c_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _build_accounting7c_warung_payment_correction_candidates():
    from app.extensions import db
    from app.models.accounting import Journal
    from sqlalchemy import text

    payment_rows = db.session.execute(text("""
        SELECT
            dp.id AS debt_payment_id,
            dp.worker_debt_id,
            dp.payment_date,
            dp.amount,
            dp.notes,
            wd.worker_id,
            wd.sale_id,
            wd.debt_amount,
            wd.status AS debt_status
        FROM debt_payments dp
        JOIN worker_debts wd ON wd.id = dp.worker_debt_id
        ORDER BY dp.payment_date ASC, dp.id ASC
    """)).mappings().all()

    existing_reference_types = [
        "WARUNG_PAYMENT_CORRECTION",
        "DEBT_PAYMENT",
        "WORKER_DEBT_PAYMENT",
        "WARUNG_PAYMENT",
    ]

    candidates = []

    for row in payment_rows:
        existing = Journal.query.filter(
            Journal.reference_type.in_(existing_reference_types),
            Journal.reference_id == row["debt_payment_id"]
        ).first()

        amount = _accounting7c_float(row["amount"])

        candidates.append({
            "payment": dict(row),
            "amount": amount,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and amount > 0
            ),
        })

    return candidates


def _generate_accounting7c_warung_payment_correction_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_cash = _accounting7c_get_account("1001")
    acc_warung_revenue = _accounting7c_get_account("4003")

    missing_accounts = []

    if not acc_cash:
        missing_accounts.append("1001 - Kas")

    if not acc_warung_revenue:
        missing_accounts.append("4003 - Pendapatan Warung")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting7c_warung_payment_correction_candidates()

    for candidate in candidates:
        payment = candidate["payment"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "payment": payment,
                "reason": "Sudah ada jurnal koreksi/payment warung",
            })
            continue

        if amount <= 0:
            skipped.append({
                "payment": payment,
                "reason": "Nominal payment tidak valid",
            })
            continue

        payment_date = _accounting7c_to_date(payment["payment_date"])

        journal = Journal(
            journal_number=_generate_journal_number(payment_date),
            journal_date=payment_date,
            reference_type="WARUNG_PAYMENT_CORRECTION",
            reference_id=payment["debt_payment_id"],
            description=f"Koreksi payment hutang warung pekerja - Debt Payment #{payment['debt_payment_id']}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_cash.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_warung_revenue.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "payment": payment,
            "amount": amount,
            "debit_account": acc_cash,
            "credit_account": acc_warung_revenue,
        })

    if commit:
        db.session.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


@accounting_bp.route("/journals/generate-warung-payment-correction", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_warung_payment_correction_journals():
    from flask import flash, redirect, url_for
    from flask_login import current_user
    from app.extensions import db

    try:
        result = _generate_accounting7c_warung_payment_correction_journals(
            created_by_id=current_user.id,
            commit=True
        )

        if result["errors"]:
            for error in result["errors"]:
                flash(error, "danger")

            db.session.rollback()
            return _redirect_after_accounting_post()

        created_count = len(result["created"])
        skipped_count = len(result["skipped"])
        created_total = sum(float(row["amount"] or 0) for row in result["created"])

        if created_count > 0:
            flash(f"{created_count} jurnal koreksi payment warung berhasil dibuat senilai Rp {created_total:,.0f}. {skipped_count} data dilewati.", "success")
        else:
            flash("Tidak ada jurnal koreksi payment warung baru yang dibuat. Semua data mungkin sudah dijurnal.", "info")

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal generate koreksi payment warung: {error}", "danger")

    return _redirect_after_accounting_post()


# ACCOUNTING9B_WARUNG_FUTURE_ACCRUAL_HELPER
ACCOUNTING9B_CUTOVER_WORKER_DEBT_ID = 2
ACCOUNTING9B_CUTOVER_DEBT_PAYMENT_ID = 4
ACCOUNTING9B_CUTOVER_INVOICE_ID = 2


def _accounting9b_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _accounting9b_to_date(value):
    from datetime import date, datetime

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        value = value.strip()

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass

    raise ValueError(f"Format tanggal warung future tidak valid: {value}")


def _accounting9b_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting9b_existing_journal(reference_types, reference_id):
    from app.models.accounting import Journal

    return Journal.query.filter(
        Journal.reference_type.in_(reference_types),
        Journal.reference_id == reference_id
    ).first()


def _build_accounting9b_warung_debt_accrual_candidates(include_protected_existing=False):
    from app.extensions import db
    from sqlalchemy import text

    where_clause = ""

    if not include_protected_existing:
        where_clause = "WHERE wd.id > :cutover_worker_debt_id"

    sql = f"""
        SELECT
            wd.id AS worker_debt_id,
            wd.branch_id,
            wd.worker_id,
            wd.sale_id,
            wd.debt_amount,
            wd.status AS debt_status,
            wd.created_at AS worker_debt_created_at,
            cs.sale_date,
            cs.sale_type,
            cs.total_amount AS sale_total_amount
        FROM worker_debts wd
        JOIN canteen_sales cs ON cs.id = wd.sale_id
        {where_clause}
        ORDER BY wd.id ASC
    """

    rows = db.session.execute(text(sql), {
        "cutover_worker_debt_id": ACCOUNTING9B_CUTOVER_WORKER_DEBT_ID
    }).mappings().all()

    candidates = []

    for row in rows:
        row_dict = dict(row)
        worker_debt_id = row_dict["worker_debt_id"]
        amount = _accounting9b_float(row_dict["debt_amount"])
        protected_existing = worker_debt_id <= ACCOUNTING9B_CUTOVER_WORKER_DEBT_ID

        existing = _accounting9b_existing_journal(
            ["WARUNG_DEBT_ACCRUAL"],
            worker_debt_id
        )

        candidates.append({
            "worker_debt": row_dict,
            "amount": amount,
            "journal_date": _accounting9b_to_date(row_dict["sale_date"]),
            "existing_journal": existing,
            "protected_existing": protected_existing,
            "can_generate": (
                existing is None
                and amount > 0
                and not protected_existing
            ),
        })

    return candidates


def _generate_accounting9b_warung_debt_accrual_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_piutang_karyawan = _accounting9b_get_account("1005")
    acc_pendapatan_warung = _accounting9b_get_account("4003")

    missing_accounts = []

    if not acc_piutang_karyawan:
        missing_accounts.append("1005 - Piutang Karyawan")

    if not acc_pendapatan_warung:
        missing_accounts.append("4003 - Pendapatan Warung")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting9b_warung_debt_accrual_candidates()

    for candidate in candidates:
        worker_debt = candidate["worker_debt"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "worker_debt": worker_debt,
                "reason": "Sudah ada jurnal WARUNG_DEBT_ACCRUAL",
            })
            continue

        if candidate["protected_existing"]:
            skipped.append({
                "worker_debt": worker_debt,
                "reason": "Data lama dilindungi cutover",
            })
            continue

        if amount <= 0:
            skipped.append({
                "worker_debt": worker_debt,
                "reason": "Nominal hutang warung tidak valid",
            })
            continue

        journal = Journal(
            journal_number=_generate_journal_number(candidate["journal_date"]),
            journal_date=candidate["journal_date"],
            reference_type="WARUNG_DEBT_ACCRUAL",
            reference_id=worker_debt["worker_debt_id"],
            description=f"Accrual hutang warung pekerja - Worker Debt #{worker_debt['worker_debt_id']}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_piutang_karyawan.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_pendapatan_warung.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "worker_debt": worker_debt,
            "amount": amount,
            "debit_account": acc_piutang_karyawan,
            "credit_account": acc_pendapatan_warung,
        })

    if commit:
        db.session.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


def _build_accounting9b_warung_debt_payment_candidates(include_protected_existing=False):
    from app.extensions import db
    from sqlalchemy import text

    where_clause = ""

    if not include_protected_existing:
        where_clause = "WHERE dp.id > :cutover_debt_payment_id"

    sql = f"""
        SELECT
            dp.id AS debt_payment_id,
            dp.worker_debt_id,
            dp.payment_date,
            dp.amount,
            dp.notes,
            wd.worker_id,
            wd.sale_id,
            wd.debt_amount,
            wd.status AS debt_status
        FROM debt_payments dp
        JOIN worker_debts wd ON wd.id = dp.worker_debt_id
        {where_clause}
        ORDER BY dp.id ASC
    """

    rows = db.session.execute(text(sql), {
        "cutover_debt_payment_id": ACCOUNTING9B_CUTOVER_DEBT_PAYMENT_ID
    }).mappings().all()

    candidates = []

    for row in rows:
        row_dict = dict(row)
        debt_payment_id = row_dict["debt_payment_id"]
        amount = _accounting9b_float(row_dict["amount"])
        protected_existing = debt_payment_id <= ACCOUNTING9B_CUTOVER_DEBT_PAYMENT_ID

        existing = _accounting9b_existing_journal(
            [
                "WARUNG_DEBT_PAYMENT",
                "WARUNG_PAYMENT_CORRECTION",
                "DEBT_PAYMENT",
                "WORKER_DEBT_PAYMENT",
                "WARUNG_PAYMENT",
            ],
            debt_payment_id
        )

        candidates.append({
            "payment": row_dict,
            "amount": amount,
            "journal_date": _accounting9b_to_date(row_dict["payment_date"]),
            "existing_journal": existing,
            "protected_existing": protected_existing,
            "can_generate": (
                existing is None
                and amount > 0
                and not protected_existing
            ),
        })

    return candidates


def _generate_accounting9b_warung_debt_payment_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_cash = _accounting9b_get_account("1001")
    acc_piutang_karyawan = _accounting9b_get_account("1005")

    missing_accounts = []

    if not acc_cash:
        missing_accounts.append("1001 - Kas")

    if not acc_piutang_karyawan:
        missing_accounts.append("1005 - Piutang Karyawan")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting9b_warung_debt_payment_candidates()

    for candidate in candidates:
        payment = candidate["payment"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "payment": payment,
                "reason": "Sudah ada jurnal payment warung",
            })
            continue

        if candidate["protected_existing"]:
            skipped.append({
                "payment": payment,
                "reason": "Data lama dilindungi cutover",
            })
            continue

        if amount <= 0:
            skipped.append({
                "payment": payment,
                "reason": "Nominal payment warung tidak valid",
            })
            continue

        journal = Journal(
            journal_number=_generate_journal_number(candidate["journal_date"]),
            journal_date=candidate["journal_date"],
            reference_type="WARUNG_DEBT_PAYMENT",
            reference_id=payment["debt_payment_id"],
            description=f"Pembayaran hutang warung pekerja - Debt Payment #{payment['debt_payment_id']}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_cash.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_piutang_karyawan.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "payment": payment,
            "amount": amount,
            "debit_account": acc_cash,
            "credit_account": acc_piutang_karyawan,
        })

    if commit:
        db.session.commit()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


def _build_accounting9b_future_invoice_journal_amounts(invoice, include_protected_existing=False):
    protected_existing = invoice.id <= ACCOUNTING9B_CUTOVER_INVOICE_ID

    if protected_existing and not include_protected_existing:
        return {
            "protected_existing": True,
            "total_debit": _accounting9b_float(invoice.total_amount),
            "credits": {},
            "total_credit": 0,
            "catering_total": 0,
            "warung_transfer_total": 0,
            "other_total": 0,
        }

    catering_total = 0
    warung_transfer_total = 0
    other_total = 0

    for item in invoice.items:
        item_type = str(item.item_type or "").upper()
        subtotal = _accounting9b_float(item.subtotal)

        if item_type in ["CATERING", "REVISION_INCREASE"]:
            catering_total += subtotal
        elif item_type in ["WARUNG_DEBT", "WARUNG"]:
            warung_transfer_total += subtotal
        else:
            other_total += subtotal

    credits = {}

    if catering_total > 0:
        credits["4001"] = catering_total

    if warung_transfer_total > 0:
        credits["1005"] = warung_transfer_total

    if other_total > 0:
        credits["4004"] = other_total

    return {
        "protected_existing": protected_existing,
        "total_debit": _accounting9b_float(invoice.total_amount),
        "credits": credits,
        "total_credit": sum(credits.values()),
        "catering_total": catering_total,
        "warung_transfer_total": warung_transfer_total,
        "other_total": other_total,
    }



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
        flash(f"Closing periode {closing.closing_number} berhasil diposting ke 3002 Laba Ditahan.", "success")
        return redirect(url_for("accounting.period_closing_detail", closing_id=closing.id))
    except Exception as exc:
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
