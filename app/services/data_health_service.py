from collections import defaultdict
from datetime import datetime

from app.utils.clock import now_wib

from app.models.accounting import Journal
from app.models.canteen import CanteenSale, WorkerDebt
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import AdvanceSettlement, Invoice, InvoiceItem
from app.models.hr import Payroll
from app.models.logistics import Procurement
from app.models.operational import DailyOrder
from app.models.production import Production
from app.services.stock_service import get_item_stock, get_stock_items
from app.utils.terms import T


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


def _diff(left, right):
    return round(_float(left) - _float(right), 2)


def _is_mismatch(left, right):
    return abs(_diff(left, right)) > TOLERANCE


def _is_cancelled(status):
    return str(status or "").upper() in CANCELLED_STATUSES


def _status_class(status):
    if status == "AMAN":
        return "status-locked"
    if status == "WARNING":
        return "status-progress"
    return "status-cancelled"


def _row(status, check, item, expected="-", actual="-", difference="-", note=""):
    return {
        "status": status,
        "status_class": _status_class(status),
        "check": check,
        "item": item,
        "expected": expected,
        "actual": actual,
        "difference": difference,
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


# Pelunasan invoice dari uang muka pelanggan (2008) atau deposit (2007) juga
# pembayaran: invoice pelanggan umum lunas lewat settlement, tanpa baris Payment.
INVOICE_SETTLEMENT_TYPES = ("CLIENT_INVOICE", "DEPOSIT_TO_INVOICE")


def _invoice_settlement_totals(branch_id):
    totals = defaultdict(float)
    settlements = AdvanceSettlement.query.filter(
        AdvanceSettlement.branch_id == branch_id,
        AdvanceSettlement.settlement_type.in_(INVOICE_SETTLEMENT_TYPES),
    ).all()
    for settlement in settlements:
        totals[settlement.reference_id] += _float(settlement.amount)
    return totals


def _invoice_rows(branch_id):
    rows = []
    invoices = Invoice.query.filter_by(branch_id=branch_id).order_by(Invoice.id.asc()).all()
    settled = _invoice_settlement_totals(branch_id)

    for invoice in invoices:
        item_total = sum(_float(item.subtotal) for item in invoice.items)
        status = "RISIKO" if _is_mismatch(invoice.total_amount, item_total) else "AMAN"
        rows.append(_row(
            status=status,
            check="Invoice total vs item invoice",
            item=f"{invoice.invoice_number} ({invoice.status})",
            expected=_money(item_total),
            actual=_money(invoice.total_amount),
            difference=_money(_diff(invoice.total_amount, item_total)),
            note="Total invoice harus sama dengan subtotal seluruh item invoice.",
        ))

        payment_total = sum(_float(payment.amount) for payment in invoice.payments) + settled.get(invoice.id, 0.0)
        status = "RISIKO" if _is_mismatch(invoice.paid_amount, payment_total) else "AMAN"
        rows.append(_row(
            status=status,
            check="Payment total vs paid_amount invoice",
            item=f"{invoice.invoice_number} ({invoice.status})",
            expected=_money(payment_total),
            actual=_money(invoice.paid_amount),
            difference=_money(_diff(invoice.paid_amount, payment_total)),
            note="Paid amount invoice harus sama dengan total payment + pelunasan dari uang muka/deposit.",
        ))

        expected_remaining = _float(invoice.total_amount) - _float(invoice.paid_amount)
        status = "RISIKO" if _is_mismatch(invoice.remaining_amount, expected_remaining) else "AMAN"
        rows.append(_row(
            status=status,
            check="Remaining amount vs total - paid",
            item=f"{invoice.invoice_number} ({invoice.status})",
            expected=_money(expected_remaining),
            actual=_money(invoice.remaining_amount),
            difference=_money(_diff(invoice.remaining_amount, expected_remaining)),
            note="Remaining invoice harus total invoice dikurangi pembayaran.",
        ))

    if not invoices:
        rows.append(_row(
            status="WARNING",
            check="Invoice data",
            item="Belum ada invoice",
            note="Data invoice kosong, belum ada angka yang bisa divalidasi.",
        ))

    return rows


def _receivable_rows(branch_id):
    active_invoices = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        ~Invoice.status.in_(list(CANCELLED_STATUSES)),
        Invoice.remaining_amount > 0,
    ).order_by(Invoice.id.asc()).all()

    cancelled_invoices = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.status.in_(list(CANCELLED_STATUSES)),
    ).order_by(Invoice.id.asc()).all()

    cancelled_leak = [invoice for invoice in active_invoices if _is_cancelled(invoice.status)]
    active_remaining = sum(_float(invoice.remaining_amount) for invoice in active_invoices)
    cancelled_remaining = sum(_float(invoice.remaining_amount) for invoice in cancelled_invoices)

    rows = [
        _row(
            status="RISIKO" if cancelled_leak else "AMAN",
            check="Invoice CANCELLED tidak masuk piutang aktif",
            item="Piutang aktif",
            expected="0 invoice CANCELLED",
            actual=f"{len(cancelled_leak)} invoice CANCELLED",
            difference="-",
            note=(
                f"Piutang aktif saat ini {_money(active_remaining)} dari {len(active_invoices)} invoice. "
                f"Invoice CANCELLED tersimpan sebagai arsip {len(cancelled_invoices)} invoice dengan remaining {_money(cancelled_remaining)}."
            ),
        )
    ]

    return rows


