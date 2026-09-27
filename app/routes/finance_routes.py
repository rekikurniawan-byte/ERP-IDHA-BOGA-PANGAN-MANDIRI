import logging
from uuid import uuid4
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
    refresh_invoice_identity_snapshot_record,
)
from app.services.audit_log_service import record_audit_log
from app.services.atomic_transaction_service import atomic_business_action
from app.services.idempotency_service import (
    IdempotencyConflictError,
    mark_idempotency_completed,
    reserve_idempotency_key,
)
from app.services.finance_collection_service import create_invoice_collection_log_record, create_receivables_statement_logs
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
from app.utils.terms import T

logger = logging.getLogger(__name__)


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
        return client.name if client else f"{T.client} ID {invoice.client_id}"

    if bill_to_type == "MANDOR" and invoice.mandor_id:
        if getattr(invoice, "client_name_snapshot", None):
            return invoice.client_name_snapshot
        mandor = Mandor.query.get(invoice.mandor_id)
        return mandor.name if mandor else f"{T.sub_client} ID {invoice.mandor_id}"

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




# Domain route modules. Imported after shared helpers are defined so decorators bind to the same blueprint.
from app.routes.finance import hub_routes as _finance_hub_routes  # noqa: F401,E402
from app.routes.finance import invoice_index_routes as _finance_invoice_index_routes  # noqa: F401,E402
from app.routes.finance import export_print_routes as _finance_export_print_routes  # noqa: F401,E402
from app.routes.finance import invoice_detail_routes as _finance_invoice_detail_routes  # noqa: F401,E402
from app.routes.finance import realtime_invoice_routes as _finance_realtime_invoice_routes  # noqa: F401,E402
from app.routes.finance import period_invoice_routes as _finance_period_invoice_routes  # noqa: F401,E402
from app.routes.finance import payment_routes as _finance_payment_routes  # noqa: F401,E402
from app.routes.finance import invoice_print_routes as _finance_invoice_print_routes  # noqa: F401,E402
from app.routes.finance import invoice_communication_routes as _finance_invoice_communication_routes  # noqa: F401,E402
from app.routes.finance import ar_dashboard_routes as _finance_ar_dashboard_routes  # noqa: F401,E402
from app.routes.finance import identity_routes as _finance_identity_routes  # noqa: F401,E402
from app.routes.finance import receivables_routes as _finance_receivables_routes  # noqa: F401,E402
from app.routes.finance import cash_bank_routes as _finance_cash_bank_routes  # noqa: F401,E402
from app.routes.finance import payables_routes as _finance_payables_routes  # noqa: F401,E402
from app.routes.finance import manual_billing_routes as _finance_manual_billing_routes  # noqa: F401,E402
from app.routes.finance import advance_expense_asset_routes as _finance_advance_expense_asset_routes  # noqa: F401,E402
from app.routes.finance import daily_cash_routes as _finance_daily_cash_routes  # noqa: F401,E402

from app.routes.finance.realtime_invoice_routes import (  # noqa: E402,F401
    _build_catering_invoice_lines,
)
from app.services.mandor_invoice_helper_service import (  # noqa: E402,F401
    calculate_realtime_locked_base_quantities as _calculate_realtime_locked_base_quantities,
    is_after_lock_increase_revision as _is_after_lock_increase_revision,
)
from app.routes.finance.ar_dashboard_routes import build_invoice_ar_warning, finance_ar_warning  # noqa: E402,F401
