from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from flask import Response

from app.models.accounting import Account, Journal, JournalDetail
from app.services.finance_export_service import make_csv_response
from app.utils.terms import T


def _today_suffix() -> str:
    return date.today().strftime("%Y%m%d")


def _money_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date_suffix(start_date: Optional[date] = None, end_date: Optional[date] = None) -> str:
    if start_date and end_date:
        return f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    if start_date:
        return f"from_{start_date.strftime('%Y%m%d')}"
    if end_date:
        return f"until_{end_date.strftime('%Y%m%d')}"
    return _today_suffix()


def _journal_totals(journal: Journal) -> Dict[str, Any]:
    total_debit = sum(_money_float(detail.debit) for detail in journal.details)
    total_credit = sum(_money_float(detail.credit) for detail in journal.details)
    return {
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": round(total_debit, 2) == round(total_credit, 2),
    }


def _filter_journal_query(start_date: Optional[date] = None, end_date: Optional[date] = None):
    query = Journal.query
    if start_date:
        query = query.filter(Journal.journal_date >= start_date)
    if end_date:
        query = query.filter(Journal.journal_date <= end_date)
    return query


def build_journal_summary_export_response(start_date: Optional[date] = None, end_date: Optional[date] = None) -> Response:
    journals = (
        _filter_journal_query(start_date, end_date)
        .order_by(Journal.journal_date.desc(), Journal.id.desc())
        .all()
    )

    rows: List[List[Any]] = []
    for journal in journals:
        totals = _journal_totals(journal)
        rows.append([
            journal.journal_date,
            journal.journal_number,
            journal.reference_type or "-",
            journal.reference_id,
            journal.description or "",
            totals["total_debit"],
            totals["total_credit"],
            "SEIMBANG" if totals["is_balanced"] else "TIDAK SEIMBANG",
            journal.created_by,
            journal.created_at,
        ])

    return make_csv_response(
        filename=f"accounting_journals_{_date_suffix(start_date, end_date)}.csv",
        headers=[
            "Tanggal Jurnal",
            "Nomor Jurnal",
            "Tipe Referensi",
            "ID Referensi",
            "Deskripsi",
            "Total Debit",
            "Total Credit",
            "Status Balance",
            "Created By User ID",
            "Dibuat Pada",
        ],
        rows=rows,
    )


def build_journal_details_export_response(start_date: Optional[date] = None, end_date: Optional[date] = None) -> Response:
    query = (
        JournalDetail.query
        .join(Journal, JournalDetail.journal_id == Journal.id)
        .join(Account, JournalDetail.account_id == Account.id)
    )
    if start_date:
        query = query.filter(Journal.journal_date >= start_date)
    if end_date:
        query = query.filter(Journal.journal_date <= end_date)

    details = query.order_by(
        Journal.journal_date.asc(),
        Journal.id.asc(),
        JournalDetail.id.asc(),
    ).all()

    rows: List[List[Any]] = []
    for detail in details:
        journal = detail.journal
        account = detail.account
        rows.append([
            journal.journal_date if journal else "",
            journal.journal_number if journal else "",
            journal.reference_type if journal else "",
            journal.reference_id if journal else "",
            journal.description if journal else "",
            account.account_code if account else "",
            account.account_name if account else "",
            account.account_type if account else "",
            detail.debit or 0,
            detail.credit or 0,
            detail.id,
            journal.created_at if journal else "",
        ])

    return make_csv_response(
        filename=f"accounting_journal_details_{_date_suffix(start_date, end_date)}.csv",
        headers=[
            "Tanggal Jurnal",
            "Nomor Jurnal",
            "Tipe Referensi",
            "ID Referensi",
            "Deskripsi Jurnal",
            "Kode Akun",
            "Nama Akun",
            "Tipe Akun",
            "Debit",
            "Credit",
            "ID Detail",
            "Dibuat Pada",
        ],
        rows=rows,
    )


def build_trial_balance_export_response(data: Mapping[str, Any]) -> Response:
    rows: List[List[Any]] = []
    for row in data.get("trial_rows", []):
        account = row.get("account")
        rows.append([
            account.account_code if account else "",
            account.account_name if account else "",
            account.account_type if account else "",
            row.get("period_debit", 0),
            row.get("period_credit", 0),
            row.get("trial_debit", 0),
            row.get("trial_credit", 0),
        ])

    rows.append([
        "TOTAL",
        "",
        "",
        data.get("total_period_debit", 0),
        data.get("total_period_credit", 0),
        data.get("total_trial_debit", 0),
        data.get("total_trial_credit", 0),
    ])

    return make_csv_response(
        filename=f"accounting_trial_balance_{_date_suffix(data.get('start_date'), data.get('end_date'))}.csv",
        headers=[
            "Kode Akun",
            "Nama Akun",
            "Tipe Akun",
            "Debit Periode",
            "Credit Periode",
            "Saldo Debit",
            "Saldo Credit",
        ],
        rows=rows,
    )


