from datetime import date, timedelta

from app.extensions import db
from app.models.canteen import WorkerDebt
from app.models.field_transaction import ManualReceivable
from app.models.finance import Invoice, InvoiceItem, ManualBillingBatch, ManualBillingBatchItem
from app.models.master import ClientPic, Mandor
from app.services.audit_log_service import record_audit_log
from app.services.canteen_service import get_debt_paid_amount, get_debt_remaining_amount
from app.services.invoice_identity_service import build_company_bank_snapshot, get_required_client_pic
from app.services.billing_input_source_service import INPUT_SOURCE_REALTIME


MANUAL_BILLING_INVOICE_SOURCE = "MANUAL_BILLING_RECAP"
MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE = "MANUAL_RECEIVABLE"
MANUAL_BILLING_SOURCE_WORKER_DEBT = "WORKER_DEBT"


def create_invoice_journal_for_invoice(invoice, created_by, commit=False):
    """Lazy accounting import so this service stays testable and avoids import cycles."""
    from app.services.accounting_service import create_invoice_journal_for_invoice as _create_invoice_journal

    return _create_invoice_journal(invoice=invoice, created_by=created_by, commit=commit)


class ManualBillingError(Exception):
    pass


def _to_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def _safe_label(obj):
    if not obj:
        return "-"
    for attr in ("name", "full_name", "party_name", "receivable_number", "transaction_number"):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return f"ID {getattr(obj, 'id', '-')}"


def generate_manual_billing_number(period_end):
    prefix = f"MBR-{period_end.strftime('%Y%m%d')}"
    counter = ManualBillingBatch.query.filter(
        ManualBillingBatch.batch_number.like(f"{prefix}-%")
    ).count() + 1

    while True:
        number = f"{prefix}-{counter:03d}"
        if not ManualBillingBatch.query.filter_by(batch_number=number).first():
            return number
        counter += 1


def generate_manual_billing_invoice_number(invoice_date):
    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1

    while True:
        number = f"{prefix}-{counter:03d}"
        if not Invoice.query.filter_by(invoice_number=number).first():
            return number
        counter += 1


def invoice_item_source_exists(source_type, source_id):
    return InvoiceItem.query.filter_by(
        source_type=source_type,
        source_id=source_id,
    ).first() is not None


def manual_billing_source_exists(source_type, source_id):
    return ManualBillingBatchItem.query.filter_by(
        source_type=source_type,
        source_id=source_id,
    ).first() is not None


def _manual_receivable_belongs_to_mandor(receivable, mandor_id):
    counterparty = getattr(receivable, "counterparty", None)
    if counterparty and int(getattr(counterparty, "linked_mandor_id", 0) or 0) == int(mandor_id):
        return True

    transaction = getattr(receivable, "field_transaction", None)
    transaction_counterparty = getattr(transaction, "counterparty", None)
    return bool(
        transaction_counterparty
        and int(getattr(transaction_counterparty, "linked_mandor_id", 0) or 0) == int(mandor_id)
    )