def _journal_rows(branch_id):
    rows = []
    journals = Journal.query.order_by(Journal.id.asc()).all()

    for journal in journals:
        debit = sum(_float(detail.debit) for detail in journal.details)
        credit = sum(_float(detail.credit) for detail in journal.details)
        status = "RISIKO" if _is_mismatch(debit, credit) else "AMAN"
        rows.append(_row(
            status=status,
            check="Jurnal debit-credit balance",
            item=f"{journal.journal_number} | {journal.reference_type} #{journal.reference_id}",
            expected=_money(debit),
            actual=_money(credit),
            difference=_money(_diff(debit, credit)),
            note="Debit dan credit wajib balance.",
        ))

    reference_groups = defaultdict(list)
    for journal in journals:
        key = (journal.reference_type, journal.reference_id)
        reference_groups[key].append(journal)

    duplicates = {
        key: group
        for key, group in reference_groups.items()
        if len(group) > 1
    }

    if duplicates:
        for key, group in duplicates.items():
            rows.append(_row(
                status="RISIKO",
                check="Duplicate journal reference",
                item=f"{key[0]} #{key[1]}",
                expected="1 jurnal",
                actual=f"{len(group)} jurnal",
                difference=str(len(group) - 1),
                note="Satu transaksi sumber seharusnya hanya punya satu jurnal otomatis.",
            ))
    else:
        rows.append(_row(
            status="AMAN",
            check="Duplicate journal reference",
            item="Semua reference",
            expected="Tidak ada duplicate",
            actual="0 duplicate",
            difference="0",
            note="Reference journal aman.",
        ))

    if not journals:
        rows.append(_row(
            status="WARNING",
            check="Jurnal akuntansi",
            item="Belum ada jurnal",
            note="Belum ada jurnal yang bisa divalidasi.",
        ))

    return rows


def _payroll_rows(branch_id):
    rows = []
    payrolls = Payroll.query.filter_by(branch_id=branch_id).order_by(Payroll.id.asc()).all()

    for payroll in payrolls:
        for detail in payroll.details:
            # Rumus penggajian lengkap (Modul Tenaga Kerja + PPh 21): kompensasi keluar menambah,
            # PPh 21 yang dipotong dari karyawan serta potongan denda/ganti rugi/kasbon mengurangi.
            pph21 = _float(getattr(detail, "pph21_amount", 0)) if getattr(detail, "pph21_borne_by", None) == "KARYAWAN" else 0
            expected = max(0, (
                _float(detail.base_salary) + _float(detail.bonus) + _float(getattr(detail, "exit_compensation", 0))
                - _float(detail.deduction) - pph21 - _float(getattr(detail, "charge_deduction", 0))
            ))
            status = "RISIKO" if _is_mismatch(detail.final_salary, expected) else "AMAN"
            employee_name = getattr(getattr(detail, "employee", None), "full_name", f"Employee #{detail.employee_id}")
            rows.append(_row(
                status=status,
                check="Payroll final salary",
                item=f"{payroll.period_month:02d}-{payroll.period_year} | {employee_name}",
                expected=_money(expected),
                actual=_money(detail.final_salary),
                difference=_money(_diff(detail.final_salary, expected)),
                note="Gaji bersih = gaji + bonus + kompensasi keluar - potongan hari - PPh 21 (dipotong) - denda/ganti rugi/kasbon.",
            ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Payroll final salary",
            item="Belum ada payroll detail",
            note="Belum ada payroll yang bisa divalidasi.",
        ))

    return rows


