"""Read-only billing trace helpers for invoice/piutang flows.

This module intentionally does not mutate database state. It only builds a
human-readable trace so finance users can audit:

- REALTIME order/rekap -> invoice -> piutang -> pembayaran -> jurnal -> buku kas/bank
- MANUAL_BACKFILL buku manual -> rekap -> invoice -> piutang -> pembayaran -> jurnal -> buku kas/bank
"""
import logging

from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import CashBankTransaction, Invoice, ManualBillingBatch, Payment
from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL, INPUT_SOURCE_REALTIME
from app.services.cash_bank_service import CUSTOMER_PAYMENT_REFERENCE_TYPE
from app.services.manual_billing_service import MANUAL_BILLING_INVOICE_SOURCE
from app.utils.terms import T

logger = logging.getLogger(__name__)


SUCCESS_STATUSES = {"PAID", "LUNAS", "LOCKED", "INVOICED", "POSTED", "DONE", "BALANCED", "ADA", "LENGKAP"}
WARNING_STATUSES = {"DRAFT", "OPEN", "PARTIAL", "PARTIALLY_PAID", "PENDING", "BELUM", "BELUM ADA", "BELUM LENGKAP"}
DANGER_STATUSES = {"VOID", "VOIDED", "CANCELLED", "CANCELED", "REJECTED", "ERROR", "TIDAK BALANCE"}


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _money_value(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/billing_trace_service.py:33")
        return 0.0


def _status_class(status):
    text = _upper(status)
    if text in SUCCESS_STATUSES:
        return "status-success"
    if text in DANGER_STATUSES:
        return "status-danger"
    if text in WARNING_STATUSES:
        return "status-warning"
    return "status-muted"


def _step(key, name, status, note="", ref_type=None, ref_id=None, ref_number=None):
    return {
        "key": key,
        "name": name,
        "status": status,
        "status_class": _status_class(status),
        "note": note,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "ref_number": ref_number,
    }


def _journal_trace(reference_type, reference_id):
    """Return a safe journal trace dict for one business reference."""
    if not reference_type or not reference_id:
        return {
            "journal": None,
            "details": [],
            "total_debit": 0.0,
            "total_credit": 0.0,
            "is_balanced": False,
            "status": "Belum ada jurnal",
            "status_class": _status_class("BELUM ADA"),
        }

    journal = Journal.query.filter_by(
        reference_type=reference_type,
        reference_id=reference_id,
    ).first()

    if not journal:
        return {
            "journal": None,
            "details": [],
            "total_debit": 0.0,
            "total_credit": 0.0,
            "is_balanced": False,
            "status": "Belum ada jurnal",
            "status_class": _status_class("BELUM ADA"),
        }

    details = JournalDetail.query.join(
        Account, JournalDetail.account_id == Account.id
    ).filter(
        JournalDetail.journal_id == journal.id
    ).order_by(
        JournalDetail.id.asc()
    ).all()

    rows = []
    total_debit = 0.0
    total_credit = 0.0
    for detail in details:
        debit = _money_value(getattr(detail, "debit", 0))
        credit = _money_value(getattr(detail, "credit", 0))
        total_debit += debit
        total_credit += credit
        account = getattr(detail, "account", None)
        rows.append({
            "account_code": getattr(account, "account_code", "-"),
            "account_name": getattr(account, "account_name", "-"),
            "debit": debit,
            "credit": credit,
        })

    is_balanced = bool(rows) and round(total_debit, 2) == round(total_credit, 2)
    status = "Balance" if is_balanced else "Tidak balance"
    return {
        "journal": journal,
        "details": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": is_balanced,
        "status": status,
        "status_class": _status_class("BALANCED" if is_balanced else "TIDAK BALANCE"),
    }


def _cash_bank_trace(payment):
    if not payment or not getattr(payment, "id", None):
        return {
            "transaction": None,
            "status": "Belum ada buku kas/bank",
            "status_class": _status_class("BELUM ADA"),
        }

    transaction = CashBankTransaction.query.filter_by(
        reference_type=CUSTOMER_PAYMENT_REFERENCE_TYPE,
        reference_id=getattr(payment, "id", None),
    ).first()

    if not transaction:
        return {
            "transaction": None,
            "status": "Belum ada buku kas/bank",
            "status_class": _status_class("BELUM ADA"),
        }

    return {
        "transaction": transaction,
        "status": "Ada",
        "status_class": _status_class("ADA"),
    }


def get_manual_billing_batch_for_invoice(invoice):
    if not invoice:
        return None
    if _upper(getattr(invoice, "source_type", None)) != MANUAL_BILLING_INVOICE_SOURCE:
        return None
    source_order_id = getattr(invoice, "source_order_id", None)
    if not source_order_id:
        return None
    return ManualBillingBatch.query.filter_by(
        id=source_order_id,
        branch_id=getattr(invoice, "branch_id", None),
    ).first()


def _invoice_source_label(invoice, batch=None):
    source_type = _upper(getattr(invoice, "source_type", None))
    input_source = _upper(getattr(invoice, "input_source", None)) or INPUT_SOURCE_REALTIME
    if input_source == INPUT_SOURCE_MANUAL_BACKFILL:
        return "Input Rekap Manual dari Buku"
    if source_type == "DAILY_ORDER":
        return "Input Order Harian Realtime"
    if source_type == "PERIOD_INVOICE":
        return "Rekap Catering Bulanan Realtime"
    if source_type == MANUAL_BILLING_INVOICE_SOURCE and batch:
        return f"Rekap Tagihan {T.sub_client}"
    return source_type or "Sumber Invoice"


def _payment_rows(invoice):
    payments = Payment.query.filter_by(
        branch_id=getattr(invoice, "branch_id", None),
        invoice_id=getattr(invoice, "id", None),
    ).order_by(
        Payment.payment_date.asc(),
        Payment.id.asc(),
    ).all()

    rows = []
    all_payment_journals_exist = True
    all_ledgers_exist = True
    for payment in payments:
        journal = _journal_trace("PAYMENT", getattr(payment, "id", None))
        cash_bank = _cash_bank_trace(payment)
        if not journal["journal"]:
            all_payment_journals_exist = False
        if not cash_bank["transaction"]:
            all_ledgers_exist = False
        rows.append({
            "payment": payment,
            "journal": journal,
            "cash_bank": cash_bank,
            "is_complete": bool(journal["journal"] and cash_bank["transaction"]),
        })

    return rows, all_payment_journals_exist, all_ledgers_exist


def build_invoice_billing_trace_context(invoice):
    """Build read-only invoice trace for UI and tests."""
    if not invoice:
        return {
            "has_invoice": False,
            "steps": [],
            "payments": [],
            "invoice_journal": _journal_trace(None, None),
            "overall_status": "Belum ada invoice",
            "overall_status_class": _status_class("BELUM ADA"),
        }

    batch = get_manual_billing_batch_for_invoice(invoice)
    input_source = _upper(getattr(invoice, "input_source", None)) or INPUT_SOURCE_REALTIME
    source_type = _upper(getattr(invoice, "source_type", None))
    invoice_journal = _journal_trace("INVOICE", getattr(invoice, "id", None))
    payments, all_payment_journals_exist, all_ledgers_exist = _payment_rows(invoice)

    total_amount = _money_value(getattr(invoice, "total_amount", 0))
    paid_amount = _money_value(getattr(invoice, "paid_amount", 0))
    remaining_amount = _money_value(getattr(invoice, "remaining_amount", 0))
    invoice_status = _upper(getattr(invoice, "status", None)) or "DRAFT"

    steps = []
    source_label = _invoice_source_label(invoice, batch=batch)
    if batch:
        steps.append(_step(
            "SOURCE_RECAP",
            "Sumber Data",
            _upper(getattr(batch, "status", None)) or "ADA",
            f"{source_label}: {getattr(batch, 'batch_number', '-')}.",
            ref_type="MANUAL_BILLING_BATCH",
            ref_id=getattr(batch, "id", None),
            ref_number=getattr(batch, "batch_number", None),
        ))
    else:
        steps.append(_step(
            "SOURCE_DATA",
            "Sumber Data",
            "Ada" if source_type else "Belum jelas",
            f"{source_label}. Sumber input: {input_source}.",
            ref_type=source_type,
            ref_id=getattr(invoice, "source_order_id", None),
            ref_number=getattr(invoice, "source_order_id", None),
        ))

    if batch and input_source == INPUT_SOURCE_MANUAL_BACKFILL:
        lock_status = "Locked" if getattr(batch, "locked_at", None) else "Belum lock"
        steps.append(_step(
            "LOCK_RECAP",
            "Lock Rekap",
            lock_status,
            "Rekap manual dikunci sebelum dijadikan invoice." if getattr(batch, "locked_at", None) else "Rekap manual belum dikunci.",
            ref_type="MANUAL_BILLING_BATCH",
            ref_id=getattr(batch, "id", None),
            ref_number=getattr(batch, "batch_number", None),
        ))

    steps.append(_step(
        "INVOICE",
        "Invoice / Piutang",
        invoice_status,
        f"Total {total_amount:,.0f}; dibayar {paid_amount:,.0f}; sisa {remaining_amount:,.0f}.",
        ref_type="INVOICE",
        ref_id=getattr(invoice, "id", None),
        ref_number=getattr(invoice, "invoice_number", None),
    ))

    if remaining_amount <= 0 and total_amount > 0:
        payment_status = "Paid"
        payment_note = "Invoice sudah lunas."
    elif paid_amount > 0:
        payment_status = "Partial"
        payment_note = "Invoice sudah dibayar sebagian."
    else:
        payment_status = "Belum ada"
        payment_note = "Belum ada pembayaran invoice."
    steps.append(_step(
        "PAYMENT",
        "Pembayaran",
        payment_status,
        payment_note,
    ))

    steps.append(_step(
        "INVOICE_JOURNAL",
        "Jurnal Invoice",
        invoice_journal["status"] if invoice_journal["journal"] else "Belum ada",
        "Dr Piutang / Cr Pendapatan sudah terbentuk." if invoice_journal["journal"] else "Jurnal invoice belum ditemukan.",
        ref_type="JOURNAL",
        ref_id=getattr(invoice_journal.get("journal"), "id", None),
        ref_number=getattr(invoice_journal.get("journal"), "journal_number", None),
    ))

    # Pelunasan bukan kas/bank (potong DP/deposit, potongan pajak pelanggan) punya
    # jurnalnya sendiri dan memang tidak membuat kas masuk baru.
    non_cash = 0
    if not payments and paid_amount > 0 and getattr(invoice, "id", None):
        from app.services.invoice_payment_history_service import settlement_total

        non_cash = _money_value(settlement_total(invoice.id))
    journal_note = "Setiap pembayaran harus punya jurnal Dr Kas/Bank / Cr Piutang."
    ledger_note = "Setiap pembayaran harus punya jejak masuk di buku kas/bank."
    if payments:
        journal_status = "Lengkap" if all_payment_journals_exist else "Belum lengkap"
        ledger_status = "Lengkap" if all_ledgers_exist else "Belum lengkap"
    elif non_cash > 0:
        journal_status = "Lengkap"
        ledger_status = "Lengkap"
        journal_note = f"Pelunasan {non_cash:,.0f} lewat potong DP/deposit atau potongan pajak; dijurnal tersendiri."
        ledger_note = "Tidak ada kas masuk baru untuk pelunasan non-kas (uangnya sudah diterima/ditahan sebagai pajak)."
    else:
        journal_status = "Belum ada"
        ledger_status = "Belum ada"
    steps.append(_step(
        "PAYMENT_JOURNAL",
        "Jurnal Pembayaran",
        journal_status,
        journal_note,
    ))
    steps.append(_step(
        "CASH_BANK_LEDGER",
        "Buku Kas/Bank",
        ledger_status,
        ledger_note,
    ))

    blocking_steps = [step for step in steps if step["status_class"] == "status-danger"]
    warning_steps = [step for step in steps if step["status_class"] == "status-warning"]
    if blocking_steps:
        overall = "Perlu Perbaikan"
    elif warning_steps:
        overall = "Belum Lengkap"
    else:
        overall = "Lengkap"

    return {
        "has_invoice": True,
        "input_source": input_source,
        "source_type": source_type,
        "source_label": source_label,
        "batch": batch,
        "steps": steps,
        "payments": payments,
        "invoice_journal": invoice_journal,
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "overall_status": overall,
        "overall_status_class": _status_class(overall if overall != "Belum Lengkap" else "BELUM LENGKAP"),
    }


def build_manual_billing_batch_trace_context(batch):
    """Build read-only trace for Rekap Tagihan Mandor detail page."""
    if not batch:
        return {
            "has_batch": False,
            "has_invoice": False,
            "steps": [],
            "invoice_trace": build_invoice_billing_trace_context(None),
        }

    invoice = getattr(batch, "invoice", None)
    if not invoice and getattr(batch, "invoice_id", None):
        invoice = Invoice.query.filter_by(
            id=getattr(batch, "invoice_id", None),
            branch_id=getattr(batch, "branch_id", None),
        ).first()

    invoice_trace = build_invoice_billing_trace_context(invoice) if invoice else build_invoice_billing_trace_context(None)
    input_source = _upper(getattr(batch, "input_source", None)) or INPUT_SOURCE_REALTIME
    batch_status = _upper(getattr(batch, "status", None)) or "DRAFT"

    if batch_status == "VOID":
        lock_status = "Void"
        lock_note = "Rekap dibatalkan sebelum menjadi invoice/piutang."
        invoice_status = "Void"
        invoice_note = "Invoice/piutang tidak dibuat karena rekap sudah dibatalkan."
    else:
        lock_status = "Locked" if getattr(batch, "locked_at", None) or batch_status in {"LOCKED", "INVOICED", "PARTIALLY_PAID", "PAID"} else "Belum ada"
        lock_note = "Rekap sudah dikunci sebagai dasar tagihan." if getattr(batch, "locked_at", None) or batch_status in {"LOCKED", "INVOICED", "PARTIALLY_PAID", "PAID"} else "Rekap masih draft."
        invoice_status = _upper(getattr(invoice, "status", None)) if invoice else "Belum ada"
        invoice_note = f"Invoice {getattr(invoice, 'invoice_number', '-')} sudah terhubung." if invoice else "Belum dibuat menjadi invoice/piutang."

    steps = [
        _step(
            "BATCH_CREATED",
            "Rekap Dibuat",
            "Ada",
            f"Rekap {getattr(batch, 'batch_number', '-')} dibuat dari sumber {input_source}.",
            ref_type="MANUAL_BILLING_BATCH",
            ref_id=getattr(batch, "id", None),
            ref_number=getattr(batch, "batch_number", None),
        ),
        _step(
            "BATCH_LOCKED",
            "Lock Rekap",
            lock_status,
            lock_note,
        ),
        _step(
            "BATCH_INVOICE",
            "Invoice / Piutang",
            invoice_status,
            invoice_note,
            ref_type="INVOICE" if invoice else None,
            ref_id=getattr(invoice, "id", None) if invoice else None,
            ref_number=getattr(invoice, "invoice_number", None) if invoice else None,
        ),
    ]

    if invoice:
        steps.extend(invoice_trace["steps"][3:])

    warning_steps = [step for step in steps if step["status_class"] == "status-warning"]
    danger_steps = [step for step in steps if step["status_class"] == "status-danger"]
    if danger_steps:
        overall = "Perlu Perbaikan"
    elif warning_steps:
        overall = "Belum Lengkap"
    else:
        overall = "Lengkap"

    return {
        "has_batch": True,
        "has_invoice": bool(invoice),
        "batch": batch,
        "invoice": invoice,
        "invoice_trace": invoice_trace,
        "steps": steps,
        "overall_status": overall,
        "overall_status_class": _status_class(overall if overall != "Belum Lengkap" else "BELUM LENGKAP"),
    }