def collect_manual_billing_candidates(branch_id, mandor_id, period_start, period_end):
    mandor_id = int(mandor_id)
    rows = []
    blocked_rows = []

    receivables = ManualReceivable.query.filter_by(branch_id=branch_id).order_by(
        ManualReceivable.receivable_date.asc(),
        ManualReceivable.id.asc(),
    ).all()

    for receivable in receivables:
        receivable_date = getattr(receivable, "receivable_date", None)
        if not receivable_date or receivable_date < period_start or receivable_date > period_end:
            continue
        if not _manual_receivable_belongs_to_mandor(receivable, mandor_id):
            continue

        remaining = _to_float(getattr(receivable, "remaining_amount", 0))
        if remaining <= 0:
            continue

        source_type = MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE
        blocked_reason = None
        if invoice_item_source_exists(source_type, receivable.id):
            blocked_reason = "Sudah masuk invoice formal."
        elif manual_billing_source_exists(source_type, receivable.id):
            blocked_reason = "Sudah masuk rekap tagihan mandor."

        row = {
            "date": receivable_date,
            "item_type": "OTHER_RECEIVABLE",
            "description": f"Piutang manual {receivable.receivable_number} - {_safe_label(receivable)}",
            "qty": 1,
            "unit_price": remaining,
            "subtotal": remaining,
            "source_type": source_type,
            "source_id": receivable.id,
            "source_label": receivable.receivable_number,
            "blocked_reason": blocked_reason,
            "included": blocked_reason is None,
        }
        (blocked_rows if blocked_reason else rows).append(row)

    debts = WorkerDebt.query.filter_by(branch_id=branch_id).order_by(WorkerDebt.id.asc()).all()
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
        if not sale_date or sale_date < period_start or sale_date > period_end:
            continue

        remaining = _to_float(get_debt_remaining_amount(debt))
        if remaining <= 0:
            continue

        source_type = MANUAL_BILLING_SOURCE_WORKER_DEBT
        blocked_reason = None
        if invoice_item_source_exists(source_type, debt.id):
            blocked_reason = "Sudah masuk invoice formal."
        elif manual_billing_source_exists(source_type, debt.id):
            blocked_reason = "Sudah masuk rekap tagihan mandor."

        paid = _to_float(get_debt_paid_amount(debt))
        row = {
            "date": sale_date,
            "item_type": "WARUNG_DEBT",
            "description": (
                f"Hutang warung pekerja {_safe_label(worker)} | "
                f"Hutang {_to_float(debt.debt_amount):,.0f} | Dibayar {paid:,.0f} | Sisa {remaining:,.0f}"
            ),
            "qty": 1,
            "unit_price": remaining,
            "subtotal": remaining,
            "source_type": source_type,
            "source_id": debt.id,
            "source_label": _safe_label(worker),
            "blocked_reason": blocked_reason,
            "included": blocked_reason is None,
        }
        (blocked_rows if blocked_reason else rows).append(row)

    rows = sorted(rows, key=lambda item: (item["date"], item["source_type"], item["source_id"]))
    blocked_rows = sorted(blocked_rows, key=lambda item: (item["date"], item["source_type"], item["source_id"]))
    return {
        "rows": rows,
        "blocked_rows": blocked_rows,
        "total_amount": sum(_to_float(row["subtotal"]) for row in rows),
        "manual_receivable_total": sum(_to_float(row["subtotal"]) for row in rows if row["source_type"] == MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE),
        "warung_total": sum(_to_float(row["subtotal"]) for row in rows if row["source_type"] == MANUAL_BILLING_SOURCE_WORKER_DEBT),
    }


def _get_client_for_mandor(mandor):
    if not mandor:
        raise ManualBillingError("Mandor/PIC lapangan tidak ditemukan.")
    client = getattr(mandor, "client", None)
    if not client:
        raise ManualBillingError("Mandor/PIC lapangan belum terhubung ke client/perusahaan.")
    if hasattr(client, "is_active") and not client.is_active:
        raise ManualBillingError("Client/perusahaan mandor sedang nonaktif.")
    return client