def _canteen_rows(branch_id):
    rows = []
    sales = CanteenSale.query.filter_by(branch_id=branch_id).order_by(CanteenSale.id.asc()).all()

    for sale in sales:
        item_total = sum(_float(item.subtotal) for item in sale.items)
        status = "RISIKO" if _is_mismatch(sale.total_amount, item_total) else "AMAN"
        rows.append(_row(
            status=status,
            check="Warung sale total vs item",
            item=f"Sale #{sale.id} ({sale.sale_type})",
            expected=_money(item_total),
            actual=_money(sale.total_amount),
            difference=_money(_diff(sale.total_amount, item_total)),
            note="Total transaksi warung harus sama dengan subtotal item.",
        ))

    debts = WorkerDebt.query.filter_by(branch_id=branch_id).order_by(WorkerDebt.id.asc()).all()
    for debt in debts:
        payment_total = sum(_float(payment.amount) for payment in debt.payments)
        remaining = _float(debt.debt_amount) - payment_total

        if remaining <= TOLERANCE:
            expected_status = "PAID"
        elif payment_total > TOLERANCE:
            expected_status = "PARTIAL"
        else:
            expected_status = "UNPAID"

        status_ok = str(debt.status or "").upper() == expected_status
        row_status = "WARNING" if not status_ok else "AMAN"
        worker_name = getattr(getattr(debt, "worker", None), "full_name", f"Worker #{debt.worker_id}")
        rows.append(_row(
            status=row_status,
            check=f"Hutang {T.worker_lower} warung",
            item=f"Debt #{debt.id} | {worker_name}",
            expected=f"{_money(remaining)} | {expected_status}",
            actual=f"{_money(remaining)} | {debt.status}",
            difference=_money(_diff(debt.debt_amount, payment_total + remaining)),
            note=f"Hutang {_money(debt.debt_amount)}, pembayaran {_money(payment_total)}.",
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Warung pekerja",
            item="Belum ada transaksi/hutang warung",
            note="Belum ada data warung yang bisa divalidasi.",
        ))

    return rows


def _stock_rows(branch_id):
    rows = []

    procurements = Procurement.query.filter_by(branch_id=branch_id).order_by(Procurement.id.asc()).all()
    for procurement in procurements:
        item_total = sum(_float(item.subtotal) for item in procurement.items)
        status = "RISIKO" if _is_mismatch(procurement.total_amount, item_total) else "AMAN"
        rows.append(_row(
            status=status,
            check="Pembelian total vs item",
            item=procurement.procurement_number,
            expected=_money(item_total),
            actual=_money(procurement.total_amount),
            difference=_money(_diff(procurement.total_amount, item_total)),
            note="Total pembelian harus sama dengan subtotal item pembelian.",
        ))

    items = get_stock_items()
    for item in items:
        stock_qty = get_item_stock(branch_id, item.id)
        minimum_stock = _float(item.minimum_stock)

        if stock_qty < 0:
            status = "RISIKO"
            note = "Stok minus. Perlu cek mutasi stok."
        elif stock_qty <= minimum_stock:
            status = "WARNING"
            note = "Stok kosong/menipis dibanding minimum stock."
        else:
            status = "AMAN"
            note = "Stok aman."

        rows.append(_row(
            status=status,
            check="Stok minus/menipis",
            item=f"{item.item_code} - {item.item_name}",
            expected=f"> {_qty(minimum_stock)} {item.unit}",
            actual=f"{_qty(stock_qty)} {item.unit}",
            difference=f"{_qty(_float(stock_qty) - minimum_stock)} {item.unit}",
            note=note,
        ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Pembelian dan stok",
            item="Belum ada data pembelian/stok",
            note="Belum ada data yang bisa divalidasi.",
        ))

    return rows


def _delivery_type_qty(order_detail, delivery_type):
    if delivery_type == "LUNCH":
        return int(order_detail.lunch_qty or 0)
    return int(order_detail.dinner_qty or 0)


