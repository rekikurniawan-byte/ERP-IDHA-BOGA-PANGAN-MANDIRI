from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models.finance import BankAccount
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import DigitalAttachment, PortalOrderDraft, PortalPaymentProofClaim
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_PENDING_TYPE,
    upload_portal_order_draft_payment_proof,
)
from app.services.pricing_service import (
    PATH_GENERAL,
    create_delivery_zone,
    set_delivery_fee,
    set_portion_price,
)
from tests.test_portal_payment_proof_service import PDF_BYTES, _file_storage
from tests.test_prepaid_orders import _ensure_accounts


TODAY = date.today()


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _setup_route_data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        _ensure_accounts(db)
        branch = Branch(code=f"PIB-{uuid4().hex[:8]}", name="Cabang Payment Inbox", is_active=True)
        client = Client(name=f"Pelanggan Toko {uuid4().hex[:6]}", phone="08123456789", is_active=True, customer_path=PATH_GENERAL)
        db.session.add_all([branch, client])
        db.session.flush()

        users = {
            role: User(
                branch_id=branch.id,
                full_name=f"{role} Pengguna",
                username=f"pib-{role.lower()}-{uuid4().hex[:8]}",
                password_hash="x",
                role=role,
                is_active=True,
            )
            for role in ("OWNER", "ADMIN", "PORTAL_CUSTOMER")
        }
        mandor = Mandor(branch_id=branch.id, client_id=client.id, name=client.name, is_active=True)
        db.session.add_all([mandor, *users.values()])
        db.session.flush()

        owner = users["OWNER"]
        zone = create_delivery_zone(branch.id, "Dalam Kota", owner.id)
        set_delivery_fee(branch_id=branch.id, zone_id=zone.id, fee=15000, effective_from=TODAY, created_by=owner.id)
        set_portion_price(branch_id=branch.id, price=25000, effective_from=TODAY, created_by=owner.id)
        location = DeliveryLocation(mandor_id=mandor.id, location_name="Kantor Proyek", is_active=True, delivery_zone_id=zone.id)
        db.session.add(location)

        bank = BankAccount(
            branch_id=branch.id,
            bank_name="BCA",
            account_number=f"5555-{uuid4().hex[:6]}",
            account_name="PT Idha Boga Mandiri",
            coa_account_code="1002",
            is_active=True,
        )
        db.session.add(bank)
        db.session.commit()

        return {
            "branch_id": branch.id,
            "client_id": client.id,
            "mandor_id": mandor.id,
            "location_id": location.id,
            "bank_id": bank.id,
            "admin_id": users["ADMIN"].id,
            "owner_id": users["OWNER"].id,
            "portal_customer_id": users["PORTAL_CUSTOMER"].id,
            "portal_customer_name": users["PORTAL_CUSTOMER"].full_name,
            "client_name": client.name,
        }


def _create_draft_and_proof(app, data, unique_code=237, claimed="315237", sender="Budi Tester", ref="REF-PIB-01"):
    with app.app_context():
        customer = db.session.get(User, data["portal_customer_id"])
        draft = PortalOrderDraft(
            user_id=data["portal_customer_id"],
            branch_id=data["branch_id"],
            client_id=data["client_id"],
            mandor_id=data["mandor_id"],
            delivery_location_id=data["location_id"],
            order_date=TODAY + timedelta(days=2),
            meal_type="LUNCH",
            portion_qty=12,
            price_per_portion=Decimal("25000"),
            price_source="STANDAR",
            delivery_fee=Decimal("15000"),
            payment_unique_code=unique_code,
            idempotency_key=uuid4().hex,
            status="PENDING_ADMIN_CONFIRMATION",
        )
        db.session.add(draft)
        db.session.commit()

        res = upload_portal_order_draft_payment_proof(
            customer,
            draft_id=draft.id,
            file_storage=_file_storage(filename=f"proof_{uuid4().hex[:6]}.pdf", payload=PDF_BYTES + uuid4().bytes),
            notes="Transfer pesanan portal",
            claimed_amount=claimed,
            sender_name=sender,
            transfer_reference=ref,
            commit=True,
        )
        return draft.id, res["attachment_id"]


