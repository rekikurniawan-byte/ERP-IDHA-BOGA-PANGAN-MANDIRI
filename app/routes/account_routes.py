"""Routes for user account and profile photos."""
from __future__ import annotations

from flask import Blueprint, abort, send_file
from flask_login import current_user, login_required

from app.extensions import db
from app.models.master import User
from app.models.system import DigitalAttachment
from app.services.digital_attachment_service import get_attachment_file_path, is_inline_view_safe
from app.services.user_profile_service import MODULE, REFERENCE_TYPE, can_view_avatar

account_bp = Blueprint("account", __name__, url_prefix="/account")


@account_bp.route("/avatar/<int:user_id>")
@login_required
def avatar(user_id: int):
    """Sajikan foto profil pengguna dengan verifikasi hak akses."""
    user = db.session.get(User, user_id)
    if not user or not user.avatar_attachment_id:
        abort(404)
    if not can_view_avatar(current_user, user):
        abort(403)
    attachment = db.session.get(DigitalAttachment, user.avatar_attachment_id)
    if (
        not attachment
        or attachment.is_deleted
        or attachment.module != MODULE
        or attachment.reference_type != REFERENCE_TYPE
        or not is_inline_view_safe(attachment)
    ):
        abort(404)
    try:
        path = get_attachment_file_path(attachment)
    except FileNotFoundError:
        abort(404)
    response = send_file(str(path), mimetype=attachment.mime_type or "image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response
