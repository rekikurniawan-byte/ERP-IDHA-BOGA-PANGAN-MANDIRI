"""Dua jalur transaksi dan harga jual per porsi.

Keputusan owner 2026-09-27:
- jalur client: KONTRAK (kredit lewat invoice) atau UMUM (bayar di muka);
- satu harga per porsi, sama untuk makan siang dan malam;
- harga bisa diubah kapan saja (mengikuti bahan pokok dan BBM) dengan tanggal
  berlaku, dan bisa dijadwalkan; harga kontrak per client menang atas harga
  standar cabang;
- harga dikunci ke pesanan saat pesanan dibuat. Admin tidak mengetik harga;
  hanya OWNER yang boleh mengubah harga satu pesanan, dan itu tercatat;
- peringatan kalau harga jual di bawah HPP;
- pelanggan UMUM minimal memesan N porsi per pengiriman (bawaan 10).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.master import BranchSetting, Client, Mandor
from app.models.pricing import PortionPrice

PATH_CONTRACT = "KONTRAK"
PATH_GENERAL = "UMUM"
CUSTOMER_PATHS = (PATH_CONTRACT, PATH_GENERAL)
CUSTOMER_PATH_LABELS = {PATH_CONTRACT: "Kontrak (kredit)", PATH_GENERAL: "Umum (bayar di muka)"}

SOURCE_CONTRACT = "KONTRAK"
SOURCE_STANDARD = "STANDAR"
SOURCE_OWNER = "OWNER"
PRICE_SOURCE_LABELS = {
    SOURCE_CONTRACT: "Harga kontrak",
    SOURCE_STANDARD: "Harga standar",
    SOURCE_OWNER: "Diubah OWNER",
    None: "Manual (sebelum daftar harga)",
}

MIN_PORTIONS_SETTING = "general_min_portions"
DEFAULT_MIN_PORTIONS = 10


class PricingError(ValueError):
    pass


@dataclass
class PriceQuote:
    price: Decimal
    source: str
    row: PortionPrice

    @property
    def source_label(self):
        return PRICE_SOURCE_LABELS.get(self.source, self.source)


def _money(value):
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, AttributeError):
        raise PricingError("Harga harus berupa angka.")
    if amount <= 0:
        raise PricingError("Harga per porsi harus lebih dari 0.")
    return amount.quantize(Decimal("0.01"))


def client_path(client):
    return getattr(client, "customer_path", None) or PATH_CONTRACT


def is_general_client(client):
    return client_path(client) == PATH_GENERAL


# --- daftar harga ---------------------------------------------------------

def _price_rows(branch_id, client_id):
    query = PortionPrice.query.filter(PortionPrice.branch_id == branch_id)
    if client_id:
        query = query.filter(PortionPrice.client_id == client_id)
    else:
        query = query.filter(PortionPrice.client_id.is_(None))
    return query


def price_in_effect(branch_id, client_id=None, on_date=None):
    """Baris harga yang berlaku pada tanggal itu (terbaru yang sudah mulai)."""
    on_date = on_date or date.today()
    return (
        _price_rows(branch_id, client_id)
        .filter(PortionPrice.effective_from <= on_date)
        .order_by(PortionPrice.effective_from.desc(), PortionPrice.id.desc())
        .first()
    )


def scheduled_prices(branch_id, client_id=None, after_date=None):
    after_date = after_date or date.today()
    return (
        _price_rows(branch_id, client_id)
        .filter(PortionPrice.effective_from > after_date)
        .order_by(PortionPrice.effective_from.asc(), PortionPrice.id.asc())
        .all()
    )


def price_history(branch_id, client_id=None, limit=20):
    return (
        _price_rows(branch_id, client_id)
        .order_by(PortionPrice.effective_from.desc(), PortionPrice.id.desc())
        .limit(limit)
        .all()
    )


def quote_price(branch_id, client_id=None, on_date=None):
    """Harga untuk client ini: harga kontrak kalau ada, kalau tidak harga standar."""
    if client_id:
        row = price_in_effect(branch_id, client_id, on_date)
        if row:
            return PriceQuote(Decimal(row.price_per_portion), SOURCE_CONTRACT, row)
    row = price_in_effect(branch_id, None, on_date)
    if row:
        return PriceQuote(Decimal(row.price_per_portion), SOURCE_STANDARD, row)
    return None


def quote_price_for_mandor(branch_id, mandor_id, on_date=None):
    mandor = Mandor.query.get(mandor_id) if mandor_id else None
    return quote_price(branch_id, getattr(mandor, "client_id", None), on_date)


def price_quotes_by_mandor(branch_id, mandors, on_date=None):
    """{mandor_id: PriceQuote|None} untuk form order, tanpa query per baris."""
    on_date = on_date or date.today()
    standard = quote_price(branch_id, None, on_date)
    client_ids = {getattr(mandor, "client_id", None) for mandor in mandors} - {None}
    contract = {}
    if client_ids:
        rows = (
            PortionPrice.query.filter(
                PortionPrice.branch_id == branch_id,
                PortionPrice.client_id.in_(client_ids),
                PortionPrice.effective_from <= on_date,
            )
            .order_by(PortionPrice.effective_from.asc(), PortionPrice.id.asc())
            .all()
        )
        for row in rows:  # urut naik: yang terakhir menang
            contract[row.client_id] = PriceQuote(Decimal(row.price_per_portion), SOURCE_CONTRACT, row)
    return {
        mandor.id: contract.get(getattr(mandor, "client_id", None)) or standard
        for mandor in mandors
    }


def set_portion_price(*, branch_id, client_id=None, price, effective_from, created_by, notes=None):
    """Tambah harga baru (baris lama tidak diubah). Commit bersama audit log-nya."""
    from app.services.audit_log_service import record_audit_log

    amount = _money(price)
    if not isinstance(effective_from, date):
        raise PricingError("Tanggal berlaku wajib diisi.")
    if client_id and not Client.query.get(client_id):
        raise PricingError("Client tidak ditemukan.")

    previous = price_in_effect(branch_id, client_id, effective_from)
    row = PortionPrice(
        branch_id=branch_id,
        client_id=client_id or None,
        price_per_portion=amount,
        effective_from=effective_from,
        notes=(notes or "").strip() or None,
        created_by=created_by,
    )
    db.session.add(row)
    db.session.flush()
    target = f"client #{client_id}" if client_id else "harga standar cabang"
    record_audit_log(
        module="PRICING",
        event_type="PORTION_PRICE_SET",
        action="CREATE",
        table_name="portion_prices",
        record_id=row.id,
        description=(
            f"Harga per porsi {target}: Rp {amount:,.0f} berlaku mulai "
            f"{effective_from.strftime('%d-%m-%Y')}"
            + (f" (sebelumnya Rp {Decimal(previous.price_per_portion):,.0f})." if previous else ".")
        ),
        old_value={"price_per_portion": str(previous.price_per_portion)} if previous else None,
        new_value={"price_per_portion": str(amount), "effective_from": effective_from.isoformat()},
        metadata={"client_id": client_id},
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return row


# --- harga di pesanan -----------------------------------------------------

def resolve_order_price(*, branch_id, mandor_id, actor_role, requested_price=None, on_date=None):
    """Harga yang dikunci ke pesanan baru: (harga, asal, pesan_error).

    Admin selalu memakai harga dari daftar harga. OWNER boleh mengisi harga
    lain untuk pesanan ini; asalnya dicatat OWNER.
    """
    quote = quote_price_for_mandor(branch_id, mandor_id, on_date)
    requested = None
    if requested_price not in (None, ""):
        try:
            requested = _money(requested_price)
        except PricingError:
            requested = None
    if actor_role == "OWNER" and requested is not None:
        if quote and requested == quote.price:
            return quote.price, quote.source, None
        return requested, SOURCE_OWNER, None
    if not quote:
        return None, None, (
            "Harga per porsi belum diatur. OWNER perlu mengisi harga standar di "
            "Pengaturan → Harga & Ongkir sebelum pesanan bisa dibuat."
        )
    return quote.price, quote.source, None


# --- minimal porsi pelanggan umum -----------------------------------------

def general_min_portions(branch_id):
    row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=MIN_PORTIONS_SETTING).first()
    try:
        value = int(str(getattr(row, "setting_value", "") or "").strip())
    except ValueError:
        value = 0
    return value if value > 0 else DEFAULT_MIN_PORTIONS


def set_general_min_portions(branch_id, value, updated_by):
    from app.services.audit_log_service import record_audit_log

    try:
        portions = int(str(value).strip())
    except (TypeError, ValueError):
        raise PricingError("Minimal porsi harus angka bulat.")
    if portions < 1:
        raise PricingError("Minimal porsi paling sedikit 1.")
    before = general_min_portions(branch_id)
    row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=MIN_PORTIONS_SETTING).first()
    if row:
        row.setting_value = str(portions)
    else:
        db.session.add(BranchSetting(branch_id=branch_id, setting_key=MIN_PORTIONS_SETTING, setting_value=str(portions)))
    record_audit_log(
        module="PRICING",
        event_type="GENERAL_MIN_PORTIONS_SET",
        action="UPDATE",
        table_name="branch_settings",
        record_id=branch_id,
        description=f"Minimal pesan pelanggan umum: {before} → {portions} porsi per pengiriman.",
        user_id=updated_by,
        branch_id=branch_id,
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return portions


def min_portion_error(branch_id, client, meal_quantities):
    """Pesan penolakan kalau pelanggan UMUM memesan di bawah minimal.

    Minimal berlaku per pengiriman: kiriman siang dan kiriman malam masing-masing
    harus memenuhi, karena masing-masing satu kali jalan.
    """
    if not is_general_client(client):
        return None
    minimum = general_min_portions(branch_id)
    for label, qty in meal_quantities:
        qty = int(qty or 0)
        if 0 < qty < minimum:
            return f"Pesanan pelanggan umum minimal {minimum} porsi per pengiriman ({label}: {qty} porsi)."
    return None


# --- peringatan HPP -------------------------------------------------------

def hpp_per_portion_for_menu(menu, packaging_profile=None, overhead_profile=None, portion_qty=100):
    from app.services.hpp_service import calculate_menu_hpp

    result = calculate_menu_hpp(
        menu,
        portion_qty,
        selling_price_per_portion=0,
        packaging_profile=packaging_profile,
        overhead_profile=overhead_profile,
    )
    if not result.get("is_complete") or not result.get("hpp_per_portion"):
        return None
    return Decimal(str(result["hpp_per_portion"])).quantize(Decimal("0.01"))


def menus_priced_below_hpp(branch_id, price):
    """[(menu, hpp)] untuk menu aktif cabang yang HPP-nya melebihi harga ini."""
    from app.models.master import Menu

    if price is None:
        return []
    price = Decimal(str(price))
    rows = []
    menus = Menu.query.filter(Menu.branch_id == branch_id, Menu.is_active.is_(True)).all()
    for menu in menus:
        hpp = hpp_per_portion_for_menu(menu)
        if hpp is not None and hpp > price:
            rows.append((menu, hpp))
    return rows


def order_hpp_warning(daily_order, price):
    """Peringatan kalau harga pesanan di bawah HPP menu default order itu."""
    if price is None:
        return None
    from app.models.master import Menu, OverheadProfile, PackagingProfile

    packaging = PackagingProfile.query.get(daily_order.packaging_profile_id) if getattr(daily_order, "packaging_profile_id", None) else None
    overhead = OverheadProfile.query.get(daily_order.overhead_profile_id) if getattr(daily_order, "overhead_profile_id", None) else None
    below = []
    for label, menu_id in (("siang", getattr(daily_order, "lunch_menu_id", None)), ("malam", getattr(daily_order, "dinner_menu_id", None))):
        menu = Menu.query.get(menu_id) if menu_id else None
        hpp = hpp_per_portion_for_menu(menu, packaging, overhead) if menu else None
        if hpp is not None and hpp > Decimal(str(price)):
            below.append(f"menu {label} {menu.menu_name} HPP Rp {hpp:,.0f}")
    if not below:
        return None
    return f"Harga Rp {Decimal(str(price)):,.0f}/porsi di bawah HPP ({'; '.join(below)}). Pesanan ini merugi."


def client_price_overview(branch_id, on_date=None):
    """Harga kontrak yang tercatat di cabang ini, per client: berlaku sekarang + terjadwal."""
    on_date = on_date or date.today()
    client_ids = [
        row.client_id
        for row in db.session.query(PortionPrice.client_id)
        .filter(PortionPrice.branch_id == branch_id, PortionPrice.client_id.isnot(None))
        .distinct()
    ]
    overview = []
    for client in Client.query.filter(Client.id.in_(client_ids)).order_by(Client.name.asc()).all() if client_ids else []:
        overview.append({
            "client": client,
            "current": price_in_effect(branch_id, client.id, on_date),
            "scheduled": scheduled_prices(branch_id, client.id, on_date),
        })
    return overview


# --- ongkir ---------------------------------------------------------------
# Kontrak: termasuk harga porsi, kecuali kontraknya punya tarif ongkir sendiri.
# Umum: tarif zona lokasi, per pengiriman, gratis kalau porsi pengiriman itu
# mencapai ambang cabang. Tarif dikunci ke pengiriman saat pesanan dibuat.

FEE_SOURCE_CONTRACT = "KONTRAK"
FEE_SOURCE_INCLUDED = "TERMASUK"
FEE_SOURCE_ZONE = "ZONA"
FEE_SOURCE_FREE = "GRATIS"
FREE_DELIVERY_SETTING = "free_delivery_min_portions"
ZERO_FEE = Decimal("0.00")


def _fee_amount(value):
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, AttributeError):
        raise PricingError("Tarif ongkir harus berupa angka.")
    if amount < 0:
        raise PricingError("Tarif ongkir tidak boleh minus.")
    return amount.quantize(Decimal("0.01"))


def _fee_rows(branch_id, zone_id=None, client_id=None):
    from app.models.pricing import DeliveryFee

    query = DeliveryFee.query.filter(DeliveryFee.branch_id == branch_id)
    if zone_id:
        return query.filter(DeliveryFee.zone_id == zone_id)
    return query.filter(DeliveryFee.client_id == client_id)


def fee_in_effect(branch_id, zone_id=None, client_id=None, on_date=None):
    from app.models.pricing import DeliveryFee

    on_date = on_date or date.today()
    return (
        _fee_rows(branch_id, zone_id, client_id)
        .filter(DeliveryFee.effective_from <= on_date)
        .order_by(DeliveryFee.effective_from.desc(), DeliveryFee.id.desc())
        .first()
    )


def scheduled_fees(branch_id, zone_id=None, client_id=None, after_date=None):
    from app.models.pricing import DeliveryFee

    after_date = after_date or date.today()
    return (
        _fee_rows(branch_id, zone_id, client_id)
        .filter(DeliveryFee.effective_from > after_date)
        .order_by(DeliveryFee.effective_from.asc(), DeliveryFee.id.asc())
        .all()
    )


def active_zones(branch_id):
    from app.models.pricing import DeliveryZone

    return (
        DeliveryZone.query.filter(DeliveryZone.branch_id == branch_id, DeliveryZone.is_active.is_(True))
        .order_by(DeliveryZone.name.asc())
        .all()
    )


def zone_overview(branch_id, on_date=None):
    from app.models.pricing import DeliveryZone

    on_date = on_date or date.today()
    return [
        {
            "zone": zone,
            "current": fee_in_effect(branch_id, zone_id=zone.id, on_date=on_date),
            "scheduled": scheduled_fees(branch_id, zone_id=zone.id, after_date=on_date),
        }
        for zone in DeliveryZone.query.filter_by(branch_id=branch_id).order_by(DeliveryZone.name.asc()).all()
    ]


def client_fee_overview(branch_id, on_date=None):
    from app.models.pricing import DeliveryFee

    on_date = on_date or date.today()
    client_ids = [
        row.client_id
        for row in db.session.query(DeliveryFee.client_id)
        .filter(DeliveryFee.branch_id == branch_id, DeliveryFee.client_id.isnot(None))
        .distinct()
    ]
    if not client_ids:
        return []
    return [
        {
            "client": client,
            "current": fee_in_effect(branch_id, client_id=client.id, on_date=on_date),
            "scheduled": scheduled_fees(branch_id, client_id=client.id, after_date=on_date),
        }
        for client in Client.query.filter(Client.id.in_(client_ids)).order_by(Client.name.asc()).all()
    ]


def _commit():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def create_delivery_zone(branch_id, name, created_by):
    from app.models.pricing import DeliveryZone
    from app.services.audit_log_service import record_audit_log

    name = (name or "").strip()
    if not name:
        raise PricingError("Nama zona wajib diisi.")
    duplicate = DeliveryZone.query.filter(
        DeliveryZone.branch_id == branch_id,
        db.func.lower(DeliveryZone.name) == name.lower(),
    ).first()
    if duplicate:
        raise PricingError(f"Zona {name} sudah ada.")
    zone = DeliveryZone(branch_id=branch_id, name=name, is_active=True)
    db.session.add(zone)
    db.session.flush()
    record_audit_log(
        module="PRICING",
        event_type="DELIVERY_ZONE_CREATED",
        action="CREATE",
        table_name="delivery_zones",
        record_id=zone.id,
        description=f"Zona ongkir {name} dibuat.",
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )
    _commit()
    return zone


def set_delivery_fee(*, branch_id, zone_id=None, client_id=None, fee, effective_from, created_by, notes=None):
    """Tarif baru untuk satu zona atau satu client kontrak (baris lama tidak diubah)."""
    from app.models.pricing import DeliveryFee, DeliveryZone
    from app.services.audit_log_service import record_audit_log

    if bool(zone_id) == bool(client_id):
        raise PricingError("Pilih zona atau client kontrak.")
    amount = _fee_amount(fee)
    if not isinstance(effective_from, date):
        raise PricingError("Tanggal berlaku wajib diisi.")
    if zone_id:
        zone = DeliveryZone.query.get(zone_id)
        if not zone or zone.branch_id != branch_id:
            raise PricingError("Zona tidak ditemukan di cabang ini.")
        target = f"zona {zone.name}"
    else:
        client = Client.query.get(client_id)
        if not client:
            raise PricingError("Client tidak ditemukan.")
        target = f"kontrak {client.name}"

    previous = fee_in_effect(branch_id, zone_id, client_id, effective_from)
    row = DeliveryFee(
        branch_id=branch_id,
        zone_id=zone_id or None,
        client_id=client_id or None,
        fee=amount,
        effective_from=effective_from,
        notes=(notes or "").strip() or None,
        created_by=created_by,
    )
    db.session.add(row)
    db.session.flush()
    previous_note = f" (sebelumnya Rp {Decimal(previous.fee):,.0f})." if previous else "."
    record_audit_log(
        module="PRICING",
        event_type="DELIVERY_FEE_SET",
        action="CREATE",
        table_name="delivery_fees",
        record_id=row.id,
        description=(
            f"Ongkir {target}: Rp {amount:,.0f}/pengiriman berlaku mulai "
            f"{effective_from.strftime('%d-%m-%Y')}{previous_note}"
        ),
        old_value={"fee": str(previous.fee)} if previous else None,
        new_value={"fee": str(amount), "effective_from": effective_from.isoformat()},
        metadata={"zone_id": zone_id, "client_id": client_id},
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )
    _commit()
    return row


def free_delivery_min_portions(branch_id):
    """Ambang gratis ongkir pelanggan umum per pengiriman. 0 = tidak ada gratis ongkir."""
    row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=FREE_DELIVERY_SETTING).first()
    try:
        value = int(str(getattr(row, "setting_value", "") or "").strip())
    except ValueError:
        value = 0
    return max(value, 0)


def _portions_label(value):
    return f"{value} porsi" if value else "tidak ada"


def set_free_delivery_min_portions(branch_id, value, updated_by):
    from app.services.audit_log_service import record_audit_log

    try:
        portions = int(str(value).strip() or "0")
    except (TypeError, ValueError):
        raise PricingError("Ambang gratis ongkir harus angka bulat.")
    if portions < 0:
        raise PricingError("Ambang gratis ongkir tidak boleh minus.")
    before = free_delivery_min_portions(branch_id)
    row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=FREE_DELIVERY_SETTING).first()
    if row:
        row.setting_value = str(portions)
    else:
        db.session.add(BranchSetting(branch_id=branch_id, setting_key=FREE_DELIVERY_SETTING, setting_value=str(portions)))
    record_audit_log(
        module="PRICING",
        event_type="FREE_DELIVERY_THRESHOLD_SET",
        action="UPDATE",
        table_name="branch_settings",
        record_id=branch_id,
        description=(
            f"Gratis ongkir mulai: {_portions_label(before)} → {_portions_label(portions)} per pengiriman."
        ),
        user_id=updated_by,
        branch_id=branch_id,
        commit=False,
    )
    _commit()
    return portions


def quote_trip_fee(branch_id, client, location, qty, on_date=None):
    """Ongkir satu pengiriman: (tarif, asal, pesan_error)."""
    if int(qty or 0) <= 0:
        return ZERO_FEE, None, None
    client_id = getattr(client, "id", None)
    contract_fee = fee_in_effect(branch_id, client_id=client_id, on_date=on_date) if client_id else None
    if contract_fee:
        return Decimal(contract_fee.fee), FEE_SOURCE_CONTRACT, None
    if not is_general_client(client):
        return ZERO_FEE, FEE_SOURCE_INCLUDED, None

    zone_id = getattr(location, "delivery_zone_id", None)
    if not zone_id:
        name = getattr(location, "location_name", "ini")
        return None, None, f"Lokasi {name} belum punya zona ongkir. Admin perlu memilih zonanya di data lokasi."
    zone_fee = fee_in_effect(branch_id, zone_id=zone_id, on_date=on_date)
    if not zone_fee:
        return None, None, "Tarif ongkir zona lokasi ini belum diatur. OWNER perlu mengisinya di Harga & Ongkir."
    threshold = free_delivery_min_portions(branch_id)
    if threshold and int(qty) >= threshold:
        return ZERO_FEE, FEE_SOURCE_FREE, None
    return Decimal(zone_fee.fee), FEE_SOURCE_ZONE, None


def order_trip_fees(branch_id, client, location, lunch_qty, dinner_qty, on_date=None):
    """Ongkir kiriman siang dan malam untuk satu baris order: (siang, malam, pesan_error)."""
    lunch_fee, _, error = quote_trip_fee(branch_id, client, location, lunch_qty, on_date)
    if error:
        return None, None, error
    dinner_fee, _, error = quote_trip_fee(branch_id, client, location, dinner_qty, on_date)
    if error:
        return None, None, error
    return lunch_fee, dinner_fee, None


# --- laporan per jalur ----------------------------------------------------

PATH_FILTER_CHOICES = (("", "Semua"), (PATH_CONTRACT, "Kontrak"), (PATH_GENERAL, "Umum"))
_INACTIVE_INVOICE_STATUSES = {"CANCELLED", "CANCELED"}


def requested_path(value):
    """Filter jalur dari query string; selain KONTRAK/UMUM berarti semua."""
    value = str(value or "").strip().upper()
    return value if value in CUSTOMER_PATHS else None


def invoice_path_breakdown(invoices):
    """Jumlah, total, dibayar, dan sisa invoice aktif per jalur (tanpa jalur = TANPA)."""
    rows = {key: {"count": 0, "total": Decimal("0"), "paid": Decimal("0"), "remaining": Decimal("0")}
            for key in (PATH_CONTRACT, PATH_GENERAL, "TANPA")}
    for invoice in invoices:
        if str(getattr(invoice, "status", "") or "").upper() in _INACTIVE_INVOICE_STATUSES:
            continue
        row = rows[getattr(invoice, "customer_path", None) or "TANPA"]
        row["count"] += 1
        row["total"] += Decimal(str(invoice.total_amount or 0))
        row["paid"] += Decimal(str(invoice.paid_amount or 0))
        row["remaining"] += Decimal(str(invoice.remaining_amount or 0))
    return rows
