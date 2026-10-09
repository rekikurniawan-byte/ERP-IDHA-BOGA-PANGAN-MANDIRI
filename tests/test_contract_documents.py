"""Test suite untuk Fase 9: Surat kontrak otomatis & adendum.

Memastikan:
1. Isi surat memuat angka riil dari data kontrak sistem (jam lock, tempo due_days, ta'zir, pihak ditagih, harga, pengadilan, penandatangan PT).
2. Snapshot terkunci: template atau data kontrak yang berubah tidak mengubah surat lama.
3. Kontrak baru aktif hanya setelah surat ditandatangani (aktivasi ditolak sebelum TTD).
4. Adendum otomatis terbentuk saat perubahan aturan di tengah kontrak aktif.
5. Alur tanda tangan (basah bermeterai scan & digital via OTP portal).
6. Portal scoping: client dan sub client hanya dapat melihat dan mengakses dokumen miliknya.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import io
from types import SimpleNamespace
from uuid import uuid4

from flask import current_app
import pytest
from werkzeug.datastructures import FileStorage

from app.models.contract import (
    COURT_KAYUAGUNG,
    COURT_PANGKALAN_BALAI,
    ContractDocument,
    ContractHoliday,
    CustomerContract,
    DISPUTE_COURT_LABELS,
    DOC_STATUS_DRAFT,
    DOC_STATUS_PENDING,
    DOC_STATUS_SIGNED,
    DOC_TYPE_ADDENDUM,
    DOC_TYPE_CONTRACT,
    SIGNING_METHOD_OTP,
    SIGNING_METHOD_WET,
)
from app.models.credit import (
    BILLING_DIRECT,
    BILLING_VIA_CLIENT,
    PARTY_MANDOR,
    CreditAccount,
)
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Mandor, User
from app.models.pricing import PortionPrice
from app.models.system import PortalUserMapping
from app.services.credit_control_service import get_or_create_credit_account
from app.services.customer_contract_document_service import (
    CustomerContractDocumentError,
    build_contract_document_context,
    contract_document_print_html,
    generate_addendum_document,
    generate_contract_document,
    get_contract_document,
    is_contract_signed,
    list_contract_documents_for_contract,
    send_contract_signing_otp,
    sign_contract_document_wet,
    verify_and_sign_contract_document_otp,
)
from app.services.customer_contract_service import (
    CONTRACT_STATUS_ACTIVE,
    CONTRACT_STATUS_DRAFT,
    CustomerContractError,
    activate_customer_contract,
    create_customer_contract,
    update_customer_contract_rules,
)
from app.services.portal_mapping_service import PRINCIPAL_CLIENT, PRINCIPAL_MANDOR


@pytest.fixture
def ctx(app, monkeypatch):
    """Fixture tanpa commit permanen ke database: flush dan rollback di akhir fixture."""
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _make_test_fixtures(db):
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"BR-{suffix}", name=f"Cabang Uji {suffix}", is_active=True)
    client_a = Client(name=f"PT Katering Mega {suffix}", phone="0812345678", is_active=True, address="Jl. Proyek No. 1")
    client_b = Client(name=f"PT Tambang Lain {suffix}", phone="0898765432", is_active=True, address="Jl. Tambang No. 2")
    db.session.add_all([branch, client_a, client_b])
    db.session.flush()

    pic_a = ClientPic(client_id=client_a.id, name="Budi Santoso", position="General Manager", phone="0811223344")
    db.session.add(pic_a)
    db.session.flush()

    owner = User(
        branch_id=branch.id,
        full_name="Owner Idha",
        username=f"owner_{suffix}",
        password_hash="hash",
        role="OWNER",
        is_active=True,
    )
    admin = User(
        branch_id=branch.id,
        full_name="Admin Kontrak",
        username=f"admin_{suffix}",
        password_hash="hash",
        role="ADMIN",
        is_active=True,
    )
    portal_client_a = User(
        branch_id=branch.id,
        full_name="Budi Santoso PIC",
        username=f"client_a_{suffix}",
        email=f"pic_{suffix}@megaproject.co.id",
        password_hash="hash",
        role="PORTAL_CLIENT",
        is_active=True,
    )
    portal_client_b = User(
        branch_id=branch.id,
        full_name="User Client B",
        username=f"client_b_{suffix}",
        email=f"pic_{suffix}@tambanglain.co.id",
        password_hash="hash",
        role="PORTAL_CLIENT",
        is_active=True,
    )
    mandor_a1 = Mandor(branch_id=branch.id, client_id=client_a.id, name=f"Mandor Sektor 1 {suffix}", is_active=True)
    mandor_a2 = Mandor(branch_id=branch.id, client_id=client_a.id, name=f"Mandor Sektor 2 {suffix}", is_active=True)
    db.session.add_all([owner, admin, portal_client_a, portal_client_b, mandor_a1, mandor_a2])
    db.session.flush()

    # Mappings
    map_a = PortalUserMapping(user_id=portal_client_a.id, principal_type=PRINCIPAL_CLIENT, client_id=client_a.id, is_active=True)
    map_b = PortalUserMapping(user_id=portal_client_b.id, principal_type=PRINCIPAL_CLIENT, client_id=client_b.id, is_active=True)
    db.session.add_all([map_a, map_b])

    # Pricing
    price = PortionPrice(
        branch_id=branch.id,
        client_id=client_a.id,
        price_per_portion=Decimal("28500.00"),
        effective_from=date(2026, 1, 1),
        created_by=owner.id,
    )
    db.session.add(price)
    db.session.flush()

    return SimpleNamespace(
        branch=branch,
        client_a=client_a,
        client_b=client_b,
        pic_a=pic_a,
        owner=owner,
        admin=admin,
        portal_client_a=portal_client_a,
        portal_client_b=portal_client_b,
        mandor_a1=mandor_a1,
        mandor_a2=mandor_a2,
    )


def test_contract_document_renders_contract_numbers_and_data(ctx):
    """Surat memuat angka riil dari data kontrak: jam lock, tempo, ta'zir, pihak ditagih, harga, pengadilan, penandatangan."""
    f = _make_test_fixtures(ctx)

    # Setup credit accounts untuk pihak tagih mandor
    acc_m1 = get_or_create_credit_account(f.branch.id, PARTY_MANDOR, f.mandor_a1.id)
    acc_m1.billing_mode = BILLING_VIA_CLIENT

    acc_m2 = get_or_create_credit_account(f.branch.id, PARTY_MANDOR, f.mandor_a2.id)
    acc_m2.billing_mode = BILLING_DIRECT

    # Buat kontrak dengan data spesifik
    contract = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_a.id,
        title="Kontrak Katering",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 10",
        credit_limit=Decimal("75000000.00"),
        client_pic_id=f.pic_a.id,
        created_by=f.admin.id,
        lunch_lock_time="10:30",
        dinner_lock_time="16:00",
        due_days=10,
        tazir_amount=Decimal("65000.00"),
        weekly_holidays=["7"],
        billing_cycle="BIWEEKLY",
        dispute_court=COURT_PANGKALAN_BALAI,
    )
    ctx.session.flush()

    doc = generate_contract_document(
        contract_id=contract.id,
        branch_id=f.branch.id,
        created_by=f.admin.id,
        commit=False,
    )
    ctx.session.flush()

    html = doc.html_snapshot

    # 1. Pihak PT: nama penandatangan Ida Royani dan Reki Kurniawan
    assert "Ida Royani" in html
    assert "Reki Kurniawan" in html
    assert "Direktur" in html
    assert "Komisaris" in html

    # 2. Identitas Client & PIC
    assert f.client_a.name in html
    assert "Budi Santoso" in html
    assert "General Manager" in html

    # 3. Harga per porsi
    assert "28.500" in html

    # 4. Jam lock
    assert "10.30" in html
    assert "16.00" in html

    # 5. Tempo pembayaran dibuat dari angka due_days
    assert "10 hari kalender setelah invoice diterbitkan" in html

    # 6. Ta'zir nominal tetap
    assert "65.000" in html
    assert "Dana Sosial" in html

    # 7. Subclient & pihak tagih
    assert f.mandor_a1.name in html
    assert f.mandor_a2.name in html
    assert "Ditagih ke Kantor Pusat" in html
    assert "Ditagih Langsung ke Sub Client" in html

    # 8. Pengadilan sengketa
    assert "PN Pangkalan Balai" in html

    # 9. Libur rutin ditulis nama hari; ambang kredit dari sistem; pasal pajak dari Pengaturan Pajak
    assert "Minggu" in html
    assert "Keterlambatan 22 Hari (Status BLOKIR)" in html
    assert "bukan PPN" in html
    assert "bukti potong" in html
    # 10. Ongkir kontrak tanpa tarif khusus = termasuk harga porsi
    assert "Sudah termasuk dalam harga per porsi" in html


