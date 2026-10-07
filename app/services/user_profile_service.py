"""Layanan profil user dan foto avatar (Bagian 1).

- Mengelola data diri user (nama lengkap, no hp, alamat, email).
- Mengelola upload, resize/crop tengah, dan hapus foto profil avatar.
- Mengelola ganti password sendiri dengan validasi aturan keamanan.
- Hak akses melihat avatar terisolasi per branch / portal user.
- Semua mutasi dicatat dalam audit log dan dieksekusi lewat atomic_business_action.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.master import User
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    get_attachment_file_path,
    stage_digital_attachment,
)
from app.services.user_management_service import (
    clean_text,
    email_is_used,
    is_valid_email_format,
    normalize_email,
    validate_password_pair,
)
from app.utils.roles import effective_role

logger = logging.getLogger(__name__)

MODULE = "USER"
REFERENCE_TYPE = "USER_AVATAR"
ATTACHMENT_TYPE = "AVATAR_PHOTO"
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
INTERNAL_STAFF_ROLES = (
    "OWNER",
    "ADMIN",
    "FINANCE",
    "ACCOUNTING",
    "LOGISTICS",
    "HR",
    "DAPUR",
    "PENGANTAR",
    "CUSTOMER_SUCCESS",
)


class UserProfileError(ValueError):
    """Kesalahan pada validasi atau pemrosesan profil pengguna."""


def can_view_avatar(viewer: Optional[User], target_user: Optional[User]) -> bool:
    """Periksa apakah viewer berhak melihat avatar target_user."""
    if not viewer or not getattr(viewer, "is_authenticated", False) or not target_user:
        return False

    # Pemilik akun selalu berhak melihat foto profilnya sendiri
    if viewer.id == target_user.id:
        return True

    viewer_role = effective_role(getattr(viewer, "role", None))

    # OWNER dan ADMIN berhak melihat semua foto profil
    if viewer_role in ("OWNER", "ADMIN"):
        return True

    # Staf internal hanya berhak melihat foto rekan dalam cabang yang sama
    if viewer_role in INTERNAL_STAFF_ROLES:
        return getattr(viewer, "branch_id", None) == getattr(target_user, "branch_id", None)

    # Akun portal tidak berhak melihat foto profil akun lain
    return False


def _crop_square_and_shrink(attachment: DigitalAttachment) -> None:
    """Crop tengah foto profil menjadi persegi dan resize jika melebihi 512px."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return

    path = get_attachment_file_path(attachment)
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            w, h = image.size
            min_dim = min(w, h)
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            image = image.crop((left, top, left + min_dim, top + min_dim))
            if min_dim > 512:
                image.thumbnail((512, 512))
            fmt = "PNG" if path.suffix.lower() == ".png" else ("WEBP" if path.suffix.lower() == ".webp" else "JPEG")
            if fmt == "JPEG" and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(path, fmt, quality=85, optimize=True)
    except Exception as error:  # noqa: BLE001
        raise UserProfileError("File foto tidak bisa dibaca sebagai gambar. Pilih foto JPG/PNG/WEBP lain.") from error

    data = path.read_bytes()
    attachment.file_size = len(data)
    attachment.sha256_hash = hashlib.sha256(data).hexdigest()


def _discard_attachment_file(attachment: Optional[DigitalAttachment]) -> None:
    """Hapus file fisik lampiran jika transaksi batal."""
    if not attachment:
        return
    try:
        get_attachment_file_path(attachment).unlink(missing_ok=True)
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("Gagal menghapus file avatar fisik: %s", getattr(attachment, "stored_filename", ""))


