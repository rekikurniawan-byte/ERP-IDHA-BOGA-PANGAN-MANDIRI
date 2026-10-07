"""Service for Menu Photos, Menu Descriptions, and Weekly Menu Schedules.

Rules:
- Atomic transactions via atomic_business_action.
- Dates & timestamps via now_wib() / today_wib().
- Digital attachments for photos (MODULE='MENU', REFERENCE_TYPE='MENU', ATTACHMENT_TYPE='MENU_PHOTO').
- Up to 3 photos per menu, first photo is primary (foto utama).
- Image validation (JPG, JPEG, PNG, WEBP) & resize via Pillow if available.
"""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import Any, Optional

from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.master import Menu, MenuSchedule
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    get_attachment_file_path,
    list_reference_attachments,
    stage_digital_attachment,
)
from app.utils.clock import now_wib, today_wib

logger = logging.getLogger(__name__)

MODULE = "MENU"
REFERENCE_TYPE = "MENU"
ATTACHMENT_TYPE = "MENU_PHOTO"
MAX_PHOTOS_PER_MENU = 3
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_SIDE = 1600

MEAL_TYPES = ("LUNCH", "DINNER")
MEAL_TYPE_LABELS = {
    "LUNCH": "Siang",
    "DINNER": "Malam",
}
DAY_NAMES_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


class MenuScheduleError(ValueError):
    """Kesalahan pada validasi atau operasi menu / jadwal menu."""


# ---------------------------------------------------------------------------
# FOTO MENU
# ---------------------------------------------------------------------------


def get_menu_photos(menu_id: int) -> list[DigitalAttachment]:
    """Daftar lampiran foto aktif untuk menu tertentu (urut ID ASC, foto 1 = utama)."""
    if not menu_id:
        return []
    return list_reference_attachments(
        module=MODULE,
        reference_type=REFERENCE_TYPE,
        reference_id=menu_id,
    )


def get_primary_menu_photo(menu_id: int) -> Optional[DigitalAttachment]:
    """Foto utama (foto pertama) dari suatu menu jika ada."""
    photos = get_menu_photos(menu_id)
    return photos[0] if photos else None


