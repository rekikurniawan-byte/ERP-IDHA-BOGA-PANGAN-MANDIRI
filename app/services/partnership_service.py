"""Pengajuan kerja sama katering proyek/perusahaan.

Calon klien mengisi formulir di halaman publik /kerja-sama/ajukan. Pengajuan
masuk ke OWNER dan ADMIN (notifikasi + daftar Pelanggan > Pengajuan Kerja
Sama) untuk dihubungi, disurvei, diberi penawaran, lalu dibuatkan kontrak.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from uuid import uuid4

from app.extensions import db
from app.models.master import Branch, User
from app.models.partnership import PartnershipRequest
from app.services.geo_service import GeoError, parse_coordinates

STATUS_NEW = "NEW"
STATUS_CONTACTED = "CONTACTED"
STATUS_SURVEY = "SURVEY"
STATUS_OFFERED = "OFFERED"
STATUS_WON = "WON"
STATUS_LOST = "LOST"
STATUS_LABELS = {
    STATUS_NEW: "Baru masuk",
    STATUS_CONTACTED: "Sudah dihubungi",
    STATUS_SURVEY: "Survei lokasi",
    STATUS_OFFERED: "Penawaran dikirim",
    STATUS_WON: "Jadi kontrak",
    STATUS_LOST: "Tidak lanjut",
}
STATUS_TONES = {
    STATUS_NEW: "warning",
    STATUS_CONTACTED: "info",
    STATUS_SURVEY: "info",
    STATUS_OFFERED: "info",
    STATUS_WON: "success",
    STATUS_LOST: "muted",
}
OPEN_STATUSES = (STATUS_NEW, STATUS_CONTACTED, STATUS_SURVEY, STATUS_OFFERED)

MEAL_LABELS = {"LUNCH": "Makan siang", "DINNER": "Makan sore", "BOTH": "Siang & sore"}
PAYMENT_LABELS = {
    "MONTHLY": "Tagihan bulanan",
    "BIWEEKLY": "Tagihan per 2 minggu",
    "WEEKLY": "Tagihan mingguan",
    "UNDECIDED": "Belum tahu, minta saran",
}

PHONE_PATTERN = re.compile(r"^[0-9+()\-\s]{8,20}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PartnershipError(ValueError):
    pass


def _clean(value, limit=None):
    text = str(value or "").strip()
    return text[:limit] if limit else text


def _positive_int(value, label, *, maximum):
    text = _clean(value).replace(".", "")
    if not text:
        return None
    try:
        number = int(text)
    except ValueError:
        raise PartnershipError(f"{label} harus angka bulat.")
    if number <= 0 or number > maximum:
        raise PartnershipError(f"{label} harus antara 1 dan {maximum:,}.".replace(",", "."))
    return number


def _start_date(value, today):
    text = _clean(value)
    if not text:
        return None
    try:
        start = date.fromisoformat(text)
    except ValueError:
        raise PartnershipError("Tanggal mulai tidak valid.")
    if start < today:
        raise PartnershipError("Tanggal mulai tidak boleh sebelum hari ini.")
    return start


def _new_number(today):
    for _ in range(10):
        number = f"KS-{today:%y%m%d}-{uuid4().hex[:4].upper()}"
        if not PartnershipRequest.query.filter_by(request_number=number).first():
            return number
    raise PartnershipError("Nomor pengajuan gagal dibuat. Coba kirim ulang.")


def _main_branch_id():
    branch = Branch.query.filter_by(is_active=True).order_by(Branch.id.asc()).first()
    return branch.id if branch else None


def validate_partnership_form(form, today=None):
    today = today or date.today()
    company = _clean(form.get("company_name"), 150)
    contact = _clean(form.get("contact_name"), 150)
    phone = _clean(form.get("phone"), 40)
    email = _clean(form.get("email"), 150)
    project = _clean(form.get("project_name"), 150)
    if not company:
        raise PartnershipError("Nama perusahaan wajib diisi.")
    if not contact:
        raise PartnershipError("Nama yang bisa dihubungi wajib diisi.")
    if not phone or not PHONE_PATTERN.match(phone):
        raise PartnershipError("Nomor HP/WhatsApp wajib diisi dengan benar (8-20 angka).")
    if email and not EMAIL_PATTERN.match(email):
        raise PartnershipError("Format email tidak valid.")
    if not project:
        raise PartnershipError("Nama proyek atau lokasi kerja wajib diisi.")
    try:
        latitude, longitude = parse_coordinates(form.get("latitude"), form.get("longitude"))
    except GeoError as exc:
        raise PartnershipError(str(exc)) from exc
    address = _clean(form.get("project_address"), 2000)
    if not address and latitude is None:
        raise PartnershipError("Isi alamat proyek atau tandai titik lokasinya di peta.")
    meals = _clean(form.get("meals")).upper() or "LUNCH"
    if meals not in MEAL_LABELS:
        raise PartnershipError("Pilih waktu makan yang dibutuhkan.")
    payment = _clean(form.get("payment_preference")).upper() or "UNDECIDED"
    if payment not in PAYMENT_LABELS:
        raise PartnershipError("Pilih cara penagihan yang diinginkan.")
    return {
        "company_name": company,
        "contact_name": contact,
        "contact_role": _clean(form.get("contact_role"), 100) or None,
        "phone": phone,
        "email": email or None,
        "project_name": project,
        "project_address": address or None,
        "latitude": latitude,
        "longitude": longitude,
        "workers_count": _positive_int(form.get("workers_count"), "Jumlah pekerja", maximum=100000),
        "portions_per_day": _positive_int(form.get("portions_per_day"), "Perkiraan porsi per hari", maximum=100000),
        "meals": meals,
        "start_date": _start_date(form.get("start_date"), today),
        "duration_months": _positive_int(form.get("duration_months"), "Lama kontrak (bulan)", maximum=120),
        "payment_preference": payment,
        "notes": _clean(form.get("notes"), 4000) or None,
    }


def submit_partnership_request(form, *, source_ip=None, today=None):
    """Simpan pengajuan + beri tahu OWNER & ADMIN. Commit."""
    from flask import url_for

    from app.services.audit_log_service import record_audit_log
    from app.services.notification_service import create_or_update_notification

    today = today or date.today()
    payload = validate_partnership_form(form, today)
    branch_id = _main_branch_id()
    request_row = PartnershipRequest(
        branch_id=branch_id,
        request_number=_new_number(today),
        status=STATUS_NEW,
        source_ip=_clean(source_ip, 64) or None,
        **payload,
    )
    db.session.add(request_row)
    db.session.flush()
    if branch_id:
        portions = f", ± {request_row.portions_per_day} porsi/hari" if request_row.portions_per_day else ""
        for role in ("OWNER", "ADMIN"):
            create_or_update_notification(
                branch_id=branch_id,
                notification_type="PARTNERSHIP_REQUEST",
                title=f"Pengajuan kerja sama: {request_row.company_name}"[:150],
                message=(
                    f"{request_row.contact_name} ({request_row.phone}) mengajukan katering untuk "
                    f"{request_row.project_name}{portions}. Segera hubungi untuk tindak lanjut."
                ),
                target_role=role,
                priority="HIGH",
                reference_type="PARTNERSHIP_REQUEST",
                reference_id=request_row.id,
                action_url=url_for("customer_success.partnership_detail", request_id=request_row.id),
                generated_key=f"partnership:{request_row.id}:{role}",
                commit=False,
            )
        record_audit_log(
            module="CUSTOMER_SUCCESS",
            event_type="PARTNERSHIP_REQUEST_SUBMITTED",
            action="CREATE",
            table_name="partnership_requests",
            record_id=request_row.id,
            description=f"Pengajuan kerja sama {request_row.request_number} dari {request_row.company_name}.",
            branch_id=branch_id,
            commit=False,
        )
    db.session.commit()
    return request_row


def list_partnership_requests(branch_id, status=None, search=None):
    query = PartnershipRequest.query.filter(
        (PartnershipRequest.branch_id == branch_id) | (PartnershipRequest.branch_id.is_(None))
    )
    if status == "OPEN":
        query = query.filter(PartnershipRequest.status.in_(OPEN_STATUSES))
    elif status in STATUS_LABELS:
        query = query.filter(PartnershipRequest.status == status)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            PartnershipRequest.company_name.ilike(like)
            | PartnershipRequest.project_name.ilike(like)
            | PartnershipRequest.contact_name.ilike(like)
            | PartnershipRequest.request_number.ilike(like)
        )
    return query.order_by(PartnershipRequest.created_at.desc()).all()


def partnership_summary(branch_id):
    rows = list_partnership_requests(branch_id)
    counts = {key: 0 for key in STATUS_LABELS}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    week_ago = datetime.utcnow() - timedelta(days=7)
    return {
        "total": len(rows),
        "open": sum(counts[key] for key in OPEN_STATUSES),
        "new": counts[STATUS_NEW],
        "won": counts[STATUS_WON],
        "this_week": sum(1 for row in rows if row.created_at and row.created_at >= week_ago),
        "portions_open": sum(row.portions_per_day or 0 for row in rows if row.status in OPEN_STATUSES),
        "counts": counts,
    }


def get_partnership_request(request_id, branch_id):
    row = db.session.get(PartnershipRequest, request_id)
    if not row or (row.branch_id not in (None, branch_id)):
        return None
    return row


def update_partnership_request(request_id, *, branch_id, status, note, user_id):
    from app.services.audit_log_service import record_audit_log

    row = get_partnership_request(request_id, branch_id)
    if not row:
        raise PartnershipError("Pengajuan kerja sama tidak ditemukan.")
    status = _clean(status).upper() or row.status
    if status not in STATUS_LABELS:
        raise PartnershipError("Status tindak lanjut tidak dikenal.")
    note = _clean(note, 2000)
    if status == row.status and not note:
        raise PartnershipError("Tulis catatan tindak lanjut atau ubah statusnya.")
    user = db.session.get(User, user_id) if user_id else None
    now = datetime.utcnow()
    stamp = (now + timedelta(hours=7)).strftime("%d/%m/%Y %H.%M")
    who = getattr(user, "full_name", None) or getattr(user, "username", None) or "Petugas"
    change = f"{STATUS_LABELS[row.status]} → {STATUS_LABELS[status]}" if status != row.status else STATUS_LABELS[status]
    entry = f"[{stamp} WIB] {who} ({change}){': ' + note if note else ''}"
    before = row.status
    row.follow_up_notes = f"{entry}\n{row.follow_up_notes}" if row.follow_up_notes else entry
    row.status = status
    row.handled_by = user_id
    row.handled_at = now
    record_audit_log(
        module="CUSTOMER_SUCCESS",
        event_type="PARTNERSHIP_REQUEST_FOLLOW_UP",
        action="UPDATE",
        table_name="partnership_requests",
        record_id=row.id,
        description=f"Tindak lanjut {row.request_number}: {change}.",
        old_value={"status": before},
        new_value={"status": status},
        user_id=user_id,
        branch_id=branch_id,
        commit=False,
    )
    if status not in OPEN_STATUSES:
        from app.models.system import Notification

        Notification.query.filter(
            Notification.reference_type == "PARTNERSHIP_REQUEST",
            Notification.reference_id == row.id,
            Notification.status.in_(("UNREAD", "READ")),
        ).update({"status": "RESOLVED", "resolved_at": now}, synchronize_session=False)
    db.session.commit()
    return row


def follow_up_entries(row):
    return [line for line in (row.follow_up_notes or "").splitlines() if line.strip()]