def upload_user_avatar(user: User, file_storage, *, uploaded_by: Optional[int] = None) -> DigitalAttachment:
    """Unggah dan perbarui foto profil pengguna."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise UserProfileError("Pilih file foto profil terlebih dahulu.")

    filename = file_storage.filename
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in IMAGE_EXTENSIONS:
        raise UserProfileError("Foto profil harus berupa gambar JPG, JPEG, PNG, atau WEBP.")

    with atomic_business_action(
        module="USER",
        action="UPDATE_AVATAR",
        description=f"Foto profil diunggah untuk {user.username}",
        reference_type="USER",
        reference_id=user.id,
        user_id=uploaded_by or user.id,
        branch_id=user.branch_id,
    ):
        try:
            attachment = stage_digital_attachment(
                file_storage=file_storage,
                module=MODULE,
                reference_type=REFERENCE_TYPE,
                reference_id=user.id,
                attachment_type=ATTACHMENT_TYPE,
                branch_id=user.branch_id,
                uploaded_by=uploaded_by or user.id,
                notes=f"Foto profil {user.username}",
            )
        except AttachmentValidationError as err:
            raise UserProfileError(str(err)) from err

        try:
            _crop_square_and_shrink(attachment)
        except Exception:
            _discard_attachment_file(attachment)
            raise

        old_avatar_id = user.avatar_attachment_id
        if old_avatar_id:
            old_attachment = db.session.get(DigitalAttachment, old_avatar_id)
            if old_attachment:
                old_attachment.is_deleted = True

        db.session.flush()
        user.avatar_attachment_id = attachment.id

    return attachment


def delete_user_avatar(user: User, *, deleted_by: Optional[int] = None) -> bool:
    """Hapus foto profil pengguna dan reset ke inisial."""
    if not user.avatar_attachment_id:
        return False

    with atomic_business_action(
        module="USER",
        action="DELETE_AVATAR",
        description=f"Foto profil dihapus untuk {user.username}",
        reference_type="USER",
        reference_id=user.id,
        user_id=deleted_by or user.id,
        branch_id=user.branch_id,
    ):
        attachment = db.session.get(DigitalAttachment, user.avatar_attachment_id)
        if attachment:
            attachment.is_deleted = True
        user.avatar_attachment_id = None

    return True


def update_user_profile(user: User, form: dict, *, is_portal: bool = False) -> None:
    """Perbarui informasi data diri pengguna (nama, no hp, alamat, email).

    Username, role, dan branch_id tidak dapat diubah melalui fungsi ini.
    Mengubah email mewajibkan verifikasi password saat ini.
    """
    full_name = clean_text(form.get("full_name"))
    if not full_name:
        raise UserProfileError("Nama lengkap wajib diisi.")

    phone = clean_text(form.get("phone")) or None
    address = clean_text(form.get("address")) or None

    new_email = normalize_email(form.get("email"))
    current_email = normalize_email(user.email)

    if is_portal and not new_email:
        raise UserProfileError("Email wajib diisi untuk akun portal.")

    if new_email:
        if not is_valid_email_format(new_email):
            raise UserProfileError("Format email tidak valid.")
        if email_is_used(new_email, exclude_id=user.id):
            raise UserProfileError("Email ini sudah dipakai akun lain.")

    if new_email != current_email:
        current_password = form.get("current_password") or ""
        if not check_password_hash(user.password_hash, current_password):
            raise UserProfileError("Password saat ini tidak sesuai untuk mengubah email.")

    old_values = {
        "full_name": user.full_name,
        "phone": user.phone,
        "address": user.address,
        "email": user.email,
    }
    new_values = {
        "full_name": full_name,
        "phone": phone,
        "address": address,
        "email": new_email or None,
    }

    with atomic_business_action(
        module="USER",
        action="UPDATE_PROFILE",
        description=f"Data profil user {user.username} diperbarui",
        reference_type="USER",
        reference_id=user.id,
        user_id=user.id,
        branch_id=user.branch_id,
        metadata={"old_values": old_values, "new_values": new_values},
    ):
        user.full_name = full_name
        user.phone = phone
        user.address = address
        user.email = new_email or None


def change_user_password(user: User, form: dict) -> None:
    """Ubah password user sendiri."""
    current_password = form.get("current_password") or ""
    password = form.get("password") or ""
    password_confirmation = form.get("password_confirmation") or ""

    if not check_password_hash(user.password_hash, current_password):
        raise UserProfileError("Password lama tidak sesuai.")

    valid, error = validate_password_pair(password, password_confirmation)
    if not valid:
        raise UserProfileError(error or "Password tidak valid.")

    if check_password_hash(user.password_hash, password):
        raise UserProfileError("Password baru tidak boleh sama dengan password lama.")

    with atomic_business_action(
        module="AUTH",
        action="PASSWORD_CHANGED",
        description=f"User {user.username} mengganti password sendiri.",
        reference_type="USER",
        reference_id=user.id,
        user_id=user.id,
        branch_id=user.branch_id,
    ):
        user.password_hash = generate_password_hash(password)
