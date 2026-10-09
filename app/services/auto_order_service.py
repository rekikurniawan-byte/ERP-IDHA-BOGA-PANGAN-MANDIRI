"""Layanan Pesanan Otomatis Harian dan Kontrol Perubahan Porsi (Fase 5).

Menangani:
1. Tugas otomatis jam 18.00 WIB (`auto_daily_orders`) untuk client/sub client kontrak.
2. Aturan porsi hari kerja terakhir dan penanganan porsi 0 dengan alasan wajib.
3. Modifikasi porsi langsung dari portal sebelum cutoff/lock time.
4. Modifikasi porsi oleh admin setelah lock dengan alasan wajib.
5. Larangan total perubahan porsi saat pengiriman sudah berjalan/diterima.
6. Pencatatan jejak audit porsi di `order_qty_changes` dan state di `standing_order_states`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import logging
from typing import Any

from app.extensions import db
from app.models.contract import CustomerContract
from app.models.credit import BILLING_CASH, BILLING_DIRECT, BILLING_VIA_CLIENT
from app.models.credit import STATUS_BLOCKED as STATUS_CREDIT_BLOCKED
from app.models.credit import STATUS_HOLD as STATUS_CREDIT_HOLD
from app.models.credit import STATUS_WRITE_OFF as STATUS_CREDIT_WRITE_OFF
from app.models.delivery import Delivery, DeliveryDetail
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.operational import DailyOrder, DailyOrderDetail, OrderQtyChange, StandingOrderState
from app.services.atomic_transaction_service import atomic_business_action
from app.services.contract_rules_service import (
    active_contract_for,
    billing_mode_for,
    is_contract_holiday,
    lock_time_for,
)
from app.services.credit_control_service import evaluate_credit
from app.services.notification_service import create_or_update_notification
from app.services.operational_service import generate_order_number
from app.services.pricing_service import quote_price, quote_trip_fee
from app.services.portal_order_draft_service import session_closed_reason
from app.utils.clock import format_wib, now_wib, today_wib, to_wib

logger = logging.getLogger(__name__)

# Kode alasan saat porsi diubah menjadi 0
REASON_OFF_TODAY = "OFF_TODAY"
REASON_OFF_UNTIL = "OFF_UNTIL"
REASON_PAUSE = "PAUSE"
REASON_PROJECT_DONE = "PROJECT_DONE"
REASON_NO_WORKERS = "NO_WORKERS"
REASON_OTHER = "OTHER"

PORTION_ZERO_REASONS = {
    REASON_OFF_TODAY: "Libur hari ini saja",
    REASON_OFF_UNTIL: "Libur sampai tanggal tertentu",
    REASON_PAUSE: "Berhenti sementara, saya pesan lagi nanti",
    REASON_PROJECT_DONE: "Proyek/pekerjaan selesai",
    REASON_NO_WORKERS: "Pekerja tidak di lokasi",
    REASON_OTHER: "Lainnya",
}

STATUS_ACTIVE = "ACTIVE"
STATUS_PAUSED_UNTIL = "PAUSED_UNTIL"
STATUS_STOPPED = "STOPPED"

SOURCE_AUTO = "AUTO"
SOURCE_PORTAL = "PORTAL"
SOURCE_ADMIN = "ADMIN"

MEAL_TYPES = ("LUNCH", "DINNER")
MEAL_LABELS = {
    "LUNCH": "Siang",
    "DINNER": "Malam",
}


def _normalize_now(now: datetime | None = None) -> datetime:
    """Normalisasi waktu ke naive WIB datetime."""
    if now is None:
        return now_wib()
    if now.tzinfo is not None:
        return to_wib(now)
    return now


def _portal_users_for_mandor(mandor: Mandor) -> list[User]:
    """Akun portal yang memegang sub client ini (lewat pemetaan portal aktif).

    User tidak punya kolom mandor_id; hubungan akun portal <-> sub client ada di
    PortalUserMapping (dipetakan langsung ke mandor, atau ke client-nya).
    """
    from app.models.system import PortalUserMapping

    user_ids = {
        row.user_id
        for row in PortalUserMapping.query.filter(
            PortalUserMapping.is_active.is_(True),
            db.or_(
                PortalUserMapping.mandor_id == mandor.id,
                db.and_(PortalUserMapping.client_id == mandor.client_id, PortalUserMapping.mandor_id.is_(None)),
            ),
        ).all()
    }
    if not user_ids:
        return []
    return User.query.filter(User.id.in_(user_ids), User.is_active.is_(True)).all()


def _apply_zero_reason_state(st_state, reason_code, resume_date, *, mandor, client, location, branch_id):
    """Efek alasan porsi 0 ke standing_order_states (dipakai portal & admin)."""
    if reason_code == REASON_OFF_UNTIL:
        st_state.status = STATUS_PAUSED_UNTIL
        st_state.resume_date = resume_date
    elif reason_code in (REASON_PAUSE, REASON_PROJECT_DONE):
        st_state.status = STATUS_STOPPED
        st_state.resume_date = None
        if reason_code == REASON_PROJECT_DONE:
            create_or_update_notification(
                branch_id=branch_id,
                notification_type="CONTRACT_REVIEW_REQUIRED",
                title=f"Proyek Selesai: {mandor.name}",
                message=(
                    f"{mandor.name} ({client.name if client else '-'}) menandai proyek selesai pada "
                    f"{location.location_name if location else '-'}. Tinjau kontrak."
                ),
                target_role="ADMIN",
                priority="WARNING",
                commit=False,
            )
    else:
        # OFF_TODAY, NO_WORKERS, OTHER: hanya hari itu; besok kembali ke porsi terakhir.
        st_state.status = STATUS_ACTIVE
        st_state.resume_date = None


def is_delivery_in_transit_or_delivered(order_detail_id: int, meal_type: str) -> bool:
    """Periksa apakah pengiriman untuk detail order dan sesi makan ini sudah berjalan atau diterima.

    Jika makanan sudah dalam perjalanan atau diterima, porsi dikunci TOTAL untuk semua orang
    termasuk admin.
    """
    if not order_detail_id:
        return False
    meal_key = str(meal_type or "").upper()
    rows = (
        DeliveryDetail.query.join(Delivery, DeliveryDetail.delivery_id == Delivery.id)
        .filter(
            DeliveryDetail.daily_order_detail_id == order_detail_id,
            Delivery.status != "CANCELLED",
            Delivery.notes.like(f"%delivery_type={meal_key}%"),
        )
        .all()
    )
    for row in rows:
        if row.receipt is not None:
            return True
        status = str(row.delivery.status or "").upper()
        if status in ("ON_THE_WAY", "DELIVERED"):
            return True
        if row.delivery.actual_departure_time is not None:
            return True
        if int(row.delivered_qty or 0) > 0:
            return True
    return False


def get_last_working_day(
    client_id: int,
    before_date: date,
    branch_id: int | None = None,
    max_days_back: int = 60,
) -> date | None:
    """Cari hari kerja terakhir kontrak (hari sebelum target yang bukan hari libur kontrak)."""
    curr = before_date - timedelta(days=1)
    for _ in range(max_days_back):
        if not is_contract_holiday(client_id, curr, branch_id=branch_id):
            return curr
        curr -= timedelta(days=1)
    return None


def resolve_auto_order_qty(
    branch_id: int,
    client_id: int,
    mandor_id: int,
    delivery_location_id: int,
    meal_type: str,
    tomorrow_date: date,
) -> tuple[int, bool, str]:
    """Tentukan jumlah porsi besok untuk satu lokasi dan sesi makan.

    Returns:
        (qty, can_create, reason_message)
    """
    meal_key = str(meal_type or "").upper()

    # 1. Periksa standing order state
    state = StandingOrderState.query.filter_by(
        branch_id=branch_id,
        mandor_id=mandor_id,
        delivery_location_id=delivery_location_id,
        meal_type=meal_key,
    ).first()

    if state:
        if state.status == STATUS_STOPPED:
            return 0, False, "State STOPPED (berhenti)"
        if state.status == STATUS_PAUSED_UNTIL and state.resume_date:
            if tomorrow_date < state.resume_date:
                return 0, False, f"State PAUSED_UNTIL sampai {state.resume_date}"

    # 2. Cari hari kerja terakhir yang bukan libur kontrak
    last_work_day = get_last_working_day(client_id, tomorrow_date, branch_id=branch_id)
    if not last_work_day:
        return 0, False, "Tidak ditemukan hari kerja sebelum tanggal ini"

    # 3. Cari DailyOrderDetail pada hari kerja terakhir
    last_order_detail = (
        DailyOrderDetail.query.join(DailyOrder, DailyOrderDetail.daily_order_id == DailyOrder.id)
        .filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.order_date == last_work_day,
            DailyOrder.status != "CANCELLED",
            DailyOrderDetail.mandor_id == mandor_id,
            DailyOrderDetail.delivery_location_id == delivery_location_id,
        )
        .first()
    )

    if last_order_detail:
        last_qty = (
            int(last_order_detail.lunch_qty or 0)
            if meal_key == "LUNCH"
            else int(last_order_detail.dinner_qty or 0)
        )
        if last_qty > 0:
            return last_qty, True, "OK"
        # Jika porsi hari kerja terakhir adalah 0, pakai last_nonzero_qty
        if state and state.last_nonzero_qty > 0:
            return state.last_nonzero_qty, True, "OK (dari last_nonzero_qty state)"

    # 4. Jika tidak ada detail pada hari kerja terakhir, periksa riwayat lampau
    has_prior_order = (
        DailyOrderDetail.query.join(DailyOrder, DailyOrderDetail.daily_order_id == DailyOrder.id)
        .filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.order_date < tomorrow_date,
            DailyOrder.status != "CANCELLED",
            DailyOrderDetail.mandor_id == mandor_id,
            DailyOrderDetail.delivery_location_id == delivery_location_id,
        )
        .first()
        is not None
    )

    if not has_prior_order:
        # Tidak ada riwayat sama sekali -> jangan buat (pesanan pertama manual/portal)
        return 0, False, "Belum ada riwayat pesanan sama sekali"

    if state and state.last_nonzero_qty > 0:
        return state.last_nonzero_qty, True, "OK (dari last_nonzero_qty state)"

    # Cari nonzero qty terakhir dari riwayat order lama
    prior_nonzero = (
        DailyOrderDetail.query.join(DailyOrder, DailyOrderDetail.daily_order_id == DailyOrder.id)
        .filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.order_date < tomorrow_date,
            DailyOrder.status != "CANCELLED",
            DailyOrderDetail.mandor_id == mandor_id,
            DailyOrderDetail.delivery_location_id == delivery_location_id,
            (DailyOrderDetail.lunch_qty > 0) if meal_key == "LUNCH" else (DailyOrderDetail.dinner_qty > 0),
        )
        .order_by(DailyOrder.order_date.desc(), DailyOrderDetail.id.desc())
        .first()
    )
    if prior_nonzero:
        qty = int(prior_nonzero.lunch_qty or 0) if meal_key == "LUNCH" else int(prior_nonzero.dinner_qty or 0)
        if qty > 0:
            return qty, True, "OK (dari riwayat non-zero)"

    return 0, False, "Porsi hari kerja terakhir 0 dan belum ada porsi non-zero"


def run_auto_daily_orders(
    branch_id: int | None = None,
    period_key: str | None = None,
    now: datetime | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """Tugas otomatis harian jam 18:00 WIB untuk membuat pesanan besok secara idempoten."""
    now_dt = _normalize_now(now)
    if period_key:
        try:
            period_date = date.fromisoformat(period_key)
        except (ValueError, TypeError):
            period_date = now_dt.date()
    else:
        period_date = now_dt.date()

    # Besok = tanggal periode + 1
    tomorrow_date = period_date + timedelta(days=1)

    branches_query = Branch.query
    if branch_id:
        branches_query = branches_query.filter_by(id=branch_id)
    branches = branches_query.all()

    created_orders_count = 0
    created_portions_total = 0
    skipped_records = []
    processed_details = []

    # Map untuk agregasi notifikasi ke portal subclient/client per (client_id, mandor_id)
    portal_notice_map: dict[tuple[int, int], dict[str, Any]] = {}
    # Baris pesanan yang dibuat run INI (sesi malam boleh masuk ke baris yang baru
    # dibuat sesi siang); baris yang sudah ada sebelum run tidak pernah disentuh.
    created_detail_ids: set[int] = set()

    for branch in branches:
        b_id = branch.id
        # Ambil semua client yang punya kontrak aktif pada tanggal besok
        active_contracts = (
            CustomerContract.query.filter(
                CustomerContract.branch_id == b_id,
                CustomerContract.status == "ACTIVE",
                CustomerContract.start_date <= tomorrow_date,
                CustomerContract.end_date >= tomorrow_date,
            )
            .all()
        )

        for contract in active_contracts:
            client = contract.client
            if not client or not client.is_active:
                continue

            # Periksa hari libur kontrak
            if is_contract_holiday(client.id, tomorrow_date, branch_id=b_id):
                skipped_records.append({
                    "branch_id": b_id,
                    "client_id": client.id,
                    "client_name": client.name,
                    "mandor_id": None,
                    "reason": "Besok adalah hari libur kontrak (rutin/khusus)",
                })
                continue

            # Ambil semua sub client (mandor) aktif client ini
            mandors = Mandor.query.filter_by(
                branch_id=b_id,
                client_id=client.id,
                is_active=True,
            ).all()

            for mandor in mandors:
                # 1. Cek mode tagih: bila bayar di muka (CASH) -> lewati
                b_mode = billing_mode_for(mandor.id, tomorrow_date, branch_id=b_id)
                if b_mode == BILLING_CASH:
                    skipped_records.append({
                        "branch_id": b_id,
                        "client_id": client.id,
                        "client_name": client.name,
                        "mandor_id": mandor.id,
                        "mandor_name": mandor.name,
                        "reason": "Pihak tagih bayar di muka (CASH) — pesanan lewat portal",
                    })
                    continue

                # 2. Cek status kredit: Tahan / Blokir
                credit_decision = evaluate_credit(
                    b_id,
                    client_id=client.id,
                    mandor_id=mandor.id,
                    pending_amount=0,
                    today=tomorrow_date,
                )
                # Status kredit memakai konstanta TAHAN/BLOKIR/HAPUS_BUKU; TAHAN tidak
                # "ditolak" tapi butuh persetujuan OWNER -- pesanan otomatis tidak boleh
                # melewati keputusan itu.
                if credit_decision.enforced and (
                    not credit_decision.allowed
                    or credit_decision.requires_approval
                    or credit_decision.status in (STATUS_CREDIT_HOLD, STATUS_CREDIT_BLOCKED, STATUS_CREDIT_WRITE_OFF)
                ):
                    reason_msg = (
                        f"Pesanan besok tidak dibuat karena status kredit {credit_decision.status}: "
                        f"{credit_decision.message or credit_decision.reason}"
                    )
                    skipped_records.append({
                        "branch_id": b_id,
                        "client_id": client.id,
                        "client_name": client.name,
                        "mandor_id": mandor.id,
                        "mandor_name": mandor.name,
                        "reason": reason_msg,
                    })

                    # Kirim notifikasi ke admin & akun portal client/sub client
                    create_or_update_notification(
                        branch_id=b_id,
                        notification_type="CREDIT_AUTO_ORDER_BLOCKED",
                        title=f"Pesanan Otomatis Ditahan: {mandor.name}",
                        message=reason_msg,
                        target_role="ADMIN",
                        priority="WARNING",
                        commit=False,
                    )
                    # Notifikasi ke akun portal sub client / client
                    for portal_user in _portal_users_for_mandor(mandor):
                        create_or_update_notification(
                            branch_id=b_id,
                            notification_type="CREDIT_AUTO_ORDER_BLOCKED",
                            title="Pesanan Otomatis Besok Ditahan",
                            message=reason_msg,
                            target_user_id=portal_user.id,
                            priority="WARNING",
                            generated_key=f"auto-order-blocked-{mandor.id}-{tomorrow_date.isoformat()}-{portal_user.id}",
                            commit=False,
                        )
                    continue

                # 3. Iterasi tiap lokasi antar aktif
                locations = DeliveryLocation.query.filter_by(
                    mandor_id=mandor.id,
                    is_active=True,
                ).all()

                for location in locations:
                    for meal_type in MEAL_TYPES:
                        target_qty, can_create, reason = resolve_auto_order_qty(
                            branch_id=b_id,
                            client_id=client.id,
                            mandor_id=mandor.id,
                            delivery_location_id=location.id,
                            meal_type=meal_type,
                            tomorrow_date=tomorrow_date,
                        )

                        if not can_create or target_qty <= 0:
                            skipped_records.append({
                                "branch_id": b_id,
                                "client_id": client.id,
                                "mandor_id": mandor.id,
                                "location_id": location.id,
                                "meal_type": meal_type,
                                "reason": reason,
                            })
                            continue

                        # Periksa apakah DailyOrderDetail untuk besok sudah ada
                        daily_order = DailyOrder.query.filter_by(
                            branch_id=b_id,
                            order_date=tomorrow_date,
                        ).first()

                        existing_detail = None
                        if daily_order is not None:
                            existing_detail = DailyOrderDetail.query.filter_by(
                                daily_order_id=daily_order.id,
                                mandor_id=mandor.id,
                                delivery_location_id=location.id,
                            ).first()

                        # Pesanan besok untuk lokasi ini sudah ada (dipesan manual/portal,
                        # atau dibuat run sebelumnya): jangan disentuh sama sekali -- termasuk
                        # sesi yang sengaja dikosongkan pemesan. Ini juga membuat tugas idempoten.
                        if existing_detail is not None and existing_detail.id not in created_detail_ids:
                            skipped_records.append({
                                "branch_id": b_id,
                                "mandor_id": mandor.id,
                                "location_id": location.id,
                                "meal_type": meal_type,
                                "reason": "Pesanan besok untuk lokasi ini sudah ada (tidak ditimpa)",
                            })
                            continue

                        # Harga & ongkir wajib bisa dihitung; jangan pernah membuat pesanan Rp0.
                        quote = quote_price(b_id, client.id, on_date=tomorrow_date)
                        if not quote or not quote.price:
                            skipped_records.append({
                                "branch_id": b_id,
                                "mandor_id": mandor.id,
                                "location_id": location.id,
                                "meal_type": meal_type,
                                "reason": "Harga per porsi belum diatur — pesanan tidak dibuat",
                            })
                            continue
                        price = quote.price
                        price_source = quote.source

                        trip_fee, _, fee_error = quote_trip_fee(
                            b_id, client, location, target_qty, on_date=tomorrow_date
                        )
                        if fee_error:
                            skipped_records.append({
                                "branch_id": b_id,
                                "mandor_id": mandor.id,
                                "location_id": location.id,
                                "meal_type": meal_type,
                                "reason": f"Ongkir tidak bisa dihitung: {fee_error}",
                            })
                            continue
                        delivery_fee = trip_fee or Decimal("0")

                        if daily_order is None:
                            daily_order = DailyOrder(
                                order_number=generate_order_number(tomorrow_date),
                                branch_id=b_id,
                                order_date=tomorrow_date,
                                status="DRAFT",
                                is_locked=False,
                                notes="Dibuat otomatis oleh tugas harian jam 18:00 WIB",
                                created_by=contract.created_by,
                            )
                            db.session.add(daily_order)
                            db.session.flush()

                        # Buat atau gabungkan ke DailyOrderDetail
                        if existing_detail is not None:
                            detail = existing_detail
                            if meal_type == "LUNCH":
                                detail.lunch_qty = target_qty
                                detail.lunch_delivery_fee = delivery_fee
                            else:
                                detail.dinner_qty = target_qty
                                detail.dinner_delivery_fee = delivery_fee
                            detail.total_qty = int(detail.lunch_qty or 0) + int(detail.dinner_qty or 0)
                        else:
                            detail = DailyOrderDetail(
                                daily_order_id=daily_order.id,
                                mandor_id=mandor.id,
                                delivery_location_id=location.id,
                                price_per_portion=price,
                                price_source=price_source,
                                lunch_qty=target_qty if meal_type == "LUNCH" else 0,
                                dinner_qty=target_qty if meal_type == "DINNER" else 0,
                                total_qty=target_qty,
                                lunch_delivery_fee=delivery_fee if meal_type == "LUNCH" else Decimal("0"),
                                dinner_delivery_fee=delivery_fee if meal_type == "DINNER" else Decimal("0"),
                                notes="Pesanan otomatis harian 18:00 WIB",
                            )
                            db.session.add(detail)
                            created_orders_count += 1

                        db.session.flush()
                        created_detail_ids.add(detail.id)
                        created_portions_total += target_qty

                        # Catat ke order_qty_changes (source=AUTO)
                        qty_change = OrderQtyChange(
                            branch_id=b_id,
                            daily_order_detail_id=detail.id,
                            meal_type=meal_type,
                            old_qty=0,
                            new_qty=target_qty,
                            source=SOURCE_AUTO,
                            reason_code=None,
                            note="Dibuat otomatis oleh penjadwal 18:00 WIB",
                            changed_by=None,
                            changed_at=now_dt,
                        )
                        db.session.add(qty_change)

                        # Perbarui atau buat standing_order_states
                        st_state = StandingOrderState.query.filter_by(
                            branch_id=b_id,
                            mandor_id=mandor.id,
                            delivery_location_id=location.id,
                            meal_type=meal_type,
                        ).first()
                        if st_state:
                            st_state.status = STATUS_ACTIVE
                            st_state.resume_date = None
                            st_state.last_nonzero_qty = target_qty
                            st_state.updated_at = now_dt
                        else:
                            st_state = StandingOrderState(
                                branch_id=b_id,
                                mandor_id=mandor.id,
                                delivery_location_id=location.id,
                                meal_type=meal_type,
                                status=STATUS_ACTIVE,
                                resume_date=None,
                                last_nonzero_qty=target_qty,
                                updated_at=now_dt,
                            )
                            db.session.add(st_state)

                        processed_details.append(detail.id)

                        # Agregasi untuk notifikasi ke portal
                        portal_key = (client.id, mandor.id)
                        if portal_key not in portal_notice_map:
                            portal_notice_map[portal_key] = {
                                "client": client,
                                "mandor": mandor,
                                "branch_id": b_id,
                                "lunch_total": 0,
                                "dinner_total": 0,
                            }
                        if meal_type == "LUNCH":
                            portal_notice_map[portal_key]["lunch_total"] += target_qty
                        else:
                            portal_notice_map[portal_key]["dinner_total"] += target_qty

    # Kirim notifikasi ke portal subclient/client
    for (c_id, m_id), p_info in portal_notice_map.items():
        client_obj = p_info["client"]
        mandor_obj = p_info["mandor"]
        b_id = p_info["branch_id"]

        lock_lunch = lock_time_for(client_obj.id, "LUNCH", on_date=tomorrow_date, branch_id=b_id)
        lock_dinner = lock_time_for(client_obj.id, "DINNER", on_date=tomorrow_date, branch_id=b_id)
        lunch_str = lock_lunch.strftime("%H.%M") if lock_lunch else "10.00"
        dinner_str = lock_dinner.strftime("%H.%M") if lock_dinner else "15.00"

        msg = (
            f"Pesanan besok ({tomorrow_date.strftime('%d-%m-%Y')}): "
            f"Siang {p_info['lunch_total']}, Malam {p_info['dinner_total']}. "
            f"Ubah sebelum {lunch_str} / {dinner_str} WIB."
        )

        for portal_user in _portal_users_for_mandor(mandor_obj):
            create_or_update_notification(
                branch_id=b_id,
                notification_type="AUTO_ORDER_SUMMARY",
                title=f"Pesanan Besok: {mandor_obj.name}",
                message=msg,
                target_user_id=portal_user.id,
                priority="INFO",
                action_url="/portal/my-dashboard",
                generated_key=f"auto-order-summary-{mandor_obj.id}-{tomorrow_date.isoformat()}-{portal_user.id}",
                commit=False,
            )

    # Kirim ringkasan ke admin & dapur
    recap_title = f"Rekap Pesanan Otomatis Besok ({tomorrow_date.strftime('%d-%m-%Y')})"
    recap_msg = (
        f"Pesanan otomatis selesai: {created_orders_count} baris order baru, "
        f"{created_portions_total} total porsi dibuat. Dilewati: {len(skipped_records)} lokasi/sesi."
    )
    for role in ("ADMIN", "DAPUR") if branch_id else ():
        create_or_update_notification(
            branch_id=branch_id,
            notification_type="AUTO_ORDER_RECAP",
            title=recap_title,
            message=recap_msg,
            target_role=role,
            priority="INFO",
            action_url="/operational/order-qty-changes",
            commit=False,
        )

    if commit:
        with atomic_business_action(
            module="OPERATIONAL",
            action="AUTO_DAILY_ORDERS",
            branch_id=branch_id,
            audit_success=False,
        ):
            pass  # Commit handled by atomic_business_action exit
    else:
        db.session.flush()

    return {
        "period_date": period_date.isoformat(),
        "tomorrow_date": tomorrow_date.isoformat(),
        "created_orders_count": created_orders_count,
        "created_portions_total": created_portions_total,
        "skipped_count": len(skipped_records),
        "skipped_records": skipped_records,
    }


def update_order_qty_from_portal(
    user: User,
    mandor_id: int,
    delivery_location_id: int,
    meal_type: str,
    order_date: date,
    new_qty: int,
    reason_code: str | None = None,
    note: str | None = None,
    resume_date: date | None = None,
    *,
    commit: bool = True,
) -> tuple[bool, str, DailyOrderDetail | None]:
    """Ubah porsi pesanan harian langsung dari portal (Sub Client & Client kontrak)."""
    meal_key = str(meal_type or "").upper()
    if meal_key not in MEAL_TYPES:
        return False, "Sesi makan harus Makan Siang atau Makan Malam.", None

    if new_qty < 0:
        return False, "Jumlah porsi tidak boleh negatif.", None

    location = DeliveryLocation.query.get(delivery_location_id)
    if not location or location.mandor_id != mandor_id:
        return False, "Lokasi pengiriman tidak valid.", None

    mandor = location.mandor
    client = mandor.client if mandor else None
    if not mandor or not client:
        return False, "Data client/sub client tidak lengkap.", None

    # 0. Lokasi wajib dalam akses akun portal ini -- ID dari form bisa diakali.
    from app.services.portal_mapping_service import build_portal_external_scope
    from app.services.portal_order_draft_service import orderable_location_ids

    scope = build_portal_external_scope(user)
    if not scope.allowed or delivery_location_id not in orderable_location_ids(user, scope):
        return False, "Lokasi ini di luar akses akun Anda.", None

    b_id = mandor.branch_id

    # 1. Cek batas sesi / cutoff jam lock
    closed_reason = session_closed_reason(
        b_id,
        order_date,
        meal_key,
        client_id=client.id,
        location_id=delivery_location_id,
    )
    if closed_reason:
        return False, f"Sudah dikunci: {closed_reason}", None

    # 2. Cek DailyOrder locked
    daily_order = DailyOrder.query.filter_by(
        branch_id=b_id,
        order_date=order_date,
    ).first()
    if daily_order and daily_order.is_locked:
        return False, "Sudah dikunci oleh dapur, hubungi admin.", None

    # 3. Cek pengiriman dalam perjalanan / sudah diterima
    existing_detail = None
    if daily_order:
        existing_detail = DailyOrderDetail.query.filter_by(
            daily_order_id=daily_order.id,
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
        ).first()

    if existing_detail and is_delivery_in_transit_or_delivered(existing_detail.id, meal_key):
        return False, "Dalam perjalanan — tidak bisa diubah.", None

    old_qty = 0
    if existing_detail:
        old_qty = int(existing_detail.lunch_qty or 0) if meal_key == "LUNCH" else int(existing_detail.dinner_qty or 0)

    if new_qty == old_qty:
        return True, "Jumlah porsi tidak berubah.", existing_detail

    # 4. Validasi porsi 0 wajib alasan
    if new_qty == 0:
        if not reason_code or reason_code not in PORTION_ZERO_REASONS:
            return False, "Perubahan porsi ke 0 wajib menyertakan alasan yang valid.", None
        if reason_code == REASON_OFF_UNTIL:
            if not resume_date:
                return False, "Alasan libur sampai tanggal tertentu wajib menyertakan tanggal kembali pesan.", None
            if resume_date <= order_date:
                return False, "Tanggal kembali pesan harus setelah tanggal pesanan ini.", None
        if reason_code == REASON_OTHER and not (note or "").strip():
            return False, "Alasan 'Lainnya' wajib mengisi catatan penjelas.", None

    # 5. Kontrol kredit bila porsi dinaikkan
    if new_qty > old_qty:
        extra_qty = new_qty - old_qty
        quote = quote_price(b_id, client.id, on_date=order_date)
        price_per_portion = existing_detail.price_per_portion if existing_detail else (quote.price if quote else Decimal("0"))
        extra_amount = Decimal(extra_qty) * Decimal(price_per_portion)

        credit_decision = evaluate_credit(
            b_id,
            client_id=client.id,
            mandor_id=mandor.id,
            pending_amount=extra_amount,
            today=order_date,
        )
        if credit_decision.enforced and (
            not credit_decision.allowed
            or credit_decision.requires_approval
            or credit_decision.status in (STATUS_CREDIT_HOLD, STATUS_CREDIT_BLOCKED, STATUS_CREDIT_WRITE_OFF)
        ):
            msg = credit_decision.message or f"Status kredit {credit_decision.status} tidak mengizinkan penambahan porsi."
            return False, f"Penambahan porsi ditolak kontrol kredit: {msg}", None

    # 6. Simpan ke DailyOrderDetail
    if not daily_order:
        daily_order = DailyOrder(
            order_number=generate_order_number(order_date),
            branch_id=b_id,
            order_date=order_date,
            status="DRAFT",
            is_locked=False,
            notes="Dibuat dari perubahan porsi portal",
            created_by=user.id,
        )
        db.session.add(daily_order)
        db.session.flush()

    trip_fee, _, fee_error = quote_trip_fee(b_id, client, location, new_qty, on_date=order_date)
    if fee_error and new_qty > 0:
        return False, f"Ongkir tidak bisa dihitung: {fee_error}", None
    delivery_fee = trip_fee or Decimal("0")

    new_quote = None
    if not existing_detail:
        new_quote = quote_price(b_id, client.id, on_date=order_date)
        if not new_quote or not new_quote.price:
            return False, "Harga per porsi belum diatur. Hubungi admin.", None

    if existing_detail:
        detail = existing_detail
        if meal_key == "LUNCH":
            detail.lunch_qty = new_qty
            detail.lunch_delivery_fee = delivery_fee if new_qty > 0 else Decimal("0")
        else:
            detail.dinner_qty = new_qty
            detail.dinner_delivery_fee = delivery_fee if new_qty > 0 else Decimal("0")
        detail.total_qty = int(detail.lunch_qty or 0) + int(detail.dinner_qty or 0)
    else:
        detail = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            price_per_portion=new_quote.price,
            price_source=new_quote.source,
            lunch_qty=new_qty if meal_key == "LUNCH" else 0,
            dinner_qty=new_qty if meal_key == "DINNER" else 0,
            total_qty=new_qty,
            lunch_delivery_fee=delivery_fee if meal_key == "LUNCH" else Decimal("0"),
            dinner_delivery_fee=delivery_fee if meal_key == "DINNER" else Decimal("0"),
            notes=note or "Pesanan dari portal",
        )
        db.session.add(detail)

    db.session.flush()

    # 7. Catat audit di order_qty_changes
    qty_change = OrderQtyChange(
        branch_id=b_id,
        daily_order_detail_id=detail.id,
        meal_type=meal_key,
        old_qty=old_qty,
        new_qty=new_qty,
        source=SOURCE_PORTAL,
        reason_code=reason_code,
        note=note,
        changed_by=user.id,
        changed_at=now_wib(),
    )
    db.session.add(qty_change)

    # 8. Perbarui standing_order_states
    st_state = StandingOrderState.query.filter_by(
        branch_id=b_id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        meal_type=meal_key,
    ).first()
    if not st_state:
        st_state = StandingOrderState(
            branch_id=b_id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            meal_type=meal_key,
            status=STATUS_ACTIVE,
            last_nonzero_qty=new_qty if new_qty > 0 else 0,
            updated_at=now_wib(),
            updated_by=user.id,
        )
        db.session.add(st_state)
    else:
        st_state.updated_at = now_wib()
        st_state.updated_by = user.id

    if new_qty > 0:
        st_state.last_nonzero_qty = new_qty
        st_state.status = STATUS_ACTIVE
        st_state.resume_date = None
    else:
        _apply_zero_reason_state(
            st_state, reason_code, resume_date,
            mandor=mandor, client=client, location=location, branch_id=b_id,
        )

    # 9. Notifikasi ke admin dan dapur
    meal_name = MEAL_LABELS.get(meal_key, meal_key)
    notice_text = f"{mandor.name} · {location.location_name} · {meal_name} {old_qty} → {new_qty}"
    for role in ("ADMIN", "DAPUR"):
        create_or_update_notification(
            branch_id=b_id,
            notification_type="PORTAL_QTY_CHANGED",
            title="Perubahan Porsi Portal",
            message=notice_text,
            target_role=role,
            priority="INFO",
            action_url="/operational/order-qty-changes",
            commit=False,
        )

    if commit:
        with atomic_business_action(
            module="OPERATIONAL",
            action="PORTAL_ORDER_QTY_CHANGE",
            branch_id=b_id,
            audit_success=False,
        ):
            pass
    else:
        db.session.flush()

    return True, f"Porsi {meal_name} berhasil diubah menjadi {new_qty}.", detail


def update_order_qty_from_admin(
    user: User,
    detail_id: int,
    meal_type: str,
    new_qty: int,
    reason: str,
    reason_code: str | None = None,
    resume_date: date | None = None,
    *,
    commit: bool = True,
) -> tuple[bool, str, DailyOrderDetail | None]:
    """Ubah porsi oleh ADMIN atau OWNER setelah jam lock dengan alasan wajib."""
    meal_key = str(meal_type or "").upper()
    if meal_key not in MEAL_TYPES:
        return False, "Sesi makan harus Makan Siang atau Makan Malam.", None

    if new_qty < 0:
        return False, "Jumlah porsi tidak boleh negatif.", None

    detail = DailyOrderDetail.query.get(detail_id)
    if not detail:
        return False, "Detail pesanan tidak ditemukan.", None

    daily_order = detail.daily_order
    b_id = daily_order.branch_id

    # 1. Cek pengiriman dalam perjalanan / diterima — ditolak untuk SEMUA ORANG termasuk ADMIN
    if is_delivery_in_transit_or_delivered(detail.id, meal_key):
        return False, "Makanan sudah dalam perjalanan atau diterima — tidak bisa diubah oleh siapa pun.", None

    # 2. Cek apakah lock time sudah lewat atau order sudah dikunci
    mandor = detail.mandor
    client = mandor.client if mandor else None
    client_id = client.id if client else None

    closed_reason = session_closed_reason(
        b_id,
        daily_order.order_date,
        meal_key,
        client_id=client_id,
        location_id=detail.delivery_location_id,
    )
    is_locked = bool(daily_order.is_locked or closed_reason)

    if is_locked and not (reason or "").strip():
        return False, "Perubahan porsi setelah batas waktu / lock wajib menyertakan alasan tertulis.", None

    old_qty = int(detail.lunch_qty or 0) if meal_key == "LUNCH" else int(detail.dinner_qty or 0)
    if new_qty == old_qty:
        return True, "Jumlah porsi tidak berubah.", detail

    if reason_code and reason_code not in PORTION_ZERO_REASONS:
        return False, "Kode alasan porsi 0 tidak valid.", None
    if new_qty == 0 and reason_code == REASON_OFF_UNTIL:
        if not resume_date or resume_date <= daily_order.order_date:
            return False, "Libur sampai tanggal wajib diisi tanggal kembali pesan setelah tanggal pesanan ini.", None

    # Update qty & delivery fee
    trip_fee, _, fee_error = quote_trip_fee(
        b_id, client, detail.delivery_location, new_qty, on_date=daily_order.order_date
    )
    if fee_error and new_qty > 0:
        return False, f"Ongkir tidak bisa dihitung: {fee_error}", None
    delivery_fee = trip_fee or Decimal("0")

    if meal_key == "LUNCH":
        detail.lunch_qty = new_qty
        detail.lunch_delivery_fee = delivery_fee if new_qty > 0 else Decimal("0")
    else:
        detail.dinner_qty = new_qty
        detail.dinner_delivery_fee = delivery_fee if new_qty > 0 else Decimal("0")
    detail.total_qty = int(detail.lunch_qty or 0) + int(detail.dinner_qty or 0)
    db.session.flush()

    # Catat ke order_qty_changes
    qty_change = OrderQtyChange(
        branch_id=b_id,
        daily_order_detail_id=detail.id,
        meal_type=meal_key,
        old_qty=old_qty,
        new_qty=new_qty,
        source=SOURCE_ADMIN,
        reason_code=reason_code,
        note=reason,
        changed_by=user.id,
        changed_at=now_wib(),
    )
    db.session.add(qty_change)

    # Perbarui standing_order_states: porsi > 0 menyimpan porsi terakhir; porsi 0
    # dengan kode alasan berefek sama seperti dari portal.
    st_state = StandingOrderState.query.filter_by(
        branch_id=b_id,
        mandor_id=detail.mandor_id,
        delivery_location_id=detail.delivery_location_id,
        meal_type=meal_key,
    ).first()
    if st_state is None and (new_qty > 0 or reason_code):
        st_state = StandingOrderState(
            branch_id=b_id,
            mandor_id=detail.mandor_id,
            delivery_location_id=detail.delivery_location_id,
            meal_type=meal_key,
            status=STATUS_ACTIVE,
            last_nonzero_qty=old_qty if old_qty > 0 else 0,
        )
        db.session.add(st_state)
    if st_state is not None:
        st_state.updated_at = now_wib()
        st_state.updated_by = user.id
        if new_qty > 0:
            st_state.last_nonzero_qty = new_qty
            st_state.status = STATUS_ACTIVE
            st_state.resume_date = None
        elif reason_code:
            _apply_zero_reason_state(
                st_state, reason_code, resume_date,
                mandor=mandor, client=client, location=detail.delivery_location, branch_id=b_id,
            )

    # Bila order sudah locked, sinkronkan ulang produksi otomatis
    if daily_order.is_locked:
        from app.services.production_service import generate_production_from_order
        generate_production_from_order(daily_order, user.id, commit=False)

    if commit:
        with atomic_business_action(
            module="OPERATIONAL",
            action="ADMIN_ORDER_QTY_CHANGE",
            branch_id=b_id,
            audit_success=False,
        ):
            pass
    else:
        db.session.flush()

    meal_name = MEAL_LABELS.get(meal_key, meal_key)
    return True, f"Porsi {meal_name} berhasil diubah dari {old_qty} menjadi {new_qty}.", detail


def build_portal_today_tomorrow_orders_context(user: User) -> dict[str, Any]:
    """Data pesanan Hari Ini & Besok untuk kartu portal subclient dan client kontrak."""
    from app.services.portal_mapping_service import build_portal_external_scope

    scope = build_portal_external_scope(user)
    if not scope.allowed or not scope.delivery_location_ids:
        return {"has_contract": False, "days": []}

    from app.services.portal_order_draft_service import orderable_location_ids

    orderable_ids = orderable_location_ids(user, scope)
    today = today_wib()
    tomorrow = today + timedelta(days=1)
    branch_id = getattr(user, "branch_id", None)

    locations = (
        DeliveryLocation.query.filter(
            DeliveryLocation.id.in_(sorted(scope.delivery_location_ids)),
            DeliveryLocation.is_active.is_(True),
        )
        .order_by(DeliveryLocation.location_name.asc())
        .all()
    )

    days_data = []
    has_any_contract = False

    for dt, day_label in [(today, "Hari Ini"), (tomorrow, "Besok")]:
        location_rows = []

        daily_order = DailyOrder.query.filter_by(
            branch_id=branch_id,
            order_date=dt,
        ).first()

        for loc in locations:
            mandor = loc.mandor
            client = mandor.client if mandor else None
            client_id = client.id if client else None

            # Cek apakah client punya kontrak aktif
            contract = active_contract_for(client_id, on_date=dt, branch_id=branch_id)
            if contract:
                has_any_contract = True

            detail = None
            if daily_order:
                detail = DailyOrderDetail.query.filter_by(
                    daily_order_id=daily_order.id,
                    mandor_id=mandor.id,
                    delivery_location_id=loc.id,
                ).first()

            sessions = []
            for m in ("LUNCH", "DINNER"):
                m_label = MEAL_LABELS.get(m, m)
                qty = (
                    (int(detail.lunch_qty or 0) if m == "LUNCH" else int(detail.dinner_qty or 0))
                    if detail
                    else 0
                )

                st_state = StandingOrderState.query.filter_by(
                    branch_id=branch_id,
                    mandor_id=mandor.id,
                    delivery_location_id=loc.id,
                    meal_type=m,
                ).first()

                state_status = st_state.status if st_state else STATUS_ACTIVE
                last_nonzero = st_state.last_nonzero_qty if st_state else qty
                resume_dt = st_state.resume_date if st_state else None

                # Status flags
                in_delivery = is_delivery_in_transit_or_delivered(detail.id, m) if detail else False
                order_locked = bool(daily_order and daily_order.is_locked)
                closed_reason = session_closed_reason(
                    branch_id, dt, m, client_id=client_id, location_id=loc.id
                )
                holiday = is_contract_holiday(client_id, dt, branch_id=branch_id)
                lock_t = lock_time_for(client_id, m, on_date=dt, branch_id=branch_id)

                if in_delivery:
                    badge_label = "Dalam perjalanan"
                    badge_class = "danger"
                    can_edit = False
                    block_msg = "Dalam perjalanan — tidak bisa diubah"
                elif order_locked:
                    badge_label = "Sudah dikunci"
                    badge_class = "secondary"
                    can_edit = False
                    block_msg = "Sudah dikunci oleh dapur, hubungi admin"
                elif closed_reason:
                    badge_label = "Sudah dikunci"
                    badge_class = "secondary"
                    can_edit = False
                    block_msg = closed_reason
                elif holiday:
                    badge_label = "Libur Kontrak"
                    badge_class = "warning"
                    can_edit = False
                    block_msg = "Hari libur kontrak"
                else:
                    badge_label = "Bisa diubah"
                    badge_class = "success"
                    can_edit = True
                    block_msg = None

                if can_edit and loc.id not in orderable_ids:
                    # PT melihat lokasi sub client-nya untuk dipantau, tapi yang
                    # mengubah porsinya sub client itu sendiri.
                    can_edit = False
                    badge_label = "Dipantau"
                    badge_class = "secondary"
                    block_msg = "Porsi lokasi ini diubah oleh sub client-nya"

                can_resume = state_status in (STATUS_STOPPED, STATUS_PAUSED_UNTIL) and loc.id in orderable_ids

                sessions.append({
                    "meal_type": m,
                    "meal_label": m_label,
                    "qty": qty,
                    "last_nonzero_qty": last_nonzero,
                    "state_status": state_status,
                    "resume_date": resume_dt,
                    "lock_time_str": lock_t.strftime("%H.%M") if lock_t else "10.00",
                    "badge_label": badge_label,
                    "badge_class": badge_class,
                    "can_edit": can_edit,
                    "block_msg": block_msg,
                    "can_resume": can_resume,
                })

            location_rows.append({
                "location_id": loc.id,
                "location_name": loc.location_name,
                "mandor_id": mandor.id if mandor else None,
                "mandor_name": mandor.name if mandor else "-",
                "client_id": client_id,
                "client_name": client.name if client else "-",
                "sessions": sessions,
            })

        days_data.append({
            "date": dt,
            "date_iso": dt.isoformat(),
            "date_label": day_label,
            "formatted_date": dt.strftime("%d-%m-%Y"),
            "locations": location_rows,
        })

    return {
        "has_contract": has_any_contract,
        "days": days_data,
        "portion_zero_reasons": PORTION_ZERO_REASONS,
    }


def list_order_qty_changes(
    branch_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    mandor_id: int | None = None,
    source: str | None = None,
    limit: int = 100,
) -> list[OrderQtyChange]:
    """Ambil riwayat perubahan porsi dengan filter tanggal, sub client, dan sumber."""
    query = OrderQtyChange.query.join(
        DailyOrderDetail, OrderQtyChange.daily_order_detail_id == DailyOrderDetail.id
    ).join(
        DailyOrder, DailyOrderDetail.daily_order_id == DailyOrder.id
    )

    if branch_id:
        query = query.filter(DailyOrder.branch_id == branch_id)
    if start_date:
        query = query.filter(DailyOrder.order_date >= start_date)
    if end_date:
        query = query.filter(DailyOrder.order_date <= end_date)
    if mandor_id:
        query = query.filter(DailyOrderDetail.mandor_id == mandor_id)
    if source:
        query = query.filter(OrderQtyChange.source == source.upper())

    return (
        query.order_by(OrderQtyChange.changed_at.desc(), OrderQtyChange.id.desc())
        .limit(limit)
        .all()
    )
