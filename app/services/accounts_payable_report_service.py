from datetime import date

from app.models.finance import SupplierBill, SupplierPayment
from app.utils.clock import today_wib


AGING_BUCKETS = [
    {"key": "CURRENT", "label": "Belum Jatuh Tempo", "min": None, "max": 0},
    {"key": "DAYS_0_30", "label": "0-30 Hari", "min": 1, "max": 30},
    {"key": "DAYS_31_60", "label": "31-60 Hari", "min": 31, "max": 60},
    {"key": "DAYS_61_90", "label": "61-90 Hari", "min": 61, "max": 90},
    {"key": "DAYS_OVER_90", "label": "> 90 Hari", "min": 91, "max": None},
]


def _money_value(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _bill_supplier_key(bill):
    if getattr(bill, "supplier_id", None):
        return f"SUPPLIER:{bill.supplier_id}"

    name = (getattr(bill, "supplier_name", None) or "Supplier / toko tidak tetap").strip()
    return f"MANUAL:{name.upper()}"


def _bill_supplier_label(bill):
    supplier = getattr(bill, "supplier", None)
    if supplier:
        return supplier.supplier_name

    return getattr(bill, "supplier_name", None) or "Supplier / toko tidak tetap"


def _bucket_for_bill(bill, as_of_date):
    remaining = _money_value(getattr(bill, "remaining_amount", 0))
    status = str(getattr(bill, "status", "") or "").upper()

    if remaining <= 0 or status == "PAID":
        return {
            "key": "PAID",
            "label": "Lunas",
            "days_overdue": 0,
            "days_to_due": 0,
            "badge_class": "status-locked",
        }

    days_to_due = (bill.due_date - as_of_date).days

    if days_to_due >= 0:
        return {
            "key": "CURRENT",
            "label": "Belum Jatuh Tempo",
            "days_overdue": 0,
            "days_to_due": days_to_due,
            "badge_class": "status-draft",
        }

    days_overdue = abs(days_to_due)

    if days_overdue <= 30:
        key = "DAYS_0_30"
        label = "0-30 Hari"
    elif days_overdue <= 60:
        key = "DAYS_31_60"
        label = "31-60 Hari"
    elif days_overdue <= 90:
        key = "DAYS_61_90"
        label = "61-90 Hari"
    else:
        key = "DAYS_OVER_90"
        label = "> 90 Hari"

    return {
        "key": key,
        "label": label,
        "days_overdue": days_overdue,
        "days_to_due": days_to_due,
        "badge_class": "status-danger" if days_overdue > 90 else "status-progress",
    }


def build_ap_aging_report(branch_id, as_of_date=None, supplier_id=None):
    as_of_date = as_of_date or today_wib()

    query = SupplierBill.query.filter(SupplierBill.branch_id == branch_id)

    if supplier_id:
        query = query.filter(SupplierBill.supplier_id == supplier_id)

    bills = query.order_by(SupplierBill.due_date.asc(), SupplierBill.id.asc()).all()

    buckets = {
        "CURRENT": {"key": "CURRENT", "label": "Belum Jatuh Tempo", "count": 0, "total": 0.0},
        "DAYS_0_30": {"key": "DAYS_0_30", "label": "0-30 Hari", "count": 0, "total": 0.0},
        "DAYS_31_60": {"key": "DAYS_31_60", "label": "31-60 Hari", "count": 0, "total": 0.0},
        "DAYS_61_90": {"key": "DAYS_61_90", "label": "61-90 Hari", "count": 0, "total": 0.0},
        "DAYS_OVER_90": {"key": "DAYS_OVER_90", "label": "> 90 Hari", "count": 0, "total": 0.0},
    }

    rows = []
    total_open = 0.0
    paid_count = 0

    for bill in bills:
        remaining = _money_value(bill.remaining_amount)
        bucket = _bucket_for_bill(bill, as_of_date)

        if bucket["key"] == "PAID":
            paid_count += 1
            continue

        total_open += remaining
        buckets[bucket["key"]]["count"] += 1
        buckets[bucket["key"]]["total"] += remaining

        rows.append({
            "bill": bill,
            "supplier_name": _bill_supplier_label(bill),
            "supplier_key": _bill_supplier_key(bill),
            "bucket": bucket,
            "remaining": remaining,
            "procurement": getattr(bill, "procurement", None),
        })

    summary = {
        "total_open": total_open,
        "open_count": len(rows),
        "paid_count": paid_count,
        "overdue_total": sum(buckets[key]["total"] for key in ["DAYS_0_30", "DAYS_31_60", "DAYS_61_90", "DAYS_OVER_90"]),
        "overdue_count": sum(buckets[key]["count"] for key in ["DAYS_0_30", "DAYS_31_60", "DAYS_61_90", "DAYS_OVER_90"]),
    }

    return {
        "as_of_date": as_of_date,
        "buckets": buckets,
        "rows": rows,
        "summary": summary,
    }


def list_supplier_card_groups(branch_id):
    bills = SupplierBill.query.filter_by(branch_id=branch_id).order_by(
        SupplierBill.supplier_name.asc(),
        SupplierBill.due_date.asc(),
    ).all()

    groups = {}

    for bill in bills:
        key = _bill_supplier_key(bill)
        if key not in groups:
            groups[key] = {
                "key": key,
                "supplier_id": bill.supplier_id,
                "supplier_name": _bill_supplier_label(bill),
                "bill_count": 0,
                "open_count": 0,
                "total_billed": 0.0,
                "total_paid": 0.0,
                "remaining": 0.0,
            }

        group = groups[key]
        group["bill_count"] += 1
        group["total_billed"] += _money_value(bill.total_amount)
        group["total_paid"] += _money_value(bill.paid_amount)
        group["remaining"] += _money_value(bill.remaining_amount)

        if _money_value(bill.remaining_amount) > 0 and str(bill.status or "").upper() != "PAID":
            group["open_count"] += 1

    return sorted(groups.values(), key=lambda row: (row["supplier_name"] or "").lower())


def build_supplier_payable_card(branch_id, supplier_key=None, start_date=None, end_date=None):
    groups = list_supplier_card_groups(branch_id)

    if not supplier_key and groups:
        supplier_key = groups[0]["key"]

    selected_group = None
    for group in groups:
        if group["key"] == supplier_key:
            selected_group = group
            break

    if not selected_group:
        return {
            "groups": groups,
            "selected_group": None,
            "activities": [],
            "summary": {
                "opening_balance": 0.0,
                "total_bill_in_period": 0.0,
                "total_payment_in_period": 0.0,
                "ending_balance": 0.0,
            },
        }

    bills_query = SupplierBill.query.filter(SupplierBill.branch_id == branch_id)

    if selected_group.get("supplier_id"):
        bills_query = bills_query.filter(SupplierBill.supplier_id == selected_group["supplier_id"])
    else:
        manual_name = selected_group["supplier_name"]
        bills_query = bills_query.filter(
            SupplierBill.supplier_id.is_(None),
            SupplierBill.supplier_name == manual_name,
        )

    bills = bills_query.order_by(SupplierBill.bill_date.asc(), SupplierBill.id.asc()).all()
    bill_ids = [bill.id for bill in bills]

    payments = []
    if bill_ids:
        payments = SupplierPayment.query.filter(
            SupplierPayment.branch_id == branch_id,
            SupplierPayment.supplier_bill_id.in_(bill_ids),
        ).order_by(SupplierPayment.payment_date.asc(), SupplierPayment.id.asc()).all()

    opening_balance = 0.0
    period_activities = []
    total_bill_in_period = 0.0
    total_payment_in_period = 0.0

    for bill in bills:
        bill_amount = _money_value(bill.total_amount)
        if start_date and bill.bill_date < start_date:
            opening_balance += bill_amount
            continue
        if end_date and bill.bill_date > end_date:
            continue

        period_activities.append({
            "date": bill.bill_date,
            "sort_id": bill.id,
            "kind": "BILL",
            "description": f"Bill {bill.bill_number}",
            "debit": bill_amount,
            "credit": 0.0,
            "bill": bill,
            "payment": None,
        })
        total_bill_in_period += bill_amount

    bill_lookup = {bill.id: bill for bill in bills}

    for payment in payments:
        payment_amount = _money_value(payment.amount)
        if start_date and payment.payment_date < start_date:
            opening_balance -= payment_amount
            continue
        if end_date and payment.payment_date > end_date:
            continue

        period_activities.append({
            "date": payment.payment_date,
            "sort_id": payment.id,
            "kind": "PAYMENT",
            "description": f"Pembayaran {payment.payment_number}",
            "debit": 0.0,
            "credit": payment_amount,
            "bill": bill_lookup.get(payment.supplier_bill_id),
            "payment": payment,
        })
        total_payment_in_period += payment_amount

    period_activities.sort(key=lambda row: (row["date"], 0 if row["kind"] == "BILL" else 1, row["sort_id"]))

    running = opening_balance
    for activity in period_activities:
        running += activity["debit"]
        running -= activity["credit"]
        activity["running_balance"] = running

    return {
        "groups": groups,
        "selected_group": selected_group,
        "activities": period_activities,
        "summary": {
            "opening_balance": opening_balance,
            "total_bill_in_period": total_bill_in_period,
            "total_payment_in_period": total_payment_in_period,
            "ending_balance": running,
        },
    }
