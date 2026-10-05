"""Foto lokasi antar (keputusan owner 2026-10-05).

- Setiap lokasi antar punya 1 foto wajib (titik serah terima) + sampai 2 foto
  tambahan (gerbang, jalan masuk, pos). Lokasi baru wajib berfoto; lokasi lama
  tanpa foto hanya diberi peringatan, pesanan tetap jalan.
- Pengunggah: pemilik lokasi (pelanggan/mandor lewat Alamat Saya), ADMIN/OWNER
  (Data Master), dan PENGANTAR (saat serah terima).
- File disimpan lewat lampiran digital (di luar folder static). Bila Pillow
  terpasang, foto diputar sesuai EXIF dan diperkecil ke sisi terpanjang 1600 px.
"""
from __future__ import annotations

import hashlib

from app.extensions import db
from app.models.system import DigitalAttachment
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    get_attachment_file_path,
    list_reference_attachments,
    soft_delete_attachment,
    stage_digital_attachment,
)

MODULE = "LOCATION"
REFERENCE_TYPE = "DELIVERY_LOCATION"
ATTACHMENT_TYPE = "LOCATION_PHOTO"
MAX_PHOTOS = 3
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_SIDE = 1600
INTERNAL_MANAGERS = ("OWNER", "ADMIN", "PENGANTAR")


class LocationPhotoError(ValueError):
    pass


def location_photos(location_id):
    if not location_id:
        return []
    return list_reference_attachments(module=MODULE, reference_type=REFERENCE_TYPE, reference_id=location_id)


def photo_counts(location_ids):
    """{location_id: jumlah foto aktif} untuk banyak lokasi sekaligus."""
    ids = [int(i) for i in location_ids if i]
    if not ids:
        return {}
    rows = (
        db.session.query(DigitalAttachment.reference_id, db.func.count(DigitalAttachment.id))
        .filter(
            DigitalAttachment.module == MODULE,
            DigitalAttachment.reference_type == REFERENCE_TYPE,
            DigitalAttachment.reference_id.in_(ids),
            DigitalAttachment.is_deleted.is_(False),
        )
        .group_by(DigitalAttachment.reference_id)
        .all()
    )
    return {reference_id: count for reference_id, count in rows}


def first_photo_ids(location_ids):
    """{location_id: id foto pertama} untuk gambar mini di daftar/kartu."""
    ids = [int(i) for i in location_ids if i]
    if not ids:
        return {}
    rows = (
        DigitalAttachment.query.filter(
            DigitalAttachment.module == MODULE,
            DigitalAttachment.reference_type == REFERENCE_TYPE,
            DigitalAttachment.reference_id.in_(ids),
            DigitalAttachment.is_deleted.is_(False),
        )
        .order_by(DigitalAttachment.created_at.asc(), DigitalAttachment.id.asc())
        .all()
    )
    result = {}
    for row in rows:
        result.setdefault(row.reference_id, row.id)
    return result


def _incoming_files(files):
    return [f for f in (files or []) if f is not None and getattr(f, "filename", "")]


