from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, send_file
from flask_login import current_user

from app.extensions import limiter
from app.utils.decorators import role_required
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context, apply_date_range_to_query
from app.models.finance import Invoice, Payment, BankAccount, SupplierBill, SupplierPayment
from app.models.master import Client, Mandor, ClientPic
from app.services.company_settings_service import get_company_settings
from app.services.invoice_identity_service import (
    apply_invoice_identity_snapshot,
    build_company_bank_snapshot,
    get_active_client_pics,
    get_invoice_official_identity,
    get_required_client_pic,
)
from app.services.audit_log_service import record_audit_log
from app.services.atomic_transaction_service import atomic_business_action
from app.services.billing_input_source_service import (
    INPUT_SOURCE_REALTIME,
    build_input_source_context,
)
from app.services.business_logic_guard_service import (
    BusinessRuleError,
    CUSTOMER_PAYMENT_METHODS,
    INVOICE_CANCELLED_STATUSES,
    assert_date_not_before,
    assert_not_future_date,
    assert_payment_amount_not_over_remaining,
    resolve_invoice_status_after_payment,
    validate_choice,
)

from app.services.digital_attachment_service import (
    AttachmentValidationError,
    format_file_size,
    get_allowed_extensions,
    get_attachment_file_path,
    get_attachment_or_none,
    get_max_upload_bytes,
    list_reference_attachments,
    count_reference_attachments,
    save_digital_attachment,
    soft_delete_attachment,
)


finance_bp = Blueprint("finance", __name__, url_prefix="/finance")


CUSTOMER_PAYMENT_ATTACHMENT_MODULE = "CUSTOMER_PAYMENT"
CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE = "PAYMENT"
SUPPLIER_PAYMENT_ATTACHMENT_MODULE = "SUPPLIER_PAYMENT"
SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE = "SUPPLIER_PAYMENT"


