"""Read-only invoice profit report from HPP snapshot allocations.

PRODUCTION
- Tidak mengubah invoice.
- Tidak membuat jurnal/stok.
- Hanya membaca invoice_items dan order_hpp_snapshot_allocations.
"""


from app.models.finance import Invoice
from app.models.operational import (
    DailyOrderDetail,
    OrderHppSnapshot,
    OrderHppSnapshotAllocation,
)
from app.utils.terms import T


def _safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _percent(part, total):
    total = _safe_float(total)
    if total <= 0:
        return 0.0
    return (_safe_float(part) / total) * 100


def _margin_percent(profit, revenue):
    revenue = _safe_float(revenue)
    if revenue <= 0:
        return 0.0
    return (_safe_float(profit) / revenue) * 100


def _latest_snapshot_for_order(order_id, branch_id):
    if not order_id:
        return None

    return OrderHppSnapshot.query.filter_by(
        branch_id=branch_id,
        daily_order_id=order_id,
    ).order_by(
        OrderHppSnapshot.snapshot_date.desc(),
        OrderHppSnapshot.id.desc(),
    ).first()


def _allocations_for_order_detail(detail_id, branch_id):
    detail = DailyOrderDetail.query.get(detail_id)

    if not detail:
        return [], None, "Detail order sumber invoice tidak ditemukan."

    order = getattr(detail, "daily_order", None)

    if not order or _safe_int(getattr(order, "branch_id", None)) != _safe_int(branch_id):
        return [], None, "Detail order tidak sesuai cabang user."

    latest_snapshot = _latest_snapshot_for_order(order.id, branch_id)

    if not latest_snapshot:
        return [], None, "Order sumber invoice belum punya Snapshot HPP."

    allocations = OrderHppSnapshotAllocation.query.filter_by(
        snapshot_id=latest_snapshot.id,
        source_type="ORDER_DETAIL",
        source_id=detail.id,
    ).order_by(
        OrderHppSnapshotAllocation.meal_type.asc(),
        OrderHppSnapshotAllocation.id.asc(),
    ).all()

    if not allocations:
        return [], latest_snapshot, "Snapshot HPP terbaru belum punya alokasi untuk detail order ini."

    return allocations, latest_snapshot, None


def _allocations_for_daily_order_invoice(invoice):
    if not getattr(invoice, "source_order_id", None) or not getattr(invoice, "mandor_id", None):
        return [], None, f"Invoice order belum punya source order atau PIC {T.sub_client_lower}."

    latest_snapshot = _latest_snapshot_for_order(invoice.source_order_id, invoice.branch_id)

    if not latest_snapshot:
        return [], None, "Order sumber invoice belum punya Snapshot HPP."

    allocations = OrderHppSnapshotAllocation.query.filter_by(
        snapshot_id=latest_snapshot.id,
        mandor_id=invoice.mandor_id,
    ).order_by(
        OrderHppSnapshotAllocation.delivery_location_id.asc(),
        OrderHppSnapshotAllocation.meal_type.asc(),
        OrderHppSnapshotAllocation.id.asc(),
    ).all()

    if not allocations:
        return [], latest_snapshot, f"Snapshot HPP terbaru belum punya alokasi untuk PIC/{T.sub_client_lower} invoice ini."

    return allocations, latest_snapshot, None


def _sum_allocations(allocations):
    revenue = sum(_safe_float(row.revenue_total) for row in allocations)
    food_cost = sum(_safe_float(row.food_cost_allocated_total) for row in allocations)
    packaging_cost = sum(_safe_float(row.packaging_cost_allocated_total) for row in allocations)
    overhead_cost = sum(_safe_float(row.overhead_cost_allocated_total) for row in allocations)
    hpp = sum(_safe_float(row.hpp_allocated_total) for row in allocations)
    gross_profit = revenue - hpp

    return {
        "revenue": revenue,
        "food_cost": food_cost,
        "packaging_cost": packaging_cost,
        "overhead_cost": overhead_cost,
        "hpp": hpp,
        "gross_profit": gross_profit,
        "margin_percentage": _margin_percent(gross_profit, revenue),
    }


def _allocation_snapshot_numbers(allocations):
    numbers = []
    for allocation in allocations:
        snapshot = getattr(allocation, "snapshot", None)
        number = getattr(snapshot, "snapshot_number", None)
        if number and number not in numbers:
            numbers.append(number)
    return numbers