def build_general_ledger_export_response(data: Mapping[str, Any]) -> Response:
    rows: List[List[Any]] = []
    for row in data.get("ledger_rows", []):
        account = row.get("account")
        for detail in row.get("details", []):
            journal = detail.journal
            rows.append([
                account.account_code if account else "",
                account.account_name if account else "",
                account.account_type if account else "",
                journal.journal_date if journal else "",
                journal.journal_number if journal else "",
                journal.reference_type if journal else "",
                journal.reference_id if journal else "",
                journal.description if journal else "",
                detail.debit or 0,
                detail.credit or 0,
            ])

        if account:
            rows.append([
                account.account_code,
                f"TOTAL {account.account_name}",
                account.account_type,
                "",
                "",
                "",
                "",
                "",
                row.get("period_debit", 0),
                row.get("period_credit", 0),
            ])

    return make_csv_response(
        filename=f"accounting_general_ledger_{_date_suffix(data.get('start_date'), data.get('end_date'))}.csv",
        headers=[
            "Kode Akun",
            "Nama Akun",
            "Tipe Akun",
            "Tanggal Jurnal",
            "Nomor Jurnal",
            "Tipe Referensi",
            "ID Referensi",
            "Deskripsi",
            "Debit",
            "Credit",
        ],
        rows=rows,
    )


def build_income_summary_export_response(data: Mapping[str, Any]) -> Response:
    rows = [
        ["Periode Awal", data.get("start_date")],
        ["Periode Akhir", data.get("end_date")],
        ["Pendapatan", data.get("revenue_total", 0)],
        ["Beban/HPP", data.get("expense_total", 0)],
        ["Laba/Rugi Ringkas", data.get("net_income", 0)],
        ["Jumlah Jurnal", data.get("journal_count", 0)],
        ["Jumlah Detail Jurnal", data.get("detail_count", 0)],
        ["Total Debit Periode", data.get("total_period_debit", 0)],
        ["Total Credit Periode", data.get("total_period_credit", 0)],
        ["Status Jurnal Periode", "BALANCE" if data.get("is_period_balanced") else "TIDAK BALANCE"],
        ["Status Neraca Saldo", "BALANCE" if data.get("is_trial_balanced") else "CEK ULANG"],
    ]

    return make_csv_response(
        filename=f"accounting_income_summary_{_date_suffix(data.get('start_date'), data.get('end_date'))}.csv",
        headers=["Item", "Nilai"],
        rows=rows,
    )


def build_data_health_export_response(report: Mapping[str, Any]) -> Response:
    rows: List[List[Any]] = []
    for section in report.get("sections", []):
        for row in section.get("rows", []):
            rows.append([
                report.get("generated_at"),
                report.get("overall_status"),
                section.get("title"),
                section.get("status"),
                row.get("status"),
                row.get("check"),
                row.get("item"),
                row.get("expected"),
                row.get("actual"),
                row.get("difference"),
                row.get("note"),
            ])

    return make_csv_response(
        filename=f"accounting_data_health_{_today_suffix()}.csv",
        headers=[
            "Generated At",
            "Overall Status",
            "Section",
            "Section Status",
            "Row Status",
            "Check",
            "Data",
            "Expected",
            "Actual",
            "Selisih",
            "Catatan",
        ],
        rows=rows,
    )


def build_daily_closing_export_response(report: Mapping[str, Any]) -> Response:
    rows: List[List[Any]] = []
    for section in report.get("sections", []):
        for row in section.get("rows", []):
            rows.append([
                report.get("selected_date"),
                report.get("generated_at"),
                report.get("overall_status"),
                section.get("title"),
                section.get("status"),
                row.get("status"),
                row.get("check"),
                row.get("item"),
                row.get("expected"),
                row.get("actual"),
                row.get("note"),
            ])

    return make_csv_response(
        filename=f"accounting_daily_closing_{str(report.get('selected_date_value') or _today_suffix()).replace('-', '')}.csv",
        headers=[
            "Tanggal Closing",
            "Generated At",
            "Overall Status",
            "Section",
            "Section Status",
            "Row Status",
            "Check",
            "Data",
            "Expected",
            "Actual",
            "Catatan",
        ],
        rows=rows,
    )


