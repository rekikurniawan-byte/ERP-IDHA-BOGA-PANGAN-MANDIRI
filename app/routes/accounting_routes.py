import logging
from uuid import uuid4
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required

from app.models.accounting import Account, Journal, JournalDetail
from app.utils.decorators import role_required
from app.services.data_health_service import get_data_health_report
from app.services.daily_closing_service import get_daily_closing_report
from app.services.order_to_cash_trace_service import get_order_to_cash_trace_report
from app.services.audit_log_service import record_audit_log
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context
from app.services.accounting_service import commit_accounting_transaction, rollback_accounting_transaction
from app.services.idempotency_service import (
    IdempotencyConflictError,
    mark_idempotency_completed,
    reserve_idempotency_key,
)

logger = logging.getLogger(__name__)


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


def _reserve_accounting_idempotency(scope, payload, default_endpoint="accounting.journals"):
    key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex
    try:
        record, reserved = reserve_idempotency_key(
            scope=scope,
            key=key,
            branch_id=current_user.branch_id,
            user_id=current_user.id,
            request_payload=payload,
        )
    except IdempotencyConflictError:
        flash("Submit accounting berbeda memakai idempotency key yang sama. Muat ulang halaman lalu coba lagi.", "warning")
        return None, _redirect_after_accounting_post(default_endpoint)

    if not reserved:
        flash("Submit accounting ini sudah pernah diproses.", "info")
        return None, _redirect_after_accounting_post(default_endpoint)

    return record, None


# ACCOUNTING9B_WARUNG_FUTURE_ACCRUAL_HELPER
ACCOUNTING9B_CUTOVER_WORKER_DEBT_ID = 2
ACCOUNTING9B_CUTOVER_DEBT_PAYMENT_ID = 4
ACCOUNTING9B_CUTOVER_INVOICE_ID = 2




# Domain route modules. Imported after shared helpers are defined so decorators bind to the same blueprint.
from app.routes.accounting import audit_routes as _accounting_audit_routes  # noqa: F401,E402
from app.routes.accounting import journal_routes as _accounting_journal_routes  # noqa: F401,E402
from app.routes.accounting import report_routes as _accounting_report_routes  # noqa: F401,E402
from app.routes.accounting import posting_routes as _accounting_posting_routes  # noqa: F401,E402
from app.routes.accounting import closing_routes as _accounting_closing_routes  # noqa: F401,E402
