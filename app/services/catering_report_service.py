import logging
from calendar import monthrange
from datetime import date, datetime

from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice, InvoiceItem
from app.models.master import Mandor
from app.models.operational import DailyOrder
from app.services.delivery_service import get_delivery_type_from_notes

logger = logging.getLogger(__name__)


def parse_date(value, fallback=None):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/catering_report_service.py:14")
        return fallback


def parse_month(value, fallback=None):
    try:
        parsed = datetime.strptime(str(value or "").strip(), "%Y-%m").date()
        return parsed.year, parsed.month
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/catering_report_service.py:22")
        fallback = fallback or date.today()
        return fallback.year, fallback.month


def month_bounds(year, month):
    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])
    return start_date, end_date


def safe_label(obj, fallback="-"):
    if not obj:
        return fallback

    for attr in ["name", "full_name", "location_name", "mandor_name", "client_name"]:
        value = getattr(obj, attr, None)
        if value:
            return str(value)

    return fallback


def _invoice_item_exists(source_type, source_id):
    if not source_type or not source_id:
        return False

    return InvoiceItem.query.filter_by(
        source_type=source_type,
        source_id=source_id,
    ).first() is not None


def _daily_order_invoice_exists(branch_id, order_id, mandor_id):
    return Invoice.query.filter_by(
        branch_id=branch_id,
        source_type="DAILY_ORDER",
        source_order_id=order_id,
        mandor_id=mandor_id,
    ).first() is not None


def _delivery_totals_by_detail(branch_id, start_date, end_date):
    delivery_details = DeliveryDetail.query.join(Delivery).filter(
        Delivery.branch_id == branch_id,
        Delivery.delivery_date >= start_date,
        Delivery.delivery_date <= end_date,
        Delivery.status != "CANCELLED",
    ).all()

    totals = {}
    for delivery_detail in delivery_details:
        delivery_type = get_delivery_type_from_notes(delivery_detail.delivery.notes)
        key = (delivery_detail.daily_order_detail_id, delivery_type)
        current = totals.setdefault(key, {"planned": 0, "delivered": 0, "shortage": 0, "count": 0})
        current["planned"] += int(delivery_detail.planned_qty or 0)
        current["delivered"] += int(delivery_detail.delivered_qty or 0)
        current["shortage"] += int(delivery_detail.shortage_qty or 0)
        current["count"] += 1

    return totals


def _revision_totals(detail):
    qty = 0
    amount = 0
    count = 0

    for revision in getattr(detail, "revisions", []) or []:
        revision_type = str(getattr(revision, "revision_type", "") or "").upper()
        direction = str(getattr(revision, "revision_direction", "") or "").upper()
        if direction != "INCREASE" or not revision_type.startswith("AFTER_LOCK"):
            continue

        lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
        dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
        revision_qty = lunch_change + dinner_change
        if revision_qty <= 0:
            continue

        price = getattr(revision, "price_per_portion", None)
        if price is None:
            price = getattr(detail, "price_per_portion", 0) or 0

        qty += revision_qty
        amount += revision_qty * float(price or 0)
        count += 1

    return {"qty": qty, "amount": amount, "count": count}


def _billing_state(order, detail):
    if str(order.status or "").upper() != "LOCKED":
        return "BELUM_LOCK"

    if _daily_order_invoice_exists(order.branch_id, order.id, detail.mandor_id):
        return "SUDAH_INVOICE"

    if _invoice_item_exists("ORDER_DETAIL", detail.id):
        return "SUDAH_INVOICE"

    return "SIAP_TAGIH"


