"""Siklus kontrak pelanggan otomatis.

Keputusan owner 2026-09-28 yang dikunci di sini:
- kontrak yang lewat tanggal berakhir otomatis Kedaluwarsa lewat sapuan harian,
  tercatat di audit log;
- pengingat mulai H-30, mendesak mulai H-7; kontrak yang sudah berakhir dan
  belum diperpanjang punya satu pemberitahuan mendesak yang hilang sendiri
  setelah diperpanjang;
- sesudah kontrak berakhir, termin invoice kembali ke 7 hari;
- pesanan baru (internal maupun portal) untuk client itu perlu keputusan
  OWNER sampai kontraknya diperpanjang.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

TODAY = date.today()


@pytest.fixture
def ctx(app, monkeypatch):
    """Tanpa commit ke test_db: semua di-flush lalu di-rollback."""
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _setup(db):
    from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
    from app.services.pricing_service import PATH_CONTRACT

    branch = Branch(code=f"KTR-{uuid4().hex[:8]}", name="Cabang Uji Kontrak", is_active=True)
    client = Client(name=f"PT Uji {uuid4().hex[:6]}", phone="0811", is_active=True, customer_path=PATH_CONTRACT)
    db.session.add_all([branch, client])
    db.session.flush()
    users = {
        role: User(
            branch_id=branch.id, full_name=f"{role} Uji", username=f"ktr-{role.lower()}-{uuid4().hex[:8]}",
            password_hash="x", role=role, is_active=True,
        )
        for role in ("OWNER", "ADMIN", "PORTAL_CLIENT")
    }
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {uuid4().hex[:6]}", is_active=True)
    db.session.add_all([mandor, *users.values()])
    db.session.flush()
    location = DeliveryLocation(mandor_id=mandor.id, location_name="Proyek A", is_active=True)
    db.session.add(location)
    db.session.flush()
    return SimpleNamespace(branch=branch, client=client, mandor=mandor, location=location, **{
        role.lower(): user for role, user in users.items()
    })


def _contract(db, s, end_date, *, status="ACTIVE", terms="net 30", client=None):
    from app.models.contract import CustomerContract

    contract = CustomerContract(
        branch_id=s.branch.id, client_id=(client or s.client).id, contract_number=f"KTR-{uuid4().hex[:10]}",
        title="Kontrak Katering", start_date=end_date - timedelta(days=180), end_date=end_date,
        payment_terms=terms, credit_limit=Decimal("0"), status=status, created_by=s.owner.id,
    )
    db.session.add(contract)
    db.session.flush()
    return contract


def _notification(key):
    from app.models.system import Notification

    return Notification.query.filter_by(generated_key=key).first()


def _draft(db, s):
    from app.models.system import PortalOrderDraft

    draft = PortalOrderDraft(
        user_id=s.portal_client.id, branch_id=s.branch.id, client_id=s.client.id, mandor_id=s.mandor.id,
        delivery_location_id=s.location.id, order_date=TODAY + timedelta(days=2), meal_type="LUNCH",
        portion_qty=10, price_per_portion=Decimal("25000"), price_source="KONTRAK",
        delivery_fee=Decimal("0"), idempotency_key=uuid4().hex,
    )
    db.session.add(draft)
    db.session.flush()
    return draft


def _contract_gate(draft, **kwargs):
    from app.services.portal_order_draft_service import evaluate_portal_order_draft_gate

    gate = evaluate_portal_order_draft_gate(draft, **kwargs)
    return gate, next(item for item in gate["gates"] if item["key"] == "CONTRACT")


# --- sapuan harian --------------------------------------------------------

def test_sapuan_mengakhiri_kontrak_lewat_tanggal_dan_mencatat_audit(ctx):
    from app.models.system import AuditLog
    from app.services.contract_lifecycle_service import sweep_contracts

    s = _setup(ctx)
    overdue = _contract(ctx, s, TODAY - timedelta(days=1))
    still_running = _contract(ctx, s, TODAY)  # berakhir hari ini = masih berlaku hari ini

    result = sweep_contracts(s.branch.id, TODAY)

    assert overdue.status == "EXPIRED"
    assert still_running.status == "ACTIVE"
    assert result["expired"] == 1
    assert AuditLog.query.filter_by(
        event_type="CUSTOMER_CONTRACT_EXPIRED", table_name="customer_contracts", record_id=overdue.id
    ).count() == 1

    # Aman dijalankan ulang: tidak ada audit ganda.
    assert sweep_contracts(s.branch.id, TODAY)["expired"] == 0
    assert AuditLog.query.filter_by(event_type="CUSTOMER_CONTRACT_EXPIRED", record_id=overdue.id).count() == 1


def test_pengingat_h30_jadi_mendesak_di_h7(ctx):
    from app.models.system import Notification
    from app.services.contract_lifecycle_service import sweep_contracts

    s = _setup(ctx)
    other = _setup(ctx)
    soon = _contract(ctx, s, TODAY + timedelta(days=20))
    urgent = _contract(ctx, other, TODAY + timedelta(days=5))
    far = _contract(ctx, s, TODAY + timedelta(days=60))

    sweep_contracts(s.branch.id, TODAY)
    sweep_contracts(other.branch.id, TODAY)

    def reminder(contract):
        return Notification.query.filter_by(
            notification_type="CUSTOMER_CONTRACT_EXPIRY", reference_id=contract.id, branch_id=contract.branch_id
        ).first()

    assert reminder(soon).priority == "WARNING"
    assert reminder(urgent).priority == "CRITICAL"
    assert reminder(far) is None
    assert reminder(soon).action_url == "/customer-success/contracts"


def test_kontrak_berakhir_punya_pemberitahuan_yang_hilang_setelah_diperpanjang(ctx):
    from app.services.contract_lifecycle_service import LAPSED_KEY_PREFIX, sweep_contracts
    from app.services.customer_contract_service import renew_customer_contract

    s = _setup(ctx)
    contract = _contract(ctx, s, TODAY - timedelta(days=3))
    key = f"{LAPSED_KEY_PREFIX}:{s.branch.id}:{s.client.id}"

    assert sweep_contracts(s.branch.id, TODAY)["lapsed"] == 1
    notification = _notification(key)
    assert notification.priority == "CRITICAL"
    assert notification.status == "UNREAD"

    renew_customer_contract(
        contract.id, branch_id=s.branch.id, start_date=TODAY, end_date=TODAY + timedelta(days=365),
        created_by=s.admin.id, commit=False,
    )
    assert sweep_contracts(s.branch.id, TODAY)["lapsed"] == 0
    assert _notification(key).status == "RESOLVED"


def test_penyapu_harian_menjalankan_kontrak_sebelum_kredit(ctx):
    from app.services.credit_account_service import daily_sweep

    s = _setup(ctx)
    contract = _contract(ctx, s, TODAY - timedelta(days=1))

    result = daily_sweep(s.branch.id, today=TODAY)

    assert contract.status == "EXPIRED"
    assert result["contracts"]["expired"] == 1
    assert "checked" in result and "escalated" in result


def test_periksa_kontrak_sekarang_menyimpan_hasilnya(ctx):
    from app.services.contract_lifecycle_service import run_contract_sweep_now

    s = _setup(ctx)
    contract = _contract(ctx, s, TODAY - timedelta(days=1))

    result = run_contract_sweep_now(s.branch.id, actor_id=s.admin.id, today=TODAY)

    assert result == {"expired": 1, "reminders": 0, "lapsed": 1}
    assert contract.status == "EXPIRED"
    assert contract.updated_by == s.admin.id


# --- termin ---------------------------------------------------------------

def test_termin_kembali_ke_7_hari_setelah_kontrak_berakhir(ctx):
    from app.services.contract_lifecycle_service import sweep_contracts
    from app.services.credit_control_service import resolve_due_date

    s = _setup(ctx)
    _contract(ctx, s, TODAY - timedelta(days=1), terms="net 30")
    assert resolve_due_date(TODAY, branch_id=s.branch.id, client_id=s.client.id) == TODAY + timedelta(days=30)

    sweep_contracts(s.branch.id, TODAY)

    assert resolve_due_date(TODAY, branch_id=s.branch.id, client_id=s.client.id) == TODAY + timedelta(days=7)


# --- pesanan internal -----------------------------------------------------

def test_order_internal_client_kontrak_berakhir_hanya_owner(ctx):
    from app.services.credit_control_service import check_internal_order_credit

    s = _setup(ctx)
    _contract(ctx, s, TODAY - timedelta(days=10), status="EXPIRED")

    ok, message, _ = check_internal_order_credit(
        branch_id=s.branch.id, mandor_id=s.mandor.id, amount=250000, actor_role="ADMIN"
    )
    assert not ok
    assert "berakhir" in message and "Hanya OWNER" in message

    ok, message, _ = check_internal_order_credit(
        branch_id=s.branch.id, mandor_id=s.mandor.id, amount=250000, actor_role="OWNER"
    )
    assert ok
    assert "keputusan OWNER" in message


def test_order_internal_tidak_ditahan_kalau_sudah_diperpanjang_atau_tanpa_kontrak(ctx):
    from app.services.credit_control_service import check_internal_order_credit

    s = _setup(ctx)
    ok, _, _ = check_internal_order_credit(branch_id=s.branch.id, mandor_id=s.mandor.id, amount=1, actor_role="ADMIN")
    assert ok  # belum pernah berkontrak: aturan kredit biasa

    _contract(ctx, s, TODAY - timedelta(days=10), status="EXPIRED")
    _contract(ctx, s, TODAY + timedelta(days=300))
    ok, message, _ = check_internal_order_credit(
        branch_id=s.branch.id, mandor_id=s.mandor.id, amount=1, actor_role="ADMIN"
    )
    assert ok
    assert not message or "berakhir" not in message


# --- pesanan portal -------------------------------------------------------

def test_draft_portal_kontrak_berakhir_ditahan_dan_bisa_diloloskan_owner(ctx):
    from app.models.system import AuditLog
    from app.services.portal_order_draft_service import _owner_override_reasons

    s = _setup(ctx)
    draft = _draft(ctx, s)
    gate, contract_gate = _contract_gate(draft)
    assert contract_gate["status"] == "OK"

    lapsed = _contract(ctx, s, TODAY - timedelta(days=2), status="EXPIRED")
    gate, contract_gate = _contract_gate(draft)
    assert contract_gate["status"] == "BLOCKED"
    assert not gate["can_confirm"]
    assert _owner_override_reasons(gate) == ["kontrak sudah berakhir"]

    gate, contract_gate = _contract_gate(draft, owner_override=True)
    assert contract_gate["status"] == "OVERRIDE"
    assert contract_gate["contract_id"] == lapsed.id

    from app.services.portal_order_draft_service import confirm_portal_order_draft

    _, converted, error = confirm_portal_order_draft(draft.id, s.admin, review_note="x", owner_override=True)
    assert not converted and "berakhir" in error

    _, converted, error = confirm_portal_order_draft(draft.id, s.owner, review_note="", owner_override=True)
    assert not converted and "alasan" in error

    _, converted, error = confirm_portal_order_draft(
        draft.id, s.owner, review_note="Perpanjangan sedang ditandatangani", owner_override=True
    )
    assert converted, error
    audit = AuditLog.query.filter_by(event_type="CONTRACT_OVERRIDE", record_id=draft.id).one()
    assert "Perpanjangan sedang ditandatangani" in audit.description