def _production_for_order(order, delivery_type):
    return Production.query.filter_by(
        branch_id=order.branch_id,
        production_date=order.order_date,
        production_type=delivery_type,
    ).first()


def _delivery_notes(delivery):
    return str(getattr(delivery, "notes", "") or "")


def _is_shortage_replacement_delivery(delivery):
    return "batch=SHORTAGE_REPLACEMENT" in _delivery_notes(delivery).upper()


def _delivery_breakdown_for_order_detail(order_detail_id, delivery_type):
    rows = DeliveryDetail.query.join(Delivery).filter(
        DeliveryDetail.daily_order_detail_id == order_detail_id,
        Delivery.notes.like(f"%delivery_type={delivery_type}%"),
        Delivery.status != "CANCELLED",
    ).all()

    breakdown = {
        "main_qty": 0,
        "replacement_qty": 0,
        "total_qty": 0,
        "main_count": 0,
        "replacement_count": 0,
    }

    for row in rows:
        delivered_qty = _float(row.delivered_qty)
        delivery = getattr(row, "delivery", None)

        if _is_shortage_replacement_delivery(delivery):
            breakdown["replacement_qty"] += delivered_qty
            breakdown["replacement_count"] += 1
        else:
            breakdown["main_qty"] += delivered_qty
            breakdown["main_count"] += 1

        breakdown["total_qty"] += delivered_qty

    return breakdown


def _is_after_lock_invoice_revision(revision):
    direction = str(getattr(revision, "revision_direction", "") or "").upper()
    rev_type = str(getattr(revision, "revision_type", "") or "").upper()
    qty_change = int(getattr(revision, "lunch_qty_change", 0) or 0) + int(getattr(revision, "dinner_qty_change", 0) or 0)

    return direction == "INCREASE" and rev_type.startswith("AFTER_LOCK") and qty_change > 0


def _build_cancelled_legacy_source_map(branch_id):
    legacy_sources = defaultdict(list)

    invoices = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.status.in_(list(CANCELLED_STATUSES)),
        Invoice.source_type == "DAILY_ORDER",
        Invoice.source_order_id.isnot(None),
    ).order_by(Invoice.id.asc()).all()

    for invoice in invoices:
        order = DailyOrder.query.filter_by(
            branch_id=branch_id,
            id=invoice.source_order_id,
        ).first()

        if not order:
            continue

        for detail in order.details:
            if invoice.mandor_id and int(detail.mandor_id or 0) != int(invoice.mandor_id):
                continue

            if int(detail.total_qty or 0) > 0:
                legacy_sources[("ORDER_DETAIL", detail.id)].append(invoice.invoice_number)

            for revision in detail.revisions:
                if _is_after_lock_invoice_revision(revision):
                    legacy_sources[("ORDER_REVISION", revision.id)].append(invoice.invoice_number)

    return legacy_sources


def _invoice_source_maps(branch_id):
    active_sources = set()
    any_sources = set()
    cancelled_sources = set()

    items = InvoiceItem.query.join(Invoice).filter(
        Invoice.branch_id == branch_id,
        InvoiceItem.source_type.isnot(None),
        InvoiceItem.source_id.isnot(None),
    ).all()

    for item in items:
        key = (item.source_type, item.source_id)
        any_sources.add(key)
        if _is_cancelled(item.invoice.status):
            cancelled_sources.add(key)
        else:
            active_sources.add(key)

    cancelled_legacy_sources = _build_cancelled_legacy_source_map(branch_id)

    return active_sources, any_sources, cancelled_sources, cancelled_legacy_sources