def test_contract_document_snapshot_immutability(ctx):
    """Snapshot tidak berubah meskipun data kontrak kemudian diubah di database."""
    f = _make_test_fixtures(ctx)

    contract = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_a.id,
        title="Kontrak Katering",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 7",
        credit_limit=Decimal("30000000.00"),
        created_by=f.admin.id,
        lunch_lock_time="10:00",
        dinner_lock_time="15:00",
        due_days=7,
        tazir_amount=Decimal("50000.00"),
        dispute_court=COURT_PANGKALAN_BALAI,
    )
    ctx.session.flush()

    # Generate document and freeze
    doc = generate_contract_document(
        contract_id=contract.id,
        branch_id=f.branch.id,
        created_by=f.admin.id,
        commit=False,
    )
    ctx.session.flush()

    frozen_snapshot = doc.html_snapshot
    assert "10.00" in frozen_snapshot
    assert "7 hari kalender" in frozen_snapshot
    assert "50.000" in frozen_snapshot

    # Ubah kontrak di DB
    contract.lunch_lock_time = time(11, 45)
    contract.due_days = 21
    contract.tazir_amount = Decimal("150000.00")
    contract.dispute_court = COURT_KAYUAGUNG
    ctx.session.flush()

    # Ambil kembali dokumen dari database
    reloaded_doc = ContractDocument.query.get(doc.id)
    assert reloaded_doc.html_snapshot == frozen_snapshot
    assert "10.00" in reloaded_doc.html_snapshot
    assert "11.45" not in reloaded_doc.html_snapshot
    assert "7 hari kalender" in reloaded_doc.html_snapshot
    assert "21 hari kalender" not in reloaded_doc.html_snapshot


