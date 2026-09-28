"""PRODUCTION Accounting Posting Status Center.

Read-only status builder that explains which operational/finance sources already
have accounting journals, which ones still need posting, and which ones are
intentionally ledger-only/non-journal events.
"""
from __future__ import annotations
import logging

from collections import Counter
from datetime import date
from typing import Any, Iterable

from flask import url_for

from app.extensions import db
from app.models.accounting import FixedAssetDepreciation, Journal
from app.models.finance import CashBankTransaction, Invoice, Payment
from app.models.hr import Payroll
from app.models.logistics import Procurement, StockMovement

logger = logging.getLogger(__name__)


POSTED = "POSTED"
UNPOSTED = "UNPOSTED"
NOT_REQUIRED = "NOT_REQUIRED"
BLOCKED = "BLOCKED"
WAITING = "WAITING"

STATUS_META = {
    POSTED: {
        "label": "Sudah Posting",
        "class": "success",
        "icon": "bi-check2-circle",
        "tone": "Aman",
    },
    UNPOSTED: {
        "label": "Belum Posting",
        "class": "warning",
        "icon": "bi-exclamation-triangle",
        "tone": "Perlu aksi",
    },
    NOT_REQUIRED: {
        "label": "Tidak Perlu Jurnal",
        "class": "muted",
        "icon": "bi-dash-circle",
        "tone": "Ledger/operasional",
    },
    BLOCKED: {
        "label": "Diblokir",
        "class": "danger",
        "icon": "bi-x-octagon",
        "tone": "Perlu koreksi data",
    },
    WAITING: {
        "label": "Menunggu Accounting",
        "class": "info",
        "icon": "bi-hourglass-split",
        "tone": "Menunggu proses",
    },
}


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/accounting_posting_status_service.py:65")
        return 0.0


def _date_value(value: Any) -> Any:
    return value if value else None


def _journal_for(reference_types: str | Iterable[str], reference_id: Any) -> Journal | None:
    if not reference_id:
        return None
    if isinstance(reference_types, str):
        reference_types = [reference_types]
    return (
        Journal.query
        .filter(Journal.reference_type.in_(list(reference_types)))
        .filter(Journal.reference_id == reference_id)
        .order_by(Journal.id.asc())
        .first()
    )


