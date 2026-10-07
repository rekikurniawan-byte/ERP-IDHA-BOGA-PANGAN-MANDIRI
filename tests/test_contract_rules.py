"""Test suite untuk Fase 3: Pengaturan kontrak (fondasi).

Mencakup:
1. Simpan & tampilkan pengaturan kontrak (jam lock, libur rutin & khusus, siklus, anchor, jatuh tempo, pengadilan, ta'zir).
2. Validasi aturan kontrak (lock siang >= malam ditolak, due_days < 1 ditolak, ta'zir < 0 ditolak, libur di luar rentang ditolak).
3. lock_time_for dan session_closed_reason cutoff portal.
4. is_contract_holiday (rutin mingguan & libur khusus).
5. billing_mode_for (override sub client vs bawaan kontrak vs legacy).
6. due_days_for dan resolve_due_date invoice (invoice baru mengikuti aturan, invoice lama tidak berubah).
7. next_cycle_cutoff untuk WEEKLY, BIWEEKLY, MONTHLY (termasuk penyesuaian akhir bulan 31 Jan -> 28 Feb).
8. Hak akses ubah aturan (hanya OWNER/ADMIN) dan pencatatan audit log.
9. Hubungan Driver.user_id dan resolusi reminder pengantar.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.contract import (
    COURT_KAYUAGUNG,
    COURT_PANGKALAN_BALAI,
    ContractHoliday,
    CustomerContract,
)
from app.models.credit import (
    BILLING_CASH,
    BILLING_DIRECT,
    BILLING_VIA_CLIENT,
    PARTY_MANDOR,
    CreditAccount,
)
from app.models.finance import Invoice
from app.models.master import Branch, Client, DeliveryLocation, Driver, Mandor, User
from app.models.system import AuditLog
from app.services.contract_rules_service import (
    active_contract_for,
    billing_mode_for,
    due_days_for,
    is_contract_holiday,
    lock_time_for,
    next_cycle_cutoff,
)
from app.services.credit_account_service import get_or_create_credit_account
from app.services.credit_control_service import resolve_due_date
from app.services.customer_contract_service import (
    CONTRACT_STATUS_ACTIVE,
    CustomerContractError,
    create_customer_contract,
    update_customer_contract_rules,
)
from app.services.live_reminder_service import _get_driver_ids_for_user
from app.services.portal_order_draft_service import session_closed_reason


@pytest.fixture
def ctx(app, monkeypatch):
    """Tanpa commit permanen ke database: flush dan rollback di akhir fixture."""
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _make_fixtures(db):
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"BR-{suffix}", name=f"Cabang Uji {suffix}", is_active=True)
    client = Client(name=f"PT Katering {suffix}", phone="0812345678", is_active=True)
    db.session.add_all([branch, client])
    db.session.flush()

    owner = User(
        branch_id=branch.id,
        full_name="Owner Uji",
        username=f"owner_{suffix}",
        password_hash="hash",
        role="OWNER",
        is_active=True,
    )
    admin = User(
        branch_id=branch.id,
        full_name="Admin Uji",
        username=f"admin_{suffix}",
        password_hash="hash",
        role="ADMIN",
        is_active=True,
    )
    dapur = User(
        branch_id=branch.id,
        full_name="Dapur Uji",
        username=f"dapur_{suffix}",
        password_hash="hash",
        role="DAPUR",
        is_active=True,
    )
    pengantar_user = User(
        branch_id=branch.id,
        full_name="Akun Pengantar",
        username=f"driver_user_{suffix}",
        password_hash="hash",
        role="PENGANTAR",
        is_active=True,
    )
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor Proyek {suffix}", is_active=True)
    db.session.add_all([owner, admin, dapur, pengantar_user, mandor])
    db.session.flush()

    location = DeliveryLocation(mandor_id=mandor.id, location_name="Titik Serah A", is_active=True)
    db.session.add(location)
    db.session.flush()

    return SimpleNamespace(
        branch=branch,
        client=client,
        owner=owner,
        admin=admin,
        dapur=dapur,
        pengantar_user=pengantar_user,
        mandor=mandor,
        location=location,
    )


def test_contract_settings_save_and_display(ctx):
    s = _make_fixtures(ctx)
    start_d = date(2026, 10, 1)
    end_d = date(2026, 12, 31)

    contract = create_customer_contract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        title="Kontrak Operasional Utama",
        start_date=start_d,
        end_date=end_d,
        payment_terms="Net 14",
        credit_limit=Decimal("50000000"),
        status=CONTRACT_STATUS_ACTIVE,
        created_by=s.owner.id,
        lunch_lock_time="09:30",
        dinner_lock_time="14:30",
        weekly_holidays=["7"],
        default_billing_mode="DIRECT",
        billing_cycle="WEEKLY",
        billing_anchor_date=date(2026, 10, 5),
        due_days=14,
        dispute_court=COURT_KAYUAGUNG,
        tazir_amount=Decimal("25000"),
        holidays=[
            {"holiday_date": "2026-10-15", "note": "Libur Proyek"},
            {"holiday_date": "2026-11-20", "note": "Cuti Bersama"},
        ],
    )

    assert contract.lunch_lock_time == time(9, 30)
    assert contract.dinner_lock_time == time(14, 30)
    assert contract.weekly_holidays == "7"
    assert contract.default_billing_mode == "DIRECT"
    assert contract.billing_cycle == "WEEKLY"
    assert contract.billing_anchor_date == date(2026, 10, 5)
    assert contract.due_days == 14
    assert contract.dispute_court == COURT_KAYUAGUNG
    assert contract.tazir_amount == Decimal("25000")

    holidays = ContractHoliday.query.filter_by(contract_id=contract.id).order_by(ContractHoliday.holiday_date.asc()).all()
    assert len(holidays) == 2
    assert holidays[0].holiday_date == date(2026, 10, 15)
    assert holidays[0].note == "Libur Proyek"
    assert holidays[1].holiday_date == date(2026, 11, 20)


def test_contract_settings_validations(ctx):
    s = _make_fixtures(ctx)
    start_d = date(2026, 10, 1)
    end_d = date(2026, 10, 31)

    # 1. Lock siang >= lock malam ditolak
    with pytest.raises(CustomerContractError, match="Jam lock siang harus lebih awal"):
        create_customer_contract(
            branch_id=s.branch.id,
            client_id=s.client.id,
            title="Kontrak Error 1",
            start_date=start_d,
            end_date=end_d,
            payment_terms="Net 7",
            created_by=s.owner.id,
            lunch_lock_time="15:00",
            dinner_lock_time="10:00",
        )

    # 2. Jam di luar rentang 05:00-20:00 ditolak
    with pytest.raises(CustomerContractError, match="di antara 05:00 dan 20:00"):
        create_customer_contract(
            branch_id=s.branch.id,
            client_id=s.client.id,
            title="Kontrak Error 2",
            start_date=start_d,
            end_date=end_d,
            payment_terms="Net 7",
            created_by=s.owner.id,
            lunch_lock_time="04:30",
            dinner_lock_time="15:00",
        )

    # 3. due_days 0 atau negatif ditolak
    with pytest.raises(CustomerContractError, match="Jatuh tempo harus antara 1 sampai 60 hari"):
        create_customer_contract(
            branch_id=s.branch.id,
            client_id=s.client.id,
            title="Kontrak Error 3",
            start_date=start_d,
            end_date=end_d,
            payment_terms="Net 7",
            created_by=s.owner.id,
            due_days=0,
        )

    # 4. ta'zir negatif ditolak
    with pytest.raises(CustomerContractError, match="Nominal ta'zir tidak boleh negatif"):
        create_customer_contract(
            branch_id=s.branch.id,
            client_id=s.client.id,
            title="Kontrak Error 4",
            start_date=start_d,
            end_date=end_d,
            payment_terms="Net 7",
            created_by=s.owner.id,
            tazir_amount=Decimal("-5000"),
        )

    # 5. Tanggal libur di luar masa kontrak ditolak
    with pytest.raises(CustomerContractError, match="berada di luar masa kontrak"):
        create_customer_contract(
            branch_id=s.branch.id,
            client_id=s.client.id,
            title="Kontrak Error 5",
            start_date=start_d,
            end_date=end_d,
            payment_terms="Net 7",
            created_by=s.owner.id,
            holidays=[{"holiday_date": "2026-11-05", "note": "Di luar Oktober"}],
        )


def test_lock_time_for_and_session_closed_reason(ctx):
    s = _make_fixtures(ctx)
    today = date(2026, 10, 10)

    # Buat kontrak aktif dengan lunch lock 09:30
    create_customer_contract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        title="Kontrak Jam Khusus",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        payment_terms="Net 7",
        status=CONTRACT_STATUS_ACTIVE,
        created_by=s.owner.id,
        lunch_lock_time="09:30",
        dinner_lock_time="14:30",
    )

    assert lock_time_for(s.client.id, "LUNCH", on_date=today, branch_id=s.branch.id) == time(9, 30)
    assert lock_time_for(s.client.id, "DINNER", on_date=today, branch_id=s.branch.id) == time(14, 30)

    # Tanpa kontrak: fallback ke default (10:00 / 15:00)
    other_client = Client(name="PT Tanpa Kontrak", is_active=True)
    ctx.session.add(other_client)
    ctx.session.flush()
    assert lock_time_for(other_client.id, "LUNCH", on_date=today, branch_id=s.branch.id) == time(10, 0)
    assert lock_time_for(other_client.id, "DINNER", on_date=today, branch_id=s.branch.id) == time(15, 0)

    # Mock waktu jam 09:15 WIB -> pesanan makan siang diterima
    with patch("app.services.portal_order_draft_service.today_wib", return_value=today), \
         patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 10, 9, 15)):
        reason = session_closed_reason(s.branch.id, today, "LUNCH", client_id=s.client.id, location_id=s.location.id)
        assert reason is None

    # Mock waktu jam 09:45 WIB -> pesanan makan siang ditolak karena melewati 09:30
    with patch("app.services.portal_order_draft_service.today_wib", return_value=today), \
         patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 10, 9, 45)):
        reason = session_closed_reason(s.branch.id, today, "LUNCH", client_id=s.client.id, location_id=s.location.id)
        assert reason is not None
        assert "09:30" in reason

        # Namun untuk PT tanpa kontrak, jam 09:45 masih diterima karena batasnya 10:00
        reason_other = session_closed_reason(s.branch.id, today, "LUNCH", client_id=other_client.id)
        assert reason_other is None


def test_is_contract_holiday_weekly_and_specific(ctx):
    s = _make_fixtures(ctx)
    create_customer_contract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        title="Kontrak Libur",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        payment_terms="Net 7",
        status=CONTRACT_STATUS_ACTIVE,
        created_by=s.owner.id,
        weekly_holidays="7",  # Minggu libur rutin
        holidays=[
            {"holiday_date": "2026-10-14", "note": "Rabu Libur Khusus"},
        ],
    )

    # 2026-10-11 adalah Minggu (ISO day 7)
    sunday_d = date(2026, 10, 11)
    assert sunday_d.isoweekday() == 7
    assert is_contract_holiday(s.client.id, sunday_d, branch_id=s.branch.id) is True

    # 2026-10-14 adalah Rabu (tanggal khusus libur)
    assert is_contract_holiday(s.client.id, date(2026, 10, 14), branch_id=s.branch.id) is True

    # 2026-10-13 adalah Selasa biasa (bukan libur)
    assert is_contract_holiday(s.client.id, date(2026, 10, 13), branch_id=s.branch.id) is False


def test_billing_mode_for_subclient_override_and_fallback(ctx):
    s = _make_fixtures(ctx)
    create_customer_contract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        title="Kontrak Mode Tagih",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        payment_terms="Net 7",
        status=CONTRACT_STATUS_ACTIVE,
        created_by=s.owner.id,
        default_billing_mode=BILLING_DIRECT,
    )

    # Subclient 1: belum ada override di CreditAccount -> pakai default kontrak (BILLING_DIRECT)
    assert billing_mode_for(s.mandor.id) == BILLING_DIRECT

    # Subclient 2: override langsung di CreditAccount -> override harus menang
    mandor2 = Mandor(branch_id=s.branch.id, client_id=s.client.id, name="Mandor Khusus Cash", is_active=True)
    ctx.session.add(mandor2)
    ctx.session.flush()
    acc = get_or_create_credit_account(s.branch.id, PARTY_MANDOR, mandor2.id)
    acc.billing_mode = BILLING_CASH
    ctx.session.flush()

    assert billing_mode_for(mandor2.id) == BILLING_CASH

    # Mandor di bawah client tanpa kontrak & tanpa akun kredit -> fallback legacy VIA_CLIENT
    client_no_contract = Client(name="PT Tanpa Kontrak", is_active=True)
    ctx.session.add(client_no_contract)
    ctx.session.flush()
    mandor3 = Mandor(branch_id=s.branch.id, client_id=client_no_contract.id, name="Mandor Mandiri", is_active=True)
    ctx.session.add(mandor3)
    ctx.session.flush()
    assert billing_mode_for(mandor3.id) == BILLING_VIA_CLIENT


def test_due_days_for_and_invoice_due_date(ctx):
    s = _make_fixtures(ctx)
    inv_date = date(2026, 10, 1)

    # 1. Buat kontrak aktif dengan due_days = 7
    contract = create_customer_contract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        title="Kontrak Tempo 7",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        payment_terms="Net 7",
        status=CONTRACT_STATUS_ACTIVE,
        created_by=s.owner.id,
        due_days=7,
    )

    assert due_days_for(s.client.id, inv_date, branch_id=s.branch.id) == 7

    # Invoice kredit baru jatuh tempo +7 hari
    resolved_due = resolve_due_date(inv_date, s.branch.id, s.client.id, s.mandor.id)
    assert resolved_due == inv_date + timedelta(days=7)

    # 2. Update due_days kontrak menjadi 21 hari
    contract.due_days = 21
    ctx.session.flush()

    assert due_days_for(s.client.id, inv_date, branch_id=s.branch.id) == 21
    resolved_due_21 = resolve_due_date(inv_date, s.branch.id, s.client.id, s.mandor.id)
    assert resolved_due_21 == inv_date + timedelta(days=21)

    # 3. Invoice lama yang sudah tercatat di database tidak berubah tanggal jatuh temponya
    old_due = inv_date + timedelta(days=14)
    old_invoice = Invoice(
        branch_id=s.branch.id,
        invoice_number="INV-OLD-001",
        invoice_date=inv_date,
        due_date=old_due,
        total_amount=Decimal("1000000"),
        remaining_amount=Decimal("1000000"),
        paid_amount=Decimal("0"),
        client_id=s.client.id,
        mandor_id=s.mandor.id,
        bill_to_type="CLIENT",
        status="UNPAID",
        created_by=s.owner.id,
    )
    ctx.session.add(old_invoice)
    ctx.session.flush()

    # Pastikan data di database tetap memiliki due_date 14 hari
    reloaded = Invoice.query.filter_by(invoice_number="INV-OLD-001").first()
    assert reloaded.due_date == old_due


def test_next_cycle_cutoff_cycles():
    # WEEKLY
    c_weekly = SimpleNamespace(
        billing_cycle="WEEKLY",
        billing_anchor_date=date(2026, 10, 1),  # Kamis
        start_date=date(2026, 10, 1),
    )
    assert next_cycle_cutoff(c_weekly, after_date=date(2026, 10, 1)) == date(2026, 10, 8)
    assert next_cycle_cutoff(c_weekly, after_date=date(2026, 10, 5)) == date(2026, 10, 8)
    assert next_cycle_cutoff(c_weekly, after_date=date(2026, 10, 8)) == date(2026, 10, 15)

    # BIWEEKLY (14 hari)
    c_biweekly = SimpleNamespace(
        billing_cycle="BIWEEKLY",
        billing_anchor_date=date(2026, 10, 1),
        start_date=date(2026, 10, 1),
    )
    assert next_cycle_cutoff(c_biweekly, after_date=date(2026, 10, 1)) == date(2026, 10, 15)
    assert next_cycle_cutoff(c_biweekly, after_date=date(2026, 10, 10)) == date(2026, 10, 15)
    assert next_cycle_cutoff(c_biweekly, after_date=date(2026, 10, 15)) == date(2026, 10, 29)

    # MONTHLY penyesuaian akhir bulan: anchor 31 Januari 2026 -> 28 Feb 2026 -> 31 Mar 2026
    c_monthly = SimpleNamespace(
        billing_cycle="MONTHLY",
        billing_anchor_date=date(2026, 1, 31),
        start_date=date(2026, 1, 31),
    )
    assert next_cycle_cutoff(c_monthly, after_date=date(2026, 1, 31)) == date(2026, 2, 28)
    assert next_cycle_cutoff(c_monthly, after_date=date(2026, 2, 28)) == date(2026, 3, 31)
    assert next_cycle_cutoff(c_monthly, after_date=date(2026, 3, 31)) == date(2026, 4, 30)


def test_update_rules_role_permission_and_audit_log(ctx):
    import json

    s = _make_fixtures(ctx)
    contract = create_customer_contract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        title="Kontrak Audit",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        payment_terms="Net 7",
        status=CONTRACT_STATUS_ACTIVE,
        created_by=s.owner.id,
        lunch_lock_time="10:00",
        dinner_lock_time="15:00",
        due_days=7,
        dispute_court=COURT_PANGKALAN_BALAI,
    )

    # User non-admin (DAPUR) tidak boleh mengubah aturan kontrak
    with pytest.raises(CustomerContractError, match="Hanya OWNER dan ADMIN"):
        update_customer_contract_rules(
            contract.id,
            branch_id=s.branch.id,
            actor=s.dapur,
            lunch_lock_time="09:00",
            dinner_lock_time="14:00",
        )

    # OWNER berhasil mengubah aturan
    update_customer_contract_rules(
        contract.id,
        branch_id=s.branch.id,
        actor=s.owner,
        lunch_lock_time="09:15",
        dinner_lock_time="14:15",
        due_days=10,
        dispute_court=COURT_KAYUAGUNG,
        tazir_amount=Decimal("15000"),
        subclient_billing_modes={s.mandor.id: BILLING_DIRECT},
    )

    ctx.session.flush()
    assert contract.lunch_lock_time == time(9, 15)
    assert contract.dinner_lock_time == time(14, 15)
    assert contract.due_days == 10
    assert contract.dispute_court == COURT_KAYUAGUNG
    assert contract.tazir_amount == Decimal("15000")

    # Mode tagih mandor ikut tersimpan di CreditAccount
    m_acc = CreditAccount.query.filter_by(branch_id=s.branch.id, party_id=s.mandor.id).first()
    assert m_acc is not None
    assert m_acc.billing_mode == BILLING_DIRECT

    # Audit log tercatat
    audit = AuditLog.query.filter_by(
        table_name="customer_contracts",
        record_id=contract.id,
        event_type="CUSTOMER_CONTRACT_RULES_UPDATED",
    ).first()
    assert audit is not None
    meta = json.loads(audit.metadata_json or "{}")
    old_meta = meta.get("old_values", {})
    new_meta = meta.get("new_values", {})
    assert old_meta.get("lunch_lock_time") == "10:00"
    assert new_meta.get("lunch_lock_time") == "09:15"
    assert old_meta.get("due_days") == 7
    assert new_meta.get("due_days") == 10


def test_driver_user_id_link_in_reminders(ctx):
    s = _make_fixtures(ctx)

    # Buat Driver dengan nama berbeda dari s.pengantar_user, namun dihubungkan lewat user_id
    driver = Driver(
        branch_id=s.branch.id,
        name="Pak Joko Pengantar Lapangan",  # Nama beda jauh dari "Akun Pengantar"
        phone="0855555555",
        is_active=True,
        user_id=s.pengantar_user.id,
    )
    ctx.session.add(driver)
    ctx.session.flush()

    # Resolusi ID driver untuk user harus mendapatkan driver.id karena Driver.user_id cocok
    driver_ids = _get_driver_ids_for_user(s.branch.id, s.pengantar_user)
    assert driver_ids == [driver.id]

    # Bila tautan user_id dilepas, pencocokan gagal karena nama & hp tidak sama
    driver.user_id = None
    ctx.session.flush()

    fallback_ids = _get_driver_ids_for_user(s.branch.id, s.pengantar_user)
    assert fallback_ids == []
