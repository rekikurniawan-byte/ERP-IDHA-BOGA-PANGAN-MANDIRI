from app.models.field_transaction import (
    FieldTransaction,
    ManualPayable,
    ManualReceivable,
)
from app.services.manual_billing_service import (
    MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
    find_manual_billing_invoice_for_source,
)


PENDING_REVIEW_STATUSES = {
    "DRAFT",
    "RECORDED",
    "WAITING_EVIDENCE",
    "WAITING_CLASSIFICATION",
    "IN_REVIEW",
    "WAITING_APPROVAL",
}


def _money_total(rows, attr="amount"):
    return sum(float(getattr(row, attr, 0) or 0) for row in rows)


def _status(value):
    return str(value or "").strip().upper()


def build_field_transaction_monitoring(branch_id):
    transactions = FieldTransaction.query.filter_by(branch_id=branch_id).order_by(
        FieldTransaction.transaction_date.desc(),
        FieldTransaction.id.desc(),
    ).all()
    receivables = ManualReceivable.query.filter_by(branch_id=branch_id).order_by(
        ManualReceivable.receivable_date.desc(),
        ManualReceivable.id.desc(),
    ).all()
    payables = ManualPayable.query.filter_by(branch_id=branch_id).order_by(
        ManualPayable.payable_date.desc(),
        ManualPayable.id.desc(),
    ).all()

    pending_review = [row for row in transactions if _status(row.review_status) in PENDING_REVIEW_STATUSES]
    ready_to_post = [
        row for row in transactions
        if _status(row.review_status) == "READY_TO_POST" and _status(row.posting_status) != "POSTED"
    ]
    posted = [row for row in transactions if _status(row.posting_status) == "POSTED"]
    needs_follow_up = [row for row in transactions if bool(row.needs_follow_up)]

    open_receivables = [row for row in receivables if _status(row.status) != "PAID"]
    open_payables = [row for row in payables if _status(row.status) != "PAID"]
    open_receivable_billed = []
    open_receivable_unbilled = []

    for row in open_receivables:
        billed_invoice = find_manual_billing_invoice_for_source(
            MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
            row.id,
        )
        setattr(row, "billing_invoice", billed_invoice)
        if billed_invoice:
            open_receivable_billed.append(row)
        else:
            open_receivable_unbilled.append(row)

    mismatches = []
    for row in posted:
        link_roles = {str(link.link_role or "").strip().upper() for link in row.links}
        has_financial_trace = bool(link_roles & {"LEDGER", "JOURNAL", "OPERATIONAL_EXPENSE", "TRANSPORT_EXPENSE", "ADVANCE_TRANSACTION"})
        if not has_financial_trace:
            mismatches.append({
                "transaction": row,
                "reason": "Status POSTED tetapi belum punya trace ledger/journal/bridge legacy.",
            })

    manual_doc_gaps = []
    for row in transactions:
        event_type = _status(row.business_event_type)
        if event_type == "MANUAL_RECEIVABLE_CREATED" and not any(link.link_role == "MANUAL_RECEIVABLE" for link in row.links):
            manual_doc_gaps.append({
                "transaction": row,
                "reason": "Event piutang manual belum dibuatkan dokumen piutang manual.",
            })
        if event_type == "UNFORMAL_VENDOR_PAYABLE" and not any(link.link_role == "MANUAL_PAYABLE" for link in row.links):
            manual_doc_gaps.append({
                "transaction": row,
                "reason": "Event hutang manual belum dibuatkan dokumen hutang manual.",
            })

    bridge_candidates = []
    for row in transactions:
        event_type = _status(row.business_event_type)
        if _status(row.posting_status) == "POSTED":
            continue
        link_roles = {str(link.link_role or "").strip().upper() for link in row.links}
        if event_type in {"SITE_OPERATION_EXPENSE", "KITCHEN_OPERATION_EXPENSE"} and "OPERATIONAL_EXPENSE" not in link_roles:
            bridge_candidates.append(row)
        elif event_type in {"TRANSPORT_TRIP_EXPENSE", "FUEL_EXPENSE"} and "TRANSPORT_EXPENSE" not in link_roles:
            bridge_candidates.append(row)
        elif event_type == "MANDOR_OPERATIONAL_ADVANCE" and "ADVANCE_TRANSACTION" not in link_roles:
            bridge_candidates.append(row)

    summary = {
        "total_transactions": len(transactions),
        "pending_review_count": len(pending_review),
        "pending_review_amount": _money_total(pending_review),
        "ready_to_post_count": len(ready_to_post),
        "ready_to_post_amount": _money_total(ready_to_post),
        "posted_count": len(posted),
        "needs_follow_up_count": len(needs_follow_up),
        "open_receivable_count": len(open_receivables),
        "open_receivable_total": _money_total(open_receivables, "remaining_amount"),
        "open_receivable_billed_count": len(open_receivable_billed),
        "open_receivable_unbilled_count": len(open_receivable_unbilled),
        "open_payable_count": len(open_payables),
        "open_payable_total": _money_total(open_payables, "remaining_amount"),
        "mismatch_count": len(mismatches),
        "manual_doc_gap_count": len(manual_doc_gaps),
        "bridge_candidate_count": len(bridge_candidates),
    }

    return {
        "summary": summary,
        "pending_review": pending_review[:20],
        "ready_to_post": ready_to_post[:20],
        "needs_follow_up": needs_follow_up[:20],
        "open_receivables": open_receivables[:20],
        "open_receivable_billed": open_receivable_billed[:20],
        "open_receivable_unbilled": open_receivable_unbilled[:20],
        "open_payables": open_payables[:20],
        "mismatches": mismatches[:20],
        "manual_doc_gaps": manual_doc_gaps[:20],
        "bridge_candidates": bridge_candidates[:20],
    }