def _status(status_key: str, reason: str = "", journal: Journal | None = None) -> dict[str, Any]:
    meta = STATUS_META.get(status_key, STATUS_META[WAITING])
    journal_url = None
    if journal:
        try:
            journal_url = url_for("accounting.journal_detail", journal_id=journal.id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_posting_status_service.py:93")
            journal_url = None
    return {
        "key": status_key,
        "label": meta["label"],
        "class": meta["class"],
        "icon": meta["icon"],
        "tone": meta["tone"],
        "reason": reason,
        "journal": journal,
        "journal_url": journal_url,
        "journal_number": journal.journal_number if journal else None,
    }


def _row(
    *,
    source_type: str,
    source_label: str,
    source_number: str,
    source_date: Any,
    amount: float,
    status: dict[str, Any],
    detail_url: str | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    action_method: str = "GET",
    helper: str = "",
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_label": source_label,
        "source_number": source_number or "-",
        "source_date": _date_value(source_date),
        "amount": _money(amount),
        "status": status,
        "detail_url": detail_url,
        "action_url": action_url,
        "action_label": action_label,
        "action_method": action_method,
        "helper": helper,
    }


def _counter(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(row["status"]["key"] for row in rows)
    return {
        "total": len(rows),
        "posted": counts.get(POSTED, 0),
        "unposted": counts.get(UNPOSTED, 0),
        "not_required": counts.get(NOT_REQUIRED, 0),
        "blocked": counts.get(BLOCKED, 0),
        "waiting": counts.get(WAITING, 0),
        "attention": counts.get(UNPOSTED, 0) + counts.get(BLOCKED, 0) + counts.get(WAITING, 0),
    }


def _attention_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["status"]["key"] in [UNPOSTED, BLOCKED, WAITING]]


def _section(key: str, title: str, description: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _counter(rows)
    return {
        "key": key,
        "title": title,
        "description": description,
        "counts": counts,
        "rows": _attention_rows(rows),
        "all_rows": rows,
    }


def build_single_source_posting_status(source_type: str, source: Any) -> dict[str, Any]:
    """Small helper for detail pages to show a global posting badge."""
    source_type = str(source_type or "").upper()

    if source_type == "INVOICE":
        invoice = source
        journal = _journal_for("INVOICE", invoice.id)
        status = str(invoice.status or "").upper()
        if status in ["CANCELLED", "CANCELED"]:
            return _status(NOT_REQUIRED, "Invoice dibatalkan, tidak dihitung piutang aktif dan tidak perlu posting baru.")
        if journal:
            return _status(POSTED, "Invoice sudah membentuk jurnal piutang/pendapatan.", journal)
        if _money(invoice.total_amount) <= 0:
            return _status(BLOCKED, "Total invoice 0 atau tidak valid, posting ditahan.")
        return _status(UNPOSTED, "Invoice aktif belum punya jurnal pendapatan/piutang.")

    if source_type == "PAYMENT":
        payment = source
        journal = _journal_for("PAYMENT", payment.id)
        if journal:
            return _status(POSTED, "Pembayaran invoice sudah masuk jurnal kas/bank dan piutang.", journal)
        if _money(payment.amount) <= 0:
            return _status(BLOCKED, "Nominal payment 0 atau tidak valid.")
        return _status(UNPOSTED, "Payment belum punya jurnal penerimaan kas/bank.")

    if source_type == "PROCUREMENT":
        procurement = source
        journal = _journal_for("PROCUREMENT", procurement.id)
        if journal:
            return _status(POSTED, "Pembelian sudah membentuk jurnal persediaan dan kas/bank/hutang supplier.", journal)
        if _money(procurement.total_amount) <= 0:
            return _status(BLOCKED, "Total pembelian 0 atau tidak valid.")
        if str(procurement.purchase_type or "").upper() not in ["CASH", "CREDIT", "TRANSFER", "BANK"]:
            return _status(BLOCKED, "Tipe pembelian belum punya mapping jurnal yang aman.")
        return _status(UNPOSTED, "Pembelian belum punya jurnal procurement.")

    if source_type == "PAYROLL":
        payroll = source
        journal = _journal_for("PAYROLL", payroll.id)
        payroll_status = str(payroll.status or "").upper()
        if payroll_status == "DRAFT":
            return _status(NOT_REQUIRED, "Payroll masih DRAFT, belum wajib posting jurnal.")
        if journal:
            return _status(POSTED, "Payroll sudah dicatat sebagai beban gaji dan hutang gaji.", journal)
        if payroll_status in ["POSTED", "PAID"]:
            return _status(BLOCKED, "Status payroll sudah lanjut, tetapi jurnal PAYROLL tidak ditemukan.")
        return _status(UNPOSTED, "Payroll FINAL belum diposting sebagai hutang gaji.")

    if source_type == "PAYROLL_PAYMENT":
        payroll = source
        journal = _journal_for("PAYROLL_PAYMENT", payroll.id)
        payroll_status = str(payroll.status or "").upper()
        if payroll_status != "PAID":
            return _status(NOT_REQUIRED, "Payroll belum PAID, belum ada jurnal pembayaran yang wajib dicek.")
        if journal:
            return _status(POSTED, "Pembayaran payroll sudah punya jurnal kas/bank.", journal)
        return _status(BLOCKED, "Payroll berstatus PAID, tetapi jurnal pembayaran payroll tidak ditemukan.")

    return _status(WAITING, "Jenis sumber belum dikenali oleh Status Posting.")


def _invoice_rows(branch_id: int) -> list[dict[str, Any]]:
    rows = []
    invoices = (
        Invoice.query
        .filter(Invoice.branch_id == branch_id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .all()
    )
    for invoice in invoices:
        status = build_single_source_posting_status("INVOICE", invoice)
        try:
            detail_url = url_for("finance.invoice_detail", invoice_id=invoice.id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_posting_status_service.py:239")
            detail_url = None
        rows.append(_row(
            source_type="INVOICE",
            source_label="Invoice",
            source_number=invoice.invoice_number,
            source_date=invoice.invoice_date,
            amount=invoice.total_amount,
            status=status,
            detail_url=detail_url,
            action_url=url_for("accounting.generate_period_invoice_journals"),
            action_label="Sinkronkan Invoice",
            action_method="POST",
            helper="Membentuk Dr Piutang Usaha dan Cr Pendapatan sesuai sumber invoice.",
        ))
    return rows


def _payment_rows(branch_id: int) -> list[dict[str, Any]]:
    rows = []
    payments = (
        Payment.query
        .filter(Payment.branch_id == branch_id)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )
    for payment in payments:
        status = build_single_source_posting_status("PAYMENT", payment)
        try:
            detail_url = url_for("finance.invoice_detail", invoice_id=payment.invoice_id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_posting_status_service.py:269")
            detail_url = None
        rows.append(_row(
            source_type="PAYMENT",
            source_label="Payment Invoice",
            source_number=payment.payment_number,
            source_date=payment.payment_date,
            amount=payment.amount,
            status=status,
            detail_url=detail_url,
            action_url=url_for("accounting.generate_payment_journals"),
            action_label="Sinkronkan Payment",
            action_method="POST",
            helper="Membentuk Dr Kas/Bank dan Cr Piutang Usaha.",
        ))
    return rows


def _procurement_rows(branch_id: int) -> list[dict[str, Any]]:
    rows = []
    procurements = (
        Procurement.query
        .filter(Procurement.branch_id == branch_id)
        .order_by(Procurement.procurement_date.desc(), Procurement.id.desc())
        .all()
    )
    for procurement in procurements:
        status = build_single_source_posting_status("PROCUREMENT", procurement)
        try:
            detail_url = url_for("logistics.purchase_detail", procurement_id=procurement.id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_posting_status_service.py:299")
            detail_url = None
        rows.append(_row(
            source_type="PROCUREMENT",
            source_label="Pembelian Barang",
            source_number=procurement.procurement_number,
            source_date=procurement.procurement_date,
            amount=procurement.total_amount,
            status=status,
            detail_url=detail_url,
            action_url=url_for("accounting.generate_procurement_journals"),
            action_label="Sinkronkan Pembelian",
            action_method="POST",
            helper="Membentuk Dr Persediaan dan Cr Kas/Bank/Hutang Supplier.",
        ))
    return rows


def _hpp_rows(branch_id: int) -> list[dict[str, Any]]:
    rows = []
    movements = (
        StockMovement.query
        .filter(StockMovement.branch_id == branch_id)
        .filter(StockMovement.reference_type == "PEMAKAIAN_PRODUKSI")
        .filter(StockMovement.movement_type == "OUT")
        .order_by(StockMovement.movement_date.desc(), StockMovement.id.desc())
        .all()
    )
    for movement in movements:
        journal = _journal_for("HPP_PRODUKSI", movement.id)
        if journal:
            status = _status(POSTED, "Pemakaian produksi sudah membentuk jurnal HPP dan pengurang persediaan.", journal)
        elif _money(movement.qty) <= 0:
            status = _status(BLOCKED, "Qty pemakaian produksi 0 atau tidak valid.")
        else:
            status = _status(UNPOSTED, "Pemakaian produksi belum punya jurnal HPP_PRODUKSI.")
        item_name = movement.item.item_name if getattr(movement, "item", None) else f"Item #{movement.item_id}"
        rows.append(_row(
            source_type="HPP_PRODUKSI",
            source_label="Pemakaian Bahan Produksi",
            source_number=f"Stock Movement #{movement.id}",
            source_date=movement.movement_date,
            amount=0,
            status=status,
            detail_url=url_for("logistics.index"),
            action_url=url_for("accounting.generate_hpp_production_journals"),
            action_label="Sinkronkan HPP",
            action_method="POST",
            helper=f"{item_name} • qty {_money(movement.qty):g}. Nominal HPP dihitung dari rata-rata nilai stok saat generate.",
        ))
    return rows


def _payroll_rows(branch_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accrual_rows = []
    payment_rows = []
    payrolls = (
        Payroll.query
        .filter(Payroll.branch_id == branch_id)
        .order_by(Payroll.period_year.desc(), Payroll.period_month.desc(), Payroll.id.desc())
        .all()
    )
    for payroll in payrolls:
        period = f"{int(payroll.period_month or 0):02d}-{payroll.period_year}"
        amount = sum(_money(detail.final_salary) for detail in payroll.details)
        try:
            detail_url = url_for("hr.payroll_detail", payroll_id=payroll.id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_posting_status_service.py:366")
            detail_url = None

        accrual_rows.append(_row(
            source_type="PAYROLL",
            source_label="Payroll Hutang Gaji",
            source_number=period,
            source_date=date(int(payroll.period_year or 2000), int(payroll.period_month or 1), 1),
            amount=amount,
            status=build_single_source_posting_status("PAYROLL", payroll),
            detail_url=detail_url,
            action_url=detail_url,
            action_label="Buka Payroll",
            action_method="GET",
            helper="Payroll FINAL harus diposting menjadi Dr Beban Gaji dan Cr Hutang Gaji.",
        ))

        payment_rows.append(_row(
            source_type="PAYROLL_PAYMENT",
            source_label="Pembayaran Payroll",
            source_number=period,
            source_date=date(int(payroll.period_year or 2000), int(payroll.period_month or 1), 1),
            amount=amount,
            status=build_single_source_posting_status("PAYROLL_PAYMENT", payroll),
            detail_url=detail_url,
            action_url=detail_url,
            action_label="Buka Payroll",
            action_method="GET",
            helper="Payroll PAID harus punya jurnal pembayaran Dr Hutang Gaji dan Cr Kas/Bank.",
        ))
    return accrual_rows, payment_rows


def _depreciation_rows(branch_id: int) -> list[dict[str, Any]]:
    rows = []
    entries = (
        FixedAssetDepreciation.query
        .filter(FixedAssetDepreciation.branch_id == branch_id)
        .order_by(FixedAssetDepreciation.depreciation_date.desc(), FixedAssetDepreciation.id.desc())
        .all()
    )
    for entry in entries:
        journal = entry.journal or _journal_for("FIXED_ASSET_DEPRECIATION", entry.id)
        if journal:
            status = _status(POSTED, "Penyusutan sudah membentuk jurnal beban dan akumulasi penyusutan.", journal)
        elif _money(entry.amount) <= 0:
            status = _status(BLOCKED, "Nominal penyusutan 0 atau tidak valid.")
        else:
            status = _status(UNPOSTED, "Entry penyusutan belum punya jurnal terkait.")
        asset_label = entry.fixed_asset.asset_name if getattr(entry, "fixed_asset", None) else f"Aset #{entry.fixed_asset_id}"
        rows.append(_row(
            source_type="FIXED_ASSET_DEPRECIATION",
            source_label="Penyusutan Aset",
            source_number=entry.depreciation_number,
            source_date=entry.depreciation_date,
            amount=entry.amount,
            status=status,
            detail_url=url_for("finance.fixed_asset_depreciation"),
            action_url=url_for("finance.fixed_asset_depreciation"),
            action_label="Buka Penyusutan",
            action_method="GET",
            helper=f"{asset_label} • periode {entry.period_year}-{int(entry.period_month or 0):02d}.",
        ))
    return rows


def _ledger_only_rows(branch_id: int) -> list[dict[str, Any]]:
    ledger_only_types = ["OPENING_BALANCE", "CASH_BANK_TRANSFER", "CASH_BANK_ADJUSTMENT"]
    transactions = (
        CashBankTransaction.query
        .filter(CashBankTransaction.branch_id == branch_id)
        .filter(db.or_(
            CashBankTransaction.reference_type.in_(ledger_only_types),
            CashBankTransaction.reference_type.is_(None),
            CashBankTransaction.reference_type == "",
        ))
        .order_by(CashBankTransaction.transaction_date.desc(), CashBankTransaction.id.desc())
        .limit(25)
        .all()
    )
    rows = []
    for trx in transactions:
        rows.append(_row(
            source_type="CASH_BANK_LEDGER",
            source_label="Buku Kas/Bank",
            source_number=f"Ledger #{trx.id}",
            source_date=trx.transaction_date,
            amount=trx.amount,
            status=_status(NOT_REQUIRED, "Ini mutasi ledger kas/bank operasional. Bukan sumber jurnal akuntansi mandiri."),
            detail_url=url_for("finance.cash_bank_ledger"),
            helper=f"{trx.reference_type or 'MANUAL_LEDGER'} • {trx.description or '-'}",
        ))
    return rows


def build_accounting_posting_status_report(branch_id: int) -> dict[str, Any]:
    """Build the PRODUCTION read-only posting status report for one branch."""
    invoice_rows = _invoice_rows(branch_id)
    payment_rows = _payment_rows(branch_id)
    procurement_rows = _procurement_rows(branch_id)
    hpp_rows = _hpp_rows(branch_id)
    payroll_accrual_rows, payroll_payment_rows = _payroll_rows(branch_id)
    depreciation_rows = _depreciation_rows(branch_id)
    ledger_rows = _ledger_only_rows(branch_id)

    sections = [
        _section("invoice", "Invoice tanpa jurnal", "Invoice aktif yang belum membentuk jurnal piutang/pendapatan.", invoice_rows),
        _section("payment", "Payment tanpa jurnal", "Pembayaran invoice yang belum membentuk jurnal kas/bank dan piutang.", payment_rows),
        _section("procurement", "Procurement belum generate journal", "Pembelian barang yang belum menjadi jurnal persediaan.", procurement_rows),
        _section("hpp", "HPP / stock usage belum posting", "Pemakaian produksi yang belum membentuk jurnal HPP dan pengurang persediaan.", hpp_rows),
        _section("payroll", "Payroll FINAL belum post journal", "Payroll internal yang perlu dicatat sebagai hutang gaji.", payroll_accrual_rows),
        _section("payroll_payment", "Payroll PAID tanpa jurnal payment", "Payroll yang sudah dibayar tetapi jurnal payment-nya belum ditemukan.", payroll_payment_rows),
        _section("depreciation", "Depreciation belum post periode", "Penyusutan aset yang belum memiliki jurnal penyusutan terkait.", depreciation_rows),
        _section("ledger_only", "Cash/Bank ledger bukan jurnal accounting", "Mutasi ledger kas/bank yang sifatnya operasional dan tidak perlu jurnal mandiri.", ledger_rows),
    ]

    all_rows: list[dict[str, Any]] = []
    for section in sections:
        all_rows.extend(section["all_rows"])
    totals = _counter(all_rows)

    return {
        "generated_at": date.today(),
        "sections": sections,
        "summary": totals,
        "attention_total": totals["attention"],
        "status_meta": STATUS_META,
        "legend": [STATUS_META[key] | {"key": key} for key in [POSTED, UNPOSTED, WAITING, BLOCKED, NOT_REQUIRED]],
        "notes": [
            "Status dihitung dari reference_type/reference_id jurnal, bukan menambah kolom baru.",
            "Cash/bank ledger bisa ada walaupun bukan jurnal accounting; ledger hanya menunjukkan mutasi kas/bank.",
            "Transaksi DRAFT atau CANCELLED tidak dipaksa posting agar laporan tidak bias.",
        ],
    }



def filter_accounting_posting_status_report(report: dict[str, Any], start_date: Any = None, end_date: Any = None, status_filter: str = "ALL") -> dict[str, Any]:
    """Apply PRODUCTION read-only date/status filters to a posting status report."""
    status_filter = str(status_filter or "ALL").upper().strip()

    def keep(row: dict[str, Any]) -> bool:
        row_date = row.get("source_date")
        if start_date and row_date and row_date < start_date:
            return False
        if end_date and row_date and row_date > end_date:
            return False
        if status_filter != "ALL" and (row.get("status") or {}).get("key") != status_filter:
            return False
        return True

    filtered_sections = []
    all_rows: list[dict[str, Any]] = []
    for section in report.get("sections", []):
        rows = [row for row in section.get("all_rows", []) if keep(row)]
        new_section = dict(section)
        new_section["all_rows"] = rows
        new_section["rows"] = _attention_rows(rows)
        new_section["counts"] = _counter(rows)
        filtered_sections.append(new_section)
        all_rows.extend(rows)

    totals = _counter(all_rows)
    new_report = dict(report)
    new_report["sections"] = filtered_sections
    new_report["summary"] = totals
    new_report["attention_total"] = totals["attention"]
    new_report["fix71d_filter"] = {
        "start_date": start_date,
        "end_date": end_date,
        "status_filter": status_filter,
    }
    return new_report
