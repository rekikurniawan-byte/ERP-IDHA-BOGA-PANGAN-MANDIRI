"""Satu langkah pencatatan pembayaran kas/bank invoice pelanggan.

Dipakai bayar manual dari halaman invoice dan bayar dari bukti transfer portal
yang sudah diverifikasi, supaya keduanya tidak bisa lagi berbeda: baris
pembayaran, sisa & status invoice, status rekap susulan, jurnal (Dr kas/bank
/ Cr 1004), buku kas/bank, dan log penagihan selalu tercatat bersama.
Tidak commit; pemanggil memegang batas transaksi (atomic_business_action).
"""
from __future__ import annotations

from app.extensions import db
from app.models.finance import InvoiceCollectionLog
from app.services.business_logic_guard_service import resolve_invoice_status_after_payment
from app.utils.money import money


def _rupiah(value) -> str:
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def apply_customer_payment(invoice, payment, *, actor_id, source_label):
    """Catat pembayaran ke invoice beserta jurnal, buku kas/bank, dan log. Tidak commit."""
    from app.services.accounting_service import create_payment_journal_for_payment
    from app.services.cash_bank_service import create_customer_payment_cash_bank_transaction
    from app.services.manual_backfill_billing_service import sync_manual_backfill_batch_status_from_invoice

    db.session.add(payment)
    db.session.flush()

    new_paid = money(invoice.paid_amount or 0) + money(payment.amount or 0)
    new_remaining = money(invoice.total_amount or 0) - new_paid
    if new_remaining <= 0:
        new_remaining = money(0)
    invoice.status = resolve_invoice_status_after_payment(invoice.total_amount, new_paid)
    invoice.paid_amount = new_paid
    invoice.remaining_amount = new_remaining

    sync_manual_backfill_batch_status_from_invoice(invoice, updated_by=actor_id, commit=False)
    db.session.flush()

    create_payment_journal_for_payment(payment=payment, created_by=actor_id, commit=False)
    create_customer_payment_cash_bank_transaction(payment=payment, created_by=actor_id, commit=False)

    paid_off = invoice.status == "PAID" or money(invoice.remaining_amount or 0) <= 0
    note = (
        f"Pembayaran {payment.payment_number} sebesar {_rupiah(payment.amount)} diterima melalui {payment.payment_method}. "
        + (
            f"Invoice {invoice.invoice_number} sudah lunas."
            if paid_off
            else f"Sisa piutang invoice {invoice.invoice_number}: {_rupiah(invoice.remaining_amount)}."
        )
    )
    if payment.reference_number:
        note += f" Referensi: {payment.reference_number}."
    if payment.notes:
        note += f" Catatan payment: {payment.notes}."

    log = InvoiceCollectionLog(
        branch_id=invoice.branch_id,
        invoice_id=invoice.id,
        follow_up_date=payment.payment_date,
        channel="SYSTEM",
        contact_person=f"SYSTEM - {source_label}",
        response_note=note,
        promise_date=None,
        next_action="Invoice sudah lunas. Tidak perlu follow up penagihan." if paid_off else "Follow up pelunasan sisa piutang.",
        collection_status="PAID" if paid_off else "PARTIAL",
        created_by=actor_id,
    )
    db.session.add(log)
    db.session.flush()
    return log
