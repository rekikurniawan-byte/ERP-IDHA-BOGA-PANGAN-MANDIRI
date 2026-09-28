from __future__ import annotations

from datetime import date
from typing import Any, Dict, Mapping, Optional

from app.models.accounting import Journal
from app.services.company_settings_service import get_company_settings


def _today() -> date:
    return date.today()


def _money_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _journal_totals(journal: Journal) -> Dict[str, Any]:
    total_debit = sum(_money_float(detail.debit) for detail in journal.details)
    total_credit = sum(_money_float(detail.credit) for detail in journal.details)
    return {
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": round(total_debit, 2) == round(total_credit, 2),
    }


def build_journal_summary_print_context(branch_id: int) -> Dict[str, Any]:
    """Build read-only print context for accounting journal summary."""
    journals = Journal.query.order_by(
        Journal.journal_date.desc(),
        Journal.id.desc(),
    ).all()

    rows = []
    total_debit = 0.0
    total_credit = 0.0
    balanced_count = 0

    for journal in journals:
        totals = _journal_totals(journal)
        total_debit += totals["total_debit"]
        total_credit += totals["total_credit"]
        if totals["is_balanced"]:
            balanced_count += 1
        rows.append({
            "journal": journal,
            "total_debit": totals["total_debit"],
            "total_credit": totals["total_credit"],
            "is_balanced": totals["is_balanced"],
        })

    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Jurnal Umum Akuntansi",
        "rows": rows,
        "summary": {
            "count": len(rows),
            "balanced_count": balanced_count,
            "unbalanced_count": len(rows) - balanced_count,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "is_balanced": round(total_debit, 2) == round(total_credit, 2),
        },
    }


def build_journal_detail_print_context(branch_id: int, journal: Journal) -> Dict[str, Any]:
    totals = _journal_totals(journal)
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Detail Jurnal Akuntansi",
        "journal": journal,
        "total_debit": totals["total_debit"],
        "total_credit": totals["total_credit"],
        "is_balanced": totals["is_balanced"],
    }


def build_trial_balance_print_context(branch_id: int, data: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Neraca Saldo",
        "data": data,
    }


def build_general_ledger_print_context(branch_id: int, data: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Buku Besar",
        "data": data,
    }


def build_income_summary_print_context(branch_id: int, data: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Laba/Rugi Ringkas",
        "data": data,
        "summary": {
            "revenue_total": data.get("revenue_total", 0),
            "expense_total": data.get("expense_total", 0),
            "net_income": data.get("net_income", 0),
            "journal_count": data.get("journal_count", 0),
            "detail_count": data.get("detail_count", 0),
            "is_period_balanced": data.get("is_period_balanced"),
            "is_trial_balanced": data.get("is_trial_balanced"),
        },
    }


# === PRODUCTION_AUDIT_TRACE_PRINT_CONTEXTS ===
def build_data_health_print_context(branch_id: int, report: Mapping[str, Any]) -> Dict[str, Any]:
    """Build read-only print context for Data Health report."""
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Data Health Check",
        "report": report,
    }


def build_daily_closing_print_context(branch_id: int, report: Mapping[str, Any]) -> Dict[str, Any]:
    """Build read-only print context for Daily Closing report."""
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Tutup Harian",
        "report": report,
    }


def build_order_to_cash_trace_print_context(branch_id: int, report: Mapping[str, Any]) -> Dict[str, Any]:
    """Build read-only print context for Order-to-Cash Trace report."""
    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Jejak Order sampai Lunas",
        "report": report,
    }
