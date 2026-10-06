from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account
from app.models.finance import BankAccount, CashBankAdjustment
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import PortalOrderDraft, PortalUserMapping
from app.services.cash_bank_service import (
    ADJUSTMENT_CATEGORIES,
    create_cash_bank_adjustment,
    create_cash_bank_adjustment_record,
)
from app.services.portal_order_draft_service import (
    _pick_unique_code,
    create_portal_order_draft,
    draft_total_amount,
)
from app.services.prepaid_order_service import (
    draft_prepaid_amount,
    draft_transfer_amount,
    draft_unique_code_amount,
    record_draft_prepayment,
)
from app.services.pricing_service import (
    PATH_CONTRACT,
    PATH_GENERAL,
    create_delivery_zone,
    set_delivery_fee,
    set_portion_price,
)
from tests.test_prepaid_orders import _ensure_accounts, _setup, ctx  # noqa: F401

TODAY = date.today()


def _setup_customer_portal(db, s, path=PATH_GENERAL):
    mapping = PortalUserMapping(
        user_id=s.portal_customer.id,
        principal_type="DELEGATE",
        client_id=s.client.id,
        mandor_id=s.mandor.id,
        delivery_location_id=s.location.id,
        access_level="DRAFT_ORDER",
        is_active=True,
    )
    db.session.add(mapping)
    db.session.flush()
    return mapping


def _setup_mandor_portal(db, s):
    contract_client = Client(
        name=f"PT Mandor {uuid4().hex[:6]}",
        phone="0812",
        is_active=True,
        customer_path=PATH_CONTRACT,
    )
    db.session.add(contract_client)
    db.session.flush()
    mandor_obj = Mandor(
        branch_id=s.branch.id,
        client_id=contract_client.id,
        name=contract_client.name,
        is_active=True,
    )
    db.session.add(mandor_obj)
    db.session.flush()
    mandor_location = DeliveryLocation(
        mandor_id=mandor_obj.id,
        location_name="Proyek Mandor",
        is_active=True,
        delivery_zone_id=s.zone.id,
    )
    db.session.add(mandor_location)
    db.session.flush()
    mandor_user = User(
        branch_id=s.branch.id,
        full_name="Mandor User Uji",
        username=f"pre-mandor-{uuid4().hex[:8]}",
        password_hash="x",
        role="PORTAL_SUBCLIENT",
        is_active=True,
    )
    db.session.add(mandor_user)
    db.session.flush()
    mapping = PortalUserMapping(
        user_id=mandor_user.id,
        principal_type="MANDOR",
        client_id=contract_client.id,
        mandor_id=mandor_obj.id,
        delivery_location_id=mandor_location.id,
        access_level="DRAFT_ORDER",
        is_active=True,
    )
    db.session.add(mapping)
    db.session.flush()
    return mandor_user, mandor_location


