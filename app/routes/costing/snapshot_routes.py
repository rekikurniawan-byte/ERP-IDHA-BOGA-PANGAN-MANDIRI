"""Costing order HPP snapshot routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.costing_routes import *  # noqa: F401,F403


@costing_bp.route("/order-hpp-snapshots")
@role_required("ADMIN")
def order_hpp_snapshots():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "ALL").strip().upper()
    margin_status = (request.args.get("margin_status") or "ALL").strip().upper()
    date_from_raw = request.args.get("date_from") or ""
    date_to_raw = request.args.get("date_to") or ""
    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)

    query = OrderHppSnapshot.query.join(DailyOrder).filter(
        OrderHppSnapshot.branch_id == current_user.branch_id
    )

    if q:
        query = query.filter(
            or_(
                OrderHppSnapshot.snapshot_number.ilike(f"%{q}%"),
                DailyOrder.order_number.ilike(f"%{q}%"),
                OrderHppSnapshot.notes.ilike(f"%{q}%"),
            )
        )

    if status != "ALL":
        query = query.filter(OrderHppSnapshot.status == status)

    if date_from:
        query = query.filter(OrderHppSnapshot.snapshot_date >= datetime.combine(date_from, time.min))

    if date_to:
        query = query.filter(OrderHppSnapshot.snapshot_date <= datetime.combine(date_to, time.max))

    snapshots = query.order_by(
        OrderHppSnapshot.snapshot_date.desc(),
        OrderHppSnapshot.id.desc(),
    ).all()

    if margin_status != "ALL":
        snapshots = [
            snapshot for snapshot in snapshots
            if snapshot_margin_status(snapshot) == margin_status
        ]

    total_revenue = sum(to_float(snapshot.revenue_total) for snapshot in snapshots)
    total_hpp = sum(to_float(snapshot.hpp_total) for snapshot in snapshots)
    total_margin = sum(to_float(snapshot.gross_margin_amount) for snapshot in snapshots)
    margin_percentage = (total_margin / total_revenue * 100) if total_revenue > 0 else 0
    low_margin_count = sum(
        1 for snapshot in snapshots
        if snapshot_margin_status(snapshot) in ["LOW", "NEGATIVE"]
    )
    unique_order_count = len({snapshot.daily_order_id for snapshot in snapshots})

    summary = {
        "snapshot_count": len(snapshots),
        "order_count": unique_order_count,
        "total_revenue": total_revenue,
        "total_hpp": total_hpp,
        "total_margin": total_margin,
        "margin_percentage": margin_percentage,
        "low_margin_count": low_margin_count,
    }

    return render_template(
        "costing/order_hpp_snapshots.html",
        snapshots=snapshots,
        summary=summary,
        q=q,
        status=status,
        margin_status=margin_status,
        date_from=date_from_raw,
        date_to=date_to_raw,
        snapshot_margin_status=snapshot_margin_status,
    )
