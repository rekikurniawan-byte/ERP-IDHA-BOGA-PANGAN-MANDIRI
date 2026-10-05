from datetime import datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import PortalUserMapping
from app.services.geo_service import GeoError, parse_accuracy, parse_coordinates
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_DELEGATE
from app.services.pricing_service import PATH_GENERAL, active_zones
from app.services.user_management_service import (
    ROLE_PORTAL_CUSTOMER,
    normalize_username,
    username_is_used,
    validate_password_pair,
)


def _clean(value):
    return (value or "").strip()


def _require(value, message):
    cleaned = _clean(value)
    if not cleaned:
        raise ValueError(message)
    return cleaned


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_active_branch(branch_id_raw):
    try:
        branch_id = int(branch_id_raw)
    except (TypeError, ValueError):
        branch_id = None

    if branch_id:
        branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
    else:
        branch = Branch.query.filter_by(is_active=True).order_by(Branch.id.asc()).first()

    if not branch:
        raise ValueError("Cabang belum tersedia. Hubungi admin.")
    return branch


def _new_client_code():
    for _ in range(10):
        code = f"CUST-{uuid4().hex[:10].upper()}"
        if not Client.query.filter_by(client_code=code).first():
            return code
    raise ValueError("Kode pelanggan gagal dibuat. Coba ulang.")


def _build_location_name(form):
    location_name = _clean(form.get("location_name"))
    if location_name:
        return location_name

    address = _clean(form.get("address"))
    if address:
        return address[:120]

    return "Alamat Utama"


def validate_customer_registration_form(form):
    full_name = _require(form.get("full_name"), "Nama lengkap wajib diisi.")
    username = normalize_username(form.get("username"))
    phone = _require(form.get("phone"), "Nomor HP wajib diisi.")
    address = _require(form.get("address"), "Alamat pengiriman wajib diisi.")
    location_name = _build_location_name(form)
    branch = _get_active_branch(form.get("branch_id"))

    if not username:
        raise ValueError("Username wajib diisi.")
    if username_is_used(username):
        raise ValueError("Username sudah digunakan.")

    valid_password, password_error = validate_password_pair(
        form.get("password") or "",
        form.get("password_confirmation") or "",
    )
    if not valid_password:
        raise ValueError(password_error)

    # Titik GPS lokasi antar (peta/GPS HP) dipakai untuk ongkir per km dan
    # petunjuk arah pengantar. Zona hanya cadangan bila peta tidak bisa dibuka.
    try:
        latitude, longitude = parse_coordinates(form.get("latitude"), form.get("longitude"))
    except GeoError as exc:
        raise ValueError(str(exc)) from exc
    zones = {zone.id: zone for zone in active_zones(branch.id)}
    zone_id = _to_int(form.get("delivery_zone_id"))
    if latitude is None and zone_id not in zones:
        raise ValueError(
            "Tandai titik lokasi pengiriman di peta atau tekan tombol GPS"
            + (", atau pilih zona pengiriman bila peta tidak muncul." if zones else ".")
        )

    return {
        "full_name": full_name,
        "username": username,
        "phone": phone,
        "address": address,
        "location_name": location_name,
        "notes": _clean(form.get("notes")),
        "password": form.get("password") or "",
        "branch": branch,
        "delivery_zone_id": zone_id if zone_id in zones else None,
        "latitude": latitude,
        "longitude": longitude,
        "gps_accuracy_m": parse_accuracy(form.get("gps_accuracy")) if latitude is not None else None,
    }


def register_portal_customer(form, files=None):
    from app.services.location_photo_service import LocationPhotoError, discard_files, stage_location_photos

    payload = validate_customer_registration_form(form)
    photo_files = [f for f in (files or []) if f is not None and getattr(f, "filename", "")]
    if not photo_files:
        raise ValueError("Foto lokasi antar wajib diunggah (minimal 1 foto titik serah terima).")
    branch = payload["branch"]

    user = User(
        branch_id=branch.id,
        full_name=payload["full_name"],
        username=payload["username"],
        password_hash=generate_password_hash(payload["password"]),
        role=ROLE_PORTAL_CUSTOMER,
        is_active=True,
    )
    client = Client(
        client_code=_new_client_code(),
        name=payload["full_name"],
        address=payload["address"],
        phone=payload["phone"],
        is_active=True,
        # Pendaftar portal = pelanggan umum: bayar di muka per pesanan.
        customer_path=PATH_GENERAL,
    )
    mandor = Mandor(
        branch_id=branch.id,
        client=client,
        name=payload["full_name"],
        phone=payload["phone"],
        is_active=True,
    )
    location = DeliveryLocation(
        mandor=mandor,
        delivery_zone_id=payload["delivery_zone_id"],
        location_name=payload["location_name"],
        description=payload["address"] if not payload["notes"] else f"{payload['address']} | {payload['notes']}",
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        gps_accuracy_m=payload["gps_accuracy_m"],
        gps_updated_at=datetime.utcnow() if payload["latitude"] is not None else None,
        is_active=True,
    )
    mapping = PortalUserMapping(
        user=user,
        principal_type=PRINCIPAL_DELEGATE,
        client=client,
        mandor=mandor,
        delivery_location=location,
        access_level=ACCESS_DRAFT_ORDER,
        is_active=True,
    )

    staged = []
    try:
        db.session.add_all([user, client, mandor, location, mapping])
        db.session.flush()
        staged = stage_location_photos(location, photo_files, uploaded_by=user.id, branch_id=branch.id, required=True)
        db.session.commit()
    except LocationPhotoError as exc:
        db.session.rollback()
        raise ValueError(str(exc)) from exc
    except IntegrityError as exc:
        db.session.rollback()
        discard_files(staged)
        raise ValueError("Data registrasi bentrok dengan data yang sudah ada. Gunakan username atau lokasi lain.") from exc
    except Exception:
        db.session.rollback()
        discard_files(staged)
        raise

    return user
