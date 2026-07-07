from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO
from typing import Any, Dict, Iterable, List, Mapping, Optional

from flask import Response

from app.models.accounting import FixedAssetPurchase, Journal
from app.models.finance import (
    BankAccount,
    CashBankAdjustment,
    CashBankOpeningBalance,
    CashBankTransaction,
    CashBankTransfer,
    Invoice,
    InvoiceCollectionLog,
    Payment,
    SupplierBill,
    SupplierPayment,
    TransportVehicleExpense,
)
from app.models.logistics import Procurement
from app.models.master import Client, Mandor, Supplier
from app.services.digital_attachment_service import count_reference_attachments

CUSTOMER_PAYMENT_ATTACHMENT_MODULE = "CUSTOMER_PAYMENT"
CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE = "PAYMENT"


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return "YA" if value else "TIDAK"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def make_csv_response(filename: str, headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> Response:
    """Build an Excel-friendly CSV response without writing files to disk."""
    buffer = StringIO()
    buffer.write("\ufeff")
    buffer.write("sep=;\r\n")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([_csv_value(header) for header in headers])
    for row in rows:
        writer.writerow([_csv_value(value) for value in row])

    response = Response(buffer.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Cache-Control"] = "no-store"
    return response


def _today_suffix() -> str:
    return date.today().strftime("%Y%m%d")


def _safe_name(obj: Any) -> str:
    if not obj:
        return "-"
    for attr in ("name", "full_name", "supplier_name", "account_name", "bank_name"):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return f"ID {getattr(obj, 'id', '-')}"


def _invoice_bill_to(invoice: Invoice, client_map: Mapping[int, Client], mandor_map: Mapping[int, Mandor]) -> str:
    bill_to_type = str(invoice.bill_to_type or "").upper()
    if bill_to_type == "CLIENT" and invoice.client_id:
        return _safe_name(client_map.get(invoice.client_id))
    if bill_to_type == "MANDOR" and invoice.mandor_id:
        return _safe_name(mandor_map.get(invoice.mandor_id))
    return "-"


def build_invoice_export_response(branch_id: int) -> Response:
    invoices = (
        Invoice.query
        .filter(Invoice.branch_id == branch_id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .all()
    )

    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    rows: List[List[Any]] = []
    for invoice in invoices:
        rows.append([
            invoice.invoice_number,
            invoice.source_type or "-",
            invoice.period_start,
            invoice.period_end,
            invoice.invoice_date,
            invoice.due_date,
            invoice.bill_to_type,
            _invoice_bill_to(invoice, client_map, mandor_map),
            invoice.total_amount or 0,
            invoice.paid_amount or 0,
            invoice.remaining_amount or 0,
            invoice.status or "-",
            invoice.notes or "",
            invoice.created_at,
        ])

    return make_csv_response(
        filename=f"finance_invoice_list_{_today_suffix()}.csv",
        headers=[
            "Nomor Invoice",
            "Sumber/Jenis",
            "Periode Awal",
            "Periode Akhir",
            "Tanggal Invoice",
            "Jatuh Tempo",
            "Ditagihkan Ke Tipe",
            "Ditagihkan Ke Nama",
            "Total",
            "Dibayar",
            "Sisa",
            "Status",
            "Catatan",
            "Dibuat Pada",
        ],
        rows=rows,
    )


def build_payment_history_export_response(branch_id: int) -> Response:
    payments = (
        Payment.query
        .filter(Payment.branch_id == branch_id)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )

    invoice_ids = {payment.invoice_id for payment in payments if payment.invoice_id}
    invoices = Invoice.query.filter(Invoice.id.in_(invoice_ids)).all() if invoice_ids else []
    invoice_map = {invoice.id: invoice for invoice in invoices}

    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    bank_ids = {payment.bank_account_id for payment in payments if payment.bank_account_id}
    bank_map = {bank.id: bank for bank in BankAccount.query.filter(BankAccount.id.in_(bank_ids)).all()} if bank_ids else {}

    journals = Journal.query.filter(
        Journal.reference_type == "PAYMENT",
        Journal.reference_id.in_([payment.id for payment in payments]) if payments else False,
    ).all() if payments else []
    journal_map = {journal.reference_id: journal for journal in journals}

    ledger_transactions = CashBankTransaction.query.filter(
        CashBankTransaction.branch_id == branch_id,
        CashBankTransaction.reference_type == "PAYMENT",
        CashBankTransaction.reference_id.in_([payment.id for payment in payments]) if payments else False,
    ).all() if payments else []
    ledger_map = {transaction.reference_id: transaction for transaction in ledger_transactions}

    rows: List[List[Any]] = []
    for payment in payments:
        invoice = invoice_map.get(payment.invoice_id)
        client_name = _safe_name(client_map.get(invoice.client_id)) if invoice and invoice.client_id else "-"
        mandor_name = _safe_name(mandor_map.get(invoice.mandor_id)) if invoice and invoice.mandor_id else "-"
        bank = bank_map.get(payment.bank_account_id)
        journal = journal_map.get(payment.id)
        ledger_transaction = ledger_map.get(payment.id)

        rows.append([
            payment.payment_date,
            payment.payment_number,
            invoice.invoice_number if invoice else f"Invoice ID {payment.invoice_id}",
            client_name,
            mandor_name,
            payment.payment_method or "-",
            f"{bank.bank_name} - {bank.account_name}" if bank else ("Kas" if str(payment.payment_method or "").upper() == "CASH" else "-"),
            payment.reference_number or "",
            payment.amount or 0,
            journal.journal_number if journal else "BELUM ADA",
            "TERCATAT" if ledger_transaction else "BELUM ADA",
            ledger_transaction.account_type if ledger_transaction else "",
            ledger_transaction.transaction_type if ledger_transaction else "",
            invoice.status if invoice else "-",
            count_reference_attachments(
                module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                reference_id=payment.id,
                branch_id=branch_id,
            ),
            payment.notes or "",
            payment.created_at,
        ])

    return make_csv_response(
        filename=f"finance_payment_history_{_today_suffix()}.csv",
        headers=[
            "Tanggal Bayar",
            "Nomor Payment",
            "Nomor Invoice",
            "Client",
            "Mandor/PIC",
            "Metode",
            "Kas/Rekening",
            "Nomor Referensi",
            "Nominal",
            "Nomor Jurnal",
            "Status Ledger",
            "Ledger Akun",
            "Ledger Tipe",
            "Status Invoice",
            "Jumlah Bukti Digital",
            "Catatan",
            "Dibuat Pada",
        ],
        rows=rows,
    )


def _normalize_filter(value: Optional[str], allowed: Iterable[str], default: str = "ALL") -> str:
    normalized = str(value or default).strip().upper()
    return normalized if normalized in set(allowed) else default


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _cash_bank_query(branch_id: int, args: Mapping[str, Any]):
    selected_transaction_type = _normalize_filter(args.get("transaction_type"), ["ALL", "IN", "OUT"])
    selected_account_type = _normalize_filter(args.get("account_type"), ["ALL", "CASH", "BANK"])
    selected_reference_type = _normalize_filter(
        args.get("reference_type"),
        ["ALL", "PAYMENT", "PROCUREMENT", "SUPPLIER_PAYMENT", "OPENING_BALANCE", "CASH_BANK_TRANSFER", "CASH_BANK_ADJUSTMENT", "FIXED_ASSET_PURCHASE", "TRANSPORT_VEHICLE_EXPENSE"],
    )
    selected_reconciliation_status = _normalize_filter(args.get("reconciliation_status"), ["ALL", "RECONCILED", "UNRECONCILED"])
    selected_bank_account_id = str(args.get("bank_account_id") or "ALL").strip()
    start_date = _parse_date(args.get("start_date"))
    end_date = _parse_date(args.get("end_date"))

    query = CashBankTransaction.query.filter(CashBankTransaction.branch_id == branch_id)

    if selected_transaction_type != "ALL":
        query = query.filter(CashBankTransaction.transaction_type == selected_transaction_type)
    if selected_account_type != "ALL":
        query = query.filter(CashBankTransaction.account_type == selected_account_type)
    if selected_reference_type != "ALL":
        query = query.filter(CashBankTransaction.reference_type == selected_reference_type)
    if selected_reconciliation_status == "RECONCILED":
        query = query.filter(CashBankTransaction.is_reconciled.is_(True))
    elif selected_reconciliation_status == "UNRECONCILED":
        query = query.filter(CashBankTransaction.is_reconciled.is_(False))
    if selected_bank_account_id != "ALL":
        try:
            query = query.filter(CashBankTransaction.bank_account_id == int(selected_bank_account_id))
        except (TypeError, ValueError):
            pass
    if start_date:
        query = query.filter(CashBankTransaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(CashBankTransaction.transaction_date <= end_date)

    return query.order_by(CashBankTransaction.transaction_date.desc(), CashBankTransaction.id.desc())


def _build_source_maps(branch_id: int, transactions: Iterable[CashBankTransaction]) -> Dict[str, Dict[int, Any]]:
    reference_ids: Dict[str, set[int]] = {
        "PAYMENT": set(),
        "PROCUREMENT": set(),
        "SUPPLIER_PAYMENT": set(),
        "OPENING_BALANCE": set(),
        "CASH_BANK_TRANSFER": set(),
        "CASH_BANK_ADJUSTMENT": set(),
        "FIXED_ASSET_PURCHASE": set(),
        "TRANSPORT_VEHICLE_EXPENSE": set(),
    }

    for transaction in transactions:
        reference_type = str(transaction.reference_type or "").upper()
        if reference_type in reference_ids and transaction.reference_id:
            reference_ids[reference_type].add(transaction.reference_id)

    maps: Dict[str, Dict[int, Any]] = {key: {} for key in reference_ids}

    if reference_ids["PAYMENT"]:
        maps["PAYMENT"] = {
            payment.id: payment
            for payment in Payment.query.filter(Payment.branch_id == branch_id, Payment.id.in_(reference_ids["PAYMENT"])).all()
        }
    if reference_ids["PROCUREMENT"]:
        maps["PROCUREMENT"] = {
            procurement.id: procurement
            for procurement in Procurement.query.filter(Procurement.branch_id == branch_id, Procurement.id.in_(reference_ids["PROCUREMENT"])).all()
        }
    if reference_ids["SUPPLIER_PAYMENT"]:
        maps["SUPPLIER_PAYMENT"] = {
            payment.id: payment
            for payment in SupplierPayment.query.filter(SupplierPayment.branch_id == branch_id, SupplierPayment.id.in_(reference_ids["SUPPLIER_PAYMENT"])).all()
        }
    if reference_ids["OPENING_BALANCE"]:
        maps["OPENING_BALANCE"] = {
            opening.id: opening
            for opening in CashBankOpeningBalance.query.filter(CashBankOpeningBalance.branch_id == branch_id, CashBankOpeningBalance.id.in_(reference_ids["OPENING_BALANCE"])).all()
        }
    if reference_ids["CASH_BANK_TRANSFER"]:
        maps["CASH_BANK_TRANSFER"] = {
            transfer.id: transfer
            for transfer in CashBankTransfer.query.filter(CashBankTransfer.branch_id == branch_id, CashBankTransfer.id.in_(reference_ids["CASH_BANK_TRANSFER"])).all()
        }
    if reference_ids["CASH_BANK_ADJUSTMENT"]:
        maps["CASH_BANK_ADJUSTMENT"] = {
            adjustment.id: adjustment
            for adjustment in CashBankAdjustment.query.filter(CashBankAdjustment.branch_id == branch_id, CashBankAdjustment.id.in_(reference_ids["CASH_BANK_ADJUSTMENT"])).all()
        }

    if reference_ids["FIXED_ASSET_PURCHASE"]:
        maps["FIXED_ASSET_PURCHASE"] = {
            purchase.id: purchase
            for purchase in FixedAssetPurchase.query.filter(FixedAssetPurchase.branch_id == branch_id, FixedAssetPurchase.id.in_(reference_ids["FIXED_ASSET_PURCHASE"])).all()
        }

    if reference_ids["TRANSPORT_VEHICLE_EXPENSE"]:
        maps["TRANSPORT_VEHICLE_EXPENSE"] = {
            expense.id: expense
            for expense in TransportVehicleExpense.query.filter(TransportVehicleExpense.branch_id == branch_id, TransportVehicleExpense.id.in_(reference_ids["TRANSPORT_VEHICLE_EXPENSE"])).all()
        }

    return maps


def _ledger_source_label(transaction: CashBankTransaction, source_maps: Mapping[str, Mapping[int, Any]]) -> tuple[str, str]:
    reference_type = str(transaction.reference_type or "").upper()
    reference_id = transaction.reference_id

    if reference_type == "PAYMENT":
        payment = source_maps.get("PAYMENT", {}).get(reference_id)
        if payment:
            invoice = getattr(payment, "invoice", None)
            return payment.payment_number, f"Invoice {invoice.invoice_number}" if invoice else f"Payment ID {payment.id}"
    elif reference_type == "PROCUREMENT":
        procurement = source_maps.get("PROCUREMENT", {}).get(reference_id)
        if procurement:
            return procurement.procurement_number, procurement.purchase_place or procurement.supplier_name or "Pembelian barang"
    elif reference_type == "SUPPLIER_PAYMENT":
        supplier_payment = source_maps.get("SUPPLIER_PAYMENT", {}).get(reference_id)
        if supplier_payment:
            bill = getattr(supplier_payment, "supplier_bill", None)
            return supplier_payment.payment_number, f"Hutang {bill.bill_number} - {bill.supplier_name}" if bill else f"Supplier Payment ID {supplier_payment.id}"
    elif reference_type == "OPENING_BALANCE":
        opening = source_maps.get("OPENING_BALANCE", {}).get(reference_id)
        return "Saldo Awal", opening.notes if opening and opening.notes else "Saldo awal kas/bank"
    elif reference_type == "CASH_BANK_TRANSFER":
        transfer = source_maps.get("CASH_BANK_TRANSFER", {}).get(reference_id)
        if transfer:
            return transfer.transfer_number, transfer.notes or "Transfer antar kas/bank"
    elif reference_type == "CASH_BANK_ADJUSTMENT":
        adjustment = source_maps.get("CASH_BANK_ADJUSTMENT", {}).get(reference_id)
        if adjustment:
            return adjustment.adjustment_number, adjustment.reason or "Penyesuaian saldo"

    elif reference_type == "FIXED_ASSET_PURCHASE":
        purchase = source_maps.get("FIXED_ASSET_PURCHASE", {}).get(reference_id)
        if purchase:
            asset_name = purchase.fixed_asset.asset_name if purchase.fixed_asset else "Aset tetap"
            return purchase.purchase_number, f"Pembelian aset tetap - {asset_name}"

    elif reference_type == "TRANSPORT_VEHICLE_EXPENSE":
        expense = source_maps.get("TRANSPORT_VEHICLE_EXPENSE", {}).get(reference_id)
        if expense:
            return expense.expense_number, f"Transport/BBM COA {expense.account_code}"

    return reference_type or "-", f"Reference ID {reference_id}" if reference_id else "-"


def build_cash_bank_ledger_export_response(branch_id: int, args: Mapping[str, Any]) -> Response:
    transactions = _cash_bank_query(branch_id, args).all()
    source_maps = _build_source_maps(branch_id, transactions)

    rows: List[List[Any]] = []
    for transaction in transactions:
        source_label, source_detail = _ledger_source_label(transaction, source_maps)
        bank_account = transaction.bank_account
        transaction_type = str(transaction.transaction_type or "").upper()
        rows.append([
            transaction.transaction_date,
            transaction.account_type or "-",
            f"{bank_account.bank_name} - {bank_account.account_name}" if bank_account else ("Kas" if transaction.account_type == "CASH" else "-"),
            transaction_type,
            transaction.reference_type or "-",
            source_label,
            source_detail,
            transaction.description or "",
            transaction.amount if transaction_type == "IN" else 0,
            transaction.amount if transaction_type == "OUT" else 0,
            transaction.amount or 0,
            transaction.is_reconciled,
            transaction.reconciled_at,
            transaction.reconciliation_note or "",
            transaction.created_at,
        ])

    return make_csv_response(
        filename=f"finance_cash_bank_ledger_{_today_suffix()}.csv",
        headers=[
            "Tanggal",
            "Kas/Bank",
            "Rekening",
            "Tipe IN/OUT",
            "Tipe Sumber",
            "Nomor Sumber",
            "Detail Sumber",
            "Deskripsi",
            "Masuk",
            "Keluar",
            "Nominal",
            "Sudah Rekonsiliasi",
            "Tanggal Rekonsiliasi",
            "Catatan Rekonsiliasi",
            "Dibuat Pada",
        ],
        rows=rows,
    )


# === PRODUCTION_FINANCE_ADVANCED_CSV_EXPORTS ===
PROCUREMENT_ATTACHMENT_MODULE = "PROCUREMENT"
PROCUREMENT_ATTACHMENT_REFERENCE = "PROCUREMENT"
SUPPLIER_PAYMENT_ATTACHMENT_MODULE = "SUPPLIER_PAYMENT"
SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE = "SUPPLIER_PAYMENT"


def _money_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _receivable_stage(invoice: Invoice) -> Dict[str, Any]:
    """Use the live finance AR warning when available, with a safe fallback."""
    try:
        from app.routes.finance_routes import build_invoice_ar_warning
        return build_invoice_ar_warning(invoice) or {}
    except Exception:
        today = date.today()
        remaining = _money_float(getattr(invoice, "remaining_amount", 0))
        due_date = getattr(invoice, "due_date", None)
        if remaining <= 0:
            return {"stage": "PAID", "stage_label": "Lunas", "level": "NORMAL", "message": "Sudah lunas.", "action": "-"}
        if due_date:
            days_to_due = (due_date - today).days
            if days_to_due < 0:
                return {"stage": "OVERDUE", "stage_label": "Overdue", "level": "URGENT", "message": f"Lewat jatuh tempo {abs(days_to_due)} hari.", "action": "Follow up penagihan."}
            if days_to_due <= 3:
                return {"stage": "DUE_SOON", "stage_label": "Reminder Jatuh Tempo", "level": "REMINDER", "message": f"Jatuh tempo dalam {days_to_due} hari.", "action": "Kirim reminder."}
        return {"stage": "NORMAL_UNPAID", "stage_label": "Belum Jatuh Tempo", "level": "NORMAL", "message": "Belum lunas.", "action": "Pantau."}


def _receivable_match_filter(stage: str, filter_key: str) -> bool:
    stage = stage or ""
    filter_key = (filter_key or "ALL").upper()

    if filter_key == "ALL":
        return True
    if filter_key == "OVERDUE":
        return stage.startswith("OVERDUE")
    if filter_key == "DUE_SOON":
        return stage == "DUE_SOON"
    if filter_key == "FOLLOW_UP":
        return stage in [
            "NO_PAYMENT_7_DAYS",
            "FOLLOW_UP",
            "PROMISE_TO_PAY",
            "OVERDUE_1_7",
            "OVERDUE_8_14",
            "OVERDUE_15_30",
            "OVERDUE_30_PLUS",
        ]
    if filter_key == "PARTIAL_MONITOR":
        return stage in ["BELOW_EXPECTED_PAYMENT", "PARTIAL"]
    return True


def _latest_collection_log(branch_id: int, invoice_id: int):
    return (
        InvoiceCollectionLog.query
        .filter_by(branch_id=branch_id, invoice_id=invoice_id)
        .order_by(InvoiceCollectionLog.follow_up_date.desc(), InvoiceCollectionLog.id.desc())
        .first()
    )


def build_receivables_export_response(branch_id: int, args: Mapping[str, Any]) -> Response:
    from app.services.finance_receivables_service import (
        BILL_TO_TYPE_CHOICES,
        INACTIVE_INVOICE_STATUSES,
        invoice_matches_receivable_filters,
        invoice_party_context,
        parse_date_filter,
        normalize_bill_to_type_filter,
        normalize_status_filter,
    )

    selected_filter = str(args.get("filter") or "ALL").strip().upper()
    if selected_filter not in {"ALL", "OVERDUE", "DUE_SOON", "FOLLOW_UP", "PARTIAL_MONITOR"}:
        selected_filter = "ALL"
    selected_client_id = str(args.get("client_id") or "").strip()
    selected_bill_to_type = normalize_bill_to_type_filter(args.get("bill_to_type"))
    selected_status = normalize_status_filter(args.get("status"))
    selected_period_from = parse_date_filter(args.get("period_from"))
    selected_period_to = parse_date_filter(args.get("period_to"))

    invoices = (
        Invoice.query
        .filter(
            Invoice.branch_id == branch_id,
            Invoice.remaining_amount > 0,
            Invoice.status.notin_(list(INACTIVE_INVOICE_STATUSES)),
        )
        .order_by(Invoice.due_date.asc(), Invoice.id.asc())
        .all()
    )

    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    priority_map = {
        "OVERDUE_30_PLUS": 1,
        "OVERDUE_15_30": 2,
        "OVERDUE_8_14": 3,
        "OVERDUE_1_7": 4,
        "DUE_SOON": 5,
        "NO_PAYMENT_7_DAYS": 6,
        "PROMISE_TO_PAY": 7,
        "BELOW_EXPECTED_PAYMENT": 8,
        "PARTIAL": 9,
        "NORMAL_UNPAID": 10,
        "NORMAL": 11,
        "PAID": 99,
    }

    prepared_rows = []
    for invoice in invoices:
        party = invoice_party_context(invoice, client_map=client_map, mandor_map=mandor_map)

        if selected_client_id:
            client_key = str(invoice.client_id) if invoice.client_id else "NO_CLIENT"
            if client_key != selected_client_id:
                continue

        if not invoice_matches_receivable_filters(
            invoice,
            party,
            bill_to_type=selected_bill_to_type,
            status=selected_status,
            period_from=selected_period_from,
            period_to=selected_period_to,
        ):
            continue

        ar = _receivable_stage(invoice)
        stage = ar.get("stage") or "NORMAL"
        if not _receivable_match_filter(stage, selected_filter):
            continue

        prepared_rows.append((priority_map.get(stage, 50), invoice.due_date or date(2999, 12, 31), invoice.id, invoice, party, ar))

    prepared_rows.sort(key=lambda row: (row[0], row[1], row[2]))

    rows: List[List[Any]] = []
    for _, _, _, invoice, party, ar in prepared_rows:
        latest_log = _latest_collection_log(branch_id, invoice.id)
        rows.append([
            invoice.invoice_number,
            invoice.invoice_date,
            invoice.due_date,
            invoice.period_start,
            invoice.period_end,
            party.get("type_label") or "-",
            party.get("name") or "-",
            party.get("input_source_label") or "-",
            invoice.total_amount or 0,
            invoice.paid_amount or 0,
            invoice.remaining_amount or 0,
            invoice.status or "-",
            ar.get("stage") or "-",
            ar.get("stage_label") or "-",
            ar.get("level") or "-",
            ar.get("message") or "",
            ar.get("action") or "",
            latest_log.follow_up_date if latest_log else "",
            latest_log.channel if latest_log else "",
            latest_log.collection_status if latest_log else "",
            latest_log.contact_person if latest_log else "",
            latest_log.response_note if latest_log else "",
            latest_log.next_action if latest_log else "",
        ])

    return make_csv_response(
        filename=f"finance_receivables_{_today_suffix()}.csv",
        headers=[
            "Nomor Invoice",
            "Tanggal Invoice",
            "Jatuh Tempo",
            "Periode Awal",
            "Periode Akhir",
            "Tipe Pihak Ditagih",
            "Nama Pihak Ditagih",
            "Asal Invoice",
            "Total",
            "Dibayar",
            "Sisa Piutang",
            "Status Invoice",
            "Stage",
            "Label Stage",
            "Level",
            "Pesan",
            "Aksi Disarankan",
            "Follow Up Terakhir",
            "Channel Follow Up",
            "Status Follow Up",
            "Contact Person",
            "Catatan Response",
            "Next Action",
        ],
        rows=rows,
    )

def build_receivables_statement_export_response(branch_id: int, args: Mapping[str, Any]) -> Response:
    selected_client_id = str(args.get("client_id") or "").strip()

    query = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"]),
    )

    if selected_client_id:
        if selected_client_id == "NO_CLIENT":
            query = query.filter(Invoice.client_id.is_(None))
        else:
            try:
                query = query.filter(Invoice.client_id == int(selected_client_id))
            except (TypeError, ValueError):
                query = query.filter(Invoice.id == -1)

    invoices = query.order_by(Invoice.client_id.asc(), Invoice.due_date.asc(), Invoice.id.asc()).all()

    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    invoice_ids = [invoice.id for invoice in invoices]
    latest_payment_map: Dict[int, Payment] = {}
    latest_log_map: Dict[int, InvoiceCollectionLog] = {}

    if invoice_ids:
        payments = (
            Payment.query
            .filter(Payment.branch_id == branch_id, Payment.invoice_id.in_(invoice_ids))
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
            .all()
        )
        for payment in payments:
            if payment.invoice_id not in latest_payment_map:
                latest_payment_map[payment.invoice_id] = payment

        logs = (
            InvoiceCollectionLog.query
            .filter(
                InvoiceCollectionLog.branch_id == branch_id,
                InvoiceCollectionLog.invoice_id.in_(invoice_ids),
                InvoiceCollectionLog.channel != "SYSTEM",
            )
            .order_by(InvoiceCollectionLog.follow_up_date.desc(), InvoiceCollectionLog.id.desc())
            .all()
        )
        for log in logs:
            if log.invoice_id not in latest_log_map:
                latest_log_map[log.invoice_id] = log

    rows: List[List[Any]] = []
    for invoice in invoices:
        client_name = _safe_name(client_map.get(invoice.client_id)) if invoice.client_id else "Tanpa Client / Mandor"
        client = client_map.get(invoice.client_id) if invoice.client_id else None
        mandor_name = _safe_name(mandor_map.get(invoice.mandor_id)) if invoice.mandor_id else "-"
        payment = latest_payment_map.get(invoice.id)
        log = latest_log_map.get(invoice.id)
        ar = _receivable_stage(invoice)
        rows.append([
            client_name,
            getattr(client, "address", "") if client else "",
            getattr(client, "phone", "") if client else "",
            invoice.invoice_number,
            invoice.invoice_date,
            invoice.due_date,
            mandor_name,
            invoice.total_amount or 0,
            invoice.paid_amount or 0,
            invoice.remaining_amount or 0,
            invoice.status or "-",
            ar.get("stage_label") or "-",
            payment.payment_date if payment else "",
            payment.payment_number if payment else "",
            payment.amount if payment else "",
            log.follow_up_date if log else "",
            log.collection_status if log else "",
            log.contact_person if log else "",
            log.next_action if log else "",
        ])

    return make_csv_response(
        filename=f"finance_receivables_statement_{_today_suffix()}.csv",
        headers=[
            "Client",
            "Alamat Client",
            "Telepon Client",
            "Nomor Invoice",
            "Tanggal Invoice",
            "Jatuh Tempo",
            "Mandor/PIC",
            "Total Tagihan",
            "Sudah Dibayar",
            "Sisa Piutang",
            "Status Invoice",
            "Status Penagihan",
            "Tanggal Payment Terakhir",
            "Nomor Payment Terakhir",
            "Nominal Payment Terakhir",
            "Tanggal Follow Up Terakhir",
            "Status Follow Up Terakhir",
            "Contact Person",
            "Next Action",
        ],
        rows=rows,
    )
