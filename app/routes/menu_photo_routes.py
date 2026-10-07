"""Routes for serving menu photos with access control."""
from __future__ import annotations

from flask import Blueprint, abort, send_file
from flask_login import current_user

from app.extensions import db
from app.models.master import Menu
from app.models.system import DigitalAttachment
from app.services.digital_attachment_service import get_attachment_file_path, is_inline_view_safe
from app.services.menu_schedule_service import MODULE, REFERENCE_TYPE
from app.utils.roles import effective_role

menu_photo_bp = Blueprint("menu_photos", __name__, url_prefix="/menu-photos")


def can_view_menu_photo(user, menu: Menu) -> bool:
    """Verifikasi hak akses melihat foto menu.

    - Pengguna publik / anonim: hanya boleh melihat foto menu yang AKTIF (untuk landing page).
    - Pelanggan portal: hanya boleh melihat menu yang AKTIF.
    - Staf internal (OWNER, ADMIN): boleh melihat semua menu.
    - Staf cabang (DAPUR, PENGANTAR): boleh melihat menu di cabangnya.
    """
    if not menu:
        return False

    if not user or not getattr(user, "is_authenticated", False):
        return bool(menu.is_active)

    role = effective_role(getattr(user, "role", None))
    if role in ("OWNER", "ADMIN"):
        return True

    if role.startswith("PORTAL_"):
        return bool(menu.is_active)

    # Staf cabang
    return user.branch_id == menu.branch_id or bool(menu.is_active)


@menu_photo_bp.route("/<int:attachment_id>", endpoint="view")
@menu_photo_bp.route("/<int:attachment_id>", endpoint="view_photo")
def view(attachment_id: int):
    """Sajikan foto menu dengan validasi keamanan dan hak akses."""
    attachment = db.session.get(DigitalAttachment, attachment_id)
    if (
        not attachment
        or attachment.is_deleted
        or attachment.module != MODULE
        or attachment.reference_type != REFERENCE_TYPE
        or not is_inline_view_safe(attachment)
    ):
        abort(404)

    menu = db.session.get(Menu, attachment.reference_id)
    if not menu or not can_view_menu_photo(current_user, menu):
        abort(403)

    try:
        path = get_attachment_file_path(attachment)
    except FileNotFoundError:
        abort(404)

    response = send_file(str(path), mimetype=attachment.mime_type or "image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "private, max-age=600"
    return response
