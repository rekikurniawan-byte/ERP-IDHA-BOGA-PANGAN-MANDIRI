"""Accounting journal routes.

Route functions moved out of app.routes.accounting_routes without changing URL rules or endpoint names.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403
from app.routes.accounting_routes import _journal_total_credit, _journal_total_debit
from datetime import datetime


def _accounting_parse_date(value, default_value):
    if not value:
        return default_value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default_value


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
        unbalanced_count=unbalanced_count,
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

    from app.utils.clock import today_wib
    today = today_wib()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting_parse_date(request.args.get("end_date"), today)
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
