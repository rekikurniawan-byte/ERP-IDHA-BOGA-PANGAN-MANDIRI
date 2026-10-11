"""Harga & Ongkir: daftar harga per porsi, diatur OWNER.

Lihat app/services/pricing_service.py untuk aturan harganya.
"""
from datetime import date, datetime

from app.routes.settings_routes import *  # noqa: F401,F403
from app.utils.clock import today_wib
from app.models.master import Client
from app.services.geo_service import distance_fee_settings, picker_context
from app.services.pricing_service import (
    PricingError,
    client_fee_overview,
    client_price_overview,
    create_delivery_zone,
    free_delivery_min_portions,
    general_min_portions,
    menus_priced_below_hpp,
    price_history,
    price_in_effect,
    scheduled_prices,
    set_delivery_fee,
    set_free_delivery_min_portions,
    set_general_min_portions,
    set_portion_price,
    zone_overview,
)


def _effective_date(value):
    """Tanggal berlaku dari form: kosong = hari ini; tidak boleh mundur."""
    value = (value or "").strip()
    if not value:
        return today_wib()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise PricingError("Tanggal berlaku tidak valid.")
    if parsed < today_wib():
        raise PricingError(
            "Tanggal berlaku tidak boleh sebelum hari ini: harga pesanan yang sudah dibuat "
            "sudah terkunci dan tidak ikut berubah."
        )
    return parsed


@settings_bp.route("/pricing")
@role_required("OWNER")
def pricing():
    branch_id = current_user.branch_id
    current = price_in_effect(branch_id)
    return render_template(
        "settings/pricing.html",
        current=current,
        scheduled=scheduled_prices(branch_id),
        history=price_history(branch_id),
        below_hpp=menus_priced_below_hpp(branch_id, current.price_per_portion if current else None),
        client_prices=client_price_overview(branch_id),
        clients=Client.query.filter(Client.is_active.is_(True)).order_by(Client.name.asc()).all(),
        min_portions=general_min_portions(branch_id),
        zones=zone_overview(branch_id),
        client_fees=client_fee_overview(branch_id),
        free_delivery_min=free_delivery_min_portions(branch_id),
        distance=distance_fee_settings(branch_id),
        geo=picker_context(branch_id),
        today=today_wib(),
    )


@settings_bp.route("/pricing/price", methods=["POST"])
@role_required("OWNER")
def pricing_set_price():
    client_id = request.form.get("client_id", type=int)
    try:
        row = set_portion_price(
            branch_id=current_user.branch_id,
            client_id=client_id,
            price=request.form.get("price_per_portion"),
            effective_from=_effective_date(request.form.get("effective_from")),
            created_by=current_user.id,
            notes=request.form.get("notes"),
        )
    except PricingError as error:
        flash(str(error), "warning")
        return redirect(url_for("settings.pricing"))

    target = f"harga kontrak {row.client.name}" if row.client else "harga standar"
    when = "mulai hari ini" if row.effective_from == today_wib() else f"mulai {row.effective_from.strftime('%d-%m-%Y')}"
    flash(f"Harga baru {target} Rp {row.price_per_portion:,.0f}/porsi berlaku {when}.", "success")
    return redirect(url_for("settings.pricing"))


@settings_bp.route("/pricing/min-portions", methods=["POST"])
@role_required("OWNER")
def pricing_set_min_portions():
    try:
        portions = set_general_min_portions(current_user.branch_id, request.form.get("min_portions"), current_user.id)
    except PricingError as error:
        flash(str(error), "warning")
        return redirect(url_for("settings.pricing"))
    flash(f"Minimal pesan pelanggan umum: {portions} porsi per pengiriman.", "success")
    return redirect(url_for("settings.pricing"))


@settings_bp.route("/pricing/zones", methods=["POST"])
@role_required("OWNER")
def pricing_create_zone():
    try:
        zone = create_delivery_zone(current_user.branch_id, request.form.get("name"), current_user.id)
    except PricingError as error:
        flash(str(error), "warning")
        return redirect(url_for("settings.pricing"))
    flash(f"Zona {zone.name} dibuat. Isi tarif ongkirnya di bawah.", "success")
    return redirect(url_for("settings.pricing"))


@settings_bp.route("/pricing/delivery-fee", methods=["POST"])
@role_required("OWNER")
def pricing_set_delivery_fee():
    try:
        row = set_delivery_fee(
            branch_id=current_user.branch_id,
            zone_id=request.form.get("zone_id", type=int),
            client_id=request.form.get("client_id", type=int),
            fee=request.form.get("fee"),
            effective_from=_effective_date(request.form.get("effective_from")),
            created_by=current_user.id,
            notes=request.form.get("notes"),
        )
    except PricingError as error:
        flash(str(error), "warning")
        return redirect(url_for("settings.pricing"))
    target = f"zona {row.zone.name}" if row.zone else f"kontrak {row.client.name}"
    flash(f"Ongkir {target} Rp {row.fee:,.0f}/pengiriman berlaku mulai {row.effective_from.strftime('%d-%m-%Y')}.", "success")
    return redirect(url_for("settings.pricing"))


@settings_bp.route("/pricing/free-delivery", methods=["POST"])
@role_required("OWNER")
def pricing_set_free_delivery():
    try:
        portions = set_free_delivery_min_portions(
            current_user.branch_id, request.form.get("free_delivery_min_portions"), current_user.id
        )
    except PricingError as error:
        flash(str(error), "warning")
        return redirect(url_for("settings.pricing"))
    message = f"Gratis ongkir untuk pengiriman minimal {portions} porsi." if portions else "Gratis ongkir dimatikan."
    flash(message, "success")
    return redirect(url_for("settings.pricing"))


@settings_bp.route("/pricing/distance-fee", methods=["POST"])
@role_required("OWNER")
def pricing_set_distance_fee():
    """Titik dapur + tarif ongkir per km pelanggan umum (keputusan owner 2026-10-04)."""
    from app.services.geo_service import GeoError, save_distance_fee_settings

    try:
        values = save_distance_fee_settings(
            current_user.branch_id,
            latitude=request.form.get("latitude"),
            longitude=request.form.get("longitude"),
            label=request.form.get("origin_label"),
            per_km=request.form.get("per_km"),
            minimum=request.form.get("minimum"),
            road_factor=request.form.get("road_factor"),
            updated_by=current_user.id,
            commit=True,
        )
    except GeoError as error:
        flash(str(error), "warning")
        return redirect(url_for("settings.pricing") + "#ongkir-jarak")
    flash(
        f"Ongkir jarak tersimpan: Rp {int(float(values['delivery_fee_per_km'])):,}/km, minimal "
        f"Rp {int(float(values['delivery_fee_minimum'])):,}.".replace(",", "."),
        "success",
    )
    return redirect(url_for("settings.pricing") + "#ongkir-jarak")