def build_daily_catering_log(branch_id, target_date):
    orders = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.order_date == target_date,
    ).order_by(DailyOrder.id.asc()).all()

    delivery_totals = _delivery_totals_by_detail(branch_id, target_date, target_date)

    rows = []
    summary = {
        "order_count": len(orders),
        "location_count": 0,
        "mandor_count": 0,
        "lunch_qty": 0,
        "dinner_qty": 0,
        "total_qty": 0,
        "delivered_qty": 0,
        "shortage_qty": 0,
        "amount": 0,
        "locked_count": 0,
        "ready_to_bill_count": 0,
        "invoiced_count": 0,
    }
    mandor_ids = set()

    for order in orders:
        if str(order.status or "").upper() == "LOCKED":
            summary["locked_count"] += 1

        for detail in order.details:
            lunch_qty = int(detail.lunch_qty or 0)
            dinner_qty = int(detail.dinner_qty or 0)
            total_qty = int(detail.total_qty or (lunch_qty + dinner_qty))
            price = float(detail.price_per_portion or 0)
            amount = total_qty * price
            lunch_delivery = delivery_totals.get((detail.id, "LUNCH"), {"planned": 0, "delivered": 0, "shortage": lunch_qty, "count": 0})
            dinner_delivery = delivery_totals.get((detail.id, "DINNER"), {"planned": 0, "delivered": 0, "shortage": dinner_qty, "count": 0})
            delivered_qty = int(lunch_delivery["delivered"] or 0) + int(dinner_delivery["delivered"] or 0)
            shortage_qty = max(total_qty - delivered_qty, 0)
            billing_state = _billing_state(order, detail)

            if billing_state == "SIAP_TAGIH":
                summary["ready_to_bill_count"] += 1
            elif billing_state == "SUDAH_INVOICE":
                summary["invoiced_count"] += 1

            mandor_ids.add(detail.mandor_id)
            summary["location_count"] += 1
            summary["lunch_qty"] += lunch_qty
            summary["dinner_qty"] += dinner_qty
            summary["total_qty"] += total_qty
            summary["delivered_qty"] += delivered_qty
            summary["shortage_qty"] += shortage_qty
            summary["amount"] += amount

            rows.append({
                "order": order,
                "detail": detail,
                "mandor_name": safe_label(getattr(detail, "mandor", None)),
                "location_name": safe_label(getattr(detail, "delivery_location", None)),
                "lunch_qty": lunch_qty,
                "dinner_qty": dinner_qty,
                "total_qty": total_qty,
                "price_per_portion": price,
                "amount": amount,
                "lunch_delivery": lunch_delivery,
                "dinner_delivery": dinner_delivery,
                "delivered_qty": delivered_qty,
                "shortage_qty": shortage_qty,
                "billing_state": billing_state,
            })

    summary["mandor_count"] = len(mandor_ids)
    return {"rows": rows, "summary": summary, "target_date": target_date}


def get_active_mandors(branch_id):
    query = Mandor.query
    if hasattr(Mandor, "branch_id"):
        query = query.filter_by(branch_id=branch_id)
    if hasattr(Mandor, "is_active"):
        query = query.filter_by(is_active=True)
    return query.order_by(Mandor.name.asc()).all()


