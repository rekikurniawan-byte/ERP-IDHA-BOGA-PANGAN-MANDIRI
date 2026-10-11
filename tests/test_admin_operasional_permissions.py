"""Pengujian izin role ADMIN_OPERASIONAL:

1. ADMIN_OPERASIONAL DITOLAK di contoh halaman keuangan, akuntansi, master, pengaturan, warung.
2. ADMIN_OPERASIONAL DIIZINKAN di halaman lingkup operasional.
3. ADMIN_OPERASIONAL tidak bisa meloloskan pesanan sebelum lunas (hanya OWNER).
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import PortalOrderDraft
from app.services.portal_order_draft_service import confirm_portal_order_draft
from app.utils.clock import today_wib


def _login_user_id(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


@pytest.fixture
def auth_users(app):
    """Fixture membuat user ADMIN_OPERASIONAL dan OWNER."""
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-PERM-{suffix}", name="Branch Perm Test", is_active=True)
        db.session.add(branch)
        db.session.flush()

        ops_user = User(
            branch_id=branch.id,
            full_name=f"Ops User {suffix}",
            username=f"ops_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="ADMIN_OPERASIONAL",
            is_active=True,
        )
        owner_user = User(
            branch_id=branch.id,
            full_name=f"Owner User {suffix}",
            username=f"owner_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="OWNER",
            is_active=True,
        )
        db.session.add_all([ops_user, owner_user])
        db.session.commit()

        return {
            "branch_id": branch.id,
            "ops_user_id": ops_user.id,
            "owner_user_id": owner_user.id,
        }


def test_admin_operasional_denied_on_restricted_areas(app, client, auth_users):
    """ADMIN_OPERASIONAL ditolak (403/redirect) di halaman keuangan, akuntansi, master, pengaturan, dan warung."""
    _login_user_id(client, auth_users["ops_user_id"])

    restricted_pages = [
        # Keuangan (Finance)
        "/finance/invoices",
        "/finance/receivables",
        "/finance/manual-billing",
        "/finance/payment-history",
        # Akuntansi (Accounting)
        "/accounting/journals",
        "/accounting/reports",
        "/accounting/posting-status",
        # Data Master
        "/master/clients",
        "/master/suppliers",
        "/master/bank-accounts",
        # Pengaturan (Settings)
        "/settings/users",
        "/settings/company",
        "/settings/backups",
        # Warung (Canteen)
        "/canteen/",
        "/canteen/quick",
        "/canteen/debts",
        # Customer Success Komplain (ditutup untuk ADMIN_OPERASIONAL)
        "/customer-success/complaints",
    ]

    for page in restricted_pages:
        res = client.get(page, follow_redirects=False)
        assert res.status_code in (302, 403), f"Halaman terlarang {page} dapat diakses langsung (status {res.status_code})"


def test_admin_operasional_denied_on_delete_attachment_and_complaints(app, client, auth_users):
    """ADMIN_OPERASIONAL DITOLAK pada POST /delivery/attachments/<id>/delete dan /customer-success/complaints."""
    app.config["WTF_CSRF_ENABLED"] = False  # tes ini menguji izin role, bukan CSRF
    _login_user_id(client, auth_users["ops_user_id"])

    # 1. Halaman komplain ditolak (302 ke dashboard atau 403)
    res_complaints = client.get("/customer-success/complaints", follow_redirects=False)
    assert res_complaints.status_code in (302, 403), f"ADMIN_OPERASIONAL seharusnya ditolak di /customer-success/complaints, status: {res_complaints.status_code}"

    # 2. POST hapus lampiran bukti delivery ditolak (hanya ADMIN)
    res_delete = client.post("/delivery/attachments/1/delete", data={"delete_note": "Uji hapus"}, follow_redirects=False)
    assert res_delete.status_code in (302, 403), f"ADMIN_OPERASIONAL seharusnya ditolak di POST /delivery/attachments/1/delete, status: {res_delete.status_code}"


def test_admin_operasional_permitted_on_in_scope_pages(app, client, auth_users):
    """ADMIN_OPERASIONAL diizinkan (200) di seluruh halaman lingkup operasional."""
    _login_user_id(client, auth_users["ops_user_id"])

    in_scope_pages = [
        "/dashboard/ops",
        "/operational/orders",
        "/portal/admin/order-drafts",
        "/operational/order-qty-changes",
        "/operational/menu-schedule",
        "/production/",
        "/operational/kitchen-recap",
        "/delivery/today",
        "/delivery/receiving",
        "/delivery/history",
        "/delivery/scan",
        "/settings/account",
        "/settings/notifications",
        "/sop/admin",
    ]

    for page in in_scope_pages:
        res = client.get(page, follow_redirects=True)
        assert res.status_code == 200, f"Halaman lingkup {page} gagal diakses (status {res.status_code})"


def test_admin_operasional_cannot_override_unpaid_portal_order_draft(app, auth_users):
    """ADMIN_OPERASIONAL tidak bisa meloloskan pesanan yang belum lunas (hanya OWNER)."""
    with app.app_context():
        branch = db.session.get(Branch, auth_users["branch_id"])
        ops_user = db.session.get(User, auth_users["ops_user_id"])
        owner_user = db.session.get(User, auth_users["owner_user_id"])

        suffix = uuid4().hex[:6]
        # Pelanggan umum (UMUM) wajib bayar di muka per pesanan
        client_obj = Client(name=f"Pelanggan Umum {suffix}", phone="0811", is_active=True, customer_path="UMUM")
        db.session.add(client_obj)
        db.session.flush()

        mandor = Mandor(branch_id=branch.id, client_id=client_obj.id, name=client_obj.name, is_active=True)
        db.session.add(mandor)
        db.session.flush()

        loc = DeliveryLocation(mandor_id=mandor.id, location_name="Lokasi Uji", is_active=True)
        db.session.add(loc)
        db.session.flush()

        # Draf pesanan portal umum yang belum dibayar di muka (uang muka = 0 < total)
        draft = PortalOrderDraft(
            user_id=ops_user.id,
            branch_id=branch.id,
            client_id=client_obj.id,
            mandor_id=mandor.id,
            delivery_location_id=loc.id,
            order_date=today_wib() + timedelta(days=2),
            meal_type="LUNCH",
            portion_qty=10,
            price_per_portion=Decimal("25000"),
            price_source="STANDAR",
            delivery_fee=Decimal("15000"),
            idempotency_key=uuid4().hex,
            status="PENDING_ADMIN_CONFIRMATION",
        )
        db.session.add(draft)
        db.session.commit()
        draft_id = draft.id

        # Muat ulang user untuk session ini
        ops_user = db.session.get(User, auth_users["ops_user_id"])
        owner_user = db.session.get(User, auth_users["owner_user_id"])

        # ADMIN_OPERASIONAL mencoba meloloskan dengan owner_override=True -> HARUS DITOLAK
        draft_res, success_ops, msg_ops = confirm_portal_order_draft(
            draft_id=draft_id,
            admin_user=ops_user,
            owner_override=True,
            review_note="Operasional memaksa loloskan",
        )
        assert success_ops is False, "ADMIN_OPERASIONAL tidak boleh meloloskan pesanan yang belum lunas!"
        assert draft_res.status != "CONFIRMED"

        # OWNER mencoba meloloskan dengan owner_override=True dan alasan -> DIIZINKAN
        draft_res_owner, success_owner, msg_owner = confirm_portal_order_draft(
            draft_id=draft_id,
            admin_user=owner_user,
            owner_override=True,
            review_note="Disetujui OWNER untuk operasional khusus",
        )
        assert success_owner is True, f"OWNER seharusnya bisa meloloskan pesanan: {msg_owner}"
        assert draft_res_owner.status == "CONFIRMED"
