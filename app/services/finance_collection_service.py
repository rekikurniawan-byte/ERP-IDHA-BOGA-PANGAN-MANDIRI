from app.extensions import db
from app.models.finance import InvoiceCollectionLog
from app.utils.terms import T


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _run_in_transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def create_invoice_collection_log_record(
    *,
    branch_id,
    invoice_id,
    follow_up_date,
    channel,
    contact_person,
    response_note,
    promise_date,
    next_action,
    collection_status,
    created_by,
):
    log = InvoiceCollectionLog(
        branch_id=branch_id,
        invoice_id=invoice_id,
        follow_up_date=follow_up_date,
        channel=channel,
        contact_person=contact_person,
        response_note=response_note,
        promise_date=promise_date,
        next_action=next_action,
        collection_status=collection_status,
        created_by=created_by,
    )

    db.session.add(log)
    _commit_or_rollback()
    return log


def create_receivables_statement_logs(
    *,
    invoices,
    branch_id,
    follow_up_date,
    contact_person,
    response_note_factory,
    created_by,
):
    created_count = 0
    skipped_count = 0

    def _create_logs():
        nonlocal created_count, skipped_count
        for invoice in invoices:
            existing_log = InvoiceCollectionLog.query.filter_by(
                branch_id=branch_id,
                invoice_id=invoice.id,
                follow_up_date=follow_up_date,
                collection_status="STATEMENT_SENT",
            ).first()

            if existing_log:
                skipped_count += 1
                continue

            log = InvoiceCollectionLog(
                branch_id=branch_id,
                invoice_id=invoice.id,
                follow_up_date=follow_up_date,
                channel="WHATSAPP",
                contact_person=contact_person,
                response_note=response_note_factory(invoice),
                promise_date=None,
                next_action=f"Menunggu konfirmasi jadwal pelunasan dari {T.client_lower}.",
                collection_status="STATEMENT_SENT",
                created_by=created_by,
            )
            db.session.add(log)
            created_count += 1

        return created_count, skipped_count

    return _run_in_transaction(_create_logs)
