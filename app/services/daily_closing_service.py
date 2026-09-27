import logging
from datetime import date, datetime

from app.models.accounting import Journal
from app.models.canteen import CashDaily, CanteenSale, DebtPayment, WorkerDebt
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice, Payment
from app.models.logistics import StockMovement
from app.models.operational import DailyOrder
from app.models.production import Production
from app.services.branch_module_service import WARUNG, module_enabled
from app.utils.terms import T

logger = logging.getLogger(__name__)


CANCELLED_STATUSES = {"CANCELLED", "CANCELED"}
TOLERANCE = 0.01


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value):
    return "Rp {:,.0f}".format(_float(value)).replace(",", ".")


def _qty(value):
    number = round(_float(value), 4)
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _safe_date(value):
    if not value:
        return "-"
    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/daily_closing_service.py:39")
        return str(value)


def _safe_label(obj, *attrs):
    if not obj:
        return "-"
    for attr in attrs:
        value = getattr(obj, attr, None)
        if value:
            return value
    return str(obj)


def _is_cancelled(status):
    return str(status or "").upper() in CANCELLED_STATUSES


def _status_class(status):
    if status == "AMAN":
        return "status-locked"
    if status == "WARNING":
        return "status-progress"
    return "status-cancelled"


def _row(status, check, item, expected="-", actual="-", note=""):
    return {
        "status": status,
        "status_class": _status_class(status),
        "check": check,
        "item": item,
        "expected": expected,
        "actual": actual,
        "note": note,
    }