def _coverage_rows(branch_id):
    rows = []
    active_sources, any_sources, cancelled_sources, cancelled_legacy_sources = _invoice_source_maps(branch_id)

    orders = DailyOrder.query.filter_by(branch_id=branch_id).order_by(DailyOrder.order_date.asc(), DailyOrder.id.asc()).all()

    for order in orders:
        if not order.is_locked:
            rows.append(_row(
                status="WARNING",
                check="Order -> production",
                item=order.order_number,
                expected="LOCKED",
                actual="OPEN/DRAFT",
                difference="-",
                note="Order belum locked, belum menjadi dasar produksi/invoice resmi.",
            ))
            continue

        for delivery_type in ["LUNCH", "DINNER"]:
            order_qty = sum(_delivery_type_qty(detail, delivery_type) for detail in order.details)
            if order_qty <= 0:
                continue

            production = _production_for_order(order, delivery_type)
            if not production:
                rows.append(_row(
                    status="WARNING",
                    check="Order -> production",
                    item=f"{order.order_number} | {delivery_type}",
                    expected=f"Production {delivery_type}",
                    actual="Belum ada production",
                    difference=f"{order_qty} porsi",
                    note="Order locked dengan porsi positif seharusnya punya production.",
                ))
                continue

            planned = sum(_float(detail.planned_qty) for detail in production.details)
            actual = sum(_float(detail.actual_qty) for detail in production.details)
            if _is_mismatch(planned, order_qty):
                rows.append(_row(
                    status="WARNING",
                    check="Order -> production",
                    item=f"{order.order_number} | {delivery_type}",
                    expected=f"{order_qty} porsi",
                    actual=f"{_qty(planned)} porsi",
                    difference=f"{_qty(planned - order_qty)} porsi",
                    note="Planned production tidak sama dengan total porsi order locked.",
                ))
            else:
                rows.append(_row(
                    status="AMAN",
                    check="Order -> production",
                    item=f"{order.order_number} | {delivery_type}",
                    expected=f"{order_qty} porsi",
                    actual=f"{_qty(planned)} porsi",
                    difference="0 porsi",
                    note=f"Production status {production.status}, actual {_qty(actual)} porsi.",
                ))

            delivery_breakdown = {
                "main_qty": 0,
                "replacement_qty": 0,
                "total_qty": 0,
                "main_count": 0,
                "replacement_count": 0,
            }

            for detail in order.details:
                detail_breakdown = _delivery_breakdown_for_order_detail(detail.id, delivery_type)
                for key in delivery_breakdown:
                    delivery_breakdown[key] += detail_breakdown[key]

            main_delivery_qty = delivery_breakdown["main_qty"]
            replacement_delivery_qty = delivery_breakdown["replacement_qty"]
            final_delivery_qty = delivery_breakdown["total_qty"]
            delivery_actual_label = (
                f"Utama {_qty(main_delivery_qty)} porsi, "
                f"pengganti shortage {_qty(replacement_delivery_qty)} porsi, "
                f"final {_qty(final_delivery_qty)} porsi"
            )

            if production.status != "COMPLETED" and final_delivery_qty > 0:
                rows.append(_row(
                    status="WARNING",
                    check="Production -> delivery",
                    item=f"{order.order_number} | {delivery_type}",
                    expected="Delivery setelah production COMPLETED",
                    actual=f"Production {production.status}, {delivery_actual_label}",
                    difference="-",
                    note="Kemungkinan data legacy/demo sebelum guard production COMPLETED diterapkan.",
                ))
            elif production.status == "COMPLETED" and final_delivery_qty < order_qty:
                rows.append(_row(
                    status="WARNING",
                    check="Production -> delivery",
                    item=f"{order.order_number} | {delivery_type}",
                    expected=f"Delivery final {_qty(order_qty)} porsi",
                    actual=delivery_actual_label,
                    difference=f"{_qty(order_qty - final_delivery_qty)} porsi",
                    note="Production sudah completed, tapi delivery final belum menutup seluruh porsi order.",
                ))
            else:
                rows.append(_row(
                    status="AMAN",
                    check="Production -> delivery",
                    item=f"{order.order_number} | {delivery_type}",
                    expected="Alur delivery sesuai status production",
                    actual=delivery_actual_label,
                    difference="-",
                    note=(
                        "Delivery utama dan pengganti shortage dihitung terpisah, "
                        "tetapi total final dipakai untuk menilai coverage."
                    ),
                ))

        for detail in order.details:
            if int(detail.total_qty or 0) <= 0:
                continue
            key = ("ORDER_DETAIL", detail.id)
            legacy_cancelled_invoices = cancelled_legacy_sources.get(key, [])
            if key in active_sources:
                status = "AMAN"
                actual = "Sudah masuk invoice aktif"
                note = "Coverage invoice aktif tersedia."
            elif key in cancelled_sources:
                status = "WARNING"
                actual = "Hanya ada di invoice CANCELLED"
                note = "Perlu invoice ulang jika memang masih harus ditagih."
            elif legacy_cancelled_invoices:
                status = "WARNING"
                actual = "Tercatat di invoice CANCELLED legacy"
                note = (
                    "Fallback legacy: data tertutup invoice CANCELLED "
                    f"{', '.join(legacy_cancelled_invoices)} yang belum punya source_type/source_id item."
                )
            else:
                status = "WARNING"
                actual = "Belum masuk invoice"
                note = "Bisa jadi beda periode/demo, tapi perlu terlihat sebagai billing coverage."

            rows.append(_row(
                status=status,
                check="Order -> invoice coverage",
                item=f"{order.order_number} | ORDER_DETAIL #{detail.id}",
                expected="Masuk invoice aktif jika sudah ditagih",
                actual=actual,
                difference="-",
                note=note,
            ))

            for revision in detail.revisions:
                if not _is_after_lock_invoice_revision(revision):
                    continue

                key = ("ORDER_REVISION", revision.id)
                legacy_cancelled_invoices = cancelled_legacy_sources.get(key, [])
                if key in active_sources:
                    status = "AMAN"
                    actual = "Sudah masuk invoice aktif"
                    note = "Revisi tambah setelah lock sudah tertagih."
                elif key in cancelled_sources:
                    status = "WARNING"
                    actual = "Hanya ada di invoice CANCELLED"
                    note = "Perlu invoice ulang jika revisi ini tetap harus ditagih."
                elif legacy_cancelled_invoices:
                    status = "WARNING"
                    actual = "Tercatat di invoice CANCELLED legacy"
                    note = (
                        "Fallback legacy: revisi tertutup invoice CANCELLED "
                        f"{', '.join(legacy_cancelled_invoices)} yang belum punya source_type/source_id item."
                    )
                else:
                    status = "WARNING"
                    actual = "Belum masuk invoice"
                    note = "Revisi tambah setelah lock perlu dipantau coverage invoice."

                rows.append(_row(
                    status=status,
                    check="Revision -> invoice coverage",
                    item=f"{order.order_number} | ORDER_REVISION #{revision.id}",
                    expected="Masuk invoice aktif jika sudah ditagih",
                    actual=actual,
                    difference="-",
                    note=note,
                ))

    debts = WorkerDebt.query.filter_by(branch_id=branch_id).order_by(WorkerDebt.id.asc()).all()
    for debt in debts:
        remaining = _float(debt.debt_amount) - sum(_float(payment.amount) for payment in debt.payments)
        if remaining <= TOLERANCE:
            continue

        key = ("WORKER_DEBT", debt.id)
        worker_name = getattr(getattr(debt, "worker", None), "full_name", f"Worker #{debt.worker_id}")
        if key in active_sources:
            rows.append(_row(
                status="AMAN",
                check="Worker debt -> invoice coverage",
                item=f"Debt #{debt.id} | {worker_name}",
                expected="Sisa hutang masuk invoice aktif",
                actual="Sudah masuk invoice aktif",
                difference="-",
                note=f"Sisa hutang {_money(remaining)} sudah tertagih di invoice aktif.",
            ))
        elif key in cancelled_sources:
            rows.append(_row(
                status="WARNING",
                check="Worker debt -> invoice coverage",
                item=f"Debt #{debt.id} | {worker_name}",
                expected="Sisa hutang masuk invoice aktif",
                actual="Hanya ada di invoice CANCELLED",
                difference="-",
                note=f"Sisa hutang {_money(remaining)} perlu dipantau untuk invoice ulang bila masih ditagih.",
            ))
        else:
            rows.append(_row(
                status="WARNING",
                check="Worker debt -> invoice coverage",
                item=f"Debt #{debt.id} | {worker_name}",
                expected=f"Sisa hutang masuk invoice aktif jika ditagih ke {T.client_lower}/{T.sub_client_lower}",
                actual="Belum masuk invoice",
                difference="-",
                note=f"Sisa hutang {_money(remaining)} belum punya coverage invoice.",
            ))

    if not rows:
        rows.append(_row(
            status="WARNING",
            check="Coverage alur bisnis",
            item="Belum ada order/coverage",
            note="Belum ada data order-production-delivery-invoice yang bisa divalidasi.",
        ))

    return rows


