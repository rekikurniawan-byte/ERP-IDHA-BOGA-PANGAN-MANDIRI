"""Service baca-saja untuk garis waktu sesi operasional hari ini (Task B).

Menghasilkan timeline dua baris (Siang dan Sore) dengan sumbu 05.00-20.00
dan 4 titik kritis: Kunci, Masak, Berangkat, Tiba.
"""
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from app.models.delivery import Delivery
from app.models.operational import DailyOrder
from app.models.production import Production
from app.services.contract_rules_service import lock_time_for
from app.utils.clock import now_wib, to_wib, today_wib

AXIS_START_HOUR = 5
AXIS_END_HOUR = 20
TOTAL_AXIS_MINUTES = (AXIS_END_HOUR - AXIS_START_HOUR) * 60  # 900 menit


def _calc_pct(t: Optional[Any]) -> Optional[float]:
    """Hitung persentase posisi horizontal pada rentang 05.00 - 20.00."""
    if not t:
        return None
    if isinstance(t, datetime):
        hour = t.hour
        minute = t.minute
    elif isinstance(t, time):
        hour = t.hour
        minute = t.minute
    else:
        return None

    minutes_from_start = (hour - AXIS_START_HOUR) * 60 + minute
    pct = (minutes_from_start / TOTAL_AXIS_MINUTES) * 100.0
    return max(0.0, min(100.0, round(pct, 1)))


def _format_time(t: Optional[Any]) -> str:
    if not t:
        return "-"
    if isinstance(t, datetime):
        return t.strftime("%H.%M")
    if isinstance(t, time):
        return t.strftime("%H.%M")
    return str(t)


