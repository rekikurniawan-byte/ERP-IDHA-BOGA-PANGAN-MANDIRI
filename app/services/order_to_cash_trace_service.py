from datetime import datetime

from app.models.accounting import Account, Journal, JournalDetail
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice, InvoiceItem, Payment
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.production import Production, ProductionDetail


CANCELLED_STATUSES = {"CANCELLED", "CANCELED"}
PAID_STATUSES = {"PAID", "LUNAS"}


def _money_value(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _status_class(status):
    text = str(status or "").upper()

    if text in {"PAID", "LUNAS", "COMPLETED", "DELIVERED", "LOCKED", "BALANCED", "AMAN"}:
        return "status-success"

    if text in {"PARTIAL", "DRAFT", "OPEN", "PROCESS", "PREPARING", "PENDING"}:
        return "status-warning"

    if text in {"CANCELLED", "CANCELED", "FAILED", "ERROR", "UNBALANCED", "RISIKO"}:
        return "status-danger"

    return "status-muted"


def _base_step(name, status="Belum ada data", note=""):
    return {
        "name": name,
        "status": status,
        "status_class": _status_class(status),
        "note": note,
    }


def _row(label, value, note=""):
    return {
        "label": label,
        "value": value,
        "note": note,
    }


def _journal_trace(reference_type, reference_id):
    if not reference_type or not reference_id:
        return {
            "journal": None,
            "details": [],
            "total_debit": 0.0,
            "total_credit": 0.0,
            "is_balanced": False,
            "status": "Belum ada jurnal",
            "status_class": _status_class("PENDING"),
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
            "status_class": _status_class("PENDING"),
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
        debit = _money_value(detail.debit)
        credit = _money_value(detail.credit)
        total_debit += debit
        total_credit += credit

        rows.append({
            "account_code": detail.account.account_code,
            "account_name": detail.account.account_name,
            "debit": debit,
            "credit": credit,
        })

    is_balanced = round(total_debit, 2) == round(total_credit, 2)

    return {
        "journal": journal,
        "details": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": is_balanced,
        "status": "Balance" if is_balanced else "Tidak balance",
        "status_class": _status_class("BALANCED" if is_balanced else "UNBALANCED"),
    }


def _detect_delivery_type(delivery):
    text = f"{delivery.delivery_number or ''} {delivery.notes or ''}".upper()

    if "DINNER" in text or "MALAM" in text:
        return "DINNER"

    if "LUNCH" in text or "SIANG" in text:
        return "LUNCH"

    return "LAINNYA"


def _build_order_summary(order):
    details = DailyOrderDetail.query.filter_by(
        daily_order_id=order.id
    ).order_by(
        DailyOrderDetail.id.asc()
    ).all()

    detail_rows = []
    total_lunch = 0
    total_dinner = 0
    total_qty = 0
    total_amount = 0.0

    for detail in details:
        lunch_qty = int(detail.lunch_qty or 0)
        dinner_qty = int(detail.dinner_qty or 0)
        qty = int(detail.total_qty or 0)
        price = _money_value(detail.price_per_portion)
        subtotal = qty * price

        total_lunch += lunch_qty
        total_dinner += dinner_qty
        total_qty += qty
        total_amount += subtotal

        client_name = "-"
        if detail.mandor and detail.mandor.client:
            client_name = detail.mandor.client.name

        location_name = "-"
        if detail.delivery_location:
            location_name = detail.delivery_location.location_name

        detail_rows.append({
            "id": detail.id,
            "client_name": client_name,
            "mandor_name": detail.mandor.name if detail.mandor else "-",
            "location_name": location_name,
            "lunch_qty": lunch_qty,
            "dinner_qty": dinner_qty,
            "total_qty": qty,
            "price_per_portion": price,
            "subtotal": subtotal,
        })

    return {
        "order": order,
        "details": detail_rows,
        "detail_ids": [detail.id for detail in details],
        "total_lunch": total_lunch,
        "total_dinner": total_dinner,
        "total_qty": total_qty,
        "total_amount": total_amount,
    }


def _build_production_summary(order):
    productions = Production.query.filter(
        Production.branch_id == order.branch_id,
        Production.production_date == order.order_date,
        Production.notes.ilike(f"%{order.order_number}%"),
    ).order_by(
        Production.production_type.asc(),
        Production.id.asc(),
    ).all()

    rows = []
    total_planned = 0.0
    total_actual = 0.0
    completed_count = 0

    for production in productions:
        details = ProductionDetail.query.filter_by(
            production_id=production.id
        ).order_by(
            ProductionDetail.id.asc()
        ).all()

        planned = sum(_money_value(detail.planned_qty) for detail in details)
        actual = sum(_money_value(detail.actual_qty) for detail in details)
        total_planned += planned
        total_actual += actual

        if str(production.status or "").upper() == "COMPLETED":
            completed_count += 1

        rows.append({
            "id": production.id,
            "production_type": production.production_type,
            "status": production.status,
            "status_class": _status_class(production.status),
            "planned_qty": planned,
            "actual_qty": actual,
            "detail_count": len(details),
        })

    if not rows:
        status = "Belum ada data"
    elif completed_count == len(rows):
        status = "Completed"
    else:
        status = "Belum selesai"

    return {
        "rows": rows,
        "total_planned": total_planned,
        "total_actual": total_actual,
        "status": status,
        "status_class": _status_class(status),
    }


def _build_delivery_summary(detail_ids):
    rows = []
    total_planned = 0
    total_delivered = 0
    total_shortage = 0
    lunch_delivered = 0
    dinner_delivered = 0

    if detail_ids:
        delivery_details = DeliveryDetail.query.join(
            Delivery, DeliveryDetail.delivery_id == Delivery.id
        ).filter(
            DeliveryDetail.daily_order_detail_id.in_(detail_ids)
        ).order_by(
            Delivery.delivery_date.asc(),
            Delivery.id.asc(),
            DeliveryDetail.id.asc(),
        ).all()
    else:
        delivery_details = []

    for detail in delivery_details:
        delivery_type = _detect_delivery_type(detail.delivery)
        planned = int(detail.planned_qty or 0)
        delivered = int(detail.delivered_qty or 0)
        shortage = int(detail.shortage_qty or 0)

        total_planned += planned
        total_delivered += delivered
        total_shortage += shortage

        if delivery_type == "LUNCH":
            lunch_delivered += delivered
        elif delivery_type == "DINNER":
            dinner_delivered += delivered

        rows.append({
            "delivery_number": detail.delivery.delivery_number,
            "delivery_date": detail.delivery.delivery_date,
            "delivery_type": delivery_type,
            "status": detail.delivery.status,
            "status_class": _status_class(detail.delivery.status),
            "planned_qty": planned,
            "delivered_qty": delivered,
            "shortage_qty": shortage,
        })

    if not rows:
        status = "Belum ada data"
    elif total_shortage == 0:
        status = "Delivered"
    else:
        status = "Ada selisih"

    return {
        "rows": rows,
        "total_planned": total_planned,
        "total_delivered": total_delivered,
        "total_shortage": total_shortage,
        "lunch_delivered": lunch_delivered,
        "dinner_delivered": dinner_delivered,
        "status": status,
        "status_class": _status_class(status),
    }


def _build_invoice_summary(order, detail_ids):
    invoices = Invoice.query.filter(
        Invoice.branch_id == order.branch_id,
        Invoice.source_order_id == order.id,
    ).order_by(
        Invoice.id.asc()
    ).all()

    if not invoices and detail_ids:
        invoice_ids = [row.invoice_id for row in InvoiceItem.query.filter(
            InvoiceItem.source_type == "ORDER_DETAIL",
            InvoiceItem.source_id.in_(detail_ids),
        ).all()]

        if invoice_ids:
            invoices = Invoice.query.filter(
                Invoice.id.in_(invoice_ids)
            ).order_by(
                Invoice.id.asc()
            ).all()

    rows = []
    active_rows = []
    total_amount = 0.0
    paid_amount = 0.0
    remaining_amount = 0.0
    invoice_journals = []

    for invoice in invoices:
        status_text = str(invoice.status or "").upper()
        is_cancelled = status_text in CANCELLED_STATUSES
        total = _money_value(invoice.total_amount)
        paid = _money_value(invoice.paid_amount)
        remaining = _money_value(invoice.remaining_amount)
        journal_trace = _journal_trace("INVOICE", invoice.id)

        item_rows = []
        for item in invoice.items:
            item_rows.append({
                "item_type": item.item_type,
                "description": item.description,
                "qty": _money_value(item.qty),
                "unit_price": _money_value(item.unit_price),
                "subtotal": _money_value(item.subtotal),
                "source_type": item.source_type,
                "source_id": item.source_id,
            })

        row = {
            "invoice": invoice,
            "is_cancelled": is_cancelled,
            "items": item_rows,
            "total_amount": total,
            "paid_amount": paid,
            "remaining_amount": remaining,
            "status_class": _status_class(invoice.status),
            "journal": journal_trace,
        }

        rows.append(row)
        invoice_journals.append(journal_trace)

        if not is_cancelled:
            active_rows.append(row)
            total_amount += total
            paid_amount += paid
            remaining_amount += remaining

    if not rows:
        status = "Belum ada invoice"
    elif remaining_amount <= 0 and active_rows:
        status = "Lunas"
    elif paid_amount > 0:
        status = "Sebagian dibayar"
    else:
        status = "Belum lunas"

    return {
        "rows": rows,
        "active_rows": active_rows,
        "invoice_ids": [row["invoice"].id for row in active_rows],
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "status": status,
        "status_class": _status_class("PAID" if status == "Lunas" else status),
        "invoice_journals": invoice_journals,
    }


def _build_payment_summary(invoice_ids):
    rows = []
    total_paid = 0.0
    payment_journals = []

    if invoice_ids:
        payments = Payment.query.filter(
            Payment.invoice_id.in_(invoice_ids)
        ).order_by(
            Payment.payment_date.asc(),
            Payment.id.asc(),
        ).all()
    else:
        payments = []

    for payment in payments:
        amount = _money_value(payment.amount)
        total_paid += amount
        journal_trace = _journal_trace("PAYMENT", payment.id)
        payment_journals.append(journal_trace)

        rows.append({
            "payment": payment,
            "amount": amount,
            "status": "Tercatat",
            "status_class": _status_class("AMAN"),
            "journal": journal_trace,
        })

    return {
        "rows": rows,
        "total_paid": total_paid,
        "status": "Ada payment" if rows else "Belum ada payment",
        "status_class": _status_class("PAID" if rows else "PENDING"),
        "payment_journals": payment_journals,
    }


def _build_trace_steps(order_summary, production, delivery, invoice, payment):
    order = order_summary["order"]

    steps = [
        _base_step(
            "Order",
            order.status,
            f"{order.order_number} | Total {order_summary['total_qty']} porsi",
        ),
        _base_step(
            "Produksi",
            production["status"],
            f"Actual {production['total_actual']:.0f} dari planned {production['total_planned']:.0f}",
        ),
        _base_step(
            "Pengiriman",
            delivery["status"],
            f"Terkirim {delivery['total_delivered']} dari rencana {delivery['total_planned']}",
        ),
        _base_step(
            "Invoice",
            invoice["status"],
            f"Total invoice aktif {invoice['total_amount']:.0f}",
        ),
        _base_step(
            "Payment",
            payment["status"],
            f"Total dibayar {payment['total_paid']:.0f}",
        ),
    ]

    journal_items = invoice["invoice_journals"] + payment["payment_journals"]
    balanced_count = len([item for item in journal_items if item["is_balanced"]])

    if not journal_items:
        journal_status = "Belum ada jurnal"
    elif balanced_count == len(journal_items):
        journal_status = "Balance"
    else:
        journal_status = "Tidak balance"

    steps.append(_base_step(
        "Jurnal",
        journal_status,
        f"{balanced_count}/{len(journal_items)} jurnal balance",
    ))

    return steps


def _empty_report(branch_id, selected_order_number, order_options):
    message = "Belum ada order production clean." if not order_options else "Pilih nomor order untuk melihat jejak."

    if selected_order_number:
        message = "Nomor order tidak ditemukan pada cabang ini."

    return {
        "generated_at": datetime.now(),
        "branch_id": branch_id,
        "selected_order_number": selected_order_number,
        "order_options": order_options,
        "has_order": False,
        "empty_message": message,
        "steps": [],
        "order_summary": None,
        "production": None,
        "delivery": None,
        "invoice": None,
        "payment": None,
        "receivable_status": "Belum ada data",
        "receivable_class": _status_class("PENDING"),
        "overall_status": "Belum ada order",
        "overall_status_class": _status_class("PENDING"),
    }


def get_order_to_cash_trace_report(branch_id, selected_order_number=""):
    selected_order_number = (selected_order_number or "").strip()

    order_options = DailyOrder.query.filter_by(
        branch_id=branch_id
    ).order_by(
        DailyOrder.order_date.desc(),
        DailyOrder.id.desc(),
    ).limit(50).all()

    order = None

    if selected_order_number:
        order = DailyOrder.query.filter_by(
            branch_id=branch_id,
            order_number=selected_order_number,
        ).first()

    if not order:
        return _empty_report(branch_id, selected_order_number, order_options)

    order_summary = _build_order_summary(order)
    production = _build_production_summary(order)
    delivery = _build_delivery_summary(order_summary["detail_ids"])
    invoice = _build_invoice_summary(order, order_summary["detail_ids"])
    payment = _build_payment_summary(invoice["invoice_ids"])
    steps = _build_trace_steps(order_summary, production, delivery, invoice, payment)

    if invoice["remaining_amount"] <= 0 and invoice["active_rows"]:
        receivable_status = "Lunas"
    elif invoice["remaining_amount"] > 0:
        receivable_status = "Masih ada piutang"
    else:
        receivable_status = "Belum ada invoice aktif"

    if receivable_status == "Lunas":
        overall_status = "Lunas"
    elif invoice["active_rows"]:
        overall_status = "Belum lunas"
    else:
        overall_status = "Belum lengkap"

    return {
        "generated_at": datetime.now(),
        "branch_id": branch_id,
        "selected_order_number": selected_order_number,
        "order_options": order_options,
        "has_order": True,
        "empty_message": "",
        "steps": steps,
        "order_summary": order_summary,
        "production": production,
        "delivery": delivery,
        "invoice": invoice,
        "payment": payment,
        "receivable_status": receivable_status,
        "receivable_class": _status_class("PAID" if receivable_status == "Lunas" else "PENDING"),
        "overall_status": overall_status,
        "overall_status_class": _status_class("PAID" if overall_status == "Lunas" else "PENDING"),
    }
