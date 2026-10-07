from datetime import date
from uuid import uuid4

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import Notification
from app.services.notification_service import (
    count_unread_notifications,
    create_or_update_notification,
    list_notifications,
)
from app.services.user_management_service import (
    ROLE_ADMIN,
    ROLE_DAPUR,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CUSTOMER,
)


def _setup_branch(code="ISOL"):
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"T-ISO-{suffix}", name="Branch Isolation", is_active=True)
    db.session.add(branch)
    db.session.flush()
    return branch


def _create_user(branch, role, username_prefix="u_iso"):
    suffix = uuid4().hex[:6]
    user = User(
        branch_id=branch.id,
        full_name=f"User {role} {suffix}",
        username=f"{username_prefix}_{role.lower()}_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def test_notification_isolation_across_roles(app):
    with app.app_context():
        branch = _setup_branch()
        admin = _create_user(branch, ROLE_ADMIN)
        dapur = _create_user(branch, ROLE_DAPUR)
        pengantar = _create_user(branch, ROLE_PENGANTAR)
        portal_a = _create_user(branch, ROLE_PORTAL_CUSTOMER, "porta")
        portal_b = _create_user(branch, ROLE_PORTAL_CUSTOMER, "portb")

        # 1. Notif internal ADMIN
        notif_admin, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="SYSTEM",
            title="Notif Admin",
            message="Untuk admin",
            target_role="ADMIN",
            priority="WARNING",
            generated_key=f"k-admin-{uuid4().hex[:6]}",
            commit=False,
        )

        # 2. Notif legacy FINANCE (harus terlihat oleh ADMIN)
        notif_finance, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="SYSTEM",
            title="Notif Finance",
            message="Untuk finance / admin",
            target_role="FINANCE",
            priority="INFO",
            generated_key=f"k-finance-{uuid4().hex[:6]}",
            commit=False,
        )

        # 3. Notif DAPUR
        notif_dapur, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="SYSTEM",
            title="Notif Dapur",
            message="Untuk dapur",
            target_role="DAPUR",
            priority="INFO",
            generated_key=f"k-dapur-{uuid4().hex[:6]}",
            commit=False,
        )

        # 4. Notif PENGANTAR
        notif_pengantar, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="SYSTEM",
            title="Notif Pengantar",
            message="Untuk pengantar",
            target_role="PENGANTAR",
            priority="CRITICAL",
            generated_key=f"k-pengantar-{uuid4().hex[:6]}",
            commit=False,
        )

        # 5. Notif Portal A (spesifik user A)
        notif_porta, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="PORTAL",
            title="Notif Portal A",
            message="Pesanan A siap",
            target_user_id=portal_a.id,
            priority="INFO",
            generated_key=f"k-porta-{uuid4().hex[:6]}",
            commit=False,
        )

        # 6. Notif Portal B (spesifik user B)
        notif_portb, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="PORTAL",
            title="Notif Portal B",
            message="Pesanan B siap",
            target_user_id=portal_b.id,
            priority="INFO",
            generated_key=f"k-portb-{uuid4().hex[:6]}",
            commit=False,
        )

        # 7. Notif umum cabang internal
        notif_general, _ = create_or_update_notification(
            branch_id=branch.id,
            notification_type="SYSTEM",
            title="Notif Umum Cabang",
            message="Pengumuman cabang",
            target_role=None,
            target_user_id=None,
            priority="INFO",
            generated_key=f"k-gen-{uuid4().hex[:6]}",
            commit=False,
        )

        db.session.flush()

        # TEST ADMIN
        admin_notifs = list_notifications(branch_id=branch.id, user=admin)
        admin_ids = {n.id for n in admin_notifs}
        assert notif_admin.id in admin_ids
        assert notif_finance.id in admin_ids
        assert notif_general.id in admin_ids
        assert notif_dapur.id not in admin_ids
        assert notif_pengantar.id not in admin_ids
        assert notif_porta.id not in admin_ids
        assert notif_portb.id not in admin_ids

        admin_badge = count_unread_notifications(branch_id=branch.id, user=admin)
        assert admin_badge["total"] == len(admin_ids)

        # TEST DAPUR
        dapur_notifs = list_notifications(branch_id=branch.id, user=dapur)
        dapur_ids = {n.id for n in dapur_notifs}
        assert notif_dapur.id in dapur_ids
        assert notif_general.id in dapur_ids
        assert notif_admin.id not in dapur_ids
        assert notif_finance.id not in dapur_ids
        assert notif_pengantar.id not in dapur_ids
        assert notif_porta.id not in dapur_ids
        assert notif_portb.id not in dapur_ids

        dapur_badge = count_unread_notifications(branch_id=branch.id, user=dapur)
        assert dapur_badge["total"] == len(dapur_ids)

        # TEST PENGANTAR
        pengantar_notifs = list_notifications(branch_id=branch.id, user=pengantar)
        pengantar_ids = {n.id for n in pengantar_notifs}
        assert notif_pengantar.id in pengantar_ids
        assert notif_general.id in pengantar_ids
        assert notif_admin.id not in pengantar_ids
        assert notif_dapur.id not in pengantar_ids
        assert notif_porta.id not in pengantar_ids
        assert notif_portb.id not in pengantar_ids

        pengantar_badge = count_unread_notifications(branch_id=branch.id, user=pengantar)
        assert pengantar_badge["total"] == len(pengantar_ids)

        # TEST PORTAL A
        porta_notifs = list_notifications(branch_id=branch.id, user=portal_a)
        porta_ids = {n.id for n in porta_notifs}
        assert notif_porta.id in porta_ids
        assert notif_portb.id not in porta_ids
        assert notif_admin.id not in porta_ids
        assert notif_dapur.id not in porta_ids
        assert notif_pengantar.id not in porta_ids
        assert notif_general.id not in porta_ids

        porta_badge = count_unread_notifications(branch_id=branch.id, user=portal_a)
        assert porta_badge["total"] == 1

        # TEST PORTAL B
        portb_notifs = list_notifications(branch_id=branch.id, user=portal_b)
        portb_ids = {n.id for n in portb_notifs}
        assert notif_portb.id in portb_ids
        assert notif_porta.id not in portb_ids
        assert notif_admin.id not in portb_ids
        assert notif_general.id not in portb_ids


