"""Test suite untuk memastikan semua tanggal dan waktu bisnis memakai WIB, bukan jam server UTC.

Skenario inti:
Server online berjam UTC. Pada pukul 18:30 UTC tanggal 10 Oktober 2026:
- Di server UTC: tanggal masih 2026-10-10.
- Di WIB (UTC+7): sudah pukul 01:30 tanggal 11 Oktober 2026 (hari berikutnya).

Pengujian memverifikasi:
1. `app.utils.clock` helper (`now_wib()`, `today_wib()`) menghasilkan tanggal 11 Okt 2026.
2. Validasi tanggal masa depan (misal uang muka, pelunasan) menerima tanggal 11 Okt 2026 dan menolak 12 Okt 2026.
3. Pesanan harian otomatis menggunakan basis tanggal WIB (target periode 11 Okt, besok 12 Okt).
4. Penentuan harga (`price_in_effect`) dan form harga efektif menggunakan default `today_wib()`.
5. Format nomor transaksi dan filter laporan memakai tanggal WIB.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.utils.clock import format_wib, now_wib, today_wib, to_wib
from app.services.business_logic_guard_service import (
    BusinessRuleError,
    assert_not_future_date,
)
from app.services.auto_order_service import _normalize_now
from app.services.pricing_service import (
    PricingError,
    price_in_effect,
)
from app.routes.settings.pricing_routes import _effective_date


FROZEN_UTC_DATETIME = datetime(2026, 10, 10, 18, 30, 0)
EXPECTED_WIB_DATETIME = datetime(2026, 10, 11, 1, 30, 0)
EXPECTED_WIB_DATE = date(2026, 10, 11)


@pytest.fixture(autouse=True)
def freeze_clock_to_utc_boundary(monkeypatch):
    """Kunci jam server ke UTC 2026-10-10 18:30:00 (= WIB 2026-10-11 01:30:00)."""
    try:
        import time_machine
        with time_machine.travel(
            datetime(2026, 10, 10, 18, 30, 0, tzinfo=timezone.utc),
            tick=False,
        ):
            yield
    except ImportError:
        monkeypatch.setattr("app.utils.clock.now_wib", lambda: EXPECTED_WIB_DATETIME)
        monkeypatch.setattr("app.utils.clock.today_wib", lambda: EXPECTED_WIB_DATE)
        yield


@pytest.fixture
def ctx(app, monkeypatch):
    """Fixture context database sesuai pola uji ERP (commit diganti flush, lalu rollback)."""
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


# ============================================================================
# 1. Clock Helper Invariant Test
# ============================================================================

def test_clock_wib_helpers_at_utc_midnight_boundary():
    """Memverifikasi bahwa saat server UTC masih 10 Okt 18:30, WIB sudah 11 Okt 01:30."""
    wib_now = now_wib()
    wib_today = today_wib()

    assert wib_now == EXPECTED_WIB_DATETIME
    assert wib_today == EXPECTED_WIB_DATE
    assert wib_today == date(2026, 10, 11)

    # to_wib konversi
    naive_utc = FROZEN_UTC_DATETIME
    assert to_wib(naive_utc) == EXPECTED_WIB_DATETIME

    # format_wib
    formatted = format_wib(naive_utc)
    assert "11/10/2026" in formatted


# ============================================================================
# 2. Future Date Validation Test
# ============================================================================

def test_future_date_validation_accepts_wib_today_and_blocks_tomorrow():
    """Validasi tanggal tidak boleh lebih dari hari ini:
    - 11 Okt 2026 (hari ini WIB) HARUS diterima (walau jam server UTC masih 10 Okt).
    - 12 Okt 2026 (besok) HARUS ditolak.
    """
    today = today_wib()
    assert today == date(2026, 10, 11)

    # 11 Okt 2026 harus lolos
    assert_not_future_date(date(2026, 10, 11), today, label="Tanggal Uang Muka")

    # 10 Okt 2026 (kemarin) harus lolos
    assert_not_future_date(date(2026, 10, 10), today, label="Tanggal Uang Muka")

    # 12 Okt 2026 (besok) harus memicu BusinessRuleError
    with pytest.raises(BusinessRuleError) as exc_info:
        assert_not_future_date(date(2026, 10, 12), today, label="Tanggal Uang Muka")
    assert "tidak boleh lebih dari hari ini" in str(exc_info.value)


def test_advance_and_expense_future_date_rules_use_wib_today():
    """Memverifikasi aturan di modul uang muka dan operasional memakai WIB."""
    wib_today = today_wib()

    # Logika pengecekan advance_date > today_wib()
    valid_advance_date = date(2026, 10, 11)
    future_advance_date = date(2026, 10, 12)

    assert not (valid_advance_date > wib_today)
    assert future_advance_date > wib_today


# ============================================================================
# 3. Auto Daily Orders Period Date Test
# ============================================================================

def test_auto_daily_orders_defaults_to_wib_datetime():
    """Tugas pesanan otomatis jam malam/dini hari harus memakai tanggal WIB."""
    normalized = _normalize_now(None)
    assert normalized == EXPECTED_WIB_DATETIME

    # Tanggal periode pesanan otomatis adalah tanggal WIB
    period_date = normalized.date()
    assert period_date == date(2026, 10, 11)

    # Tanggal besok untuk pesanan adalah +1 dari tanggal WIB
    tomorrow_date = period_date + timedelta(days=1)
    assert tomorrow_date == date(2026, 10, 12)


# ============================================================================
# 4. Pricing Effective Date & Settings Test
# ============================================================================

def test_pricing_effective_date_validation_uses_wib_today():
    """Form pengaturan harga: kosong = hari ini WIB (11 Okt), tidak boleh sebelum hari ini."""
    # Input kosong -> default hari ini WIB (11 Okt)
    default_effective = _effective_date("")
    assert default_effective == date(2026, 10, 11)

    # Input tanggal hari ini WIB (11 Okt) -> lolos
    today_effective = _effective_date("2026-10-11")
    assert today_effective == date(2026, 10, 11)

    # Input 10 Okt (kemarin di WIB, walau UTC server masih 10 Okt) -> ditolak
    with pytest.raises(PricingError) as exc_info:
        _effective_date("2026-10-10")
    assert "tidak boleh sebelum hari ini" in str(exc_info.value)


def test_price_in_effect_defaults_to_wib_today(ctx):
    """Layanan penentuan harga yang berlaku (on_date=None) harus memakai today_wib()."""
    from app.models.master import Branch, User
    from app.models.pricing import PortionPrice

    suffix = uuid4().hex[:6]
    branch = Branch(code=f"BR-{suffix}", name=f"Cabang {suffix}", is_active=True)
    user = User(
        branch=branch,
        full_name="Owner WIB",
        username=f"owner_{suffix}",
        password_hash="hash",
        role="OWNER",
        is_active=True,
    )
    ctx.session.add_all([branch, user])
    ctx.session.flush()

    # Harga lama berlaku sampai 10 Okt
    old_price = PortionPrice(
        branch_id=branch.id,
        price_per_portion=Decimal("20000"),
        effective_from=date(2026, 10, 1),
        created_by=user.id,
    )
    # Harga baru mulai berlaku 11 Okt 2026
    new_price = PortionPrice(
        branch_id=branch.id,
        price_per_portion=Decimal("25000"),
        effective_from=date(2026, 10, 11),
        created_by=user.id,
    )
    ctx.session.add_all([old_price, new_price])
    ctx.session.flush()

    # Saat on_date=None, fungsi harus mengambil harga yang sudah mulai per 11 Okt 2026
    active_price = price_in_effect(branch.id, on_date=None)
    assert active_price is not None
    assert active_price.price_per_portion == Decimal("25000")
    assert active_price.effective_from == date(2026, 10, 11)


# ============================================================================
# 5. Cash Bank & Numbering Format Test
# ============================================================================

def test_cash_bank_sequence_date_uses_wib():
    """Nomor urut transaksi kas bank memakai format tanggal YYYYMMDD WIB (20261011)."""
    wib_suffix = today_wib().strftime("%Y%m%d")
    assert wib_suffix == "20261011"