def _payment_or_404(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.branch_id != current_user.branch_id:
        abort(404)
    return payment


def _payment_attachment_or_404(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if (
        not attachment
        or attachment.module != CUSTOMER_PAYMENT_ATTACHMENT_MODULE
        or attachment.reference_type != CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE
    ):
        abort(404)

    payment = _payment_or_404(attachment.reference_id)
    return attachment, payment


def _supplier_payment_or_404(payment_id):
    supplier_payment = SupplierPayment.query.get_or_404(payment_id)
    if supplier_payment.branch_id != current_user.branch_id:
        abort(404)
    return supplier_payment


def _supplier_payment_attachment_or_404(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if (
        not attachment
        or attachment.module != SUPPLIER_PAYMENT_ATTACHMENT_MODULE
        or attachment.reference_type != SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE
    ):
        abort(404)

    supplier_payment = _supplier_payment_or_404(attachment.reference_id)
    return attachment, supplier_payment


def get_invoice_bill_to(invoice):
    bill_to_type = str(getattr(invoice, "bill_to_type", "") or "").upper()

    if bill_to_type == "CLIENT" and invoice.client_id:
        if getattr(invoice, "client_name_snapshot", None):
            return invoice.client_name_snapshot
        client = Client.query.get(invoice.client_id)
        return client.name if client else f"Client ID {invoice.client_id}"

    if bill_to_type == "MANDOR" and invoice.mandor_id:
        if getattr(invoice, "client_name_snapshot", None):
            return invoice.client_name_snapshot
        mandor = Mandor.query.get(invoice.mandor_id)
        return mandor.name if mandor else f"Mandor ID {invoice.mandor_id}"

    if bill_to_type in {"KELOMPOK", "PERORANGAN", "CLIENT_LAIN"}:
        snapshot_name = getattr(invoice, "client_name_snapshot", None)
        return snapshot_name or "Pihak bebas tanpa nama"

    if getattr(invoice, "client_name_snapshot", None):
        return invoice.client_name_snapshot

    return "-"


def _resolve_manual_billing_source_reference(source_type, source_id, branch_id):
    source_type = str(source_type or "").upper().strip()

    if source_type == "MANUAL_RECEIVABLE":
        from app.models.field_transaction import ManualReceivable

        receivable = ManualReceivable.query.filter_by(
            id=source_id,
            branch_id=branch_id,
        ).first()
        if not receivable:
            return None
        return {
            "label": getattr(receivable, "receivable_number", f"Piutang Manual #{source_id}"),
            "href": url_for("field_transactions.detail", transaction_id=receivable.field_transaction_id) + "#manual-receivable",
            "helper": "Buka piutang manual lapangan",
        }

    if source_type == "WORKER_DEBT":
        from app.models.canteen import WorkerDebt

        debt = WorkerDebt.query.filter_by(
            id=source_id,
            branch_id=branch_id,
        ).first()
        if not debt:
            return None
        worker_name = getattr(getattr(debt, "worker", None), "full_name", None)
        label = f"Hutang Warung #{debt.id}"
        if worker_name:
            label = f"{label} - {worker_name}"
        return {
            "label": label,
            "href": url_for("canteen.debts") + f"#worker-debt-{debt.id}",
            "helper": "Buka daftar hutang warung pekerja",
        }

    return None


@finance_bp.route("/")
@role_required("OWNER", "ADMIN", "FINANCE")
def index():
    from app.models.canteen import WorkerDebt
    from app.models.field_transaction import ManualReceivable
    from app.models.finance import CashBankTransaction, ManualBillingBatch
    from app.services.canteen_service import get_debt_remaining_amount
    from app.services.manual_billing_service import (
        MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
        MANUAL_BILLING_SOURCE_WORKER_DEBT,
        find_manual_billing_invoice_for_source,
    )

    active_invoices = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.status.notin_(["CANCELLED", "CANCELED"]),
    ).all()
    open_manual_receivables = ManualReceivable.query.filter(
        ManualReceivable.branch_id == current_user.branch_id,
        ManualReceivable.remaining_amount > 0,
    ).all()
    open_worker_debts = [
        debt for debt in WorkerDebt.query.filter_by(branch_id=current_user.branch_id).all()
        if float(get_debt_remaining_amount(debt) or 0) > 0
    ]
    manual_batches = ManualBillingBatch.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(ManualBillingBatch.id.desc()).limit(8).all()
    recent_ledger = CashBankTransaction.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(CashBankTransaction.transaction_date.desc(), CashBankTransaction.id.desc()).limit(8).all()
    unbilled_manual_receivables = [
        row for row in open_manual_receivables
        if not find_manual_billing_invoice_for_source(MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE, row.id)
    ]
    unbilled_worker_debts = [
        row for row in open_worker_debts
        if not find_manual_billing_invoice_for_source(MANUAL_BILLING_SOURCE_WORKER_DEBT, row.id)
    ]
    billed_manual_sources = (
        len(open_manual_receivables) - len(unbilled_manual_receivables)
        + len(open_worker_debts) - len(unbilled_worker_debts)
    )
    pending_manual_sources = []

    for row in unbilled_manual_receivables[:5]:
        pending_manual_sources.append({
            "kind": "PIUTANG_MANUAL",
            "label": getattr(row, "receivable_number", f"Piutang Manual #{row.id}"),
            "party": getattr(row, "party_name", None) or "-",
            "date": getattr(row, "receivable_date", None),
            "amount": float(getattr(row, "remaining_amount", 0) or 0),
            "href": url_for("field_transactions.detail", transaction_id=row.field_transaction_id) + "#manual-receivable",
            "action_label": "Buka Sumber",
        })

    for row in unbilled_worker_debts[:5]:
        worker = getattr(row, "worker", None)
        pending_manual_sources.append({
            "kind": "HUTANG_WARUNG",
            "label": f"Hutang Warung #{row.id}",
            "party": getattr(worker, "full_name", None) or "-",
            "date": getattr(getattr(row, "sale", None), "sale_date", None),
            "amount": float(get_debt_remaining_amount(row) or 0),
            "href": url_for("canteen.debts") + f"#worker-debt-{row.id}",
            "action_label": "Buka Sumber",
        })

    pending_manual_sources = sorted(
        pending_manual_sources,
        key=lambda item: (item["date"] or "", item["kind"], item["label"]),
        reverse=True,
    )[:8]

    return render_template(
        "finance/hub.html",
        summary={
            "invoice_count": len(active_invoices),
            "invoice_remaining": sum(float(invoice.remaining_amount or 0) for invoice in active_invoices),
            "manual_receivable_count": len(open_manual_receivables),
            "manual_receivable_remaining": sum(float(row.remaining_amount or 0) for row in open_manual_receivables),
            "manual_source_unbilled_count": len(unbilled_manual_receivables) + len(unbilled_worker_debts),
            "manual_source_unbilled_total": (
                sum(float(row.remaining_amount or 0) for row in unbilled_manual_receivables)
                + sum(float(get_debt_remaining_amount(row) or 0) for row in unbilled_worker_debts)
            ),
            "manual_source_billed_count": billed_manual_sources,
            "manual_batch_count": ManualBillingBatch.query.filter_by(branch_id=current_user.branch_id).count(),
        },
        manual_batches=manual_batches,
        pending_manual_sources=pending_manual_sources,
        recent_ledger=recent_ledger,
    )


@finance_bp.route("/invoices")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoices():
    from flask_login import current_user
    from flask import render_template
    from app.models.finance import Invoice

    invoices = Invoice.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        Invoice.id.desc()
    ).all()

    invoices_data = []
    for invoice in invoices:
        invoices_data.append({
            "invoice": invoice,
            "bill_to": get_invoice_bill_to(invoice),
            "input_source": build_input_source_context(getattr(invoice, "input_source", None)),
        })

    # HYGIENE5C_ACTIVE_INVOICE_SUMMARY
    cancelled_statuses = ["CANCELLED", "CANCELED"]
    active_invoices = [
        invoice for invoice in invoices
        if str(invoice.status or "").upper() not in cancelled_statuses
    ]

    total_invoice = sum(float(invoice.total_amount or 0) for invoice in active_invoices)
    total_paid = sum(float(invoice.paid_amount or 0) for invoice in active_invoices)
    total_remaining = sum(float(invoice.remaining_amount or 0) for invoice in active_invoices)

    draft_count = len([invoice for invoice in active_invoices if invoice.status == "DRAFT"])
    paid_count = len([invoice for invoice in active_invoices if invoice.status == "PAID" or float(invoice.remaining_amount or 0) <= 0])
    unpaid_count = len([invoice for invoice in active_invoices if float(invoice.remaining_amount or 0) > 0])

    return render_template(
        "finance/invoice_index.html",
        invoices=invoices_data,
        total_invoice=total_invoice,
        total_paid=total_paid,
        total_remaining=total_remaining,
        draft_count=draft_count,
        paid_count=paid_count,
        unpaid_count=unpaid_count,
        # HYGIENE7A_CANCELLED_COUNT_SUMMARY
        active_invoice_count=len(active_invoices),
        cancelled_count=len(invoices) - len(active_invoices),
    )





# === PRODUCTION_FINANCE_CSV_EXPORT_ROUTES ===
@finance_bp.route("/invoices/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_invoices_csv():
    from app.services.finance_export_service import build_invoice_export_response
    return build_invoice_export_response(current_user.branch_id)


@finance_bp.route("/payment-history/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_payment_history_csv():
    from app.services.finance_export_service import build_payment_history_export_response
    return build_payment_history_export_response(current_user.branch_id)


@finance_bp.route("/cash-bank-ledger/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_cash_bank_ledger_csv():
    from app.services.finance_export_service import build_cash_bank_ledger_export_response
    return build_cash_bank_ledger_export_response(current_user.branch_id, request.args.to_dict(flat=True))


# === PRODUCTION_FINANCE_ADVANCED_CSV_EXPORT_ROUTES ===
@finance_bp.route("/receivables/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_receivables_csv():
    from app.services.finance_export_service import build_receivables_export_response
    branch_id = current_user.branch_id
    requested_branch_id = (request.args.get("branch_id") or "").strip()
    if getattr(current_user, "role", "") == "OWNER" and requested_branch_id.isdigit():
        branch_id = int(requested_branch_id)
    return build_receivables_export_response(branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/supplier-bills/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_supplier_bills_csv():
    from app.services.finance_export_service import build_supplier_bills_export_response
    return build_supplier_bills_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/receivables/statement/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_receivables_statement_csv():
    from app.services.finance_export_service import build_receivables_statement_export_response
    return build_receivables_statement_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/accounts-payable-aging/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_accounts_payable_aging_csv():
    from app.services.finance_export_service import build_ap_aging_export_response
    return build_ap_aging_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/supplier-payable-card/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_supplier_payable_card_csv():
    from app.services.finance_export_service import build_supplier_payable_card_export_response
    return build_supplier_payable_card_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/invoice-profit-report/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_invoice_profit_report_csv():
    from app.services.finance_export_service import build_invoice_profit_export_response
    return build_invoice_profit_export_response(current_user.branch_id, request.args.to_dict(flat=True))


# === PRODUCTION_FINANCE_PRINT_READY_REPORT_ROUTES ===
@finance_bp.route("/cash-bank-ledger/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_cash_bank_ledger():
    from app.services.finance_print_service import build_cash_bank_ledger_print_context
    context = build_cash_bank_ledger_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_cash_bank_ledger.html", **context)


@finance_bp.route("/accounts-payable-aging/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_accounts_payable_aging():
    from app.services.finance_print_service import build_ap_aging_print_context
    context = build_ap_aging_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_accounts_payable_aging.html", **context)


@finance_bp.route("/supplier-payable-card/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_supplier_payable_card():
    from app.services.finance_print_service import build_supplier_payable_card_print_context
    context = build_supplier_payable_card_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_supplier_payable_card.html", **context)


@finance_bp.route("/invoice-profit-report/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_invoice_profit_report():
    from app.services.finance_print_service import build_invoice_profit_print_context
    context = build_invoice_profit_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_invoice_profit_report.html", **context)


@finance_bp.route("/invoices/<int:invoice_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_detail(invoice_id):
    from datetime import date
    from app.models.finance import InvoiceCollectionLog
    from app.models.master import ClientPic

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    payments = Payment.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id
    ).order_by(
        Payment.payment_date.desc(),
        Payment.id.desc()
    ).all()

    collection_logs = InvoiceCollectionLog.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id
    ).order_by(
        InvoiceCollectionLog.follow_up_date.desc(),
        InvoiceCollectionLog.id.desc()
    ).all()

    client_name = "-"
    mandor_name = "-"
    client_pics = []

    if invoice.client_id:
        client = Client.query.get(invoice.client_id)
        client_name = client.name if client else f"Client ID {invoice.client_id}"

        client_pics = ClientPic.query.filter_by(
            client_id=invoice.client_id,
            is_active=True
        ).order_by(
            ClientPic.id.asc()
        ).all()

    if invoice.mandor_id:
        mandor = Mandor.query.get(invoice.mandor_id)
        mandor_name = mandor.name if mandor else f"Mandor ID {invoice.mandor_id}"

    official_identity = get_invoice_official_identity(invoice)
    whatsapp = build_invoice_whatsapp_context(invoice)
    manual_billing_batch = None
    manual_billing_source_refs = {}
    if getattr(invoice, "source_type", None) == "MANUAL_BILLING_RECAP":
        from app.services.manual_billing_service import get_manual_billing_batch_for_invoice
        manual_billing_batch = get_manual_billing_batch_for_invoice(invoice)
        for item in invoice.items:
            ref = _resolve_manual_billing_source_reference(
                getattr(item, "source_type", None),
                getattr(item, "source_id", None),
                current_user.branch_id,
            )
            if ref:
                manual_billing_source_refs[item.id] = ref
    from app.services.accounting_posting_status_service import build_single_source_posting_status
    posting_status = build_single_source_posting_status("INVOICE", invoice)

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc()
    ).all()

    payment_attachments = {
        payment.id: list_reference_attachments(
            module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=payment.id,
            branch_id=current_user.branch_id,
        )
        for payment in payments
    }

    from app.services.billing_trace_service import build_invoice_billing_trace_context
    billing_trace = build_invoice_billing_trace_context(invoice)

    return render_template(
        "finance/invoice_detail.html",
        invoice=invoice,
        payments=payments,
        collection_logs=collection_logs,
        client_pics=client_pics,
        active_bank_accounts=active_bank_accounts,
        today_date=date.today().isoformat(),
        bill_to=get_invoice_bill_to(invoice),
        official_identity=official_identity,
        client_name=client_name,
        mandor_name=mandor_name,
        whatsapp=whatsapp,
        manual_billing_batch=manual_billing_batch,
        manual_billing_source_refs=manual_billing_source_refs,
        posting_status=posting_status,
        payment_attachments=payment_attachments,
        billing_trace=billing_trace,
        input_source_context=build_input_source_context(getattr(invoice, "input_source", None)),
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


# === PATCH_GENERATE_CATERING_INVOICE ===
def _finance_safe_label(obj):
    if not obj:
        return "-"

    for attr in ["name", "location_name", "full_name", "location_code", "code"]:
        value = getattr(obj, attr, None)
        if value:
            return str(value)

    return f"ID {getattr(obj, 'id', '-')}"


def _get_client_for_mandor_invoice(mandor):
    """Return (client, error_message) for official client invoice flow.

    Mandor is kept as field PIC, but the invoice bill-to must be the client/company.
    """
    if not mandor:
        return None, "Data mandor/PIC lapangan tidak ditemukan."

    client_id = getattr(mandor, "client_id", None)

    if not client_id:
        return None, "Mandor/PIC lapangan belum terhubung ke client/perusahaan."

    client = getattr(mandor, "client", None)

    if not client:
        client = Client.query.get(client_id)

    if not client:
        return None, "Client/perusahaan untuk mandor/PIC lapangan ini tidak ditemukan."

    if hasattr(client, "is_active") and not client.is_active:
        return None, "Client/perusahaan untuk mandor/PIC lapangan ini sedang nonaktif."

    return client, None


def _is_after_lock_increase_revision(revision):
    revision_type = str(getattr(revision, "revision_type", "") or "").upper()
    direction = str(getattr(revision, "revision_direction", "") or "").upper()

    return direction == "INCREASE" and revision_type.startswith("AFTER_LOCK")




def _calculate_realtime_locked_base_quantities(detail, revision_predicate):
    """Return locked-base quantities for realtime catering invoice lines.

    After-lock increases are stored both by mutating DailyOrderDetail totals and
    by creating OrderRevision rows.  Invoice generation must bill the locked
    base and after-lock revisions as separate lines, so the base line subtracts
    all after-lock increase revisions from the current detail quantity.
    """
    lunch_qty = int(getattr(detail, "lunch_qty", 0) or 0)
    dinner_qty = int(getattr(detail, "dinner_qty", 0) or 0)

    for revision in getattr(detail, "revisions", []) or []:
        if not revision_predicate(revision):
            continue

        lunch_qty -= int(getattr(revision, "lunch_qty_change", 0) or 0)
        dinner_qty -= int(getattr(revision, "dinner_qty_change", 0) or 0)

    return max(lunch_qty, 0), max(dinner_qty, 0)

def _build_catering_invoice_lines(order, mandor_id):
    lines = []

    for detail in order.details:
        if int(detail.mandor_id) != int(mandor_id):
            continue

        mandor_name = _finance_safe_label(getattr(detail, "mandor", None))
        location_name = _finance_safe_label(getattr(detail, "delivery_location", None))

        lunch_qty, dinner_qty = _calculate_realtime_locked_base_quantities(
            detail,
            _is_after_lock_increase_revision,
        )
        total_qty = lunch_qty + dinner_qty
        price = float(getattr(detail, "price_per_portion", 0) or 0)

        if total_qty > 0 and price >= 0:
            lines.append({
                "item_type": "CATERING",
                "description": (
                    f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                    f"Porsi locked: Lunch {lunch_qty}, Dinner {dinner_qty}"
                ),
                "qty": total_qty,
                "unit_price": price,
                "subtotal": total_qty * price,
                "source_type": "DAILY_ORDER_DETAIL",
                "source_id": detail.id
            })

        for revision in getattr(detail, "revisions", []) or []:
            if not _is_after_lock_increase_revision(revision):
                continue

            lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
            dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
            qty_change = lunch_change + dinner_change

            if qty_change <= 0:
                continue

            revision_price = getattr(revision, "price_per_portion", None)

            if revision_price is None:
                revision_price = price

            revision_price = float(revision_price or 0)

            lines.append({
                "item_type": "REVISION_INCREASE",
                "description": (
                    f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                    f"Revisi tambah setelah lock: Lunch +{lunch_change}, Dinner +{dinner_change}"
                ),
                "qty": qty_change,
                "unit_price": revision_price,
                "subtotal": qty_change * revision_price,
                "source_type": "ORDER_REVISION",
                "source_id": revision.id
            })

    return lines


def _generate_invoice_number(invoice_date):
    from app.models.finance import Invoice

    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1

    while True:
        invoice_number = f"{prefix}-{counter:03d}"
        existing = Invoice.query.filter_by(invoice_number=invoice_number).first()

        if not existing:
            return invoice_number

        counter += 1


@finance_bp.route("/invoices/generate-order")
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_order_invoices():
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice

    locked_orders = DailyOrder.query.filter_by(
        branch_id=current_user.branch_id,
        status="LOCKED"
    ).order_by(
        DailyOrder.order_date.desc(),
        DailyOrder.id.desc()
    ).all()

    groups = []

    for order in locked_orders:
        mandor_ids = []

        for detail in order.details:
            if detail.mandor_id not in mandor_ids:
                mandor_ids.append(detail.mandor_id)

        for mandor_id in mandor_ids:
            lines = _build_catering_invoice_lines(order, mandor_id)
            total_amount = sum(line["subtotal"] for line in lines)

            if total_amount <= 0:
                continue

            existing_invoice = Invoice.query.filter_by(
                branch_id=current_user.branch_id,
                source_type="DAILY_ORDER",
                source_order_id=order.id,
                mandor_id=mandor_id
            ).first()

            mandor_obj = None
            mandor_name = "-"
            client_name = "-"
            client_ready = False
            client_error = "Mandor/PIC lapangan belum terhubung ke client/perusahaan."

            for detail in order.details:
                if detail.mandor_id == mandor_id:
                    mandor_obj = getattr(detail, "mandor", None)
                    mandor_name = _finance_safe_label(mandor_obj)
                    break

            client, client_error_result = _get_client_for_mandor_invoice(mandor_obj)
            client_pics = []
            client_code = ""

            if client:
                client_name = _finance_safe_label(client)
                client_code = getattr(client, "client_code", "") or ""
                client_pics = get_active_client_pics(client.id)
                client_ready = bool(client_pics)
                client_error = None if client_ready else "Client belum punya PIC resmi aktif."
            elif client_error_result:
                client_error = client_error_result

            groups.append({
                "order": order,
                "mandor_id": mandor_id,
                "mandor_name": mandor_name,
                "client_name": client_name,
                "client_code": client_code,
                "client_pics": client_pics,
                "client_ready": client_ready,
                "client_error": client_error,
                "line_count": len(lines),
                "total_amount": total_amount,
                "existing_invoice": existing_invoice
            })

    return render_template(
        "finance/invoice_generate_order.html",
        groups=groups
    )


@finance_bp.route("/invoices/generate-order/<int:order_id>/<int:mandor_id>", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_order_invoice(order_id, mandor_id):
    from datetime import date, timedelta
    from app.extensions import db
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice, InvoiceItem

    order = DailyOrder.query.get_or_404(order_id)

    if order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    if order.status != "LOCKED":
        flash("Invoice hanya bisa dibuat dari order yang sudah LOCKED.", "warning")
        return redirect(url_for("finance.generate_order_invoices"))

    mandor = Mandor.query.get(mandor_id)

    if not mandor or int(getattr(mandor, "branch_id", 0) or 0) != int(current_user.branch_id):
        flash("Mandor/PIC lapangan tidak valid untuk cabang user.", "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    client, client_error = _get_client_for_mandor_invoice(mandor)

    if client_error:
        flash(client_error, "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    client_pic_id = request.form.get("client_pic_id", type=int)
    client_pic, client_pic_error = get_required_client_pic(client.id, client_pic_id)
    if client_pic_error:
        flash(client_pic_error, "warning")
        return redirect(url_for("finance.generate_order_invoices"))

    existing_invoice = Invoice.query.filter_by(
        branch_id=current_user.branch_id,
        source_type="DAILY_ORDER",
        source_order_id=order.id,
        mandor_id=mandor_id
    ).first()

    if existing_invoice:
        flash("Invoice untuk order dan mandor ini sudah pernah dibuat.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=existing_invoice.id))

    lines = _build_catering_invoice_lines(order, mandor_id)
    total_amount = sum(line["subtotal"] for line in lines)

    if not lines or total_amount <= 0:
        flash("Tidak ada item invoice yang valid untuk order dan mandor ini.", "warning")
        return redirect(url_for("finance.generate_order_invoices"))

    invoice_date = date.today()
    due_date = invoice_date + timedelta(days=7)

    invoice = Invoice(
        branch_id=current_user.branch_id,
        invoice_number=_generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=due_date,
        period_start=order.order_date,
        period_end=order.order_date,
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor_id,
        client_pic_id=client_pic.id,
        **build_company_bank_snapshot(current_user.branch_id),
        client_name_snapshot=client.name,
        client_code_snapshot=getattr(client, "client_code", None),
        client_pic_name_snapshot=client_pic.name,
        client_pic_position_snapshot=getattr(client_pic, "position", None),
        client_pic_phone_snapshot=getattr(client_pic, "phone", None),
        client_pic_email_snapshot=getattr(client_pic, "email", None),
        expected_payment_percent=100,
        total_amount=total_amount,
        paid_amount=0,
        remaining_amount=total_amount,
        status="DRAFT",
        notes=(
            f"Invoice catering resmi ke client {client.name}. "
            f"PIC lapangan: {mandor.name}. "
            f"Sumber order locked {order.order_number} + revisi AFTER_LOCK INCREASE. "
            f"Belum termasuk warung."
        ),
        source_type="DAILY_ORDER",
        source_order_id=order.id,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=current_user.id
    )

    try:
        with atomic_business_action(
            module="FINANCE",
            action="ORDER_INVOICE_CREATE",
            description=f"Create invoice order locked {order.order_number} secara atomic.",
            reference_type="invoices",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"source_order_id": order.id, "source_type": "DAILY_ORDER", "input_source": INPUT_SOURCE_REALTIME, "item_count": len(lines)},
        ):
            db.session.add(invoice)
            db.session.flush()

            for line in lines:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    item_type=line["item_type"],
                    description=line["description"],
                    qty=line["qty"],
                    unit_price=line["unit_price"],
                    subtotal=line["subtotal"],
                    source_type=line.get("source_type"),
                    source_id=line.get("source_id"),
                    input_source=INPUT_SOURCE_REALTIME,
                )

                db.session.add(item)

            # PRODUCTION: invoice order harian harus posting ke 4002 Pendapatan Catering Harian.
            db.session.flush()

            from app.services.accounting_service import create_invoice_journal_for_invoice
            create_invoice_journal_for_invoice(
                invoice=invoice,
                created_by=current_user.id,
                commit=False
            )

        record_audit_log(
            module="FINANCE",
            event_type="INVOICE_CREATED",
            action="CREATE",
            table_name="invoices",
            record_id=invoice.id,
            description=f"Invoice dibuat dari order locked: {invoice.invoice_number}.",
            metadata={"invoice_number": invoice.invoice_number, "source_type": invoice.source_type, "input_source": invoice.input_source, "total_amount": invoice.total_amount},
        )
        flash("Invoice catering harian resmi berhasil dibuat dan jurnal otomatis dicatat ke 4002.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal membuat invoice: {error}", "danger")
        return redirect(url_for("finance.generate_order_invoices"))



# === PATCH_PERIOD_INVOICE_PREVIEW ===
def _period_parse_date(value):
    from datetime import datetime

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _period_safe_label(obj):
    if not obj:
        return "-"

    for attr in ["name", "full_name", "mandor_name", "worker_name", "location_name", "item_name"]:
        value = getattr(obj, attr, None)
        if value:
            return str(value)

    return f"ID {getattr(obj, 'id', '-')}"


def _period_is_after_lock_increase(revision):
    revision_type = str(getattr(revision, "revision_type", "") or "").upper()
    direction = str(getattr(revision, "revision_direction", "") or "").upper()

    return direction == "INCREASE" and revision_type.startswith("AFTER_LOCK")


def _period_invoice_item_exists(source_type, source_id):
    from app.models.finance import InvoiceItem

    if not source_type or not source_id:
        return False

    return InvoiceItem.query.filter_by(
        source_type=source_type,
        source_id=source_id
    ).first() is not None


# PRODUCTION_INVOICE_PROFIT_REPORT_READONLY
@finance_bp.route("/invoice-profit-report")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_profit_report():
    from app.models.finance import Invoice
    from app.services.invoice_profit_service import build_invoice_profit_report_index

    start_value = request.args.get("start_date", "").strip()
    end_value = request.args.get("end_date", "").strip()

    start_date = _period_parse_date(start_value) if start_value else None
    end_date = _period_parse_date(end_value) if end_value else None

    if start_value and not start_date:
        flash("Tanggal awal filter profit invoice tidak valid.", "warning")
        start_value = ""

    if end_value and not end_date:
        flash("Tanggal akhir filter profit invoice tidak valid.", "warning")
        end_value = ""

    if start_date and end_date and start_date > end_date:
        flash("Tanggal awal tidak boleh lebih besar dari tanggal akhir.", "warning")
        start_date = None
        end_date = None
        start_value = ""
        end_value = ""

    report_index = build_invoice_profit_report_index(
        branch_id=current_user.branch_id,
        start_date=start_date,
        end_date=end_date,
    )

    rows = []

    for row in report_index["rows"]:
        invoice = row["invoice"]
        rows.append({
            "invoice": invoice,
            "summary": row["summary"],
            "bill_to": get_invoice_bill_to(invoice),
        })

    return render_template(
        "finance/invoice_profit_report.html",
        rows=rows,
        totals=report_index["totals"],
        start_value=start_value,
        end_value=end_value,
    )


@finance_bp.route("/invoices/<int:invoice_id>/profit-report")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_profit_detail(invoice_id):
    from app.services.invoice_profit_service import build_invoice_profit_report

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    report = build_invoice_profit_report(invoice)

    return render_template(
        "finance/invoice_profit_detail.html",
        invoice=invoice,
        report=report,
        bill_to=get_invoice_bill_to(invoice),
    )


@finance_bp.route("/invoices/generate-period", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_period_invoice_preview():
    from datetime import date
    from flask import request
    from app.models.master import Client, Mandor
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice
    from app.models.canteen import WorkerDebt
    from app.services.canteen_service import get_debt_paid_amount, get_debt_remaining_amount

    mandor_query = Mandor.query

    if hasattr(Mandor, "branch_id"):
        mandor_query = mandor_query.filter_by(branch_id=current_user.branch_id)

    if hasattr(Mandor, "is_active"):
        mandor_query = mandor_query.filter_by(is_active=True)

    mandors = mandor_query.order_by(Mandor.id.asc()).all()

    today_value = date.today().strftime("%Y-%m-%d")

    selected_mandor_id = ""
    period_start_value = today_value
    period_end_value = today_value

    lines = []
    total_catering = 0
    total_revision = 0
    total_warung = 0
    grand_total = 0
    selected_mandor = None
    selected_client = None
    selected_client_error = None
    selected_client_pics = []
    preview_ready = False

    if request.method == "POST":
        selected_mandor_id = request.form.get("mandor_id", "").strip()
        period_start_value = request.form.get("period_start", "").strip()
        period_end_value = request.form.get("period_end", "").strip()

        period_start = _period_parse_date(period_start_value)
        period_end = _period_parse_date(period_end_value)

        if not selected_mandor_id:
            flash("Pilih mandor terlebih dahulu.", "warning")
        elif not period_start or not period_end:
            flash("Tanggal mulai dan tanggal selesai wajib diisi dengan benar.", "warning")
        elif period_start > period_end:
            flash("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.", "warning")
        else:
            selected_mandor_id_int = int(selected_mandor_id)
            selected_mandor = Mandor.query.get(selected_mandor_id_int)
            selected_client, selected_client_error = _get_client_for_mandor_invoice(selected_mandor)

            if selected_client_error:
                flash(selected_client_error, "danger")
            else:
                selected_client_pics = get_active_client_pics(selected_client.id) if selected_client else []
                if not selected_client_pics:
                    flash("Client belum punya PIC resmi aktif. Lihat data tetap tampil, tapi invoice belum bisa disimpan.", "warning")
                preview_ready = True

            orders = DailyOrder.query.filter(
                DailyOrder.branch_id == current_user.branch_id,
                DailyOrder.status == "LOCKED",
                DailyOrder.order_date >= period_start,
                DailyOrder.order_date <= period_end
            ).order_by(
                DailyOrder.order_date.asc(),
                DailyOrder.id.asc()
            ).all()

            for order in orders:
                old_order_invoice = Invoice.query.filter_by(
                    branch_id=current_user.branch_id,
                    source_type="DAILY_ORDER",
                    source_order_id=order.id,
                    mandor_id=selected_mandor_id_int
                ).first()

                for detail in order.details:
                    if int(detail.mandor_id) != selected_mandor_id_int:
                        continue

                    mandor_name = _period_safe_label(getattr(detail, "mandor", None))
                    location_name = _period_safe_label(getattr(detail, "delivery_location", None))

                    lunch_qty, dinner_qty = _calculate_realtime_locked_base_quantities(
                        detail,
                        _period_is_after_lock_increase,
                    )
                    total_qty = lunch_qty + dinner_qty
                    price = float(getattr(detail, "price_per_portion", 0) or 0)
                    subtotal = total_qty * price

                    blocked_reason = None

                    if old_order_invoice:
                        blocked_reason = f"Sudah ada invoice order {old_order_invoice.invoice_number}"
                    elif _period_invoice_item_exists("ORDER_DETAIL", detail.id):
                        blocked_reason = "Sudah pernah masuk invoice periode"

                    included = blocked_reason is None

                    if total_qty > 0 and subtotal >= 0:
                        lines.append({
                            "date": order.order_date,
                            "item_type": "CATERING",
                            "description": (
                                f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                                f"Locked: Lunch {lunch_qty}, Dinner {dinner_qty}"
                            ),
                            "qty": total_qty,
                            "unit_price": price,
                            "subtotal": subtotal,
                            "included": included,
                            "blocked_reason": blocked_reason,
                            "source_type": "ORDER_DETAIL",
                            "source_id": detail.id,
                        })

                        if included:
                            total_catering += subtotal
                            grand_total += subtotal

                    for revision in getattr(detail, "revisions", []) or []:
                        if not _period_is_after_lock_increase(revision):
                            continue

                        lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
                        dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
                        qty_change = lunch_change + dinner_change

                        if qty_change <= 0:
                            continue

                        revision_price = getattr(revision, "price_per_portion", None)

                        if revision_price is None:
                            revision_price = price

                        revision_price = float(revision_price or 0)
                        revision_subtotal = qty_change * revision_price

                        blocked_reason = None

                        if old_order_invoice:
                            blocked_reason = f"Sudah ada invoice order {old_order_invoice.invoice_number}"
                        elif _period_invoice_item_exists("ORDER_REVISION", revision.id):
                            blocked_reason = "Sudah pernah masuk invoice periode"

                        included = blocked_reason is None

                        lines.append({
                            "date": order.order_date,
                            "item_type": "REVISION_INCREASE",
                            "description": (
                                f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                                f"Revisi tambah: Lunch +{lunch_change}, Dinner +{dinner_change}"
                            ),
                            "qty": qty_change,
                            "unit_price": revision_price,
                            "subtotal": revision_subtotal,
                            "included": included,
                            "blocked_reason": blocked_reason,
                            "source_type": "ORDER_REVISION",
                            "source_id": revision.id,
                        })

                        if included:
                            total_revision += revision_subtotal
                            grand_total += revision_subtotal

            debts = WorkerDebt.query.filter_by(
                branch_id=current_user.branch_id
            ).order_by(
                WorkerDebt.id.asc()
            ).all()

            for debt in debts:
                worker = getattr(debt, "worker", None)
                sale = getattr(debt, "sale", None)

                if not worker or not sale:
                    continue

                if int(getattr(worker, "mandor_id", 0) or 0) != selected_mandor_id_int:
                    continue

                sale_date = getattr(sale, "sale_date", None)

                if hasattr(sale_date, "date"):
                    sale_date = sale_date.date()

                if not sale_date:
                    continue

                if sale_date < period_start or sale_date > period_end:
                    continue

                remaining = float(get_debt_remaining_amount(debt) or 0)

                if remaining <= 0:
                    continue

                paid = float(get_debt_paid_amount(debt) or 0)

                blocked_reason = None

                if _period_invoice_item_exists("WORKER_DEBT", debt.id):
                    blocked_reason = "Sudah pernah masuk invoice periode"

                included = blocked_reason is None

                lines.append({
                    "date": sale_date,
                    "item_type": "WARUNG_DEBT",
                    "description": (
                        f"Hutang warung pekerja {_period_safe_label(worker)} | "
                        f"Hutang {float(debt.debt_amount or 0):,.0f} | Dibayar {paid:,.0f} | Sisa {remaining:,.0f}"
                    ),
                    "qty": 1,
                    "unit_price": remaining,
                    "subtotal": remaining,
                    "included": included,
                    "blocked_reason": blocked_reason,
                    "source_type": "WORKER_DEBT",
                    "source_id": debt.id,
                })

                if included:
                    total_warung += remaining
                    grand_total += remaining

            lines = sorted(lines, key=lambda row: (row["date"], row["item_type"], row["source_id"]))

    return render_template(
        "finance/invoice_generate_period_preview.html",
        mandors=mandors,
        selected_mandor_id=selected_mandor_id,
        selected_mandor=selected_mandor,
        selected_client=selected_client,
        selected_client_error=selected_client_error,
        selected_client_pics=selected_client_pics,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        lines=lines,
        total_catering=total_catering,
        total_revision=total_revision,
        total_warung=total_warung,
        grand_total=grand_total,
        preview_ready=preview_ready
    )



# === PATCH_PERIOD_INVOICE_SAVE ===
def _period_generate_invoice_number(invoice_date):
    from app.models.finance import Invoice

    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1

    while True:
        invoice_number = f"{prefix}-{counter:03d}"
        existing = Invoice.query.filter_by(invoice_number=invoice_number).first()

        if not existing:
            return invoice_number

        counter += 1


def _build_period_invoice_lines_for_save(mandor_id, period_start, period_end, branch_id):
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice
    from app.models.canteen import WorkerDebt
    from app.services.canteen_service import get_debt_paid_amount, get_debt_remaining_amount

    mandor_id = int(mandor_id)
    lines = []

    orders = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.status == "LOCKED",
        DailyOrder.order_date >= period_start,
        DailyOrder.order_date <= period_end
    ).order_by(
        DailyOrder.order_date.asc(),
        DailyOrder.id.asc()
    ).all()

    for order in orders:
        old_order_invoice = Invoice.query.filter_by(
            branch_id=branch_id,
            source_type="DAILY_ORDER",
            source_order_id=order.id,
            mandor_id=mandor_id
        ).first()

        for detail in order.details:
            if int(detail.mandor_id) != mandor_id:
                continue

            mandor_name = _period_safe_label(getattr(detail, "mandor", None))
            location_name = _period_safe_label(getattr(detail, "delivery_location", None))

            lunch_qty, dinner_qty = _calculate_realtime_locked_base_quantities(
                detail,
                _period_is_after_lock_increase,
            )
            total_qty = lunch_qty + dinner_qty
            price = float(getattr(detail, "price_per_portion", 0) or 0)
            subtotal = total_qty * price

            if total_qty > 0 and subtotal >= 0:
                if not old_order_invoice and not _period_invoice_item_exists("ORDER_DETAIL", detail.id):
                    lines.append({
                        "item_type": "CATERING",
                        "description": (
                            f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                            f"Locked: Lunch {lunch_qty}, Dinner {dinner_qty}"
                        ),
                        "qty": total_qty,
                        "unit_price": price,
                        "subtotal": subtotal,
                        "source_type": "ORDER_DETAIL",
                        "source_id": detail.id,
                    })

            for revision in getattr(detail, "revisions", []) or []:
                if not _period_is_after_lock_increase(revision):
                    continue

                lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
                dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
                qty_change = lunch_change + dinner_change

                if qty_change <= 0:
                    continue

                revision_price = getattr(revision, "price_per_portion", None)

                if revision_price is None:
                    revision_price = price

                revision_price = float(revision_price or 0)
                revision_subtotal = qty_change * revision_price

                if not old_order_invoice and not _period_invoice_item_exists("ORDER_REVISION", revision.id):
                    lines.append({
                        "item_type": "REVISION_INCREASE",
                        "description": (
                            f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                            f"Revisi tambah: Lunch +{lunch_change}, Dinner +{dinner_change}"
                        ),
                        "qty": qty_change,
                        "unit_price": revision_price,
                        "subtotal": revision_subtotal,
                        "source_type": "ORDER_REVISION",
                        "source_id": revision.id,
                    })

    debts = WorkerDebt.query.filter_by(
        branch_id=branch_id
    ).order_by(
        WorkerDebt.id.asc()
    ).all()

    for debt in debts:
        worker = getattr(debt, "worker", None)
        sale = getattr(debt, "sale", None)

        if not worker or not sale:
            continue

        if int(getattr(worker, "mandor_id", 0) or 0) != mandor_id:
            continue

        sale_date = getattr(sale, "sale_date", None)

        if hasattr(sale_date, "date"):
            sale_date = sale_date.date()

        if not sale_date:
            continue

        if sale_date < period_start or sale_date > period_end:
            continue

        remaining = float(get_debt_remaining_amount(debt) or 0)

        if remaining <= 0:
            continue

        if _period_invoice_item_exists("WORKER_DEBT", debt.id):
            continue

        paid = float(get_debt_paid_amount(debt) or 0)

        lines.append({
            "item_type": "WARUNG_DEBT",
            "description": (
                f"Hutang warung pekerja {_period_safe_label(worker)} | "
                f"Hutang {float(debt.debt_amount or 0):,.0f} | Dibayar {paid:,.0f} | Sisa {remaining:,.0f}"
            ),
            "qty": 1,
            "unit_price": remaining,
            "subtotal": remaining,
            "source_type": "WORKER_DEBT",
            "source_id": debt.id,
        })

    return lines


@finance_bp.route("/invoices/generate-period/save", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_period_invoice_save():
    from datetime import date, timedelta
    from app.extensions import db
    from app.models.master import Mandor
    from app.models.finance import Invoice, InvoiceItem

    mandor_id = request.form.get("mandor_id", "").strip()
    period_start_value = request.form.get("period_start", "").strip()
    period_end_value = request.form.get("period_end", "").strip()

    period_start = _period_parse_date(period_start_value)
    period_end = _period_parse_date(period_end_value)

    if not mandor_id:
        flash("Mandor wajib dipilih.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    if not period_start or not period_end:
        flash("Periode invoice tidak valid.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    if period_start > period_end:
        flash("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    mandor_id = int(mandor_id)
    mandor = Mandor.query.get(mandor_id)

    if not mandor:
        flash("Data mandor tidak ditemukan.", "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    if int(getattr(mandor, "branch_id", 0) or 0) != int(current_user.branch_id):
        flash("Mandor/PIC lapangan tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    client, client_error = _get_client_for_mandor_invoice(mandor)

    if client_error:
        flash(client_error, "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    client_pic_id = request.form.get("client_pic_id", type=int)
    client_pic, client_pic_error = get_required_client_pic(client.id, client_pic_id)
    if client_pic_error:
        flash(client_pic_error, "warning")
        return redirect(url_for("finance.generate_period_invoice_preview", mandor_id=mandor_id, period_start=period_start, period_end=period_end))

    existing_period_invoice = Invoice.query.filter_by(
        branch_id=current_user.branch_id,
        source_type="PERIOD_INVOICE",
        mandor_id=mandor_id,
        period_start=period_start,
        period_end=period_end
    ).first()

    if existing_period_invoice:
        flash("Invoice periode untuk mandor dan rentang tanggal ini sudah pernah dibuat.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=existing_period_invoice.id))

    lines = _build_period_invoice_lines_for_save(
        mandor_id=mandor_id,
        period_start=period_start,
        period_end=period_end,
        branch_id=current_user.branch_id
    )

    total_amount = sum(float(line["subtotal"] or 0) for line in lines)

    if not lines or total_amount <= 0:
        flash("Tidak ada item valid untuk disimpan menjadi invoice periode.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    invoice_date = date.today()
    due_date = invoice_date + timedelta(days=7)

    invoice = Invoice(
        branch_id=current_user.branch_id,
        invoice_number=_period_generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=due_date,
        period_start=period_start,
        period_end=period_end,
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor_id,
        client_pic_id=client_pic.id,
        **build_company_bank_snapshot(current_user.branch_id),
        client_name_snapshot=client.name,
        client_code_snapshot=getattr(client, "client_code", None),
        client_pic_name_snapshot=client_pic.name,
        client_pic_position_snapshot=getattr(client_pic, "position", None),
        client_pic_phone_snapshot=getattr(client_pic, "phone", None),
        client_pic_email_snapshot=getattr(client_pic, "email", None),
        expected_payment_percent=100,
        total_amount=total_amount,
        paid_amount=0,
        remaining_amount=total_amount,
        status="DRAFT",
        notes=(
            f"Invoice periode resmi ke client {client.name} "
            f"({period_start.strftime('%d-%m-%Y')} s/d {period_end.strftime('%d-%m-%Y')}). "
            f"PIC lapangan: {mandor.name}. "
            f"Isi: catering locked, revisi tambah setelah lock, dan hutang warung belum lunas. "
            f"Sumber bukan dari pengiriman."
        ),
        source_type="PERIOD_INVOICE",
        source_order_id=None,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=current_user.id
    )

    try:
        with atomic_business_action(
            module="FINANCE",
            action="PERIOD_INVOICE_CREATE",
            description=f"Create invoice periode {period_start} s/d {period_end} secara atomic.",
            reference_type="invoices",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"source_type": "PERIOD_INVOICE", "input_source": INPUT_SOURCE_REALTIME, "mandor_id": mandor.id, "item_count": len(lines)},
        ):
            db.session.add(invoice)
            db.session.flush()

            for line in lines:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    item_type=line["item_type"],
                    description=line["description"],
                    qty=line["qty"],
                    unit_price=line["unit_price"],
                    subtotal=line["subtotal"],
                    source_type=line["source_type"],
                    source_id=line["source_id"],
                    input_source=INPUT_SOURCE_REALTIME,
                )

                db.session.add(item)

            # AUTO_JOURNAL_PERIOD_INVOICE_STEP10F4B
            db.session.flush()

            from app.services.accounting_service import create_invoice_journal_for_invoice
            create_invoice_journal_for_invoice(
                invoice=invoice,
                created_by=current_user.id,
                commit=False
            )

        record_audit_log(
            module="FINANCE",
            event_type="INVOICE_CREATED",
            action="CREATE",
            table_name="invoices",
            record_id=invoice.id,
            description=f"Invoice periode dibuat: {invoice.invoice_number}.",
            metadata={"invoice_number": invoice.invoice_number, "source_type": invoice.source_type, "input_source": invoice.input_source, "total_amount": invoice.total_amount},
        )
        flash("Invoice periode resmi ke client berhasil dibuat dan jurnal otomatis dicatat.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal menyimpan invoice periode: {error}", "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))



# === PATCH_INVOICE_PAYMENT_STEP10E1 ===
def _generate_payment_number(payment_date):
    from app.models.finance import Payment

    prefix = f"PAY-{payment_date.strftime('%Y%m%d')}"
    counter = Payment.query.filter(Payment.payment_number.like(f"{prefix}-%")).count() + 1

    while True:
        payment_number = f"{prefix}-{counter:03d}"
        existing = Payment.query.filter_by(payment_number=payment_number).first()

        if not existing:
            return payment_number

        counter += 1


def _parse_payment_amount(value):
    value = str(value or "").strip()

    if not value:
        return 0

    # Form number biasanya masuk tanpa pemisah ribuan.
    # Ini hanya jaga-jaga kalau user mengetik koma desimal.
    value = value.replace(",", ".")

    return float(value)


@finance_bp.route("/invoices/<int:invoice_id>/payments/create", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_invoice_payment(invoice_id):
    from datetime import datetime
    from flask import request
    from app.extensions import db
    from app.models.finance import Invoice, Payment, BankAccount, SupplierBill, SupplierPayment

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    # HYGIENE5C_BLOCK_PAYMENT_CANCELLED
    if str(invoice.status or "").upper() in INVOICE_CANCELLED_STATUSES:
        flash("Invoice yang dibatalkan tidak bisa menerima pembayaran.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    if float(invoice.remaining_amount or 0) <= 0:
        flash("Invoice ini sudah lunas.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    payment_date_raw = request.form.get("payment_date", "").strip()
    payment_method = request.form.get("payment_method", "").strip()
    bank_account_id_raw = request.form.get("bank_account_id", "").strip()
    amount_raw = request.form.get("amount", "").strip()
    reference_number = request.form.get("reference_number", "").strip()
    notes = request.form.get("notes", "").strip()

    try:
        payment_date = datetime.strptime(payment_date_raw, "%Y-%m-%d").date()
    except Exception:
        flash("Tanggal pembayaran tidak valid.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    # RISK_VALIDATION_PAYMENT_DATE_STEP_RISK1B
    try:
        assert_not_future_date(payment_date, datetime.now().date(), label="Tanggal pembayaran")
        assert_date_not_before(payment_date, invoice.invoice_date, label="Tanggal pembayaran", reference_label="tanggal invoice")
        payment_method = validate_choice(payment_method, CUSTOMER_PAYMENT_METHODS, "Metode pembayaran")
    except BusinessRuleError as error:
        flash(str(error), "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    bank_account_id = None

    if payment_method == "TRANSFER":
        if not bank_account_id_raw:
            flash("Pembayaran transfer wajib memilih rekening bank penerima.", "warning")
            return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

        try:
            bank_account_id = int(bank_account_id_raw)
        except (TypeError, ValueError):
            flash("Rekening bank penerima tidak valid.", "warning")
            return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=current_user.branch_id,
            is_active=True
        ).first()

        if not bank_account:
            flash("Rekening bank penerima tidak ditemukan atau tidak aktif.", "warning")
            return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    try:
        amount = _parse_payment_amount(amount_raw)
    except Exception:
        flash("Nominal pembayaran tidak valid.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    if amount <= 0:
        flash("Nominal pembayaran harus lebih dari 0.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    current_remaining = float(invoice.remaining_amount or 0)

    try:
        amount = assert_payment_amount_not_over_remaining(amount, current_remaining, label="Nominal pembayaran")
    except BusinessRuleError as error:
        flash(str(error), "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    payment = Payment(
        payment_number=_generate_payment_number(payment_date),
        branch_id=current_user.branch_id,
        payment_date=payment_date,
        invoice_id=invoice.id,
        bank_account_id=bank_account_id,
        payment_method=payment_method,
        amount=amount,
        reference_number=reference_number or None,
        notes=notes or None,
        received_by=current_user.id
    )

    try:
        proof_file = request.files.get("proof_file")
        proof_uploaded = False

        with atomic_business_action(
            module="FINANCE",
            action="CUSTOMER_PAYMENT_CREATE",
            description=f"Create payment invoice {invoice.invoice_number} + jurnal + ledger + bukti secara atomic.",
            reference_type="payments",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "amount": amount, "method": payment_method},
        ) as atomic:
            db.session.add(payment)

            new_paid = float(invoice.paid_amount or 0) + amount
            new_remaining = float(invoice.total_amount or 0) - new_paid

            if new_remaining <= 0:
                new_remaining = 0

            invoice.status = resolve_invoice_status_after_payment(invoice.total_amount, new_paid)
            invoice.paid_amount = new_paid
            invoice.remaining_amount = new_remaining

            from app.services.manual_backfill_billing_service import sync_manual_backfill_batch_status_from_invoice
            sync_manual_backfill_batch_status_from_invoice(
                invoice,
                updated_by=current_user.id,
                commit=False,
            )

            # AUTO_JOURNAL_PAYMENT_STEP10F4B
            db.session.flush()

            from app.services.accounting_service import create_payment_journal_for_payment
            create_payment_journal_for_payment(
                payment=payment,
                created_by=current_user.id,
                commit=False
            )

            # PRODUCTION_CASH_BANK_LEDGER_CUSTOMER_PAYMENT
            from app.services.cash_bank_service import create_customer_payment_cash_bank_transaction
            create_customer_payment_cash_bank_transaction(
                payment=payment,
                created_by=current_user.id,
                commit=False
            )

            # AUTO_COLLECTION_LOG_PAYMENT_STEP12B2B
            from app.models.finance import InvoiceCollectionLog

            def _collection_money(value):
                try:
                    return f"Rp {float(value or 0):,.0f}".replace(",", ".")
                except Exception:
                    return "Rp 0"

            if invoice.status == "PAID" or float(invoice.remaining_amount or 0) <= 0:
                collection_status = "PAID"
                next_action = "Invoice sudah lunas. Tidak perlu follow up penagihan."
                response_note = (
                    f"Pembayaran {payment.payment_number} sebesar {_collection_money(payment.amount)} "
                    f"diterima melalui {payment.payment_method}. "
                    f"Invoice {invoice.invoice_number} sudah lunas."
                )
            else:
                collection_status = "PARTIAL"
                next_action = "Follow up pelunasan sisa piutang."
                response_note = (
                    f"Pembayaran {payment.payment_number} sebesar {_collection_money(payment.amount)} "
                    f"diterima melalui {payment.payment_method}. "
                    f"Sisa piutang invoice {invoice.invoice_number}: {_collection_money(invoice.remaining_amount)}."
                )

            if payment.reference_number:
                response_note += f" Referensi: {payment.reference_number}."

            if payment.notes:
                response_note += f" Catatan payment: {payment.notes}."

            collection_log = InvoiceCollectionLog(
                branch_id=current_user.branch_id,
                invoice_id=invoice.id,
                follow_up_date=payment.payment_date,
                channel="SYSTEM",
                contact_person="SYSTEM - Pembayaran Masuk",
                response_note=response_note,
                promise_date=None,
                next_action=next_action,
                collection_status=collection_status,
                created_by=current_user.id
            )

            db.session.add(collection_log)
            db.session.flush()

            if proof_file and proof_file.filename:
                attachment = save_digital_attachment(
                    file_storage=proof_file,
                    module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                    reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                    reference_id=payment.id,
                    attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_CUSTOMER",
                    branch_id=current_user.branch_id,
                    uploaded_by=current_user.id,
                    notes=request.form.get("proof_notes") or None,
                    commit=False,
                )
                atomic.track_attachment(attachment)
                proof_uploaded = True
                record_audit_log(
                    module="ATTACHMENT",
                    event_type="DIGITAL_ATTACHMENT_UPLOADED",
                    action="CREATE",
                    table_name="digital_attachments",
                    record_id=attachment.id,
                    description=f"Lampiran payment customer diunggah secara atomic untuk {payment.payment_number}.",
                    metadata={
                        "module": CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                        "reference_type": CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                        "reference_id": payment.id,
                        "attachment_type": attachment.attachment_type,
                        "original_filename": attachment.original_filename,
                        "file_size": attachment.file_size,
                        "sha256": attachment.sha256_hash,
                        "atomic_guard": "PRODUCTION",
                    },
                    commit=False,
                )

        record_audit_log(
            module="FINANCE",
            event_type="CUSTOMER_PAYMENT_CREATED",
            action="CREATE",
            table_name="payments",
            record_id=payment.id,
            description=f"Pembayaran customer dicatat atomic: {payment.payment_number} untuk invoice {invoice.invoice_number}.",
            metadata={"payment_number": payment.payment_number, "invoice_id": invoice.id, "amount": payment.amount, "method": payment.payment_method, "atomic_guard": "PRODUCTION"},
        )

        if proof_uploaded:
            flash("Bukti transfer/payment customer berhasil diunggah dalam transaksi atomic.", "success")

        flash("Pembayaran invoice berhasil disimpan, jurnal otomatis dicatat, dan ledger kas/bank masuk dibuat.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal menyimpan pembayaran invoice: {error}", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))


# === PATCH_PRINT_INVOICE_STEP11A1 ===
# === PATCH_PRINT_OPERASIONAL_STEP12D1 ===
def _invoice_print_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _invoice_print_parse_meals(description):
    import re

    description = description or ""

    def find_qty(*labels):
        for label in labels:
            match = re.search(rf"{label}\s*([+-]?\s*\d+(?:[.,]\d+)?)", description, re.IGNORECASE)
            if match:
                return match.group(1).replace(" ", "")
        return "-"

    return {
        "breakfast": find_qty("Sarapan", "Pagi", "Breakfast"),
        "lunch": find_qty("Lunch", "Siang"),
        "dinner": find_qty("Dinner", "Sore"),
    }


def _invoice_print_parse_lunch_dinner(description):
    meals = _invoice_print_parse_meals(description)
    return meals["lunch"], meals["dinner"]


def _invoice_print_parse_money(value):
    value = str(value or "").strip()

    if not value:
        return 0

    # Deskripsi lama memakai format 10,000 / 1,015 / 8,985.
    # Untuk kebutuhan cetak, koma/titik pada deskripsi dianggap pemisah ribuan.
    cleaned = value.replace(".", "").replace(",", "")

    try:
        return float(cleaned)
    except Exception:
        return 0


def _invoice_print_extract_money(description, label):
    import re

    description = description or ""
    pattern = rf"{label}\s*([0-9.,]+)"
    match = re.search(pattern, description, re.IGNORECASE)

    if not match:
        return 0

    return _invoice_print_parse_money(match.group(1))


def _invoice_print_parse_common_description(description):
    description = description or ""
    parts = [part.strip() for part in description.split("|")]

    return {
        "order_number": parts[0] if len(parts) > 0 and parts[0] else "-",
        "mandor": parts[1] if len(parts) > 1 and parts[1] else "-",
        "location": parts[2] if len(parts) > 2 and parts[2] else "-",
        "note": parts[3] if len(parts) > 3 and parts[3] else description,
    }


def _invoice_print_parse_worker_debt(description):
    import re

    description = description or ""

    worker_name = "-"
    worker_match = re.search(r"pekerja\s+([^|]+)", description, re.IGNORECASE)

    if worker_match:
        worker_name = worker_match.group(1).strip()

    debt_amount = _invoice_print_extract_money(description, "Hutang")
    paid_amount = _invoice_print_extract_money(description, "Dibayar")
    remaining_amount = _invoice_print_extract_money(description, "Sisa")

    return {
        "worker_name": worker_name,
        "debt_amount": debt_amount,
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "note": description,
    }



def _invoice_print_format_date(value):
    if not value:
        return "-"

    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        return str(value)


def _invoice_print_resolve_daily_order_detail(source_id):
    """Resolve invoice item source detail so invoice print does not show blank
    order/mandor/location/lunch/dinner when the item is linked to a daily order.
    """
    if not source_id:
        return {}

    try:
        from app.models.operational import DailyOrderDetail

        detail = DailyOrderDetail.query.get(source_id)
        if not detail:
            return {}

        daily_order = getattr(detail, "daily_order", None)
        mandor = getattr(detail, "mandor", None)
        location = getattr(detail, "delivery_location", None)

        return {
            "order_number": getattr(daily_order, "order_number", None) or f"Detail Order #{detail.id}",
            "order_date": _invoice_print_format_date(getattr(daily_order, "order_date", None)),
            "mandor": getattr(mandor, "name", None) or "-",
            "location": getattr(location, "location_name", None) or "-",
            "breakfast": "-",
            "lunch": str(int(getattr(detail, "lunch_qty", 0) or 0)),
            "dinner": str(int(getattr(detail, "dinner_qty", 0) or 0)),
            "qty": _invoice_print_float(getattr(detail, "total_qty", 0)),
            "unit_price": _invoice_print_float(getattr(detail, "price_per_portion", 0)),
            "source_label": "Order Harian",
            "source_meta": f"Tanggal {_invoice_print_format_date(getattr(daily_order, 'order_date', None))}",
            "note": getattr(detail, "notes", None) or getattr(daily_order, "notes", None) or "Catering harian",
        }
    except Exception:
        return {}

def build_invoice_print_operational_data(invoice):
    data = {
        "catering": [],
        "revision": [],
        "warung": [],
        "other": [],
        "totals": {
            "catering": 0,
            "revision": 0,
            "warung": 0,
            "other": 0,
            "grand": _invoice_print_float(invoice.total_amount),
            "paid": _invoice_print_float(invoice.paid_amount),
            "remaining": _invoice_print_float(invoice.remaining_amount),
        }
    }

    for item in invoice.items:
        item_type = (getattr(item, "item_type", "") or "").upper()
        description = getattr(item, "description", "") or ""
        subtotal = _invoice_print_float(getattr(item, "subtotal", 0))
        qty = _invoice_print_float(getattr(item, "qty", 0))
        unit_price = _invoice_print_float(getattr(item, "unit_price", 0))

        common = _invoice_print_parse_common_description(description)
        meals = _invoice_print_parse_meals(description)
        lunch, dinner = meals["lunch"], meals["dinner"]
        breakfast = meals["breakfast"]
        source_type = (getattr(item, "source_type", None) or "").upper()
        source_id = getattr(item, "source_id", None)
        source_detail = {}

        if source_type == "DAILY_ORDER_DETAIL":
            source_detail = _invoice_print_resolve_daily_order_detail(source_id)

        resolved_qty = qty or _invoice_print_float(source_detail.get("qty"))
        resolved_unit_price = unit_price or _invoice_print_float(source_detail.get("unit_price"))

        base_row = {
            "item": item,
            "description": description,
            "qty": resolved_qty,
            "unit_price": resolved_unit_price,
            "subtotal": subtotal,
            "source_type": source_type or getattr(item, "source_type", None),
            "source_id": source_id,
            "source_label": source_detail.get("source_label") or "",
            "source_meta": source_detail.get("source_meta") or "",
            "order_date": source_detail.get("order_date") or "",
        }

        if item_type == "CATERING":
            row = dict(base_row)
            row.update({
                "order_number": common["order_number"] if common["order_number"] != "-" else source_detail.get("order_number", "-"),
                "mandor": common["mandor"] if common["mandor"] != "-" else source_detail.get("mandor", "-"),
                "location": common["location"] if common["location"] != "-" else source_detail.get("location", "-"),
                "note": common["note"] if common["note"] != description else source_detail.get("note", common["note"]),
                "breakfast": breakfast if breakfast != "-" else source_detail.get("breakfast", "-"),
                "lunch": lunch if lunch != "-" else source_detail.get("lunch", "-"),
                "dinner": dinner if dinner != "-" else source_detail.get("dinner", "-"),
            })

            data["catering"].append(row)
            data["totals"]["catering"] += subtotal

        elif item_type == "REVISION_INCREASE":
            row = dict(base_row)
            row.update({
                "order_number": common["order_number"] if common["order_number"] != "-" else source_detail.get("order_number", "-"),
                "mandor": common["mandor"] if common["mandor"] != "-" else source_detail.get("mandor", "-"),
                "location": common["location"] if common["location"] != "-" else source_detail.get("location", "-"),
                "note": common["note"] if common["note"] != description else source_detail.get("note", common["note"]),
                "breakfast": breakfast if breakfast != "-" else source_detail.get("breakfast", "-"),
                "lunch": lunch if lunch != "-" else source_detail.get("lunch", "-"),
                "dinner": dinner if dinner != "-" else source_detail.get("dinner", "-"),
            })

            data["revision"].append(row)
            data["totals"]["revision"] += subtotal

        elif item_type == "WARUNG_DEBT":
            debt = _invoice_print_parse_worker_debt(description)

            row = dict(base_row)
            row.update(debt)

            if not row["remaining_amount"]:
                row["remaining_amount"] = subtotal

            data["warung"].append(row)
            data["totals"]["warung"] += subtotal

        else:
            row = dict(base_row)
            row.update({
                "item_type": item_type or "-",
            })

            data["other"].append(row)
            data["totals"]["other"] += subtotal

    return data


@finance_bp.route("/invoices/<int:invoice_id>/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_print(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    payments = Payment.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id
    ).order_by(
        Payment.payment_date.desc(),
        Payment.id.desc()
    ).all()

    client_name = "-"
    mandor_name = "-"

    if invoice.client_id:
        client = Client.query.get(invoice.client_id)
        client_name = client.name if client else f"Client ID {invoice.client_id}"

    if invoice.mandor_id:
        mandor = Mandor.query.get(invoice.mandor_id)
        mandor_name = mandor.name if mandor else f"Mandor ID {invoice.mandor_id}"

    company_settings = get_company_settings(current_user.branch_id)
    official_identity = get_invoice_official_identity(invoice)
    whatsapp = build_invoice_whatsapp_context(invoice)
    print_data = build_invoice_print_operational_data(invoice)

    return render_template(
        "finance/invoice_print.html",
        invoice=invoice,
        payments=payments,
        bill_to=get_invoice_bill_to(invoice),
        official_identity=official_identity,
        client_name=client_name,
        mandor_name=mandor_name,
        whatsapp=whatsapp,
        print_data=print_data,
        company_settings=company_settings
    )


# === PATCH_WHATSAPP_INVOICE_STEP11C1 ===
def _normalize_whatsapp_number(phone):
    import re

    phone = str(phone or "").strip()
    phone = re.sub(r"[^0-9]", "", phone)

    if not phone:
        return ""

    if phone.startswith("0"):
        return "62" + phone[1:]

    if phone.startswith("8"):
        return "62" + phone

    return phone


def _format_money_for_whatsapp(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _build_invoice_whatsapp_message(invoice, target_name, mandor_name, company_name=None):
    periode = "-"

    if invoice.period_start and invoice.period_end:
        periode = f"{invoice.period_start.strftime('%d-%m-%Y')} s/d {invoice.period_end.strftime('%d-%m-%Y')}"

    company_name = company_name or "PT Idha Boga Pangan Mandiri"

    return f"""Yth. Bapak/Ibu {target_name},

Berikut kami sampaikan informasi tagihan dari {company_name}.

No Invoice      : {invoice.invoice_number}
Periode         : {periode}
Penanggung Jawab: {mandor_name}
Tanggal Invoice : {invoice.invoice_date.strftime('%d-%m-%Y')}
Jatuh Tempo     : {invoice.due_date.strftime('%d-%m-%Y')}

Total Tagihan   : {_format_money_for_whatsapp(invoice.total_amount)}
Sudah Dibayar   : {_format_money_for_whatsapp(invoice.paid_amount)}
Sisa Tagihan    : {_format_money_for_whatsapp(invoice.remaining_amount)}

Mohon dilakukan pengecekan tagihan. Apabila tagihan sudah sesuai, pembayaran dapat dilakukan sebelum tanggal jatuh tempo.

Cetakan invoice dapat kami kirimkan terpisah apabila diperlukan.

Terima kasih.
{company_name}"""


def build_invoice_whatsapp_context(invoice):
    from urllib.parse import quote

    target_name = "-"
    target_phone = ""
    target_source = "-"
    mandor_name = "-"

    client = None
    mandor = None

    if invoice.client_id:
        client = Client.query.get(invoice.client_id)

    if invoice.mandor_id:
        mandor = Mandor.query.get(invoice.mandor_id)
        if mandor:
            mandor_name = mandor.name or "-"

    # PRIORITAS BARU:
    # Invoice ke CLIENT akan dikirim ke PIC aktif yang punya nomor.
    # Kalau belum ada PIC aktif, fallback ke nomor umum client.
    if invoice.bill_to_type == "CLIENT" and client:
        active_pic = None

        try:
            from app.models.master import ClientPic

            active_pic = ClientPic.query.filter_by(
                client_id=client.id,
                is_active=True
            ).filter(
                ClientPic.phone.isnot(None),
                ClientPic.phone != ""
            ).order_by(
                ClientPic.id.asc()
            ).first()
        except Exception:
            active_pic = None

        if active_pic:
            target_name = active_pic.name or client.name or "-"
            target_phone = active_pic.phone or ""
            target_source = "PIC_CLIENT"
        else:
            target_name = client.name or "-"
            target_phone = client.phone or ""
            target_source = "CLIENT_PHONE_FALLBACK"

    elif invoice.bill_to_type == "MANDOR" and mandor:
        target_name = mandor.name or "-"
        target_phone = mandor.phone or ""
        target_source = "MANDOR"

    wa_number = _normalize_whatsapp_number(target_phone)

    if not wa_number:
        return {
            "url": "",
            "number": "",
            "target_name": target_name,
            "target_phone": target_phone,
            "target_source": target_source,
            "message": ""
        }

    company_settings = get_company_settings(invoice.branch_id)
    message = _build_invoice_whatsapp_message(
        invoice=invoice,
        target_name=target_name,
        mandor_name=mandor_name,
        company_name=company_settings.get("company_name")
    )

    return {
        "url": f"https://wa.me/{wa_number}?text={quote(message)}",
        "number": wa_number,
        "target_name": target_name,
        "target_phone": target_phone,
        "target_source": target_source,
        "message": message
    }



# === PATCH_COLLECTION_HISTORY_STEP12B1B ===
@finance_bp.route("/invoices/<int:invoice_id>/collection/create", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_invoice_collection_log(invoice_id):
    from datetime import datetime, date
    from app.models.finance import InvoiceCollectionLog
    from app.extensions import db

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    # HYGIENE5C_BLOCK_COLLECTION_CANCELLED
    if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]:
        flash("Invoice yang dibatalkan tidak perlu dicatat follow up penagihan.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    def parse_date(value, default=None):
        value = (value or "").strip()
        if not value:
            return default
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return default

    allowed_channels = ["WHATSAPP", "PHONE", "EMAIL", "VISIT", "OTHER"]
    allowed_statuses = [
        "SENT",
        "UNPAID",
        "DUE_SOON",
        "OVERDUE",
        "FOLLOW_UP",
        "PROMISE_TO_PAY",
        "STATEMENT_SENT",
        "OFFICIAL_LETTER",
        "INSTALLMENT",
        "PARTIAL",
        "PAID",
        "OTHER"
    ]

    follow_up_date = parse_date(request.form.get("follow_up_date"), date.today())
    promise_date = parse_date(request.form.get("promise_date"), None)

    # RISK_VALIDATION_FOLLOW_UP_DATE_STEP_RISK1B
    if follow_up_date > date.today():
        flash("Tanggal follow up tidak boleh lebih dari hari ini.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    channel = (request.form.get("channel") or "WHATSAPP").strip().upper()
    if channel not in allowed_channels:
        channel = "OTHER"

    collection_status = (request.form.get("collection_status") or "FOLLOW_UP").strip().upper()
    if collection_status not in allowed_statuses:
        collection_status = "FOLLOW_UP"

    contact_person = (request.form.get("contact_person") or "").strip()
    response_note = (request.form.get("response_note") or "").strip()
    next_action = (request.form.get("next_action") or "").strip()

    if not response_note:
        flash("Catatan respon client wajib diisi agar riwayat follow up jelas.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    log = InvoiceCollectionLog(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id,
        follow_up_date=follow_up_date,
        channel=channel,
        contact_person=contact_person,
        response_note=response_note,
        promise_date=promise_date,
        next_action=next_action,
        collection_status=collection_status,
        created_by=current_user.id
    )

    db.session.add(log)
    db.session.commit()

    record_audit_log(
        module="FINANCE",
        event_type="INVOICE_COLLECTION_LOG_CREATED",
        action="CREATE",
        table_name="invoice_collection_logs",
        record_id=log.id,
        description=f"Follow up invoice dicatat: {invoice.invoice_number} via {channel}.",
        metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "channel": channel, "collection_status": collection_status},
    )

    flash("Riwayat follow up invoice berhasil dicatat.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))



# === PATCH_WA_SEND_COLLECTION_STEP12B2A ===
@finance_bp.route("/invoices/<int:invoice_id>/whatsapp/send")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_whatsapp_send(invoice_id):
    from datetime import date
    from flask import redirect, url_for, flash
    from app.extensions import db
    from app.models.finance import InvoiceCollectionLog

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    # HYGIENE5C_BLOCK_WA_CANCELLED
    if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]:
        flash("Invoice yang dibatalkan tidak bisa dikirim sebagai tagihan WhatsApp.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    wa = build_invoice_whatsapp_context(invoice)

    if not wa.get("url"):
        flash("Nomor WhatsApp tujuan belum tersedia.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    today = date.today()
    target_name = wa.get("target_name") or "-"
    target_source = wa.get("target_source") or "-"
    target_phone = wa.get("target_phone") or "-"

    # Anti dobel:
    # Kalau hari ini sudah ada log SENT untuk invoice + PIC yang sama,
    # sistem tidak membuat log baru lagi.
    existing_log = InvoiceCollectionLog.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id,
        follow_up_date=today,
        channel="WHATSAPP",
        contact_person=target_name,
        collection_status="SENT"
    ).first()

    if not existing_log:
        note = (
            f"Invoice {invoice.invoice_number} dibuka untuk dikirim melalui WhatsApp "
            f"ke {target_name} ({target_phone})."
        )

        if target_source == "PIC_CLIENT":
            note += " Target menggunakan PIC aktif client."
        elif target_source == "CLIENT_PHONE_FALLBACK":
            note += " Target menggunakan nomor umum client karena PIC aktif belum tersedia."
        elif target_source == "MANDOR":
            note += " Target menggunakan nomor mandor."

        log = InvoiceCollectionLog(
            branch_id=current_user.branch_id,
            invoice_id=invoice.id,
            follow_up_date=today,
            channel="WHATSAPP",
            contact_person=target_name,
            response_note=note,
            promise_date=None,
            next_action="Follow up konfirmasi penerimaan invoice.",
            collection_status="SENT",
            created_by=current_user.id
        )

        db.session.add(log)
        db.session.commit()

        record_audit_log(
            module="FINANCE",
            event_type="INVOICE_WHATSAPP_OPENED",
            action="CREATE",
            table_name="invoice_collection_logs",
            record_id=log.id,
            description=f"Invoice dibuka untuk dikirim via WhatsApp: {invoice.invoice_number}.",
            metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "target_name": target_name, "target_source": target_source},
        )

    return redirect(wa.get("url"))



# === PATCH_AR_WARNING_STEP12B3B ===
def _finance_ar_money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _finance_ar_percent(paid, total):
    try:
        total = float(total or 0)
        paid = float(paid or 0)

        if total <= 0:
            return 0

        return round((paid / total) * 100, 2)
    except Exception:
        return 0


def _finance_format_date(value):
    if not value:
        return "-"

    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        return str(value)


def build_invoice_ar_warning(invoice):
    from datetime import date

    try:
        from app.models.finance import InvoiceCollectionLog
    except Exception:
        InvoiceCollectionLog = None

    today = date.today()

    total = float(invoice.total_amount or 0)
    paid = float(invoice.paid_amount or 0)
    remaining = float(invoice.remaining_amount or 0)
    paid_percent = _finance_ar_percent(paid, total)
    expected_percent = float(getattr(invoice, "expected_payment_percent", 100) or 100)

    latest_log = None

    if InvoiceCollectionLog:
        latest_log = InvoiceCollectionLog.query.filter_by(
            invoice_id=invoice.id
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

    base = {
        "stage": "NORMAL",
        "stage_label": "Normal",
        "level": "NORMAL",
        "badge_class": "status-progress",
        "message": "-",
        "action": "-",
        "paid_percent": paid_percent,
        "expected_percent": expected_percent,
        "latest_status": latest_log.collection_status if latest_log else "-",
        "latest_date": _finance_format_date(latest_log.follow_up_date) if latest_log else "-",
        "latest_pic": latest_log.contact_person if latest_log and latest_log.contact_person else "-",
        "latest_note": latest_log.response_note if latest_log and latest_log.response_note else "-"
    }

    # HYGIENE5C_AR_CANCELLED
    if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]:
        base.update({
            "stage": "CANCELLED",
            "stage_label": "Dibatalkan",
            "level": "ARSIP",
            "badge_class": "status-cancelled",
            "message": "Invoice ini dibatalkan dan tidak dihitung sebagai piutang aktif.",
            "action": "Tidak perlu follow up penagihan."
        })
        return base

    if remaining <= 0 or str(invoice.status).upper() == "PAID":
        base.update({
            "stage": "PAID",
            "stage_label": "Lunas",
            "level": "AMAN",
            "badge_class": "status-locked",
            "message": "Invoice sudah lunas.",
            "action": "Tidak perlu follow up penagihan."
        })
        return base

    if latest_log and latest_log.collection_status == "PROMISE_TO_PAY":
        promise = _finance_format_date(latest_log.promise_date)
        base.update({
            "stage": "PROMISE_TO_PAY",
            "stage_label": "Janji Bayar",
            "level": "PANTAU",
            "badge_class": "status-progress",
            "message": f"Client sudah ada janji bayar tanggal {promise}.",
            "action": "Pantau sesuai tanggal janji bayar."
        })
        return base

    if not invoice.due_date:
        base.update({
            "stage": "NO_DUE_DATE",
            "stage_label": "Cek Jatuh Tempo",
            "level": "CEK",
            "badge_class": "status-draft",
            "message": "Invoice belum memiliki tanggal jatuh tempo.",
            "action": "Lengkapi tanggal jatuh tempo invoice."
        })
        return base

    days_to_due = (invoice.due_date - today).days
    days_from_invoice = (today - invoice.invoice_date).days if invoice.invoice_date else 0

    if days_to_due < 0:
        overdue_days = abs(days_to_due)

        if overdue_days <= 7:
            base.update({
                "stage": "OVERDUE_1_7",
                "stage_label": "Overdue",
                "level": "WARNING",
                "badge_class": "status-cancelled",
                "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
                "action": "Follow up overdue ke PIC client."
            })
            return base

        if overdue_days <= 14:
            base.update({
                "stage": "OVERDUE_8_14",
                "stage_label": "Kirim Rekap Piutang",
                "level": "TINGGI",
                "badge_class": "status-cancelled",
                "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
                "action": "Kirim Statement of Account / Rekap Piutang."
            })
            return base

        if overdue_days <= 30:
            base.update({
                "stage": "OVERDUE_15_30",
                "stage_label": "Surat Tagihan",
                "level": "SERIUS",
                "badge_class": "status-cancelled",
                "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
                "action": "Kirim surat tagihan resmi dan minta janji bayar."
            })
            return base

        base.update({
            "stage": "OVERDUE_30_PLUS",
            "stage_label": "Eskalasi Owner",
            "level": "KRITIS",
            "badge_class": "status-cancelled",
            "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
            "action": "Eskalasi ke owner untuk keputusan penagihan."
        })
        return base

    if days_to_due <= 3:
        base.update({
            "stage": "DUE_SOON",
            "stage_label": "Reminder Jatuh Tempo",
            "level": "REMINDER",
            "badge_class": "status-draft",
            "message": f"Jatuh tempo dalam {days_to_due} hari.",
            "action": "Kirim reminder jatuh tempo ke PIC client."
        })
        return base

    if days_from_invoice >= 7 and paid <= 0:
        base.update({
            "stage": "NO_PAYMENT_7_DAYS",
            "stage_label": "Butuh Follow Up",
            "level": "FOLLOW_UP",
            "badge_class": "status-draft",
            "message": "Invoice sudah 7 hari dibuat/dikirim tetapi belum ada pembayaran.",
            "action": "Follow up konfirmasi proses pembayaran."
        })
        return base

    if paid > 0 and paid_percent < expected_percent:
        base.update({
            "stage": "BELOW_EXPECTED_PAYMENT",
            "stage_label": "Pantau Sisa Piutang",
            "level": "PANTAU",
            "badge_class": "status-progress",
            "message": f"Pembayaran baru {paid_percent}% dari total, target minimal {expected_percent}%.",
            "action": "Pantau sisa pembayaran dan follow up jika mendekati jatuh tempo."
        })
        return base

    if paid > 0 and remaining > 0:
        base.update({
            "stage": "PARTIAL",
            "stage_label": "Bayar Sebagian",
            "level": "PANTAU",
            "badge_class": "status-progress",
            "message": "Invoice sudah dibayar sebagian tetapi belum lunas.",
            "action": "Follow up pelunasan sisa tagihan."
        })
        return base

    base.update({
        "stage": "NORMAL_UNPAID",
        "stage_label": "Belum Jatuh Tempo",
        "level": "NORMAL",
        "badge_class": "status-progress",
        "message": f"Belum jatuh tempo. Sisa {days_to_due} hari.",
        "action": "Pantau sampai mendekati jatuh tempo."
    })
    return base


@finance_bp.app_template_global()
def finance_ar_warning(invoice):
    return build_invoice_ar_warning(invoice)





# === PATCH_RECEIVABLES_DASHBOARD_STEP12C1 ===
# === PATCH_RECEIVABLES_FILTER_STEP12C2B ===
# === FINAL_FILTER_COUNT_SYNC_STEP12C2C ===
# === TAHAP_10_10_ENHANCE_EXISTING_RECEIVABLES ===
def _build_receivables_dashboard_context(args):
    from collections import defaultdict
    from datetime import date
    from app.models.finance import Invoice, InvoiceCollectionLog
    from app.models.master import Branch, Client, Mandor
    from app.services.finance_receivables_service import (
        BILL_TO_TYPE_CHOICES,
        INACTIVE_INVOICE_STATUSES,
        invoice_matches_receivable_filters,
        invoice_party_context,
        parse_date_filter,
        normalize_bill_to_type_filter,
        normalize_status_filter,
        receivable_status_choices_from_invoices,
    )

    selected_filter = (args.get("filter") or "ALL").strip().upper()
    selected_client_id = (args.get("client_id") or "").strip()
    selected_bill_to_type = normalize_bill_to_type_filter(args.get("bill_to_type"))
    selected_status = normalize_status_filter(args.get("status"))
    selected_period_from_raw = (args.get("period_from") or "").strip()
    selected_period_to_raw = (args.get("period_to") or "").strip()
    selected_period_from = parse_date_filter(selected_period_from_raw)
    selected_period_to = parse_date_filter(selected_period_to_raw)

    branch_options = []
    if getattr(current_user, "role", "") == "OWNER":
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
        if not branches:
            branches = Branch.query.order_by(Branch.name.asc()).all()
    else:
        branches = Branch.query.filter_by(id=current_user.branch_id).all()

    for branch in branches:
        branch_options.append({"value": str(branch.id), "label": branch.name or f"Cabang {branch.id}"})

    allowed_branch_ids = {int(row["value"]) for row in branch_options if str(row.get("value", "")).isdigit()}
    requested_branch_id = (args.get("branch_id") or "").strip()
    selected_branch_id = current_user.branch_id
    if requested_branch_id.isdigit() and int(requested_branch_id) in allowed_branch_ids:
        selected_branch_id = int(requested_branch_id)
    elif selected_branch_id not in allowed_branch_ids and allowed_branch_ids:
        selected_branch_id = sorted(allowed_branch_ids)[0]

    filter_labels = {
        "ALL": "Semua Piutang",
        "OVERDUE": "Overdue",
        "DUE_SOON": "Due Soon",
        "FOLLOW_UP": "Butuh Follow Up",
        "PARTIAL_MONITOR": "Pantau Sisa Piutang",
    }

    if selected_filter not in filter_labels:
        selected_filter = "ALL"

    def match_filter(stage, filter_key):
        stage = stage or ""

        if filter_key == "ALL":
            return True

        if filter_key == "OVERDUE":
            return stage.startswith("OVERDUE")

        if filter_key == "DUE_SOON":
            return stage == "DUE_SOON"

        if filter_key == "FOLLOW_UP":
            return stage in [
                "NO_PAYMENT_7_DAYS",
                "FOLLOW_UP",
                "PROMISE_TO_PAY",
                "OVERDUE_1_7",
                "OVERDUE_8_14",
                "OVERDUE_15_30",
                "OVERDUE_30_PLUS",
            ]

        if filter_key == "PARTIAL_MONITOR":
            return stage in [
                "BELOW_EXPECTED_PAYMENT",
                "PARTIAL",
            ]

        return True

    priority_map = {
        "OVERDUE_30_PLUS": 1,
        "OVERDUE_15_30": 2,
        "OVERDUE_8_14": 3,
        "OVERDUE_1_7": 4,
        "DUE_SOON": 5,
        "NO_PAYMENT_7_DAYS": 6,
        "PROMISE_TO_PAY": 7,
        "BELOW_EXPECTED_PAYMENT": 8,
        "PARTIAL": 9,
        "NORMAL_UNPAID": 10,
        "NORMAL": 11,
        "PAID": 99,
    }

    invoices = Invoice.query.filter(
        Invoice.branch_id == selected_branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(list(INACTIVE_INVOICE_STATUSES)),
    ).order_by(
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    all_rows = []
    client_stats = {}
    party_stats_all = {}

    for invoice in invoices:
        party = invoice_party_context(invoice, client_map=client_map, mandor_map=mandor_map)

        if not invoice_matches_receivable_filters(
            invoice,
            party,
            bill_to_type=selected_bill_to_type,
            status=selected_status,
            period_from=selected_period_from,
            period_to=selected_period_to,
        ):
            continue

        latest_log = InvoiceCollectionLog.query.filter_by(
            branch_id=selected_branch_id,
            invoice_id=invoice.id
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

        ar = build_invoice_ar_warning(invoice)
        stage = ar.get("stage") or "NORMAL"
        priority = priority_map.get(stage, 50)

        if invoice.client_id:
            client_key = str(invoice.client_id)
            client_name = party.get("client_name") or f"Client ID {invoice.client_id}"
        else:
            client_key = "NO_CLIENT"
            client_name = "Tanpa Client / Pihak Bebas"

        remaining = float(invoice.remaining_amount or 0)

        row = {
            "invoice": invoice,
            "client_key": client_key,
            "client_name": client_name,
            "mandor_name": party.get("mandor_name") or "-",
            "party": party,
            "party_key": party.get("key"),
            "party_name": party.get("name") or "-",
            "bill_to_type_label": party.get("type_label") or "-",
            "input_source_label": party.get("input_source_label") or "-",
            "latest_log": latest_log,
            "ar": ar,
            "priority": priority,
            "remaining": remaining,
        }

        all_rows.append(row)

        if client_key not in client_stats:
            client_stats[client_key] = {
                "value": client_key,
                "label": client_name,
                "invoice_count": 0,
                "remaining_total": 0,
            }

        client_stats[client_key]["invoice_count"] += 1
        client_stats[client_key]["remaining_total"] += remaining

        party_key = party.get("key") or f"UNKNOWN:{party.get('name', '-') }"
        if party_key not in party_stats_all:
            party_stats_all[party_key] = {
                "party_key": party_key,
                "party_name": party.get("name") or "-",
                "bill_to_type_label": party.get("type_label") or "-",
                "invoice_count": 0,
                "remaining_total": 0,
            }
        party_stats_all[party_key]["invoice_count"] += 1
        party_stats_all[party_key]["remaining_total"] += remaining

    if selected_client_id:
        base_rows_for_filter_count = [row for row in all_rows if row["client_key"] == selected_client_id]
    else:
        base_rows_for_filter_count = all_rows

    filter_stats = {
        key: {"value": key, "label": label, "count": 0, "total": 0}
        for key, label in filter_labels.items()
    }

    for row in base_rows_for_filter_count:
        stage = row["ar"].get("stage") or "NORMAL"
        remaining = float(row["remaining"] or 0)

        for key in filter_stats.keys():
            if match_filter(stage, key):
                filter_stats[key]["count"] += 1
                filter_stats[key]["total"] += remaining

    rows = [
        row for row in base_rows_for_filter_count
        if match_filter(row["ar"].get("stage"), selected_filter)
    ]

    rows.sort(key=lambda row: (
        row["priority"],
        row["invoice"].due_date or date(2999, 12, 31),
        row["invoice"].id
    ))

    stage_counter = defaultdict(int)
    party_recap = {}

    total_receivable = 0
    overdue_count = 0
    due_soon_count = 0
    follow_up_count = 0

    for row in rows:
        invoice = row["invoice"]
        ar = row["ar"]
        stage = ar.get("stage") or "NORMAL"
        stage_label = ar.get("stage_label") or "-"
        remaining = float(invoice.remaining_amount or 0)

        total_receivable += remaining
        stage_counter[stage_label] += 1

        if stage.startswith("OVERDUE"):
            overdue_count += 1

        if stage == "DUE_SOON":
            due_soon_count += 1

        if stage in [
            "NO_PAYMENT_7_DAYS",
            "FOLLOW_UP",
            "PROMISE_TO_PAY",
            "BELOW_EXPECTED_PAYMENT",
            "PARTIAL",
        ]:
            follow_up_count += 1

        party_key = row["party_key"]
        if party_key not in party_recap:
            party_recap[party_key] = {
                "party_name": row["party_name"],
                "bill_to_type_label": row["bill_to_type_label"],
                "invoice_count": 0,
                "remaining_total": 0,
            }

        party_recap[party_key]["invoice_count"] += 1
        party_recap[party_key]["remaining_total"] += remaining

    stage_rows = [
        {"stage": stage, "count": count}
        for stage, count in sorted(stage_counter.items(), key=lambda item: item[0])
    ]

    party_rows = sorted(
        party_recap.values(),
        key=lambda row: row["remaining_total"],
        reverse=True
    )

    # Backward-compatible alias for older template/tests that still read client_rows.
    client_rows = party_rows

    client_options = sorted(
        client_stats.values(),
        key=lambda row: row["remaining_total"],
        reverse=True
    )

    selected_client_name = ""
    if selected_client_id:
        selected_client_name = client_stats.get(selected_client_id, {}).get("label", "")

    summary = {
        "invoice_count": len(rows),
        "total_receivable": total_receivable,
        "overdue_count": overdue_count,
        "due_soon_count": due_soon_count,
        "follow_up_count": follow_up_count,
    }

    filter_options = [
        filter_stats["ALL"],
        filter_stats["OVERDUE"],
        filter_stats["DUE_SOON"],
        filter_stats["FOLLOW_UP"],
        filter_stats["PARTIAL_MONITOR"],
    ]

    selected_branch_name = next((row["label"] for row in branch_options if row["value"] == str(selected_branch_id)), "")

    return {
        "rows": rows,
        "stage_rows": stage_rows,
        "party_rows": party_rows,
        "client_rows": client_rows,
        "summary": summary,
        "filter_options": filter_options,
        "client_options": client_options,
        "branch_options": branch_options,
        "bill_to_type_choices": BILL_TO_TYPE_CHOICES,
        "status_options": receivable_status_choices_from_invoices(invoices),
        "selected_filter": selected_filter,
        "selected_filter_label": filter_labels[selected_filter],
        "selected_client_id": selected_client_id,
        "selected_client_name": selected_client_name,
        "selected_branch_id": str(selected_branch_id),
        "selected_branch_name": selected_branch_name,
        "selected_bill_to_type": selected_bill_to_type,
        "selected_status": selected_status,
        "selected_period_from": selected_period_from_raw,
        "selected_period_to": selected_period_to_raw,
        "filter_query": {
            "filter": selected_filter,
            "client_id": selected_client_id,
            "branch_id": selected_branch_id,
            "bill_to_type": selected_bill_to_type,
            "status": selected_status,
            "period_from": selected_period_from_raw,
            "period_to": selected_period_to_raw,
        },
    }


@finance_bp.route("/receivables")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables():
    context = _build_receivables_dashboard_context(request.args)
    return render_template("finance/receivables_dashboard.html", **context)


@finance_bp.route("/receivables/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables_print():
    context = _build_receivables_dashboard_context(request.args)
    return render_template("finance/receivables_print.html", **context)

# === PATCH_SOA_STEP13A1 ===
@finance_bp.route("/receivables/statement")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables_statement():
    from collections import defaultdict
    from datetime import date
    from urllib.parse import quote
    # SOA5B_IMPORT_PAYMENT
    from app.models.finance import Invoice, InvoiceCollectionLog, Payment
    from app.models.master import Client, Mandor, ClientPic

    # SOA2C2_HELPERS_IN_RECEIVABLES_STATEMENT
    def _soa_money(value):
        try:
            return f"Rp {float(value or 0):,.0f}".replace(",", ".")
        except Exception:
            return "Rp 0"

    def _soa_date(value):
        if not value:
            return "-"

        try:
            return value.strftime("%d-%m-%Y")
        except Exception:
            return str(value)

    def _soa_normalize_whatsapp(phone):
        raw = str(phone or "").strip()

        if not raw:
            return ""

        cleaned = ""

        for char in raw:
            if char.isdigit():
                cleaned += char

        if not cleaned:
            return ""

        if cleaned.startswith("0"):
            cleaned = "62" + cleaned[1:]

        if cleaned.startswith("8"):
            cleaned = "62" + cleaned

        return cleaned

    def _soa_build_message(group):
        target_name = group.get("wa_target_name") or "PIC Finance"
        client_name = group.get("client_name") or "-"
        rows = group.get("rows") or []

        lines = []

        lines.append("Yth. " + target_name + ",")
        lines.append("")
        lines.append("Berikut kami sampaikan Statement of Account / rekap piutang aktif PT Idha Boga Pangan Mandiri.")
        lines.append("")
        lines.append("Client: " + client_name)
        lines.append("Tanggal Rekap: " + _soa_date(date.today()))
        lines.append("")
        lines.append("Ringkasan Piutang:")
        lines.append("- Total Tagihan: " + _soa_money(group.get("total_amount")))
        lines.append("- Sudah Dibayar: " + _soa_money(group.get("paid_amount")))
        lines.append("- Sisa Piutang: " + _soa_money(group.get("remaining_total")))
        lines.append("")
        lines.append("Detail Invoice:")

        for idx, row in enumerate(rows, start=1):
            invoice = row.get("invoice")
            ar = row.get("ar") or {}
            latest_log = row.get("latest_log")

            lines.append(
                f"{idx}. {invoice.invoice_number} | Jatuh Tempo: {_soa_date(invoice.due_date)} | "
                f"Total: {_soa_money(invoice.total_amount)} | Dibayar: {_soa_money(invoice.paid_amount)} | "
                f"Sisa: {_soa_money(invoice.remaining_amount)} | Status: {invoice.status} | "
                f"Catatan: {ar.get('stage_label') or '-'}"
            )

            if latest_log:
                lines.append(
                    f"   Follow up terakhir: {latest_log.collection_status} pada {_soa_date(latest_log.follow_up_date)} "
                    f"oleh {latest_log.contact_person or '-'}"
                )

        lines.append("")
        lines.append("Mohon konfirmasi jadwal pelunasan atau informasi proses pembayaran dari pihak client.")
        lines.append("")
        lines.append("Terima kasih.")

        return "\n".join(lines)

    selected_client_id = (request.args.get("client_id") or "").strip()
    date_filter = resolve_date_filter(request.args, default_preset="all")

    active_query = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    )

    all_active_invoices = active_query.order_by(
        Invoice.client_id.asc(),
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    client_stats = {}

    for invoice in all_active_invoices:
        if invoice.client_id:
            client = Client.query.get(invoice.client_id)
            client_key = str(invoice.client_id)
            client_name = client.name if client else f"Client ID {invoice.client_id}"
        else:
            client_key = "NO_CLIENT"
            client_name = "Tanpa Client / Mandor"

        if client_key not in client_stats:
            client_stats[client_key] = {
                "value": client_key,
                "label": client_name,
                "invoice_count": 0,
                "total_amount": 0,
                "paid_amount": 0,
                "remaining_total": 0
            }

        client_stats[client_key]["invoice_count"] += 1
        client_stats[client_key]["total_amount"] += float(invoice.total_amount or 0)
        client_stats[client_key]["paid_amount"] += float(invoice.paid_amount or 0)
        client_stats[client_key]["remaining_total"] += float(invoice.remaining_amount or 0)

    client_options = sorted(
        client_stats.values(),
        key=lambda row: row["label"].lower()
    )

    selected_client_name = ""

    statement_query = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    )
    statement_query = apply_date_range_to_query(statement_query, Invoice.due_date, date_filter)

    if selected_client_id:
        if selected_client_id == "NO_CLIENT":
            statement_query = statement_query.filter(Invoice.client_id.is_(None))
            selected_client_name = "Tanpa Client / Mandor"
        else:
            try:
                selected_client_int = int(selected_client_id)
            except Exception:
                selected_client_int = None

            if not selected_client_int:
                flash("Filter client tidak valid.", "warning")
                return redirect(url_for("finance.receivables_statement"))

            statement_query = statement_query.filter(Invoice.client_id == selected_client_int)

            selected_client = Client.query.get(selected_client_int)
            selected_client_name = selected_client.name if selected_client else f"Client ID {selected_client_int}"

    invoices = statement_query.order_by(
        Invoice.client_id.asc(),
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    grouped = {}

    for invoice in invoices:
        client = Client.query.get(invoice.client_id) if invoice.client_id else None
        mandor = Mandor.query.get(invoice.mandor_id) if invoice.mandor_id else None

        if client:
            client_key = str(client.id)
            client_name = client.name or f"Client ID {client.id}"
            client_address = client.address or "-"
            client_phone = client.phone or "-"
            pics = ClientPic.query.filter_by(
                client_id=client.id,
                is_active=True
            ).order_by(
                ClientPic.id.asc()
            ).all()
        else:
            client_key = "NO_CLIENT"
            client_name = "Tanpa Client / Mandor"
            client_address = "-"
            client_phone = "-"
            pics = []

        # SOA2B_TARGET_WHATSAPP_GROUP
        selected_pic = None

        for pic in pics:
            if not selected_pic and pic.phone:
                selected_pic = pic

        if selected_pic:
            wa_target_source = "PIC_CLIENT"
            wa_target_name = selected_pic.name or client_name
            wa_target_phone = selected_pic.phone or ""
        elif client_phone and client_phone != "-":
            wa_target_source = "CLIENT_PHONE_FALLBACK"
            wa_target_name = client_name
            wa_target_phone = client_phone
        else:
            wa_target_source = "NO_PHONE"
            wa_target_name = client_name
            wa_target_phone = ""

        wa_number = _soa_normalize_whatsapp(wa_target_phone)

        if client_key not in grouped:
            grouped[client_key] = {
                "client_key": client_key,
                "client_name": client_name,
                "client_address": client_address,
                "client_phone": client_phone,
                "pics": pics,
                "wa_target_source": wa_target_source,
                "wa_target_name": wa_target_name,
                "wa_target_phone": wa_target_phone,
                "wa_number": wa_number,
                "soa_message": "",
                "soa_whatsapp_url": "",
                "rows": [],
                "invoice_count": 0,
                "total_amount": 0,
                "paid_amount": 0,
                "remaining_total": 0
            }

        # SOA5B_LATEST_PAYMENT_AND_FOLLOWUP
        latest_payment = Payment.query.filter_by(
            branch_id=current_user.branch_id,
            invoice_id=invoice.id
        ).order_by(
            Payment.payment_date.desc(),
            Payment.id.desc()
        ).first()

        latest_log = InvoiceCollectionLog.query.filter(
            InvoiceCollectionLog.branch_id == current_user.branch_id,
            InvoiceCollectionLog.invoice_id == invoice.id,
            InvoiceCollectionLog.channel != "SYSTEM"
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

        ar = build_invoice_ar_warning(invoice)

        row = {
            "invoice": invoice,
            "bill_to": get_invoice_bill_to(invoice),
            "mandor_name": mandor.name if mandor else "-",
            "latest_payment": latest_payment,
            "latest_log": latest_log,
            "ar": ar
        }

        grouped[client_key]["rows"].append(row)
        grouped[client_key]["invoice_count"] += 1
        grouped[client_key]["total_amount"] += float(invoice.total_amount or 0)
        grouped[client_key]["paid_amount"] += float(invoice.paid_amount or 0)
        grouped[client_key]["remaining_total"] += float(invoice.remaining_amount or 0)

    client_groups = sorted(
        grouped.values(),
        key=lambda row: row["remaining_total"],
        reverse=True
    )

    # SOA2B_BUILD_MESSAGE_URL
    for group in client_groups:
        message = _soa_build_message(group)
        group["soa_message"] = message

        if group.get("wa_number"):
            group["soa_whatsapp_url"] = f"https://wa.me/{group['wa_number']}?text={quote(message)}"
        else:
            group["soa_whatsapp_url"] = ""

    summary = {
        "generated_date": date.today(),
        "client_count": len(client_groups),
        "invoice_count": len(invoices),
        "total_amount": sum(float(invoice.total_amount or 0) for invoice in invoices),
        "paid_amount": sum(float(invoice.paid_amount or 0) for invoice in invoices),
        "remaining_total": sum(float(invoice.remaining_amount or 0) for invoice in invoices)
    }

    return render_template(
        "finance/receivables_statement.html",
        client_groups=client_groups,
        client_options=client_options,
        selected_client_id=selected_client_id,
        selected_client_name=selected_client_name,
        summary=summary,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("finance.receivables_statement"),
            reset_url=url_for("finance.receivables_statement"),
            title="Filter Statement Piutang",
            description="Custom tanggal jatuh tempo invoice dan client yang ingin ditagih.",
            hidden_fields={"client_id": selected_client_id},
        )
    )

# SOA4B_STATEMENT_SENT_ROUTE
@finance_bp.route("/receivables/statement/send")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables_statement_send():
    from datetime import date
    from urllib.parse import quote
    from app.extensions import db
    from app.models.finance import Invoice, InvoiceCollectionLog
    from app.models.master import Client, Mandor, ClientPic

    def _soa_money(value):
        try:
            return f"Rp {float(value or 0):,.0f}".replace(",", ".")
        except Exception:
            return "Rp 0"

    def _soa_date(value):
        if not value:
            return "-"

        try:
            return value.strftime("%d-%m-%Y")
        except Exception:
            return str(value)

    def _soa_normalize_whatsapp(phone):
        cleaned = ""

        for char in str(phone or ""):
            if char.isdigit():
                cleaned += char

        if cleaned.startswith("0"):
            cleaned = "62" + cleaned[1:]

        if cleaned.startswith("8"):
            cleaned = "62" + cleaned

        return cleaned

    selected_client_id = (request.args.get("client_id") or "").strip()

    if not selected_client_id:
        flash("Pilih client terlebih dahulu sebelum mengirim Statement of Account.", "warning")
        return redirect(url_for("finance.receivables_statement"))

    query = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    )

    client = None
    client_name = "Tanpa Client / Mandor"
    client_phone = ""

    if selected_client_id == "NO_CLIENT":
        query = query.filter(Invoice.client_id.is_(None))
    else:
        try:
            client_id_int = int(selected_client_id)
        except Exception:
            flash("Filter client tidak valid.", "warning")
            return redirect(url_for("finance.receivables_statement"))

        client = Client.query.get(client_id_int)

        if not client:
            flash("Data client tidak ditemukan.", "warning")
            return redirect(url_for("finance.receivables_statement"))

        client_name = client.name or f"Client ID {client.id}"
        client_phone = client.phone or ""

        query = query.filter(Invoice.client_id == client.id)

    invoices = query.order_by(
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    if not invoices:
        flash("Tidak ada invoice piutang aktif untuk client tersebut.", "info")
        return redirect(url_for("finance.receivables_statement", client_id=selected_client_id))

    pics = []
    if client:
        pics = ClientPic.query.filter_by(
            client_id=client.id,
            is_active=True
        ).order_by(
            ClientPic.id.asc()
        ).all()

    selected_pic = None

    for pic in pics:
        if not selected_pic and pic.phone:
            selected_pic = pic

    if selected_pic:
        target_source = "PIC_CLIENT"
        target_name = selected_pic.name or client_name
        target_phone = selected_pic.phone or ""
    elif client_phone:
        target_source = "CLIENT_PHONE_FALLBACK"
        target_name = client_name
        target_phone = client_phone
    else:
        target_source = "NO_PHONE"
        target_name = client_name
        target_phone = ""

    wa_number = _soa_normalize_whatsapp(target_phone)

    if not wa_number:
        flash("Nomor WhatsApp tujuan belum tersedia untuk client ini.", "warning")
        return redirect(url_for("finance.receivables_statement", client_id=selected_client_id))

    rows = []
    total_amount = 0
    paid_amount = 0
    remaining_total = 0

    for invoice in invoices:
        mandor = Mandor.query.get(invoice.mandor_id) if invoice.mandor_id else None
        latest_log = InvoiceCollectionLog.query.filter_by(
            branch_id=current_user.branch_id,
            invoice_id=invoice.id
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

        ar = build_invoice_ar_warning(invoice)

        rows.append({
            "invoice": invoice,
            "mandor": mandor,
            "latest_log": latest_log,
            "ar": ar
        })

        total_amount += float(invoice.total_amount or 0)
        paid_amount += float(invoice.paid_amount or 0)
        remaining_total += float(invoice.remaining_amount or 0)

    lines = []

    lines.append("Yth. " + target_name + ",")
    lines.append("")
    lines.append("Berikut kami sampaikan Statement of Account / rekap piutang aktif PT Idha Boga Pangan Mandiri.")
    lines.append("")
    lines.append("Client: " + client_name)
    lines.append("Tanggal Rekap: " + _soa_date(date.today()))
    lines.append("")
    lines.append("Ringkasan Piutang:")
    lines.append("- Total Tagihan: " + _soa_money(total_amount))
    lines.append("- Sudah Dibayar: " + _soa_money(paid_amount))
    lines.append("- Sisa Piutang: " + _soa_money(remaining_total))
    lines.append("")
    lines.append("Detail Invoice:")

    for index, row in enumerate(rows, start=1):
        invoice = row["invoice"]
        ar = row["ar"]
        latest_log = row["latest_log"]

        lines.append(
            f"{index}. {invoice.invoice_number} | Jatuh Tempo: {_soa_date(invoice.due_date)} | "
            f"Total: {_soa_money(invoice.total_amount)} | Dibayar: {_soa_money(invoice.paid_amount)} | "
            f"Sisa: {_soa_money(invoice.remaining_amount)} | Status: {invoice.status} | "
            f"Catatan: {ar.get('stage_label') or '-'}"
        )

        if latest_log:
            lines.append(
                f"   Follow up terakhir: {latest_log.collection_status} pada {_soa_date(latest_log.follow_up_date)} "
                f"oleh {latest_log.contact_person or '-'}"
            )

    lines.append("")
    lines.append("Mohon konfirmasi jadwal pelunasan atau informasi proses pembayaran dari pihak client.")
    lines.append("")
    lines.append("Terima kasih.")

    message = "\n".join(lines)
    wa_url = f"https://wa.me/{wa_number}?text={quote(message)}"

    created_count = 0
    skipped_count = 0
    today = date.today()

    try:
        for invoice in invoices:
            existing_log = InvoiceCollectionLog.query.filter_by(
                branch_id=current_user.branch_id,
                invoice_id=invoice.id,
                follow_up_date=today,
                collection_status="STATEMENT_SENT"
            ).first()

            if existing_log:
                skipped_count += 1
                continue

            log = InvoiceCollectionLog(
                branch_id=current_user.branch_id,
                invoice_id=invoice.id,
                follow_up_date=today,
                channel="WHATSAPP",
                contact_person=target_name,
                response_note=(
                    f"Statement of Account / rekap piutang aktif client {client_name} "
                    f"dikirim melalui WhatsApp ke {target_name} ({target_phone}). "
                    f"Target menggunakan {target_source}. "
                    f"Total tagihan { _soa_money(total_amount) }, sudah dibayar { _soa_money(paid_amount) }, "
                    f"sisa piutang { _soa_money(remaining_total) }."
                ),
                promise_date=None,
                next_action="Menunggu konfirmasi jadwal pelunasan dari client.",
                collection_status="STATEMENT_SENT",
                created_by=current_user.id
            )

            db.session.add(log)
            created_count += 1

        db.session.commit()

        if created_count > 0:
            record_audit_log(
                module="FINANCE",
                event_type="RECEIVABLES_STATEMENT_LOG_CREATED",
                action="CREATE",
                table_name="invoice_collection_logs",
                record_id=None,
                description=f"Statement of Account dicatat untuk {created_count} invoice client {client_name}.",
                metadata={"client_id": selected_client_id, "client_name": client_name, "created_count": created_count, "skipped_count": skipped_count},
            )
            flash(f"Log Statement of Account berhasil dicatat untuk {created_count} invoice.", "success")
        else:
            flash("Statement of Account sudah pernah dicatat hari ini. Tidak dibuat log ganda.", "info")

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal mencatat log Statement of Account: {error}", "danger")
        return redirect(url_for("finance.receivables_statement", client_id=selected_client_id))

    return redirect(wa_url)

# RECEIPT1B_PAYMENT_RECEIPT_ROUTE
@finance_bp.route("/payments/<int:payment_id>/receipt")
@role_required("OWNER", "ADMIN", "FINANCE")
def payment_receipt(payment_id):
    from app.models.finance import Invoice, Payment
    from app.models.master import Client, Mandor, ClientPic
    from app.models.accounting import Journal, JournalDetail

    payment = Payment.query.get_or_404(payment_id)
    invoice = Invoice.query.get_or_404(payment.invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data pembayaran tidak sesuai cabang aktif.", "danger")
        return redirect(url_for("finance.invoices"))

    client = Client.query.get(invoice.client_id) if invoice.client_id else None
    mandor = Mandor.query.get(invoice.mandor_id) if invoice.mandor_id else None

    client_pics = []
    if client:
        client_pics = ClientPic.query.filter_by(
            client_id=client.id,
            is_active=True
        ).order_by(
            ClientPic.id.asc()
        ).all()

    journal = Journal.query.filter_by(
        reference_type="PAYMENT",
        reference_id=payment.id
    ).order_by(
        Journal.id.desc()
    ).first()

    journal_details = []

    if journal:
        journal_details = JournalDetail.query.filter_by(
            journal_id=journal.id
        ).order_by(
            JournalDetail.id.asc()
        ).all()

    company_settings = get_company_settings(current_user.branch_id)

    payment_attachments = list_reference_attachments(
        module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
        reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
        reference_id=payment.id,
        branch_id=current_user.branch_id,
    )

    receipt = {
        "receipt_number": payment.payment_number,
        "payment": payment,
        "invoice": invoice,
        "client": client,
        "mandor": mandor,
        "client_pics": client_pics,
        "journal": journal,
        "journal_details": journal_details,
        "company_name": company_settings.get("company_name"),
        "company_subtitle": company_settings.get("company_subtitle"),
        "company_address": company_settings.get("company_address"),
        "company_phone": company_settings.get("company_phone"),
        "company_email": company_settings.get("company_email"),
        "company_npwp": company_settings.get("company_npwp"),
        "invoice_authorized_name": company_settings.get("invoice_authorized_name"),
        "invoice_authorized_position": company_settings.get("invoice_authorized_position"),
        "received_from": client.name if client else (mandor.name if mandor else "-"),
        "for_invoice": invoice.invoice_number,
        "remaining_after_payment": invoice.remaining_amount,
    }

    return render_template(
        "finance/payment_receipt.html",
        receipt=receipt,
        payment=payment,
        invoice=invoice,
        client=client,
        mandor=mandor,
        client_pics=client_pics,
        journal=journal,
        journal_details=journal_details,
        company_settings=company_settings,
        payment_attachments=payment_attachments,
        format_file_size=format_file_size,
    )


@finance_bp.route("/payments/<int:payment_id>/attachments/upload", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def upload_customer_payment_attachment(payment_id):
    payment = _payment_or_404(payment_id)

    proof_file = request.files.get("proof_file")
    try:
        save_digital_attachment(
            file_storage=proof_file,
            module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=payment.id,
            attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_CUSTOMER",
            branch_id=current_user.branch_id,
            uploaded_by=current_user.id,
            notes=request.form.get("proof_notes") or None,
        )
        flash("Bukti transfer/payment customer berhasil diunggah.", "success")
    except AttachmentValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"Bukti transfer/payment customer gagal diunggah: {exc}", "danger")

    return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))


@finance_bp.route("/payments/attachments/<int:attachment_id>/view")
@role_required("OWNER", "ADMIN", "FINANCE")
def view_customer_payment_attachment(attachment_id):
    attachment, payment = _payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        flash(f"File bukti payment tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))

    return send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/payments/attachments/<int:attachment_id>/download")
@role_required("OWNER", "ADMIN", "FINANCE")
def download_customer_payment_attachment(attachment_id):
    attachment, payment = _payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        flash(f"File bukti payment tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/payments/attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def delete_customer_payment_attachment(attachment_id):
    attachment, payment = _payment_attachment_or_404(attachment_id)
    note = (request.form.get("delete_note") or "Bukti payment customer salah upload.").strip()
    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    flash("Bukti payment customer berhasil dihapus lunak. File fisik tetap tersimpan untuk audit.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))


# FINANCE3B_PAYMENT_HISTORY_ROUTE
@finance_bp.route("/payment-history")
@role_required("OWNER", "ADMIN", "FINANCE")
def payment_history():
    # FINANCE3B_FINAL_LOCAL_JOURNAL_IMPORT
    from app.models.accounting import Journal
    from app.models.finance import CashBankTransaction
    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    method_filter = (request.args.get("payment_method") or "ALL").upper().strip()
    if method_filter not in ["ALL", "CASH", "TRANSFER", "QRIS"]:
        method_filter = "ALL"

    payment_query = Payment.query.filter(Payment.branch_id == current_user.branch_id)
    payment_query = apply_date_range_to_query(payment_query, Payment.payment_date, date_filter)
    if method_filter != "ALL":
        payment_query = payment_query.filter(Payment.payment_method == method_filter)

    payments = (
        payment_query
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )

    rows = []
    total_paid = 0

    for payment in payments:
        invoice = payment.invoice

        if not invoice:
            invoice = Invoice.query.filter_by(id=payment.invoice_id).first()

        client = None
        mandor = None

        if invoice and invoice.client_id:
            client = Client.query.filter_by(id=invoice.client_id).first()

        if invoice and invoice.mandor_id:
            mandor = Mandor.query.filter_by(id=invoice.mandor_id).first()

        journal = Journal.query.filter_by(
            reference_type="PAYMENT",
            reference_id=payment.id
        ).first()

        ledger_transaction = CashBankTransaction.query.filter_by(
            reference_type="PAYMENT",
            reference_id=payment.id
        ).first()

        amount = float(payment.amount or 0)
        total_paid += amount

        rows.append({
            "payment": payment,
            "invoice": invoice,
            "client": client,
            "mandor": mandor,
            "journal": journal,
            "ledger_transaction": ledger_transaction,
            "attachment_count": count_reference_attachments(
                module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                reference_id=payment.id,
                branch_id=current_user.branch_id,
            ),
            "amount": amount,
        })

    return render_template(
        "finance/payment_history.html",
        rows=rows,
        total_paid=total_paid,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("finance.payment_history"),
            reset_url=url_for("finance.payment_history"),
            title="Filter Pembayaran Invoice",
            description="Custom tanggal pembayaran dan metode masuk kas/bank.",
            status_name="payment_method",
            status_value=method_filter,
            status_options=[
                {"value": "ALL", "label": "Semua Metode"},
                {"value": "CASH", "label": "Cash"},
                {"value": "TRANSFER", "label": "Transfer"},
                {"value": "QRIS", "label": "QRIS"},
            ],
        ),
    )


# === PRODUCTION_CASH_BANK_LEDGER_ROUTE ===
@finance_bp.route("/cash-bank-ledger")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def cash_bank_ledger():
    from datetime import datetime
    from app.models.finance import (
        CashBankAdjustment,
        CashBankOpeningBalance,
        CashBankTransaction,
        CashBankTransfer,
        Payment,
        SupplierPayment,
        BankAccount,
        TransportVehicleExpense,
    )
    from app.models.logistics import Procurement
    from app.models.accounting import FixedAssetPurchase

    selected_transaction_type = (request.args.get("transaction_type") or "ALL").strip().upper()
    selected_account_type = (request.args.get("account_type") or "ALL").strip().upper()
    selected_reference_type = (request.args.get("reference_type") or "ALL").strip().upper()
    selected_bank_account_id = (request.args.get("bank_account_id") or "ALL").strip()
    selected_reconciliation_status = (request.args.get("reconciliation_status") or "ALL").strip().upper()
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()

    allowed_transaction_types = ["ALL", "IN", "OUT"]
    allowed_account_types = ["ALL", "CASH", "BANK"]
    allowed_reference_types = [
        "ALL",
        "PAYMENT",
        "PROCUREMENT",
        "SUPPLIER_PAYMENT",
        "OPENING_BALANCE",
        "CASH_BANK_TRANSFER",
        "CASH_BANK_ADJUSTMENT",
        "FIXED_ASSET_PURCHASE",
        "TRANSPORT_VEHICLE_EXPENSE",
        "OPERATIONAL_EXPENSE",
    ]
    allowed_reconciliation_statuses = ["ALL", "RECONCILED", "UNRECONCILED"]

    if selected_transaction_type not in allowed_transaction_types:
        selected_transaction_type = "ALL"

    if selected_account_type not in allowed_account_types:
        selected_account_type = "ALL"

    if selected_reference_type not in allowed_reference_types:
        selected_reference_type = "ALL"

    if selected_reconciliation_status not in allowed_reconciliation_statuses:
        selected_reconciliation_status = "ALL"

    start_date = None
    end_date = None

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
        except Exception:
            flash("Filter tanggal awal ledger kas/bank tidak valid.", "warning")
            start_date_raw = ""

    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
        except Exception:
            flash("Filter tanggal akhir ledger kas/bank tidak valid.", "warning")
            end_date_raw = ""

    query = CashBankTransaction.query.filter(
        CashBankTransaction.branch_id == current_user.branch_id
    )

    if selected_transaction_type != "ALL":
        query = query.filter(CashBankTransaction.transaction_type == selected_transaction_type)

    if selected_account_type != "ALL":
        query = query.filter(CashBankTransaction.account_type == selected_account_type)

    if selected_reference_type != "ALL":
        query = query.filter(CashBankTransaction.reference_type == selected_reference_type)

    if selected_reconciliation_status == "RECONCILED":
        query = query.filter(CashBankTransaction.is_reconciled.is_(True))
    elif selected_reconciliation_status == "UNRECONCILED":
        query = query.filter(CashBankTransaction.is_reconciled.is_(False))

    if selected_bank_account_id != "ALL":
        try:
            selected_bank_account_int = int(selected_bank_account_id)
            query = query.filter(CashBankTransaction.bank_account_id == selected_bank_account_int)
        except (TypeError, ValueError):
            flash("Filter rekening bank ledger kas/bank tidak valid.", "warning")
            selected_bank_account_id = "ALL"

    if start_date:
        query = query.filter(CashBankTransaction.transaction_date >= start_date)

    if end_date:
        query = query.filter(CashBankTransaction.transaction_date <= end_date)

    transactions_all_for_summary = query.order_by(
        CashBankTransaction.transaction_date.desc(),
        CashBankTransaction.id.desc()
    ).all()

    transactions = transactions_all_for_summary[:300]
    is_limited = len(transactions_all_for_summary) > len(transactions)

    summary = {
        "count": len(transactions_all_for_summary),
        "total_in": 0,
        "total_out": 0,
        "net": 0,
        "cash_in": 0,
        "cash_out": 0,
        "cash_net": 0,
        "bank_in": 0,
        "bank_out": 0,
        "bank_net": 0,
        "reconciled_count": 0,
        "unreconciled_count": 0,
    }

    bank_summary = {}

    for transaction in transactions_all_for_summary:
        amount = float(transaction.amount or 0)
        transaction_type = str(transaction.transaction_type or "").upper()
        account_type = str(transaction.account_type or "").upper()

        if transaction.is_reconciled:
            summary["reconciled_count"] += 1
        else:
            summary["unreconciled_count"] += 1

        if transaction_type == "IN":
            summary["total_in"] += amount
            if account_type == "CASH":
                summary["cash_in"] += amount
            elif account_type == "BANK":
                summary["bank_in"] += amount
        elif transaction_type == "OUT":
            summary["total_out"] += amount
            if account_type == "CASH":
                summary["cash_out"] += amount
            elif account_type == "BANK":
                summary["bank_out"] += amount

        if account_type == "BANK" and transaction.bank_account_id:
            bank_key = transaction.bank_account_id
            if bank_key not in bank_summary:
                bank_summary[bank_key] = {
                    "bank_account": transaction.bank_account,
                    "total_in": 0,
                    "total_out": 0,
                    "net": 0,
                    "count": 0,
                    "reconciled_count": 0,
                    "unreconciled_count": 0,
                }

            bank_summary[bank_key]["count"] += 1
            if transaction.is_reconciled:
                bank_summary[bank_key]["reconciled_count"] += 1
            else:
                bank_summary[bank_key]["unreconciled_count"] += 1

            if transaction_type == "IN":
                bank_summary[bank_key]["total_in"] += amount
            elif transaction_type == "OUT":
                bank_summary[bank_key]["total_out"] += amount

    summary["net"] = summary["total_in"] - summary["total_out"]
    summary["cash_net"] = summary["cash_in"] - summary["cash_out"]
    summary["bank_net"] = summary["bank_in"] - summary["bank_out"]

    for row in bank_summary.values():
        row["net"] = row["total_in"] - row["total_out"]

    reference_ids = {
        "PAYMENT": [],
        "PROCUREMENT": [],
        "SUPPLIER_PAYMENT": [],
        "OPENING_BALANCE": [],
        "CASH_BANK_TRANSFER": [],
        "CASH_BANK_ADJUSTMENT": [],
        "FIXED_ASSET_PURCHASE": [],
        "TRANSPORT_VEHICLE_EXPENSE": [],
        "OPERATIONAL_EXPENSE": [],
    }

    for transaction in transactions:
        reference_type = str(transaction.reference_type or "").upper()
        if reference_type in reference_ids and transaction.reference_id:
            reference_ids[reference_type].append(transaction.reference_id)

    payment_map = {}
    procurement_map = {}
    supplier_payment_map = {}
    opening_map = {}
    transfer_map = {}
    adjustment_map = {}
    fixed_asset_purchase_map = {}
    transport_expense_map = {}
    operational_expense_map = {}

    if reference_ids["PAYMENT"]:
        payments = Payment.query.filter(
            Payment.branch_id == current_user.branch_id,
            Payment.id.in_(reference_ids["PAYMENT"])
        ).all()
        payment_map = {payment.id: payment for payment in payments}

    if reference_ids["PROCUREMENT"]:
        procurements = Procurement.query.filter(
            Procurement.branch_id == current_user.branch_id,
            Procurement.id.in_(reference_ids["PROCUREMENT"])
        ).all()
        procurement_map = {procurement.id: procurement for procurement in procurements}

    if reference_ids["SUPPLIER_PAYMENT"]:
        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.branch_id == current_user.branch_id,
            SupplierPayment.id.in_(reference_ids["SUPPLIER_PAYMENT"])
        ).all()
        supplier_payment_map = {payment.id: payment for payment in supplier_payments}

    if reference_ids["OPENING_BALANCE"]:
        openings = CashBankOpeningBalance.query.filter(
            CashBankOpeningBalance.branch_id == current_user.branch_id,
            CashBankOpeningBalance.id.in_(reference_ids["OPENING_BALANCE"])
        ).all()
        opening_map = {opening.id: opening for opening in openings}

    if reference_ids["CASH_BANK_TRANSFER"]:
        transfers = CashBankTransfer.query.filter(
            CashBankTransfer.branch_id == current_user.branch_id,
            CashBankTransfer.id.in_(reference_ids["CASH_BANK_TRANSFER"])
        ).all()
        transfer_map = {transfer.id: transfer for transfer in transfers}

    if reference_ids["CASH_BANK_ADJUSTMENT"]:
        adjustments = CashBankAdjustment.query.filter(
            CashBankAdjustment.branch_id == current_user.branch_id,
            CashBankAdjustment.id.in_(reference_ids["CASH_BANK_ADJUSTMENT"])
        ).all()
        adjustment_map = {adjustment.id: adjustment for adjustment in adjustments}

    if reference_ids["FIXED_ASSET_PURCHASE"]:
        fixed_asset_purchases = FixedAssetPurchase.query.filter(
            FixedAssetPurchase.branch_id == current_user.branch_id,
            FixedAssetPurchase.id.in_(reference_ids["FIXED_ASSET_PURCHASE"])
        ).all()
        fixed_asset_purchase_map = {purchase.id: purchase for purchase in fixed_asset_purchases}

    if reference_ids["TRANSPORT_VEHICLE_EXPENSE"]:
        transport_expenses = TransportVehicleExpense.query.filter(
            TransportVehicleExpense.branch_id == current_user.branch_id,
            TransportVehicleExpense.id.in_(reference_ids["TRANSPORT_VEHICLE_EXPENSE"])
        ).all()
        transport_expense_map = {expense.id: expense for expense in transport_expenses}

    if reference_ids["OPERATIONAL_EXPENSE"]:
        from app.models.finance import OperationalExpense
        operational_expenses = OperationalExpense.query.filter(
            OperationalExpense.branch_id == current_user.branch_id,
            OperationalExpense.id.in_(reference_ids["OPERATIONAL_EXPENSE"])
        ).all()
        operational_expense_map = {expense.id: expense for expense in operational_expenses}

    rows = []

    for transaction in transactions:
        reference_type = str(transaction.reference_type or "").upper()
        source_label = reference_type or "-"
        source_detail = "-"
        source_url = None

        if reference_type == "PAYMENT":
            payment = payment_map.get(transaction.reference_id)
            if payment:
                source_label = payment.payment_number
                if payment.invoice:
                    source_detail = f"Invoice {payment.invoice.invoice_number}"
                    source_url = url_for("finance.invoice_detail", invoice_id=payment.invoice_id)
                else:
                    source_detail = f"Payment ID {payment.id}"

        elif reference_type == "PROCUREMENT":
            procurement = procurement_map.get(transaction.reference_id)
            if procurement:
                source_label = procurement.procurement_number
                source_detail = procurement.purchase_place or procurement.supplier_name or "Pembelian barang"
                source_url = url_for("logistics.purchase_detail", procurement_id=procurement.id)

        elif reference_type == "SUPPLIER_PAYMENT":
            supplier_payment = supplier_payment_map.get(transaction.reference_id)
            if supplier_payment:
                source_label = supplier_payment.payment_number
                if supplier_payment.supplier_bill:
                    source_detail = f"Hutang {supplier_payment.supplier_bill.bill_number} - {supplier_payment.supplier_bill.supplier_name}"
                    source_url = url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill.id)
                else:
                    source_detail = f"Supplier Payment ID {supplier_payment.id}"

        elif reference_type == "OPENING_BALANCE":
            opening = opening_map.get(transaction.reference_id)
            source_label = "Saldo Awal"
            if opening:
                source_detail = opening.notes or "Saldo awal kas/bank"
                source_url = url_for("finance.cash_bank_opening_balances")

        elif reference_type == "CASH_BANK_TRANSFER":
            transfer = transfer_map.get(transaction.reference_id)
            if transfer:
                source_label = transfer.transfer_number
                source_detail = transfer.notes or "Transfer antar kas/bank"
                source_url = url_for("finance.cash_bank_transfers")

        elif reference_type == "CASH_BANK_ADJUSTMENT":
            adjustment = adjustment_map.get(transaction.reference_id)
            if adjustment:
                source_label = adjustment.adjustment_number
                source_detail = adjustment.reason or "Penyesuaian saldo"
                source_url = url_for("finance.cash_bank_adjustments")

        elif reference_type == "FIXED_ASSET_PURCHASE":
            purchase = fixed_asset_purchase_map.get(transaction.reference_id)
            if purchase:
                source_label = purchase.purchase_number
                asset_name = purchase.fixed_asset.asset_name if purchase.fixed_asset else "Aset tetap"
                source_detail = f"Pembelian aset tetap - {asset_name}"
                source_url = url_for("finance.fixed_asset_purchase_detail", purchase_id=purchase.id)

        elif reference_type == "TRANSPORT_VEHICLE_EXPENSE":
            expense = transport_expense_map.get(transaction.reference_id)
            if expense:
                source_label = expense.expense_number
                source_detail = f"Transport/BBM COA {expense.account_code}"
                source_url = url_for("finance.transport_expense_detail", expense_id=expense.id)

        elif reference_type == "OPERATIONAL_EXPENSE":
            expense = operational_expense_map.get(transaction.reference_id)
            if expense:
                source_label = expense.expense_number
                source_detail = f"Biaya operasional COA {expense.account_code}"
                source_url = url_for("finance.operational_expense_detail", expense_id=expense.id)

        rows.append({
            "transaction": transaction,
            "source_label": source_label,
            "source_detail": source_detail,
            "source_url": source_url,
        })

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc(),
    ).all()

    transaction_type_options = [
        {"value": "ALL", "label": "Semua"},
        {"value": "IN", "label": "Uang Masuk"},
        {"value": "OUT", "label": "Uang Keluar"},
    ]
    account_type_options = [
        {"value": "ALL", "label": "Semua"},
        {"value": "CASH", "label": "Kas"},
        {"value": "BANK", "label": "Bank"},
    ]
    reference_type_options = [
        {"value": "ALL", "label": "Semua Sumber"},
        {"value": "OPENING_BALANCE", "label": "Saldo Awal"},
        {"value": "PAYMENT", "label": "Pembayaran Customer"},
        {"value": "PROCUREMENT", "label": "Pembelian Tunai"},
        {"value": "SUPPLIER_PAYMENT", "label": "Pembayaran Supplier"},
        {"value": "CASH_BANK_TRANSFER", "label": "Transfer Kas/Bank"},
        {"value": "CASH_BANK_ADJUSTMENT", "label": "Penyesuaian Saldo"},
        {"value": "FIXED_ASSET_PURCHASE", "label": "Pembelian Aset Tetap"},
        {"value": "TRANSPORT_VEHICLE_EXPENSE", "label": "Transport & BBM"},
        {"value": "OPERATIONAL_EXPENSE", "label": "Biaya Operasional Catering"},
    ]
    reconciliation_status_options = [
        {"value": "ALL", "label": "Semua"},
        {"value": "RECONCILED", "label": "Sudah Rekonsiliasi"},
        {"value": "UNRECONCILED", "label": "Belum Rekonsiliasi"},
    ]

    return render_template(
        "finance/cash_bank_ledger.html",
        rows=rows,
        summary=summary,
        bank_summary=sorted(bank_summary.values(), key=lambda row: (row["bank_account"].bank_name if row["bank_account"] else "", row["bank_account"].account_name if row["bank_account"] else "")),
        active_bank_accounts=active_bank_accounts,
        selected_transaction_type=selected_transaction_type,
        selected_account_type=selected_account_type,
        selected_reference_type=selected_reference_type,
        selected_bank_account_id=selected_bank_account_id,
        selected_reconciliation_status=selected_reconciliation_status,
        start_date=start_date_raw,
        end_date=end_date_raw,
        export_cash_bank_ledger_url=url_for("finance.export_cash_bank_ledger_csv", **request.args.to_dict(flat=True)),
        transaction_type_options=transaction_type_options,
        account_type_options=account_type_options,
        reference_type_options=reference_type_options,
        reconciliation_status_options=reconciliation_status_options,
        is_limited=is_limited,
    )


@finance_bp.route("/cash-bank-ledger/<int:transaction_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def cash_bank_transaction_detail(transaction_id):
    from app.models.finance import CashBankTransaction
    from app.services.field_transaction_service import find_field_transaction_linked_source

    transaction = CashBankTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        abort(404)

    field_transaction_link = find_field_transaction_linked_source(
        "CASH_BANK_TRANSACTION",
        transaction.id,
        branch_id=current_user.branch_id,
    )

    return render_template(
        "finance/cash_bank_transaction_detail.html",
        transaction=transaction,
        field_transaction_link=field_transaction_link,
    )


@finance_bp.route("/cash-bank-opening-balances", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def cash_bank_opening_balances():
    from datetime import datetime
    from app.extensions import db
    from app.models.finance import BankAccount, CashBankOpeningBalance
    from app.services.cash_bank_service import create_opening_balance

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    if request.method == "POST":
        account_type = (request.form.get("account_type") or "").strip().upper()
        bank_account_id = (request.form.get("bank_account_id") or "").strip() or None
        opening_date_raw = (request.form.get("opening_date") or "").strip()
        amount_raw = (request.form.get("amount") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            opening_date = datetime.strptime(opening_date_raw, "%Y-%m-%d").date()
            amount = _parse_payment_amount(amount_raw)
            opening, ledger_transaction = create_opening_balance(
                account_type=account_type,
                bank_account_id=bank_account_id,
                opening_date=opening_date,
                amount=amount,
                created_by=current_user.id,
                branch_id=current_user.branch_id,
                notes=notes,
                commit=False,
            )
            db.session.commit()
            record_audit_log(
                module="CASH_BANK",
                event_type="OPENING_BALANCE_CREATED",
                action="CREATE",
                table_name="cash_bank_opening_balances",
                record_id=opening.id,
                description="Saldo awal kas/bank dibuat.",
                metadata={"amount": amount, "account_type": account_type, "bank_account_id": bank_account_id, "ledger_transaction_id": ledger_transaction.id},
            )
            flash("Saldo awal kas/bank berhasil disimpan dan masuk ledger.", "success")
            return redirect(url_for("finance.cash_bank_opening_balances"))
        except Exception as error:
            db.session.rollback()
            flash(f"Gagal menyimpan saldo awal: {error}", "danger")

    openings = CashBankOpeningBalance.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(CashBankOpeningBalance.opening_date.desc(), CashBankOpeningBalance.id.desc()).all()

    return render_template(
        "finance/cash_bank_opening_balances.html",
        openings=openings,
        active_bank_accounts=active_bank_accounts,
    )


@finance_bp.route("/cash-bank-transfers", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def cash_bank_transfers():
    from datetime import datetime
    from app.extensions import db
    from app.models.finance import BankAccount, CashBankTransfer
    from app.services.cash_bank_service import create_cash_bank_transfer

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    if request.method == "POST":
        transfer_date_raw = (request.form.get("transfer_date") or "").strip()
        from_account_type = (request.form.get("from_account_type") or "").strip().upper()
        from_bank_account_id = (request.form.get("from_bank_account_id") or "").strip() or None
        to_account_type = (request.form.get("to_account_type") or "").strip().upper()
        to_bank_account_id = (request.form.get("to_bank_account_id") or "").strip() or None
        amount_raw = (request.form.get("amount") or "").strip()
        reference_number = (request.form.get("reference_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            transfer_date = datetime.strptime(transfer_date_raw, "%Y-%m-%d").date()
            amount = _parse_payment_amount(amount_raw)
            transfer, out_transaction, in_transaction = create_cash_bank_transfer(
                transfer_date=transfer_date,
                from_account_type=from_account_type,
                from_bank_account_id=from_bank_account_id,
                to_account_type=to_account_type,
                to_bank_account_id=to_bank_account_id,
                amount=amount,
                created_by=current_user.id,
                branch_id=current_user.branch_id,
                reference_number=reference_number,
                notes=notes,
                commit=False,
            )
            db.session.commit()
            record_audit_log(
                module="CASH_BANK",
                event_type="CASH_BANK_TRANSFER_CREATED",
                action="CREATE",
                table_name="cash_bank_transfers",
                record_id=transfer.id,
                description=f"Transfer kas/bank dibuat: {transfer.transfer_number}.",
                metadata={"amount": amount, "out_transaction_id": out_transaction.id, "in_transaction_id": in_transaction.id},
            )
            flash("Transfer antar kas/bank berhasil disimpan dan ledger IN/OUT dibuat.", "success")
            return redirect(url_for("finance.cash_bank_transfers"))
        except Exception as error:
            db.session.rollback()
            flash(f"Gagal menyimpan transfer kas/bank: {error}", "danger")

    transfers = CashBankTransfer.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(CashBankTransfer.transfer_date.desc(), CashBankTransfer.id.desc()).all()

    return render_template(
        "finance/cash_bank_transfers.html",
        transfers=transfers,
        active_bank_accounts=active_bank_accounts,
    )


@finance_bp.route("/cash-bank-adjustments", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def cash_bank_adjustments():
    from datetime import datetime
    from app.extensions import db
    from app.models.finance import BankAccount, CashBankAdjustment
    from app.services.cash_bank_service import create_cash_bank_adjustment

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    if request.method == "POST":
        adjustment_date_raw = (request.form.get("adjustment_date") or "").strip()
        account_type = (request.form.get("account_type") or "").strip().upper()
        bank_account_id = (request.form.get("bank_account_id") or "").strip() or None
        adjustment_type = (request.form.get("adjustment_type") or "").strip().upper()
        amount_raw = (request.form.get("amount") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            adjustment_date = datetime.strptime(adjustment_date_raw, "%Y-%m-%d").date()
            amount = _parse_payment_amount(amount_raw)
            adjustment, ledger_transaction = create_cash_bank_adjustment(
                adjustment_date=adjustment_date,
                account_type=account_type,
                bank_account_id=bank_account_id,
                adjustment_type=adjustment_type,
                amount=amount,
                reason=reason,
                created_by=current_user.id,
                branch_id=current_user.branch_id,
                notes=notes,
                commit=False,
            )
            db.session.commit()
            record_audit_log(
                module="CASH_BANK",
                event_type="CASH_BANK_ADJUSTMENT_CREATED",
                action="CREATE",
                table_name="cash_bank_adjustments",
                record_id=adjustment.id,
                description=f"Penyesuaian saldo dibuat: {adjustment.adjustment_number}.",
                metadata={"amount": amount, "adjustment_type": adjustment_type, "ledger_transaction_id": ledger_transaction.id},
            )
            flash("Penyesuaian saldo kas/bank berhasil disimpan dan masuk ledger.", "success")
            return redirect(url_for("finance.cash_bank_adjustments"))
        except Exception as error:
            db.session.rollback()
            flash(f"Gagal menyimpan penyesuaian saldo: {error}", "danger")

    adjustments = CashBankAdjustment.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(CashBankAdjustment.adjustment_date.desc(), CashBankAdjustment.id.desc()).all()

    return render_template(
        "finance/cash_bank_adjustments.html",
        adjustments=adjustments,
        active_bank_accounts=active_bank_accounts,
    )


@finance_bp.route("/cash-bank-ledger/<int:transaction_id>/reconcile", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def reconcile_cash_bank_ledger_transaction(transaction_id):
    from app.extensions import db
    from app.models.finance import CashBankTransaction
    from app.services.cash_bank_service import reconcile_cash_bank_transaction

    transaction = CashBankTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        flash("Transaksi kas/bank tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.cash_bank_ledger"))

    note = (request.form.get("reconciliation_note") or "").strip()

    try:
        reconcile_cash_bank_transaction(transaction, reconciled_by=current_user.id, note=note, commit=False)
        db.session.commit()
        record_audit_log(
            module="CASH_BANK",
            event_type="LEDGER_RECONCILED",
            action="UPDATE",
            table_name="cash_bank_transactions",
            record_id=transaction.id,
            description="Transaksi kas/bank ditandai sudah rekonsiliasi.",
            metadata={"note": note},
        )
        flash("Transaksi kas/bank berhasil ditandai sudah rekonsiliasi.", "success")
    except Exception as error:
        db.session.rollback()
        flash(f"Gagal rekonsiliasi transaksi kas/bank: {error}", "danger")

    return redirect(request.referrer or url_for("finance.cash_bank_ledger"))


@finance_bp.route("/cash-bank-ledger/<int:transaction_id>/unreconcile", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def unreconcile_cash_bank_ledger_transaction(transaction_id):
    from app.extensions import db
    from app.models.finance import CashBankTransaction
    from app.services.cash_bank_service import unreconcile_cash_bank_transaction

    transaction = CashBankTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        flash("Transaksi kas/bank tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.cash_bank_ledger"))

    try:
        unreconcile_cash_bank_transaction(transaction, commit=False)
        db.session.commit()
        record_audit_log(
            module="CASH_BANK",
            event_type="LEDGER_UNRECONCILED",
            action="UPDATE",
            table_name="cash_bank_transactions",
            record_id=transaction.id,
            description="Status rekonsiliasi transaksi kas/bank dibuka kembali.",
        )
        flash("Status rekonsiliasi transaksi kas/bank berhasil dibuka kembali.", "success")
    except Exception as error:
        db.session.rollback()
        flash(f"Gagal membuka rekonsiliasi transaksi kas/bank: {error}", "danger")

    return redirect(request.referrer or url_for("finance.cash_bank_ledger"))



# === PRODUCTION_AP_AGING_DETAIL_REPORTS ===
@finance_bp.route("/accounts-payable-aging")
@role_required("OWNER", "ADMIN", "FINANCE")
def accounts_payable_aging():
    from datetime import date, datetime
    from app.models.master import Supplier
    from app.services.accounts_payable_report_service import build_ap_aging_report

    as_of_raw = (request.args.get("as_of_date") or "").strip()
    supplier_id_raw = (request.args.get("supplier_id") or "").strip()

    try:
        as_of_date = datetime.strptime(as_of_raw, "%Y-%m-%d").date() if as_of_raw else date.today()
    except Exception:
        flash("Tanggal aging tidak valid. Sistem memakai tanggal hari ini.", "warning")
        as_of_date = date.today()

    supplier_id = None
    if supplier_id_raw:
        try:
            supplier_id = int(supplier_id_raw)
        except (TypeError, ValueError):
            supplier_id = None

    suppliers = Supplier.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(
        Supplier.supplier_name.asc(),
    ).all()

    report = build_ap_aging_report(
        branch_id=current_user.branch_id,
        as_of_date=as_of_date,
        supplier_id=supplier_id,
    )

    return render_template(
        "finance/accounts_payable_aging.html",
        report=report,
        suppliers=suppliers,
        selected_supplier_id=supplier_id,
        as_of_date=as_of_date,
    )


@finance_bp.route("/supplier-payable-card")
@role_required("OWNER", "ADMIN", "FINANCE")
def supplier_payable_card():
    from datetime import datetime
    from app.services.accounts_payable_report_service import build_supplier_payable_card

    supplier_key = (request.args.get("supplier_key") or "").strip() or None
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()

    start_date = None
    end_date = None

    try:
        if start_raw:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
    except Exception:
        flash("Tanggal awal kartu hutang tidak valid dan diabaikan.", "warning")
        start_date = None

    try:
        if end_raw:
            end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except Exception:
        flash("Tanggal akhir kartu hutang tidak valid dan diabaikan.", "warning")
        end_date = None

    if start_date and end_date and start_date > end_date:
        flash("Tanggal awal tidak boleh lebih besar dari tanggal akhir. Filter tanggal diabaikan.", "warning")
        start_date = None
        end_date = None

    report = build_supplier_payable_card(
        branch_id=current_user.branch_id,
        supplier_key=supplier_key,
        start_date=start_date,
        end_date=end_date,
    )

    return render_template(
        "finance/supplier_payable_card.html",
        report=report,
        selected_supplier_key=supplier_key,
        start_date=start_date,
        end_date=end_date,
    )

# === PRODUCTION_SUPPLIER_BILL_AP_ROUTES ===
@finance_bp.route("/supplier-bills")
@role_required("OWNER", "ADMIN", "FINANCE")
def supplier_bills():
    from datetime import date
    from app.models.finance import SupplierBill
    from app.services.accounts_payable_service import supplier_bill_aging_stage

    selected_filter = (request.args.get("filter") or "OPEN").strip().upper()
    allowed_filters = ["OPEN", "OVERDUE", "DUE_SOON", "ALL", "PAID"]
    date_filter = resolve_date_filter(request.args, default_preset="all")

    if selected_filter not in allowed_filters:
        selected_filter = "OPEN"

    bills_query = SupplierBill.query.filter_by(branch_id=current_user.branch_id)
    bills_query = apply_date_range_to_query(bills_query, SupplierBill.due_date, date_filter)

    bills = bills_query.order_by(
        SupplierBill.due_date.asc(),
        SupplierBill.id.desc()
    ).all()

    today = date.today()
    rows = []
    summary = {
        "total_open": 0,
        "open_count": 0,
        "overdue_total": 0,
        "overdue_count": 0,
        "due_soon_total": 0,
        "due_soon_count": 0,
        "paid_count": 0,
    }

    for bill in bills:
        aging = supplier_bill_aging_stage(bill, today)
        remaining = float(bill.remaining_amount or 0)

        if aging["stage"] != "PAID":
            summary["total_open"] += remaining
            summary["open_count"] += 1

        if aging["stage"] == "OVERDUE":
            summary["overdue_total"] += remaining
            summary["overdue_count"] += 1
        elif aging["stage"] == "DUE_SOON":
            summary["due_soon_total"] += remaining
            summary["due_soon_count"] += 1
        elif aging["stage"] == "PAID":
            summary["paid_count"] += 1

        show_row = False

        if selected_filter == "ALL":
            show_row = True
        elif selected_filter == "OPEN" and aging["stage"] != "PAID":
            show_row = True
        elif selected_filter == aging["stage"]:
            show_row = True

        if show_row:
            rows.append({
                "bill": bill,
                "aging": aging,
                "procurement": bill.procurement,
                "supplier": bill.supplier,
            })

    filter_options = [
        {"value": "OPEN", "label": "Belum Lunas"},
        {"value": "OVERDUE", "label": "Overdue"},
        {"value": "DUE_SOON", "label": "Segera Jatuh Tempo"},
        {"value": "PAID", "label": "Lunas"},
        {"value": "ALL", "label": "Semua"},
    ]

    return render_template(
        "finance/supplier_bills.html",
        rows=rows,
        summary=summary,
        selected_filter=selected_filter,
        filter_options=filter_options,
        today=today,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("finance.supplier_bills"),
            reset_url=url_for("finance.supplier_bills"),
            title="Filter Hutang Supplier",
            description="Custom tanggal jatuh tempo dan status hutang supplier.",
            status_name="filter",
            status_value=selected_filter,
            status_options=filter_options,
        ),
    )


@finance_bp.route("/supplier-bills/<int:bill_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def supplier_bill_detail(bill_id):
    from datetime import date
    from app.models.finance import BankAccount, CashBankTransaction, SupplierBill, SupplierPayment
    from app.models.accounting import Journal
    from app.models.logistics import StockMovement
    from app.services.accounts_payable_service import supplier_bill_aging_stage

    bill = SupplierBill.query.get_or_404(bill_id)

    if bill.branch_id != current_user.branch_id:
        flash("Data hutang supplier tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.supplier_bills"))

    procurement = bill.procurement
    journal = None
    stock_movements = []

    procurement_posting_status = None

    if procurement:
        journal = Journal.query.filter_by(
            reference_type="PROCUREMENT",
            reference_id=procurement.id,
        ).first()
        from app.services.accounting_posting_status_service import build_single_source_posting_status
        procurement_posting_status = build_single_source_posting_status("PROCUREMENT", procurement)

        stock_movements = StockMovement.query.filter_by(
            branch_id=current_user.branch_id,
            reference_type="PEMBELIAN_BARANG",
            reference_id=procurement.id,
        ).all()

    payments = SupplierPayment.query.filter_by(
        branch_id=current_user.branch_id,
        supplier_bill_id=bill.id,
    ).order_by(
        SupplierPayment.payment_date.desc(),
        SupplierPayment.id.desc(),
    ).all()

    payment_ids = [payment.id for payment in payments]
    journal_by_payment = {}
    ledger_by_payment = {}
    supplier_payment_attachments = {
        payment.id: list_reference_attachments(
            module=SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=payment.id,
            branch_id=current_user.branch_id,
        )
        for payment in payments
    }

    if payment_ids:
        journals = Journal.query.filter(
            Journal.reference_type == "SUPPLIER_PAYMENT",
            Journal.reference_id.in_(payment_ids),
        ).all()
        journal_by_payment = {row.reference_id: row for row in journals}

        ledgers = CashBankTransaction.query.filter(
            CashBankTransaction.branch_id == current_user.branch_id,
            CashBankTransaction.reference_type == "SUPPLIER_PAYMENT",
            CashBankTransaction.reference_id.in_(payment_ids),
        ).all()
        ledger_by_payment = {row.reference_id: row for row in ledgers}

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc(),
    ).all()

    return render_template(
        "finance/supplier_bill_detail.html",
        bill=bill,
        procurement=procurement,
        supplier=bill.supplier,
        journal=journal,
        procurement_posting_status=procurement_posting_status,
        stock_movements=stock_movements,
        payments=payments,
        journal_by_payment=journal_by_payment,
        ledger_by_payment=ledger_by_payment,
        active_bank_accounts=active_bank_accounts,
        today_date=date.today().isoformat(),
        aging=supplier_bill_aging_stage(bill, date.today()),
        supplier_payment_attachments=supplier_payment_attachments,
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


@finance_bp.route("/supplier-bills/<int:bill_id>/payments/create", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_supplier_bill_payment(bill_id):
    from datetime import datetime
    from app.extensions import db
    from app.models.finance import BankAccount, SupplierBill
    from app.models.accounting import Journal
    from app.services.accounts_payable_service import create_supplier_payment_for_bill
    from app.services.accounting_service import create_supplier_payment_journal_for_payment
    from app.services.cash_bank_service import create_supplier_payment_cash_bank_transaction

    bill = SupplierBill.query.get_or_404(bill_id)

    if bill.branch_id != current_user.branch_id:
        flash("Data hutang supplier tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.supplier_bills"))

    if float(bill.remaining_amount or 0) <= 0 or str(bill.status or "").upper() == "PAID":
        flash("Supplier bill ini sudah lunas.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    procurement_journal = Journal.query.filter_by(
        reference_type="PROCUREMENT",
        reference_id=bill.procurement_id,
    ).first()

    if not procurement_journal:
        flash("Jurnal pembelian sumber belum ada. Sinkronkan jurnal pembelian dulu sebelum membayar hutang supplier.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    payment_date_raw = (request.form.get("payment_date") or "").strip()
    payment_method = (request.form.get("payment_method") or "").strip().upper()
    bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    reference_number = (request.form.get("reference_number") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    try:
        payment_date = datetime.strptime(payment_date_raw, "%Y-%m-%d").date()
    except Exception:
        flash("Tanggal pembayaran hutang supplier tidak valid.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    if payment_date > datetime.now().date():
        flash("Tanggal pembayaran hutang supplier tidak boleh lebih dari hari ini.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    if payment_method not in ["CASH", "TRANSFER"]:
        flash("Metode pembayaran hutang supplier tidak valid.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    bank_account_id = None

    if payment_method == "TRANSFER":
        if not bank_account_id_raw:
            flash("Pembayaran supplier via transfer wajib memilih rekening bank keluar.", "warning")
            return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

        try:
            bank_account_id = int(bank_account_id_raw)
        except (TypeError, ValueError):
            flash("Rekening bank keluar tidak valid.", "warning")
            return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=current_user.branch_id,
            is_active=True,
        ).first()

        if not bank_account:
            flash("Rekening bank keluar tidak ditemukan atau tidak aktif.", "warning")
            return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    try:
        amount = _parse_payment_amount(amount_raw)
    except Exception:
        flash("Nominal pembayaran hutang supplier tidak valid.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    try:
        proof_file = request.files.get("proof_file")
        proof_uploaded = False

        with atomic_business_action(
            module="FINANCE",
            action="SUPPLIER_PAYMENT_CREATE",
            description=f"Create payment supplier bill {bill.bill_number} + jurnal + ledger + bukti secara atomic.",
            reference_type="supplier_payments",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"supplier_bill_id": bill.id, "amount": amount, "method": payment_method},
        ) as atomic:
            _, _, supplier_payment = create_supplier_payment_for_bill(
                bill=bill,
                payment_date=payment_date,
                payment_method=payment_method,
                amount=amount,
                paid_by=current_user.id,
                bank_account_id=bank_account_id,
                reference_number=reference_number,
                notes=notes,
                commit=False,
            )

            db.session.flush()

            create_supplier_payment_journal_for_payment(
                supplier_payment=supplier_payment,
                created_by=current_user.id,
                commit=False,
            )

            create_supplier_payment_cash_bank_transaction(
                supplier_payment=supplier_payment,
                created_by=current_user.id,
                commit=False,
            )

            db.session.flush()

            if proof_file and proof_file.filename:
                attachment = save_digital_attachment(
                    file_storage=proof_file,
                    module=SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
                    reference_type=SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
                    reference_id=supplier_payment.id,
                    attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_SUPPLIER",
                    branch_id=current_user.branch_id,
                    uploaded_by=current_user.id,
                    notes=request.form.get("proof_notes") or None,
                    commit=False,
                )
                atomic.track_attachment(attachment)
                proof_uploaded = True
                record_audit_log(
                    module="ATTACHMENT",
                    event_type="DIGITAL_ATTACHMENT_UPLOADED",
                    action="CREATE",
                    table_name="digital_attachments",
                    record_id=attachment.id,
                    description=f"Lampiran payment supplier diunggah secara atomic untuk {supplier_payment.payment_number}.",
                    metadata={
                        "module": SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
                        "reference_type": SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
                        "reference_id": supplier_payment.id,
                        "attachment_type": attachment.attachment_type,
                        "original_filename": attachment.original_filename,
                        "file_size": attachment.file_size,
                        "sha256": attachment.sha256_hash,
                        "atomic_guard": "PRODUCTION",
                    },
                    commit=False,
                )

        record_audit_log(
            module="FINANCE",
            event_type="SUPPLIER_PAYMENT_CREATED",
            action="CREATE",
            table_name="supplier_payments",
            record_id=supplier_payment.id,
            description=f"Pembayaran hutang supplier dicatat atomic: {supplier_payment.payment_number}.",
            metadata={"supplier_bill_id": bill.id, "amount": supplier_payment.amount, "method": supplier_payment.payment_method, "atomic_guard": "PRODUCTION"},
        )

        if proof_uploaded:
            flash("Bukti transfer/payment supplier berhasil diunggah dalam transaksi atomic.", "success")

        flash("Pembayaran hutang supplier berhasil disimpan, jurnal otomatis dicatat, dan ledger kas/bank OUT dibuat.", "success")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    except Exception as error:
        db.session.rollback()
        flash(f"Gagal menyimpan pembayaran hutang supplier: {error}", "danger")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))


@finance_bp.route("/supplier-payments/<int:payment_id>/attachments/upload", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def upload_supplier_payment_attachment(payment_id):
    supplier_payment = _supplier_payment_or_404(payment_id)

    proof_file = request.files.get("proof_file")
    try:
        save_digital_attachment(
            file_storage=proof_file,
            module=SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=supplier_payment.id,
            attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_SUPPLIER",
            branch_id=current_user.branch_id,
            uploaded_by=current_user.id,
            notes=request.form.get("proof_notes") or None,
        )
        flash("Bukti transfer/payment supplier berhasil diunggah.", "success")
    except AttachmentValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"Bukti transfer/payment supplier gagal diunggah: {exc}", "danger")

    return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))


@finance_bp.route("/supplier-payments/attachments/<int:attachment_id>/view")
@role_required("OWNER", "ADMIN", "FINANCE")
def view_supplier_payment_attachment(attachment_id):
    attachment, supplier_payment = _supplier_payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        flash(f"File bukti payment supplier tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))

    return send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/supplier-payments/attachments/<int:attachment_id>/download")
@role_required("OWNER", "ADMIN", "FINANCE")
def download_supplier_payment_attachment(attachment_id):
    attachment, supplier_payment = _supplier_payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        flash(f"File bukti payment supplier tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/supplier-payments/attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def delete_supplier_payment_attachment(attachment_id):
    attachment, supplier_payment = _supplier_payment_attachment_or_404(attachment_id)
    note = (request.form.get("delete_note") or "Bukti payment supplier salah upload.").strip()
    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    flash("Bukti payment supplier berhasil dihapus lunak. File fisik tetap tersimpan untuk audit.", "success")
    return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))



# === PRODUCTION_UNIFIED_FINANCE_TRANSACTION_INPUT ===
@finance_bp.route("/transactions", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def finance_transactions():
    """Unified finance transaction entry.

    This page intentionally consolidates the daily finance posting flows that used
    to be separated in the sidebar: DP/advance, transport/BBM, and operational
    expense. It does not replace invoice/AP/asset/closing workflows because those
    have their own business documents and controls.
    """
    from datetime import date, datetime
    from app.extensions import db
    from app.models.delivery import Delivery
    from app.models.finance import BankAccount
    from app.models.master import Client, Driver, Mandor, Supplier
    from app.services.advance_service import (
        get_advance_type_choices,
        is_advance_schema_ready,
        create_advance_transaction,
    )
    from app.services.operational_expense_service import (
        get_operational_expense_category_choices,
        is_operational_expense_schema_ready,
        create_operational_expense,
    )
    from app.services.transport_expense_service import (
        get_transport_expense_type_choices,
        is_transport_expense_schema_ready,
        create_transport_vehicle_expense,
    )

    schema_ready = {
        "advance": is_advance_schema_ready(),
        "transport": is_transport_expense_schema_ready(),
        "operational": is_operational_expense_schema_ready(),
    }

    def _to_int(value):
        try:
            return int(value) if value not in (None, "") else None
        except Exception:
            return None

    if request.method == "POST":
        transaction_kind = (request.form.get("transaction_kind") or "").strip().upper()
        transaction_date_raw = (request.form.get("transaction_date") or "").strip()
        amount_raw = (request.form.get("amount") or "").strip()
        payment_method = (request.form.get("payment_method") or "").strip().upper()
        bank_account_id = _to_int((request.form.get("bank_account_id") or "").strip())
        reference_number = (request.form.get("reference_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            transaction_date = datetime.strptime(transaction_date_raw, "%Y-%m-%d").date()
        except Exception:
            flash("Tanggal transaksi tidak valid.", "warning")
            return redirect(url_for("finance.finance_transactions", tx=transaction_kind.lower()))

        try:
            amount = _parse_payment_amount(amount_raw)
        except Exception:
            flash("Nominal transaksi tidak valid.", "warning")
            return redirect(url_for("finance.finance_transactions", tx=transaction_kind.lower()))

        try:
            if transaction_kind == "ADVANCE":
                if not schema_ready["advance"]:
                    raise Exception("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
                ok, message, advance = create_advance_transaction(
                    branch_id=current_user.branch_id,
                    advance_date=transaction_date,
                    advance_type=(request.form.get("advance_type") or "").strip().upper(),
                    payment_method=payment_method,
                    amount=amount,
                    created_by=current_user.id,
                    client_id=_to_int(request.form.get("advance_client_id")),
                    supplier_id=_to_int(request.form.get("advance_supplier_id")),
                    mandor_id=_to_int(request.form.get("advance_mandor_id")),
                    bank_account_id=bank_account_id,
                    reference_number=reference_number,
                    notes=notes,
                    commit=False,
                )
                db.session.commit()
                flash("Transaksi DP/uang muka berhasil diposting dari input terpadu.", "success")
                return redirect(url_for("finance.advance_detail", advance_id=advance.id))

            if transaction_kind == "TRANSPORT":
                if not schema_ready["transport"]:
                    raise Exception("Tabel transport/BBM belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
                ok, message, expense = create_transport_vehicle_expense(
                    branch_id=current_user.branch_id,
                    expense_date=transaction_date,
                    expense_type=(request.form.get("transport_expense_type") or "").strip().upper(),
                    payment_method=payment_method,
                    amount=amount,
                    created_by=current_user.id,
                    vehicle_label=(request.form.get("vehicle_label") or "").strip(),
                    driver_id=_to_int(request.form.get("driver_id")),
                    delivery_id=_to_int(request.form.get("delivery_id")),
                    bank_account_id=bank_account_id,
                    vendor_name=(request.form.get("transport_vendor_name") or "").strip(),
                    reference_number=reference_number,
                    notes=notes,
                    commit=False,
                )
                db.session.commit()
                flash("Transaksi transport/BBM berhasil diposting dari input terpadu.", "success")
                return redirect(url_for("finance.transport_expense_detail", expense_id=expense.id))

            if transaction_kind == "OPERATIONAL_EXPENSE":
                if not schema_ready["operational"]:
                    raise Exception("Tabel biaya operasional belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
                ok, message, expense = create_operational_expense(
                    branch_id=current_user.branch_id,
                    expense_date=transaction_date,
                    expense_category=(request.form.get("operational_expense_category") or "").strip().upper(),
                    payment_method=payment_method,
                    amount=amount,
                    created_by=current_user.id,
                    bank_account_id=bank_account_id,
                    supplier_id=_to_int(request.form.get("operational_supplier_id")),
                    vendor_name=(request.form.get("operational_vendor_name") or "").strip(),
                    reference_number=reference_number,
                    notes=notes,
                    commit=False,
                )
                db.session.commit()
                flash("Transaksi biaya operasional berhasil diposting dari input terpadu.", "success")
                return redirect(url_for("finance.operational_expense_detail", expense_id=expense.id))

            flash("Jenis transaksi belum dipilih atau belum didukung input terpadu.", "warning")
            return redirect(url_for("finance.finance_transactions"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("finance.finance_transactions", tx=transaction_kind.lower()))

    selected_tx = (request.args.get("tx") or "advance").strip().lower()
    if selected_tx not in {"advance", "transport", "operational_expense"}:
        selected_tx = "advance"

    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    suppliers = Supplier.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all()
    mandors = Mandor.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Mandor.name.asc()).all()
    drivers = Driver.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Driver.name.asc()).all()
    deliveries = Delivery.query.filter_by(branch_id=current_user.branch_id).order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(80).all()

    return render_template(
        "finance/transactions.html",
        today_date=date.today().isoformat(),
        selected_tx=selected_tx,
        schema_ready=schema_ready,
        bank_accounts=bank_accounts,
        clients=clients,
        suppliers=suppliers,
        mandors=mandors,
        drivers=drivers,
        deliveries=deliveries,
        advance_type_choices=get_advance_type_choices(),
        transport_expense_type_choices=get_transport_expense_type_choices(),
        operational_expense_category_choices=get_operational_expense_category_choices(),
    )


@finance_bp.route("/manual-billing", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def manual_billing():
    from datetime import date
    from app.models.finance import ManualBillingBatch
    from app.models.master import Mandor
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import get_manual_backfill_status_context, get_manual_backfill_bill_to_context
    from app.services.manual_billing_service import (
        collect_manual_billing_candidates,
        get_active_client_pics_for_mandor,
    )

    today_value = date.today().isoformat()
    selected_mandor_id = (request.form.get("mandor_id") if request.method == "POST" else request.args.get("mandor_id")) or ""
    period_start_value = (request.form.get("period_start") if request.method == "POST" else request.args.get("period_start")) or today_value
    period_end_value = (request.form.get("period_end") if request.method == "POST" else request.args.get("period_end")) or today_value

    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()

    selected_mandor = None
    client_pics = []
    preview = {
        "rows": [],
        "blocked_rows": [],
        "total_amount": 0,
        "manual_receivable_total": 0,
        "warung_total": 0,
    }
    preview_ready = False

    if selected_mandor_id:
        period_start = _period_parse_date(period_start_value)
        period_end = _period_parse_date(period_end_value)
        try:
            selected_mandor_id_int = int(selected_mandor_id)
        except (TypeError, ValueError):
            selected_mandor_id_int = None
        if not period_start or not period_end:
            flash("Periode rekap tagihan mandor tidak valid.", "warning")
        elif period_start > period_end:
            flash("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.", "warning")
        elif not selected_mandor_id_int:
            flash("Mandor/PIC lapangan tidak valid.", "warning")
        else:
            selected_mandor = Mandor.query.filter_by(
                id=selected_mandor_id_int,
                branch_id=current_user.branch_id,
            ).first()
            if not selected_mandor:
                flash("Mandor/PIC lapangan tidak ditemukan.", "warning")
            elif not getattr(selected_mandor, "client", None):
                flash("Mandor/PIC lapangan belum terhubung ke client/perusahaan.", "warning")
            else:
                preview = collect_manual_billing_candidates(
                    branch_id=current_user.branch_id,
                    mandor_id=selected_mandor.id,
                    period_start=period_start,
                    period_end=period_end,
                )
                client_pics = get_active_client_pics_for_mandor(selected_mandor)
                preview_ready = True
                if not client_pics:
                    flash("Client belum punya PIC resmi aktif. Tambahkan PIC di Master Client sebelum membuat invoice.", "warning")

    manual_backfill_batches = ManualBillingBatch.query.filter_by(
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).order_by(ManualBillingBatch.id.desc()).limit(10).all()

    return render_template(
        "finance/manual_billing.html",
        mandors=mandors,
        selected_mandor_id=str(selected_mandor_id or ""),
        selected_mandor=selected_mandor,
        client_pics=client_pics,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        preview=preview,
        preview_ready=preview_ready,
        manual_backfill_batches=manual_backfill_batches,
        get_manual_backfill_status_context=get_manual_backfill_status_context,
        get_manual_backfill_bill_to_context=get_manual_backfill_bill_to_context,
    )


def _pad_manual_backfill_rows(rows, minimum):
    rows = list(rows or [])
    while len(rows) < minimum:
        rows.append({})
    return rows


def _manual_backfill_period_dates(period_start_value, period_end_value):
    from datetime import timedelta

    period_start = _period_parse_date(period_start_value) if period_start_value else None
    period_end = _period_parse_date(period_end_value) if period_end_value else None
    if not period_start or not period_end or period_start > period_end:
        return []

    # Keep the generated table bounded so an accidental multi-year range does not
    # make the browser unusable. Backend validation still owns final truth.
    dates = []
    current = period_start
    for _ in range(370):
        if current > period_end:
            break
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _manual_backfill_catering_rows_for_period(period_start_value, period_end_value, existing_rows=None, minimum=1):
    existing_rows = list(existing_rows or [])
    by_date = {str(row.get("date") or ""): row for row in existing_rows if row.get("date")}
    used_dates = set()
    rows = []

    for iso_date in _manual_backfill_period_dates(period_start_value, period_end_value):
        row = dict(by_date.get(iso_date) or {})
        row["date"] = iso_date
        rows.append(row)
        used_dates.add(iso_date)

    # Preserve manual adjustment rows outside the period or without date, especially
    # after a failed POST/edit. JavaScript can still add/remove rows in the browser.
    for row in existing_rows:
        row_date = str(row.get("date") or "")
        if not row_date or row_date not in used_dates:
            rows.append(row)

    return _pad_manual_backfill_rows(rows, minimum)


def _manual_backfill_request_catering_rows(minimum=1):
    dates = request.form.getlist("catering_date[]")
    breakfast_qtys = request.form.getlist("catering_breakfast_qty[]")
    lunch_qtys = request.form.getlist("catering_lunch_qty[]")
    dinner_qtys = request.form.getlist("catering_dinner_qty[]")
    unit_prices = request.form.getlist("catering_unit_price[]")
    notes = request.form.getlist("catering_note[]")
    max_len = max(len(dates), len(breakfast_qtys), len(lunch_qtys), len(dinner_qtys), len(unit_prices), len(notes), minimum)
    return [
        {
            "date": dates[index] if index < len(dates) else "",
            "breakfast_qty": breakfast_qtys[index] if index < len(breakfast_qtys) else "",
            "lunch_qty": lunch_qtys[index] if index < len(lunch_qtys) else "",
            "dinner_qty": dinner_qtys[index] if index < len(dinner_qtys) else "",
            "unit_price": unit_prices[index] if index < len(unit_prices) else "",
            "note": notes[index] if index < len(notes) else "",
        }
        for index in range(max_len)
    ]


def _manual_backfill_request_warung_rows(minimum=8):
    worker_names = request.form.getlist("warung_worker_name[]")
    amounts = request.form.getlist("warung_amount[]")
    notes = request.form.getlist("warung_note[]")
    max_len = max(len(worker_names), len(amounts), len(notes), minimum)
    return [
        {
            "worker_name": worker_names[index] if index < len(worker_names) else "",
            "amount": amounts[index] if index < len(amounts) else "",
            "note": notes[index] if index < len(notes) else "",
        }
        for index in range(max_len)
    ]


def _number_for_form(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0
    if value == int(value):
        return str(int(value))
    return (f"{value:.2f}").rstrip("0").rstrip(".")


def _manual_backfill_existing_catering_rows(batch, minimum=14):
    import re

    rows = []
    for item in getattr(batch, "items", []) or []:
        if getattr(item, "item_type", None) != "CATERING":
            continue
        description = str(getattr(item, "description", "") or "")
        breakfast_qty = 0
        lunch_qty = getattr(item, "qty", 0) or 0
        dinner_qty = 0
        meal_match = re.search(
            r"(?:Sarapan\s+([0-9.,]+)\s*\|\s*)?Siang\s+([0-9.,]+)\s*\|\s*Sore\s+([0-9.,]+)",
            description,
            flags=re.I,
        )
        if meal_match:
            breakfast_qty = meal_match.group(1) or 0
            lunch_qty = meal_match.group(2)
            dinner_qty = meal_match.group(3)
        parts = [part.strip() for part in description.split("|")]
        note_start = 5 if any(part.lower().startswith("total ") for part in parts[:5]) else 4
        note = " | ".join(parts[note_start:]).strip() if len(parts) > note_start else ""
        source_date = getattr(item, "source_date", None)
        rows.append({
            "date": source_date.isoformat() if source_date else "",
            "breakfast_qty": breakfast_qty,
            "lunch_qty": lunch_qty,
            "dinner_qty": dinner_qty,
            "unit_price": _number_for_form(getattr(item, "unit_price", 0)),
            "note": note,
        })
    return _pad_manual_backfill_rows(rows, minimum)


def _manual_backfill_existing_warung_rows(batch, minimum=8):
    rows = []
    prefix = "Kasbon/hutang warung pekerja "
    for item in getattr(batch, "items", []) or []:
        if getattr(item, "item_type", None) != "WARUNG_DEBT":
            continue
        description = str(getattr(item, "description", "") or "")
        parts = [part.strip() for part in description.split("|")]
        worker_name = str(getattr(item, "source_label", "") or "").strip()
        if not worker_name and parts:
            worker_name = parts[0]
            if worker_name.startswith(prefix):
                worker_name = worker_name[len(prefix):].strip()
        note = " | ".join(parts[1:]).strip() if len(parts) > 1 else ""
        rows.append({
            "worker_name": worker_name,
            "amount": _number_for_form(getattr(item, "unit_price", None) or getattr(item, "subtotal", 0)),
            "note": note,
        })
    return _pad_manual_backfill_rows(rows, minimum)


@finance_bp.route("/manual-billing/batches")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def manual_billing_batches_list():
    """Register semua rekap manual dari buku dengan filter operasional.

    Halaman ini hanya membaca lane MANUAL_BACKFILL. Tidak mengubah alur REALTIME.
    """
    from sqlalchemy import or_
    from app.models.finance import ManualBillingBatch
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import (
        build_manual_backfill_register_summary,
        get_manual_backfill_bill_to_context,
        get_manual_backfill_bill_to_filter_choices,
        get_manual_backfill_status_context,
        get_manual_backfill_status_filter_choices,
        normalize_manual_backfill_bill_to_filter,
        normalize_manual_backfill_status_filter,
    )

    status_filter = normalize_manual_backfill_status_filter(request.args.get("status"))
    bill_to_type_filter = normalize_manual_backfill_bill_to_filter(request.args.get("bill_to_type"))
    q = (request.args.get("q") or "").strip()
    period_start_value = (request.args.get("period_start") or "").strip()
    period_end_value = (request.args.get("period_end") or "").strip()
    period_start = _period_parse_date(period_start_value) if period_start_value else None
    period_end = _period_parse_date(period_end_value) if period_end_value else None

    if period_start_value and not period_start:
        flash("Tanggal mulai filter rekap manual tidak valid.", "warning")
        period_start_value = ""
    if period_end_value and not period_end:
        flash("Tanggal selesai filter rekap manual tidak valid.", "warning")
        period_end_value = ""
    if period_start and period_end and period_start > period_end:
        flash("Tanggal mulai filter tidak boleh lebih besar dari tanggal selesai.", "warning")
        period_start, period_end = period_end, period_start
        period_start_value, period_end_value = period_start.isoformat(), period_end.isoformat()

    query = ManualBillingBatch.query.filter_by(
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    )

    if status_filter:
        query = query.filter(ManualBillingBatch.status == status_filter)
    if bill_to_type_filter:
        legacy_bill_to_types = {
            "MANDOR_EXISTING": ["MANDOR_EXISTING", "MANDOR"],
            "CLIENT_EXISTING": ["CLIENT_EXISTING", "CLIENT"],
        }
        query = query.filter(ManualBillingBatch.bill_to_type.in_(
            legacy_bill_to_types.get(bill_to_type_filter, [bill_to_type_filter])
        ))
    if period_start:
        query = query.filter(ManualBillingBatch.period_end >= period_start)
    if period_end:
        query = query.filter(ManualBillingBatch.period_start <= period_end)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            ManualBillingBatch.batch_number.ilike(like),
            ManualBillingBatch.bill_to_name_snapshot.ilike(like),
            ManualBillingBatch.bill_to_phone_snapshot.ilike(like),
            ManualBillingBatch.notes.ilike(like),
        ))

    batches = query.order_by(ManualBillingBatch.id.desc()).limit(300).all()

    return render_template(
        "finance/manual_billing_batches.html",
        batches=batches,
        summary=build_manual_backfill_register_summary(batches),
        status_choices=get_manual_backfill_status_filter_choices(),
        bill_to_type_choices=get_manual_backfill_bill_to_filter_choices(),
        selected_status=status_filter,
        selected_bill_to_type=bill_to_type_filter,
        q=q,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        get_manual_backfill_status_context=get_manual_backfill_status_context,
        get_manual_backfill_bill_to_context=get_manual_backfill_bill_to_context,
    )


@finance_bp.route("/manual-billing/input-buku", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def manual_billing_backfill_form():
    """Input old/manual book recap as a MANUAL_BACKFILL draft batch.

    This is the second input path. It must not change the realtime order flow and
    it must not create invoice/piutang yet; later roadmap stages will lock and
    promote these batches.
    """
    from datetime import date
    from app.extensions import db
    from app.models.master import Mandor
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        build_catering_backfill_rows,
        build_warung_backfill_rows,
        create_manual_backfill_batch,
    )

    today_value = date.today().isoformat()
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()
    clients = Client.query.filter_by(
        is_active=True,
    ).order_by(Client.name.asc()).all()

    default_warung_rows = 8
    form_values = {
        "bill_to_type": request.form.get("bill_to_type", "MANDOR_EXISTING"),
        "mandor_id": request.form.get("mandor_id", ""),
        "client_id": request.form.get("client_id", ""),
        "bill_to_name_snapshot": request.form.get("bill_to_name_snapshot", ""),
        "bill_to_phone_snapshot": request.form.get("bill_to_phone_snapshot", ""),
        "bill_to_address_snapshot": request.form.get("bill_to_address_snapshot", ""),
        "bill_to_notes": request.form.get("bill_to_notes", ""),
        "period_start": request.form.get("period_start", today_value),
        "period_end": request.form.get("period_end", today_value),
        "notes": request.form.get("notes", ""),
    }
    default_rows = max(len(_manual_backfill_period_dates(form_values["period_start"], form_values["period_end"])), 1)
    catering_form_rows = (
        _manual_backfill_request_catering_rows(default_rows)
        if request.method == "POST"
        else _manual_backfill_catering_rows_for_period(form_values["period_start"], form_values["period_end"], minimum=default_rows)
    )
    warung_form_rows = _manual_backfill_request_warung_rows(default_warung_rows) if request.method == "POST" else _pad_manual_backfill_rows([], default_warung_rows)

    if request.method == "POST":
        try:
            catering_rows = build_catering_backfill_rows(
                request.form.getlist("catering_date[]"),
                request.form.getlist("catering_lunch_qty[]"),
                request.form.getlist("catering_dinner_qty[]"),
                request.form.getlist("catering_unit_price[]"),
                request.form.getlist("catering_note[]"),
                request.form.getlist("catering_breakfast_qty[]"),
            )
            warung_rows = build_warung_backfill_rows(
                request.form.getlist("warung_worker_name[]"),
                request.form.getlist("warung_amount[]"),
                request.form.getlist("warung_note[]"),
            )
            batch = create_manual_backfill_batch(
                branch_id=current_user.branch_id,
                bill_to_type=form_values["bill_to_type"],
                mandor_id=form_values["mandor_id"],
                client_id=form_values["client_id"],
                bill_to_name_snapshot=form_values["bill_to_name_snapshot"],
                bill_to_phone_snapshot=form_values["bill_to_phone_snapshot"],
                bill_to_address_snapshot=form_values["bill_to_address_snapshot"],
                bill_to_notes=form_values["bill_to_notes"],
                period_start=form_values["period_start"],
                period_end=form_values["period_end"],
                catering_rows=catering_rows,
                warung_rows=warung_rows,
                notes=form_values["notes"],
                created_by=current_user.id,
            )
            db.session.commit()
            flash(f"Input rekap manual dari buku {batch.batch_number} berhasil disimpan sebagai draft.", "success")
            return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch.id))
        except ManualBackfillBillingError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
        except Exception as exc:
            db.session.rollback()
            flash(f"Gagal menyimpan input rekap manual dari buku: {exc}", "danger")

    return render_template(
        "finance/manual_billing_backfill_form.html",
        mandors=mandors,
        clients=clients,
        form_values=form_values,
        catering_form_rows=catering_form_rows,
        warung_form_rows=warung_form_rows,
        default_rows=default_rows,
        default_warung_rows=default_warung_rows,
        action_url=url_for("finance.manual_billing_backfill_form"),
        page_title="Input Rekap Manual dari Buku",
        page_subtitle="Jalur tambahan untuk memasukkan rekap lama/buku manual. Ini tidak mengubah alur realtime order harian.",
        mode_badge="Input Belakangan",
        form_confirm="Simpan rekap manual dari buku sebagai draft?",
        submit_heading="Simpan Draft Rekap Manual",
        submit_help="Draft ini belum menjadi invoice/piutang. Setelah tersimpan, cek detail lalu kunci rekap jika total sudah benar.",
        submit_label="Simpan Draft",
        submit_icon="bi-save",
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>/edit", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def edit_manual_billing_backfill_batch(batch_id):
    from app.extensions import db
    from app.models.finance import ManualBillingBatch
    from app.models.master import Mandor
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_DRAFT,
        ManualBackfillBillingError,
        build_catering_backfill_rows,
        build_warung_backfill_rows,
        update_manual_backfill_batch,
    )

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).first_or_404()

    if batch.status != MANUAL_BACKFILL_STATUS_DRAFT or batch.invoice_id:
        flash("Hanya draft rekap manual yang belum memiliki invoice yang bisa diedit.", "warning")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch.id))

    default_warung_rows = 8
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()
    clients = Client.query.filter_by(
        is_active=True,
    ).order_by(Client.name.asc()).all()

    if request.method == "POST":
        form_values = {
            "bill_to_type": request.form.get("bill_to_type", "MANDOR_EXISTING"),
            "mandor_id": request.form.get("mandor_id", ""),
            "client_id": request.form.get("client_id", ""),
            "bill_to_name_snapshot": request.form.get("bill_to_name_snapshot", ""),
            "bill_to_phone_snapshot": request.form.get("bill_to_phone_snapshot", ""),
            "bill_to_address_snapshot": request.form.get("bill_to_address_snapshot", ""),
            "bill_to_notes": request.form.get("bill_to_notes", ""),
            "period_start": request.form.get("period_start", ""),
            "period_end": request.form.get("period_end", ""),
            "notes": request.form.get("notes", ""),
        }
        default_rows = max(len(_manual_backfill_period_dates(form_values["period_start"], form_values["period_end"])), 1)
        catering_form_rows = _manual_backfill_request_catering_rows(default_rows)
        warung_form_rows = _manual_backfill_request_warung_rows(default_warung_rows)
        try:
            catering_rows = build_catering_backfill_rows(
                request.form.getlist("catering_date[]"),
                request.form.getlist("catering_lunch_qty[]"),
                request.form.getlist("catering_dinner_qty[]"),
                request.form.getlist("catering_unit_price[]"),
                request.form.getlist("catering_note[]"),
                request.form.getlist("catering_breakfast_qty[]"),
            )
            warung_rows = build_warung_backfill_rows(
                request.form.getlist("warung_worker_name[]"),
                request.form.getlist("warung_amount[]"),
                request.form.getlist("warung_note[]"),
            )
            updated_batch = update_manual_backfill_batch(
                batch_id=batch.id,
                branch_id=current_user.branch_id,
                bill_to_type=form_values["bill_to_type"],
                mandor_id=form_values["mandor_id"],
                client_id=form_values["client_id"],
                bill_to_name_snapshot=form_values["bill_to_name_snapshot"],
                bill_to_phone_snapshot=form_values["bill_to_phone_snapshot"],
                bill_to_address_snapshot=form_values["bill_to_address_snapshot"],
                bill_to_notes=form_values["bill_to_notes"],
                period_start=form_values["period_start"],
                period_end=form_values["period_end"],
                catering_rows=catering_rows,
                warung_rows=warung_rows,
                notes=form_values["notes"],
                updated_by=current_user.id,
                commit=False,
            )
            db.session.commit()
            flash(f"Draft rekap manual {updated_batch.batch_number} berhasil diperbarui.", "success")
            return redirect(url_for("finance.manual_billing_batch_detail", batch_id=updated_batch.id))
        except ManualBackfillBillingError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
        except Exception as exc:
            db.session.rollback()
            flash(f"Gagal memperbarui draft rekap manual dari buku: {exc}", "danger")
    else:
        selected_bill_to_type = batch.bill_to_type or "MANDOR_EXISTING"
        if selected_bill_to_type == "MANDOR":
            selected_bill_to_type = "MANDOR_EXISTING"
        elif selected_bill_to_type == "CLIENT":
            selected_bill_to_type = "CLIENT_EXISTING"
        form_values = {
            "bill_to_type": selected_bill_to_type,
            "mandor_id": str(batch.mandor_id or ""),
            "client_id": str(batch.client_id or ""),
            "bill_to_name_snapshot": batch.bill_to_name_snapshot or "",
            "bill_to_phone_snapshot": batch.bill_to_phone_snapshot or "",
            "bill_to_address_snapshot": batch.bill_to_address_snapshot or "",
            "bill_to_notes": batch.bill_to_notes or "",
            "period_start": batch.period_start.isoformat() if batch.period_start else "",
            "period_end": batch.period_end.isoformat() if batch.period_end else "",
            "notes": batch.notes or "",
        }
        existing_catering_rows = _manual_backfill_existing_catering_rows(batch, minimum=0)
        default_rows = max(len(_manual_backfill_period_dates(form_values["period_start"], form_values["period_end"])), len(existing_catering_rows), 1)
        catering_form_rows = _manual_backfill_catering_rows_for_period(
            form_values["period_start"],
            form_values["period_end"],
            existing_catering_rows,
            minimum=default_rows,
        )
        warung_form_rows = _manual_backfill_existing_warung_rows(batch, default_warung_rows)

    return render_template(
        "finance/manual_billing_backfill_form.html",
        mandors=mandors,
        clients=clients,
        form_values=form_values,
        catering_form_rows=catering_form_rows,
        warung_form_rows=warung_form_rows,
        default_rows=default_rows,
        default_warung_rows=default_warung_rows,
        action_url=url_for("finance.edit_manual_billing_backfill_batch", batch_id=batch.id),
        page_title=f"Edit Draft Rekap Manual {batch.batch_number}",
        page_subtitle="Edit hanya diizinkan saat rekap masih Draft dan belum dibuat invoice/piutang.",
        mode_badge="Edit Draft",
        form_confirm="Simpan perubahan draft rekap manual ini?",
        submit_heading="Simpan Perubahan Draft",
        submit_help="Perubahan hanya berlaku pada draft. Setelah rekap dikunci, data tidak bisa diedit lewat halaman ini.",
        submit_label="Simpan Perubahan",
        submit_icon="bi-pencil-square",
        edit_batch=batch,
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def manual_billing_batch_detail(batch_id):
    from app.models.finance import ManualBillingBatch
    from app.services.billing_input_source_service import build_input_source_context
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_DRAFT,
        MANUAL_BACKFILL_STATUS_LOCKED,
        build_manual_backfill_duplicate_guard_context,
        get_manual_backfill_status_context,
        get_manual_backfill_bill_to_context,
    )

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=current_user.branch_id,
    ).first_or_404()

    catering_total = sum(float(item.subtotal or 0) for item in batch.items if item.item_type == "CATERING")
    warung_total = sum(float(item.subtotal or 0) for item in batch.items if item.item_type == "WARUNG_DEBT")
    other_total = sum(float(item.subtotal or 0) for item in batch.items if item.item_type not in {"CATERING", "WARUNG_DEBT"})
    status_context = get_manual_backfill_status_context(batch.status)
    duplicate_guard = build_manual_backfill_duplicate_guard_context(batch)
    from app.services.billing_trace_service import build_manual_billing_batch_trace_context
    billing_trace = build_manual_billing_batch_trace_context(batch)

    return render_template(
        "finance/manual_billing_batch_detail.html",
        batch=batch,
        input_source_context=build_input_source_context(batch.input_source),
        status_context=status_context,
        bill_to_context=get_manual_backfill_bill_to_context(batch),
        duplicate_guard=duplicate_guard,
        billing_trace=billing_trace,
        can_edit=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status == MANUAL_BACKFILL_STATUS_DRAFT
            and not batch.invoice_id
        ),
        can_void=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status in {MANUAL_BACKFILL_STATUS_DRAFT, MANUAL_BACKFILL_STATUS_LOCKED}
            and not batch.invoice_id
        ),
        can_lock=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status == MANUAL_BACKFILL_STATUS_DRAFT
            and not batch.invoice_id
            and not duplicate_guard["has_conflicts"]
        ),
        can_create_invoice=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status == MANUAL_BACKFILL_STATUS_LOCKED
            and not batch.invoice_id
            and not duplicate_guard["has_conflicts"]
        ),
        is_locked=batch.status == MANUAL_BACKFILL_STATUS_LOCKED,
        catering_total=catering_total,
        warung_total=warung_total,
        other_total=other_total,
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>/print")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def print_manual_billing_batch(batch_id):
    from app.models.finance import ManualBillingBatch
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import build_manual_backfill_print_context

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).first_or_404()

    context = build_manual_backfill_print_context(batch)
    return render_template(
        "finance/print_manual_billing_batch.html",
        company_settings=get_company_settings(current_user.branch_id),
        **context,
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>/lock", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def lock_manual_billing_batch_route(batch_id):
    from app.extensions import db
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        lock_manual_backfill_batch,
    )

    try:
        batch = lock_manual_backfill_batch(
            batch_id=batch_id,
            branch_id=current_user.branch_id,
            locked_by=current_user.id,
            commit=False,
        )
        db.session.commit()
        flash(f"Rekap manual dari buku {batch.batch_number} berhasil dikunci.", "success")
    except ManualBackfillBillingError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:
        db.session.rollback()
        flash(f"Gagal mengunci rekap manual dari buku: {exc}", "danger")

    return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))


@finance_bp.route("/manual-billing/batches/<int:batch_id>/void", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def void_manual_billing_batch_route(batch_id):
    from app.extensions import db
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        void_manual_backfill_batch,
    )

    reason = (request.form.get("void_reason") or request.form.get("reason") or "").strip()

    try:
        batch = void_manual_backfill_batch(
            batch_id=batch_id,
            branch_id=current_user.branch_id,
            voided_by=current_user.id,
            reason=reason,
            commit=False,
        )
        db.session.commit()
        flash(f"Rekap manual dari buku {batch.batch_number} berhasil dibatalkan sebelum menjadi invoice/piutang.", "success")
    except ManualBackfillBillingError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:
        db.session.rollback()
        flash(f"Gagal membatalkan rekap manual dari buku: {exc}", "danger")

    return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))


@finance_bp.route("/manual-billing/batches/<int:batch_id>/create-invoice", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_manual_backfill_invoice_route(batch_id):
    from app.extensions import db
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        create_invoice_from_manual_backfill_batch,
    )

    notes = (request.form.get("notes") or "").strip() or None

    try:
        batch, invoice = create_invoice_from_manual_backfill_batch(
            batch_id=batch_id,
            branch_id=current_user.branch_id,
            created_by=current_user.id,
            notes=notes,
            commit=False,
        )
        db.session.commit()
        flash(f"Rekap manual dari buku {batch.batch_number} berhasil dibuat menjadi invoice {invoice.invoice_number} dan piutang aktif.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    except ManualBackfillBillingError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:
        db.session.rollback()
        flash(f"Gagal membuat invoice dari rekap manual dari buku: {exc}", "danger")

    return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))


@finance_bp.route("/manual-billing/create", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_manual_billing_invoice_route():
    from app.extensions import db
    from app.services.manual_billing_service import ManualBillingError, create_manual_billing_invoice

    mandor_id = (request.form.get("mandor_id") or "").strip()
    period_start_value = (request.form.get("period_start") or "").strip()
    period_end_value = (request.form.get("period_end") or "").strip()
    client_pic_id = request.form.get("client_pic_id", type=int)
    notes = request.form.get("notes")

    period_start = _period_parse_date(period_start_value)
    period_end = _period_parse_date(period_end_value)

    if not mandor_id or not period_start or not period_end:
        flash("Mandor dan periode wajib diisi.", "warning")
        return redirect(url_for("finance.manual_billing"))

    try:
        batch, invoice = create_manual_billing_invoice(
            branch_id=current_user.branch_id,
            mandor_id=int(mandor_id),
            period_start=period_start,
            period_end=period_end,
            client_pic_id=client_pic_id,
            created_by=current_user.id,
            notes=notes,
        )
        db.session.commit()
        flash(f"Rekap billing manual {batch.batch_number} berhasil dibuat menjadi invoice {invoice.invoice_number}.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    except ManualBillingError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:
        db.session.rollback()
        flash(f"Gagal membuat invoice dari rekap tagihan mandor: {exc}", "danger")

    return redirect(url_for(
        "finance.manual_billing",
        mandor_id=mandor_id,
        period_start=period_start_value,
        period_end=period_end_value,
    ))

# === PRODUCTION_OPTIONAL_ADVANCE_DP_FLOW ===
@finance_bp.route("/advances")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def advances():
    from app.models.finance import AdvanceTransaction
    from app.services.advance_service import (
        ADVANCE_TYPES,
        get_advance_status_summary,
        get_party_label,
        is_advance_schema_ready,
    )

    schema_ready = is_advance_schema_ready()
    selected_type = (request.args.get("type") or "ALL").strip().upper()
    selected_status = (request.args.get("status") or "ALL").strip().upper()

    rows = []
    summary = {"total": 0, "open": 0, "settled": 0, "remaining": 0}

    if schema_ready:
        query = AdvanceTransaction.query.filter_by(branch_id=current_user.branch_id)
        if selected_type != "ALL":
            query = query.filter(AdvanceTransaction.advance_type == selected_type)
        if selected_status != "ALL":
            query = query.filter(AdvanceTransaction.status == selected_status)
        rows = query.order_by(AdvanceTransaction.advance_date.desc(), AdvanceTransaction.id.desc()).all()
        summary = get_advance_status_summary(current_user.branch_id)
    else:
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION sebelum memakai fitur ini.", "warning")

    return render_template(
        "finance/advances.html",
        advances=rows,
        summary=summary,
        advance_types=ADVANCE_TYPES,
        selected_type=selected_type,
        selected_status=selected_status,
        get_party_label=get_party_label,
        schema_ready=schema_ready,
    )


@finance_bp.route("/advances/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def advance_create():
    from datetime import datetime, date
    from app.extensions import db
    from app.models.finance import BankAccount
    from app.models.master import Client, Mandor, Supplier
    from app.services.advance_service import create_advance_transaction, get_advance_type_choices, is_advance_schema_ready

    schema_ready = is_advance_schema_ready()
    if not schema_ready:
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.advances"))

    if request.method == "POST":
        advance_date_raw = (request.form.get("advance_date") or "").strip()
        advance_type = (request.form.get("advance_type") or "").strip().upper()
        payment_method = (request.form.get("payment_method") or "").strip().upper()
        bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
        amount_raw = (request.form.get("amount") or "").strip()
        client_id_raw = (request.form.get("client_id") or "").strip()
        supplier_id_raw = (request.form.get("supplier_id") or "").strip()
        mandor_id_raw = (request.form.get("mandor_id") or "").strip()
        reference_number = (request.form.get("reference_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            advance_date = datetime.strptime(advance_date_raw, "%Y-%m-%d").date()
        except Exception:
            flash("Tanggal DP/uang muka tidak valid.", "warning")
            return redirect(url_for("finance.advance_create"))

        try:
            amount = _parse_payment_amount(amount_raw)
        except Exception:
            flash("Nominal DP/uang muka tidak valid.", "warning")
            return redirect(url_for("finance.advance_create"))

        def _to_int(value):
            try:
                return int(value) if value else None
            except Exception:
                return None

        try:
            ok, message, advance = create_advance_transaction(
                branch_id=current_user.branch_id,
                advance_date=advance_date,
                advance_type=advance_type,
                payment_method=payment_method,
                amount=amount,
                created_by=current_user.id,
                client_id=_to_int(client_id_raw),
                supplier_id=_to_int(supplier_id_raw),
                mandor_id=_to_int(mandor_id_raw),
                bank_account_id=_to_int(bank_account_id_raw),
                reference_number=reference_number,
                notes=notes,
                commit=False,
            )
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("finance.advance_detail", advance_id=advance.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("finance.advance_create"))

    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    suppliers = Supplier.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all()
    mandors = Mandor.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Mandor.name.asc()).all()
    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    return render_template(
        "finance/advance_form.html",
        today_date=date.today().isoformat(),
        advance_type_choices=get_advance_type_choices(),
        clients=clients,
        suppliers=suppliers,
        mandors=mandors,
        bank_accounts=bank_accounts,
    )


@finance_bp.route("/advances/<int:advance_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def advance_detail(advance_id):
    from datetime import date
    from app.models.finance import AdvanceTransaction, AdvanceSettlement
    from app.services.advance_service import (
        ADVANCE_TYPES,
        SETTLEMENT_TYPES,
        get_party_label,
        get_mandor_expense_proof_choices,
        get_settlement_reference_options,
        is_advance_schema_ready,
    )
    from app.services.field_transaction_service import find_field_transaction_linked_source

    if not is_advance_schema_ready():
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.advances"))

    advance = AdvanceTransaction.query.get_or_404(advance_id)
    if advance.branch_id != current_user.branch_id:
        abort(404)

    settlements = AdvanceSettlement.query.filter_by(
        branch_id=current_user.branch_id,
        advance_id=advance.id,
    ).order_by(AdvanceSettlement.settlement_date.desc(), AdvanceSettlement.id.desc()).all()
    reference_options = get_settlement_reference_options(current_user.branch_id, advance)
    field_transaction_link = find_field_transaction_linked_source(
        "ADVANCE_TRANSACTION",
        advance.id,
        branch_id=current_user.branch_id,
    )
    settlement_field_transaction_links = {
        settlement.id: find_field_transaction_linked_source(
            "ADVANCE_SETTLEMENT",
            settlement.id,
            branch_id=current_user.branch_id,
        )
        for settlement in settlements
    }

    return render_template(
        "finance/advance_detail.html",
        advance=advance,
        settlements=settlements,
        rule=ADVANCE_TYPES.get(advance.advance_type, {}),
        settlement_types=SETTLEMENT_TYPES,
        get_party_label=get_party_label,
        mandor_expense_proof_choices=get_mandor_expense_proof_choices(),
        today_date=date.today().isoformat(),
        reference_options=reference_options,
        field_transaction_link=field_transaction_link,
        settlement_field_transaction_links=settlement_field_transaction_links,
    )


@finance_bp.route("/advances/<int:advance_id>/settle", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def advance_settle(advance_id):
    from datetime import datetime
    from app.extensions import db
    from app.models.finance import AdvanceTransaction
    from app.services.advance_service import create_advance_settlement, is_advance_schema_ready

    if not is_advance_schema_ready():
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.advances"))

    advance = AdvanceTransaction.query.get_or_404(advance_id)
    if advance.branch_id != current_user.branch_id:
        abort(404)

    settlement_date_raw = (request.form.get("settlement_date") or "").strip()
    settlement_type = (request.form.get("settlement_type") or "").strip().upper()
    reference_id_raw = (request.form.get("reference_id") or "").strip()
    expense_account_code = (request.form.get("expense_account_code") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    try:
        settlement_date = datetime.strptime(settlement_date_raw, "%Y-%m-%d").date()
    except Exception:
        flash("Tanggal settlement DP tidak valid.", "warning")
        return redirect(url_for("finance.advance_detail", advance_id=advance.id))

    try:
        amount = _parse_payment_amount(amount_raw)
    except Exception:
        flash("Nominal settlement DP tidak valid.", "warning")
        return redirect(url_for("finance.advance_detail", advance_id=advance.id))

    try:
        reference_id = int(reference_id_raw) if reference_id_raw else None
    except Exception:
        reference_id = None

    try:
        ok, message, settlement = create_advance_settlement(
            advance=advance,
            settlement_date=settlement_date,
            settlement_type=settlement_type,
            amount=amount,
            created_by=current_user.id,
            reference_id=reference_id,
            expense_account_code=expense_account_code,
            notes=notes,
            commit=False,
        )
        db.session.commit()
        flash(message, "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    return redirect(url_for("finance.advance_detail", advance_id=advance.id))



# === PRODUCTION_TRANSPORT_VEHICLE_FUEL_EXPENSE_COA_MAPPING_ROUTES ===
@finance_bp.route("/transport-expenses")
@role_required("OWNER", "ADMIN", "FINANCE")
def transport_expenses():
    from app.models.finance import TransportVehicleExpense
    from app.services.transport_expense_service import (
        TRANSPORT_EXPENSE_TYPES,
        get_driver_label,
        get_delivery_label,
        get_transport_expense_status_summary,
        is_transport_expense_schema_ready,
    )

    schema_ready = is_transport_expense_schema_ready()
    selected_type = (request.args.get("type") or "ALL").strip().upper()
    selected_account = (request.args.get("account") or "ALL").strip().upper()
    rows = []
    summary = get_transport_expense_status_summary(current_user.branch_id)
    if schema_ready:
        query = TransportVehicleExpense.query.filter_by(branch_id=current_user.branch_id)
        if selected_type != "ALL":
            query = query.filter(TransportVehicleExpense.expense_type == selected_type)
        if selected_account != "ALL":
            query = query.filter(TransportVehicleExpense.account_type == selected_account)
        rows = query.order_by(TransportVehicleExpense.expense_date.desc(), TransportVehicleExpense.id.desc()).all()

    return render_template(
        "finance/transport_expenses.html",
        expenses=rows,
        summary=summary,
        expense_types=TRANSPORT_EXPENSE_TYPES,
        selected_type=selected_type,
        selected_account=selected_account,
        schema_ready=schema_ready,
        get_driver_label=get_driver_label,
        get_delivery_label=get_delivery_label,
    )


@finance_bp.route("/transport-expenses/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def transport_expense_create():
    from datetime import date, datetime
    from app.extensions import db
    from app.models.delivery import Delivery
    from app.models.finance import BankAccount
    from app.models.master import Driver
    from app.services.transport_expense_service import create_transport_vehicle_expense, get_transport_expense_type_choices, is_transport_expense_schema_ready

    if not is_transport_expense_schema_ready():
        flash("Tabel transport/BBM belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.transport_expenses"))

    if request.method == "POST":
        try:
            expense_date = datetime.strptime((request.form.get("expense_date") or "").strip(), "%Y-%m-%d").date()
            amount = _parse_payment_amount((request.form.get("amount") or "").strip())
            ok, message, expense = create_transport_vehicle_expense(
                branch_id=current_user.branch_id,
                expense_date=expense_date,
                expense_type=(request.form.get("expense_type") or "").strip().upper(),
                payment_method=(request.form.get("payment_method") or "").strip().upper(),
                amount=amount,
                created_by=current_user.id,
                vehicle_label=(request.form.get("vehicle_label") or "").strip(),
                driver_id=(request.form.get("driver_id") or "").strip() or None,
                delivery_id=(request.form.get("delivery_id") or "").strip() or None,
                bank_account_id=(request.form.get("bank_account_id") or "").strip() or None,
                vendor_name=(request.form.get("vendor_name") or "").strip(),
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
                commit=False,
            )
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("finance.transport_expense_detail", expense_id=expense.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("finance.transport_expense_create"))

    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    drivers = Driver.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Driver.name.asc()).all()
    deliveries = Delivery.query.filter_by(branch_id=current_user.branch_id).order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(100).all()
    return render_template(
        "finance/transport_expense_form.html",
        today_date=date.today().isoformat(),
        expense_type_choices=get_transport_expense_type_choices(),
        bank_accounts=bank_accounts,
        drivers=drivers,
        deliveries=deliveries,
    )


@finance_bp.route("/transport-expenses/<int:expense_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def transport_expense_detail(expense_id):
    from app.models.finance import TransportVehicleExpense
    from app.services.transport_expense_service import TRANSPORT_EXPENSE_TYPES, get_driver_label, get_delivery_label, is_transport_expense_schema_ready
    from app.services.field_transaction_service import find_field_transaction_linked_source

    if not is_transport_expense_schema_ready():
        flash("Tabel transport/BBM belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.transport_expenses"))
    expense = TransportVehicleExpense.query.get_or_404(expense_id)
    if expense.branch_id != current_user.branch_id:
        abort(404)
    field_transaction_link = find_field_transaction_linked_source(
        "TRANSPORT_VEHICLE_EXPENSE",
        expense.id,
        branch_id=current_user.branch_id,
    )
    return render_template(
        "finance/transport_expense_detail.html",
        expense=expense,
        rule=TRANSPORT_EXPENSE_TYPES.get(expense.expense_type, {}),
        get_driver_label=get_driver_label,
        get_delivery_label=get_delivery_label,
        field_transaction_link=field_transaction_link,
    )


# === PRODUCTION_OPERATIONAL_EXPENSE_COA_MAPPING_ROUTES ===
@finance_bp.route("/operational-expenses")
@role_required("OWNER", "ADMIN", "FINANCE")
def operational_expenses():
    from app.models.finance import OperationalExpense
    from app.services.operational_expense_service import (
        OPERATIONAL_EXPENSE_CATEGORIES,
        get_operational_expense_status_summary,
        get_supplier_label,
        is_operational_expense_schema_ready,
    )

    schema_ready = is_operational_expense_schema_ready()
    selected_category = (request.args.get("category") or "ALL").strip().upper()
    selected_account = (request.args.get("account") or "ALL").strip().upper()
    rows = []
    summary = get_operational_expense_status_summary(current_user.branch_id)
    if schema_ready:
        query = OperationalExpense.query.filter_by(branch_id=current_user.branch_id)
        if selected_category != "ALL":
            query = query.filter(OperationalExpense.expense_category == selected_category)
        if selected_account != "ALL":
            query = query.filter(OperationalExpense.account_type == selected_account)
        rows = query.order_by(OperationalExpense.expense_date.desc(), OperationalExpense.id.desc()).all()

    return render_template(
        "finance/operational_expenses.html",
        expenses=rows,
        summary=summary,
        expense_categories=OPERATIONAL_EXPENSE_CATEGORIES,
        selected_category=selected_category,
        selected_account=selected_account,
        schema_ready=schema_ready,
        get_supplier_label=get_supplier_label,
    )


@finance_bp.route("/operational-expenses/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def operational_expense_create():
    from datetime import date, datetime
    from app.extensions import db
    from app.models.finance import BankAccount
    from app.models.master import Supplier
    from app.services.operational_expense_service import create_operational_expense, get_operational_expense_category_choices, is_operational_expense_schema_ready

    if not is_operational_expense_schema_ready():
        flash("Tabel biaya operasional belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.operational_expenses"))

    if request.method == "POST":
        try:
            expense_date = datetime.strptime((request.form.get("expense_date") or "").strip(), "%Y-%m-%d").date()
            amount = _parse_payment_amount((request.form.get("amount") or "").strip())
            ok, message, expense = create_operational_expense(
                branch_id=current_user.branch_id,
                expense_date=expense_date,
                expense_category=(request.form.get("expense_category") or "").strip().upper(),
                payment_method=(request.form.get("payment_method") or "").strip().upper(),
                amount=amount,
                created_by=current_user.id,
                bank_account_id=(request.form.get("bank_account_id") or "").strip() or None,
                supplier_id=(request.form.get("supplier_id") or "").strip() or None,
                vendor_name=(request.form.get("vendor_name") or "").strip(),
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
                commit=False,
            )
            db.session.commit()
            flash(message, "success")
            return redirect(url_for("finance.operational_expense_detail", expense_id=expense.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("finance.operational_expense_create"))

    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    suppliers = Supplier.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all()
    return render_template(
        "finance/operational_expense_form.html",
        today_date=date.today().isoformat(),
        expense_category_choices=get_operational_expense_category_choices(),
        bank_accounts=bank_accounts,
        suppliers=suppliers,
    )


@finance_bp.route("/operational-expenses/<int:expense_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def operational_expense_detail(expense_id):
    from app.models.finance import OperationalExpense
    from app.services.operational_expense_service import OPERATIONAL_EXPENSE_CATEGORIES, get_supplier_label, is_operational_expense_schema_ready
    from app.services.field_transaction_service import find_field_transaction_linked_source

    if not is_operational_expense_schema_ready():
        flash("Tabel biaya operasional belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.operational_expenses"))
    expense = OperationalExpense.query.get_or_404(expense_id)
    if expense.branch_id != current_user.branch_id:
        abort(404)
    field_transaction_link = find_field_transaction_linked_source(
        "OPERATIONAL_EXPENSE",
        expense.id,
        branch_id=current_user.branch_id,
    )
    return render_template(
        "finance/operational_expense_detail.html",
        expense=expense,
        rule=OPERATIONAL_EXPENSE_CATEGORIES.get(expense.expense_category, {}),
        get_supplier_label=get_supplier_label,
        field_transaction_link=field_transaction_link,
    )




# === PRODUCTION_OPTIONAL_FIXED_ASSET_DEPRECIATION_ENGINE_ROUTES ===
@finance_bp.route("/fixed-asset-depreciation")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_depreciation():
    from app.services.fixed_asset_depreciation_service import (
        get_asset_depreciation_rows,
        get_depreciation_summary,
        is_depreciation_schema_ready,
    )

    schema_ready = is_depreciation_schema_ready()
    status = (request.args.get("status") or "ALL").strip().upper()
    rows = []
    summary = get_depreciation_summary(current_user.branch_id)
    if schema_ready:
        rows = get_asset_depreciation_rows(current_user.branch_id, status=status)

    return render_template(
        "finance/fixed_asset_depreciation.html",
        schema_ready=schema_ready,
        rows=rows,
        summary=summary,
        status=status,
    )


@finance_bp.route("/fixed-asset-depreciation/<int:asset_id>/configure", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_depreciation_configure(asset_id):
    from datetime import datetime
    from app.extensions import db
    from app.models.accounting import FixedAsset
    from app.services.fixed_asset_depreciation_service import (
        DEPRECIATION_STATUS_OPTIONS,
        configure_asset_depreciation,
        get_accumulated_account_options,
        is_depreciation_schema_ready,
        preview_asset_depreciation,
        resolve_default_accumulated_account_code,
    )

    if not is_depreciation_schema_ready():
        flash("Tabel penyusutan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_depreciation"))

    asset = FixedAsset.query.filter_by(id=asset_id, branch_id=current_user.branch_id).first_or_404()
    config = getattr(asset, "depreciation_config", None)

    if request.method == "POST":
        try:
            start_date = datetime.strptime((request.form.get("depreciation_start_date") or "").strip(), "%Y-%m-%d").date()
            configure_asset_depreciation(
                branch_id=current_user.branch_id,
                asset_id=asset.id,
                depreciation_start_date=start_date,
                useful_life_months=(request.form.get("useful_life_months") or "").strip(),
                residual_value=(request.form.get("residual_value") or "0").strip(),
                accumulated_account_code=(request.form.get("accumulated_account_code") or "").strip(),
                status=(request.form.get("status") or "CONFIGURED").strip().upper(),
                notes=(request.form.get("notes") or "").strip(),
                created_by=current_user.id,
                commit=False,
            )
            db.session.commit()
            flash("Konfigurasi penyusutan aset berhasil disimpan. Jurnal belum dibuat sampai proses posting dijalankan.", "success")
            return redirect(url_for("finance.fixed_asset_depreciation"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("finance.fixed_asset_depreciation_configure", asset_id=asset.id))

    default_account_code = resolve_default_accumulated_account_code(asset.asset_category)
    preview_rows = preview_asset_depreciation(asset, months=12) if config else []
    return render_template(
        "finance/fixed_asset_depreciation_configure.html",
        asset=asset,
        config=config,
        default_account_code=default_account_code,
        accumulated_account_options=get_accumulated_account_options(),
        status_options=DEPRECIATION_STATUS_OPTIONS,
        preview_rows=preview_rows,
    )


@finance_bp.route("/fixed-asset-depreciation/<int:asset_id>/post", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_depreciation_post(asset_id):
    from app.extensions import db
    from app.services.fixed_asset_depreciation_service import is_depreciation_schema_ready, post_asset_depreciation

    if not is_depreciation_schema_ready():
        flash("Tabel penyusutan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_depreciation"))

    try:
        entry = post_asset_depreciation(
            branch_id=current_user.branch_id,
            asset_id=asset_id,
            period_year=(request.form.get("period_year") or "").strip(),
            period_month=(request.form.get("period_month") or "").strip(),
            created_by=current_user.id,
            commit=False,
        )
        db.session.commit()
        flash(f"Penyusutan {entry.depreciation_number} berhasil diposting ke jurnal.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("finance.fixed_asset_depreciation"))


# === PRODUCTION_FIXED_ASSET_PURCHASE_CASH_BANK ===
@finance_bp.route("/fixed-asset-purchases")
@role_required("OWNER", "ADMIN", "FINANCE")
def fixed_asset_purchases():
    from app.services.fixed_asset_purchase_service import list_fixed_asset_purchases

    q = (request.args.get("q") or "").strip()
    payment_method = (request.args.get("payment_method") or "ALL").strip().upper()
    purchases = list_fixed_asset_purchases(
        branch_id=current_user.branch_id,
        q=q,
        payment_method=payment_method,
    )

    summary = {
        "count": len(purchases),
        "total_amount": sum(float(row.amount or 0) for row in purchases),
        "cash_amount": sum(float(row.amount or 0) for row in purchases if row.account_type == "CASH"),
        "bank_amount": sum(float(row.amount or 0) for row in purchases if row.account_type == "BANK"),
    }

    return render_template(
        "finance/fixed_asset_purchases.html",
        purchases=purchases,
        q=q,
        payment_method=payment_method,
        summary=summary,
    )


@finance_bp.route("/fixed-asset-purchases/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_fixed_asset_purchase():
    from datetime import datetime
    from app.extensions import db
    from app.models.accounting import FixedAsset
    from app.models.finance import BankAccount
    from app.services.fixed_asset_purchase_service import (
        ASSET_CATEGORY_OPTIONS,
        create_fixed_asset_purchase as create_purchase_service,
        get_asset_account_options,
    )

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    existing_assets = FixedAsset.query.filter_by(
        branch_id=current_user.branch_id,
        status="ACTIVE",
    ).order_by(FixedAsset.asset_code.asc()).all()

    if request.method == "POST":
        purchase_date_raw = (request.form.get("purchase_date") or "").strip()
        try:
            purchase_date = datetime.strptime(purchase_date_raw, "%Y-%m-%d").date()
        except Exception:
            flash("Tanggal pembelian aset tidak valid.", "warning")
            return redirect(url_for("finance.create_fixed_asset_purchase"))

        asset_mode = (request.form.get("asset_mode") or "NEW").strip().upper()
        asset_id_raw = (request.form.get("asset_id") or "").strip()
        asset_id = None
        if asset_id_raw:
            try:
                asset_id = int(asset_id_raw)
            except (TypeError, ValueError):
                asset_id = None

        bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
        bank_account_id = None
        if bank_account_id_raw:
            try:
                bank_account_id = int(bank_account_id_raw)
            except (TypeError, ValueError):
                bank_account_id = None

        try:
            purchase, ledger_transaction, journal = create_purchase_service(
                branch_id=current_user.branch_id,
                purchase_date=purchase_date,
                asset_mode=asset_mode,
                asset_id=asset_id,
                asset_name=(request.form.get("asset_name") or "").strip(),
                asset_category=(request.form.get("asset_category") or "OTHER").strip(),
                asset_account_code=(request.form.get("asset_account_code") or "").strip(),
                payment_method=(request.form.get("payment_method") or "").strip(),
                bank_account_id=bank_account_id,
                amount=(request.form.get("amount") or "").strip(),
                useful_life_years=(request.form.get("useful_life_years") or "0").strip(),
                residual_value=(request.form.get("residual_value") or "0").strip(),
                vendor_name=(request.form.get("vendor_name") or "").strip(),
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
                created_by=current_user.id,
                commit=False,
            )
            db.session.commit()
            flash(
                f"Pembelian aset tetap {purchase.purchase_number} berhasil disimpan. Ledger OUT dan jurnal {journal.journal_number} dibuat.",
                "success",
            )
            return redirect(url_for("finance.fixed_asset_purchase_detail", purchase_id=purchase.id))
        except Exception as exc:
            db.session.rollback()
            flash(f"Gagal menyimpan pembelian aset tetap: {exc}", "danger")
            return redirect(url_for("finance.create_fixed_asset_purchase"))

    return render_template(
        "finance/fixed_asset_purchase_form.html",
        active_bank_accounts=active_bank_accounts,
        existing_assets=existing_assets,
        asset_categories=ASSET_CATEGORY_OPTIONS,
        asset_account_options=get_asset_account_options(),
    )


@finance_bp.route("/fixed-asset-purchases/<int:purchase_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def fixed_asset_purchase_detail(purchase_id):
    from app.services.fixed_asset_purchase_service import get_fixed_asset_purchase_detail

    purchase = get_fixed_asset_purchase_detail(purchase_id, current_user.branch_id)
    if not purchase:
        flash("Pembelian aset tetap tidak ditemukan.", "warning")
        return redirect(url_for("finance.fixed_asset_purchases"))

    return render_template(
        "finance/fixed_asset_purchase_detail.html",
        purchase=purchase,
        asset=purchase.fixed_asset,
        ledger_transaction=purchase.cash_bank_transaction,
        journal=purchase.journal,
    )


# === PRODUCTION_ASSET_VEHICLE_INSTALLMENT_FOUNDATION_ROUTES ===
@finance_bp.route("/fixed-asset-installments")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_installments():
    from app.services.fixed_asset_installment_service import (
        build_installment_summary,
        is_installment_schema_ready,
        list_asset_financing_contracts,
    )

    schema_ready = is_installment_schema_ready()
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "ALL").strip().upper()
    contracts = list_asset_financing_contracts(current_user.branch_id, q=q, status=status) if schema_ready else []
    summary = build_installment_summary(contracts) if schema_ready else {
        "count": 0,
        "active_count": 0,
        "total_contract": 0,
        "paid": 0,
        "remaining": 0,
    }

    return render_template(
        "finance/fixed_asset_installments.html",
        schema_ready=schema_ready,
        contracts=contracts,
        summary=summary,
        q=q,
        status=status,
    )


@finance_bp.route("/fixed-asset-installments/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def create_fixed_asset_installment_contract():
    from datetime import datetime
    from app.extensions import db
    from app.models.accounting import FixedAsset
    from app.models.finance import BankAccount
    from app.services.fixed_asset_installment_service import (
        create_asset_financing_contract,
        get_installment_account_options,
        is_installment_schema_ready,
    )
    from app.services.fixed_asset_purchase_service import ASSET_CATEGORY_OPTIONS

    if not is_installment_schema_ready():
        flash("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    existing_assets = FixedAsset.query.filter_by(
        branch_id=current_user.branch_id,
        status="ACTIVE",
    ).order_by(FixedAsset.asset_code.asc()).all()

    if request.method == "POST":
        try:
            contract_date = datetime.strptime((request.form.get("contract_date") or "").strip(), "%Y-%m-%d").date()
            first_due_date = datetime.strptime((request.form.get("first_due_date") or "").strip(), "%Y-%m-%d").date()
            asset_id_raw = (request.form.get("asset_id") or "").strip()
            asset_id = int(asset_id_raw) if asset_id_raw else None

            with atomic_business_action(
                module="FIXED_ASSET",
                action="ASSET_FINANCING_CONTRACT_CREATE",
                description="Buat kontrak cicilan aset tetap/kendaraan.",
                reference_type="asset_financing_contracts",
                user_id=current_user.id,
                branch_id=current_user.branch_id,
                severity="HIGH",
                metadata={"app_version": "PRODUCTION", "scope": "asset_installment_contract"},
            ):
                contract = create_asset_financing_contract(
                    branch_id=current_user.branch_id,
                    contract_date=contract_date,
                    asset_mode=(request.form.get("asset_mode") or "NEW").strip().upper(),
                    asset_id=asset_id,
                    asset_name=(request.form.get("asset_name") or "").strip(),
                    asset_category=(request.form.get("asset_category") or "OTHER").strip(),
                    asset_account_code=(request.form.get("asset_account_code") or "").strip(),
                    liability_account_code=(request.form.get("liability_account_code") or "2001").strip(),
                    interest_expense_account_code=(request.form.get("interest_expense_account_code") or "5008").strip(),
                    admin_expense_account_code=(request.form.get("admin_expense_account_code") or "5008").strip(),
                    principal_amount=(request.form.get("principal_amount") or "").strip(),
                    total_interest_amount=(request.form.get("total_interest_amount") or "0").strip(),
                    total_admin_amount=(request.form.get("total_admin_amount") or "0").strip(),
                    installment_count=(request.form.get("installment_count") or "1").strip(),
                    first_due_date=first_due_date,
                    vendor_name=(request.form.get("vendor_name") or "").strip(),
                    financing_provider=(request.form.get("financing_provider") or "").strip(),
                    notes=(request.form.get("notes") or "").strip(),
                    created_by=current_user.id,
                    commit=False,
                )
            flash(f"Kontrak cicilan aset {contract.contract_number} berhasil dibuat. Jurnal akuisisi dan jadwal cicilan terbentuk.", "success")
            return redirect(url_for("finance.fixed_asset_installment_detail", contract_id=contract.id))
        except Exception as exc:
            db.session.rollback()
            flash(f"Gagal membuat kontrak cicilan aset: {exc}", "danger")
            return redirect(url_for("finance.create_fixed_asset_installment_contract"))

    return render_template(
        "finance/fixed_asset_installment_form.html",
        existing_assets=existing_assets,
        active_bank_accounts=active_bank_accounts,
        asset_categories=ASSET_CATEGORY_OPTIONS,
        account_options=get_installment_account_options(),
    )


@finance_bp.route("/fixed-asset-installments/<int:contract_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_installment_detail(contract_id):
    from app.models.finance import BankAccount
    from app.services.fixed_asset_installment_service import calculate_contract_summary, get_contract_detail, is_installment_schema_ready

    if not is_installment_schema_ready():
        flash("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))
    contract = get_contract_detail(contract_id, current_user.branch_id)
    if not contract:
        flash("Kontrak cicilan aset tidak ditemukan.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))
    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    return render_template(
        "finance/fixed_asset_installment_detail.html",
        contract=contract,
        asset=contract.fixed_asset,
        summary=calculate_contract_summary(contract),
        active_bank_accounts=active_bank_accounts,
    )


@finance_bp.route("/fixed-asset-installments/<int:contract_id>/pay/<int:schedule_id>", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def pay_fixed_asset_installment(contract_id, schedule_id):
    from datetime import datetime
    from app.extensions import db
    from app.services.fixed_asset_installment_service import is_installment_schema_ready, pay_installment_schedule

    if not is_installment_schema_ready():
        flash("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))
    try:
        payment_date = datetime.strptime((request.form.get("payment_date") or "").strip(), "%Y-%m-%d").date()
        bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
        bank_account_id = int(bank_account_id_raw) if bank_account_id_raw else None
        with atomic_business_action(
            module="FIXED_ASSET",
            action="ASSET_INSTALLMENT_PAYMENT_CREATE",
            description="Bayar jadwal cicilan aset tetap/kendaraan.",
            reference_type="asset_installment_schedules",
            reference_id=schedule_id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            severity="HIGH",
            metadata={"app_version": "PRODUCTION", "contract_id": contract_id, "schedule_id": schedule_id},
        ):
            payment = pay_installment_schedule(
                branch_id=current_user.branch_id,
                contract_id=contract_id,
                schedule_id=schedule_id,
                payment_date=payment_date,
                payment_method=(request.form.get("payment_method") or "").strip(),
                bank_account_id=bank_account_id,
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
                created_by=current_user.id,
                commit=False,
            )
        flash(f"Pembayaran cicilan {payment.payment_number} berhasil dicatat ke ledger dan jurnal.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Gagal membayar cicilan aset: {exc}", "danger")
    return redirect(url_for("finance.fixed_asset_installment_detail", contract_id=contract_id))


@finance_bp.route("/invoices/<int:invoice_id>/official-identity/refresh", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def refresh_invoice_official_identity(invoice_id):
    from app.extensions import db

    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    if not invoice.client_id:
        flash("Invoice ini belum terkait client/perusahaan.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    client = Client.query.get(invoice.client_id)
    client_pic_id = request.form.get("client_pic_id", type=int)
    client_pic, error = get_required_client_pic(invoice.client_id, client_pic_id)
    if error:
        flash(error, "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    apply_invoice_identity_snapshot(invoice, client=client, client_pic=client_pic, branch_id=current_user.branch_id)
    db.session.commit()

    flash("Identitas resmi invoice, PIC client, dan snapshot rekening pembayaran berhasil dikunci ulang.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