def build_order_to_cash_trace_export_response(report: Mapping[str, Any]) -> Response:
    rows: List[List[Any]] = []
    selected_order = report.get("selected_order_number") or ""

    rows.append(["SUMMARY", "Generated At", report.get("generated_at"), ""])
    rows.append(["SUMMARY", "Nomor Order", selected_order, ""])
    rows.append(["SUMMARY", "Overall Status", report.get("overall_status"), ""])
    rows.append(["SUMMARY", "Status Piutang", report.get("receivable_status"), ""])

    for step in report.get("steps", []):
        rows.append(["STEP", step.get("name"), step.get("status"), step.get("note")])

    if not report.get("has_order"):
        rows.append(["EMPTY", report.get("empty_message"), "", ""])
        order_name = selected_order or "no_order"
        return make_csv_response(
            filename=f"accounting_order_to_cash_trace_{order_name}_{_today_suffix()}.csv".replace("/", "-"),
            headers=["Bagian", "Item", "Nilai", "Catatan"],
            rows=rows,
        )

    order_summary = report.get("order_summary") or {}
    order = order_summary.get("order")
    if order:
        rows.extend([
            ["ORDER", "Order Number", order.order_number, order.status],
            ["ORDER", "Tanggal Order", order.order_date, ""],
            ["ORDER", "Total Lunch", order_summary.get("total_lunch", 0), ""],
            ["ORDER", "Total Dinner", order_summary.get("total_dinner", 0), ""],
            ["ORDER", "Total Qty", order_summary.get("total_qty", 0), ""],
            ["ORDER", "Total Amount", order_summary.get("total_amount", 0), ""],
        ])

    for detail in order_summary.get("details", []):
        rows.append([
            "ORDER DETAIL",
            f"Detail #{detail.get('id')}",
            f"{T.client}: {detail.get('client_name')} | PIC: {detail.get('mandor_name')} | Lokasi: {detail.get('location_name')}",
            f"Lunch {detail.get('lunch_qty')} | Dinner {detail.get('dinner_qty')} | Total {detail.get('total_qty')} | Subtotal {detail.get('subtotal')}",
        ])

    for group_key in ["production", "delivery"]:
        group = report.get(group_key) or {}
        for row in group.get("rows", []):
            label = row.get("production_type") or row.get("delivery_number") or row.get("label") or row.get("id") or group_key
            status = row.get("status") or ""
            note_parts = []
            for key, value in row.items():
                if key.endswith("_class"):
                    continue
                if key not in {"status", "label"}:
                    note_parts.append(f"{key}={value}")
            rows.append([group_key.upper(), label, status, " | ".join(note_parts)])

    invoice = report.get("invoice") or {}
    for row in invoice.get("active_rows", []):
        invoice_obj = row.get("invoice")
        rows.append([
            "INVOICE",
            invoice_obj.invoice_number if invoice_obj else row.get("id") or "Invoice",
            invoice_obj.status if invoice_obj else row.get("status") or "",
            f"Total={row.get('total_amount')} | Paid={row.get('paid_amount')} | Remaining={row.get('remaining_amount')}",
        ])
    for journal_trace in invoice.get("invoice_journals", []):
        journal = journal_trace.get("journal")
        rows.append([
            "INVOICE JOURNAL",
            journal.journal_number if journal else "Belum ada jurnal",
            journal_trace.get("status"),
            f"Debit={journal_trace.get('total_debit')} | Credit={journal_trace.get('total_credit')}",
        ])

    payment = report.get("payment") or {}
    for row in payment.get("rows", []):
        payment_obj = row.get("payment")
        rows.append([
            "PAYMENT",
            payment_obj.payment_number if payment_obj else row.get("id") or "Payment",
            payment_obj.payment_method if payment_obj else row.get("payment_method") or "",
            f"Amount={row.get('amount')} | Date={payment_obj.payment_date if payment_obj else row.get('payment_date')}",
        ])
    for journal_trace in payment.get("payment_journals", []):
        journal = journal_trace.get("journal")
        rows.append([
            "PAYMENT JOURNAL",
            journal.journal_number if journal else "Belum ada jurnal",
            journal_trace.get("status"),
            f"Debit={journal_trace.get('total_debit')} | Credit={journal_trace.get('total_credit')}",
        ])

    order_name = selected_order or "order_trace"
    return make_csv_response(
        filename=f"accounting_order_to_cash_trace_{order_name}_{_today_suffix()}.csv".replace("/", "-"),
        headers=["Bagian", "Item", "Nilai", "Catatan"],
        rows=rows,
    )