def test_draft_pelanggan_umum_dapat_kode_unik_mandor_none(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    mandor_user, mandor_location = _setup_mandor_portal(ctx, s)

    # Pelanggan umum -> draft dapat kode unik 1-999
    form_cust = {
        "order_date": (TODAY + timedelta(days=2)).isoformat(),
        "meal_type": "LUNCH",
        "portion_qty": "12",
        "delivery_location_id": str(s.location.id),
        "idempotency_key": uuid4().hex,
    }
    draft_cust, ok_cust, err_cust = create_portal_order_draft(s.portal_customer, form_cust)
    assert ok_cust, err_cust
    assert draft_cust.payment_unique_code is not None
    assert 1 <= draft_cust.payment_unique_code <= 999

    # Mandor / subclient (jalur tempo/kontrak) -> kode unik None
    form_mandor = {
        "order_date": (TODAY + timedelta(days=2)).isoformat(),
        "meal_type": "DINNER",
        "portion_qty": "12",
        "delivery_location_id": str(mandor_location.id),
        "idempotency_key": uuid4().hex,
    }
    draft_mandor, ok_mandor, err_mandor = create_portal_order_draft(mandor_user, form_mandor)
    assert ok_mandor, err_mandor
    assert draft_mandor.payment_unique_code is None


def test_tiga_puluh_draft_pending_cabang_sama_kode_selalu_unik(ctx):
    s = _setup(ctx)
    codes = set()
    for i in range(30):
        code = _pick_unique_code(s.branch.id)
        assert code is not None
        assert 1 <= code <= 999
        assert code not in codes
        codes.add(code)
        # Simpan draft dummy dengan kode ini agar _pick_unique_code mendeteksinya sebagai terpakai
        draft = PortalOrderDraft(
            user_id=s.portal_customer.id,
            branch_id=s.branch.id,
            client_id=s.client.id,
            mandor_id=s.mandor.id,
            delivery_location_id=s.location.id,
            order_date=TODAY + timedelta(days=i + 1),
            meal_type="LUNCH",
            portion_qty=12,
            price_per_portion=Decimal("25000"),
            delivery_fee=Decimal("15000"),
            payment_unique_code=code,
            idempotency_key=uuid4().hex,
            status="PENDING_ADMIN_CONFIRMATION",
        )
        ctx.session.add(draft)
        ctx.session.flush()

    assert len(codes) == 30


def test_draft_transfer_amount_dan_unique_code_calculation(ctx):
    s = _setup(ctx)
    draft = PortalOrderDraft(
        user_id=s.portal_customer.id,
        branch_id=s.branch.id,
        client_id=s.client.id,
        mandor_id=s.mandor.id,
        delivery_location_id=s.location.id,
        order_date=TODAY + timedelta(days=2),
        meal_type="LUNCH",
        portion_qty=12,
        price_per_portion=Decimal("25000"),
        price_source="STANDAR",
        delivery_fee=Decimal("15000"),
        payment_unique_code=237,
        idempotency_key=uuid4().hex,
        status="PENDING_ADMIN_CONFIRMATION",
    )
    ctx.session.add(draft)
    ctx.session.flush()

    # Total: 12 * 25.000 + 15.000 = 315.000
    assert draft_total_amount(draft) == Decimal("315000.00")
    assert draft_prepaid_amount(draft) == Decimal("0.00")
    assert draft_unique_code_amount(draft) == Decimal("237.00")
    # Transfer pertama = total + kode = 315.237
    assert draft_transfer_amount(draft) == Decimal("315237.00")

    # Catat pembayaran parsial Rp 100.000
    record_draft_prepayment(draft=draft, amount=Decimal("100000"), payment_method="CASH", created_by=s.admin.id)
    assert draft_prepaid_amount(draft) == Decimal("100000.00")
    # Setelah ada uang muka, kode unik tidak berlaku lagi (= 0)
    assert draft_unique_code_amount(draft) == Decimal("0.00")
    # Sisa = 315.000 - 100.000 = 215.000
    assert draft_transfer_amount(draft) == Decimal("215000.00")


def test_kategori_kode_unik_ditolak_manual_dan_tidak_muncul_di_halaman(app, ctx):
    s = _setup(ctx)

    # 1. Halaman penyesuaian kas/bank tidak memuat opsi KODE_UNIK di select manual
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(s.admin.id)
        session["_fresh"] = True

    resp = client.get("/finance/cash-bank-adjustments")
    assert resp.status_code == 200, f"Redirected to: {resp.headers.get('Location')}"
    html = resp.get_data(as_text=True)
    assert 'value="KODE_UNIK"' not in html
    assert "Kode unik transfer pelanggan" not in html
    assert 'value="SELISIH"' in html

    # 2. create_cash_bank_adjustment manual ditolak
    with pytest.raises(Exception, match="hanya dibuat otomatis oleh sistem"):
        create_cash_bank_adjustment(
            adjustment_date=TODAY,
            account_type="CASH",
            bank_account_id=None,
            adjustment_type="INCREASE",
            amount=237,
            reason="Uji manual kode unik",
            created_by=s.admin.id,
            branch_id=s.branch.id,
            category="KODE_UNIK",
            allow_system_category=False,
            commit=False,
        )

    # 3. create_cash_bank_adjustment_record manual juga ditolak
    with pytest.raises(Exception, match="hanya dibuat otomatis oleh sistem"):
        create_cash_bank_adjustment_record(
            adjustment_date=TODAY,
            account_type="CASH",
            bank_account_id=None,
            adjustment_type="INCREASE",
            amount=237,
            reason="Uji manual kode unik",
            created_by=s.admin.id,
            branch_id=s.branch.id,
            category="KODE_UNIK",
            allow_system_category=False,
        )
