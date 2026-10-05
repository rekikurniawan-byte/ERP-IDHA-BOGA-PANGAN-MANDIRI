"""Foto lokasi antar: lihat, tambah, hapus (pemilik lokasi, admin, pengantar)."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.master import DeliveryLocation
from app.models.system import DigitalAttachment
from app.services.digital_attachment_service import get_attachment_file_path, is_inline_view_safe
from app.services.location_photo_service import (
    MODULE,
    REFERENCE_TYPE,
    LocationPhotoError,
    add_photos,
    can_view,
    remove_photo,
)

location_photo_bp = Blueprint("location_photos", __name__, url_prefix="/location-photos")


def _back(default_endpoint="dashboard.index"):
    target = (request.form.get("next") or request.args.get("next") or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(url_for(default_endpoint))


def _location_or_404(location_id):
    location = db.session.get(DeliveryLocation, location_id)
    if not location or not location.mandor:
        abort(404)
    return location


@location_photo_bp.route("/<int:attachment_id>")
@login_required
def view(attachment_id):
    attachment = db.session.get(DigitalAttachment, attachment_id)
    if not attachment or attachment.is_deleted or attachment.module != MODULE or attachment.reference_type != REFERENCE_TYPE:
        abort(404)
    location = _location_or_404(attachment.reference_id)
    if not can_view(current_user, location) or not is_inline_view_safe(attachment):
        abort(403)
    try:
        path = get_attachment_file_path(attachment)
    except FileNotFoundError:
        abort(404)
    response = send_file(str(path), mimetype=attachment.mime_type or "image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@location_photo_bp.route("/locations/<int:location_id>/add", methods=["POST"])
@login_required
def add(location_id):
    location = _location_or_404(location_id)
    try:
        photos = add_photos(current_user, location, request.files.getlist("location_photos"))
        flash(f"{len(photos)} foto lokasi {location.location_name} tersimpan.", "success")
    except LocationPhotoError as error:
        flash(str(error), "warning")
    return _back()


@location_photo_bp.route("/<int:attachment_id>/delete", methods=["POST"])
@login_required
def delete(attachment_id):
    attachment = db.session.get(DigitalAttachment, attachment_id)
    if not attachment or attachment.module != MODULE:
        abort(404)
    location = _location_or_404(attachment.reference_id)
    try:
        remove_photo(current_user, location, attachment_id)
        flash("Foto lokasi dihapus.", "success")
    except LocationPhotoError as error:
        flash(str(error), "warning")
    return _back()