def build_session_timeline(branch_id: int, day: Optional[date] = None) -> Dict[str, Any]:
    """Buat data garis waktu sesi hari ini untuk Siang dan Sore."""
    if not day:
        day = today_wib()

    curr_now = now_wib()
    is_today = (day == today_wib())
    now_pct = _calc_pct(curr_now) if is_today else None

    # 1. Orders
    orders = DailyOrder.query.filter_by(branch_id=branch_id, order_date=day).all()

    # 2. Productions
    productions = Production.query.filter_by(branch_id=branch_id, production_date=day).all()
    prod_by_type = {p.production_type: p for p in productions}

    # 3. Deliveries
    deliveries = Delivery.query.filter(
        Delivery.branch_id == branch_id,
        Delivery.delivery_date == day,
        Delivery.status != "CANCELLED",
    ).all()

    sessions_data = []

    for meal_type, session_name, icon in (("LUNCH", "Siang", "bi-sun"), ("DINNER", "Sore", "bi-moon")):
        # --- TITIK 1: KUNCI ---
        # Kumpulkan client yang memiliki porsi pada sesi ini
        clients_with_session = {}
        for order in orders:
            for detail in order.details:
                qty = detail.lunch_qty if meal_type == "LUNCH" else detail.dinner_qty
                if (qty or 0) > 0 and detail.mandor and detail.mandor.client:
                    client = detail.mandor.client
                    clients_with_session[client.id] = client

        earliest_lock_time: Optional[time] = None
        earliest_client_name: Optional[str] = None

        for c_id, client in clients_with_session.items():
            l_time = lock_time_for(client.id, meal_type, on_date=day, branch_id=branch_id)
            if l_time:
                if earliest_lock_time is None or l_time < earliest_lock_time:
                    earliest_lock_time = l_time
                    earliest_client_name = client.name

        order_for_session = [
            o for o in orders if any((d.lunch_qty if meal_type == "LUNCH" else d.dinner_qty) > 0 for d in o.details)
        ]
        is_locked = bool(order_for_session and all(o.is_locked for o in order_for_session))
        locked_at = None
        for o in order_for_session:
            if o.locked_at:
                if locked_at is None or o.locked_at < locked_at:
                    locked_at = o.locked_at

        lock_pct = _calc_pct(earliest_lock_time) if earliest_lock_time else 25.0
        lock_color = "gray"
        lock_tooltip = ""
        lock_status_text = ""

        if not earliest_lock_time:
            lock_color = "gray"
            lock_status_text = "Belum dijadwalkan"
            lock_tooltip = f"Kunci {session_name}: belum ada jadwal kontrak"
        elif is_locked:
            lock_color = "green"
            lock_status_text = "Terkunci"
            lock_tooltip = (
                f"Kunci {session_name}: {_format_time(earliest_lock_time)}"
                f"{f' ({earliest_client_name})' if earliest_client_name else ''} · Selesai terkunci"
            )
        else:
            if is_today and curr_now.time() > earliest_lock_time:
                lock_color = "red"
                lock_status_text = "Lewat jam kunci"
                lock_tooltip = (
                    f"Kunci {session_name}: {_format_time(earliest_lock_time)}"
                    f"{f' ({earliest_client_name})' if earliest_client_name else ''} · Lewat jam kunci (belum lock)"
                )
            else:
                lock_color = "blue"
                lock_status_text = "Menunggu lock"
                lock_tooltip = (
                    f"Kunci {session_name}: {_format_time(earliest_lock_time)}"
                    f"{f' ({earliest_client_name})' if earliest_client_name else ''}"
                )

        point_lock = {
            "key": "lock",
            "label": "Kunci",
            "time_display": _format_time(earliest_lock_time) if earliest_lock_time else None,
            "pct": lock_pct,
            "color": lock_color,
            "tooltip": lock_tooltip,
            "status_text": lock_status_text,
        }

        # --- TITIK 2: MASAK (PRODUKSI) ---
        prod = prod_by_type.get(meal_type)
        prod_target = prod.target_ready_time if prod else None
        prod_actual = to_wib(prod.actual_completed_time) if prod else None  # disimpan UTC
        prod_tol = (prod.late_tolerance_minutes or 0) if prod else 0
        prod_status = prod.status if prod else None

        prod_pct = _calc_pct(prod_target or prod_actual) if (prod_target or prod_actual) else 45.0
        prod_color = "gray"
        prod_status_text = ""
        prod_tooltip = ""

        if not prod or (not prod_target and not prod_actual and prod_status == "DRAFT"):
            prod_color = "gray"
            prod_status_text = "Belum dijadwalkan"
            prod_tooltip = f"Dapur {session_name}: belum ada target produksi"
        elif prod_status == "COMPLETED":
            if prod_target and prod_actual:
                limit = prod_target + timedelta(minutes=prod_tol)
                if prod_actual > limit:
                    prod_color = "red"
                    prod_status_text = "Telat selesai"
                    prod_tooltip = f"Dapur {session_name}: target {_format_time(prod_target)}, selesai {_format_time(prod_actual)} (telat)"
                else:
                    prod_color = "green"
                    prod_status_text = "Tepat waktu"
                    prod_tooltip = f"Dapur {session_name}: selesai {_format_time(prod_actual)}"
            else:
                prod_color = "green"
                prod_status_text = "Selesai"
                prod_tooltip = f"Dapur {session_name}: produksi selesai"
        elif prod_status == "IN_PROGRESS":
            if prod_target and is_today and curr_now > (prod_target + timedelta(minutes=prod_tol)):
                prod_color = "red"
                prod_status_text = "Sedang masak (telat)"
                prod_tooltip = f"Dapur {session_name}: target {_format_time(prod_target)} (lewat target)"
            else:
                prod_color = "blue"
                prod_status_text = "Sedang dimasak"
                prod_tooltip = f"Dapur {session_name}: proses masak berjalan"
        else:  # DRAFT
            if prod_target and is_today and curr_now > (prod_target + timedelta(minutes=prod_tol)):
                prod_color = "red"
                prod_status_text = "Belum mulai (telat)"
                prod_tooltip = f"Dapur {session_name}: target {_format_time(prod_target)} (belum mulai)"
            else:
                prod_color = "gray"
                prod_status_text = "Belum mulai"
                prod_tooltip = f"Dapur {session_name}: target {_format_time(prod_target) if prod_target else '-'}"

        point_cook = {
            "key": "cook",
            "label": "Masak",
            "time_display": _format_time(prod_target or prod_actual) if (prod_target or prod_actual) else None,
            "pct": prod_pct,
            "color": prod_color,
            "tooltip": prod_tooltip,
            "status_text": prod_status_text,
        }

        # --- TITIK 3 & 4: PENGIRIMAN (BERANGKAT & TIBA) ---
        session_deliveries = [
            d for d in deliveries if f"delivery_type={meal_type}" in (d.notes or "")
        ]

        target_dispatches = [d.target_dispatch_time for d in session_deliveries if d.target_dispatch_time]
        actual_dispatches = [to_wib(d.actual_departure_time) for d in session_deliveries if d.actual_departure_time]  # disimpan UTC
        target_arrivals = [d.target_arrival_time for d in session_deliveries if d.target_arrival_time]
        receipt_times = [
            to_wib(det.receipt.receive_time)  # disimpan UTC
            for d in session_deliveries
            for det in d.details
            if det.receipt and det.receipt.receive_time
        ]

        target_dispatch = min(target_dispatches) if target_dispatches else None
        actual_dispatch = min(actual_dispatches) if actual_dispatches else None
        target_arrival = max(target_arrivals) if target_arrivals else None
        last_receive = max(receipt_times) if receipt_times else None

        total_details = sum(len(d.details) for d in session_deliveries)
        total_received = len(receipt_times)
        all_received = bool(total_details > 0 and total_received >= total_details)
        any_in_transit = any(d.status in ("IN_TRANSIT", "ON_THE_WAY") for d in session_deliveries)

        deliv_tol = min([d.late_tolerance_minutes or 15 for d in session_deliveries]) if session_deliveries else 15

        # Berangkat Point
        disp_pct = _calc_pct(target_dispatch or actual_dispatch) if (target_dispatch or actual_dispatch) else 65.0
        disp_color = "gray"
        disp_status_text = ""
        disp_tooltip = ""

        if not session_deliveries or (not target_dispatch and not actual_dispatch):
            disp_color = "gray"
            disp_status_text = "Belum dijadwalkan"
            disp_tooltip = f"Armada {session_name}: belum ada jadwal keberangkatan"
        elif actual_dispatch:
            if target_dispatch:
                limit = target_dispatch + timedelta(minutes=deliv_tol)
                if actual_dispatch > limit:
                    disp_color = "red"
                    disp_status_text = "Telat berangkat"
                    disp_tooltip = f"Berangkat {session_name}: target {_format_time(target_dispatch)}, berangkat {_format_time(actual_dispatch)} (telat)"
                else:
                    disp_color = "green"
                    disp_status_text = "Tepat waktu"
                    disp_tooltip = f"Berangkat {session_name}: berangkat {_format_time(actual_dispatch)}"
            else:
                disp_color = "green"
                disp_status_text = "Berangkat"
                disp_tooltip = f"Berangkat {session_name}: berangkat {_format_time(actual_dispatch)}"
        else:
            if target_dispatch and is_today and curr_now > (target_dispatch + timedelta(minutes=deliv_tol)):
                disp_color = "red"
                disp_status_text = "Telat berangkat"
                disp_tooltip = f"Berangkat {session_name}: target {_format_time(target_dispatch)} (belum berangkat)"
            elif any_in_transit:
                disp_color = "blue"
                disp_status_text = "Di perjalanan"
                disp_tooltip = f"Berangkat {session_name}: armada sedang jalan"
            else:
                disp_color = "gray"
                disp_status_text = "Menunggu siap"
                disp_tooltip = f"Berangkat {session_name}: target {_format_time(target_dispatch) if target_dispatch else '-'}"

        point_dispatch = {
            "key": "dispatch",
            "label": "Berangkat",
            "time_display": _format_time(target_dispatch or actual_dispatch) if (target_dispatch or actual_dispatch) else None,
            "pct": disp_pct,
            "color": disp_color,
            "tooltip": disp_tooltip,
            "status_text": disp_status_text,
        }

        # Tiba Point
        arr_pct = _calc_pct(target_arrival or last_receive) if (target_arrival or last_receive) else 85.0
        arr_color = "gray"
        arr_status_text = ""
        arr_tooltip = ""

        if not session_deliveries or (not target_arrival and not last_receive):
            arr_color = "gray"
            arr_status_text = "Belum dijadwalkan"
            arr_tooltip = f"Tiba {session_name}: belum ada jadwal tiba"
        elif all_received:
            if target_arrival and last_receive:
                limit = target_arrival + timedelta(minutes=deliv_tol)
                if last_receive > limit:
                    arr_color = "red"
                    arr_status_text = "Diterima (telat)"
                    arr_tooltip = f"Tiba {session_name}: target {_format_time(target_arrival)}, selesai terima {_format_time(last_receive)} (telat)"
                else:
                    arr_color = "green"
                    arr_status_text = "Lengkap diterima"
                    arr_tooltip = f"Tiba {session_name}: lengkap diterima {_format_time(last_receive)}"
            else:
                arr_color = "green"
                arr_status_text = "Lengkap diterima"
                arr_tooltip = f"Tiba {session_name}: semua lokasi sudah menerima"
        elif total_received > 0 or any_in_transit:
            if target_arrival and is_today and curr_now > (target_arrival + timedelta(minutes=deliv_tol)):
                arr_color = "red"
                arr_status_text = "Sebagian (telat)"
                arr_tooltip = f"Tiba {session_name}: {total_received}/{total_details} diterima (melewati target {_format_time(target_arrival)})"
            else:
                arr_color = "blue"
                arr_status_text = f"Proses ({total_received}/{total_details})"
                arr_tooltip = f"Tiba {session_name}: {total_received}/{total_details} lokasi sudah terima"
        else:
            if target_arrival and is_today and curr_now > (target_arrival + timedelta(minutes=deliv_tol)):
                arr_color = "red"
                arr_status_text = "Telat tiba"
                arr_tooltip = f"Tiba {session_name}: target {_format_time(target_arrival)} (belum sampai)"
            else:
                arr_color = "gray"
                arr_status_text = "Belum tiba"
                arr_tooltip = f"Tiba {session_name}: target {_format_time(target_arrival) if target_arrival else '-'}"

        point_arrive = {
            "key": "arrive",
            "label": "Tiba",
            "time_display": _format_time(target_arrival or last_receive) if (target_arrival or last_receive) else None,
            "pct": arr_pct,
            "color": arr_color,
            "tooltip": arr_tooltip,
            "status_text": arr_status_text,
        }

        sessions_data.append({
            "session_code": meal_type,
            "session_name": session_name,
            "icon": icon,
            "points": [point_lock, point_cook, point_dispatch, point_arrive],
        })

    return {
        "day": day,
        "is_today": is_today,
        "now_pct": now_pct,
        "now_time_str": curr_now.strftime("%H.%M"),
        "sessions": sessions_data,
    }


