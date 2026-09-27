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