def test_sop_isolation_across_roles(client, app):
    with app.app_context():
        branch = _setup_branch("SOPB")
        admin = _create_user(branch, ROLE_ADMIN, "s_adm")
        dapur = _create_user(branch, ROLE_DAPUR, "s_dap")
        pengantar = _create_user(branch, ROLE_PENGANTAR, "s_pen")
        portal = _create_user(branch, ROLE_PORTAL_CUSTOMER, "s_por")
        db.session.commit()
        admin_id = admin.id
        dapur_id = dapur.id
        pengantar_id = pengantar.id
        portal_id = portal.id

    # 1. Login sebagai DAPUR
    with client.session_transaction() as sess:
        sess["_user_id"] = str(dapur_id)
        sess["_fresh"] = True

    # DAPUR can access /sop/dapur
    resp = client.get("/sop/dapur")
    assert resp.status_code == 200
    assert "SOP Dapur" in resp.get_data(as_text=True)

    # DAPUR cannot access /sop/admin, /sop/delivery, /sop/owner
    assert client.get("/sop/admin").status_code == 403
    assert client.get("/sop/delivery").status_code == 403
    assert client.get("/sop/owner").status_code == 403
    assert client.get("/sop/disaster-recovery").status_code == 403

    # DAPUR index only has dapur SOP
    resp_index = client.get("/sop/")
    assert resp_index.status_code == 200
    html = resp_index.get_data(as_text=True)
    assert "SOP Dapur" in html
    assert "SOP Admin" not in html
    assert "SOP Pengantaran" not in html

    # 2. Login sebagai PENGANTAR
    with client.session_transaction() as sess:
        sess["_user_id"] = str(pengantar_id)
        sess["_fresh"] = True

    # PENGANTAR can access /sop/delivery
    resp = client.get("/sop/delivery")
    assert resp.status_code == 200
    assert "SOP Delivery" in resp.get_data(as_text=True)

    # PENGANTAR cannot access /sop/dapur or /sop/admin
    assert client.get("/sop/dapur").status_code == 403
    assert client.get("/sop/admin").status_code == 403
    assert client.get("/sop/disaster-recovery").status_code == 403

    # PENGANTAR index only has delivery
    resp_index = client.get("/sop/")
    assert resp_index.status_code == 200
    html = resp_index.get_data(as_text=True)
    assert "SOP Delivery" in html
    assert "SOP Dapur" not in html
    assert "SOP Admin" not in html

    # 3. Login sebagai ADMIN
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    assert client.get("/sop/admin").status_code == 200
    assert client.get("/sop/finance").status_code == 200
    assert client.get("/sop/disaster-recovery").status_code == 200
    assert client.get("/sop/dapur").status_code == 403
    assert client.get("/sop/delivery").status_code == 403
    assert client.get("/sop/owner").status_code == 403

    # 4. Login sebagai PORTAL
    with client.session_transaction() as sess:
        sess["_user_id"] = str(portal_id)
        sess["_fresh"] = True

    # Portal user gets 403 on internal SOP routes
    assert client.get("/sop/").status_code == 403
    assert client.get("/sop/dapur").status_code == 403
    assert client.get("/sop/admin").status_code == 403
