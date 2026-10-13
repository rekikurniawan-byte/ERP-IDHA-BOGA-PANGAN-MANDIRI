"""Halaman 360° Pelanggan (UI desktop internal, keputusan owner 2026-10-13).

Satu layar untuk satu pelanggan: profil, kredit, kontrak, tagihan, pembayaran,
pesanan, sub client, komplain, dan hutang warung pekerjanya. Semua data dibatasi
cabang pengguna. Hanya baca, tanpa commit.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_

from app.extensions import db
from app.services.dashboard_pulse_service import MONTHS_SHORT, _ago
from app.utils.clock import now_wib, to_wib, today_wib

INACTIVE_INVOICE = ("CANCELLED", "CANCELED")
OPEN_COMPLAINTS = ("OPEN", "IN_PROGRESS", "WAITING_CUSTOMER")
PATH_LABELS = {"KONTRAK": "Kontrak (tagihan berkala)", "UMUM": "Umum (bayar di muka)"}


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _invoice_scope(branch_id: int, client_id: int, mandor_ids: list[int]):
    from app.models.finance import Invoice

    owner = Invoice.client_id == client_id
    if mandor_ids:
        owner = or_(owner, Invoice.mandor_id.in_(mandor_ids))
    return Invoice.query.filter(Invoice.branch_id == branch_id, owner,
                                ~func.upper(func.coalesce(Invoice.status, "")).in_(INACTIVE_INVOICE))


def _aging(invoices, today: date) -> dict:
    buckets = [
        {"label": "Belum jatuh tempo", "tone": "ok", "amount": Decimal("0")},
        {"label": "1–14 hari", "tone": "warn", "amount": Decimal("0")},
        {"label": "15–30 hari", "tone": "late", "amount": Decimal("0")},
        {"label": "> 30 hari", "tone": "bad", "amount": Decimal("0")},
    ]
    total = Decimal("0")
    oldest = 0
    overdue = 0
    for invoice in invoices:
        remaining = _d(invoice.remaining_amount)
        if remaining <= 0 or str(invoice.status or "").upper() in ("PAID", "CLOSED"):
            continue
        total += remaining
        days = (today - invoice.due_date).days if invoice.due_date else 0
        if days <= 0:
            buckets[0]["amount"] += remaining
            continue
        overdue += 1
        oldest = max(oldest, days)
        buckets[1 if days <= 14 else 2 if days <= 30 else 3]["amount"] += remaining
    for bucket in buckets:
        bucket["percent"] = float(round(bucket["amount"] / total * 100, 1)) if total else 0.0
        bucket["amount"] = float(bucket["amount"])
    return {"total": float(total), "oldest_days": oldest, "overdue_count": overdue, "buckets": buckets}


def _credit(branch_id: int, client_id: int) -> dict | None:
    from app.services.credit_control_service import STATUS_LABELS, evaluate_credit

    decision = evaluate_credit(branch_id, client_id=client_id)
    return {
        "status": decision.status,
        "label": STATUS_LABELS.get(decision.status, decision.status),
        "enforced": decision.enforced,
        "limit": float(decision.credit_limit or 0),
        "exposure": float(decision.exposure or 0),
        "available": float(decision.available or 0),
        "reason": decision.reason or decision.message or "",
    }


def build_client_360(client_id: int, branch_id: int) -> dict | None:
    from app.models.canteen import DebtPayment, WorkerDebt
    from app.models.complaint import CustomerComplaint
    from app.models.contract import CustomerContract
    from app.models.finance import Invoice, Payment
    from app.models.master import Client, ClientPic, DeliveryLocation, Mandor, Worker
    from app.models.operational import DailyOrder, DailyOrderDetail
    from app.models.system import AuditLog
    from app.services.branch_module_service import WORKER_DEBT, module_enabled

    client = Client.query.get(client_id)
    if not client:
        return None
    today = today_wib()

    mandors = (Mandor.query.filter(Mandor.client_id == client.id, Mandor.branch_id == branch_id)
               .order_by(Mandor.name.asc()).all())
    mandor_ids = [m.id for m in mandors]
    pics = ClientPic.query.filter_by(client_id=client.id, is_active=True).order_by(ClientPic.id.asc()).all()

    invoices = _invoice_scope(branch_id, client.id, mandor_ids).order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all()
    aging = _aging(invoices, today)
    invoice_ids = [inv.id for inv in invoices]

    payments = []
    if invoice_ids:
        payments = (Payment.query.filter(Payment.branch_id == branch_id, Payment.invoice_id.in_(invoice_ids))
                    .order_by(Payment.payment_date.desc(), Payment.id.desc()).limit(6).all())

    # Pesanan: per detail milik sub client pelanggan ini.
    order_rows = []
    porsi_30 = 0
    porsi_by_mandor: dict[int, int] = {}
    if mandor_ids:
        since = today - timedelta(days=29)
        detail_rows = (
            db.session.query(DailyOrder.id, DailyOrder.order_number, DailyOrder.order_date, DailyOrder.status,
                             DailyOrder.is_locked, DailyOrderDetail.mandor_id,
                             func.coalesce(func.sum(DailyOrderDetail.total_qty), 0))
            .join(DailyOrderDetail, DailyOrderDetail.daily_order_id == DailyOrder.id)
            .filter(DailyOrder.branch_id == branch_id, DailyOrder.status != "CANCELLED",
                    DailyOrderDetail.mandor_id.in_(mandor_ids))
            .group_by(DailyOrder.id, DailyOrder.order_number, DailyOrder.order_date, DailyOrder.status,
                      DailyOrder.is_locked, DailyOrderDetail.mandor_id)
            .order_by(DailyOrder.order_date.desc())
            .limit(400)
            .all()
        )
        merged: dict[int, dict] = {}
        for order_id, number, order_date, status, locked, mandor_id, qty in detail_rows:
            row = merged.setdefault(order_id, {"id": order_id, "number": number, "date": order_date,
                                               "status": status, "locked": locked, "qty": 0})
            row["qty"] += int(qty or 0)
            if order_date >= since:
                porsi_30 += int(qty or 0)
                porsi_by_mandor[mandor_id] = porsi_by_mandor.get(mandor_id, 0) + int(qty or 0)
        order_rows = sorted(merged.values(), key=lambda row: (row["date"], row["id"]), reverse=True)[:6]

    # Omzet & pembayaran 6 bulan untuk grafik.
    month_keys = []
    cursor = today.replace(day=1)
    for _ in range(6):
        month_keys.append((cursor.year, cursor.month))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    month_keys.reverse()
    billed = {key: Decimal("0") for key in month_keys}
    for inv in invoices:
        key = (inv.invoice_date.year, inv.invoice_date.month) if inv.invoice_date else None
        if key in billed:
            billed[key] += _d(inv.total_amount)
    paid = {key: Decimal("0") for key in month_keys}
    if invoice_ids:
        start = date(month_keys[0][0], month_keys[0][1], 1)
        for pay_date, amount in (db.session.query(Payment.payment_date, Payment.amount)
                                 .filter(Payment.branch_id == branch_id, Payment.invoice_id.in_(invoice_ids),
                                         Payment.payment_date >= start).all()):
            key = (pay_date.year, pay_date.month)
            if key in paid:
                paid[key] += _d(amount)
    chart = {
        "kind": "bar", "format": "rupiah", "height": 240,
        "categories": [f"{MONTHS_SHORT[m - 1]} {str(y)[2:]}" for y, m in month_keys],
        "series": [
            {"name": "Ditagih", "data": [float(billed[k]) for k in month_keys], "color": "brand-600"},
            {"name": "Dibayar", "data": [float(paid[k]) for k in month_keys], "color": "chart-green"},
        ],
    }
    omzet_12 = sum((_d(inv.total_amount) for inv in invoices
                    if inv.invoice_date and inv.invoice_date >= today - timedelta(days=364)), Decimal("0"))

    contract = (CustomerContract.query.filter(CustomerContract.branch_id == branch_id,
                                              CustomerContract.client_id == client.id)
                .order_by((func.upper(CustomerContract.status) == "ACTIVE").desc(), CustomerContract.end_date.desc().nullslast())
                .first())
    contract_info = None
    if contract:
        days_left = (contract.end_date - today).days if contract.end_date else None
        contract_info = {"id": contract.id, "number": contract.contract_number, "title": contract.title,
                         "status": contract.status, "start": contract.start_date, "end": contract.end_date,
                         "days_left": days_left, "payment_terms": contract.payment_terms, "due_days": contract.due_days,
                         "credit_limit": float(contract.credit_limit or 0)}

    complaints = (CustomerComplaint.query.filter(CustomerComplaint.branch_id == branch_id,
                                                 or_(CustomerComplaint.client_id == client.id,
                                                     CustomerComplaint.mandor_id.in_(mandor_ids or [0])))
                  .order_by(CustomerComplaint.submitted_at.desc()).limit(5).all())
    open_complaints = [c for c in complaints if str(c.status or "").upper() in OPEN_COMPLAINTS]

    remaining_by_mandor: dict[int, Decimal] = {}
    for inv in invoices:
        if inv.mandor_id and _d(inv.remaining_amount) > 0:
            remaining_by_mandor[inv.mandor_id] = remaining_by_mandor.get(inv.mandor_id, Decimal("0")) + _d(inv.remaining_amount)
    location_counts = dict(
        db.session.query(DeliveryLocation.mandor_id, func.count(DeliveryLocation.id))
        .filter(DeliveryLocation.mandor_id.in_(mandor_ids or [0]), DeliveryLocation.is_active.is_(True))
        .group_by(DeliveryLocation.mandor_id).all()
    )
    worker_debt_on = module_enabled(WORKER_DEBT, branch_id)
    debt_by_mandor: dict[int, Decimal] = {}
    if worker_debt_on and mandor_ids:
        paid_sub = (db.session.query(DebtPayment.worker_debt_id, func.sum(DebtPayment.amount).label("paid"))
                    .group_by(DebtPayment.worker_debt_id).subquery())
        for mandor_id, debt, paid_amount in (
            db.session.query(Worker.mandor_id, WorkerDebt.debt_amount, paid_sub.c.paid)
            .join(Worker, Worker.id == WorkerDebt.worker_id)
            .outerjoin(paid_sub, paid_sub.c.worker_debt_id == WorkerDebt.id)
            .filter(WorkerDebt.branch_id == branch_id, WorkerDebt.status != "PAID", Worker.mandor_id.in_(mandor_ids))
            .all()
        ):
            left = _d(debt) - _d(paid_amount)
            if left > 0:
                debt_by_mandor[mandor_id] = debt_by_mandor.get(mandor_id, Decimal("0")) + left
    sub_clients = [{
        "id": m.id, "name": m.name, "phone": m.phone, "active": m.is_active,
        "locations": int(location_counts.get(m.id, 0)), "porsi_30": porsi_by_mandor.get(m.id, 0),
        "receivable": float(remaining_by_mandor.get(m.id, 0)), "worker_debt": float(debt_by_mandor.get(m.id, 0)),
    } for m in mandors]

    credit = _credit(branch_id, client.id)

    timeline = []
    for inv in invoices[:6]:
        timeline.append({"date": inv.invoice_date, "icon": "bi-receipt", "tone": "blue",
                         "title": f"Invoice {inv.invoice_number}", "amount": float(_d(inv.total_amount)),
                         "detail": inv.status, "endpoint": "finance.invoice_detail", "args": {"invoice_id": inv.id}})
    for pay in payments:
        timeline.append({"date": pay.payment_date, "icon": "bi-cash-coin", "tone": "green",
                         "title": f"Pembayaran {pay.payment_number}", "amount": float(_d(pay.amount)),
                         "detail": pay.payment_method, "endpoint": "finance.invoice_detail", "args": {"invoice_id": pay.invoice_id}})
    for comp in complaints:
        timeline.append({"date": to_wib(comp.submitted_at).date() if comp.submitted_at else today, "icon": "bi-chat-left-dots",
                         "tone": "red", "title": f"Komplain {comp.complaint_number}", "amount": None,
                         "detail": comp.title, "endpoint": "customer_success.complaints", "args": {}})
    if contract_info:
        timeline.append({"date": contract_info["start"], "icon": "bi-file-earmark-text", "tone": "violet",
                         "title": f"Kontrak {contract_info['number']} mulai", "amount": None, "detail": contract.status,
                         "endpoint": "customer_success.contract_detail", "args": {"contract_id": contract.id}})
    timeline = sorted([row for row in timeline if row["date"]], key=lambda row: row["date"], reverse=True)[:10]

    alerts = []
    if credit and credit["status"] != "ACTIVE":
        alerts.append({"tone": "bad" if credit["status"] in ("HOLD", "BLOCKED", "WRITE_OFF") else "warn",
                       "icon": "bi-shield-exclamation", "title": f"Kredit: {credit['label']}",
                       "detail": credit["reason"] or "Lihat rincian kredit.", "endpoint": "credit.overview", "args": {}})
    if aging["overdue_count"]:
        alerts.append({"tone": "bad" if aging["oldest_days"] > 14 else "warn", "icon": "bi-hourglass-split",
                       "title": f"{aging['overdue_count']} invoice lewat jatuh tempo",
                       "detail": f"Tertua {aging['oldest_days']} hari.", "endpoint": "finance.receivables", "args": {}})
    if contract_info and contract_info["days_left"] is not None and contract_info["days_left"] <= 30 \
            and str(contract_info["status"]).upper() == "ACTIVE":
        left = contract_info["days_left"]
        alerts.append({"tone": "warn" if left >= 0 else "bad", "icon": "bi-file-earmark-text",
                       "title": "Kontrak segera berakhir" if left >= 0 else "Kontrak sudah lewat masa berlaku",
                       "detail": f"Berakhir {contract_info['end'].strftime('%d/%m/%Y')}.",
                       "endpoint": "customer_success.contract_detail", "args": {"contract_id": contract_info["id"]}})
    if client.customer_path == "KONTRAK" and not contract_info:
        alerts.append({"tone": "warn", "icon": "bi-file-earmark-plus", "title": "Belum ada kontrak",
                       "detail": "Pelanggan jalur kontrak tanpa dokumen kontrak di cabang ini.",
                       "endpoint": "customer_success.contracts", "args": {}})
    if open_complaints:
        alerts.append({"tone": "warn", "icon": "bi-chat-left-dots", "title": f"{len(open_complaints)} komplain terbuka",
                       "detail": open_complaints[0].title, "endpoint": "customer_success.complaints", "args": {}})

    now = now_wib()
    logs = (AuditLog.query.filter(AuditLog.branch_id == branch_id, AuditLog.table_name == "clients",
                                  AuditLog.record_id == client.id)
            .order_by(AuditLog.id.desc()).limit(8).all())
    activity = [{"text": (log.description or log.action or "Perubahan data").strip(), "user": log.username_snapshot or "Sistem",
                 "when": _ago(to_wib(log.created_at), now) if log.created_at else ""} for log in logs]

    last_payment = payments[0] if payments else None
    return {
        "client": client,
        "path_label": PATH_LABELS.get(client.customer_path, client.customer_path),
        "pic": pics[0] if pics else None,
        "pics": pics,
        "credit": credit,
        "aging": aging,
        "contract": contract_info,
        "stats": {
            "omzet_12": float(omzet_12),
            "receivable": aging["total"],
            "porsi_30": porsi_30,
            "last_payment": {"date": last_payment.payment_date, "amount": float(_d(last_payment.amount))} if last_payment else None,
        },
        "chart": chart,
        "invoices": invoices[:6],
        "payments": payments,
        "orders": order_rows,
        "sub_clients": sub_clients,
        "worker_debt_on": worker_debt_on,
        "timeline": timeline,
        "alerts": alerts,
        "activity": activity,
    }