def test_contract_activation_blocked_until_signed(ctx):
    """Kontrak baru aktif setelah ditandatangani: aktivasi ditolak bila dokumen belum DITANDATANGANI."""
    f = _make_test_fixtures(ctx)

    contract = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_a.id,
        title="Kontrak Katering",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 7",
        credit_limit=Decimal("20000000.00"),
        created_by=f.admin.id,
    )
    ctx.session.flush()
    assert contract.status == CONTRACT_STATUS_DRAFT

    # Skenario 1: Belum ada dokumen sama sekali -> aktivasi ditolak
    with pytest.raises(CustomerContractError, match="ditandatangani"):
        activate_customer_contract(contract.id, branch_id=f.branch.id, updated_by=f.admin.id, commit=False)

    # Skenario 2: Dokumen dibuat tetapi status masih MENUNGGU_TTD -> aktivasi tetap ditolak
    doc = generate_contract_document(
        contract_id=contract.id,
        branch_id=f.branch.id,
        created_by=f.admin.id,
        commit=False,
    )
    ctx.session.flush()
    assert doc.status == DOC_STATUS_PENDING

    with pytest.raises(CustomerContractError, match="ditandatangani"):
        activate_customer_contract(contract.id, branch_id=f.branch.id, updated_by=f.admin.id, commit=False)

    assert contract.status == CONTRACT_STATUS_DRAFT

    # Skenario 3: Dokumen ditandatangani -> aktivasi berhasil
    doc.status = DOC_STATUS_SIGNED
    doc.signing_method = SIGNING_METHOD_WET
    doc.signed_at = datetime.utcnow()
    ctx.session.flush()

    assert is_contract_signed(contract.id, f.branch.id) is True

    activated = activate_customer_contract(contract.id, branch_id=f.branch.id, updated_by=f.admin.id, commit=False)
    assert activated.status == CONTRACT_STATUS_ACTIVE


