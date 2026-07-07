from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional

from app.models.finance import BankAccount, CashBankTransaction, Invoice
from app.models.master import Client, Mandor, Supplier
from app.services.company_settings_service import get_company_settings
from app.services.finance_export_service import (
    _build_source_maps,
    _cash_bank_query,
    _invoice_bill_to,
    _ledger_source_label,
    _parse_date,
)


def _today() -> date:
    return date.today()


def _parse_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_filter_text(value: Any, default: str = "Semua") -> str:
    value = str(value or "").strip()
    return value if value else default


def _money_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_cash_bank_ledger_print_context(branch_id: int, args: Mapping[str, Any]) -> Dict[str, Any]:
    """Build read-only print context for cash/bank ledger.

    This mirrors the CSV filter behavior and does not write files or database rows.
    """
    transactions = list(_cash_bank_query(branch_id, args).all())
    source_maps = _build_source_maps(branch_id, transactions)

    summary = {
        "count": len(transactions),
        "total_in": 0.0,
        "total_out": 0.0,
        "net": 0.0,
        "cash_in": 0.0,
        "cash_out": 0.0,
        "cash_net": 0.0,
        "bank_in": 0.0,
        "bank_out": 0.0,
        "bank_net": 0.0,
        "reconciled_count": 0,
        "unreconciled_count": 0,
    }

    bank_summary: Dict[int, Dict[str, Any]] = {}
    rows = []

    for transaction in transactions:
        amount = _money_float(transaction.amount)
        transaction_type = str(transaction.transaction_type or "").upper()
        account_type = str(transaction.account_type or "").upper()

        if transaction.is_reconciled:
            summary["reconciled_count"] += 1
        else:
            summary["unreconciled_count"] += 1

        if transaction_type == "IN":
            summary["total_in"] += amount
            if account_type == "CASH":
                summary["cash_in"] += amount
            elif account_type == "BANK":
                summary["bank_in"] += amount
        elif transaction_type == "OUT":
            summary["total_out"] += amount
            if account_type == "CASH":
                summary["cash_out"] += amount
            elif account_type == "BANK":
                summary["bank_out"] += amount

        if account_type == "BANK" and transaction.bank_account_id:
            bank_key = transaction.bank_account_id
            if bank_key not in bank_summary:
                bank_summary[bank_key] = {
                    "bank_account": transaction.bank_account,
                    "total_in": 0.0,
                    "total_out": 0.0,
                    "net": 0.0,
                    "count": 0,
                    "reconciled_count": 0,
                    "unreconciled_count": 0,
                }
            bank_summary[bank_key]["count"] += 1
            if transaction.is_reconciled:
                bank_summary[bank_key]["reconciled_count"] += 1
            else:
                bank_summary[bank_key]["unreconciled_count"] += 1
            if transaction_type == "IN":
                bank_summary[bank_key]["total_in"] += amount
            elif transaction_type == "OUT":
                bank_summary[bank_key]["total_out"] += amount

        source_label, source_detail = _ledger_source_label(transaction, source_maps)
        bank_account = transaction.bank_account
        rows.append({
            "transaction": transaction,
            "source_label": source_label,
            "source_detail": source_detail,
            "account_display": f"{bank_account.bank_name} - {bank_account.account_name}" if bank_account else ("Kas" if account_type == "CASH" else "-"),
            "money_in": amount if transaction_type == "IN" else 0.0,
            "money_out": amount if transaction_type == "OUT" else 0.0,
        })

    summary["net"] = summary["total_in"] - summary["total_out"]
    summary["cash_net"] = summary["cash_in"] - summary["cash_out"]
    summary["bank_net"] = summary["bank_in"] - summary["bank_out"]

    for bank_row in bank_summary.values():
        bank_row["net"] = bank_row["total_in"] - bank_row["total_out"]

    bank_summary_rows = sorted(
        bank_summary.values(),
        key=lambda row: (
            row["bank_account"].bank_name if row.get("bank_account") else "",
            row["bank_account"].account_name if row.get("bank_account") else "",
        ),
    )

    selected_bank_name = "Semua Rekening"
    bank_id = _parse_int(args.get("bank_account_id"))
    if bank_id:
        bank = BankAccount.query.filter_by(branch_id=branch_id, id=bank_id).first()
        if bank:
            selected_bank_name = f"{bank.bank_name} - {bank.account_name}"

    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Buku Kas/Bank",
        "rows": rows,
        "summary": summary,
        "bank_summary": bank_summary_rows,
        "filters": {
            "transaction_type": _safe_filter_text(args.get("transaction_type"), "ALL"),
            "account_type": _safe_filter_text(args.get("account_type"), "ALL"),
            "reference_type": _safe_filter_text(args.get("reference_type"), "ALL"),
            "reconciliation_status": _safe_filter_text(args.get("reconciliation_status"), "ALL"),
            "bank_account": selected_bank_name,
            "start_date": _parse_date(args.get("start_date")),
            "end_date": _parse_date(args.get("end_date")),
        },
    }