def build_invoice_profit_report(invoice):
    """Build read-only profit report for one invoice.

    Matching rules:
    - PERIOD_INVOICE + ORDER_DETAIL item: match to latest HPP snapshot allocation by daily_order_detail_id.
    - DAILY_ORDER invoice: match to latest HPP snapshot allocations by order + mandor.
    - ORDER_REVISION and WORKER_DEBT are shown as not costed/excluded for now.
    """

    invoice_items = list(getattr(invoice, "items", []) or [])

    item_rows = []
    allocation_rows = []
    warnings = []
    used_allocation_ids = set()

    invoice_total = _safe_float(getattr(invoice, "total_amount", 0))
    costed_revenue_total = 0.0
    excluded_revenue_total = 0.0
    no_hpp_revenue_total = 0.0
    food_cost_total = 0.0
    packaging_cost_total = 0.0
    overhead_cost_total = 0.0
    hpp_total = 0.0

    daily_order_invoice_consumed = False

    for item in invoice_items:
        item_type = str(getattr(item, "item_type", "") or "").upper()
        source_type = str(getattr(item, "source_type", "") or "").upper()
        source_id = getattr(item, "source_id", None)
        item_subtotal = _safe_float(getattr(item, "subtotal", 0))

        row = {
            "item": item,
            "status": "NO_HPP",
            "status_label": "Belum ada HPP",
            "status_class": "status-progress",
            "revenue": item_subtotal,
            "hpp": 0.0,
            "gross_profit": item_subtotal,
            "margin_percentage": 0.0,
            "snapshot_numbers": [],
            "note": "Belum bisa dicocokkan ke alokasi HPP snapshot.",
        }

        allocations = []
        warning = None

        if source_type == "ORDER_DETAIL" and source_id:
            allocations, snapshot, warning = _allocations_for_order_detail(source_id, invoice.branch_id)
        elif (
            str(getattr(invoice, "source_type", "") or "").upper() == "DAILY_ORDER"
            and not daily_order_invoice_consumed
            and item_type in ["CATERING", "REVISION_INCREASE"]
        ):
            allocations, snapshot, warning = _allocations_for_daily_order_invoice(invoice)
            daily_order_invoice_consumed = True
        elif source_type == "WORKER_DEBT" or item_type == "WARUNG_DEBT":
            row.update({
                "status": "EXCLUDED",
                "status_label": "Warung / non-HPP",
                "status_class": "status-draft",
                "note": "Hutang warung pekerja bukan komponen HPP catering.",
            })
            excluded_revenue_total += item_subtotal
            item_rows.append(row)
            continue
        elif source_type == "ORDER_REVISION" or item_type == "REVISION_INCREASE":
            warning = "Revisi tambah belum punya alokasi HPP khusus. Perlu patch alokasi revisi kalau ingin margin revisi presisi."

        if allocations:
            summary = _sum_allocations(allocations)

            row.update({
                "status": "COSTED",
                "status_label": "Terhitung",
                "status_class": "status-locked",
                "hpp": summary["hpp"],
                "gross_profit": item_subtotal - summary["hpp"],
                "margin_percentage": _margin_percent(item_subtotal - summary["hpp"], item_subtotal),
                "snapshot_numbers": _allocation_snapshot_numbers(allocations),
                "note": "HPP dibaca dari alokasi snapshot HPP terbaru untuk sumber invoice.",
            })

            costed_revenue_total += item_subtotal
            food_cost_total += summary["food_cost"]
            packaging_cost_total += summary["packaging_cost"]
            overhead_cost_total += summary["overhead_cost"]
            hpp_total += summary["hpp"]

            for allocation in allocations:
                if allocation.id in used_allocation_ids:
                    continue
                used_allocation_ids.add(allocation.id)
                allocation_rows.append(allocation)
        else:
            no_hpp_revenue_total += item_subtotal
            if warning:
                row["note"] = warning
                warnings.append(warning)

        item_rows.append(row)

    gross_profit_total = costed_revenue_total - hpp_total

    summary = {
        "invoice_total": invoice_total,
        "costed_revenue_total": costed_revenue_total,
        "excluded_revenue_total": excluded_revenue_total,
        "no_hpp_revenue_total": no_hpp_revenue_total,
        "food_cost_total": food_cost_total,
        "packaging_cost_total": packaging_cost_total,
        "overhead_cost_total": overhead_cost_total,
        "hpp_total": hpp_total,
        "gross_profit_total": gross_profit_total,
        "gross_margin_percentage": _margin_percent(gross_profit_total, costed_revenue_total),
        "coverage_percentage": _percent(costed_revenue_total, invoice_total),
        "allocation_count": len(allocation_rows),
        "warning_count": len(set(warnings)),
    }

    if summary["coverage_percentage"] < 100 and invoice_total > 0:
        warnings.append(
            "Belum semua item invoice punya alokasi HPP. Margin resmi hanya dihitung dari revenue yang sudah matched ke HPP allocation."
        )

    return {
        "invoice": invoice,
        "summary": summary,
        "item_rows": item_rows,
        "allocation_rows": allocation_rows,
        "warnings": list(dict.fromkeys(warnings)),
    }


def build_invoice_profit_report_index(branch_id, start_date=None, end_date=None):
    query = Invoice.query.filter_by(branch_id=branch_id)

    if start_date:
        query = query.filter(Invoice.invoice_date >= start_date)

    if end_date:
        query = query.filter(Invoice.invoice_date <= end_date)

    invoices = query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all()

    rows = []
    totals = {
        "invoice_total": 0.0,
        "costed_revenue_total": 0.0,
        "hpp_total": 0.0,
        "gross_profit_total": 0.0,
        "no_hpp_revenue_total": 0.0,
        "excluded_revenue_total": 0.0,
        "invoice_count": len(invoices),
        "costed_invoice_count": 0,
        "low_margin_count": 0,
    }

    for invoice in invoices:
        report = build_invoice_profit_report(invoice)
        summary = report["summary"]

        if _safe_float(summary["costed_revenue_total"]) > 0:
            totals["costed_invoice_count"] += 1

        if _safe_float(summary["gross_margin_percentage"]) < 20 and _safe_float(summary["costed_revenue_total"]) > 0:
            totals["low_margin_count"] += 1

        for key in [
            "invoice_total",
            "costed_revenue_total",
            "hpp_total",
            "gross_profit_total",
            "no_hpp_revenue_total",
            "excluded_revenue_total",
        ]:
            totals[key] += _safe_float(summary[key])

        rows.append({
            "invoice": invoice,
            "summary": summary,
        })

    totals["gross_margin_percentage"] = _margin_percent(
        totals["gross_profit_total"],
        totals["costed_revenue_total"],
    )
    totals["coverage_percentage"] = _percent(
        totals["costed_revenue_total"],
        totals["invoice_total"],
    )

    return {
        "rows": rows,
        "totals": totals,
    }
