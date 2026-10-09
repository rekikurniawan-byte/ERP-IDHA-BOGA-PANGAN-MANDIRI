"""Audit integrasi keuangan 2026-10-09: satu output untuk semua jalur.

- pelunasan lewat potong DP/deposit = pelunasan (janji bayar ditepati, riwayat, log);
- pembayaran manual dan dari bukti portal lewat satu fungsi yang sama;
- invoice tidak boleh tersimpan tanpa jurnal;
- pesanan yang sudah ditagih tidak bisa ditagih lagi lewat invoice per pesanan.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account, Journal
from app.models.credit import PARTY_CLIENT
from app.models.finance import CashBankTransaction, Invoice, InvoiceCollectionLog, InvoiceItem, Payment
from app.services.credit_control_service import broken_promises
from app.services.invoice_payment_history_service import payment_dates_by_invoice, payment_events

from tests.test_sharia_credit import TODAY, _fixtures, _invoice, _promise, ctx  # noqa: F401


def _journaled_invoice(f, *, due, amount=Decimal("500000")):
    """Invoice catering dengan item + jurnal piutang, seperti yang dibuat jalur resmi."""
    from app.services.accounting_service import post_invoice_journal_or_raise

    invoice = Invoice(
        branch_id=f.branch.id, invoice_number=f"INV-T-{uuid4().hex[:10]}", invoice_date=due - timedelta(days=7),
        due_date=due, bill_to_type="CLIENT", client_id=f.client.id, total_amount=amount, paid_amount=0,
        remaining_amount=amount, status="DRAFT", source_type="PERIOD_INVOICE", created_by=f.owner.id,
    )
    db.session.add(invoice)
    db.session.flush()
    db.session.add(InvoiceItem(invoice_id=invoice.id, item_type="CATERING", description="Porsi", qty=1,
                               unit_price=amount, subtotal=amount, source_type="ORDER_DETAIL", source_id=None))
    db.session.flush()
    post_invoice_journal_or_raise(invoice, f.owner.id)
    return invoice


def _ensure(code, name, kind):
    if not Account.query.filter_by(account_code=code).first():
        db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
        db.session.flush()


def test_dp_settlement_keeps_promise_and_shows_in_history(ctx):
    from app.services.advance_service import CLIENT_DP_RECEIVED, create_advance_settlement, create_advance_transaction

    from app.utils.clock import today_wib

    today = today_wib()
    _ensure("2008", "Uang Muka Pelanggan", "LIABILITY")
    f = _fixtures()
    invoice = _journaled_invoice(f, due=today - timedelta(days=5))
    _promise(f, invoice, today - timedelta(days=2), today - timedelta(days=4))
    assert broken_promises(f.branch.id, PARTY_CLIENT, f.client.id, today) != []

    _, _, advance = create_advance_transaction(
        branch_id=f.branch.id, advance_date=today - timedelta(days=6), advance_type=CLIENT_DP_RECEIVED,
        payment_method="CASH", amount=Decimal("500000"), created_by=f.owner.id, client_id=f.client.id,
    )
    create_advance_settlement(
        advance=advance, settlement_date=today - timedelta(days=3), settlement_type="CLIENT_INVOICE",
        amount=Decimal("500000"), created_by=f.owner.id, reference_id=invoice.id,
    )
    db.session.flush()

    # Janji ditepati lewat potong DP: tidak dihitung meleset (dulu: dihitung meleset).
    assert broken_promises(f.branch.id, PARTY_CLIENT, f.client.id, today) == []
    assert payment_dates_by_invoice([invoice.id])[invoice.id] == [today - timedelta(days=3)]
    events = payment_events([invoice.id])
    assert [(row["payment_method"], row["amount"]) for row in events] == [("POTONG_DP", Decimal("500000"))]
    log = InvoiceCollectionLog.query.filter_by(invoice_id=invoice.id, channel="SYSTEM").one()
    assert log.collection_status == "PAID"
    assert invoice.status == "PAID"


def test_manual_and_portal_payments_share_one_recording_path(ctx):
    from app.services.customer_payment_service import apply_customer_payment

    _ensure("1001", "Kas", "ASSET")
    f = _fixtures()
    invoice = _journaled_invoice(f, due=TODAY, amount=Decimal("300000"))
    payment = Payment(
        payment_number=f"PAY-T-{uuid4().hex[:8]}", branch_id=f.branch.id, payment_date=TODAY, invoice_id=invoice.id,
        payment_method="CASH", amount=Decimal("100000"), received_by=f.owner.id,
    )
    apply_customer_payment(invoice, payment, actor_id=f.owner.id, source_label="Pembayaran Masuk")

    assert invoice.status == "PARTIAL"
    assert invoice.paid_amount == Decimal("100000") and invoice.remaining_amount == Decimal("200000")
    assert Journal.query.filter_by(reference_type="PAYMENT", reference_id=payment.id).count() == 1
    assert CashBankTransaction.query.filter_by(reference_type="PAYMENT", reference_id=payment.id).count() == 1
    log = InvoiceCollectionLog.query.filter_by(invoice_id=invoice.id).one()
    assert log.collection_status == "PARTIAL" and log.contact_person == "SYSTEM - Pembayaran Masuk"


def test_invoice_without_journal_is_refused(ctx):
    from app.services.accounting_service import InvoiceJournalError, post_invoice_journal_or_raise

    f = _fixtures()
    invoice = _invoice(f, days_overdue=0, source_type="TIDAK_DIKENAL")
    with pytest.raises(InvoiceJournalError):
        post_invoice_journal_or_raise(invoice, f.owner.id)


def test_order_lines_already_billed_elsewhere_are_detected(ctx):
    from app.services.order_invoice_service import _already_billed_invoice_numbers

    f = _fixtures()
    period_invoice = _invoice(f, days_overdue=0)
    db.session.add(InvoiceItem(invoice_id=period_invoice.id, item_type="CATERING", description="Porsi",
                               qty=10, unit_price=25000, subtotal=250000, source_type="ORDER_DETAIL", source_id=987654321))
    db.session.flush()

    lines = [{"source_type": "ORDER_DETAIL", "source_id": 987654321}, {"source_type": "ORDER_DETAIL", "source_id": 1}]
    assert _already_billed_invoice_numbers(lines) == [period_invoice.invoice_number]
    assert _already_billed_invoice_numbers([{"source_type": "ORDER_DETAIL", "source_id": 123456789}]) == []
    assert Invoice.query.get(period_invoice.id) is not None