def build_monthly_catering_recap(branch_id, year, month, mandor_id=None, start_date=None, end_date=None):
    if start_date is None or end_date is None:
        start_date, end_date = month_bounds(year, month)
    orders = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.order_date >= start_date,
        DailyOrder.order_date <= end_date,
    ).order_by(DailyOrder.order_date.asc(), DailyOrder.id.asc()).all()

    delivery_totals = _delivery_totals_by_detail(branch_id, start_date, end_date)
    grouped = {}
    mandor_totals = {}
    summary = {
        "order_count": len(orders),
        "locked_order_count": 0,
        "row_count": 0,
        "mandor_count": 0,
        "location_count": 0,
        "lunch_qty": 0,
        "dinner_qty": 0,
        "total_qty": 0,
        "delivered_qty": 0,
        "shortage_qty": 0,
        "base_amount": 0,
        "revision_qty": 0,
        "revision_amount": 0,
        "invoice_candidate_amount": 0,
        "ready_to_bill_count": 0,
        "invoiced_count": 0,
        "draft_count": 0,
    }
    location_keys = set()

    for order in orders:
        is_locked = str(order.status or "").upper() == "LOCKED"
        if is_locked:
            summary["locked_order_count"] += 1

        for detail in order.details:
            if mandor_id and int(detail.mandor_id or 0) != int(mandor_id):
                continue

            lunch_qty = int(detail.lunch_qty or 0)
            dinner_qty = int(detail.dinner_qty or 0)
            total_qty = int(detail.total_qty or (lunch_qty + dinner_qty))
            price = float(detail.price_per_portion or 0)
            base_amount = total_qty * price
            revision = _revision_totals(detail)
            invoice_candidate_amount = base_amount + float(revision["amount"] or 0)
            lunch_delivery = delivery_totals.get((detail.id, "LUNCH"), {"planned": 0, "delivered": 0, "shortage": lunch_qty, "count": 0})
            dinner_delivery = delivery_totals.get((detail.id, "DINNER"), {"planned": 0, "delivered": 0, "shortage": dinner_qty, "count": 0})
            delivered_qty = int(lunch_delivery["delivered"] or 0) + int(dinner_delivery["delivered"] or 0)
            shortage_qty = max(total_qty - delivered_qty, 0)
            billing_state = _billing_state(order, detail)

            key = (detail.mandor_id, detail.delivery_location_id)
            row = grouped.setdefault(key, {
                "mandor_id": detail.mandor_id,
                "location_id": detail.delivery_location_id,
                "mandor_name": safe_label(getattr(detail, "mandor", None)),
                "location_name": safe_label(getattr(detail, "delivery_location", None)),
                "order_count": 0,
                "locked_count": 0,
                "draft_count": 0,
                "lunch_qty": 0,
                "dinner_qty": 0,
                "total_qty": 0,
                "delivered_qty": 0,
                "shortage_qty": 0,
                "base_amount": 0,
                "revision_qty": 0,
                "revision_amount": 0,
                "invoice_candidate_amount": 0,
                "ready_to_bill_count": 0,
                "invoiced_count": 0,
                "billing_state": "BELUM_LOCK",
            })

            row["order_count"] += 1
            row["locked_count"] += 1 if is_locked else 0
            row["draft_count"] += 0 if is_locked else 1
            row["lunch_qty"] += lunch_qty
            row["dinner_qty"] += dinner_qty
            row["total_qty"] += total_qty
            row["delivered_qty"] += delivered_qty
            row["shortage_qty"] += shortage_qty
            row["base_amount"] += base_amount
            row["revision_qty"] += revision["qty"]
            row["revision_amount"] += revision["amount"]
            row["invoice_candidate_amount"] += invoice_candidate_amount
            row["ready_to_bill_count"] += 1 if billing_state == "SIAP_TAGIH" else 0
            row["invoiced_count"] += 1 if billing_state == "SUDAH_INVOICE" else 0

            location_keys.add(key)
            mandor_summary = mandor_totals.setdefault(detail.mandor_id, {
                "mandor_id": detail.mandor_id,
                "mandor_name": safe_label(getattr(detail, "mandor", None)),
                "total_qty": 0,
                "invoice_candidate_amount": 0,
                "ready_to_bill_count": 0,
                "invoiced_count": 0,
                "draft_count": 0,
            })
            mandor_summary["total_qty"] += total_qty
            mandor_summary["invoice_candidate_amount"] += invoice_candidate_amount
            mandor_summary["ready_to_bill_count"] += 1 if billing_state == "SIAP_TAGIH" else 0
            mandor_summary["invoiced_count"] += 1 if billing_state == "SUDAH_INVOICE" else 0
            mandor_summary["draft_count"] += 0 if is_locked else 1

            summary["row_count"] += 1
            summary["lunch_qty"] += lunch_qty
            summary["dinner_qty"] += dinner_qty
            summary["total_qty"] += total_qty
            summary["delivered_qty"] += delivered_qty
            summary["shortage_qty"] += shortage_qty
            summary["base_amount"] += base_amount
            summary["revision_qty"] += revision["qty"]
            summary["revision_amount"] += revision["amount"]
            summary["invoice_candidate_amount"] += invoice_candidate_amount
            summary["ready_to_bill_count"] += 1 if billing_state == "SIAP_TAGIH" else 0
            summary["invoiced_count"] += 1 if billing_state == "SUDAH_INVOICE" else 0
            summary["draft_count"] += 0 if is_locked else 1

    rows = []
    for row in grouped.values():
        if row["draft_count"] > 0 and row["locked_count"] == 0:
            row["billing_state"] = "BELUM_LOCK"
        elif row["invoiced_count"] > 0 and row["ready_to_bill_count"] == 0 and row["draft_count"] == 0:
            row["billing_state"] = "SUDAH_INVOICE"
        elif row["invoiced_count"] > 0 and row["ready_to_bill_count"] > 0:
            row["billing_state"] = "SEBAGIAN"
        elif row["ready_to_bill_count"] > 0:
            row["billing_state"] = "SIAP_TAGIH"
        rows.append(row)

    rows.sort(key=lambda item: (item["mandor_name"], item["location_name"]))
    summary["mandor_count"] = len(mandor_totals)
    summary["location_count"] = len(location_keys)
    return {
        "rows": rows,
        "mandor_totals": sorted(mandor_totals.values(), key=lambda item: item["mandor_name"]),
        "summary": summary,
        "start_date": start_date,
        "end_date": end_date,
        "month_value": f"{year:04d}-{month:02d}",
    }
