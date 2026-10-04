"""PRODUCTION Expense/Beban Drilldown + Posting Status.

Read-only report explaining where the accounting expense number comes from.
The report intentionally uses posted JournalDetail rows as the source of truth,
then compares them with operational sources that can still affect precision.
"""
from __future__ import annotations
import logging

from collections import defaultdict
from datetime import date
from typing import Any

from flask import url_for
from sqlalchemy import or_

from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import OperationalExpense, TransportVehicleExpense
from app.services.accounting_posting_status_service import build_accounting_posting_status_report

logger = logging.getLogger(__name__)

EXPENSE_ACCOUNT_TYPES = ["EXPENSE", "COGS", "COST", "HPP"]

COMPONENTS = {
    "hpp": {
        "label": "HPP Produksi / Bahan Baku",
        "short_label": "HPP",
        "icon": "bi-box-seam",
        "tone": "danger",
        "description": "Beban bahan/HPP yang sudah masuk jurnal. Biasanya dari pemakaian bahan produksi atau akun biaya bahan baku.",
    },
    "payroll": {
        "label": "Gaji / Payroll",
        "short_label": "Gaji",
        "icon": "bi-people",
        "tone": "warning",
        "description": "Beban gaji karyawan internal yang sudah diposting dari payroll.",
    },
    "transport": {
        "label": "Transport / BBM",
        "short_label": "Transport",
        "icon": "bi-truck",
        "tone": "info",
        "description": "Biaya transportasi, BBM kendaraan, dan biaya pengiriman yang sudah masuk jurnal.",
    },
    "operational": {
        "label": "Operasional Dapur / Utilitas",
        "short_label": "Operasional",
        "icon": "bi-shop-window",
        "tone": "primary",
        "description": "Biaya operasional dapur seperti listrik, air, gas, perawatan, dan biaya operasional umum.",
    },
    "depreciation": {
        "label": "Penyusutan",
        "short_label": "Penyusutan",
        "icon": "bi-building-gear",
        "tone": "secondary",
        "description": "Beban penyusutan aset tetap yang sudah diposting ke jurnal penyusutan.",
    },
    "packaging": {
        "label": "Kemasan / Packaging",
        "short_label": "Kemasan",
        "icon": "bi-bag-check",
        "tone": "success",
        "description": "Biaya kertas nasi, box, plastik, dan perlengkapan kemasan yang sudah masuk jurnal.",
    },
    "administration": {
        "label": "Administrasi",
        "short_label": "Administrasi",
        "icon": "bi-file-earmark-text",
        "tone": "muted",
        "description": "Biaya administrasi operasional yang sudah masuk jurnal.",
    },
    "other": {
        "label": "Lain-lain / Pajak / Koreksi",
        "short_label": "Lain-lain",
        "icon": "bi-three-dots",
        "tone": "dark",
        "description": "Beban lain yang belum masuk kategori utama, termasuk pajak/koreksi/manual journal.",
    },
}


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/accounting_expense_drilldown_service.py:85")
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _expense_amount(detail: JournalDetail) -> float:
    return max(_money(detail.debit) - _money(detail.credit), 0.0)


def _component_key(account: Account | None, journal: Journal | None) -> str:
    code = _upper(getattr(account, "account_code", ""))
    name = _text(getattr(account, "account_name", ""))
    reference_type = _upper(getattr(journal, "reference_type", ""))
    desc = _text(getattr(journal, "description", ""))
    haystack = " ".join([code.lower(), name, reference_type.lower(), desc])

    if reference_type == "HPP_PRODUKSI" or code == "5001" or "hpp" in haystack or "bahan baku" in haystack:
        return "hpp"
    if reference_type == "PAYROLL" or code == "5004" or "gaji" in haystack or "payroll" in haystack:
        return "payroll"
    if reference_type == "TRANSPORT_VEHICLE_EXPENSE" or code in ["5003", "5011"] or "transport" in haystack or "bbm" in haystack or "kendaraan" in haystack:
        return "transport"
    if reference_type == "FIXED_ASSET_DEPRECIATION" or code == "5012" or "penyusutan" in haystack:
        return "depreciation"
    if code == "5010" or "kemasan" in haystack or "packaging" in haystack:
        return "packaging"
    if code == "5008" or "administrasi" in haystack:
        return "administration"
    if code in ["5002", "5005", "5006", "5007"] or any(word in haystack for word in ["operasional", "dapur", "listrik", "air", "gas", "lpg", "perawatan"]):
        return "operational"
    return "other"