def get_order_lock_countdowns(
    order: Optional[DailyOrder],
    on_date: Optional[date] = None,
    branch_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Hitung mundur jam kunci per sesi untuk kartu Hari Ini/Besok atau kepala order_detail (Task C)."""
    if order and order.is_locked:
        return []

    target_date = order.order_date if order else (on_date or today_wib())
    b_id = order.branch_id if order else branch_id
    curr_now = now_wib()

    countdowns = []
    for meal_type, session_name in (("LUNCH", "Siang"), ("DINNER", "Sore")):
        # Bila order memiliki detail, cek apakah ada porsi untuk sesi ini
        if order and order.details:
            qty_sum = sum((d.lunch_qty if meal_type == "LUNCH" else d.dinner_qty) or 0 for d in order.details)
            if qty_sum <= 0:
                continue

        # Kumpulkan client id
        client_ids = set()
        if order and order.details:
            for d in order.details:
                q = (d.lunch_qty if meal_type == "LUNCH" else d.dinner_qty) or 0
                if q > 0 and d.mandor and d.mandor.client_id:
                    client_ids.add(d.mandor.client_id)

        earliest_time: Optional[time] = None
        if client_ids:
            for c_id in client_ids:
                lt = lock_time_for(c_id, meal_type, on_date=target_date, branch_id=b_id)
                if lt:
                    if earliest_time is None or lt < earliest_time:
                        earliest_time = lt
        else:
            earliest_time = lock_time_for(None, meal_type, on_date=target_date, branch_id=b_id)

        if not earliest_time:
            continue

        target_dt = datetime.combine(target_date, earliest_time)
        seconds_left = int((target_dt - curr_now).total_seconds())

        if seconds_left > 0:
            h = seconds_left // 3600
            m = (seconds_left % 3600) // 60
            s = seconds_left % 60
            text = f"Kunci {session_name.lower()} dalam {h:02d}:{m:02d}:{s:02d}"
            if seconds_left > 3600:
                tone = "normal"
            elif seconds_left > 900:
                tone = "warning"
            else:
                tone = "danger"
            is_passed = False
        else:
            text = f"Kunci {session_name.lower()}: Lewat jam kunci"
            tone = "danger"
            is_passed = True

        countdowns.append({
            "meal_type": meal_type,
            "session_name": session_name,
            "lock_time_str": earliest_time.strftime("%H.%M"),
            "target_iso": target_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "text": text,
            "tone": tone,
            "is_passed": is_passed,
        })

    return countdowns