def _prepayment_refund_rows(branch_id):
    from app.services.prepaid_order_service import advances_to_refund

    rows = [
        _row(
            status="WARNING",
            check="Uang muka harus dikembalikan",
            item=advance.advance_number,
            expected="Rp 0",
            actual=_money(advance.remaining_amount),
            difference=_money(advance.remaining_amount),
            note=f"{reason} OWNER mengembalikannya di Finance > Uang Muka.",
        )
        for advance, reason in advances_to_refund(branch_id)
    ]
    if not rows:
        rows.append(_row(status="AMAN", check="Uang muka harus dikembalikan", item="Semua uang muka pelanggan",
                         note="Tidak ada sisa uang muka dari pesanan yang ditolak atau sudah ditagih."))
    return rows


def _subledger_rows(branch_id):
    """Buku pembantu vs buku besar, untuk semua cabang (jurnal tidak punya cabang)."""
    from app.services.subledger_check_service import subledger_lines, unjournaled_stock_movements

    rows = [
        _row(
            status="AMAN" if line.ok else "RISIKO",
            check=f"{line.label} = buku besar {line.accounts}",
            item=line.source,
            expected=_money(line.ledger),
            actual=_money(line.subledger),
            difference=_money(line.difference),
            note="Sama." if line.ok else "Ada transaksi tanpa jurnal, jurnal manual di akun ini, atau data lama sebelum jurnal otomatis.",
        )
        for line in subledger_lines()
    ]
    missing = unjournaled_stock_movements()
    rows.append(_row(
        status="WARNING" if missing else "AMAN",
        check="Pergerakan stok sudah dijurnal",
        item="Pemakaian, barang rusak, selisih opname",
        expected="0 tanpa jurnal",
        actual=f"{len(missing)} tanpa jurnal",
        note="Barang yang belum pernah dibeli lewat Pembelian Barang tidak punya harga rata-rata, jadi keluarnya tidak bisa dinilai." if missing else "Sama.",
    ))
    return rows


