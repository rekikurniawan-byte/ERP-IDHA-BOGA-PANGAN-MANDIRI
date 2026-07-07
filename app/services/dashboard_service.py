from datetime import date

from app.models.operational import DailyOrder
from app.models.production import Production
from app.models.delivery import Delivery, DeliveryDetail
from app.models.canteen import CanteenSale, WorkerDebt
from app.services.dashboard_analytics_service import get_owner_admin_analytics_data
from app.services.dashboard_command_center_service import (
    build_admin_command_center,
    build_owner_command_center,
)
from app.services.delivery_service import get_pending_delivery_next_actions


def get_debt_paid_amount(worker_debt):
    return sum(payment.amount for payment in worker_debt.payments)


def get_debt_remaining_amount(worker_debt):
    remaining = worker_debt.debt_amount - get_debt_paid_amount(worker_debt)

    if remaining < 0:
        return 0

    return remaining


def get_owner_dashboard_data(
    analytics_year=None,
    analytics_month=None,
    include_asset_purchase=False,
    revenue_period=None,
    revenue_start_date=None,
    revenue_end_date=None,
    revenue_group_by=None,
    revenue_source=None,
    revenue_client_id=None,
    revenue_mandor_id=None,
    revenue_branch_id=None,
):
    # DASHBOARD1C_OWNER_FINAL_SERVICE
    from datetime import date, timedelta
    from sqlalchemy import text

    from app.extensions import db
    from app.models.finance import (
        CashBankTransaction,
        Invoice,
        InvoiceCollectionLog,
        Payment,
        SupplierBill,
    )
    from app.models.accounting import Journal, JournalDetail
    from app.models.operational import OrderHppSnapshot

    today = date.today()
    next_7_days = today + timedelta(days=7)

    def _safe_sum(values):
        total = 0

        for value in values:
            try:
                total += float(value or 0)
            except Exception:
                pass

        return total

    def _rollback_after_read_error():
        try:
            db.session.rollback()
        except Exception:
            pass

    def _table_count(table_name):
        try:
            return int(db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
        except Exception:
            _rollback_after_read_error()
            return 0

    def _table_count_where(table_name, where_clause):
        try:
            return int(db.session.execute(text(f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}")).scalar() or 0)
        except Exception:
            _rollback_after_read_error()
            return 0

    def _rows(sql, params=None):
        try:
            return [dict(row) for row in db.session.execute(text(sql), params or {}).mappings().all()]
        except Exception:
            _rollback_after_read_error()
            return []

    # ==================================================
    # DATA LAMA - TETAP DIPERTAHANKAN
    # ==================================================
    total_order = DailyOrder.query.count()
    total_locked_order = DailyOrder.query.filter_by(is_locked=True).count()
    total_production = Production.query.count()
    total_delivery = Delivery.query.count()

    total_cash_sales = _safe_sum(
        sale.total_amount for sale in CanteenSale.query.filter_by(sale_type="CASH").all()
    )

    total_debt_sales = _safe_sum(
        sale.total_amount for sale in CanteenSale.query.filter_by(sale_type="DEBT").all()
    )

    all_debts = WorkerDebt.query.all()
    total_worker_debt = _safe_sum(get_debt_remaining_amount(debt) for debt in all_debts)
    unpaid_debt_count = sum(1 for debt in all_debts if get_debt_remaining_amount(debt) > 0)

    today_orders = DailyOrder.query.filter_by(order_date=today).count()
    today_deliveries = Delivery.query.filter_by(delivery_date=today).count()
    today_productions = Production.query.filter_by(production_date=today).count()

    # ==================================================
    # FINANCE LOCKED SUMMARY
    # ==================================================
    all_invoices = Invoice.query.order_by(Invoice.id.asc()).all()

    active_invoices = [
        invoice for invoice in all_invoices
        if str(invoice.status or "").upper() not in ["CANCELLED", "CANCELED"]
    ]

    cancelled_invoices = [
        invoice for invoice in all_invoices
        if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]
    ]

    receivable_invoices = Invoice.query.filter(
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    ).order_by(
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    total_invoice_active = _safe_sum(invoice.total_amount for invoice in active_invoices)
    paid_invoice_active = _safe_sum(invoice.paid_amount for invoice in active_invoices)
    remaining_invoice_active = _safe_sum(invoice.remaining_amount for invoice in active_invoices)

    payments = Payment.query.order_by(Payment.payment_date.desc(), Payment.id.desc()).all()
    total_payment = _safe_sum(payment.amount for payment in payments)
    recent_payments = payments[:5]

    overdue_invoices = [
        invoice for invoice in receivable_invoices
        if invoice.due_date and invoice.due_date < today
    ]

    due_soon_invoices = [
        invoice for invoice in receivable_invoices
        if invoice.due_date and today <= invoice.due_date <= next_7_days
    ]

    # ==================================================
    # COLLECTION / SOA
    # ==================================================
    collection_logs = InvoiceCollectionLog.query.order_by(
        InvoiceCollectionLog.follow_up_date.desc(),
        InvoiceCollectionLog.id.desc()
    ).all()

    latest_collection_logs = collection_logs[:5]

    statement_sent_today = [
        log for log in collection_logs
        if log.follow_up_date == today
        and str(log.collection_status or "").upper() == "STATEMENT_SENT"
    ]

    # ==================================================
    # PRODUCTION - AP + CASH/BANK OWNER MINI SUMMARY
    # ==================================================
    supplier_bills = SupplierBill.query.order_by(
        SupplierBill.due_date.asc(),
        SupplierBill.id.desc()
    ).all()

    open_supplier_bills = [
        bill for bill in supplier_bills
        if str(bill.status or "").upper() != "PAID"
        and float(bill.remaining_amount or 0) > 0
    ]

    overdue_supplier_bills = [
        bill for bill in open_supplier_bills
        if bill.due_date and bill.due_date < today
    ]

    due_soon_supplier_bills = [
        bill for bill in open_supplier_bills
        if bill.due_date and today <= bill.due_date <= next_7_days
    ]

    total_supplier_ap = _safe_sum(bill.remaining_amount for bill in open_supplier_bills)
    overdue_supplier_ap = _safe_sum(bill.remaining_amount for bill in overdue_supplier_bills)
    due_soon_supplier_ap = _safe_sum(bill.remaining_amount for bill in due_soon_supplier_bills)

    cash_bank_transactions = CashBankTransaction.query.order_by(
        CashBankTransaction.transaction_date.desc(),
        CashBankTransaction.id.desc()
    ).all()

    cash_bank_summary = {
        "transaction_count": len(cash_bank_transactions),
        "total_in": 0,
        "total_out": 0,
        "net": 0,
        "cash_in": 0,
        "cash_out": 0,
        "cash_net": 0,
        "bank_in": 0,
        "bank_out": 0,
        "bank_net": 0,
        "recent_transactions": cash_bank_transactions[:5],
    }

    for transaction in cash_bank_transactions:
        amount = float(transaction.amount or 0)
        transaction_type = str(transaction.transaction_type or "").upper()
        account_type = str(transaction.account_type or "").upper()

        if transaction_type == "IN":
            cash_bank_summary["total_in"] += amount

            if account_type == "CASH":
                cash_bank_summary["cash_in"] += amount
            elif account_type == "BANK":
                cash_bank_summary["bank_in"] += amount

        elif transaction_type == "OUT":
            cash_bank_summary["total_out"] += amount

            if account_type == "CASH":
                cash_bank_summary["cash_out"] += amount
            elif account_type == "BANK":
                cash_bank_summary["bank_out"] += amount

    cash_bank_summary["net"] = cash_bank_summary["total_in"] - cash_bank_summary["total_out"]
    cash_bank_summary["cash_net"] = cash_bank_summary["cash_in"] - cash_bank_summary["cash_out"]
    cash_bank_summary["bank_net"] = cash_bank_summary["bank_in"] - cash_bank_summary["bank_out"]

    # ==================================================
    # PRODUCTION - HPP SNAPSHOT + ORDER MARGIN OWNER SUMMARY
    # ==================================================
    hpp_snapshots = OrderHppSnapshot.query.filter(
        OrderHppSnapshot.status != "CANCELLED"
    ).order_by(
        OrderHppSnapshot.id.desc()
    ).all()

    latest_hpp_snapshots_by_order = []
    seen_order_ids = set()

    for snapshot in hpp_snapshots:
        if snapshot.daily_order_id in seen_order_ids:
            continue

        seen_order_ids.add(snapshot.daily_order_id)
        latest_hpp_snapshots_by_order.append(snapshot)

    total_hpp_snapshot_revenue = _safe_sum(
        snapshot.revenue_total for snapshot in latest_hpp_snapshots_by_order
    )
    total_hpp_snapshot_cost = _safe_sum(
        snapshot.hpp_total for snapshot in latest_hpp_snapshots_by_order
    )
    total_hpp_snapshot_margin = _safe_sum(
        snapshot.gross_margin_amount for snapshot in latest_hpp_snapshots_by_order
    )

    hpp_snapshot_margin_percentage = 0
    if total_hpp_snapshot_revenue > 0:
        hpp_snapshot_margin_percentage = (
            total_hpp_snapshot_margin / total_hpp_snapshot_revenue
        ) * 100

    low_margin_snapshots = [
        snapshot for snapshot in latest_hpp_snapshots_by_order
        if float(snapshot.gross_margin_percentage or 0) < float(snapshot.target_margin_percentage or 0)
    ]

    low_margin_snapshots = sorted(
        low_margin_snapshots,
        key=lambda snapshot: float(snapshot.gross_margin_percentage or 0)
    )

    hpp_snapshot_summary = {
        "snapshot_count": len(hpp_snapshots),
        "order_count": len(latest_hpp_snapshots_by_order),
        "total_revenue": total_hpp_snapshot_revenue,
        "total_hpp": total_hpp_snapshot_cost,
        "total_margin": total_hpp_snapshot_margin,
        "margin_percentage": hpp_snapshot_margin_percentage,
        "low_margin_count": len(low_margin_snapshots),
        "latest_order_snapshots": latest_hpp_snapshots_by_order[:5],
        "low_margin_snapshots": low_margin_snapshots[:5],
        "recent_snapshots": hpp_snapshots[:5],
    }

    # ==================================================
    # OPERASIONAL
    # ==================================================
    locked_today = DailyOrder.query.filter_by(
        order_date=today,
        is_locked=True
    ).count()

    delivery_today = Delivery.query.filter_by(
        delivery_date=today
    ).count()

    delivered_today = Delivery.query.filter_by(
        delivery_date=today,
        status="DELIVERED"
    ).count()

    production_today = Production.query.filter_by(
        production_date=today
    ).count()

    production_in_progress = Production.query.filter_by(
        status="IN_PROGRESS"
    ).count()

    delivery_receipt_count = _table_count("delivery_receipts")

    # ==================================================
    # LOGISTIK
    # ==================================================
    item_count = _table_count("items")
    stock_movement_count = _table_count("stock_movements")
    item_request_count = _table_count("item_requests")
    fulfilled_request_count = _table_count_where("item_requests", "status = 'FULFILLED'")
    damaged_item_count = _table_count("damaged_items")

    low_stock_items = _rows("""
        SELECT
            i.item_name,
            i.unit,
            i.minimum_stock,
            COALESCE(SUM(
                CASE
                    WHEN sm.movement_type = 'IN' THEN sm.qty
                    WHEN sm.movement_type = 'OUT' THEN -sm.qty
                    ELSE sm.qty
                END
            ), 0) AS current_stock
        FROM items i
        LEFT JOIN stock_movements sm ON sm.item_id = i.id
        WHERE i.is_stock_tracked IS TRUE
          AND i.is_active IS TRUE
        GROUP BY i.id, i.item_name, i.unit, i.minimum_stock
        HAVING COALESCE(SUM(
                CASE
                    WHEN sm.movement_type = 'IN' THEN sm.qty
                    WHEN sm.movement_type = 'OUT' THEN -sm.qty
                    ELSE sm.qty
                END
            ), 0) <= i.minimum_stock
        ORDER BY current_stock ASC
        LIMIT 5
    """)

    # ==================================================
    # AKUNTANSI
    # ==================================================
    journal_count = Journal.query.count()
    today_journal_count = Journal.query.filter_by(journal_date=today).count()

    # Optimized: single SQL query for total debit/credit (replaces loading ALL details)
    _debit_credit_result = _rows("""
        SELECT COALESCE(SUM(debit), 0) AS total_debit,
               COALESCE(SUM(credit), 0) AS total_credit
        FROM journal_details
    """)
    total_debit = float(_debit_credit_result[0]["total_debit"]) if _debit_credit_result else 0
    total_credit = float(_debit_credit_result[0]["total_credit"]) if _debit_credit_result else 0

    # Optimized: single SQL query for unbalanced journal count (replaces N+1 loop)
    _unbalanced_result = _rows("""
        SELECT COUNT(*) AS cnt FROM (
            SELECT jd.journal_id,
                   ABS(COALESCE(SUM(jd.debit), 0) - COALESCE(SUM(jd.credit), 0)) AS diff
            FROM journal_details jd
            GROUP BY jd.journal_id
            HAVING ABS(COALESCE(SUM(jd.debit), 0) - COALESCE(SUM(jd.credit), 0)) > 1
        ) unbalanced
    """)
    unbalanced_journal_count = int(_unbalanced_result[0]["cnt"]) if _unbalanced_result else 0

    # ==================================================
    # RETURN DATA
    # ==================================================
    return {
        # data lama
        "total_order": total_order,
        "total_locked_order": total_locked_order,
        "total_production": total_production,
        "total_delivery": total_delivery,
        "total_cash_sales": total_cash_sales,
        "total_debt_sales": total_debt_sales,
        "total_worker_debt": total_worker_debt,
        "unpaid_debt_count": unpaid_debt_count,
        "today_orders": today_orders,
        "today_deliveries": today_deliveries,

        # data baru
        "today_date": today,

        "finance": {
            "invoice_count": len(all_invoices),
            "active_invoice_count": len(active_invoices),
            "cancelled_invoice_count": len(cancelled_invoices),
            "receivable_invoice_count": len(receivable_invoices),
            "total_invoice_active": total_invoice_active,
            "paid_invoice_active": paid_invoice_active,
            "remaining_invoice_active": remaining_invoice_active,
            "payment_count": len(payments),
            "total_payment": total_payment,
            "overdue_count": len(overdue_invoices),
            "due_soon_count": len(due_soon_invoices),
            "receivable_priorities": receivable_invoices[:5],
            "recent_payments": recent_payments,
        },

        "collection": {
            "log_count": len(collection_logs),
            "statement_sent_today": len(statement_sent_today),
            "latest_logs": latest_collection_logs,
        },

        "accounts_payable": {
            "open_count": len(open_supplier_bills),
            "total_open": total_supplier_ap,
            "overdue_count": len(overdue_supplier_bills),
            "overdue_total": overdue_supplier_ap,
            "due_soon_count": len(due_soon_supplier_bills),
            "due_soon_total": due_soon_supplier_ap,
            "priority_bills": open_supplier_bills[:5],
        },

        "cash_bank": cash_bank_summary,

        "hpp_snapshot": hpp_snapshot_summary,

        "operations": {
            "today_orders": today_orders,
            "locked_today": locked_today,
            "today_productions": today_productions,
            "production_in_progress": production_in_progress,
            "today_deliveries": delivery_today,
            "delivered_today": delivered_today,
            "delivery_receipt_count": delivery_receipt_count,
        },

        "canteen": {
            "total_cash_sales": total_cash_sales,
            "total_debt_sales": total_debt_sales,
            "total_worker_debt": total_worker_debt,
            "unpaid_debt_count": unpaid_debt_count,
        },

        "logistics": {
            "item_count": item_count,
            "stock_movement_count": stock_movement_count,
            "item_request_count": item_request_count,
            "fulfilled_request_count": fulfilled_request_count,
            "damaged_item_count": damaged_item_count,
            "low_stock_items": low_stock_items,
        },

        "accounting": {
            "journal_count": journal_count,
            "today_journal_count": today_journal_count,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "unbalanced_journal_count": unbalanced_journal_count,
        },

        # PRODUCTION — dashboard command center final payload.
        "command_center": build_owner_command_center({
            "finance": {
                "active_invoice_count": len(active_invoices),
                "receivable_invoice_count": len(receivable_invoices),
                "total_invoice_active": total_invoice_active,
                "remaining_invoice_active": remaining_invoice_active,
                "payment_count": len(payments),
                "total_payment": total_payment,
                "overdue_count": len(overdue_invoices),
            },
            "accounts_payable": {
                "overdue_count": len(overdue_supplier_bills),
                "due_soon_count": len(due_soon_supplier_bills),
            },
            "cash_bank": cash_bank_summary,
            "hpp_snapshot": hpp_snapshot_summary,
            "operations": {
                "today_deliveries": delivery_today,
                "delivered_today": delivered_today,
            },
            "logistics": {
                "low_stock_items": low_stock_items,
            },
            "accounting": {
                "unbalanced_journal_count": unbalanced_journal_count,
            },
        }),

        # PRODUCTION — read-only chart payload for Owner dashboard analytics with filter support.
        "analytics": get_owner_admin_analytics_data(
            branch_id=None,
            role="OWNER",
            year=analytics_year,
            month=analytics_month,
            include_asset_purchase=include_asset_purchase,
            revenue_period=revenue_period,
            revenue_start_date=revenue_start_date,
            revenue_end_date=revenue_end_date,
            revenue_group_by=revenue_group_by,
            revenue_source=revenue_source,
            revenue_client_id=revenue_client_id,
            revenue_mandor_id=revenue_mandor_id,
            revenue_branch_id=revenue_branch_id,
        ),
    }



def _format_dashboard_rupiah(value):
    try:
        value = float(value or 0)
        return "Rp {:,.0f}".format(value).replace(",", ".")
    except Exception:
        return "Rp 0"


def _dashboard_kpi(label, value, caption, icon="bi-speedometer2", tone="blue"):
    return {
        "label": label,
        "value": value,
        "caption": caption,
        "icon": icon,
        "tone": tone,
    }


def get_role_dashboard_metrics(role, branch_id=None):
    """Read-only KPI summary for PRODUCTION role landing dashboards.

    Semua query dibuat defensif agar landing role tetap render walaupun data lama
    belum lengkap. Fungsi ini tidak melakukan write/commit apa pun ke database.
    """
    role = str(role or "").upper()

    try:
        if role == "FINANCE":
            from app.models.finance import Invoice, Payment, SupplierBill, CashBankTransaction

            invoice_query = Invoice.query
            payment_query = Payment.query
            supplier_bill_query = SupplierBill.query
            ledger_query = CashBankTransaction.query

            if branch_id:
                invoice_query = invoice_query.filter_by(branch_id=branch_id)
                payment_query = payment_query.filter_by(branch_id=branch_id)
                supplier_bill_query = supplier_bill_query.filter_by(branch_id=branch_id)
                ledger_query = ledger_query.filter_by(branch_id=branch_id)

            receivable_invoices = invoice_query.filter(
                Invoice.remaining_amount > 0,
                Invoice.status.notin_(["CANCELLED", "CANCELED"]),
            ).all()
            open_supplier_bills = supplier_bill_query.filter(
                SupplierBill.remaining_amount > 0,
                SupplierBill.status != "PAID",
            ).all()

            return [
                _dashboard_kpi(
                    "Piutang Aktif",
                    _format_dashboard_rupiah(sum(invoice.remaining_amount or 0 for invoice in receivable_invoices)),
                    f"{len(receivable_invoices)} invoice belum lunas",
                    "bi-cash-coin",
                    "red" if receivable_invoices else "green",
                ),
                _dashboard_kpi(
                    "Pembayaran Masuk",
                    payment_query.count(),
                    "Total transaksi payment tercatat",
                    "bi-credit-card",
                    "green",
                ),
                _dashboard_kpi(
                    "Hutang Supplier",
                    _format_dashboard_rupiah(sum(bill.remaining_amount or 0 for bill in open_supplier_bills)),
                    f"{len(open_supplier_bills)} bill masih terbuka",
                    "bi-receipt-cutoff",
                    "orange" if open_supplier_bills else "green",
                ),
                _dashboard_kpi(
                    "Buku Kas/Bank",
                    ledger_query.count(),
                    "Transaksi ledger tercatat",
                    "bi-bank",
                    "blue",
                ),
            ]

        if role == "ACCOUNTING":
            from app.models.accounting import Account, Journal, JournalDetail
            from sqlalchemy import text as sa_text
            from app.extensions import db

            journal_count = Journal.query.count()
            today_journal_count = Journal.query.filter_by(journal_date=date.today()).count()
            account_count = Account.query.filter_by(is_active=True).count()

            # Optimized: single SQL query for unbalanced count (replaces N+1 loop)
            try:
                unbalanced_count = int(db.session.execute(sa_text("""
                    SELECT COUNT(*) FROM (
                        SELECT journal_id
                        FROM journal_details
                        GROUP BY journal_id
                        HAVING ABS(COALESCE(SUM(debit), 0) - COALESCE(SUM(credit), 0)) > 1
                    ) unbalanced
                """)).scalar() or 0)
            except Exception:
                unbalanced_count = 0

            return [
                _dashboard_kpi("Jurnal", journal_count, "Total jurnal akuntansi", "bi-journal-check", "blue"),
                _dashboard_kpi("Jurnal Hari Ini", today_journal_count, "Posting sesuai tanggal sistem", "bi-calendar-check", "green"),
                _dashboard_kpi("COA Aktif", account_count, "Akun yang dapat dipakai", "bi-diagram-2", "blue"),
                _dashboard_kpi(
                    "Tidak Balance",
                    unbalanced_count,
                    "Harus 0 sebelum final lock",
                    "bi-exclamation-triangle",
                    "red" if unbalanced_count else "green",
                ),
            ]

        if role == "LOGISTICS":
            from sqlalchemy import text
            from app.extensions import db
            from app.models.master import Item, Supplier
            from app.models.logistics import Procurement, ItemRequest, DamagedItem

            item_count = Item.query.filter_by(is_active=True).count()
            supplier_query = Supplier.query.filter_by(is_active=True)
            procurement_query = Procurement.query
            request_query = ItemRequest.query
            damaged_query = DamagedItem.query

            if branch_id:
                supplier_query = supplier_query.filter_by(branch_id=branch_id)
                procurement_query = procurement_query.filter_by(branch_id=branch_id)
                request_query = request_query.filter_by(branch_id=branch_id)
                damaged_query = damaged_query.filter_by(branch_id=branch_id)

            low_stock_count = 0
            try:
                low_stock_count = int(db.session.execute(text("""
                    SELECT COUNT(*) FROM (
                        SELECT i.id,
                               COALESCE(SUM(CASE
                                   WHEN sm.movement_type = 'IN' THEN sm.qty
                                   WHEN sm.movement_type = 'OUT' THEN -sm.qty
                                   ELSE sm.qty
                               END), 0) AS current_stock,
                               i.minimum_stock
                        FROM items i
                        LEFT JOIN stock_movements sm ON sm.item_id = i.id
                        WHERE i.is_stock_tracked IS TRUE
                          AND i.is_active IS TRUE
                        GROUP BY i.id, i.minimum_stock
                        HAVING COALESCE(SUM(CASE
                                   WHEN sm.movement_type = 'IN' THEN sm.qty
                                   WHEN sm.movement_type = 'OUT' THEN -sm.qty
                                   ELSE sm.qty
                               END), 0) <= i.minimum_stock
                    ) low_items
                """)).scalar() or 0)
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                low_stock_count = 0

            pending_requests = request_query.filter(ItemRequest.status == "PENDING").count()

            return [
                _dashboard_kpi("Item Aktif", item_count, "Master bahan/barang aktif", "bi-box-seam", "blue"),
                _dashboard_kpi("Stok Menipis", low_stock_count, "Item di bawah minimum", "bi-exclamation-triangle", "red" if low_stock_count else "green"),
                _dashboard_kpi("Request Dapur", pending_requests, "Permintaan menunggu proses", "bi-inboxes", "orange" if pending_requests else "green"),
                _dashboard_kpi("Pembelian", procurement_query.count(), f"{supplier_query.count()} supplier aktif", "bi-basket", "blue"),
            ]

        if role == "HR":
            from app.models.master import Employee
            from app.models.hr import Payroll, PayrollDetail, EmployeeAttendance

            employee_query = Employee.query
            payroll_query = Payroll.query
            attendance_query = EmployeeAttendance.query

            if branch_id:
                employee_query = employee_query.filter_by(branch_id=branch_id)
                payroll_query = payroll_query.filter_by(branch_id=branch_id)
                attendance_query = attendance_query.filter_by(branch_id=branch_id)

            active_employee_count = employee_query.filter(Employee.status == "ACTIVE").count()
            draft_payroll_count = payroll_query.filter(Payroll.status == "DRAFT").count()
            payroll_detail_count = PayrollDetail.query.join(Payroll).filter(Payroll.branch_id == branch_id).count() if branch_id else PayrollDetail.query.count()

            return [
                _dashboard_kpi("Karyawan Aktif", active_employee_count, "Employee internal saja", "bi-people", "green"),
                _dashboard_kpi("Payroll Draft", draft_payroll_count, "Perlu dicek sebelum final", "bi-cash-stack", "orange" if draft_payroll_count else "green"),
                _dashboard_kpi("Detail Payroll", payroll_detail_count, "Baris payroll tercatat", "bi-list-check", "blue"),
                _dashboard_kpi("Absensi", attendance_query.count(), "Catatan absensi karyawan", "bi-calendar2-check", "blue"),
            ]

    except Exception:
        pass

    return [
        _dashboard_kpi("Area Role", "Aktif", "Dashboard role berhasil dibuka", "bi-speedometer2", "blue"),
        _dashboard_kpi("Shortcut", "Siap", "Akses modul tersedia", "bi-grid", "green"),
        _dashboard_kpi("Reminder", "Live", "Mengikuti Live Reminder Center", "bi-bell", "orange"),
        _dashboard_kpi("Data", "Read-only", "Tidak mengubah database", "bi-shield-check", "green"),
    ]


def get_admin_dashboard_data(
    branch_id,
    analytics_year=None,
    analytics_month=None,
    include_asset_purchase=False,
    revenue_period=None,
    revenue_start_date=None,
    revenue_end_date=None,
    revenue_group_by=None,
    revenue_source=None,
    revenue_client_id=None,
    revenue_mandor_id=None,
    revenue_branch_id=None,
):
    today = date.today()

    today_orders = DailyOrder.query.filter_by(
        branch_id=branch_id,
        order_date=today
    ).count()

    locked_orders = DailyOrder.query.filter_by(
        branch_id=branch_id,
        is_locked=True
    ).count()

    preparing_delivery = Delivery.query.filter_by(
        branch_id=branch_id,
        status="PREPARING"
    ).count()

    on_the_way_delivery = Delivery.query.filter_by(
        branch_id=branch_id,
        status="ON_THE_WAY"
    ).count()

    today_cash_sales = sum(
        sale.total_amount for sale in CanteenSale.query.filter_by(
            branch_id=branch_id,
            sale_date=today,
            sale_type="CASH"
        ).all()
    )

    branch_debts = WorkerDebt.query.filter_by(branch_id=branch_id).all()
    unpaid_worker_debt = sum(1 for debt in branch_debts if get_debt_remaining_amount(debt) > 0)

    recent_orders = DailyOrder.query.filter_by(
        branch_id=branch_id
    ).order_by(
        DailyOrder.order_date.desc(),
        DailyOrder.id.desc()
    ).limit(5).all()

    recent_deliveries = Delivery.query.filter_by(
        branch_id=branch_id
    ).order_by(
        Delivery.delivery_date.desc(),
        Delivery.id.desc()
    ).limit(5).all()

    delivery_next_actions = get_pending_delivery_next_actions(
        branch_id=branch_id,
        limit=6,
    )

    # PRODUCTION — read-only admin command center low stock signal.
    admin_low_stock_count = 0
    try:
        from sqlalchemy import text
        from app.extensions import db

        admin_low_stock_count = int(db.session.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT i.id,
                       COALESCE(SUM(CASE
                           WHEN sm.movement_type = 'IN' THEN sm.qty
                           WHEN sm.movement_type = 'OUT' THEN -sm.qty
                           ELSE sm.qty
                       END), 0) AS current_stock,
                       i.minimum_stock
                FROM items i
                LEFT JOIN stock_movements sm
                       ON sm.item_id = i.id
                      AND sm.branch_id = :branch_id
                WHERE i.is_stock_tracked IS TRUE
                  AND i.is_active IS TRUE
                GROUP BY i.id, i.minimum_stock
                HAVING COALESCE(SUM(CASE
                                   WHEN sm.movement_type = 'IN' THEN sm.qty
                                   WHEN sm.movement_type = 'OUT' THEN -sm.qty
                                   ELSE sm.qty
                               END), 0) <= i.minimum_stock
            ) low_items
        """), {"branch_id": branch_id}).scalar() or 0)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        admin_low_stock_count = 0

    today_productions = Production.query.filter_by(
        branch_id=branch_id,
        production_date=today,
    ).count()

    return {
        "today_orders": today_orders,
        "locked_orders": locked_orders,
        "preparing_delivery": preparing_delivery,
        "on_the_way_delivery": on_the_way_delivery,
        "today_cash_sales": today_cash_sales,
        "unpaid_worker_debt": unpaid_worker_debt,
        "recent_orders": recent_orders,
        "recent_deliveries": recent_deliveries,
        "delivery_next_actions": delivery_next_actions,
        "delivery_next_action_count": len(delivery_next_actions),
        "today_productions": today_productions,
        "low_stock_count": admin_low_stock_count,
        # PRODUCTION — dashboard command center final payload.
        "command_center": build_admin_command_center({
            "today_orders": today_orders,
            "locked_orders": locked_orders,
            "preparing_delivery": preparing_delivery,
            "on_the_way_delivery": on_the_way_delivery,
            "today_cash_sales": today_cash_sales,
            "unpaid_worker_debt": unpaid_worker_debt,
            "delivery_next_action_count": len(delivery_next_actions),
            "today_productions": today_productions,
            "low_stock_count": admin_low_stock_count,
        }),
        # PRODUCTION — read-only chart payload for Admin branch analytics with filter support.
        "analytics": get_owner_admin_analytics_data(
            branch_id=branch_id,
            role="ADMIN",
            year=analytics_year,
            month=analytics_month,
            include_asset_purchase=include_asset_purchase,
            revenue_period=revenue_period,
            revenue_start_date=revenue_start_date,
            revenue_end_date=revenue_end_date,
            revenue_group_by=revenue_group_by,
            revenue_source=revenue_source,
            revenue_client_id=revenue_client_id,
            revenue_mandor_id=revenue_mandor_id,
            revenue_branch_id=revenue_branch_id,
        ),
    }


def get_dapur_dashboard_data(branch_id):
    today = date.today()

    today_productions = Production.query.filter_by(
        branch_id=branch_id,
        production_date=today
    ).all()

    draft_count = Production.query.filter_by(
        branch_id=branch_id,
        status="DRAFT"
    ).count()

    in_progress_count = Production.query.filter_by(
        branch_id=branch_id,
        status="IN_PROGRESS"
    ).count()

    completed_count = Production.query.filter_by(
        branch_id=branch_id,
        status="COMPLETED"
    ).count()

    recent_productions = Production.query.filter_by(
        branch_id=branch_id
    ).order_by(
        Production.production_date.desc(),
        Production.id.desc()
    ).limit(8).all()

    return {
        "today_productions": today_productions,
        "draft_count": draft_count,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "recent_productions": recent_productions,
    }


def get_pengantar_dashboard_data(branch_id):
    today = date.today()

    today_deliveries = Delivery.query.filter_by(
        branch_id=branch_id,
        delivery_date=today
    ).all()

    preparing_count = Delivery.query.filter_by(
        branch_id=branch_id,
        status="PREPARING"
    ).count()

    on_the_way_count = Delivery.query.filter_by(
        branch_id=branch_id,
        status="ON_THE_WAY"
    ).count()

    delivered_count = Delivery.query.filter_by(
        branch_id=branch_id,
        status="DELIVERED"
    ).count()

    shortage_total = sum(
        detail.shortage_qty for detail in DeliveryDetail.query.join(Delivery).filter(
            Delivery.branch_id == branch_id
        ).all()
    )

    recent_deliveries = Delivery.query.filter_by(
        branch_id=branch_id
    ).order_by(
        Delivery.delivery_date.desc(),
        Delivery.id.desc()
    ).limit(8).all()

    return {
        "today_deliveries": today_deliveries,
        "preparing_count": preparing_count,
        "on_the_way_count": on_the_way_count,
        "delivered_count": delivered_count,
        "shortage_total": shortage_total,
        "recent_deliveries": recent_deliveries,
    }
