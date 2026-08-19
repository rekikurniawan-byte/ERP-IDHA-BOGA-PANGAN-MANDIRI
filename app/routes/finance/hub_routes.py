# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403

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
    from app.services.portal_erp_integration_status_service import (
        build_finance_portal_payment_status,
        build_portal_erp_integration_status,
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
        portal_payment_status=build_finance_portal_payment_status(current_user),
        erp_integration=build_portal_erp_integration_status(current_user),
    )
