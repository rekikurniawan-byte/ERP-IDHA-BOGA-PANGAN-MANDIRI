"""Kontrol kredit untuk sub client (mandor) yang ditagih langsung.

Mengunci aturan bisnis di BLUEPRINT_V2_KONTROL_KREDIT.md. Yang paling penting
dikunci bukan fitur barunya, tapi dua jaminannya: tidak ada pihak yang berubah
perlakuannya sebelum owner menyetel kreditnya, dan gerbang tidak bisa dibuka
diam-diam.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models.credit import (
    BILLING_CASH,
    BILLING_DIRECT,
    PARTY_CLIENT,
    PARTY_MANDOR,
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_HOLD,
    STATUS_WATCH,
    STATUS_WRITE_OFF,
)
from app.services import credit_control_service
from app.services.credit_control_service import (
    DEFAULT_THRESHOLDS,
    LEGACY_FALLBACK_TERMS_DAYS,
    CreditDecision,
    check_internal_order_credit,
    credit_gate_from_decision,
    derive_status,
    evaluate_credit,
    get_credit_account,
    get_or_create_credit_account,
    invoice_billing_terms,
    is_billed,
    is_promise_kept,
    parse_terms_days,
    resolve_billing_party,
    resolve_due_date,
    stricter_status,
)


T = DEFAULT_THRESHOLDS
ZERO = Decimal("0")


def d(value):
    return Decimal(str(value))


# --- tangga eskalasi: murni angka, tanpa DB -------------------------------

def test_lancar_tetap_aktif():
    status, _ = derive_status(d(100), d(1000), 0, 0, T)
    assert status == STATUS_ACTIVE


def test_telat_sehari_langsung_masuk_pantau():
    # Ini yang hilang sebelumnya: gerbang lama hanya melihat jumlah, tidak
    # pernah melihat umur, jadi telat berapa hari pun tidak berbunyi.
    status, _ = derive_status(d(10), d(1000), 1, 0, T)
    assert status == STATUS_WATCH


def test_exposure_75_persen_masuk_pantau_walau_belum_telat():
    status, _ = derive_status(d(750), d(1000), 0, 0, T)
    assert status == STATUS_WATCH
    status, _ = derive_status(d(749), d(1000), 0, 0, T)
    assert status == STATUS_ACTIVE


def test_lewat_limit_masuk_tahan_bukan_sekadar_peringatan():
    status, reason = derive_status(d(1001), d(1000), 0, 0, T)
    assert status == STATUS_HOLD
    assert "limit" in reason.lower()


def test_telat_lebih_21_hari_diblokir():
    status, _ = derive_status(ZERO, d(1000), 22, 0, T)
    assert status == STATUS_BLOCKED


def test_ingkar_janji_dua_kali_langsung_blokir_tanpa_menunggu_umur():
    # Sinyal niat kabur datang jauh sebelum tunggakan menua.
    status, reason = derive_status(d(10), d(1000), 0, 2, T)
    assert status == STATUS_BLOCKED
    assert "janji" in reason.lower()


def test_ingkar_janji_sekali_menahan_belum_memblokir():
    status, _ = derive_status(d(10), d(1000), 0, 1, T)
    assert status == STATUS_HOLD


def test_telat_lebih_60_hari_jadi_hapus_buku():
    status, _ = derive_status(ZERO, d(1000), 61, 0, T)
    assert status == STATUS_WRITE_OFF


def test_limit_nol_tidak_pernah_memicu_ambang_persentase():
    # Akun yang baru dibuat mulai dengan limit 0. Kalau limit 0 dianggap
    # "sudah 75% terpakai", setiap akun baru langsung berstatus PANTAU.
    status, _ = derive_status(ZERO, ZERO, 0, 0, T)
    assert status == STATUS_ACTIVE


# --- status tersimpan vs status hitungan ----------------------------------

def test_gerbang_memakai_yang_lebih_ketat():
    assert stricter_status(STATUS_ACTIVE, STATUS_BLOCKED) == STATUS_BLOCKED
    assert stricter_status(STATUS_BLOCKED, STATUS_ACTIVE) == STATUS_BLOCKED
    assert stricter_status(STATUS_WATCH, STATUS_HOLD) == STATUS_HOLD
    assert stricter_status(STATUS_ACTIVE, STATUS_ACTIVE) == STATUS_ACTIVE


def test_status_tak_dikenal_tidak_melonggarkan():
    # Data lama atau typo tidak boleh jadi celah.
    assert stricter_status("ENTAH_APA", STATUS_BLOCKED) == STATUS_BLOCKED


# --- termin -----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("net 30", 30), ("NET 14", 14), ("Net30", 30),
    ("tempo", None), (None, None), ("", None), ("999", None),
])
def test_termin_teks_bebas_diurai_apa_adanya(raw, expected):
    assert parse_terms_days(raw) == expected


def test_jatuh_tempo_lama_tetap_tujuh_hari():
    # Mengaktifkan termin tidak boleh mengubah invoice yang terminnya memang
    # belum pernah disetel siapa pun.
    assert LEGACY_FALLBACK_TERMS_DAYS == 7


# --- penilaian dengan DB ----------------------------------------------------
#
# Angka tunggakan diisolasi lewat monkeypatch. test_db berisi seed yang
# menumpuk dari ribuan run, jadi invoice dan order di dalamnya tidak bisa
# dijadikan pegangan. Yang diuji di sini adalah keputusan, bukan query.

@pytest.fixture
def numbers(monkeypatch):
    """Setel angka yang dilihat penilai: tunggakan, umur, belum ditagih, janji, deposit."""

    def apply(outstanding=0, oldest_days=0, unbilled=0, promises=0, deposit=0):
        monkeypatch.setattr(
            credit_control_service, "outstanding_and_aging",
            lambda *args, **kwargs: (d(outstanding), oldest_days, {}),
        )
        # Deposit dibaca dari buku besar; di sini diisolasi seperti angka lain.
        monkeypatch.setattr(
            credit_control_service, "deposit_balance",
            lambda *args, **kwargs: d(deposit),
        )
        monkeypatch.setattr(
            credit_control_service, "unbilled_delivered",
            lambda *args, **kwargs: d(unbilled),
        )
        monkeypatch.setattr(
            credit_control_service, "broken_promise_count",
            lambda *args, **kwargs: promises,
        )

    apply()
    return apply


@pytest.fixture
def mandor(app):
    with app.app_context():
        from app.extensions import db
        from app.models.master import Mandor

        row = Mandor.query.order_by(Mandor.id.asc()).first()
        if row is None:
            pytest.skip("tidak ada mandor di database uji")
        # Mulai dari keadaan tanpa akun, apa pun yang ditinggal run lain
        # (riwayat statusnya dulu, karena merujuk akun). Di-rollback di akhir.
        existing = get_credit_account(row.branch_id, PARTY_MANDOR, row.id)
        if existing is not None:
            from app.models.credit import CreditStatusEvent

            CreditStatusEvent.query.filter_by(credit_account_id=existing.id).delete()
            db.session.delete(existing)
            db.session.flush()
        try:
            yield row
        finally:
            db.session.rollback()


def direct_account(mandor, **values):
    """Akun DIRECT untuk uji. Syarat deposit 0% kecuali disebut, supaya tes
    tangga eskalasi tidak tertahan oleh gerbang deposit (yang diuji terpisah)."""
    account = get_or_create_credit_account(mandor.branch_id, PARTY_MANDOR, mandor.id)
    account.billing_mode = values.pop("billing_mode", BILLING_DIRECT)
    values.setdefault("deposit_percent", d(0))
    values.setdefault("credit_limit", d(1000))
    for key, value in values.items():
        setattr(account, key, value)
    from app.extensions import db
    db.session.flush()
    return account


def evaluate(mandor, pending=0):
    return evaluate_credit(
        mandor.branch_id, client_id=mandor.client_id,
        mandor_id=mandor.id, pending_amount=d(pending),
    )


def test_mandor_tanpa_akun_tetap_ditagih_lewat_pt(mandor):
    party_type, party_id, _ = resolve_billing_party(
        mandor.branch_id, mandor.client_id, mandor.id
    )
    assert party_type == PARTY_CLIENT
    assert party_id == mandor.client_id


def test_pihak_yang_belum_disetel_tidak_pernah_ditahan(mandor, numbers):
    # Jaminan terpenting. Jatuh tempo invoice lama di-hardcode 7 hari, jadi
    # client kontrak "net 30" yang membayar tepat waktu tampak telat 23 hari.
    # Tanpa jaminan ini, mengaktifkan kontrol kredit akan memblokir client
    # yang tidak melanggar apa pun.
    numbers(outstanding=5_000_000, oldest_days=90, promises=3)
    decision = evaluate(mandor, pending=1_000_000)

    assert decision.status == STATUS_WRITE_OFF  # tetap terlihat sebagai info
    assert not decision.enforced
    assert decision.allowed
    assert not decision.requires_approval
    assert decision.reason == "NOT_CONFIGURED"


def test_angka_yang_sama_diblokir_begitu_owner_menyetel_kredit(mandor, numbers):
    # Pasangan tes di atas: satu-satunya beda adalah akun kreditnya.
    numbers(outstanding=5_000_000, oldest_days=90, promises=3)
    direct_account(mandor, credit_limit=d(10_000_000))
    decision = evaluate(mandor, pending=1_000_000)

    assert decision.enforced
    assert not decision.allowed


def test_mandor_direct_jadi_pihak_tertagih_sendiri(mandor):
    direct_account(mandor)
    party_type, party_id, _ = resolve_billing_party(
        mandor.branch_id, mandor.client_id, mandor.id
    )
    assert party_type == PARTY_MANDOR
    assert party_id == mandor.id


def test_akun_baru_selalu_mulai_netral(mandor):
    account = get_or_create_credit_account(mandor.branch_id, PARTY_MANDOR, mandor.id)
    assert account.billing_mode == "VIA_CLIENT"
    assert d(account.credit_limit) == ZERO
    # Syarat deposit bawaan 20% dari limit (keputusan owner 2026-09-25).
    assert d(account.deposit_percent) == d(20)
    assert account.status == STATUS_ACTIVE


def test_deposit_mengurangi_exposure(mandor, numbers):
    numbers(deposit=400)
    direct_account(mandor, credit_limit=d(1000))
    decision = evaluate(mandor, pending=500)

    # 500 diminta - 400 deposit = 100 yang benar-benar berisiko.
    assert decision.exposure == d(100)
    assert decision.allowed


def test_barang_terkirim_belum_ditagih_ikut_dihitung(mandor, numbers):
    # Lubang terbesar gerbang lama: invoice periode terbit belakangan, jadi
    # yang sudah diantar tapi belum ditagih tidak terlihat sama sekali.
    numbers(outstanding=0, unbilled=900)
    direct_account(mandor, credit_limit=d(1000))
    decision = evaluate(mandor, pending=200)

    assert decision.exposure == d(1100)
    assert decision.status == STATUS_HOLD
    assert decision.requires_approval


def test_lewat_limit_butuh_approval_owner(mandor, numbers):
    numbers(outstanding=950)
    direct_account(mandor, credit_limit=d(1000))
    decision = evaluate(mandor, pending=100)

    assert decision.status == STATUS_HOLD
    assert decision.allowed
    assert decision.requires_approval


def test_ingkar_janji_dua_kali_memblokir_order_baru(mandor, numbers):
    numbers(outstanding=100, promises=2)
    direct_account(mandor, credit_limit=d(1000))
    decision = evaluate(mandor, pending=100)

    assert decision.status == STATUS_BLOCKED
    assert not decision.allowed


def test_mode_cash_tidak_boleh_ngutang(mandor, numbers):
    direct_account(mandor, billing_mode=BILLING_CASH)
    decision = evaluate(mandor, pending=100)

    assert not decision.allowed
    assert decision.reason == "CASH_ONLY"


def test_blokir_manual_owner_tidak_hilang_walau_angkanya_bagus(mandor, numbers):
    # Penyapu harian yang gagal jalan, atau angka yang kebetulan membaik, tidak
    # boleh membuka akun yang sengaja diblokir OWNER.
    direct_account(
        mandor, credit_limit=d(1000),
        status=STATUS_BLOCKED, status_reason="Diblokir manual oleh OWNER.",
    )
    decision = evaluate(mandor)

    assert decision.derived_status == STATUS_ACTIVE
    assert decision.status == STATUS_BLOCKED
    assert not decision.allowed
    assert "OWNER" in decision.reason


def test_direct_tanpa_deposit_diperingatkan(mandor, numbers):
    direct_account(mandor, credit_limit=d(1000))
    decision = evaluate(mandor)

    assert decision.allowed
    assert decision.warning
    assert "tanpa deposit" in decision.message


# --- deposit dulu, kredit belakangan -----------------------------------------

def test_deposit_kurang_dari_syarat_memblokir(mandor, numbers):
    # Limit 1000, syarat 20% = 200. Deposit 199 belum cukup.
    numbers(deposit=199)
    direct_account(mandor, credit_limit=d(1000), deposit_percent=d(20))
    decision = evaluate(mandor, pending=100)

    assert not decision.allowed
    assert decision.reason == "DEPOSIT_SHORT"
    assert decision.required_deposit == d(200)


def test_deposit_cukup_membuka_kredit(mandor, numbers):
    numbers(deposit=200)
    direct_account(mandor, credit_limit=d(1000), deposit_percent=d(20))
    decision = evaluate(mandor, pending=100)

    assert decision.allowed
    assert not decision.warning


def test_ditagih_langsung_tanpa_limit_ditolak(mandor, numbers):
    direct_account(mandor, credit_limit=d(0))
    decision = evaluate(mandor, pending=100)

    assert not decision.allowed
    assert decision.reason == "NO_LIMIT"


def test_gerbang_deposit_kurang_diberi_label_jelas(mandor, numbers):
    numbers(deposit=0)
    direct_account(mandor, credit_limit=d(1000), deposit_percent=d(20))
    gate = credit_gate_from_decision(evaluate(mandor))
    assert gate["status"] == "BLOCKED"
    assert gate["label"] == "Deposit Kurang"


# --- pelepasan sementara oleh OWNER -----------------------------------------

def test_owner_bisa_melepas_sementara_walau_tunggakan_masih_tua(mandor, numbers):
    # Tanpa ini, OWNER yang memberi kesempatan (ada komitmen tertulis) tidak
    # bisa membuka mandor: gerbang selalu memakai status yang lebih ketat.
    from datetime import timedelta

    numbers(outstanding=500, oldest_days=30)
    direct_account(
        mandor, status=STATUS_ACTIVE, status_reason="Komitmen tertulis lunas.",
        release_until=date.today() + timedelta(days=5),
    )
    decision = evaluate(mandor, pending=100)

    assert decision.derived_status == STATUS_BLOCKED
    assert decision.status == STATUS_ACTIVE
    assert decision.allowed
    assert "Dilepas sementara" in decision.reason


def test_pelepasan_yang_lewat_tanggal_tidak_berlaku_lagi(mandor, numbers):
    from datetime import timedelta

    numbers(outstanding=500, oldest_days=30)
    direct_account(
        mandor, status=STATUS_ACTIVE, release_until=date.today() - timedelta(days=1),
    )
    decision = evaluate(mandor, pending=100)

    assert decision.status == STATUS_BLOCKED
    assert not decision.allowed


def test_pelepasan_tidak_melewati_syarat_deposit(mandor, numbers):
    from datetime import timedelta

    numbers(outstanding=500, oldest_days=30, deposit=0)
    direct_account(
        mandor, deposit_percent=d(20), status=STATUS_ACTIVE,
        release_until=date.today() + timedelta(days=5),
    )
    decision = evaluate(mandor, pending=100)

    assert not decision.allowed
    assert decision.reason == "DEPOSIT_SHORT"


# --- jatuh tempo dan tertagih invoice ---------------------------------------

def test_jatuh_tempo_ikut_termin_akun_kredit(mandor):
    from datetime import timedelta

    direct_account(mandor, payment_terms_days=14)
    today = date(2026, 9, 25)
    assert resolve_due_date(today, mandor.branch_id, mandor.client_id, mandor.id) == today + timedelta(days=14)


def test_jatuh_tempo_ikut_termin_kontrak_kalau_akun_belum_disetel(mandor, monkeypatch):
    # Keputusan owner: client "net 30" jatuh tempo 30 hari, bukan 7.
    from datetime import timedelta

    monkeypatch.setattr(credit_control_service, "active_contract_terms", lambda *a: "NET 30")
    today = date(2026, 9, 25)
    assert resolve_due_date(today, mandor.branch_id, mandor.client_id, mandor.id) == today + timedelta(days=30)


def test_jatuh_tempo_tetap_tujuh_hari_tanpa_kontrak_dan_akun(mandor, monkeypatch):
    from datetime import timedelta

    monkeypatch.setattr(credit_control_service, "active_contract_terms", lambda *a: None)
    today = date(2026, 9, 25)
    assert resolve_due_date(today, mandor.branch_id, mandor.client_id, mandor.id) == today + timedelta(days=7)


def test_bayar_di_muka_jatuh_tempo_hari_itu_juga(mandor):
    direct_account(mandor, billing_mode=BILLING_CASH)
    today = date(2026, 9, 25)
    assert resolve_due_date(today, mandor.branch_id, mandor.client_id, mandor.id) == today


def test_invoice_mandor_langsung_ditujukan_ke_mandor(mandor, monkeypatch):
    monkeypatch.setattr(credit_control_service, "active_contract_terms", lambda *a: None)
    client = mandor.client
    direct_account(mandor, payment_terms_days=14)
    billing = invoice_billing_terms(date(2026, 9, 25), mandor.branch_id, client, mandor)
    assert billing["bill_to_type"] == "MANDOR"
    assert billing["bill_to_name"] == mandor.name


def test_invoice_mandor_lewat_pt_tetap_ditujukan_ke_client(mandor, monkeypatch):
    monkeypatch.setattr(credit_control_service, "active_contract_terms", lambda *a: None)
    client = mandor.client
    billing = invoice_billing_terms(date(2026, 9, 25), mandor.branch_id, client, mandor)
    assert billing["bill_to_type"] == "CLIENT"
    assert billing["bill_to_name"] == client.name


# --- "sudah ditagih": jangan menghitung tagihan dua kali -------------------

def test_order_dalam_rentang_invoice_periode_sudah_ditagih():
    # Invoice periode mengisi period_start..period_end dan source_order_id
    # kosong. Versi pertama penilai hanya mencocokkan source_order_id, jadi
    # setiap order yang sudah masuk invoice periode terhitung dua kali.
    ranges = [(date(2026, 9, 1), date(2026, 9, 15))]
    assert is_billed(10, date(2026, 9, 1), ranges, set())
    assert is_billed(10, date(2026, 9, 15), ranges, set())
    assert not is_billed(10, date(2026, 9, 16), ranges, set())


def test_order_dengan_invoice_per_order_sudah_ditagih():
    # Invoice per order mengisi period_start = period_end = order_date,
    # dan source_order_id sebagai jaring pengaman untuk invoice lama.
    assert is_billed(10, date(2026, 9, 3), [(date(2026, 9, 3), date(2026, 9, 3))], set())
    assert is_billed(10, date(2026, 9, 3), [], {10})
    assert not is_billed(11, date(2026, 9, 4), [(date(2026, 9, 3), date(2026, 9, 3))], {10})


# --- janji bayar ------------------------------------------------------------

def test_janji_ditepati_kalau_ada_pembayaran_sebelum_jatuhnya():
    made, due = date(2026, 9, 5), date(2026, 9, 10)
    assert is_promise_kept(made, due, [date(2026, 9, 5)])
    assert is_promise_kept(made, due, [date(2026, 9, 10)])


def test_janji_meleset_kalau_bayarnya_telat_atau_sebelum_berjanji():
    made, due = date(2026, 9, 5), date(2026, 9, 10)
    assert not is_promise_kept(made, due, [])
    assert not is_promise_kept(made, due, [date(2026, 9, 11)])
    # Pembayaran lama sebelum janji dibuat bukan bukti janji ditepati.
    assert not is_promise_kept(made, due, [date(2026, 9, 1)])


# --- bentuk gerbang ---------------------------------------------------------

def decision_of(**values):
    base = dict(
        allowed=True, requires_approval=False, status=STATUS_ACTIVE,
        billing_mode=BILLING_DIRECT, enforced=True, message="Lancar.",
    )
    base.update(values)
    return CreditDecision(**base)


def test_gerbang_blokir_menghalangi_konfirmasi():
    gate = credit_gate_from_decision(decision_of(allowed=False, status=STATUS_BLOCKED))
    assert gate["status"] == "BLOCKED"
    assert not gate["needs_approval"]


def test_approval_tidak_bisa_membuka_blokir():
    # BLOKIR hanya turun lewat tindakan OWNER pada akunnya, bukan approval.
    gate = credit_gate_from_decision(
        decision_of(allowed=False, status=STATUS_BLOCKED), approved=True
    )
    assert gate["status"] == "BLOCKED"


def test_gerbang_tahan_minta_approval_lalu_lepas_setelah_disetujui():
    held = decision_of(status=STATUS_HOLD, requires_approval=True)
    assert credit_gate_from_decision(held)["needs_approval"]
    released = credit_gate_from_decision(held, approved=True)
    assert released["status"] == "APPROVED"
    assert not released["needs_approval"]


def test_gerbang_pantau_muncul_sebagai_peringatan(mandor, numbers):
    # Lewat penilai sungguhan: status PANTAU harus sampai ke gerbang sebagai
    # peringatan, bukan hanya kalau keputusannya dirakit dengan tangan.
    numbers(outstanding=100, oldest_days=1)
    direct_account(mandor)
    decision = evaluate(mandor, pending=100)
    assert decision.status == STATUS_WATCH
    assert decision.warning
    gate = credit_gate_from_decision(decision)
    assert gate["status"] == "WARNING"


# --- jalur order internal ---------------------------------------------------

def test_jalur_internal_tanpa_akun_tidak_berubah(mandor, numbers, monkeypatch):
    # Tanpa akun kredit dan tanpa limit kontrak: tidak ada rem apa pun.
    monkeypatch.setattr(credit_control_service, "active_contract_limit", lambda *a: d(0))
    numbers(outstanding=5_000_000, oldest_days=90)
    ok, message, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="ADMIN",
    )
    assert ok
    assert message is None


# --- limit kontrak di jalur admin (keputusan owner 2026-09-25) -------------

def test_jalur_admin_lewat_limit_kontrak_hanya_owner(mandor, numbers, monkeypatch):
    # Dulu limit kontrak hanya dicek di portal; order yang diinput admin untuk
    # client tidak direm sama sekali.
    monkeypatch.setattr(credit_control_service, "active_contract_limit", lambda *a: d(1000))
    numbers(outstanding=950)

    ok, message, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="ADMIN",
    )
    assert not ok
    assert "limit kontrak" in message and "OWNER" in message

    ok, message, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="OWNER",
    )
    assert ok
    assert "keputusan OWNER" in message


def test_jalur_admin_limit_kontrak_ikut_menghitung_order_belum_ditagih(mandor, numbers, monkeypatch):
    # Invoice periode terbit belakangan; tanpa ini client bisa menumpuk satu
    # periode penuh di atas limit kontraknya.
    monkeypatch.setattr(credit_control_service, "active_contract_limit", lambda *a: d(1000))
    numbers(outstanding=0, unbilled=950)
    ok, _, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="ADMIN",
    )
    assert not ok


def test_jalur_admin_di_bawah_limit_kontrak_jalan(mandor, numbers, monkeypatch):
    monkeypatch.setattr(credit_control_service, "active_contract_limit", lambda *a: d(1000))
    numbers(outstanding=500)
    ok, message, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="ADMIN",
    )
    assert ok
    assert message is None


def test_jalur_internal_tahan_menolak_admin_tapi_menerima_owner(mandor, numbers):
    numbers(outstanding=950)
    direct_account(mandor, credit_limit=d(1000))

    ok, message, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="ADMIN",
    )
    assert not ok
    assert "OWNER" in message

    ok, message, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="OWNER",
    )
    assert ok
    assert "OWNER" in message


def test_jalur_internal_tanpa_role_diperlakukan_bukan_owner(mandor, numbers):
    numbers(outstanding=950)
    direct_account(mandor, credit_limit=d(1000))
    ok, _, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100),
    )
    assert not ok


def test_jalur_internal_blokir_menolak_owner_juga(mandor, numbers):
    # OWNER tidak bisa sekadar menginput order untuk pihak yang diblokir;
    # dia harus sengaja menurunkan status akunnya dulu.
    numbers(outstanding=100, oldest_days=30)
    direct_account(mandor, credit_limit=d(1000))
    ok, _, _ = check_internal_order_credit(
        branch_id=mandor.branch_id, mandor_id=mandor.id, amount=d(100), actor_role="OWNER",
    )
    assert not ok


# --- approval penahanan kredit khusus OWNER ---------------------------------

def approval_row(action_key, requested_by):
    from app.models.system import ApprovalRequest

    return ApprovalRequest(
        branch_id=1, action_key=action_key, reference_type="PORTAL_ORDER_DRAFT",
        reference_id=1, status="SUBMITTED", requested_by=requested_by,
        requested_reason="uji",
    )


@pytest.fixture
def reviewers(app, monkeypatch):
    """User palsu untuk pemeriksa, supaya tidak bergantung pada tabel users."""
    from types import SimpleNamespace

    from app.extensions import db

    users = {1: SimpleNamespace(id=1, role="OWNER"), 2: SimpleNamespace(id=2, role="ADMIN"),
             3: SimpleNamespace(id=3, role="ADMIN")}
    with app.app_context():
        monkeypatch.setattr(db.session, "get", lambda model, user_id: users.get(user_id))
        yield users


def test_admin_tidak_boleh_menyetujui_penahanan_kredit(reviewers):
    from app.services.approval_service import ApprovalError, approve_request

    with pytest.raises(ApprovalError, match="OWNER"):
        approve_request(approval_row("PORTAL_ORDER_CREDIT_OVERRIDE", 3), reviewed_by=2, commit=False)


def test_owner_tunggal_boleh_memutuskan_penahanan_yang_dia_ajukan_sendiri(reviewers):
    # Dengan satu OWNER, tanpa ini order yang dikonfirmasi OWNER sendiri
    # akan tertahan selamanya: tidak ada OWNER kedua yang boleh jadi checker.
    from app.services.approval_service import approve_request

    row = approve_request(approval_row("PORTAL_ORDER_CREDIT_OVERRIDE", 1), reviewed_by=1, commit=False)
    assert row.status == "APPROVED"


def test_maker_checker_aksi_lain_tidak_berubah(reviewers):
    from app.services.approval_service import ApprovalError, approve_request

    with pytest.raises(ApprovalError, match="Maker dan checker"):
        approve_request(approval_row("PORTAL_ORDER_CUTOFF_OVERRIDE", 1), reviewed_by=1, commit=False)
    row = approve_request(approval_row("PORTAL_ORDER_CUTOFF_OVERRIDE", 3), reviewed_by=2, commit=False)
    assert row.status == "APPROVED"
