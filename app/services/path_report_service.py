"""Ringkasan dua jalur transaksi untuk dashboard OWNER.

Keputusan owner 2026-09-27: omzet, kas masuk, dan piutang dipisah per jalur
(Kontrak / Umum), ditambah ongkir (4005) dibandingkan beban transport/BBM
(5003). Hanya membaca data -- tidak ada yang ditulis.

- Omzet    : total invoice aktif yang terbit bulan ini, per jalur yang dikunci
             di invoice.
- Kas masuk: pembayaran invoice bulan ini (per jalur invoice-nya) + uang muka
             pelanggan yang diterima bulan ini (jalur client-nya). Uang muka
             yang kemudian melunasi invoice tidak menjadi Payment, jadi tidak
             terhitung dua kali.
- Piutang  : sisa invoice aktif saat ini.
- Ongkir vs BBM: dari buku besar, yang tidak dipisah per cabang.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import AdvanceTransaction, Invoice, Payment
from app.models.master import Client
from app.services.advance_service import CLIENT_DP_RECEIVED
from app.services.pricing_service import PATH_CONTRACT, PATH_GENERAL

PATHS = (PATH_CONTRACT, PATH_GENERAL)
PATH_LABELS = {PATH_CONTRACT: "Kontrak", PATH_GENERAL: "Umum"}
INACTIVE_STATUSES = ("CANCELLED", "CANCELED")
DELIVERY_REVENUE_CODE = "4005"
TRANSPORT_EXPENSE_CODE = "5003"


def _zero_row():
    return {"revenue": Decimal("0"), "cash_in": Decimal("0"), "receivable": Decimal("0"), "invoice_count": 0}


def _money(value):
    return Decimal(str(value or 0))


def _ledger_total(account_code, column, start, end):
    total = (
        db.session.query(func.coalesce(func.sum(column), 0))
        .join(Account, Account.id == JournalDetail.account_id)
        .join(Journal, Journal.id == JournalDetail.journal_id)
        .filter(Account.account_code == account_code, Journal.journal_date >= start, Journal.journal_date <= end)
        # Jurnal tutup buku memindahkan saldo ke laba ditahan; bukan pendapatan.
        .filter(or_(Journal.reference_type.is_(None), Journal.reference_type != "PERIOD_CLOSING"))
        .scalar()
    )
    return _money(total)


def build_path_summary(branch_id, today=None):
    today = today or date.today()
    start, end = today.replace(day=1), today
    rows = {path: _zero_row() for path in PATHS}

    invoices = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.status.notin_(INACTIVE_STATUSES),
        Invoice.customer_path.in_(PATHS),
    ).all()
    for invoice in invoices:
        row = rows[invoice.customer_path]
        row["receivable"] += _money(invoice.remaining_amount)
        # Ta'zir masuk Dana Sosial, bukan omzet.
        if invoice.source_type == "TAZIR":
            continue
        if start <= invoice.invoice_date <= end:
            # PBJT titipan konsumen, bukan omzet (Fase 8).
            from app.services.tax_service import invoice_pbjt_amount

            row["revenue"] += _money(invoice.total_amount) - invoice_pbjt_amount(invoice.id)
            row["invoice_count"] += 1

    payments = (
        db.session.query(Invoice.customer_path, func.coalesce(func.sum(Payment.amount), 0))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .filter(
            Payment.branch_id == branch_id,
            Payment.payment_date >= start,
            Payment.payment_date <= end,
            Invoice.customer_path.in_(PATHS),
        )
        .group_by(Invoice.customer_path)
        .all()
    )
    for path, amount in payments:
        rows[path]["cash_in"] += _money(amount)

    prepayments = (
        db.session.query(Client.customer_path, func.coalesce(func.sum(AdvanceTransaction.amount), 0))
        .join(Client, Client.id == AdvanceTransaction.client_id)
        .filter(
            AdvanceTransaction.branch_id == branch_id,
            AdvanceTransaction.advance_type == CLIENT_DP_RECEIVED,
            AdvanceTransaction.advance_date >= start,
            AdvanceTransaction.advance_date <= end,
            Client.customer_path.in_(PATHS),
        )
        .group_by(Client.customer_path)
        .all()
    )
    for path, amount in prepayments:
        rows[path]["cash_in"] += _money(amount)

    delivery_revenue = _ledger_total(DELIVERY_REVENUE_CODE, JournalDetail.credit, start, end) - _ledger_total(
        DELIVERY_REVENUE_CODE, JournalDetail.debit, start, end
    )
    transport_expense = _ledger_total(TRANSPORT_EXPENSE_CODE, JournalDetail.debit, start, end) - _ledger_total(
        TRANSPORT_EXPENSE_CODE, JournalDetail.credit, start, end
    )
    return {
        "period_label": f"{start.strftime('%d-%m-%Y')} s/d {end.strftime('%d-%m-%Y')}",
        "rows": [{"path": path, "label": PATH_LABELS[path], **rows[path]} for path in PATHS],
        "totals": {key: sum((rows[path][key] for path in PATHS), Decimal("0")) for key in ("revenue", "cash_in", "receivable")},
        "delivery_revenue": delivery_revenue,
        "transport_expense": transport_expense,
        "delivery_gap": delivery_revenue - transport_expense,
    }