def _shrink_image(attachment):
    """Putar sesuai EXIF dan perkecil foto besar. Tanpa Pillow: dibiarkan."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return
    path = get_attachment_file_path(attachment)
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            if max(image.size) <= MAX_SIDE and image.format in ("JPEG", "WEBP"):
                return
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            fmt = "PNG" if path.suffix.lower() == ".png" else ("WEBP" if path.suffix.lower() == ".webp" else "JPEG")
            if fmt == "JPEG" and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(path, fmt, quality=82, optimize=True)
    except Exception as error:  # noqa: BLE001 - file rusak/bukan gambar
        raise LocationPhotoError("File foto tidak bisa dibaca sebagai gambar. Pilih foto JPG/PNG/WEBP lain.") from error
    data = path.read_bytes()
    attachment.file_size = len(data)
    attachment.sha256_hash = hashlib.sha256(data).hexdigest()


def stage_location_photos(location, files, *, uploaded_by, branch_id, required=False, note=None):
    """Simpan foto baru untuk lokasi (sudah punya id). Tidak commit."""
    files = _incoming_files(files)
    existing = len(location_photos(location.id)) if location.id else 0
    if required and not files and not existing:
        raise LocationPhotoError("Foto lokasi antar wajib diunggah (minimal 1 foto titik serah terima).")
    if existing + len(files) > MAX_PHOTOS:
        raise LocationPhotoError(f"Maksimal {MAX_PHOTOS} foto per lokasi. Hapus foto lama dulu bila ingin mengganti.")
    for file_storage in files:
        extension = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
        if extension not in IMAGE_EXTENSIONS:
            raise LocationPhotoError("Foto lokasi harus berupa gambar JPG, PNG, atau WEBP.")
    staged = []
    try:
        for file_storage in files:
            try:
                attachment = stage_digital_attachment(
                    file_storage=file_storage,
                    module=MODULE,
                    reference_type=REFERENCE_TYPE,
                    reference_id=location.id,
                    attachment_type=ATTACHMENT_TYPE,
                    branch_id=branch_id,
                    uploaded_by=uploaded_by,
                    notes=note or f"Foto lokasi {location.location_name}",
                )
            except AttachmentValidationError as error:
                raise LocationPhotoError(str(error)) from error
            staged.append(attachment)
            _shrink_image(attachment)
    except Exception:
        discard_files(staged)
        raise
    return staged


def discard_files(staged):
    """Hapus file fisik foto yang batal disimpan (transaksi gagal)."""
    for attachment in staged:
        try:
            get_attachment_file_path(attachment).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - file mungkin belum/tidak ada
            pass


def can_manage(user, location):
    """OWNER/ADMIN/PENGANTAR cabang itu, atau akun portal yang memesan untuk lokasi ini."""
    from app.utils.roles import effective_role

    role = effective_role(getattr(user, "role", None))
    mandor = getattr(location, "mandor", None)
    if role in INTERNAL_MANAGERS:
        return bool(mandor) and mandor.branch_id == getattr(user, "branch_id", None)
    if role and role.startswith("PORTAL_"):
        from app.services.portal_mapping_service import build_portal_external_scope
        from app.services.portal_order_draft_service import orderable_location_ids

        return location.id in orderable_location_ids(user, build_portal_external_scope(user))
    return False


def can_view(user, location):
    from app.utils.roles import effective_role

    role = effective_role(getattr(user, "role", None))
    mandor = getattr(location, "mandor", None)
    if role and not role.startswith("PORTAL_"):
        return bool(mandor) and mandor.branch_id == getattr(user, "branch_id", None)
    from app.services.portal_mapping_service import build_portal_external_scope

    scope = build_portal_external_scope(user)
    return scope.allowed and location.id in scope.delivery_location_ids


def add_photos(user, location, files):
    """Tambah foto dari halaman (Alamat Saya, Data Master, pengantar). Commit."""
    from app.services.audit_log_service import record_audit_log

    if not can_manage(user, location):
        raise LocationPhotoError("Anda tidak berhak mengubah foto lokasi ini.")
    if not _incoming_files(files):
        raise LocationPhotoError("Pilih foto yang akan diunggah.")
    staged = stage_location_photos(location, files, uploaded_by=user.id, branch_id=location.mandor.branch_id)
    db.session.flush()
    record_audit_log(
        module="LOCATION",
        event_type="LOCATION_PHOTO_ADDED",
        action="CREATE",
        table_name="delivery_locations",
        record_id=location.id,
        description=f"{len(staged)} foto ditambahkan ke lokasi {location.location_name}.",
        metadata={"attachment_ids": [a.id for a in staged]},
        user_id=user.id,
        branch_id=location.mandor.branch_id,
        commit=False,
    )
    _commit(staged)
    return staged


def remove_photo(user, location, attachment_id):
    if not can_manage(user, location):
        raise LocationPhotoError("Anda tidak berhak mengubah foto lokasi ini.")
    photos = location_photos(location.id)
    target = next((p for p in photos if p.id == attachment_id), None)
    if not target:
        raise LocationPhotoError("Foto tidak ditemukan.")
    if len(photos) <= 1:
        raise LocationPhotoError("Foto terakhir tidak bisa dihapus: lokasi wajib punya minimal 1 foto. Unggah foto pengganti dulu.")
    soft_delete_attachment(target, deleted_by=user.id, note="Foto lokasi dihapus pemilik/admin")
    return target


def _commit(staged):
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        discard_files(staged)
        raise