# 1. GET sebagai ADMIN & OWNER -> 200, memuat nama pelanggan dan nominal "Harus ditransfer"; sebagai role portal -> ditolak (403/redirect)
def test_get_payment_inbox_admin_dan_owner_sukses_portal_ditolak(app, client):
    data = _setup_route_data(app)
    draft_id, att_id = _create_draft_and_proof(app, data)

    # Sebagai ADMIN
    _login_user_id(client, data["admin_id"])
    res_admin = client.get("/finance/payment-inbox")
    assert res_admin.status_code == 200
    html_admin = res_admin.get_data(as_text=True)
    assert "Harus Ditransfer" in html_admin or "Harus ditransfer" in html_admin
    assert data["portal_customer_name"] in html_admin or data["client_name"] in html_admin

    # Sebagai OWNER
    _login_user_id(client, data["owner_id"])
    res_owner = client.get("/finance/payment-inbox")
    assert res_owner.status_code == 200
    html_owner = res_owner.get_data(as_text=True)
    assert "Harus Ditransfer" in html_owner or "Harus ditransfer" in html_owner

    # Sebagai PORTAL_CUSTOMER (ditolak)
    _login_user_id(client, data["portal_customer_id"])
    res_portal = client.get("/finance/payment-inbox")
    assert res_portal.status_code in (302, 403)


# 2. Halaman tidak mengandung teks "User ID"
def test_payment_inbox_tidak_mengandung_teks_user_id(app, client):
    data = _setup_route_data(app)
    _create_draft_and_proof(app, data)

    _login_user_id(client, data["admin_id"])
    res = client.get("/finance/payment-inbox")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "User ID" not in html


# 3. POST approve sukses -> redirect + flash; draft CONFIRMED
def test_post_approve_payment_inbox_sukses_draft_confirmed(app, client):
    data = _setup_route_data(app)
    draft_id, att_id = _create_draft_and_proof(app, data, unique_code=237, claimed="315237", ref="REF-APPROVE-1")

    _login_user_id(client, data["admin_id"])
    post_data = {
        "draft_id": draft_id,
        "received_amount": "315237",
        "payment_method": "TRANSFER",
        "bank_account_id": data["bank_id"],
        "payment_date": TODAY.strftime("%Y-%m-%d"),
        "reference_number": "REF-APPROVE-1",
        "checked_mutation": "1",
        "note": "",
        "idempotency_key": uuid4().hex,
    }

    res = client.post(f"/finance/payment-inbox/{att_id}/approve", data=post_data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "masuk ke Operasional" in html or "diterima" in html

    with app.app_context():
        d = db.session.get(PortalOrderDraft, draft_id)
        assert d.status == "CONFIRMED"
        assert d.converted_daily_order_id is not None


# 4. POST approve dengan draft_id salah -> flash error, tidak ada perubahan
def test_post_approve_draft_id_salah_error_tidak_berubah(app, client):
    data = _setup_route_data(app)
    draft_id, att_id = _create_draft_and_proof(app, data)

    _login_user_id(client, data["admin_id"])
    post_data = {
        "draft_id": 9999999,  # draft_id salah
        "received_amount": "315237",
        "payment_method": "TRANSFER",
        "bank_account_id": data["bank_id"],
        "payment_date": TODAY.strftime("%Y-%m-%d"),
        "reference_number": "REF-WRONG-1",
        "checked_mutation": "1",
        "note": "",
        "idempotency_key": uuid4().hex,
    }

    res = client.post(f"/finance/payment-inbox/{att_id}/approve", data=post_data, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "tidak ditemukan" in html or "bukan milik" in html or "Terjadi kesalahan" in html

    with app.app_context():
        d = db.session.get(PortalOrderDraft, draft_id)
        assert d.status == "PENDING_ADMIN_CONFIRMATION"


# 5. Jumlah query GET tab waiting dengan 10 bukti <= 40 (mencegah N+1)
def test_get_payment_inbox_query_count_under_40_for_10_proofs(app, client):
    data = _setup_route_data(app)

    # Buat 10 draft dan bukti
    for i in range(10):
        _create_draft_and_proof(
            app,
            data,
            unique_code=100 + i,
            claimed=str(315100 + i),
            sender=f"Pengirim {i}",
            ref=f"REF-BULK-{uuid4().hex[:6]}",
        )

    _login_user_id(client, data["admin_id"])
    # Warm up context processors & caches (e.g. live reminder badge in sidebar)
    client.get("/finance/payment-inbox?tab=waiting")

    queries = []

    def _count_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    with app.app_context():
        engine = db.engine

    event.listen(engine, "before_cursor_execute", _count_queries)
    try:
        res = client.get("/finance/payment-inbox?tab=waiting")
        assert res.status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _count_queries)

    assert len(queries) <= 40, f"Terlalu banyak query: {len(queries)} query dieksekusi (maksimal 40)"
