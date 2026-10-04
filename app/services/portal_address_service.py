"""Alamat antar milik akun portal (pelanggan umum & mandor).

Setiap alamat = DeliveryLocation di bawah mandor akun itu, lengkap dengan
titik GPS (peta/GPS HP). Titik dipakai pengantar untuk petunjuk arah dan
untuk ongkir per km pelanggan umum (geo_service). Keputusan owner 2026-10-04.
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.master import DeliveryLocation, Mandor
from app.services import geo_service
from app.services.portal_mapping_service import build_portal_external_scope
from app.services.portal_order_draft_service import orderable_location_ids
from app.services.user_management_service import ROLE_PORTAL_CUSTOMER, ROLE_PORTAL_SUBCLIENT

ADDRESS_ROLES = (ROLE_PORTAL_CUSTOMER, ROLE_PORTAL_SUBCLIENT)


class PortalAddressError(ValueError):
    pass


def _clean(value, limit):
    return str(value or "").strip()[:limit]


def _owner_mandor(user, scope):
    """Mandor tempat alamat baru disimpan: satu-satunya mandor dalam akses akun."""
    if getattr(user, "role", None) not in ADDRESS_ROLES or not scope.allowed or len(scope.mandor_ids) != 1:
        return None
    return db.session.get(Mandor, next(iter(scope.mandor_ids)))


def address_book(user):
    from app.services.pricing_service import free_delivery_min_portions, is_general_client

    scope = build_portal_external_scope(user)
    editable = orderable_location_ids(user, scope) if getattr(user, "role", None) in ADDRESS_ROLES else set()
    rows = []
    if scope.allowed and scope.delivery_location_ids:
        locations = (
            DeliveryLocation.query.filter(DeliveryLocation.id.in_(sorted(scope.delivery_location_ids)))
            .order_by(DeliveryLocation.is_active.desc(), DeliveryLocation.location_name.asc())
            .all()
        )
        for location in locations:
            mandor = location.mandor
            branch_id = mandor.branch_id if mandor else None
            general = bool(mandor and is_general_client(mandor.client))
            quote = geo_service.quote_distance_fee(branch_id, location) if branch_id and general else None
            rows.append({
                "location": location,
                "editable": location.id in editable,
                "has_point": geo_service.has_point(location),
                "quote": quote,
                "maps_url": geo_service.maps_url(location.latitude, location.longitude),
            })
    branch_id = getattr(user, "branch_id", None) or (rows[0]["location"].mandor.branch_id if rows else None)
    owner = _owner_mandor(user, scope)
    return {
        "allowed": scope.allowed,
        "reason": scope.reason,
        "rows": rows,
        "can_add": owner is not None,
        "missing_point": sum(1 for row in rows if row["editable"] and not row["has_point"]),
        "geo": geo_service.picker_context(branch_id) if branch_id else None,
        "free_from": free_delivery_min_portions(branch_id) if branch_id else 0,
    }


def _apply_form(location, form):
    name = _clean(form.get("location_name"), 120)
    if not name:
        raise PortalAddressError("Nama alamat wajib diisi, misalnya Rumah, Kantor, atau Mes Proyek.")
    address = _clean(form.get("address"), 500)
    if not address:
        raise PortalAddressError("Alamat lengkap wajib diisi.")
    try:
        lat, lng = geo_service.parse_coordinates(form.get("latitude"), form.get("longitude"), required=True)
    except geo_service.GeoError as exc:
        raise PortalAddressError(str(exc)) from exc
    location.location_name = name
    location.description = address
    geo_service.apply_location_point(location, {
        "latitude": str(lat), "longitude": str(lng), "gps_accuracy": form.get("gps_accuracy"),
    })


def _audit(user, location, action, before=None):
    from app.services.audit_log_service import record_audit_log

    record_audit_log(
        module="PORTAL",
        event_type="PORTAL_ADDRESS_SAVED",
        action=action,
        table_name="delivery_locations",
        record_id=location.id,
        description=f"Alamat antar {location.location_name} disimpan dari portal.",
        old_value=before,
        new_value={"location_name": location.location_name, "latitude": str(location.latitude),
                   "longitude": str(location.longitude)},
        user_id=user.id,
        branch_id=getattr(user, "branch_id", None),
        commit=False,
    )


def _commit():
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise PortalAddressError("Nama alamat itu sudah dipakai. Pakai nama lain, misalnya Rumah 2.") from exc


def add_address(user, form):
    scope = build_portal_external_scope(user)
    mandor = _owner_mandor(user, scope)
    if not mandor:
        raise PortalAddressError("Akun ini tidak bisa menambah alamat sendiri. Hubungi admin.")
    location = DeliveryLocation(mandor_id=mandor.id, is_active=True)
    _apply_form(location, form)
    db.session.add(location)
    db.session.flush()
    _audit(user, location, "CREATE")
    _commit()
    return location


def update_address(user, location_id, form):
    scope = build_portal_external_scope(user)
    if getattr(user, "role", None) not in ADDRESS_ROLES or location_id not in orderable_location_ids(user, scope):
        raise PortalAddressError("Alamat ini tidak bisa diubah dari akun Anda.")
    location = db.session.get(DeliveryLocation, location_id)
    before = {"location_name": location.location_name, "latitude": str(location.latitude),
              "longitude": str(location.longitude)}
    _apply_form(location, form)
    _audit(user, location, "UPDATE", before)
    _commit()
    return location