def _resize_menu_photo_if_pillow(attachment: DigitalAttachment) -> None:
    """Perkecil foto ke sisi terpanjang maksimal 1600px dan koreksi orientasi EXIF."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return

    path = get_attachment_file_path(attachment)
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            if max(width, height) > MAX_IMAGE_SIDE:
                scale = MAX_IMAGE_SIDE / max(width, height)
                new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize(new_size, resample=resample)

            fmt = img.format or "JPEG"
            if fmt.upper() not in ("JPEG", "PNG", "WEBP"):
                fmt = "JPEG"
            img.save(path, format=fmt, quality=85)
    except Exception as exc:
        logger.warning("Gagal mengolah Pillow untuk foto menu %s: %s", attachment.id, exc)


def add_menu_photos(
    menu: Menu,
    files: list[FileStorage],
    acted_by: Optional[int] = None,
    commit: bool = True,
) -> list[DigitalAttachment]:
    """Unggah 1 atau lebih foto untuk menu (maksimal 3 foto total per menu)."""
    valid_files = [f for f in files if f and f.filename and f.filename.strip()]
    if not valid_files:
        return []

    current_photos = get_menu_photos(menu.id)
    if len(current_photos) + len(valid_files) > MAX_PHOTOS_PER_MENU:
        raise MenuScheduleError(
            f"Maksimal {MAX_PHOTOS_PER_MENU} foto per menu. Saat ini sudah ada {len(current_photos)} foto."
        )

    staged_attachments = []
    for file_storage in valid_files:
        ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise MenuScheduleError("Format file harus berupa JPG, JPEG, PNG, atau WEBP.")

        try:
            attachment = stage_digital_attachment(
                file_storage=file_storage,
                module=MODULE,
                reference_type=REFERENCE_TYPE,
                reference_id=menu.id,
                attachment_type=ATTACHMENT_TYPE,
                branch_id=menu.branch_id,
                uploaded_by=acted_by,
                notes=f"Foto menu {menu.menu_name}",
            )
            db.session.flush()
            _resize_menu_photo_if_pillow(attachment)
            staged_attachments.append(attachment)
        except AttachmentValidationError as exc:
            raise MenuScheduleError(str(exc)) from exc

    def _persist():
        db.session.flush()
        return staged_attachments

    if commit:
        with atomic_business_action(
            module=MODULE,
            action="ADD_MENU_PHOTOS",
            description=f"Unggah {len(staged_attachments)} foto untuk menu {menu.menu_name}",
            reference_type=REFERENCE_TYPE,
            reference_id=menu.id,
            user_id=acted_by,
            branch_id=menu.branch_id,
        ):
            return _persist()
    return _persist()


def delete_menu_photo(
    menu: Menu,
    attachment_id: int,
    acted_by: Optional[int] = None,
    commit: bool = True,
) -> bool:
    """Hapus foto menu tertentu (soft-delete pada digital_attachments)."""
    attachment = db.session.get(DigitalAttachment, attachment_id)
    if (
        not attachment
        or attachment.is_deleted
        or attachment.module != MODULE
        or attachment.reference_type != REFERENCE_TYPE
        or attachment.reference_id != menu.id
    ):
        raise MenuScheduleError("Foto menu tidak ditemukan atau tidak sesuai.")

    def _delete():
        attachment.is_deleted = True
        attachment.deleted_at = now_wib()
        attachment.deleted_by = acted_by
        db.session.flush()
        return True

    if commit:
        with atomic_business_action(
            module=MODULE,
            action="DELETE_MENU_PHOTO",
            description=f"Hapus foto attachment {attachment_id} untuk menu {menu.menu_name}",
            reference_type=REFERENCE_TYPE,
            reference_id=menu.id,
            user_id=acted_by,
            branch_id=menu.branch_id,
        ):
            return _delete()
    return _delete()


# ---------------------------------------------------------------------------
# JADWAL MENU (MENU SCHEDULE)
# ---------------------------------------------------------------------------


def get_scheduled_menu(
    branch_id: int,
    menu_date: date,
    meal_type: str,
) -> Optional[MenuSchedule]:
    """Ambil jadwal menu spesifik untuk cabang, tanggal, dan sesi."""
    norm_meal = meal_type.strip().upper()
    if norm_meal not in MEAL_TYPES:
        return None
    return (
        MenuSchedule.query.filter_by(
            branch_id=branch_id,
            menu_date=menu_date,
            meal_type=norm_meal,
        )
        .first()
    )


def save_menu_schedule(
    branch_id: int,
    menu_date: date,
    meal_type: str,
    menu_id: Optional[int],
    notes: Optional[str] = None,
    acted_by: Optional[int] = None,
    commit: bool = True,
) -> Optional[MenuSchedule]:
    """Simpan, ubah, atau hapus jadwal menu per cabang + tanggal + sesi (LUNCH/DINNER)."""
    norm_meal = meal_type.strip().upper()
    if norm_meal not in MEAL_TYPES:
        raise MenuScheduleError(f"Sesi makan harus salah satu dari: {', '.join(MEAL_TYPES)}.")

    def _persist():
        existing = MenuSchedule.query.filter_by(
            branch_id=branch_id,
            menu_date=menu_date,
            meal_type=norm_meal,
        ).first()

        if not menu_id:
            # Kosongkan / hapus jadwal jika menu_id None atau 0
            if existing:
                db.session.delete(existing)
                db.session.flush()
            return None

        menu = db.session.get(Menu, menu_id)
        if not menu or menu.branch_id != branch_id:
            raise MenuScheduleError("Menu tidak ditemukan atau tidak terdaftar pada cabang ini.")

        if existing:
            existing.menu_id = menu.id
            existing.notes = (notes or "").strip() or None
            db.session.flush()
            return existing
        else:
            schedule = MenuSchedule(
                branch_id=branch_id,
                menu_date=menu_date,
                meal_type=norm_meal,
                menu_id=menu.id,
                notes=(notes or "").strip() or None,
            )
            db.session.add(schedule)
            db.session.flush()
            return schedule

    if commit:
        with atomic_business_action(
            module=MODULE,
            action="SAVE_MENU_SCHEDULE",
            description=f"Jadwal menu cabang {branch_id} tanggal {menu_date} sesi {norm_meal}",
            reference_type="MENU_SCHEDULE",
            branch_id=branch_id,
            user_id=acted_by,
        ):
            return _persist()
    return _persist()


def get_monday_of_week(ref_date: Optional[date] = None) -> date:
    """Hitung tanggal Senin untuk minggu dari ref_date (default: hari ini)."""
    ref = ref_date or today_wib()
    return ref - timedelta(days=ref.weekday())


def get_weekly_schedule_matrix(branch_id: int, start_monday: Optional[date] = None) -> dict[str, Any]:
    """Kembalikan matriks jadwal 7 hari (Senin s/d Minggu) untuk tampilan mingguan."""
    monday = get_monday_of_week(start_monday)
    days = []
    dates_list = [monday + timedelta(days=i) for i in range(7)]
    sunday = dates_list[-1]
    today = today_wib()

    # Query semua jadwal dalam rentang 7 hari
    schedules = (
        MenuSchedule.query.filter(
            MenuSchedule.branch_id == branch_id,
            MenuSchedule.menu_date >= monday,
            MenuSchedule.menu_date <= sunday,
        )
        .all()
    )

    sched_map: dict[tuple[date, str], MenuSchedule] = {
        (s.menu_date, s.meal_type): s for s in schedules
    }

    # Ambil semua foto untuk menu-menu yang terjadwal
    menu_ids = {s.menu_id for s in schedules if s.menu_id}
    primary_photos: dict[int, Optional[DigitalAttachment]] = {}
    for mid in menu_ids:
        primary_photos[mid] = get_primary_menu_photo(mid)

    for i, d in enumerate(dates_list):
        lunch_sched = sched_map.get((d, "LUNCH"))
        dinner_sched = sched_map.get((d, "DINNER"))

        days.append({
            "date": d,
            "date_str": d.strftime("%Y-%m-%d"),
            "day_name": DAY_NAMES_ID[i],
            "day_index": i,
            "is_today": (d == today),
            "is_past": (d < today),
            "lunch": {
                "schedule": lunch_sched,
                "menu": lunch_sched.menu if lunch_sched else None,
                "photo": primary_photos.get(lunch_sched.menu_id) if lunch_sched else None,
                "notes": lunch_sched.notes if lunch_sched else None,
            },
            "dinner": {
                "schedule": dinner_sched,
                "menu": dinner_sched.menu if dinner_sched else None,
                "photo": primary_photos.get(dinner_sched.menu_id) if dinner_sched else None,
                "notes": dinner_sched.notes if dinner_sched else None,
            },
        })

    return {
        "start_monday": monday,
        "end_sunday": sunday,
        "prev_monday": monday - timedelta(days=7),
        "next_monday": monday + timedelta(days=7),
        "days": days,
    }


def copy_previous_week_schedule(
    branch_id: int,
    target_monday: date,
    acted_by: Optional[int] = None,
    commit: bool = True,
) -> int:
    """Salin jadwal dari minggu sebelumnya (target_monday - 7 hari) ke minggu target.

    Mengembalikan jumlah slot yang disalin.
    """
    target_mon = get_monday_of_week(target_monday)
    prev_mon = target_mon - timedelta(days=7)
    prev_sun = prev_mon + timedelta(days=6)

    prev_schedules = (
        MenuSchedule.query.filter(
            MenuSchedule.branch_id == branch_id,
            MenuSchedule.menu_date >= prev_mon,
            MenuSchedule.menu_date <= prev_sun,
        )
        .all()
    )

    if not prev_schedules:
        return 0

    def _copy():
        copied_count = 0
        for ps in prev_schedules:
            day_offset = (ps.menu_date - prev_mon).days
            target_date = target_mon + timedelta(days=day_offset)

            existing = MenuSchedule.query.filter_by(
                branch_id=branch_id,
                menu_date=target_date,
                meal_type=ps.meal_type,
            ).first()

            if existing:
                existing.menu_id = ps.menu_id
                existing.notes = ps.notes
            else:
                new_item = MenuSchedule(
                    branch_id=branch_id,
                    menu_date=target_date,
                    meal_type=ps.meal_type,
                    menu_id=ps.menu_id,
                    notes=ps.notes,
                )
                db.session.add(new_item)
            copied_count += 1

        db.session.flush()
        return copied_count

    if commit:
        with atomic_business_action(
            module=MODULE,
            action="COPY_MENU_SCHEDULE_WEEK",
            description=f"Salin jadwal menu cabang {branch_id} dari minggu {prev_mon} ke {target_mon}",
            reference_type="MENU_SCHEDULE",
            branch_id=branch_id,
            user_id=acted_by,
        ):
            return _copy()
    return _copy()


# ---------------------------------------------------------------------------
# TAMPILAN PELANGGAN & PUBLIK
# ---------------------------------------------------------------------------


def get_customer_today_tomorrow_menu(branch_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Ambil informasi menu hari ini dan besok untuk dashboard pelanggan."""
    today = today_wib()
    tomorrow = today + timedelta(days=1)
    target_dates = [today, tomorrow]

    query = MenuSchedule.query.filter(MenuSchedule.menu_date.in_(target_dates))
    if branch_id:
        query = query.filter(MenuSchedule.branch_id == branch_id)

    schedules = query.all()
    sched_map: dict[tuple[date, str], MenuSchedule] = {
        (s.menu_date, s.meal_type): s for s in schedules
    }

    result = []
    for d in target_dates:
        is_today = (d == today)
        for meal in ("LUNCH", "DINNER"):
            sched = sched_map.get((d, meal))
            photo = get_primary_menu_photo(sched.menu_id) if sched else None
            result.append({
                "date": d,
                "date_label": "Hari Ini" if is_today else "Besok",
                "meal_type": meal,
                "meal_label": MEAL_TYPE_LABELS.get(meal, meal),
                "scheduled": bool(sched and sched.menu and sched.menu.is_active),
                "menu_name": sched.menu.menu_name if (sched and sched.menu and sched.menu.is_active) else None,
                "description": sched.menu.description if (sched and sched.menu and sched.menu.is_active) else None,
                "photo_id": photo.id if photo else None,
            })
    return result