def _section(key, title, description, rows):
    counts = {"AMAN": 0, "WARNING": 0, "RISIKO": 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    if counts["RISIKO"] > 0:
        status = "RISIKO"
    elif counts["WARNING"] > 0:
        status = "WARNING"
    else:
        status = "AMAN"

    return {
        "key": key,
        "title": title,
        "description": description,
        "status": status,
        "status_class": _status_class(status),
        "counts": counts,
        "rows": rows,
    }


def _parse_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/daily_closing_service.py:106")
        return None


def _latest_date_for_model(model, date_field, branch_id=None):
    query = model.query

    if branch_id is not None and hasattr(model, "branch_id"):
        query = query.filter_by(branch_id=branch_id)

    row = query.order_by(date_field.desc()).first()

    if row:
        return getattr(row, date_field.key)

    return None


def _resolve_target_date(branch_id, selected_date_value):
    parsed_date = _parse_date(selected_date_value)

    if parsed_date:
        return parsed_date

    candidates = [
        _latest_date_for_model(DailyOrder, DailyOrder.order_date, branch_id),
        _latest_date_for_model(Production, Production.production_date, branch_id),
        _latest_date_for_model(Delivery, Delivery.delivery_date, branch_id),
        _latest_date_for_model(Invoice, Invoice.invoice_date, branch_id),
        _latest_date_for_model(Payment, Payment.payment_date, branch_id),
        _latest_date_for_model(CanteenSale, CanteenSale.sale_date, branch_id),
        _latest_date_for_model(CashDaily, CashDaily.cash_date, branch_id),
        _latest_date_for_model(StockMovement, StockMovement.movement_date, branch_id),
        _latest_date_for_model(Journal, Journal.journal_date, None),
    ]

    candidates = [candidate for candidate in candidates if candidate]

    if candidates:
        return max(candidates)

    return date.today()


def _date_value(value):
    return value.strftime("%Y-%m-%d")


def _delivery_type_from_notes(notes):
    text = str(notes or "").upper()

    if "DELIVERY_TYPE=LUNCH" in text:
        return "LUNCH"

    if "DELIVERY_TYPE=DINNER" in text:
        return "DINNER"

    return "UNKNOWN"


def _is_shortage_replacement(notes):
    return "BATCH=SHORTAGE_REPLACEMENT" in str(notes or "").upper()


def _order_rows(branch_id, target_date):
    rows = []
    orders = DailyOrder.query.filter_by(
        branch_id=branch_id,
        order_date=target_date,
    ).order_by(DailyOrder.id.asc()).all()

    for order in orders:
        lunch_qty = sum(int(detail.lunch_qty or 0) for detail in order.details)
        dinner_qty = sum(int(detail.dinner_qty or 0) for detail in order.details)
        total_qty = sum(int(detail.total_qty or 0) for detail in order.details)
        status = "AMAN" if order.is_locked else "WARNING"

        rows.append(_row(
            status=status,
            check="Order harian",
            item=order.order_number,
            expected="LOCKED untuk dasar produksi/invoice",
            actual=(
                f"{order.status} | {'LOCKED' if order.is_locked else 'OPEN'} | "
                f"Lunch {_qty(lunch_qty)}, Dinner {_qty(dinner_qty)}, Total {_qty(total_qty)}"
            ),
            note=f"Jumlah detail order: {len(order.details)}.",
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Order harian",
            item="Tidak ada order",
            expected="Order harian jika ada operasional",
            actual="0 order",
            note="Tanggal ini tidak punya order harian.",
        ))

    return rows, orders


def _production_rows(branch_id, target_date, orders):
    rows = []
    productions = Production.query.filter_by(
        branch_id=branch_id,
        production_date=target_date,
    ).order_by(Production.production_type.asc(), Production.id.asc()).all()

    expected_qty = {"LUNCH": 0, "DINNER": 0}

    for order in orders:
        for detail in order.details:
            expected_qty["LUNCH"] += int(detail.lunch_qty or 0)
            expected_qty["DINNER"] += int(detail.dinner_qty or 0)

    production_types = set()

    for production in productions:
        production_type = str(production.production_type or "UNKNOWN").upper()
        production_types.add(production_type)
        planned_qty = sum(_float(detail.planned_qty) for detail in production.details)
        actual_qty = sum(_float(detail.actual_qty) for detail in production.details)
        expected = expected_qty.get(production_type, 0)

        if expected > 0 and abs(planned_qty - expected) > TOLERANCE:
            status = "WARNING"
            note = "Planned production belum sama dengan total porsi order tanggal ini."
        elif production.status == "COMPLETED" and actual_qty >= planned_qty:
            status = "AMAN"
            note = "Production completed dan actual menutup planned."
        else:
            status = "WARNING"
            note = "Production belum completed atau actual belum menutup planned."

        rows.append(_row(
            status=status,
            check=f"Produksi {production_type}",
            item=f"{production_type} #{production.id}",
            expected=f"Order qty {_qty(expected)} porsi",
            actual=f"Status {production.status}, planned {_qty(planned_qty)}, actual {_qty(actual_qty)}",
            note=note,
        ))

    for production_type, qty in expected_qty.items():
        if qty > 0 and production_type not in production_types:
            rows.append(_row(
                status="WARNING",
                check=f"Produksi {production_type}",
                item=f"{production_type} belum ada",
                expected=f"Production untuk {_qty(qty)} porsi",
                actual="Belum ada production",
                note="Order punya porsi, tapi production belum ditemukan.",
            ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Produksi lunch/dinner",
            item="Tidak ada produksi",
            expected="Produksi jika ada order",
            actual="0 produksi",
            note="Tanggal ini belum punya data produksi.",
        ))

    return rows


def _delivery_rows(branch_id, target_date):
    rows = []
    deliveries = Delivery.query.filter_by(
        branch_id=branch_id,
        delivery_date=target_date,
    ).order_by(Delivery.id.asc()).all()

    summary = {
        "LUNCH": {"main": 0, "replacement": 0},
        "DINNER": {"main": 0, "replacement": 0},
        "UNKNOWN": {"main": 0, "replacement": 0},
    }

    for delivery in deliveries:
        delivery_type = _delivery_type_from_notes(delivery.notes)
        is_replacement = _is_shortage_replacement(delivery.notes)
        kind = "replacement" if is_replacement else "main"
        delivered_qty = sum(_float(detail.delivered_qty) for detail in delivery.details)

        if delivery_type not in summary:
            summary[delivery_type] = {"main": 0, "replacement": 0}

        if not _is_cancelled(delivery.status):
            summary[delivery_type][kind] += delivered_qty

        if _is_cancelled(delivery.status):
            status = "WARNING"
            note = "Delivery cancelled, tidak dihitung ke final delivery."
        elif delivered_qty <= 0:
            status = "WARNING"
            note = "Delivery aktif tapi delivered qty masih 0."
        else:
            status = "AMAN"
            note = "Delivery aktif terbaca sebagai bagian distribusi harian."

        rows.append(_row(
            status=status,
            check="Delivery pengganti shortage" if is_replacement else "Delivery utama",
            item=delivery.delivery_number,
            expected="Delivered qty > 0 untuk delivery aktif",
            actual=f"{delivery_type} | {delivery.status} | {_qty(delivered_qty)} porsi",
            note=note,
        ))

    for delivery_type in ["LUNCH", "DINNER"]:
        main_qty = summary[delivery_type]["main"]
        replacement_qty = summary[delivery_type]["replacement"]
        final_qty = main_qty + replacement_qty

        if final_qty > 0:
            rows.append(_row(
                status="AMAN",
                check=f"Delivery final {delivery_type}",
                item=f"{delivery_type} final",
                expected="Utama + pengganti shortage",
                actual=(
                    f"Utama {_qty(main_qty)} porsi, "
                    f"pengganti shortage {_qty(replacement_qty)} porsi, "
                    f"final {_qty(final_qty)} porsi"
                ),
                note="Delivery utama dan shortage replacement tetap dipisahkan.",
            ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Delivery harian",
            item="Tidak ada delivery",
            expected="Delivery jika produksi sudah selesai",
            actual="0 delivery",
            note="Tanggal ini belum punya delivery.",
        ))

    return rows


def _invoice_rows(branch_id, target_date):
    rows = []
    invoices = Invoice.query.filter_by(
        branch_id=branch_id,
        invoice_date=target_date,
    ).order_by(Invoice.id.asc()).all()

    for invoice in invoices:
        total_item = sum(_float(item.subtotal) for item in invoice.items)
        remaining_expected = _float(invoice.total_amount) - _float(invoice.paid_amount)

        if _is_cancelled(invoice.status):
            status = "WARNING"
            note = "Invoice cancelled disimpan sebagai arsip dan tidak dihitung piutang aktif."
        elif abs(total_item - _float(invoice.total_amount)) > TOLERANCE:
            status = "RISIKO"
            note = "Total invoice tidak sama dengan subtotal item."
        elif abs(remaining_expected - _float(invoice.remaining_amount)) > TOLERANCE:
            status = "RISIKO"
            note = "Remaining invoice tidak sama dengan total - paid."
        else:
            status = "AMAN"
            note = "Invoice harian aman secara angka."

        rows.append(_row(
            status=status,
            check="Invoice dibuat",
            item=invoice.invoice_number,
            expected=f"Total item {_money(total_item)}, remaining {_money(remaining_expected)}",
            actual=(
                f"{invoice.status} | total {_money(invoice.total_amount)}, "
                f"paid {_money(invoice.paid_amount)}, remaining {_money(invoice.remaining_amount)}"
            ),
            note=note,
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Invoice dibuat",
            item="Tidak ada invoice",
            expected="Invoice jika ada penagihan hari ini",
            actual="0 invoice",
            note="Tanggal ini belum punya invoice baru.",
        ))

    return rows


def _payment_rows(branch_id, target_date):
    rows = []
    payments = Payment.query.filter_by(
        branch_id=branch_id,
        payment_date=target_date,
    ).order_by(Payment.id.asc()).all()

    for payment in payments:
        invoice = payment.invoice
        status = "WARNING" if invoice and _is_cancelled(invoice.status) else "AMAN"

        rows.append(_row(
            status=status,
            check="Payment masuk",
            item=payment.payment_number,
            expected="Payment hanya untuk invoice aktif",
            actual=(
                f"{_money(payment.amount)} | {payment.payment_method} | "
                f"Invoice {invoice.invoice_number if invoice else '-'}"
            ),
            note=(
                "Payment masuk hari ini."
                if status == "AMAN"
                else "Payment terkait invoice cancelled, perlu dicek."
            ),
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Payment masuk",
            item="Tidak ada payment",
            expected="Payment jika ada pelunasan/follow-up",
            actual="0 payment",
            note="Tanggal ini belum punya pembayaran masuk.",
        ))

    return rows


def _canteen_rows(branch_id, target_date):
    rows = []
    sales = CanteenSale.query.filter_by(
        branch_id=branch_id,
        sale_date=target_date,
    ).order_by(CanteenSale.id.asc()).all()

    for sale in sales:
        item_total = sum(_float(item.subtotal) for item in sale.items)
        status = "RISIKO" if abs(item_total - _float(sale.total_amount)) > TOLERANCE else "AMAN"
        debt = sale.worker_debt

        rows.append(_row(
            status=status,
            check="Warung/canteen sale",
            item=f"Sale #{sale.id} | {sale.sale_type}",
            expected=f"Subtotal item {_money(item_total)}",
            actual=f"Total sale {_money(sale.total_amount)}",
            note=(
                f"Hutang {T.worker_lower} {_money(debt.debt_amount)} status {debt.status}."
                if debt else f"Cash sale / tidak ada hutang {T.worker_lower}."
            ),
        ))

    debt_payments = (
        DebtPayment.query
        .join(WorkerDebt, DebtPayment.worker_debt_id == WorkerDebt.id)
        .filter(
            WorkerDebt.branch_id == branch_id,
            DebtPayment.payment_date == target_date,
        )
        .order_by(DebtPayment.id.asc())
        .all()
    )

    for payment in debt_payments:
        debt = payment.worker_debt
        worker_name = _safe_label(getattr(debt, "worker", None), "full_name", "name")
        rows.append(_row(
            status="AMAN",
            check=f"Pembayaran hutang {T.worker_lower}",
            item=f"Debt #{debt.id} | {worker_name}",
            expected="Pembayaran hutang tercatat",
            actual=_money(payment.amount),
            note=payment.notes or f"Pembayaran hutang {T.worker_lower} masuk.",
        ))

    cash_daily = CashDaily.query.filter_by(
        branch_id=branch_id,
        cash_date=target_date,
    ).first()

    if cash_daily:
        status = "AMAN" if abs(_float(cash_daily.cash_difference)) <= TOLERANCE else "WARNING"
        rows.append(_row(
            status=status,
            check="Kas warung harian",
            item=f"CashDaily #{cash_daily.id} | {cash_daily.status}",
            expected=f"Selisih kas 0",
            actual=(
                f"Opening {_money(cash_daily.opening_balance)}, "
                f"sales {_money(cash_daily.cash_sales)}, debt payment {_money(cash_daily.debt_payments)}, "
                f"expense {_money(cash_daily.expenses)}, difference {_money(cash_daily.cash_difference)}"
            ),
            note=cash_daily.notes or "Ringkasan kas warung harian.",
        ))
    else:
        rows.append(_row(
            status="WARNING",
            check="Kas warung harian",
            item="Belum ada CashDaily",
            expected="CashDaily jika warung ditutup harian",
            actual="Belum ada data closing kas",
            note="Read-only warning, tidak membuat closing otomatis.",
        ))

    if not sales and not debt_payments and not cash_daily:
        rows.append(_row(
            status="WARNING",
            check="Warung/canteen",
            item="Tidak ada aktivitas warung",
            expected="Aktivitas warung jika ada penjualan",
            actual="0 sales/payment/cash daily",
            note="Tanggal ini belum punya aktivitas warung.",
        ))

    return rows


def _stock_rows(branch_id, target_date):
    rows = []
    movements = StockMovement.query.filter_by(
        branch_id=branch_id,
        movement_date=target_date,
    ).order_by(StockMovement.id.asc()).all()

    totals = {}

    for movement in movements:
        movement_type = str(movement.movement_type or "UNKNOWN").upper()
        totals[movement_type] = totals.get(movement_type, 0) + _float(movement.qty)
        item_name = _safe_label(movement.item, "item_name", "name")

        status = "RISIKO" if _float(movement.qty) < 0 else "AMAN"
        rows.append(_row(
            status=status,
            check="Stock movement",
            item=f"{movement_type} | {item_name}",
            expected="Qty movement tidak minus",
            actual=f"{_qty(movement.qty)} {getattr(movement.item, 'unit', '')}",
            note=f"Reference {movement.reference_type} #{movement.reference_id or '-'} | {movement.notes or '-'}",
        ))

    for movement_type, total_qty in sorted(totals.items()):
        rows.append(_row(
            status="AMAN",
            check=f"Total stock {movement_type}",
            item=movement_type,
            expected="Total movement harian",
            actual=_qty(total_qty),
            note="Ringkasan movement per tipe.",
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Stock movement",
            item="Tidak ada movement",
            expected="Movement jika ada pembelian/pemakaian/rusak/adjustment",
            actual="0 movement",
            note="Tanggal ini belum punya mutasi stok.",
        ))

    return rows


def _journal_rows(target_date):
    rows = []
    journals = Journal.query.filter_by(
        journal_date=target_date,
    ).order_by(Journal.id.asc()).all()

    for journal in journals:
        debit = sum(_float(detail.debit) for detail in journal.details)
        credit = sum(_float(detail.credit) for detail in journal.details)
        status = "RISIKO" if abs(debit - credit) > TOLERANCE else "AMAN"

        rows.append(_row(
            status=status,
            check="Jurnal transaksi harian",
            item=journal.journal_number,
            expected=f"Debit = Credit ({_money(debit)})",
            actual=f"{journal.reference_type} #{journal.reference_id} | debit {_money(debit)}, credit {_money(credit)}",
            note=journal.description,
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Jurnal transaksi harian",
            item="Tidak ada jurnal",
            expected="Jurnal jika ada transaksi harian yang dijurnal",
            actual="0 jurnal",
            note="Tabel jurnal belum punya branch_id, jadi check ini berdasarkan tanggal global.",
        ))

    return rows


def get_daily_closing_report(branch_id, selected_date_value=None):
    target_date = _resolve_target_date(branch_id, selected_date_value)

    order_rows, orders = _order_rows(branch_id, target_date)
    sections = [
        _section(
            "orders",
            "Order Harian",
            "Ringkasan order harian, status lock, dan total porsi.",
            order_rows,
        ),
        _section(
            "production",
            "Produksi Lunch/Dinner",
            "Ringkasan produksi lunch/dinner berdasarkan tanggal order.",
            _production_rows(branch_id, target_date, orders),
        ),
        _section(
            "delivery",
            "Delivery Utama & Pengganti Shortage",
            "Ringkasan delivery utama, delivery pengganti shortage, dan final delivery.",
            _delivery_rows(branch_id, target_date),
        ),
        _section(
            "invoice",
            "Invoice Dibuat",
            "Invoice yang dibuat pada tanggal closing, termasuk status dan remaining.",
            _invoice_rows(branch_id, target_date),
        ),
        _section(
            "payment",
            "Payment Masuk",
            "Pembayaran invoice yang masuk pada tanggal closing.",
            _payment_rows(branch_id, target_date),
        ),
        # Cabang tanpa modul Warung tidak diperiksa bagian warungnya.
        *([_section(
            "canteen",
            f"Warung / Canteen Cash & Hutang {T.worker}",
            f"Penjualan warung, hutang {T.worker_lower}, pembayaran hutang, dan kas harian.",
            _canteen_rows(branch_id, target_date),
        )] if module_enabled(WARUNG, branch_id) else []),
        _section(
            "stock",
            "Stock Movement",
            "Mutasi stok masuk, keluar, rusak, dan adjustment pada tanggal closing.",
            _stock_rows(branch_id, target_date),
        ),
        _section(
            "journal",
            "Jurnal Transaksi Harian",
            "Jurnal terkait transaksi pada tanggal closing.",
            _journal_rows(target_date),
        ),
    ]

    summary = {"total_sections": len(sections), "total_rows": 0, "AMAN": 0, "WARNING": 0, "RISIKO": 0}

    for section in sections:
        summary["total_rows"] += len(section["rows"])
        for key in ["AMAN", "WARNING", "RISIKO"]:
            summary[key] += section["counts"].get(key, 0)

    if summary["RISIKO"] > 0:
        overall = "RISIKO"
    elif summary["WARNING"] > 0:
        overall = "WARNING"
    else:
        overall = "AMAN"

    return {
        "generated_at": datetime.now(),
        "selected_date": target_date,
        "selected_date_label": _safe_date(target_date),
        "selected_date_value": _date_value(target_date),
        "overall_status": overall,
        "overall_status_class": _status_class(overall),
        "summary": summary,
        "sections": sections,
    }