def test_addendum_generated_on_active_contract_rule_change(ctx):
    """Perubahan aturan di tengah kontrak aktif otomatis membuat dokumen ADENDUM."""
    f = _make_test_fixtures(ctx)

    contract = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_a.id,
        title="Kontrak Katering",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 7",
        credit_limit=Decimal("20000000.00"),
        created_by=f.admin.id,
        lunch_lock_time="10:00",
        due_days=7,
        tazir_amount=Decimal("50000.00"),
    )
    ctx.session.flush()

    # Buat dokumen utama dan tandatangani
    main_doc = generate_contract_document(contract_id=contract.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    main_doc.status = DOC_STATUS_SIGNED
    ctx.session.flush()

    activate_customer_contract(contract.id, branch_id=f.branch.id, updated_by=f.admin.id, commit=False)
    assert contract.status == CONTRACT_STATUS_ACTIVE

    # Hitung jumlah adendum sebelum update
    docs_before = list_contract_documents_for_contract(contract.id, f.branch.id)
    assert len(docs_before) == 1
    assert docs_before[0].document_type == DOC_TYPE_CONTRACT

    # Ubah aturan kontrak aktif (jam lock siang diubah dari 10:00 -> 11:00, ta'zir diubah -> 75000)
    update_customer_contract_rules(
        contract.id,
        branch_id=f.branch.id,
        actor=f.owner,
        lunch_lock_time="11:00",
        dinner_lock_time="15:00",
        due_days=7,
        tazir_amount=Decimal("75000.00"),
        commit=False,
    )
    ctx.session.flush()

    docs_after = list_contract_documents_for_contract(contract.id, f.branch.id)
    assert len(docs_after) == 2

    addendum = next(d for d in docs_after if d.document_type == DOC_TYPE_ADDENDUM)
    assert addendum.version_no == 1
    assert addendum.document_number.startswith("ADENDUM-01/")
    assert addendum.status == DOC_STATUS_PENDING
    assert "11.00" in addendum.html_snapshot
    assert "75.000" in addendum.html_snapshot


def test_wet_signature_and_otp_signing_methods(ctx, monkeypatch):
    """Uji tanda tangan basah bermeterai dan persetujuan digital via OTP portal."""
    f = _make_test_fixtures(ctx)

    contract = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_a.id,
        title="Kontrak Katering",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 7",
        created_by=f.admin.id,
    )
    ctx.session.flush()

    # --- Test Tanda Tangan Basah ---
    doc_wet = generate_contract_document(contract_id=contract.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    ctx.session.flush()
    snapshot_before_signing = doc_wet.html_snapshot

    fake_file = FileStorage(stream=io.BytesIO(b"%PDF-1.4 test contract scan content"), filename="kontrak_meterai.pdf", content_type="application/pdf")
    signed_wet = sign_contract_document_wet(
        document_id=doc_wet.id,
        branch_id=f.branch.id,
        file_storage=fake_file,
        actor_id=f.admin.id,
        notes="Scan bermeterai basah lengkap",
        commit=False,
    )
    ctx.session.flush()

    assert signed_wet.status == DOC_STATUS_SIGNED
    assert signed_wet.signing_method == SIGNING_METHOD_WET
    assert signed_wet.scan_attachment_id is not None
    # Isi yang ditandatangani = isi saat dibuat; cap TTD hanya ditambahkan saat dicetak.
    assert signed_wet.html_snapshot == snapshot_before_signing
    assert "DOKUMEN INI TELAH DITANDATANGANI" in contract_document_print_html(signed_wet)

    # --- Test Tanda Tangan OTP Portal ---
    # Buat dokumen adendum untuk ditandatangani via OTP
    doc_otp = generate_addendum_document(contract_id=contract.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    ctx.session.flush()
    assert doc_otp.status == DOC_STATUS_PENDING

    # Minta OTP (email dipalsukan; kode ditangkap seperti yang diterima pelanggan)
    sent = {}

    def fake_send(to_email, contract_number, otp_code):
        sent["code"] = otp_code
        return True, None

    monkeypatch.setattr("app.services.customer_contract_document_service.send_contract_otp_email", fake_send)
    ok, msg = send_contract_signing_otp(
        document_id=doc_otp.id,
        user_id=f.portal_client_a.id,
        branch_id=f.branch.id,
        commit=False,
    )
    assert ok is True
    assert doc_otp.otp_code_hash is not None
    assert doc_otp.otp_expires_at is not None

    # OTP salah -> ditolak
    with pytest.raises(CustomerContractDocumentError, match="tidak valid"):
        verify_and_sign_contract_document_otp(
            document_id=doc_otp.id,
            user_id=f.portal_client_a.id,
            otp_code="999999",
            branch_id=f.branch.id,
            commit=False,
        )

    signed_otp = verify_and_sign_contract_document_otp(
        document_id=doc_otp.id,
        user_id=f.portal_client_a.id,
        otp_code=sent["code"],
        branch_id=f.branch.id,
        commit=False,
    )
    ctx.session.flush()

    assert signed_otp.status == DOC_STATUS_SIGNED
    assert signed_otp.signing_method == SIGNING_METHOD_OTP
    assert signed_otp.portal_signed_by_user_id == f.portal_client_a.id
    assert signed_otp.portal_signed_at is not None
    assert "verifikasi OTP email" in contract_document_print_html(signed_otp)


def test_portal_scoping_isolation(ctx):
    """Portal scoping: client hanya melihat dokumen miliknya, bukan milik client lain."""
    from app.services.portal_mapping_service import build_portal_external_scope

    f = _make_test_fixtures(ctx)

    # Kontrak Client A
    contract_a = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_a.id,
        title="Kontrak Katering",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 7",
        created_by=f.admin.id,
    )
    # Kontrak Client B
    contract_b = create_customer_contract(
        branch_id=f.branch.id,
        client_id=f.client_b.id,
        title="Kontrak B",
        start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31),
        payment_terms="net 7",
        created_by=f.admin.id,
    )
    ctx.session.flush()

    doc_a = generate_contract_document(contract_id=contract_a.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    doc_b = generate_contract_document(contract_id=contract_b.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    ctx.session.flush()

    # Scope Client A
    scope_a = build_portal_external_scope(f.portal_client_a)
    assert f.client_a.id in scope_a.client_ids
    assert f.client_b.id not in scope_a.client_ids

    # Scope Client B
    scope_b = build_portal_external_scope(f.portal_client_b)
    assert f.client_b.id in scope_b.client_ids
    assert f.client_a.id not in scope_b.client_ids

    # Dokumen Client A tidak boleh diakses oleh Client B
    from app.routes.portal_routes import _can_portal_user_access_contract
    assert _can_portal_user_access_contract(f.portal_client_a, contract_a) is True
    assert _can_portal_user_access_contract(f.portal_client_a, contract_b) is False
    assert _can_portal_user_access_contract(f.portal_client_b, contract_b) is True
    assert _can_portal_user_access_contract(f.portal_client_b, contract_a) is False


def test_otp_refused_without_smtp_and_never_logged(ctx, caplog, monkeypatch):
    """Tanpa SMTP, OTP tidak dikirim dan TIDAK ditulis ke log (OTP = tanda tangan)."""
    f = _make_test_fixtures(ctx)
    contract = create_customer_contract(
        branch_id=f.branch.id, client_id=f.client_a.id, title="Kontrak OTP", start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31), payment_terms="net 7", created_by=f.admin.id,
    )
    doc = generate_contract_document(contract_id=contract.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    monkeypatch.setitem(current_app.config, "MAIL_SERVER", "")
    monkeypatch.setattr("app.services.customer_contract_document_service.secrets.randbelow", lambda n: 424242)
    with pytest.raises(CustomerContractDocumentError, match="SMTP"):
        send_contract_signing_otp(document_id=doc.id, user_id=f.portal_client_a.id, branch_id=f.branch.id, commit=False)
    assert "424242" not in caplog.text


def test_saving_unchanged_rules_creates_no_addendum(ctx):
    f = _make_test_fixtures(ctx)
    contract = create_customer_contract(
        branch_id=f.branch.id, client_id=f.client_a.id, title="Kontrak Tetap", start_date=date(2026, 10, 1),
        end_date=date(2027, 3, 31), payment_terms="net 7", created_by=f.admin.id,
        lunch_lock_time="10:00", dinner_lock_time="15:00", due_days=7, tazir_amount=Decimal("50000.00"),
    )
    doc = generate_contract_document(contract_id=contract.id, branch_id=f.branch.id, created_by=f.admin.id, commit=False)
    doc.status = DOC_STATUS_SIGNED
    activate_customer_contract(contract.id, branch_id=f.branch.id, updated_by=f.admin.id, commit=False)
    rules = dict(dinner_lock_time="15:00", due_days=7, tazir_amount="50000",
                 billing_anchor_date=contract.billing_anchor_date, commit=False)

    update_customer_contract_rules(contract.id, branch_id=f.branch.id, actor=f.owner, lunch_lock_time="10:00", **rules)
    assert [d.document_type for d in list_contract_documents_for_contract(contract.id, f.branch.id)] == [DOC_TYPE_CONTRACT]

    update_customer_contract_rules(contract.id, branch_id=f.branch.id, actor=f.owner, lunch_lock_time="11:00", **rules)
    addendum = next(d for d in list_contract_documents_for_contract(contract.id, f.branch.id)
                    if d.document_type == DOC_TYPE_ADDENDUM)
    assert "Jam lock siang: 10:00 → 11:00" in addendum.notes