def build_ap_aging_print_context(branch_id: int, args: Mapping[str, Any]) -> Dict[str, Any]:
    from app.services.accounts_payable_report_service import build_ap_aging_report

    as_of_date = _parse_date(args.get("as_of_date")) or _today()
    supplier_id = _parse_int(args.get("supplier_id"))
    suppliers = Supplier.query.filter_by(branch_id=branch_id).order_by(Supplier.supplier_name.asc()).all()
    selected_supplier = None
    if supplier_id:
        selected_supplier = Supplier.query.filter_by(branch_id=branch_id, id=supplier_id).first()

    report = build_ap_aging_report(branch_id=branch_id, as_of_date=as_of_date, supplier_id=supplier_id)

    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "AP Aging Hutang Supplier",
        "report": report,
        "suppliers": suppliers,
        "as_of_date": as_of_date,
        "selected_supplier_id": supplier_id,
        "selected_supplier": selected_supplier,
    }


def build_supplier_payable_card_print_context(branch_id: int, args: Mapping[str, Any]) -> Dict[str, Any]:
    from app.services.accounts_payable_report_service import build_supplier_payable_card

    supplier_key = str(args.get("supplier_key") or "").strip() or None
    start_date = _parse_date(args.get("start_date"))
    end_date = _parse_date(args.get("end_date"))
    if start_date and end_date and start_date > end_date:
        start_date = None
        end_date = None

    report = build_supplier_payable_card(
        branch_id=branch_id,
        supplier_key=supplier_key,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Kartu Hutang Supplier",
        "report": report,
        "selected_supplier_key": supplier_key,
        "start_date": start_date,
        "end_date": end_date,
    }


def build_invoice_profit_print_context(branch_id: int, args: Mapping[str, Any]) -> Dict[str, Any]:
    from app.services.invoice_profit_service import build_invoice_profit_report_index

    start_date = _parse_date(args.get("start_date"))
    end_date = _parse_date(args.get("end_date"))
    if start_date and end_date and start_date > end_date:
        start_date = None
        end_date = None

    report_index = build_invoice_profit_report_index(branch_id=branch_id, start_date=start_date, end_date=end_date)

    invoices = [row.get("invoice") for row in report_index.get("rows", []) if row.get("invoice")]
    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    rows = []
    for row in report_index.get("rows", []):
        invoice: Invoice = row.get("invoice")
        if not invoice:
            continue
        rows.append({
            "invoice": invoice,
            "summary": row.get("summary") or {},
            "bill_to": _invoice_bill_to(invoice, client_map, mandor_map),
        })

    return {
        "company_settings": get_company_settings(branch_id),
        "generated_date": _today(),
        "title": "Profit Invoice dari HPP Allocation",
        "rows": rows,
        "totals": report_index.get("totals") or {},
        "start_date": start_date,
        "end_date": end_date,
    }