def get_public_weekly_menu(branch_id: Optional[int] = None, ref_date: Optional[date] = None) -> list[dict[str, Any]]:
    """Menu minggu ini untuk landing page publik.

    Hanya menampilkan menu AKTIF yang dijadwalkan pada minggu ini.
    Menghasilkan daftar menu unik dengan foto utama, nama, dan sesi.
    """
    monday = get_monday_of_week(ref_date)
    sunday = monday + timedelta(days=6)

    query = (
        MenuSchedule.query.join(Menu, MenuSchedule.menu_id == Menu.id)
        .filter(
            MenuSchedule.menu_date >= monday,
            MenuSchedule.menu_date <= sunday,
            Menu.is_active.is_(True),
        )
    )
    if branch_id:
        query = query.filter(MenuSchedule.branch_id == branch_id)

    schedules = query.order_by(MenuSchedule.menu_date.asc(), MenuSchedule.meal_type.asc()).all()

    seen_menus: dict[int, dict[str, Any]] = {}
    for s in schedules:
        menu = s.menu
        if not menu or not menu.is_active:
            continue
        if menu.id not in seen_menus:
            photo = get_primary_menu_photo(menu.id)
            seen_menus[menu.id] = {
                "id": menu.id,
                "menu_name": menu.menu_name,
                "description": menu.description or "",
                "photo_id": photo.id if photo else None,
                "schedule_days": set(),
                "meal_types": set(),
            }
        day_idx = (s.menu_date - monday).days
        if 0 <= day_idx < 7:
            seen_menus[menu.id]["schedule_days"].add(DAY_NAMES_ID[day_idx])
        seen_menus[menu.id]["meal_types"].add(MEAL_TYPE_LABELS.get(s.meal_type, s.meal_type))

    items = []
    for item in seen_menus.values():
        items.append({
            "id": item["id"],
            "menu_name": item["menu_name"],
            "description": item["description"],
            "photo_id": item["photo_id"],
            "days_label": ", ".join(sorted(item["schedule_days"])),
            "meals_label": " & ".join(sorted(item["meal_types"])),
        })
    return items


def build_menu_schedule_json_for_order(branch_id: int, days_ahead: int = 14) -> dict[str, dict[str, Any]]:
    """Peta JSON { 'YYYY-MM-DD_LUNCH': { 'name': ..., 'description': ..., 'photo_id': ... } } untuk order draft."""
    today = today_wib()
    end_date = today + timedelta(days=days_ahead)

    schedules = (
        MenuSchedule.query.join(Menu, MenuSchedule.menu_id == Menu.id)
        .filter(
            MenuSchedule.branch_id == branch_id,
            MenuSchedule.menu_date >= today,
            MenuSchedule.menu_date <= end_date,
            Menu.is_active.is_(True),
        )
        .all()
    )

    data = {}
    for s in schedules:
        photo = get_primary_menu_photo(s.menu_id)
        key = f"{s.menu_date.strftime('%Y-%m-%d')}_{s.meal_type}"
        data[key] = {
            "name": s.menu.menu_name,
            "menu_name": s.menu.menu_name,
            "description": s.menu.description or "",
            "photo_id": photo.id if photo else None,
        }
    return data
