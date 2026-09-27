from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import PortalUserMapping
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_DELEGATE
from app.services.pricing_service import PATH_GENERAL
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

    return {
        "full_name": full_name,
        "username": username,
        "phone": phone,
        "address": address,
        "location_name": location_name,
        "notes": _clean(form.get("notes")),
        "password": form.get("password") or "",
        "branch": branch,
    }


def register_portal_customer(form):
    payload = validate_customer_registration_form(form)
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
        location_name=payload["location_name"],
        description=payload["address"] if not payload["notes"] else f"{payload['address']} | {payload['notes']}",
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

    try:
        db.session.add_all([user, client, mandor, location, mapping])
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValueError("Data registrasi bentrok dengan data yang sudah ada. Gunakan username atau lokasi lain.") from exc
    except Exception:
        db.session.rollback()
        raise

    return user
