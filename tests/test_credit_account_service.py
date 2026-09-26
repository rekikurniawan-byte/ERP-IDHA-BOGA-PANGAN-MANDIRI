"""Tindakan kredit, deposit jaminan, dan pemetaan akun yang diperbaiki.

Keputusan owner 2026-09-25 yang dikunci di sini:
- hanya OWNER yang boleh menyetel kredit dan mengubah status;
- status naik otomatis, tidak pernah turun sendiri;
- NIK mandor yang diblokir/dihapus buku tidak bisa dapat kredit langsung lagi;
- deposit dan DP client dicatat di akun kewajiban, bukan 1008 (aset);
- kode akun beban mengikuti COA di database.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.credit import (
    BILLING_DIRECT,
    PARTY_MANDOR,
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_HOLD,
    CreditStatusEvent,
)
from app.services import credit_control_service
from app.services.credit_account_service import (
    CreditActionError,
    change_credit_status,
    parse_money,
    receive_deposit,
    save_credit_settings,
    sweep_credit_statuses,
)
from app.services.credit_control_service import get_credit_account, get_or_create_credit_account


OWNER = SimpleNamespace(id=1, role="OWNER")
ADMIN = SimpleNamespace(id=2, role="ADMIN")


def d(value):
    return Decimal(str(value))


# --- tanpa DB -------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1.500.000", d(1500000)), ("Rp 1.500.000", d(1500000)), ("1500000", d(1500000)),
    ("1.500.000,50", d("1500000.50")), ("", d(0)), (None, d(0)),
])
def test_nominal_dari_form_diurai_seperti_ditulis_orang_indonesia(raw, expected):
    assert parse_money(raw) == expected


def test_nominal_minus_atau_asal_ditolak():
    with pytest.raises(CreditActionError):
        parse_money("-5")
    with pytest.raises(CreditActionError):
        parse_money("lima ribu")


def test_uang_yang_diterima_dicatat_di_akun_kewajiban():
    from app.services.advance_service import (
        ADVANCE_TYPES,
        CLIENT_DP_RECEIVED,
        MANDOR_OPERATIONAL_ADVANCE,
        MANDOR_SECURITY_DEPOSIT,
        SUPPLIER_ADVANCE_PAID,
    )

    # Uang DITERIMA = kewajiban (2xxx). Sebelumnya DP client masuk 1008 (aset).
    assert ADVANCE_TYPES[CLIENT_DP_RECEIVED]["account_code"] == "2008"
    assert ADVANCE_TYPES[MANDOR_SECURITY_DEPOSIT]["account_code"] == "2007"
    # Uang DIBAYAR = aset, tetap 1008.
    assert ADVANCE_TYPES[SUPPLIER_ADVANCE_PAID]["account_code"] == "1008"
    assert ADVANCE_TYPES[MANDOR_OPERATIONAL_ADVANCE]["account_code"] == "1008"
    for rule in ADVANCE_TYPES.values():
        is_received = rule["cash_direction"] == "IN"
        assert rule["account_code"].startswith("2") == is_received


# Nama akun beban di COA database, yang disepakati owner sebagai acuan
# (2026-09-25). Kalau salah satu modul memetakan kategori ke kode yang
# namanya tidak cocok, tes di bawah gagal -- persis bug yang ditemukan:
# Gas ke 5006 (Beban Air), Perawatan ke 5007 (Beban Gas LPG), BBM ke 5011.
COA_EXPENSE_NAMES = {
    "5002": "Beban Operasional Dapur",
    "5003": "Beban Transport / BBM",
    "5005": "Beban Listrik",
    "5006": "Beban Air",
    "5007": "Beban Gas LPG",
    "5008": "Beban Administrasi / Bunga",
    "5009": "Beban Lain-Lain",
    "5010": "Beban Kemasan",
    "5011": "Beban Perawatan Kendaraan",
}


def _assert_label_matches_coa(code, account_label):
    assert code in COA_EXPENSE_NAMES, f"kode {code} tidak ada di COA"
    assert account_label == f"{code} {COA_EXPENSE_NAMES[code]}"


def test_pemetaan_panjar_mandor_sesuai_coa():
    from app.services.advance_service import MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES

    for code, rule in MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES.items():
        _assert_label_matches_coa(code, rule["account_label"])


def test_pemetaan_biaya_operasional_sesuai_coa():
    from app.services.operational_expense_service import OPERATIONAL_EXPENSE_CATEGORIES

    for rule in OPERATIONAL_EXPENSE_CATEGORIES.values():
        _assert_label_matches_coa(rule["account_code"], rule["account_label"])
    labels = {rule["label"]: rule["account_code"] for rule in OPERATIONAL_EXPENSE_CATEGORIES.values()}
    assert labels["Gas / LPG"] == "5007"
    assert labels["Listrik"] == "5005"
    assert labels["Air"] == "5006"


def test_pemetaan_biaya_transport_sesuai_coa():
    from app.services.transport_expense_service import TRANSPORT_EXPENSE_TYPES, VEHICLE_FUEL

    for rule in TRANSPORT_EXPENSE_TYPES.values():
        _assert_label_matches_coa(rule["account_code"], rule["account_label"])
    assert TRANSPORT_EXPENSE_TYPES[VEHICLE_FUEL]["account_code"] == "5003"


def test_invoice_mandor_langsung_berkontak_mandor_tanpa_pic_client(monkeypatch):
    from app.services import invoice_identity_service

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("PIC client tidak boleh diwajibkan untuk mandor yang ditagih langsung")

    monkeypatch.setattr(invoice_identity_service, "get_required_client_pic", must_not_be_called)
    mandor = SimpleNamespace(name="Mandor Budi", phone="0812")
    contact, error = invoice_identity_service.invoice_contact_snapshot(
        SimpleNamespace(id=5), mandor, None, "MANDOR"
    )
    assert error is None
    assert contact["client_pic_id"] is None
    assert contact["client_pic_name_snapshot"] == "Mandor Budi"
    assert contact["client_pic_phone_snapshot"] == "0812"


def test_invoice_lewat_pt_tetap_wajib_pic_client(monkeypatch):
    from app.services import invoice_identity_service

    monkeypatch.setattr(
        invoice_identity_service, "get_required_client_pic",
        lambda client_id, pic_id: (None, "Client belum punya PIC resmi aktif."),
    )
    contact, error = invoice_identity_service.invoice_contact_snapshot(
        SimpleNamespace(id=5), SimpleNamespace(name="Mandor Budi"), None, "CLIENT"
    )
    assert contact is None
    assert "PIC" in error


def test_bbm_transaksi_lapangan_sesuai_coa():
    from app.services.field_transaction_policy_service import get_field_transaction_event_policy

    assert get_field_transaction_event_policy("FUEL_EXPENSE")["expense_account_code"] == "5003"


# --- dengan DB --------------------------------------------------------------------

@pytest.fixture
def numbers(monkeypatch):
    def apply(outstanding=0, oldest_days=0, unbilled=0, promises=0, deposit=0):
        monkeypatch.setattr(credit_control_service, "outstanding_and_aging",
                            lambda *a, **k: (d(outstanding), oldest_days, {}))
        monkeypatch.setattr(credit_control_service, "unbilled_delivered", lambda *a, **k: d(unbilled))
        monkeypatch.setattr(credit_control_service, "broken_promise_count", lambda *a, **k: promises)
        monkeypatch.setattr(credit_control_service, "deposit_balance", lambda *a, **k: d(deposit))

    apply()
    return apply


@pytest.fixture
def db_session(app):
    with app.app_context():
        from app.extensions import db

        try:
            yield db
        finally:
            db.session.rollback()


@pytest.fixture
def no_commit(monkeypatch):
    """Tindakan kredit commit sendiri; di tes, cukup flush supaya bisa di-rollback."""
    from app.extensions import db
    from app.services import credit_account_service

    def run_without_commit(action):
        result = action()
        db.session.flush()
        return result

    monkeypatch.setattr(credit_account_service, "_in_transaction", run_without_commit)


def _mandors(count):
    from app.models.master import Mandor

    rows = Mandor.query.order_by(Mandor.id.asc()).limit(count).all()
    if len(rows) < count:
        pytest.skip("mandor di database uji kurang")
    from app.extensions import db

    for row in rows:
        # Riwayat status merujuk akun, jadi dihapus dulu. Semua di-rollback.
        existing = get_credit_account(row.branch_id, PARTY_MANDOR, row.id)
        if existing is not None:
            CreditStatusEvent.query.filter_by(credit_account_id=existing.id).delete()
            db.session.delete(existing)
    db.session.flush()
    return rows


def _direct(mandor, **values):
    from app.extensions import db

    account = get_or_create_credit_account(mandor.branch_id, PARTY_MANDOR, mandor.id)
    account.billing_mode = BILLING_DIRECT
    values.setdefault("credit_limit", d(1000))
    values.setdefault("deposit_percent", d(0))
    for key, value in values.items():
        setattr(account, key, value)
    db.session.flush()
    return account


def _form(**values):
    base = {
        "billing_mode": "DIRECT", "credit_limit": "1.000.000", "payment_terms_days": "14",
        "deposit_percent": "20", "id_number": "3201000000000001", "address": "Jl. Uji 1",
    }
    base.update(values)
    return base


def test_hanya_owner_yang_boleh_menyetel_kredit(db_session, no_commit):
    (mandor,) = _mandors(1)
    with pytest.raises(CreditActionError, match="OWNER"):
        save_credit_settings(mandor, _form(), ADMIN)


def test_mandor_langsung_wajib_punya_limit_termin_nik_alamat(db_session, no_commit):
    (mandor,) = _mandors(1)
    with pytest.raises(CreditActionError, match="NIK"):
        save_credit_settings(mandor, _form(id_number=""), OWNER)
    with pytest.raises(CreditActionError, match="limit"):
        save_credit_settings(mandor, _form(credit_limit="0"), OWNER)


def test_owner_menyetel_kredit_mandor(db_session, no_commit, monkeypatch):
    from app.services import audit_log_service

    monkeypatch.setattr(audit_log_service, "record_audit_log", lambda **kwargs: None)
    (mandor,) = _mandors(1)
    account = save_credit_settings(mandor, _form(), OWNER)
    assert account.billing_mode == BILLING_DIRECT
    assert account.credit_limit == d(1000000)
    assert account.payment_terms_days == 14
    assert mandor.id_number == "3201000000000001"


def test_nik_mandor_yang_diblokir_tidak_bisa_dapat_kredit_lagi(db_session, no_commit, monkeypatch):
    # Mandor yang kabur mendaftar ulang dengan nama lain, NIK yang sama.
    from app.services import audit_log_service

    monkeypatch.setattr(audit_log_service, "record_audit_log", lambda **kwargs: None)
    kabur, baru = _mandors(2)
    kabur.id_number = "3201999999999999"
    _direct(kabur, status=STATUS_BLOCKED)

    with pytest.raises(CreditActionError, match="diblokir"):
        save_credit_settings(baru, _form(id_number="3201999999999999"), OWNER)


def test_deposit_hanya_untuk_mandor_yang_ditagih_langsung(db_session):
    (mandor,) = _mandors(1)
    with pytest.raises(CreditActionError, match="Ditagih langsung"):
        receive_deposit(mandor, {"amount": "500000", "payment_method": "CASH"}, ADMIN)


def test_penyapu_menaikkan_status_dan_mencatat_jejak(db_session, numbers, monkeypatch):
    from app.services import credit_account_service

    monkeypatch.setattr(credit_account_service, "_notify", lambda *a, **k: None)
    (mandor,) = _mandors(1)
    account = _direct(mandor)
    numbers(outstanding=100, oldest_days=10)

    result = sweep_credit_statuses(mandor.branch_id)
    db_session.session.flush()

    assert account.status == STATUS_HOLD
    assert any(row["account_id"] == account.id for row in result["escalated"])
    event = CreditStatusEvent.query.filter_by(credit_account_id=account.id).one()
    assert event.from_status == STATUS_ACTIVE
    assert event.to_status == STATUS_HOLD
    assert event.trigger == "SWEEP"
    assert event.oldest_days_overdue == 10


def test_penyapu_tidak_pernah_menurunkan_status(db_session, numbers, monkeypatch):
    from app.services import credit_account_service

    monkeypatch.setattr(credit_account_service, "_notify", lambda *a, **k: None)
    (mandor,) = _mandors(1)
    account = _direct(mandor, status=STATUS_BLOCKED)
    numbers(outstanding=0, oldest_days=0)

    sweep_credit_statuses(mandor.branch_id)

    assert account.status == STATUS_BLOCKED
    assert CreditStatusEvent.query.filter_by(credit_account_id=account.id).count() == 0


def test_ubah_status_wajib_owner_dan_alasan(db_session, numbers, no_commit, monkeypatch):
    from app.services import credit_account_service

    monkeypatch.setattr(credit_account_service, "_notify", lambda *a, **k: None)
    (mandor,) = _mandors(1)
    account = _direct(mandor, status=STATUS_BLOCKED)

    with pytest.raises(CreditActionError, match="OWNER"):
        change_credit_status(account, {"status": "AKTIF", "reason": "sudah bayar lunas semua"}, ADMIN)
    with pytest.raises(CreditActionError, match="Alasan"):
        change_credit_status(account, {"status": "AKTIF", "reason": "ok"}, OWNER)

    change_credit_status(
        account,
        {"status": "AKTIF", "reason": "komitmen tertulis lunas 30-09", "release_until": "2099-01-01"},
        OWNER,
    )
    assert account.status == STATUS_ACTIVE
    assert account.release_until.isoformat() == "2099-01-01"
    event = CreditStatusEvent.query.filter_by(credit_account_id=account.id).one()
    assert event.trigger == "MANUAL"
    assert event.changed_by == OWNER.id


def test_hapus_buku_tidak_bisa_lewat_tombol_status(db_session, no_commit):
    (mandor,) = _mandors(1)
    account = _direct(mandor)
    with pytest.raises(CreditActionError, match="Hapus buku"):
        change_credit_status(account, {"status": "HAPUS_BUKU", "reason": "mandor kabur tidak bisa dihubungi"}, OWNER)
