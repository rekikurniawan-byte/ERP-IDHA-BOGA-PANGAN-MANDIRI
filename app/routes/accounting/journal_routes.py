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
        idempotency_keys={
            "period_invoice": uuid4().hex,
            "payment": uuid4().hex,
            "warung_payment_correction": uuid4().hex,
            "hpp_production": uuid4().hex,
            "procurement": uuid4().hex,
        },
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
    from app.services.accounting_service import generate_period_invoice_journals_batch

    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_GENERATE_PERIOD_INVOICE_JOURNALS",
        {"action": "generate_period_invoice_journals"},
    )
    if idempotency_response:
        return idempotency_response

    try:
        result = generate_period_invoice_journals_batch(created_by=current_user.id)
        created_count = result["created_count"]
        skipped_count = result["skipped_count"]
        skipped_cancelled_count = result["skipped_cancelled_count"]

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

        mark_idempotency_completed(
            idempotency_record,
            reference_type="JOURNAL_BATCH",
            reference_id=None,
            response_payload={"created_count": created_count, "skipped_count": skipped_count},
            commit=True,
        )

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:405")
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
    from app.services.accounting_service import generate_payment_journals_batch

    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_GENERATE_PAYMENT_JOURNALS",
        {"action": "generate_payment_journals"},
    )
    if idempotency_response:
        return idempotency_response

    try:
        result = generate_payment_journals_batch(created_by=current_user.id)
        created_count = result["created_count"]
        skipped_count = result["skipped_count"]

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

        mark_idempotency_completed(
            idempotency_record,
            reference_type="JOURNAL_BATCH",
            reference_id=None,
            response_payload={"created_count": created_count, "skipped_count": skipped_count},
            commit=True,
        )

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:447")
        flash(f"Gagal generate jurnal pembayaran: {error}", "danger")

    return _redirect_after_accounting_post()