def get_data_health_report(branch_id):
    sections = [
        _section(
            "subledger",
            "Buku Pembantu vs Buku Besar",
            "Kas, bank, piutang, hutang supplier, persediaan, dan aset harus sama dengan saldo akunnya di jurnal (semua cabang).",
            _subledger_rows(branch_id),
        ),
        _section(
            "invoice",
            "Invoice, Payment, dan Piutang",
            "Validasi total invoice, payment, remaining, dan invoice cancelled agar tidak masuk piutang aktif.",
            _invoice_rows(branch_id) + _receivable_rows(branch_id) + _prepayment_refund_rows(branch_id),
        ),
        _section(
            "journal",
            "Jurnal Akuntansi",
            "Validasi balance debit-credit dan duplicate journal reference.",
            _journal_rows(branch_id),
        ),
        _section(
            "payroll",
            "Payroll SDM",
            "Validasi final salary karyawan internal.",
            _payroll_rows(branch_id),
        ),
        _section(
            "canteen",
            f"Warung dan Hutang {T.worker}",
            f"Validasi transaksi warung, hutang {T.worker_lower}, pembayaran hutang, dan status hutang.",
            _canteen_rows(branch_id),
        ),
        _section(
            "stock",
            "Pembelian dan Stok",
            "Validasi total pembelian, stok minus, stok kosong, dan stok menipis.",
            _stock_rows(branch_id),
        ),
        _section(
            "coverage",
            "Coverage Order -> Production -> Delivery -> Invoice",
            "Validasi keterhubungan order locked, produksi, delivery, dan coverage invoice.",
            _coverage_rows(branch_id),
        ),
    ]

    summary = {"AMAN": 0, "WARNING": 0, "RISIKO": 0, "total_checks": 0}
    for section in sections:
        for status, count in section["counts"].items():
            summary[status] += count
            summary["total_checks"] += count

    if summary["RISIKO"] > 0:
        overall_status = "RISIKO"
    elif summary["WARNING"] > 0:
        overall_status = "WARNING"
    else:
        overall_status = "AMAN"

    return {
        "generated_at": now_wib(),
        "branch_id": branch_id,
        "overall_status": overall_status,
        "overall_status_class": _status_class(overall_status),
        "summary": summary,
        "sections": sections,
    }
