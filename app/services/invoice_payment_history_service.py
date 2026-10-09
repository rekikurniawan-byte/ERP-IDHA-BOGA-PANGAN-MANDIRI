"""Satu sumber riwayat pelunasan invoice.

Invoice bisa berkurang sisanya lewat dua jalan:
- pembayaran kas/bank (tabel payments: bayar manual, bukti transfer portal);
- potongan uang muka/DP client atau deposit jaminan sub client
  (advance_settlements ber-referensi INVOICE). Uangnya sudah masuk saat
  DP/deposit diterima, jadi potongan ini tidak membuat baris kas/bank baru.

Semua yang perlu tahu "kapan dan berapa invoice ini dibayar" -- janji bayar
ditepati atau tidak, riwayat di detail kredit, detail invoice, portal --
membaca dari sini, supaya pelunasan lewat DP/deposit tidak dianggap belum bayar.
Laporan arus kas tetap membaca payments saja.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.finance import AdvanceSettlement, Payment

INVOICE_SETTLEMENT_TYPES = ("CLIENT_INVOICE", "DEPOSIT_TO_INVOICE")
SETTLEMENT_METHODS = {"CLIENT_INVOICE": "POTONG_DP", "DEPOSIT_TO_INVOICE": "POTONG_DEPOSIT"}


def invoice_settlements(invoice_ids):
    """Potongan DP/deposit ke invoice-invoice ini, terbaru dulu."""
    ids = [int(value) for value in invoice_ids or [] if value]
    if not ids:
        return []
    return (
        AdvanceSettlement.query.filter(
            AdvanceSettlement.reference_type == "INVOICE",
            AdvanceSettlement.reference_id.in_(ids),
            AdvanceSettlement.settlement_type.in_(INVOICE_SETTLEMENT_TYPES),
            AdvanceSettlement.amount > 0,
        )
        .order_by(AdvanceSettlement.settlement_date.desc(), AdvanceSettlement.id.desc())
        .all()
    )


def payment_dates_by_invoice(invoice_ids):
    """{invoice_id: [tanggal pelunasan]} dari pembayaran kas/bank dan potongan DP/deposit."""
    ids = [int(value) for value in invoice_ids or [] if value]
    dates = {}
    if not ids:
        return dates
    for invoice_id, paid_on in Payment.query.filter(
        Payment.invoice_id.in_(ids), Payment.amount > 0
    ).with_entities(Payment.invoice_id, Payment.payment_date).all():
        dates.setdefault(invoice_id, []).append(paid_on)
    for settlement in invoice_settlements(ids):
        dates.setdefault(settlement.reference_id, []).append(settlement.settlement_date)
    return dates


def settlement_total(invoice_id) -> Decimal:
    return sum((Decimal(str(row.amount or 0)) for row in invoice_settlements([invoice_id])), Decimal("0"))


def payment_events(invoice_ids, limit=None):
    """Riwayat pelunasan gabungan, terbaru dulu, sebagai dict seragam."""
    ids = [int(value) for value in invoice_ids or [] if value]
    if not ids:
        return []
    events = [
        {
            "kind": "PAYMENT",
            "invoice_id": payment.invoice_id,
            "payment_date": payment.payment_date,
            "payment_number": payment.payment_number,
            "payment_method": payment.payment_method,
            "amount": Decimal(str(payment.amount or 0)),
            "reference_number": payment.reference_number,
            "payment_id": payment.id,
        }
        for payment in Payment.query.filter(Payment.invoice_id.in_(ids), Payment.amount > 0).all()
    ]
    events.extend(
        {
            "kind": "SETTLEMENT",
            "invoice_id": settlement.reference_id,
            "payment_date": settlement.settlement_date,
            "payment_number": settlement.settlement_number,
            "payment_method": SETTLEMENT_METHODS.get(settlement.settlement_type, settlement.settlement_type),
            "amount": Decimal(str(settlement.amount or 0)),
            "reference_number": None,
            "payment_id": None,
        }
        for settlement in invoice_settlements(ids)
    )
    events.sort(key=lambda row: (row["payment_date"], row["payment_number"] or ""), reverse=True)
    return events[:limit] if limit else events
