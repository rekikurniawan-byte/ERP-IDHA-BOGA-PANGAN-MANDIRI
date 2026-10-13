"""Denyut dashboard Owner & Admin (UI desktop internal, keputusan owner 2026-10-13).

Semua angka dihitung dari tabel asli cabang pengguna. Tidak ada angka cadangan
atau tren karangan: kalau data pembanding tidak ada, persentasenya None dan
tampilan menulis "belum ada pembanding". Saran Sistem dan Peringatan hanya muncul
kalau kondisinya benar-benar terjadi.

Hanya baca, tanpa commit.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.utils.clock import now_wib, to_wib, today_wib

INACTIVE_INVOICE = ("CANCELLED", "CANCELED")
SETTLED_INVOICE = ("CANCELLED", "CANCELED", "PAID", "CLOSED")
SPARK_DAYS = 30
# Uang masuk yang bukan hasil usaha: saldo awal, setoran modal owner, koreksi kas.
NON_OPERATING_CASH_IN = ("OPENING_BALANCE", "OWNER_CAPITAL", "OWNER_CASH_INJECTION", "CASH_BANK_ADJUSTMENT")
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
DAYS_LONG = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_LONG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
               "Oktober", "November", "Desember"]


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _label(day: date) -> str:
    return f"{day.day} {MONTHS_SHORT[day.month - 1]}"


def long_date(day: date) -> str:
    return f"{DAYS_LONG[day.weekday()]}, {day.day} {MONTHS_LONG[day.month - 1]} {day.year}"


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _month_window(today: date) -> tuple[date, date, date, date]:
    """Bulan berjalan s/d hari ini dan rentang tanggal yang sama bulan lalu."""
    start = today.replace(day=1)
    prev_end_month = start - timedelta(days=1)
    prev_start = prev_end_month.replace(day=1)
    prev_end = prev_start.replace(day=min(today.day, calendar.monthrange(prev_start.year, prev_start.month)[1]))
    return start, today, prev_start, prev_end


def _delta(current: Decimal, previous: Decimal):
    if previous <= 0:
        return None
    return float(round((current - previous) / previous * 100, 1))


# --- seri harian dari tabel asli ---------------------------------------------------

def _invoice_daily(branch_id: int, start: date, end: date) -> dict[date, Decimal]:
    from app.models.finance import Invoice

    rows = (
        db.session.query(Invoice.invoice_date, func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.branch_id == branch_id, Invoice.invoice_date.between(start, end),
                ~func.upper(func.coalesce(Invoice.status, "")).in_(INACTIVE_INVOICE))
        .group_by(Invoice.invoice_date)
        .all()
    )
    return {day: _d(total) for day, total in rows}


def _cash_in_daily(branch_id: int, start: date, end: date) -> dict[date, Decimal]:
    """Kas & bank masuk dari usaha; pindah buku, saldo awal, modal owner, dan koreksi tidak dihitung."""
    from app.models.finance import CashBankTransaction

    rows = (
        db.session.query(CashBankTransaction.transaction_date, func.coalesce(func.sum(CashBankTransaction.amount), 0))
        .filter(CashBankTransaction.branch_id == branch_id,
                CashBankTransaction.transaction_type == "IN",
                CashBankTransaction.transfer_group_id.is_(None),
                ~func.coalesce(CashBankTransaction.reference_type, "").in_(NON_OPERATING_CASH_IN),
                CashBankTransaction.transaction_date.between(start, end))
        .group_by(CashBankTransaction.transaction_date)
        .all()
    )
    return {day: _d(total) for day, total in rows}


def _portion_daily(branch_id: int, start: date, end: date) -> dict[date, dict]:
    from app.models.operational import DailyOrder, DailyOrderDetail

    rows = (
        db.session.query(
            DailyOrder.order_date,
            func.coalesce(func.sum(DailyOrderDetail.lunch_qty), 0),
            func.coalesce(func.sum(DailyOrderDetail.dinner_qty), 0),
        )
        .join(DailyOrderDetail, DailyOrderDetail.daily_order_id == DailyOrder.id)
        .filter(DailyOrder.branch_id == branch_id, DailyOrder.status != "CANCELLED",
                DailyOrder.order_date.between(start, end))
        .group_by(DailyOrder.order_date)
        .all()
    )
    return {day: {"lunch": int(lunch or 0), "dinner": int(dinner or 0), "total": int(lunch or 0) + int(dinner or 0)}
            for day, lunch, dinner in rows}


def _spark(name: str, daily: dict, days: list[date], color: str, fmt: str, pick=None) -> dict:
    values = []
    for day in days:
        value = daily.get(day, 0)
        if pick:
            value = pick(value) if value else 0
        values.append(float(value or 0))
    return {
        "kind": "spark",
        "area": True,
        "format": fmt,
        "height": 44,
        "categories": [_label(day) for day in days],
        "series": [{"name": name, "data": values, "color": color}],
    }


def _sum(daily: dict, start: date, end: date, pick=None) -> Decimal:
    total = Decimal("0")
    for day, value in daily.items():
        if start <= day <= end:
            total += _d(pick(value) if pick else value)
    return total


# --- piutang -------------------------------------------------------------------------

def receivable_aging(branch_id: int, today: date) -> dict:
    from app.models.finance import Invoice

    rows = (
        db.session.query(Invoice.due_date, Invoice.remaining_amount, Invoice.client_name_snapshot, Invoice.client_id)
        .filter(Invoice.branch_id == branch_id, Invoice.remaining_amount > 0,
                ~func.upper(func.coalesce(Invoice.status, "")).in_(SETTLED_INVOICE))
        .all()
    )
    buckets = [
        {"key": "current", "label": "Belum jatuh tempo", "amount": Decimal("0"), "tone": "ok"},
        {"key": "d14", "label": "1–14 hari", "amount": Decimal("0"), "tone": "warn"},
        {"key": "d30", "label": "15–30 hari", "amount": Decimal("0"), "tone": "late"},
        {"key": "d30p", "label": "> 30 hari", "amount": Decimal("0"), "tone": "bad"},
    ]
    total = Decimal("0")
    overdue_count = 0
    late14_by_client: dict = {}
    for due, remaining, client_name, client_id in rows:
        amount = _d(remaining)
        total += amount
        days = (today - due).days if due else 0
        if days <= 0:
            buckets[0]["amount"] += amount
            continue
        overdue_count += 1
        buckets[1 if days <= 14 else 2 if days <= 30 else 3]["amount"] += amount
        if days > 14:
            key = client_id or client_name or "-"
            entry = late14_by_client.setdefault(key, {"name": client_name or "Tanpa nama", "amount": Decimal("0"), "days": 0})
            entry["amount"] += amount
            entry["days"] = max(entry["days"], days)
    for bucket in buckets:
        bucket["percent"] = float(round(bucket["amount"] / total * 100, 1)) if total else 0.0
        bucket["amount"] = float(bucket["amount"])
    late = sorted(late14_by_client.values(), key=lambda row: row["amount"], reverse=True)
    return {
        "total": float(total),
        "overdue_count": overdue_count,
        "overdue_amount": float(sum((_d(b["amount"]) for b in buckets[1:]), Decimal("0"))),
        "buckets": buckets,
        "late14": [{"name": row["name"], "amount": float(row["amount"]), "days": row["days"]} for row in late],
    }


# --- aktivitas -----------------------------------------------------------------------

ACTIVITY_ICONS = {
    "ORDER": "bi-journal-check", "OPERATIONAL": "bi-journal-text", "PRODUCTION": "bi-egg-fried",
    "PAYMENT": "bi-cash-coin", "FINANCE": "bi-receipt", "ACCOUNTING": "bi-journal-bookmark",
    "DELIVERY": "bi-truck", "INVENTORY": "bi-box-seam", "LOGISTICS": "bi-box-seam", "CANTEEN": "bi-shop",
    "HR": "bi-people", "WORKFORCE": "bi-people", "PAYROLL": "bi-wallet2", "AUTH": "bi-person-check",
    "PORTAL": "bi-globe2", "SETTINGS": "bi-gear", "SYSTEM": "bi-gear",
}
_NOISE = re.compile(r"\s*\|\s*Atomic\s+(PASS|FAIL)\.?\s*$|\s+secara\s+atomic\.?", re.IGNORECASE)


def _clean_activity(text: str) -> str:
    text = _NOISE.sub("", (text or "").strip()).strip()
    text = text.rstrip(".").strip()
    return text[:1].upper() + text[1:] if text else "Aktivitas sistem"


def _ago(moment: datetime, now: datetime) -> str:
    seconds = max((now - moment).total_seconds(), 0)
    if seconds < 60:
        return "baru saja"
    if seconds < 3600:
        return f"{int(seconds // 60)} mnt lalu"
    if seconds < 86400:
        return f"{int(seconds // 3600)} jam lalu"
    if seconds < 172800:
        return "kemarin " + moment.strftime("%H.%M")
    return f"{moment.day} {MONTHS_SHORT[moment.month - 1]} {moment.strftime('%H.%M')}"


def recent_activity(branch_id: int, limit: int = 8) -> list[dict]:
    from app.models.system import AuditLog

    logs = (
        AuditLog.query.filter(AuditLog.branch_id == branch_id)
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    now = now_wib()
    rows = []
    for log in logs:
        moment = to_wib(log.created_at) if log.created_at else None
        rows.append({
            "icon": ACTIVITY_ICONS.get(str(log.module or "SYSTEM").upper(), "bi-activity"),
            "text": _clean_activity(log.description or f"{log.action or 'Aksi'} {log.table_name or ''}"),
            "user": log.username_snapshot or "Sistem",
            "when": _ago(moment, now) if moment else "",
            "time": moment.strftime("%H.%M") if moment else "",
            "url_id": log.id,
        })
    return rows


# --- peringatan & saran --------------------------------------------------------------

def _pending_payment_proofs(branch_id: int) -> tuple[int, datetime | None]:
    from app.models.system import DigitalAttachment

    count, oldest = (
        db.session.query(func.count(DigitalAttachment.id), func.min(DigitalAttachment.created_at))
        .filter(DigitalAttachment.branch_id == branch_id, DigitalAttachment.module == "PORTAL_PAYMENT",
                DigitalAttachment.is_deleted.is_(False), DigitalAttachment.attachment_type == "PAYMENT_PROOF_PENDING")
        .one()
    )
    return int(count or 0), (to_wib(oldest) if oldest else None)


def _unlocked_orders(branch_id: int, day: date) -> int:
    from app.models.operational import DailyOrder

    return (
        DailyOrder.query.filter(DailyOrder.branch_id == branch_id, DailyOrder.order_date == day,
                                DailyOrder.status != "CANCELLED", DailyOrder.is_locked.is_(False))
        .count()
    )


def _expiring_contracts(branch_id: int, today: date, days: int = 30) -> list:
    from app.models.contract import CustomerContract

    return (
        CustomerContract.query.filter(CustomerContract.branch_id == branch_id,
                                      func.upper(CustomerContract.status) == "ACTIVE",
                                      CustomerContract.end_date.isnot(None),
                                      CustomerContract.end_date.between(today, today + timedelta(days=days)))
        .order_by(CustomerContract.end_date.asc())
        .all()
    )


def _alert(tone, icon, title, detail, endpoint, count=None, args=None):
    return {"tone": tone, "icon": icon, "title": title, "detail": detail, "endpoint": endpoint,
            "args": args or {}, "count": count}


def _alerts(branch_id: int, today: date, command: dict, aging: dict) -> list[dict]:
    alerts = []
    proofs, oldest = _pending_payment_proofs(branch_id)
    if proofs:
        wait = ""
        if oldest:
            hours = int((now_wib() - oldest).total_seconds() // 3600)
            wait = f" Terlama menunggu {hours} jam." if hours >= 1 else " Baru masuk."
        alerts.append(_alert("bad", "bi-patch-check", "Bukti bayar menunggu", f"{proofs} bukti transfer belum dicek.{wait}",
                             "finance.payment_inbox", proofs))
    if aging["overdue_count"]:
        alerts.append(_alert("bad", "bi-cash-coin", "Invoice lewat jatuh tempo",
                             f"{aging['overdue_count']} invoice, sisa Rp {aging['overdue_amount']:,.0f}.".replace(",", "."),
                             "finance.receivables", aging["overdue_count"]))
    unlocked = _unlocked_orders(branch_id, today)
    if unlocked:
        alerts.append(_alert("warn", "bi-lock", "Pesanan hari ini belum dikunci",
                             f"{unlocked} pesanan belum dikunci; dapur belum punya angka final.", "operational.orders", unlocked))
    contracts = _expiring_contracts(branch_id, today)
    if contracts:
        first = contracts[0]
        left = (first.end_date - today).days
        alerts.append(_alert("warn", "bi-file-earmark-text", "Kontrak segera berakhir",
                             f"{len(contracts)} kontrak berakhir ≤ 30 hari (terdekat {left} hari lagi).",
                             "customer_success.contracts", len(contracts)))
    seen = {"finance.receivables"}
    for reminder in command.get("reminders") or []:
        if reminder.get("endpoint") in seen:
            continue
        tone = "bad" if reminder.get("severity") == "danger" else "warn"
        alerts.append(_alert(tone, reminder.get("icon") or "bi-exclamation-circle", reminder["title"],
                             reminder.get("detail") or "", reminder["endpoint"]))
    order = {"bad": 0, "warn": 1}
    return sorted(alerts, key=lambda row: order.get(row["tone"], 2))


def _suggestions(branch_id: int, today: date, aging: dict, omzet_mtd: Decimal, kas_mtd: Decimal,
                 portions: dict) -> list[dict]:
    rows = []
    if aging["late14"]:
        top = aging["late14"][0]
        total = sum(row["amount"] for row in aging["late14"])
        rows.append({
            "tone": "bad", "icon": "bi-hourglass-split", "tag": "Penagihan",
            "title": f"{len(aging['late14'])} pelanggan menunggak > 14 hari",
            "detail": (f"Total Rp {total:,.0f}. Terbesar {top['name']} Rp {top['amount']:,.0f} "
                       f"({top['days']} hari).").replace(",", "."),
            "action": "Buka Kontrol Kredit", "endpoint": "credit.overview",
        })
    tomorrow = today + timedelta(days=1)
    tomorrow_qty = portions.get(tomorrow, {}).get("total", 0)
    history = [portions[day]["total"] for day in _days(today - timedelta(days=7), today) if portions.get(day, {}).get("total")]
    if tomorrow_qty and history:
        average = sum(history) / len(history)
        change = (tomorrow_qty - average) / average * 100 if average else 0
        if abs(change) >= 20:
            rows.append({
                "tone": "warn", "icon": "bi-basket", "tag": "Dapur & stok",
                "title": f"Porsi besok {'naik' if change > 0 else 'turun'} {abs(change):.0f}%",
                "detail": f"{tomorrow_qty:,} porsi vs rata-rata {average:,.0f} porsi/hari (7 hari terakhir).".replace(",", "."),
                "action": "Cek kebutuhan bahan", "endpoint": "logistics.material_forecast",
            })
    if omzet_mtd > 0:
        ratio = float(kas_mtd / omzet_mtd * 100)
        if ratio < 60:
            rows.append({
                "tone": "warn", "icon": "bi-droplet-half", "tag": "Arus kas",
                "title": f"Kas masuk baru {ratio:.0f}% dari omzet bulan ini",
                "detail": (f"Omzet Rp {omzet_mtd:,.0f}, kas masuk Rp {kas_mtd:,.0f}. "
                           "Sisanya masih jadi piutang.").replace(",", "."),
                "action": "Lihat piutang", "endpoint": "finance.receivables",
            })
    return rows


# --- perakitan -----------------------------------------------------------------------

def _kpi(key, label, icon, tone, value, fmt, endpoint, delta=None, compare="", caption="", spark=None,
         bar=None, args=None):
    return {"key": key, "label": label, "icon": icon, "tone": tone, "value": float(value), "format": fmt,
            "endpoint": endpoint, "args": args or {}, "delta": delta, "compare": compare, "caption": caption,
            "spark": spark, "bar": bar}


def build_owner_pulse(branch_id: int, command: dict) -> dict:
    today = today_wib()
    start, end, prev_start, prev_end = _month_window(today)
    spark_days = _days(today - timedelta(days=SPARK_DAYS - 1), today)
    window_start = min(prev_start, spark_days[0])
    omzet = _invoice_daily(branch_id, window_start, today)
    kas = _cash_in_daily(branch_id, window_start, today)
    porsi = _portion_daily(branch_id, window_start, today + timedelta(days=1))
    aging = receivable_aging(branch_id, today)
    total_of = lambda row: row["total"]  # noqa: E731

    omzet_mtd, omzet_prev = _sum(omzet, start, end), _sum(omzet, prev_start, prev_end)
    kas_mtd, kas_prev = _sum(kas, start, end), _sum(kas, prev_start, prev_end)
    porsi_mtd, porsi_prev = _sum(porsi, start, end, total_of), _sum(porsi, prev_start, prev_end, total_of)
    compare = f"vs {prev_start.day}–{prev_end.day} {MONTHS_SHORT[prev_start.month - 1]}"

    kpis = [
        _kpi("omzet", "Omzet bulan ini", "bi-receipt", "blue", omzet_mtd, "rupiah", "dashboard.revenue_explorer",
             _delta(omzet_mtd, omzet_prev), compare, "Invoice terbit, tanpa yang dibatalkan",
             _spark("Omzet", omzet, spark_days, "brand-600", "rupiah")),
        _kpi("kas", "Kas masuk dari usaha", "bi-cash-stack", "green", kas_mtd, "rupiah", "finance.cash_bank_ledger",
             _delta(kas_mtd, kas_prev), compare, "Tanpa saldo awal, modal owner, pindah buku, koreksi",
             _spark("Kas masuk", kas, spark_days, "chart-green", "rupiah")),
        _kpi("porsi", "Porsi dipesan", "bi-box-seam", "violet", porsi_mtd, "number", "operational.orders",
             _delta(porsi_mtd, porsi_prev), compare, "Siang + sore, pesanan tidak batal",
             _spark("Porsi", porsi, spark_days, "chart-violet", "number", total_of)),
        _kpi("piutang", "Piutang berjalan", "bi-hourglass-split", "amber", aging["total"], "rupiah", "finance.receivables",
             caption=(f"{aging['overdue_count']} invoice lewat jatuh tempo" if aging["overdue_count"]
                      else "Tidak ada yang lewat jatuh tempo"),
             bar=aging["buckets"]),
    ]
    trend = {
        "kind": "area", "format": "rupiah", "height": 300, "legend": False,
        "categories": [_label(day) for day in spark_days],
        "series": [
            {"name": "Omzet (invoice)", "data": [float(omzet.get(day, 0)) for day in spark_days], "color": "brand-600"},
            {"name": "Kas masuk", "data": [float(kas.get(day, 0)) for day in spark_days], "color": "chart-green"},
        ],
    }
    return {
        "today_label": long_date(today),
        "kpis": kpis,
        "trend": trend,
        "trend_total": {"omzet": float(_sum(omzet, spark_days[0], today)), "kas": float(_sum(kas, spark_days[0], today))},
        "aging": aging,
        "alerts": _alerts(branch_id, today, command, aging),
        "suggestions": _suggestions(branch_id, today, aging, omzet_mtd, kas_mtd, porsi),
        "activity": recent_activity(branch_id),
    }


def build_admin_pulse(branch_id: int, command: dict) -> dict:
    from app.models.delivery import Delivery

    today = today_wib()
    days = _days(today - timedelta(days=13), today)
    porsi = _portion_daily(branch_id, days[0], today + timedelta(days=1))
    aging = receivable_aging(branch_id, today)
    proofs, oldest = _pending_payment_proofs(branch_id)
    today_row = porsi.get(today, {"lunch": 0, "dinner": 0, "total": 0})
    yesterday_total = porsi.get(today - timedelta(days=1), {}).get("total", 0)

    deliveries = (
        db.session.query(Delivery.status, func.count(Delivery.id))
        .filter(Delivery.branch_id == branch_id, Delivery.delivery_date == today, Delivery.status != "CANCELLED")
        .group_by(Delivery.status)
        .all()
    )
    delivery_total = sum(int(count) for _, count in deliveries)
    delivered = sum(int(count) for status, count in deliveries if status == "DELIVERED")
    wait_caption = "Tidak ada antrean"
    if proofs and oldest:
        hours = int((now_wib() - oldest).total_seconds() // 3600)
        wait_caption = f"Terlama menunggu {hours} jam" if hours >= 1 else "Baru masuk"

    kpis = [
        _kpi("porsi", "Porsi hari ini", "bi-box-seam", "blue", today_row["total"], "number", "operational.orders",
             _delta(_d(today_row["total"]), _d(yesterday_total)), "vs kemarin",
             f"Siang {today_row['lunch']:,} · Sore {today_row['dinner']:,}".replace(",", "."),
             _spark("Porsi", porsi, days, "brand-600", "number", lambda row: row["total"])),
        _kpi("bukti", "Bukti bayar menunggu", "bi-patch-check", "amber" if proofs else "green", proofs, "number",
             "finance.payment_inbox", caption=wait_caption),
        _kpi("jatuh_tempo", "Invoice lewat jatuh tempo", "bi-receipt-cutoff", "red" if aging["overdue_count"] else "green",
             aging["overdue_count"], "number", "finance.receivables",
             caption=f"Sisa Rp {aging['overdue_amount']:,.0f}".replace(",", ".") if aging["overdue_count"] else "Semua tepat waktu"),
        _kpi("antar", "Pengiriman selesai", "bi-truck", "violet", delivered, "number", "delivery.today",
             caption=f"dari {delivery_total} pengiriman hari ini" if delivery_total else "Belum ada pengiriman hari ini",
             bar=[{"tone": "ok", "percent": round(delivered / delivery_total * 100, 1), "label": "Selesai", "amount": delivered},
                  {"tone": "muted", "percent": round(100 - delivered / delivery_total * 100, 1), "label": "Berjalan",
                   "amount": delivery_total - delivered}] if delivery_total else None),
    ]
    return {
        "today_label": long_date(today),
        "kpis": kpis,
        "aging": aging,
        "alerts": _alerts(branch_id, today, command, aging),
        "suggestions": _suggestions(branch_id, today, aging, Decimal("0"), Decimal("0"), porsi),
        "activity": recent_activity(branch_id),
    }