def _component_template(key: str) -> dict[str, Any]:
    meta = COMPONENTS[key]
    return {
        "key": key,
        "label": meta["label"],
        "short_label": meta["short_label"],
        "icon": meta["icon"],
        "tone": meta["tone"],
        "description": meta["description"],
        "amount": 0.0,
        "journal_count": 0,
        "detail_count": 0,
        "accounts": {},
        "rows": [],
        "percent": 0.0,
    }


def _journal_url(journal: Journal | None) -> str | None:
    if not journal:
        return None
    try:
        return url_for("accounting.journal_detail", journal_id=journal.id)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/accounting_expense_drilldown_service.py:148")
        return None


def _build_posted_expense_components(start_date: date, end_date: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    components = {key: _component_template(key) for key in COMPONENTS.keys()}

    details = (
        JournalDetail.query
        .join(Journal, JournalDetail.journal_id == Journal.id)
        .join(Account, JournalDetail.account_id == Account.id)
        .filter(Journal.journal_date >= start_date)
        .filter(Journal.journal_date <= end_date)
        .filter(Account.account_type.in_(EXPENSE_ACCOUNT_TYPES))
        .filter(or_(Journal.reference_type.is_(None), Journal.reference_type != "PERIOD_CLOSING"))
        .order_by(Journal.journal_date.desc(), Journal.id.desc(), JournalDetail.id.desc())
        .all()
    )

    total = 0.0
    seen_journals_by_component: dict[str, set[int]] = defaultdict(set)
    rows: list[dict[str, Any]] = []

    for detail in details:
        amount = _expense_amount(detail)
        if amount <= 0:
            continue
        account = detail.account
        journal = detail.journal
        key = _component_key(account, journal)
        component = components[key]
        total += amount
        component["amount"] += amount
        component["detail_count"] += 1
        if journal:
            seen_journals_by_component[key].add(journal.id)

        account_key = getattr(account, "account_code", "-") or "-"
        if account_key not in component["accounts"]:
            component["accounts"][account_key] = {
                "code": account_key,
                "name": getattr(account, "account_name", "-"),
                "type": getattr(account, "account_type", "-"),
                "amount": 0.0,
                "detail_count": 0,
            }
        component["accounts"][account_key]["amount"] += amount
        component["accounts"][account_key]["detail_count"] += 1

        row = {
            "component_key": key,
            "component_label": component["short_label"],
            "account_code": account_key,
            "account_name": getattr(account, "account_name", "-"),
            "journal_number": getattr(journal, "journal_number", "-"),
            "journal_date": getattr(journal, "journal_date", None),
            "reference_type": getattr(journal, "reference_type", "-"),
            "description": getattr(journal, "description", "-"),
            "amount": amount,
            "journal_url": _journal_url(journal),
        }
        rows.append(row)
        component["rows"].append(row)

    for key, component in components.items():
        component["journal_count"] = len(seen_journals_by_component[key])
        component["accounts"] = sorted(component["accounts"].values(), key=lambda item: item["amount"], reverse=True)
        component["rows"] = component["rows"][:12]
        component["percent"] = (component["amount"] / total * 100.0) if total else 0.0

    component_rows = list(components.values())
    component_rows.sort(key=lambda item: item["amount"], reverse=True)
    return component_rows, rows[:50], total


def _status_class(key: str) -> str:
    key = _upper(key)
    if key == "POSTED":
        return "success"
    if key in ["UNPOSTED", "WAITING"]:
        return "warning"
    if key == "BLOCKED":
        return "danger"
    return "muted"


def _source_row(*, label: str, number: str, source_date: Any, amount: float, status_key: str, reason: str, detail_url: str | None = None, helper: str = "") -> dict[str, Any]:
    return {
        "label": label,
        "number": number or "-",
        "source_date": source_date,
        "amount": _money(amount),
        "status_key": _upper(status_key),
        "status_class": _status_class(status_key),
        "reason": reason,
        "detail_url": detail_url,
        "helper": helper,
    }


def _direct_expense_precision_rows(branch_id: int, start_date: date, end_date: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    operational_expenses = (
        OperationalExpense.query
        .filter(OperationalExpense.branch_id == branch_id)
        .filter(OperationalExpense.expense_date >= start_date)
        .filter(OperationalExpense.expense_date <= end_date)
        .order_by(OperationalExpense.expense_date.desc(), OperationalExpense.id.desc())
        .all()
    )
    for expense in operational_expenses:
        if expense.journal_id and expense.cash_bank_transaction_id:
            continue
        status_key = "BLOCKED" if not expense.journal_id else "WAITING"
        missing = []
        if not expense.journal_id:
            missing.append("jurnal")
        if not expense.cash_bank_transaction_id:
            missing.append("ledger kas/bank")
        try:
            detail_url = url_for("finance.operational_expense_detail", expense_id=expense.id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_expense_drilldown_service.py:269")
            detail_url = None
        rows.append(_source_row(
            label="Biaya Operasional",
            number=expense.expense_number,
            source_date=expense.expense_date,
            amount=expense.amount,
            status_key=status_key,
            reason="Kurang " + ", ".join(missing) + ". Beban operasional belum presisi sampai trace lengkap.",
            detail_url=detail_url,
            helper=f"Akun {expense.account_code} • {expense.expense_category}",
        ))

    transport_expenses = (
        TransportVehicleExpense.query
        .filter(TransportVehicleExpense.branch_id == branch_id)
        .filter(TransportVehicleExpense.expense_date >= start_date)
        .filter(TransportVehicleExpense.expense_date <= end_date)
        .order_by(TransportVehicleExpense.expense_date.desc(), TransportVehicleExpense.id.desc())
        .all()
    )
    for expense in transport_expenses:
        if expense.journal_id and expense.cash_bank_transaction_id:
            continue
        status_key = "BLOCKED" if not expense.journal_id else "WAITING"
        missing = []
        if not expense.journal_id:
            missing.append("jurnal")
        if not expense.cash_bank_transaction_id:
            missing.append("ledger kas/bank")
        try:
            detail_url = url_for("finance.transport_expense_detail", expense_id=expense.id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/accounting_expense_drilldown_service.py:301")
            detail_url = None
        rows.append(_source_row(
            label="Transport / BBM",
            number=expense.expense_number,
            source_date=expense.expense_date,
            amount=expense.amount,
            status_key=status_key,
            reason="Kurang " + ", ".join(missing) + ". Beban transport belum presisi sampai trace lengkap.",
            detail_url=detail_url,
            helper=f"Akun {expense.account_code} • {expense.expense_type}",
        ))

    return rows


def _posting_attention_rows(branch_id: int) -> list[dict[str, Any]]:
    report = build_accounting_posting_status_report(branch_id)
    rows: list[dict[str, Any]] = []
    included_sections = {"hpp", "payroll", "depreciation", "procurement"}
    for section in report["sections"]:
        if section["key"] not in included_sections:
            continue
        for row in section["rows"]:
            status = row["status"]
            if status["key"] == "NOT_REQUIRED":
                continue
            helper = row.get("helper") or ""
            if section["key"] == "procurement":
                helper = (helper + " Catatan: pembelian biasanya menjadi persediaan dulu, bukan beban langsung; HPP muncul saat bahan dipakai.").strip()
            rows.append(_source_row(
                label=row.get("source_label") or section["title"],
                number=row.get("source_number") or "-",
                source_date=row.get("source_date"),
                amount=row.get("amount") or 0,
                status_key=status.get("key"),
                reason=status.get("reason") or "Perlu dicek.",
                detail_url=row.get("detail_url"),
                helper=helper,
            ))
    return rows


def _depreciation_not_generated_rows(branch_id: int, start_date: date, end_date: date) -> list[dict[str, Any]]:
    # Existing depreciation rows with missing journals are already caught by posting status.
    # This helper keeps the report wording clear without requiring new schedule columns.
    return []


def build_expense_drilldown_report(branch_id: int, start_date: date, end_date: date) -> dict[str, Any]:
    component_rows, detail_rows, total_expense = _build_posted_expense_components(start_date, end_date)
    unposted_rows = _direct_expense_precision_rows(branch_id, start_date, end_date)
    unposted_rows.extend(_posting_attention_rows(branch_id))
    unposted_rows.extend(_depreciation_not_generated_rows(branch_id, start_date, end_date))

    unposted_rows = sorted(
        unposted_rows,
        key=lambda item: (item["source_date"] or date.min, item["number"]),
        reverse=True,
    )[:80]

    top_component = component_rows[0] if component_rows and component_rows[0]["amount"] > 0 else None
    precision_status = "PERLU CEK" if unposted_rows else "AMAN"

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_expense": total_expense,
        "component_rows": component_rows,
        "detail_rows": detail_rows,
        "top_component": top_component,
        "unposted_rows": unposted_rows,
        "unposted_count": len(unposted_rows),
        "precision_status": precision_status,
        "explain": {
            "definition": "Beban di laporan akuntansi dihitung dari JournalDetail akun tipe EXPENSE/COGS/COST/HPP yang sudah POSTED, bukan semua kas keluar.",
            "risk": "Kalau HPP, payroll, penyusutan, transport, atau biaya operasional belum posting, angka beban bisa terlihat lebih kecil dari kondisi nyata.",
            "procurement_note": "Pembelian barang umumnya masuk persediaan terlebih dahulu. Beban/HPP baru muncul saat bahan dipakai dan jurnal HPP diposting.",
        },
    }
