"""Lokasi GPS dan ongkir berbasis jarak.

Titik dapur (asal pengiriman) dan tarif per km disimpan per cabang di
branch_settings. Jarak = garis lurus (haversine) x faktor jalan, karena rute
jalan sebenarnya butuh layanan peta berbayar; faktor jalan bisa diatur OWNER
(bawaan 1,3: jalan rata-rata 30% lebih panjang dari garis lurus).

Ongkir = max(ongkir minimal, jarak x tarif per km), dibulatkan ke atas ke
kelipatan Rp 500.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from app.extensions import db
from app.models.master import BranchSetting

ORIGIN_LAT_SETTING = "delivery_origin_latitude"
ORIGIN_LNG_SETTING = "delivery_origin_longitude"
ORIGIN_LABEL_SETTING = "delivery_origin_label"
FEE_PER_KM_SETTING = "delivery_fee_per_km"
FEE_MINIMUM_SETTING = "delivery_fee_minimum"
ROAD_FACTOR_SETTING = "delivery_road_factor"

DEFAULT_ROAD_FACTOR = Decimal("1.3")
FEE_ROUNDING = Decimal("500")
# Batas kasar wilayah Indonesia: koordinat di luar ini hampir pasti salah ketik.
LAT_RANGE = (Decimal("-11.5"), Decimal("6.5"))
LNG_RANGE = (Decimal("94.5"), Decimal("141.5"))


class GeoError(ValueError):
    pass


@dataclass(frozen=True)
class DistanceQuote:
    km: Decimal
    fee: Decimal
    per_km: Decimal
    minimum: Decimal

    @property
    def km_label(self):
        return f"{self.km:.1f}".replace(".", ",") + " km"


def parse_coordinates(latitude, longitude, *, required=False):
    """(lat, lng) Decimal 7 desimal, atau (None, None) bila kosong."""
    raw_lat = str(latitude if latitude is not None else "").strip().replace(",", ".")
    raw_lng = str(longitude if longitude is not None else "").strip().replace(",", ".")
    if not raw_lat and not raw_lng:
        if required:
            raise GeoError("Titik lokasi wajib dipilih di peta atau dengan tombol GPS.")
        return None, None
    try:
        lat = Decimal(raw_lat).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP)
        lng = Decimal(raw_lng).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise GeoError("Koordinat lokasi tidak valid.")
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
        raise GeoError("Titik lokasi berada di luar wilayah Indonesia. Periksa lagi titik di peta.")
    return lat, lng


def parse_accuracy(value):
    try:
        accuracy = int(round(float(str(value).replace(",", "."))))
    except (TypeError, ValueError):
        return None
    return accuracy if 0 < accuracy < 100000 else None


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = (math.radians(float(value)) for value in (lat1, lng1, lat2, lng2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def maps_url(latitude, longitude):
    """Tautan petunjuk arah Google Maps (dibuka di aplikasi Maps di HP)."""
    if latitude is None or longitude is None:
        return None
    return f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}"


def has_point(obj):
    return getattr(obj, "latitude", None) is not None and getattr(obj, "longitude", None) is not None


# --- pengaturan cabang ------------------------------------------------------

def _setting(branch_id, key):
    row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=key).first()
    return str(getattr(row, "setting_value", "") or "").strip()


def _decimal_setting(branch_id, key, default=None):
    value = _setting(branch_id, key)
    try:
        return Decimal(value) if value else default
    except InvalidOperation:
        return default


def delivery_origin(branch_id):
    """Titik dapur: dict(lat, lng, label) atau None bila belum diatur."""
    lat = _decimal_setting(branch_id, ORIGIN_LAT_SETTING)
    lng = _decimal_setting(branch_id, ORIGIN_LNG_SETTING)
    if lat is None or lng is None:
        return None
    return {"lat": lat, "lng": lng, "label": _setting(branch_id, ORIGIN_LABEL_SETTING) or "Dapur"}


def distance_fee_settings(branch_id):
    per_km = _decimal_setting(branch_id, FEE_PER_KM_SETTING, Decimal("0"))
    minimum = _decimal_setting(branch_id, FEE_MINIMUM_SETTING, Decimal("0"))
    factor = _decimal_setting(branch_id, ROAD_FACTOR_SETTING, DEFAULT_ROAD_FACTOR)
    origin = delivery_origin(branch_id)
    return {
        "origin": origin,
        "per_km": per_km,
        "minimum": minimum,
        "road_factor": factor if factor and factor >= 1 else DEFAULT_ROAD_FACTOR,
        "enabled": bool(origin) and (per_km > 0 or minimum > 0),
    }


def _round_up(value):
    return (value / FEE_ROUNDING).to_integral_value(rounding=ROUND_CEILING) * FEE_ROUNDING


def road_distance_km(branch_id, latitude, longitude, settings=None):
    settings = settings or distance_fee_settings(branch_id)
    origin = settings["origin"]
    if not origin or latitude is None or longitude is None:
        return None
    straight = Decimal(str(haversine_km(origin["lat"], origin["lng"], latitude, longitude)))
    return (straight * settings["road_factor"]).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def quote_distance_fee(branch_id, location):
    """Ongkir per kiriman ke lokasi bertitik GPS, atau None bila tidak bisa dihitung."""
    settings = distance_fee_settings(branch_id)
    if not settings["enabled"] or not has_point(location):
        return None
    km = road_distance_km(branch_id, location.latitude, location.longitude, settings)
    fee = max(settings["minimum"], _round_up(km * settings["per_km"]))
    return DistanceQuote(km=km, fee=fee, per_km=settings["per_km"], minimum=settings["minimum"])


def save_distance_fee_settings(branch_id, *, latitude, longitude, label, per_km, minimum, road_factor, updated_by):
    """Simpan titik dapur dan tarif per km (OWNER). Tidak commit."""
    from app.services.audit_log_service import record_audit_log

    lat, lng = parse_coordinates(latitude, longitude, required=True)
    try:
        per_km = Decimal(str(per_km or "0").replace(".", "").replace(",", "")) if str(per_km).strip() else Decimal("0")
        minimum = Decimal(str(minimum or "0").replace(".", "").replace(",", "")) if str(minimum).strip() else Decimal("0")
        road_factor = Decimal(str(road_factor or DEFAULT_ROAD_FACTOR).replace(",", "."))
    except InvalidOperation:
        raise GeoError("Tarif per km, ongkir minimal, dan faktor jalan harus angka.")
    if per_km < 0 or minimum < 0:
        raise GeoError("Tarif ongkir tidak boleh minus.")
    if not (Decimal("1") <= road_factor <= Decimal("3")):
        raise GeoError("Faktor jalan antara 1 dan 3 (1 = garis lurus).")
    values = {
        ORIGIN_LAT_SETTING: str(lat),
        ORIGIN_LNG_SETTING: str(lng),
        ORIGIN_LABEL_SETTING: str(label or "Dapur").strip()[:120],
        FEE_PER_KM_SETTING: str(per_km),
        FEE_MINIMUM_SETTING: str(minimum),
        ROAD_FACTOR_SETTING: str(road_factor),
    }
    before = distance_fee_settings(branch_id)
    for key, value in values.items():
        row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=key).first()
        if row:
            row.setting_value = value
        else:
            db.session.add(BranchSetting(branch_id=branch_id, setting_key=key, setting_value=value))
    record_audit_log(
        module="PRICING",
        event_type="DISTANCE_FEE_SET",
        action="UPDATE",
        table_name="branch_settings",
        record_id=branch_id,
        description=(
            f"Ongkir jarak: Rp {per_km:,.0f}/km, minimal Rp {minimum:,.0f}, faktor jalan {road_factor} "
            f"(sebelumnya Rp {before['per_km']:,.0f}/km, minimal Rp {before['minimum']:,.0f})."
        ).replace(",", "."),
        metadata={key: value for key, value in values.items()},
        user_id=updated_by,
        branch_id=branch_id,
        commit=False,
    )
    return values


def picker_context(branch_id):
    """Data untuk components/location_picker.html: titik dapur + tarif (perkiraan di peta)."""
    from app.services.pricing_service import free_delivery_min_portions

    if not branch_id:
        return None
    settings = distance_fee_settings(branch_id)
    return {
        "origin": settings["origin"],
        "per_km": settings["per_km"] if settings["enabled"] else 0,
        "minimum": settings["minimum"] if settings["enabled"] else 0,
        "road_factor": settings["road_factor"],
        "free_from": free_delivery_min_portions(branch_id),
    }


def apply_location_point(location, form, *, prefix=""):
    """Isi latitude/longitude/akurasi lokasi dari form (field {prefix}latitude dst)."""
    from datetime import datetime

    lat, lng = parse_coordinates(form.get(f"{prefix}latitude"), form.get(f"{prefix}longitude"))
    changed = (lat, lng) != (getattr(location, "latitude", None), getattr(location, "longitude", None))
    location.latitude = lat
    location.longitude = lng
    location.gps_accuracy_m = parse_accuracy(form.get(f"{prefix}gps_accuracy")) if lat is not None else None
    if changed:
        location.gps_updated_at = datetime.utcnow() if lat is not None else None
    return lat is not None