def create_manual_billing_invoice(branch_id, mandor_id, period_start, period_end, client_pic_id, created_by, notes=None):
    mandor = Mandor.query.filter_by(id=int(mandor_id), branch_id=branch_id).first()
    client = _get_client_for_mandor(mandor)

    client_pic, client_pic_error = get_required_client_pic(client.id, client_pic_id)
    if client_pic_error:
        raise ManualBillingError(client_pic_error)

    candidates = collect_manual_billing_candidates(branch_id, mandor.id, period_start, period_end)
    rows = candidates["rows"]
    total_amount = _to_float(candidates["total_amount"])
    if not rows or total_amount <= 0:
        raise ManualBillingError("Tidak ada sumber manual yang valid untuk dibuat rekap tagihan mandor.")

    invoice_date = date.today()
    due_date = invoice_date + timedelta(days=7)

    batch = ManualBillingBatch(
        branch_id=branch_id,
        batch_number=generate_manual_billing_number(period_end),
        period_start=period_start,
        period_end=period_end,
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor.id,
        client_pic_id=client_pic.id,
        total_amount=total_amount,
        status="FINALIZED",
        input_source=INPUT_SOURCE_REALTIME,
        notes=notes,
        created_by=created_by,
    )

    db.session.add(batch)
    db.session.flush()

    invoice = Invoice(
        branch_id=branch_id,
        invoice_number=generate_manual_billing_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=due_date,
        period_start=period_start,
        period_end=period_end,
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor.id,
        client_pic_id=client_pic.id,
        **build_company_bank_snapshot(branch_id),
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
            f"Invoice dari rekap tagihan mandor {batch.batch_number}. "
            f"Periode {period_start.strftime('%d-%m-%Y')} s/d {period_end.strftime('%d-%m-%Y')}. "
            f"PIC lapangan: {mandor.name}. "
            "Sumber: piutang manual lapangan dan hutang warung pekerja yang belum tertagih."
        ),
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=batch.id,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=created_by,
    )

    db.session.add(invoice)
    db.session.flush()

    for row in rows:
        batch_item = ManualBillingBatchItem(
            batch=batch,
            item_type=row["item_type"],
            description=row["description"],
            qty=row["qty"],
            unit_price=row["unit_price"],
            subtotal=row["subtotal"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_date=row["date"],
            input_source=INPUT_SOURCE_REALTIME,
            source_label=row["source_label"],
        )
        invoice_item = InvoiceItem(
            invoice=invoice,
            item_type=row["item_type"],
            description=f"{batch.batch_number} | {row['description']}",
            qty=row["qty"],
            unit_price=row["unit_price"],
            subtotal=row["subtotal"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            input_source=INPUT_SOURCE_REALTIME,
        )
        db.session.add(batch_item)
        db.session.add(invoice_item)

    batch.invoice_id = invoice.id
    batch.status = "INVOICED"

    create_invoice_journal_for_invoice(invoice=invoice, created_by=created_by, commit=False)

    record_audit_log(
        module="FINANCE",
        event_type="MANUAL_BILLING_INVOICE_CREATED",
        action="CREATE",
        table_name="manual_billing_batches",
        record_id=batch.id,
        description=f"Rekap billing manual {batch.batch_number} dibuat menjadi invoice {invoice.invoice_number}.",
        metadata={
            "batch_number": batch.batch_number,
            "invoice_number": invoice.invoice_number,
            "source_type": MANUAL_BILLING_INVOICE_SOURCE,
            "input_source": INPUT_SOURCE_REALTIME,
            "item_count": len(rows),
            "total_amount": total_amount,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    return batch, invoice


def get_manual_billing_batch_for_invoice(invoice):
    if not invoice or getattr(invoice, "source_type", None) != MANUAL_BILLING_INVOICE_SOURCE:
        return None
    return ManualBillingBatch.query.filter_by(
        id=getattr(invoice, "source_order_id", None),
        invoice_id=getattr(invoice, "id", None),
    ).first()


def get_active_client_pics_for_mandor(mandor):
    client = getattr(mandor, "client", None)
    if not client:
        return []
    return ClientPic.query.filter_by(client_id=client.id, is_active=True).order_by(ClientPic.id.asc()).all()


def find_manual_billing_invoice_for_source(source_type, source_id):
    batch_item = ManualBillingBatchItem.query.filter_by(
        source_type=source_type,
        source_id=source_id,
    ).first()
    if not batch_item or not getattr(batch_item, "batch", None):
        return None

    batch = batch_item.batch
    if getattr(batch, "invoice", None):
        return batch.invoice

    invoice_id = getattr(batch, "invoice_id", None)
    if not invoice_id:
        return None
    return Invoice.query.get(invoice_id)
