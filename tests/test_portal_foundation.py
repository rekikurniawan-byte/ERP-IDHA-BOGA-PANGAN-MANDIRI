from io import BytesIO
from datetime import date, datetime, timedelta
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.complaint import CustomerComplaint
from app.models.contract import CustomerContract
from app.models.delivery import Delivery, DeliveryDetail
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Driver, Mandor, User
from app.models.operational import DailyOrder
from app.models.production import Production
from app.models.system import ApprovalRequest, DigitalAttachment, Notification, PortalOrderDraft
from app.models.system import PortalUserMapping
from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_location_directory,
    build_portal_mandor_directory,
    build_portal_ownership_analysis,
    build_portal_status_shell,
)
from app.services.portal_mapping_service import (
    PRINCIPAL_CLIENT,
    PRINCIPAL_DELEGATE,
    PRINCIPAL_MANDOR,
    build_portal_external_scope,
)
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_CLIENT,
    validate_user_payload,
)


def _create_test_user(role="OWNER"):
    suffix = uuid4().hex[:10]
    branch = Branch(
        code=f"T-PORTAL-{suffix}",
        name="Test Portal Branch",
        address="Test",
        phone="0800000000",
        is_active=True,
    )
    user = User(
        branch=branch,
        full_name=f"Test Portal {role}",
        username=f"portal-{role.lower()}-{suffix}",
        password_hash=generate_password_hash("portal-test-password"),
        role=role,
        is_active=True,
    )
    db.session.add(branch)
    db.session.add(user)
    db.session.flush()
    return user


def _create_user_for_branch(role, branch):
    suffix = uuid4().hex[:10]
    user = User(
        branch=branch,
        full_name=f"Test Portal {role}",
        username=f"portal-{role.lower()}-{suffix}",
        password_hash=generate_password_hash("portal-test-password"),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user):
    _login_user_id(client, user.id)


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _login_with_password(client, username, password="portal-test-password"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def _create_scope_master_data(user):
    client = Client(
        client_code=f"T-PORTAL-CLIENT-{uuid4().hex[:8]}",
        name="AAA Test Portal Client",
        address="Test",
        phone="0800000001",
        is_active=True,
    )
    db.session.add(client)
    db.session.flush()

    client_pic = ClientPic(
        client_id=client.id,
        name="AAA Test Portal PIC",
        phone="0800000002",
        email="portal@example.test",
        position="PIC",
        is_active=True,
    )
    mandor = Mandor(
        branch_id=user.branch_id,
        client_id=client.id,
        name="AAA Test Portal Mandor",
        phone="0800000003",
        is_active=True,
    )
    db.session.add(client_pic)
    db.session.add(mandor)
    db.session.flush()

    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name="AAA Test Portal Location",
        description="Test location",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return client, client_pic, mandor, location


def _create_portal_mapping(
    user,
    *,
    principal_type,
    mandor=None,
    client=None,
    client_pic=None,
    location=None,
    access_level="READ_ONLY",
):
    mapping = PortalUserMapping(
        user_id=user.id,
        principal_type=principal_type,
        client_id=client.id if client else None,
        mandor_id=mandor.id if mandor else None,
        client_pic_id=client_pic.id if client_pic else None,
        delivery_location_id=location.id if location else None,
        access_level=access_level,
        is_active=True,
    )
    db.session.add(mapping)
    db.session.flush()
    return mapping


def _create_other_branch_scope_data():
    branch = Branch(
        code=f"T-PORTAL-OTHER-{uuid4().hex[:8]}",
        name="Other Portal Branch",
        address="Other",
        phone="0800000099",
        is_active=True,
    )
    client = Client(
        client_code=f"T-PORTAL-OTHER-CLIENT-{uuid4().hex[:8]}",
        name="ZZZ Other Branch Client",
        address="Other",
        phone="0800000098",
        is_active=True,
    )
    db.session.add(branch)
    db.session.add(client)
    db.session.flush()
    mandor = Mandor(
        branch_id=branch.id,
        client_id=client.id,
        name="ZZZ Other Branch Mandor",
        phone="0800000097",
        is_active=True,
    )
    db.session.add(mandor)
    db.session.flush()
    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name="ZZZ Other Branch Location",
        description="Other",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return branch, client, mandor, location


def _create_extra_mandor_location(user, client_obj, name_prefix):
    mandor = Mandor(
        branch_id=user.branch_id,
        client_id=client_obj.id,
        name=f"{name_prefix} Mandor",
        phone="0800000044",
        is_active=True,
    )
    db.session.add(mandor)
    db.session.flush()
    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name=f"{name_prefix} Location",
        description="Sibling scope test",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return mandor, location


def test_portal_feature_flag_off_returns_404_for_authenticated_owner(app):
    app.config["PORTAL_ENABLED"] = False

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            with app.test_client() as client:
                _login(client, user)
                assert client.get("/portal").status_code == 404
                assert client.get("/portal/dashboard").status_code == 404
        finally:
            transaction.rollback()


def test_portal_enabled_requires_login(app):
    app.config["PORTAL_ENABLED"] = True

    with app.test_client() as client:
        response = client.get("/portal/dashboard")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_portal_external_login_redirects_to_portal_dashboard(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CLIENT)
        username = user.username
        db.session.commit()

    with app.test_client() as client:
        response = _login_with_password(client, username)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/portal/pt")


def test_authenticated_portal_external_login_page_redirects_to_portal_dashboard(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CUSTOMER)
        username = user.username
        db.session.commit()

    with app.test_client() as client:
        with app.app_context():
            _login(client, User.query.filter_by(username=username).first())
        response = client.get("/auth/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/portal/customer")


def test_portal_enabled_allows_owner_and_admin_preview(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            users = [_create_test_user("OWNER"), _create_test_user("ADMIN")]
            for user in users:
                with app.test_client() as client:
                    _login(client, user)
                    response = client.get("/portal/dashboard")
                    html = response.get_data(as_text=True)

                assert response.status_code == 200
                assert "Pengaturan Akses Portal" in html
                assert "Kontrol integrasi user portal ke data ERP existing" in html
                assert "User Portal" in html
                assert "Mapping Aktif" in html
                assert "Draft Pending" in html
                assert "clients, mandors, delivery_locations" in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_hidden_when_feature_flag_off(app):
    app.config["PORTAL_ENABLED"] = False

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal' not in html
            assert "Pengaturan Akses" not in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_visible_when_feature_flag_on_for_owner(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal/dashboard"' in html
            assert 'href="/portal/customers"' not in html
            assert 'href="/portal/mandors"' not in html
            assert 'href="/portal/locations"' not in html
            assert 'href="/portal/orders/draft"' not in html
            assert 'href="/portal/orders/status"' not in html
            assert 'href="/portal/invoices"' not in html
            assert 'href="/portal/payments"' not in html
            assert 'href="/portal/debts"' not in html
            assert 'href="/portal/closing"' not in html
            assert 'href="/portal/status"' not in html
            assert 'href="/portal/ownership"' not in html
            assert "Pengaturan Akses" in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_hidden_for_non_preview_role_even_when_enabled(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            # DAPUR, not FINANCE: FINANCE is retired into ADMIN, which
            # legitimately administers the portal.
            user = _create_test_user("DAPUR")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal' not in html
            assert "Pengaturan Akses" not in html
        finally:
            transaction.rollback()


def test_portal_enabled_rejects_unauthorized_internal_role(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            # DAPUR, not FINANCE: FINANCE is retired into ADMIN, which
            # legitimately administers the portal.
            user = _create_test_user("DAPUR")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/dashboard")

            assert response.status_code == 302
            assert response.headers["Location"].endswith("/")
        finally:
            transaction.rollback()


def test_portal_route_has_no_session_commit_or_rollback():
    source = open("app/routes/portal_routes.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source


def test_portal_access_scope_is_branch_scoped_for_admin(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_scope_master_data(user)

            scope = build_portal_access_scope(user)

            assert scope["allowed"] is True
            assert scope["scope_mode"] == "ADMIN_BRANCH_PREVIEW"
            assert scope["counts"]["clients"] == 1
            assert scope["counts"]["client_pics"] == 1
            assert scope["counts"]["mandors"] == 1
            assert scope["counts"]["locations"] == 1
            assert scope["active_counts"]["clients"] == 1
            assert scope["active_counts"]["mandors"] == 1
            assert scope["active_counts"]["locations"] == 1
            assert scope["client_preview"][0]["name"] == "AAA Test Portal Client"
            assert scope["mandor_preview"][0]["name"] == "AAA Test Portal Mandor"
            assert scope["location_preview"][0]["name"] == "AAA Test Portal Location"
        finally:
            transaction.rollback()


def test_portal_readonly_directories_are_branch_scoped_for_admin(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_scope_master_data(user)
            _create_other_branch_scope_data()

            with app.test_client() as client:
                _login(client, user)
                customers_response = client.get("/portal/customers")
                mandors_response = client.get("/portal/mandors")
                locations_response = client.get("/portal/locations")

            customers_html = customers_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)
            locations_html = locations_response.get_data(as_text=True)

            assert customers_response.status_code == 200
            assert mandors_response.status_code == 200
            assert locations_response.status_code == 200
            assert "Client/PT Read-only" in customers_html
            assert "Mandor Read-only" in mandors_html
            assert "Lokasi Read-only" in locations_html
            assert "AAA Test Portal Client" in customers_html
            assert "AAA Test Portal Mandor" in mandors_html
            assert "AAA Test Portal Location" in locations_html
            assert "ZZZ Other Branch Client" not in customers_html
            assert "ZZZ Other Branch Mandor" not in mandors_html
            assert "ZZZ Other Branch Location" not in locations_html
            assert 'action="/portal' not in customers_html.lower()
            assert 'action="/portal' not in mandors_html.lower()
            assert 'action="/portal' not in locations_html.lower()
        finally:
            transaction.rollback()


def test_portal_status_shell_is_read_only_and_shows_approval_gates(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            status = build_portal_status_shell(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/status")

            html = response.get_data(as_text=True)
            assert status["ready_count"] >= 1
            assert status["approval_required_count"] >= 1
            assert response.status_code == 200
            assert "Status Portal Read-only" in html
            assert "Akun eksternal Client/PT/Mandor" in html
            assert "Draft order portal" in html
            assert "Invoice/payment portal" in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_ownership_analysis_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_scope_master_data(user)
            _create_other_branch_scope_data()
            analysis = build_portal_ownership_analysis(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/ownership")

            html = response.get_data(as_text=True)
            assert analysis["summary"]["scope_mode"] == "ADMIN_BRANCH_PREVIEW"
            assert analysis["summary"]["clients"] == 1
            assert analysis["summary"]["mandors"] == 1
            assert analysis["summary"]["locations"] == 1
            assert response.status_code == 200
            assert "Ownership Portal" in html
            assert "User.branch_id, User.role" in html
            assert "APPROVAL_REQUIRED" in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_access_service_has_no_session_commit_or_rollback():
    source = open("app/services/portal_access_service.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source


def test_user_management_accepts_portal_roles_on_existing_auth(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            owner = _create_test_user("OWNER")
            payload, error = validate_user_payload(
                {
                    "full_name": "Portal Mandor User",
                    "username": f"portal-mandor-{uuid4().hex[:8]}",
                    "role": ROLE_PORTAL_SUBCLIENT,
                    "branch_id": str(owner.branch_id),
                    "is_active": "on",
                }
            )

            assert error is None
            assert payload["role"] == ROLE_PORTAL_SUBCLIENT
            assert payload["branch_id"] == owner.branch_id

            pt_payload, pt_error = validate_user_payload(
                {
                    "full_name": "Portal PT User",
                    "username": f"portal-pt-{uuid4().hex[:8]}",
                    "role": ROLE_PORTAL_CLIENT,
                    "branch_id": str(owner.branch_id),
                    "is_active": "on",
                }
            )
            assert pt_error is None
            assert pt_payload["role"] == ROLE_PORTAL_CLIENT
        finally:
            transaction.rollback()


def test_portal_external_mandor_scope_uses_mapping_and_hides_other_branch(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
            client_obj, client_pic, mandor, location = _create_scope_master_data(user)
            sibling_mandor, sibling_location = _create_extra_mandor_location(user, client_obj, "BBB Same Client")
            _create_portal_mapping(user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
            _create_other_branch_scope_data()

            scope = build_portal_external_scope(user)
            access_scope = build_portal_access_scope(user)

            assert scope.allowed is True
            assert scope.scope_mode == "PORTAL_SUBCLIENT_SCOPE"
            assert scope.client_ids == {client_obj.id}
            assert scope.mandor_ids == {mandor.id}
            assert scope.delivery_location_ids == {location.id}
            assert sibling_mandor.id not in scope.mandor_ids
            assert sibling_location.id not in scope.delivery_location_ids
            assert client_pic.id not in scope.client_pic_ids
            assert access_scope["allowed"] is True
            assert access_scope["counts"]["clients"] == 1
            assert access_scope["counts"]["mandors"] == 1
            assert access_scope["counts"]["locations"] == 1

            with app.test_client() as client:
                _login(client, user)
                index_response = client.get("/")
                dashboard_response = client.get("/portal/my-dashboard", follow_redirects=True)
                customers_response = client.get("/portal/customers")
                mandors_response = client.get("/portal/mandors")
                locations_response = client.get("/portal/locations")
                status_response = client.get("/portal/status")
                ownership_response = client.get("/portal/ownership")

            assert index_response.status_code == 302
            assert index_response.headers["Location"].endswith("/portal/my-dashboard")

            dashboard_html = dashboard_response.get_data(as_text=True)

            assert dashboard_response.status_code == 200
            assert customers_response.status_code == 302
            assert mandors_response.status_code == 302
            assert locations_response.status_code == 302
            assert status_response.status_code == 302
            assert "PORTAL_SUBCLIENT_SCOPE" in dashboard_html
            assert "AAA Test Portal Client" not in dashboard_html
            assert "AAA Test Portal Mandor" not in dashboard_html
            assert "BBB Same Client Mandor" not in dashboard_html
            assert "ZZZ Other Branch Client" not in dashboard_html
            assert "ZZZ Other Branch Mandor" not in dashboard_html
            assert "Ownership" not in dashboard_html
            assert ownership_response.status_code == 302
        finally:
            transaction.rollback()


def test_portal_client_scope_covers_client_family_without_other_client(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user(ROLE_PORTAL_CLIENT)
            client_obj, _client_pic, mandor, location = _create_scope_master_data(user)
            sibling_mandor, sibling_location = _create_extra_mandor_location(user, client_obj, "BBB Same Client")
            _create_portal_mapping(user, principal_type=PRINCIPAL_CLIENT, client=client_obj)
            _create_other_branch_scope_data()

            scope = build_portal_external_scope(user)
            directory = build_portal_mandor_directory(user)

            assert scope.allowed is True
            assert scope.scope_mode == "PORTAL_CLIENT_SCOPE"
            assert scope.client_ids == {client_obj.id}
            assert {mandor.id, sibling_mandor.id}.issubset(scope.mandor_ids)
            assert {location.id, sibling_location.id}.issubset(scope.delivery_location_ids)
            assert directory["allowed"] is True
            assert {row["name"] for row in directory["rows"]} == {
                "AAA Test Portal Mandor",
                "BBB Same Client Mandor",
            }

            with app.test_client() as client:
                _login(client, user)
                profile_response = client.get("/portal/profile")
                mandors_response = client.get("/portal/mandors")

            profile_html = profile_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)

            assert profile_response.status_code == 200
            assert mandors_response.status_code == 302
            assert "PORTAL_CLIENT_SCOPE" in profile_html
            assert "AAA Test Portal Mandor" not in mandors_html
            assert "BBB Same Client Mandor" not in mandors_html
            assert "ZZZ Other Branch Mandor" not in mandors_html
        finally:
            transaction.rollback()


def test_portal_delegate_location_scope_is_limited_to_mapped_location(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user(ROLE_PORTAL_DELEGATE)
            client_obj, _client_pic, mandor, location = _create_scope_master_data(user)
            sibling_location = DeliveryLocation(
                mandor_id=mandor.id,
                location_name="BBB Same Mandor Other Location",
                description="Should stay hidden",
                is_active=True,
            )
            db.session.add(sibling_location)
            _create_extra_mandor_location(user, client_obj, "CCC Same Client Other")
            db.session.flush()
            _create_portal_mapping(user, principal_type=PRINCIPAL_DELEGATE, location=location)

            scope = build_portal_external_scope(user)
            directory = build_portal_location_directory(user)
            mandor_directory = build_portal_mandor_directory(user)

            assert scope.allowed is True
            assert scope.scope_mode == "PORTAL_DELEGATE_SCOPE"
            assert scope.client_ids == {client_obj.id}
            assert scope.mandor_ids == {mandor.id}
            assert scope.delivery_location_ids == {location.id}
            assert sibling_location.id not in scope.delivery_location_ids
            assert directory["allowed"] is True
            assert len(directory["rows"]) == 1
            assert directory["rows"][0]["name"] == "AAA Test Portal Location"
            assert mandor_directory["allowed"] is True
            assert {row["name"] for row in mandor_directory["rows"]} == {"AAA Test Portal Mandor"}

            with app.test_client() as client:
                _login(client, user)
                profile_response = client.get("/portal/profile")
                mandors_response = client.get("/portal/mandors")
                locations_response = client.get("/portal/locations")

            profile_html = profile_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)
            locations_html = locations_response.get_data(as_text=True)

            assert profile_response.status_code == 200
            assert mandors_response.status_code == 302
            assert locations_response.status_code == 302
            assert "PORTAL_DELEGATE_SCOPE" in profile_html
            assert "AAA Test Portal Location" in profile_html
            assert "BBB Same Mandor Other Location" not in profile_html
            assert "AAA Test Portal Mandor" not in mandors_html
            assert "CCC Same Client Other Mandor" not in mandors_html
            assert "AAA Test Portal Location" not in locations_html
            assert "BBB Same Mandor Other Location" not in locations_html
            assert "CCC Same Client Other Location" not in locations_html
        finally:
            transaction.rollback()


def test_unmapped_portal_external_user_does_not_receive_master_data(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
            _create_scope_master_data(user)

            access_scope = build_portal_access_scope(user)
            assert access_scope["allowed"] is False
            assert access_scope["scope_mode"] == "NO_PORTAL_SCOPE"
            assert access_scope["counts"]["clients"] == 0
            assert access_scope["counts"]["mandors"] == 0

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/my-dashboard", follow_redirects=True)

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert "AAA Test Portal Client" not in html
            assert "User portal belum memiliki mapping aktif" in html
        finally:
            transaction.rollback()


def test_portal_draft_order_requires_draft_order_mapping(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        _client_obj, _client_pic, mandor, location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
        db.session.commit()

        with app.test_client() as client:
            _login(client, user)
            get_response = client.get("/portal/orders/draft")
            post_response = client.post(
                "/portal/orders/draft",
                data={
                    "order_date": "2099-01-01",
                    "meal_type": "LUNCH",
                    "portion_qty": "10",
                    "delivery_location_id": str(location.id),
                    "idempotency_key": f"readonly-{uuid4().hex}",
                },
            )

        assert get_response.status_code == 200
        assert "Belum Bisa Membuat Draft" in get_response.get_data(as_text=True)
        assert post_response.status_code == 400
        assert (
            PortalOrderDraft.query.filter(PortalOrderDraft.user_id == user.id).count()
            == 0
        )


def test_portal_draft_order_submit_is_idempotent_and_does_not_create_operational_order(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        _client_obj, _client_pic, mandor, location = _create_scope_master_data(user)
        _create_portal_mapping(
            user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        db.session.commit()
        operational_count_before = DailyOrder.query.count()
        key = f"draft-{uuid4().hex}"

        with app.test_client() as client:
            _login(client, user)
            get_response = client.get("/portal/orders/draft")
            first_response = client.post(
                "/portal/orders/draft",
                data={
                    "order_date": "2099-01-01",
                    "meal_type": "LUNCH",
                    "portion_qty": "10",
                    "delivery_location_id": str(location.id),
                    "notes": "QA draft portal",
                    "idempotency_key": key,
                },
            )
            second_response = client.post(
                "/portal/orders/draft",
                data={
                    "order_date": "2099-01-01",
                    "meal_type": "LUNCH",
                    "portion_qty": "10",
                    "delivery_location_id": str(location.id),
                    "notes": "QA draft portal duplicate",
                    "idempotency_key": key,
                },
            )

        drafts = PortalOrderDraft.query.filter(
            PortalOrderDraft.user_id == user.id,
            PortalOrderDraft.idempotency_key == key,
        ).all()

        assert get_response.status_code == 200
        assert "Kirim Draft" in get_response.get_data(as_text=True)
        assert first_response.status_code == 302
        assert second_response.status_code == 302
        assert len(drafts) == 1
        assert drafts[0].status == "PENDING_ADMIN_CONFIRMATION"
        assert drafts[0].portion_qty == 10
        assert drafts[0].delivery_location_id == location.id
        assert DailyOrder.query.count() == operational_count_before


def test_portal_draft_order_rejects_location_outside_scope(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        _client_obj, _client_pic, mandor, _location = _create_scope_master_data(user)
        _other_branch, _other_client, _other_mandor, other_location = _create_other_branch_scope_data()
        _create_portal_mapping(
            user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        db.session.commit()

        with app.test_client() as client:
            _login(client, user)
            response = client.post(
                "/portal/orders/draft",
                data={
                    "order_date": "2099-01-01",
                    "meal_type": "LUNCH",
                    "portion_qty": "10",
                    "delivery_location_id": str(other_location.id),
                    "idempotency_key": f"outside-{uuid4().hex}",
                },
            )

        assert response.status_code == 400
        assert (
            PortalOrderDraft.query.filter(PortalOrderDraft.user_id == user.id).count()
            == 0
        )


def test_admin_confirmation_bridge_converts_draft_once_to_daily_order(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        portal_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        admin = _create_user_for_branch("ADMIN", portal_user.branch)
        portal_username = portal_user.username
        admin_username = admin.username
        _client_obj, _client_pic, mandor, location = _create_scope_master_data(portal_user)
        location_id = location.id
        _create_portal_mapping(
            portal_user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        db.session.commit()
        operational_count_before = DailyOrder.query.count()

    client = app.test_client()
    _login_with_password(client, portal_username)
    submit_response = client.post(
        "/portal/orders/draft",
        data={
            "order_date": "2099-01-02",
            "meal_type": "DINNER",
            "portion_qty": "12",
            "delivery_location_id": str(location_id),
            "notes": "QA bridge portal",
            "idempotency_key": f"bridge-{uuid4().hex}",
        },
    )

    with app.app_context():
        draft = (
            PortalOrderDraft.query.filter(PortalOrderDraft.user.has(username=portal_username))
            .order_by(PortalOrderDraft.id.desc())
            .first()
        )
        draft_id = draft.id

    client = app.test_client()
    _login_with_password(client, admin_username)
    list_response = client.get("/portal/admin/order-drafts")
    first_confirm = client.post(f"/portal/admin/order-drafts/{draft_id}/confirm")
    second_confirm = client.post(f"/portal/admin/order-drafts/{draft_id}/confirm")

    client = app.test_client()
    _login_with_password(client, portal_username)
    status_response = client.get("/portal/orders/status")

    with app.app_context():
        draft = PortalOrderDraft.query.get(draft_id)
        db.session.refresh(draft)
        daily_order = DailyOrder.query.get(draft.converted_daily_order_id)
        details = daily_order.details

        assert submit_response.status_code == 302
        assert list_response.status_code == 200
        assert status_response.status_code == 200
        assert "QA bridge portal" in list_response.get_data(as_text=True)
        status_html = status_response.get_data(as_text=True)
        assert "CONFIRMED" in status_html
        assert daily_order.order_number in status_html
        assert "Rp " not in status_html
        assert first_confirm.status_code == 302
        assert second_confirm.status_code == 302
        assert DailyOrder.query.count() == operational_count_before + 1
        assert daily_order.status == "DRAFT"
        assert daily_order.is_locked is False
        assert len(details) == 1
        assert details[0].dinner_qty == 12
        assert details[0].lunch_qty == 0
        assert details[0].total_qty == 12
        assert draft.status == "CONFIRMED"


def test_portal_pt_cannot_submit_draft_order_or_create_operational_data(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CLIENT)
        username = user.username
        client_obj, _client_pic, _mandor, location = _create_scope_master_data(user)
        _create_portal_mapping(
            user,
            principal_type=PRINCIPAL_CLIENT,
            client=client_obj,
            access_level="DRAFT_ORDER",
        )
        user_id = user.id
        db.session.commit()
        operational_count_before = DailyOrder.query.count()

    client = app.test_client()
    _login_with_password(client, username)
    page_response = client.get("/portal/pt/order", follow_redirects=False)
    submit_response = client.post(
        "/portal/orders/draft",
        data={
            "order_date": "2099-04-01",
            "meal_type": "LUNCH",
            "portion_qty": "25",
            "delivery_location_id": "1",
            "notes": "PT portal order draft",
            "idempotency_key": f"pt-draft-{uuid4().hex}",
        },
        follow_redirects=False,
    )

    with app.app_context():
        draft = PortalOrderDraft.query.filter_by(user_id=user_id).order_by(PortalOrderDraft.id.desc()).first()
        operational_count_after = DailyOrder.query.count()

    assert page_response.status_code == 302
    assert page_response.headers["Location"].endswith("/portal/pt")
    assert submit_response.status_code == 302
    assert submit_response.headers["Location"].endswith("/portal/pt")
    assert draft is None
    assert operational_count_after == operational_count_before


def test_portal_pt_with_direct_unit_orders_only_for_that_unit(app):
    # Pasangan tes di atas. Client kontrak yang memesan sendiri mendapat unit
    # "PT X — Langsung" (keputusan owner 2026-09-25): PT boleh memesan untuk
    # unit itu, tapi tetap tidak untuk lokasi mandornya.
    from app.models.master import DeliveryLocation
    from app.services.client_direct_order_service import activate_direct_ordering

    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CLIENT)
        username = user.username
        client_obj, _client_pic, _mandor, mandor_location = _create_scope_master_data(user)
        unit, _ = activate_direct_ordering(client_obj, user.branch_id)
        unit_location = DeliveryLocation(mandor_id=unit.id, location_name="Kantor PT Langsung", is_active=True)
        db.session.add(unit_location)
        _create_portal_mapping(user, principal_type=PRINCIPAL_CLIENT, client=client_obj, access_level="DRAFT_ORDER")
        db.session.commit()
        user_id, unit_id = user.id, unit.id
        unit_location_id, mandor_location_id = unit_location.id, mandor_location.id

    client = app.test_client()
    _login_with_password(client, username)
    page_response = client.get("/portal/pt/order", follow_redirects=False)
    rejected = client.post("/portal/orders/draft", data={
        "order_date": "2099-04-01", "meal_type": "LUNCH", "portion_qty": "25",
        "delivery_location_id": str(mandor_location_id), "idempotency_key": f"pt-mandor-{uuid4().hex}",
    }, follow_redirects=False)
    accepted = client.post("/portal/orders/draft", data={
        "order_date": "2099-04-01", "meal_type": "LUNCH", "portion_qty": "25",
        "delivery_location_id": str(unit_location_id), "idempotency_key": f"pt-unit-{uuid4().hex}",
    }, follow_redirects=False)

    with app.app_context():
        drafts = PortalOrderDraft.query.filter_by(user_id=user_id).all()

    assert page_response.status_code == 302
    assert page_response.headers["Location"].endswith("/portal/orders/draft")
    assert rejected.status_code == 400
    assert "unit order langsungnya" in rejected.get_data(as_text=True)
    assert accepted.status_code == 302
    assert [(draft.mandor_id, draft.delivery_location_id) for draft in drafts] == [(unit_id, unit_location_id)]


def test_portal_order_tracking_reads_converted_order_production_and_delivery(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        portal_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        other_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        admin = _create_user_for_branch("ADMIN", portal_user.branch)
        portal_username = portal_user.username
        other_username = other_user.username
        admin_username = admin.username
        admin_id = admin.id
        _client_obj, _client_pic, mandor, location = _create_scope_master_data(portal_user)
        _create_portal_mapping(
            portal_user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        location_id = location.id
        db.session.commit()

    client = app.test_client()
    _login_with_password(client, portal_username)
    client.post(
        "/portal/orders/draft",
        data={
            "order_date": "2099-05-01",
            "meal_type": "LUNCH",
            "portion_qty": "14",
            "delivery_location_id": str(location_id),
            "notes": "TRACKING DELIVERY VISIBLE",
            "idempotency_key": f"tracking-{uuid4().hex}",
        },
    )

    with app.app_context():
        draft = (
            PortalOrderDraft.query.filter(PortalOrderDraft.user.has(username=portal_username))
            .order_by(PortalOrderDraft.id.desc())
            .first()
        )
        draft_id = draft.id

    client = app.test_client()
    _login_with_password(client, admin_username)
    confirm_response = client.post(
        f"/portal/admin/order-drafts/{draft_id}/confirm",
        data={"review_note": "Admin confirmed for tracking test."},
    )

    with app.app_context():
        draft = PortalOrderDraft.query.get(draft_id)
        daily_order = DailyOrder.query.get(draft.converted_daily_order_id)
        detail = daily_order.details[0]
        production = Production(
            branch_id=daily_order.branch_id,
            production_date=daily_order.order_date,
            production_type="LUNCH",
            status="COMPLETED",
            notes=f"Production for {daily_order.order_number}",
            created_by=admin_id,
        )
        driver = Driver(
            branch_id=daily_order.branch_id,
            name="Portal Tracking Driver",
            phone="0800000055",
            is_active=True,
        )
        db.session.add(production)
        db.session.add(driver)
        db.session.flush()
        delivery = Delivery(
            delivery_number=f"T-PORTAL-DLV-{uuid4().hex[:8]}",
            branch_id=daily_order.branch_id,
            delivery_date=daily_order.order_date,
            driver_id=driver.id,
            status="DELIVERED",
            notes="Delivery for portal tracking",
            created_by=admin_id,
        )
        db.session.add(delivery)
        db.session.flush()
        db.session.add(
            DeliveryDetail(
                delivery_id=delivery.id,
                daily_order_detail_id=detail.id,
                mandor_id=detail.mandor_id,
                delivery_location_id=detail.delivery_location_id,
                planned_qty=14,
                delivered_qty=14,
                shortage_qty=0,
                sla_status="ON_TIME",
            )
        )
        daily_order_number = daily_order.order_number
        delivery_number = delivery.delivery_number
        db.session.commit()

    client = app.test_client()
    _login_with_password(client, portal_username)
    response = client.get("/portal/orders/status")
    html = response.get_data(as_text=True)

    other_client = app.test_client()
    _login_with_password(other_client, other_username)
    other_response = other_client.get("/portal/orders/status")
    other_html = other_response.get_data(as_text=True)

    assert confirm_response.status_code == 302
    assert response.status_code == 200
    assert "DELIVERED" in html
    assert "Production: COMPLETED" in html
    assert f"Delivery: DELIVERED" in html
    assert delivery_number in html
    assert "Delivered 14" in html
    assert daily_order_number in html
    assert "Rp " not in html
    assert other_response.status_code == 200
    assert delivery_number not in other_html
    assert daily_order_number not in other_html


def test_portal_order_status_shows_only_current_user_drafts(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        first_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        second_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        first_username = first_user.username
        first_client, _first_pic, first_mandor, first_location = _create_scope_master_data(first_user)
        second_client, _second_pic, second_mandor, second_location = _create_scope_master_data(second_user)
        first_location.location_name = "VISIBLE STATUS LOCATION"
        second_location.location_name = "HIDDEN STATUS LOCATION"
        near_calendar_date = date.today() + timedelta(days=7)
        first_draft = PortalOrderDraft(
            user_id=first_user.id,
            branch_id=first_user.branch_id,
            client_id=first_client.id,
            mandor_id=first_mandor.id,
            delivery_location_id=first_location.id,
            order_date=date(2099, 2, 1),
            meal_type="LUNCH",
            portion_qty=5,
            notes="VISIBLE STATUS NOTE",
            status="PENDING_ADMIN_CONFIRMATION",
            idempotency_key=f"status-a-{uuid4().hex}",
        )
        second_draft = PortalOrderDraft(
            user_id=second_user.id,
            branch_id=second_user.branch_id,
            client_id=second_client.id,
            mandor_id=second_mandor.id,
            delivery_location_id=second_location.id,
            order_date=date(2099, 2, 1),
            meal_type="LUNCH",
            portion_qty=7,
            notes="HIDDEN STATUS NOTE",
            status="PENDING_ADMIN_CONFIRMATION",
            idempotency_key=f"status-b-{uuid4().hex}",
        )
        db.session.add(first_draft)
        db.session.add(second_draft)
        db.session.commit()

    client = app.test_client()
    _login_with_password(client, first_username)
    response = client.get("/portal/orders/status")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "VISIBLE STATUS NOTE" not in html
    assert "HIDDEN STATUS NOTE" not in html
    assert "VISIBLE STATUS LOCATION" in html
    assert "HIDDEN STATUS LOCATION" not in html
    assert "Rp " not in html


def test_admin_confirmation_bridge_rejects_other_branch_admin(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        portal_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        other_admin = _create_test_user("ADMIN")
        portal_username = portal_user.username
        other_admin_username = other_admin.username
        _client_obj, _client_pic, mandor, location = _create_scope_master_data(portal_user)
        location_id = location.id
        _create_portal_mapping(
            portal_user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        db.session.commit()

    client = app.test_client()
    _login_with_password(client, portal_username)
    client.post(
        "/portal/orders/draft",
        data={
            "order_date": "2099-01-03",
            "meal_type": "LUNCH",
            "portion_qty": "8",
            "delivery_location_id": str(location_id),
            "idempotency_key": f"other-branch-{uuid4().hex}",
        },
    )

    with app.app_context():
        draft = (
            PortalOrderDraft.query.filter(PortalOrderDraft.user.has(username=portal_username))
            .order_by(PortalOrderDraft.id.desc())
            .first()
        )
        draft_id = draft.id

    client = app.test_client()
    _login_with_password(client, other_admin_username)
    list_response = client.get("/portal/admin/order-drafts")
    confirm_response = client.post(f"/portal/admin/order-drafts/{draft_id}/confirm")

    with app.app_context():
        draft = PortalOrderDraft.query.get(draft_id)
        db.session.refresh(draft)

        assert list_response.status_code == 200
        assert "2099" not in list_response.get_data(as_text=True)
        assert confirm_response.status_code == 302
        assert draft.status == "PENDING_ADMIN_CONFIRMATION"
        assert draft.converted_daily_order_id is None


def test_admin_confirmation_bridge_reject_action_does_not_create_daily_order(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        portal_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        admin = _create_user_for_branch("ADMIN", portal_user.branch)
        portal_username = portal_user.username
        admin_username = admin.username
        _client_obj, _client_pic, mandor, location = _create_scope_master_data(portal_user)
        location_id = location.id
        _create_portal_mapping(
            portal_user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        db.session.commit()
        operational_count_before = DailyOrder.query.count()

    client = app.test_client()
    _login_with_password(client, portal_username)
    client.post(
        "/portal/orders/draft",
        data={
            "order_date": "2099-01-04",
            "meal_type": "LUNCH",
            "portion_qty": "6",
            "delivery_location_id": str(location_id),
            "idempotency_key": f"reject-{uuid4().hex}",
        },
    )

    with app.app_context():
        draft = (
            PortalOrderDraft.query.filter(PortalOrderDraft.user.has(username=portal_username))
            .order_by(PortalOrderDraft.id.desc())
            .first()
        )
        draft_id = draft.id

    client = app.test_client()
    _login_with_password(client, admin_username)
    reject_response = client.post(f"/portal/admin/order-drafts/{draft_id}/reject")

    with app.app_context():
        draft = PortalOrderDraft.query.get(draft_id)
        db.session.refresh(draft)

        assert reject_response.status_code == 302
        assert draft.status == "REJECTED"
        assert draft.converted_daily_order_id is None
        assert DailyOrder.query.count() == operational_count_before


def test_portal_customer_prepayment_guard_blocks_draft_order(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CUSTOMER)
        username = user.username
        user_id = user.id
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        _login(client, user)
    get_response = client.get("/portal/orders/draft")
    post_response = client.post(
        "/portal/orders/draft",
        data={
            "order_date": "2099-03-01",
            "meal_type": "LUNCH",
            "portion_qty": "4",
            "delivery_location_id": "1",
            "idempotency_key": f"customer-{uuid4().hex}",
        },
    )
    status_response = client.get("/portal/status", follow_redirects=False)
    dashboard_response = client.get("/portal/my-dashboard", follow_redirects=True)

    with app.app_context():
        draft_count = PortalOrderDraft.query.filter(PortalOrderDraft.user_id == user_id).count()

    get_html = get_response.get_data(as_text=True)
    dashboard_html = dashboard_response.get_data(as_text=True)

    assert get_response.status_code == 200
    assert post_response.status_code == 400
    assert status_response.status_code == 302
    assert dashboard_response.status_code == 200
    assert "Pelanggan umum wajib memiliki pembayaran terverifikasi" in get_html
    assert "Prepayment tetap wajib" in dashboard_html
    assert draft_count == 0


def test_portal_mapping_service_has_no_session_commit_or_rollback():
    source = open("app/services/portal_mapping_service.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source


def test_portal_external_mandor_role_can_render_role_dashboard_pages(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        username = user.username
        _client_obj, _client_pic, mandor, _location = _create_scope_master_data(user)
        _create_portal_mapping(
            user,
            principal_type=PRINCIPAL_MANDOR,
            mandor=mandor,
            access_level="DRAFT_ORDER",
        )
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        _login(client, user)

    page_expectations = {
        "/portal/my-dashboard": ["Dashboard Mandor", "PORTAL_SUBCLIENT_SCOPE", "portal-mobile-shell"],
        "/portal/invoices": ["Invoice Portal", "Belum ada invoice dalam scope portal"],
        "/portal/payments": ["Riwayat Pembayaran", "Belum ada pembayaran dalam scope portal"],
        "/portal/debts": ["Hutang Pekerja", "Belum ada hutang pekerja dalam scope portal"],
        "/portal/closing": ["Closing Portal", "Status closing"],
    }

    for path, texts in page_expectations.items():
        response = client.get(path, follow_redirects=(path == "/portal/my-dashboard"))
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Halaman tidak ditemukan" not in html
        assert "BuildError" not in html
        assert "UndefinedError" not in html
        for text in texts:
            assert text in html


def test_portal_roles_redirect_to_their_dedicated_dashboard_pages(app):
    app.config["PORTAL_ENABLED"] = True

    role_cases = [
        (ROLE_PORTAL_CUSTOMER, None, None, "/portal/customer", 'data-endpoint="portal.customer_dashboard"'),
        (ROLE_PORTAL_SUBCLIENT, PRINCIPAL_MANDOR, "mandor", "/portal/mandor", 'data-endpoint="portal.mandor_dashboard"'),
        # Client and PT are one role now and land on the PT home; the
        # narrower client_dashboard page still renders when visited.
        (ROLE_PORTAL_CLIENT, PRINCIPAL_CLIENT, "client", "/portal/pt", 'data-endpoint="portal.pt_dashboard"'),
        (ROLE_PORTAL_DELEGATE, PRINCIPAL_DELEGATE, "location", "/portal/delegate", 'data-endpoint="portal.delegate_dashboard"'),
    ]

    for role, principal_type, principal_key, expected_path, expected_endpoint in role_cases:
        with app.app_context():
            user = _create_test_user(role)
            username = user.username
            client_obj, _client_pic, mandor, location = _create_scope_master_data(user)
            if principal_type:
                kwargs = {"principal_type": principal_type}
                if principal_key == "client":
                    kwargs["client"] = client_obj
                elif principal_key == "mandor":
                    kwargs["mandor"] = mandor
                elif principal_key == "location":
                    kwargs["location"] = location
                _create_portal_mapping(user, **kwargs)
            db.session.commit()

        client = app.test_client()
        with app.app_context():
            user = User.query.filter_by(username=username).first()
            _login(client, user)

        redirect_response = client.get("/portal/my-dashboard", follow_redirects=False)
        page_response = client.get(expected_path)
        html = page_response.get_data(as_text=True)

        assert redirect_response.status_code == 302
        assert redirect_response.headers["Location"].endswith(expected_path)
        assert page_response.status_code == 200
        assert expected_endpoint in html
        assert "portal-mobile-shell" in html
        assert "portal-web-nav" in html
        assert 'action="/auth/logout"' in html
        assert "portal-web-logout-button" in html
        assert "portal-mobile-bottom-nav" not in html
        assert "app-sidebar" not in html


def test_portal_login_routes_each_external_role_to_its_own_page(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    role_cases = [
        (ROLE_PORTAL_CUSTOMER, "/portal/customer", 'data-endpoint="portal.customer_dashboard"'),
        (ROLE_PORTAL_SUBCLIENT, "/portal/mandor", 'data-endpoint="portal.mandor_dashboard"'),
        # Client and PT are one role now and land on the PT home; the
        # narrower client_dashboard page still renders when visited.
        (ROLE_PORTAL_CLIENT, "/portal/pt", 'data-endpoint="portal.pt_dashboard"'),
        (ROLE_PORTAL_DELEGATE, "/portal/delegate", 'data-endpoint="portal.delegate_dashboard"'),
    ]

    for role, expected_path, expected_endpoint in role_cases:
        with app.app_context():
            user = _create_test_user(role)
            username = user.username
            db.session.commit()

        client = app.test_client()
        response = _login_with_password(client, username)

        assert response.status_code == 302
        assert response.headers["Location"].endswith(expected_path)

        page_response = client.get(expected_path)
        page_html = page_response.get_data(as_text=True)
        assert page_response.status_code == 200
        assert expected_endpoint in page_html
        assert 'action="/auth/logout"' in page_html
        assert "Keluar" in page_html
        assert "app-sidebar" not in page_html


def test_internal_login_stays_on_internal_dashboard_flow(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user("OWNER")
        username = user.username
        db.session.commit()

    response = _login_with_password(app.test_client(), username)

    assert response.status_code == 302
    assert not response.headers["Location"].endswith("/portal/customer")
    assert not response.headers["Location"].endswith("/portal/mandor")
    assert not response.headers["Location"].endswith("/portal/pt")


def test_portal_internal_configuration_pages_are_not_external_portal_pages(app):
    app.config["PORTAL_ENABLED"] = True

    internal_paths = [
        "/portal/dashboard",
        "/portal/customers",
        "/portal/mandors",
        "/portal/locations",
        "/portal/status",
        "/portal/ownership",
        "/portal/admin/order-drafts",
    ]

    with app.app_context():
        admin = _create_test_user("ADMIN")
        external = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        _client_obj, _client_pic, mandor, _location = _create_scope_master_data(external)
        _create_portal_mapping(external, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
        db.session.commit()
        admin_username = admin.username
        external_username = external.username

    admin_client = app.test_client()
    external_client = app.test_client()
    with app.app_context():
        _login(admin_client, User.query.filter_by(username=admin_username).first())
        _login(external_client, User.query.filter_by(username=external_username).first())

    for path in internal_paths:
        admin_response = admin_client.get(path)
        external_response = external_client.get(path, follow_redirects=False)

        assert admin_response.status_code == 200, path
        assert external_response.status_code == 302, path
        assert external_response.headers["Location"] == "/"


def test_portal_role_dashboard_pages_reject_other_portal_roles(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        mandor_user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        client_obj, _client_pic, mandor, _location = _create_scope_master_data(mandor_user)
        _create_portal_mapping(mandor_user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
        pt_user = _create_test_user(ROLE_PORTAL_CLIENT)
        _create_portal_mapping(pt_user, principal_type=PRINCIPAL_CLIENT, client=client_obj)
        db.session.commit()
        mandor_username = mandor_user.username
        pt_username = pt_user.username

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=mandor_username).first())

    wrong_role_response = client.get("/portal/pt", follow_redirects=False)
    own_role_response = client.get("/portal/mandor")

    assert wrong_role_response.status_code == 302
    assert wrong_role_response.headers["Location"] == "/"
    assert own_role_response.status_code == 200
    assert "Dashboard Mandor" in own_role_response.get_data(as_text=True)

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=pt_username).first())

    assert client.get("/portal/pt").status_code == 200


def test_portal_customer_feature_foundation_pages_render(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CUSTOMER)
        username = user.username
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=username).first())

    pages = {
        "/portal/customer/order": "Pesan Catering",
        "/portal/customer/orders": "Riwayat Pesanan",
        "/portal/customer/tracking": "Lacak Pesanan",
        "/portal/customer/payments": "Pembayaran",
        "/portal/customer/complaints": "Komplain",
        "/portal/customer/returns": "Retur",
        "/portal/notifications": "Notifikasi",
        "/portal/documents": "Dokumen",
        "/portal/approvals": "Approval",
        "/portal/calendar": "Kalender Operasional",
    }

    for path, title in pages.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200, path
        assert title in html
        assert "portal-mobile-shell" in html
        assert "app-sidebar" not in html
        assert "BuildError" not in html
        assert "UndefinedError" not in html

    invoices_response = client.get("/portal/customer/invoices", follow_redirects=False)
    assert invoices_response.status_code == 302
    assert invoices_response.headers["Location"].endswith("/portal/customer/payments")


def test_portal_mandor_feature_foundation_pages_render(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        username = user.username
        _client_obj, _client_pic, mandor, _location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=username).first())

    pages = {
        "/portal/mandor/order": "Pesan Catering",
        "/portal/mandor/workers": "Data Pekerja",
        "/portal/mandor/catering-debts": "Hutang Catering",
        "/portal/mandor/canteen-debts": "Hutang Warung",
        "/portal/mandor/installments": "Cicilan",
        "/portal/mandor/invoices": "Invoice",
        "/portal/mandor/payments": "Riwayat Pembayaran",
        "/portal/mandor/subscriptions": "Pesanan Berulang",
        "/portal/notifications": "Notifikasi",
        "/portal/documents": "Dokumen",
        "/portal/approvals": "Approval",
        "/portal/calendar": "Kalender Operasional",
    }

    for path, title in pages.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200, path
        assert title in html
        assert "portal-mobile-shell" in html
        assert "app-sidebar" not in html
        assert "BuildError" not in html
        assert "UndefinedError" not in html


def test_portal_pt_feature_foundation_pages_render(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CLIENT)
        username = user.username
        client_obj, _client_pic, _mandor, _location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_CLIENT, client=client_obj)
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=username).first())

    pages = {
        "/portal/pt/mandors": "Seluruh Mandor",
        "/portal/pt/invoices": "Seluruh Invoice",
        "/portal/pt/receivables": "Seluruh Piutang",
        "/portal/pt/contracts": "Seluruh Kontrak",
        "/portal/pt/subscriptions": "Pesanan Berulang",
        "/portal/notifications": "Notifikasi",
        "/portal/documents": "Dokumen",
        "/portal/approvals": "Approval",
        "/portal/calendar": "Kalender Operasional",
    }

    for path, title in pages.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200, path
        assert title in html
        assert "portal-mobile-shell" in html
        assert "app-sidebar" not in html
        assert "BuildError" not in html
        assert "UndefinedError" not in html

    pt_order_response = client.get("/portal/pt/order", follow_redirects=False)
    assert pt_order_response.status_code == 302
    assert pt_order_response.headers["Location"].endswith("/portal/pt")


def test_portal_customer_complaint_submits_to_existing_complaint_table(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CUSTOMER)
        client_obj, _client_pic, mandor, _location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
        username = user.username
        user_id = user.id
        client_id = client_obj.id
        mandor_id = mandor.id
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=username).first())

    response = client.post(
        "/portal/customer/complaints",
        data={
            "category": "LATE_DELIVERY",
            "title": "Pengiriman terlambat",
            "description": "Pesanan datang lewat dari jam makan.",
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    with app.app_context():
        complaint = CustomerComplaint.query.filter_by(submitted_by=user_id).one()

    assert response.status_code == 200
    assert "Komplain" in html
    assert "customer_complaints ERP existing" in html
    assert "Pengiriman terlambat" in html
    assert complaint.client_id == client_id
    assert complaint.mandor_id == mandor_id
    assert complaint.status == "OPEN"


def test_portal_pt_contract_page_reads_existing_customer_contracts(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CLIENT)
        client_obj, client_pic, _mandor, _location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_CLIENT, client=client_obj)
        contract = CustomerContract(
            branch_id=user.branch_id,
            client_id=client_obj.id,
            client_pic_id=client_pic.id,
            contract_number=f"QA-PORTAL-CONTRACT-{uuid4().hex[:8]}",
            title="Kontrak Catering PT",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            payment_terms="NET 14",
            credit_limit=1000000,
            status="ACTIVE",
            version_no=1,
            created_by=user.id,
        )
        db.session.add(contract)
        username = user.username
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=username).first())

    response = client.get("/portal/pt/contracts")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Seluruh Kontrak" in html
    assert "customer_contracts ERP existing" in html
    assert "Kontrak Catering PT" in html
    assert "NET 14" in html
    assert "Rp 1.000.000" in html


def test_portal_integrated_foundation_pages_read_existing_tables(app, tmp_path):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)
    (tmp_path / "portal-proof.pdf").write_bytes(b"%PDF-1.4\nportal proof\n%%EOF")

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_SUBCLIENT)
        customer = _create_user_for_branch(ROLE_PORTAL_CUSTOMER, user.branch)
        client_obj, _client_pic, mandor, location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
        notification = Notification(
            branch_id=user.branch_id,
            notification_type="PORTAL_TEST",
            title="Jadwal kirim berubah",
            message="Pengiriman lunch maju 15 menit.",
            status="UNREAD",
            target_user_id=user.id,
            priority="WARNING",
            reference_type="PORTAL",
            reference_id=1,
        )
        attachment = DigitalAttachment(
            branch_id=user.branch_id,
            module="PORTAL_PAYMENT",
            reference_type="INVOICE",
            reference_id=999001,
            attachment_type="PAYMENT_PROOF_PENDING",
            original_filename="portal-proof.pdf",
            stored_filename=f"portal-proof-{uuid4().hex}.pdf",
            file_path="portal-proof.pdf",
            mime_type="application/pdf",
            file_size=120,
            sha256_hash="a" * 64,
            uploaded_by=user.id,
            is_deleted=False,
        )
        approval = ApprovalRequest(
            branch_id=user.branch_id,
            action_key="PORTAL_ORDER_APPROVAL",
            reference_type="PORTAL_ORDER_DRAFT",
            reference_id=123,
            status="SUBMITTED",
            requested_by=user.id,
            requested_reason="Butuh approval order portal.",
        )
        complaint = CustomerComplaint(
            branch_id=user.branch_id,
            complaint_number=f"QA-PORTAL-RETURN-{uuid4().hex[:8]}",
            category="WRONG_MENU",
            status="OPEN",
            title="Menu salah kirim",
            description="Menu tidak sesuai permintaan.",
            client_id=client_obj.id,
            mandor_id=mandor.id,
            submitted_by=customer.id,
            submitted_at=datetime(2099, 6, 1, 10, 0),
        )
        near_calendar_date = date.today() + timedelta(days=7)
        first_draft = PortalOrderDraft(
            user_id=user.id,
            branch_id=user.branch_id,
            client_id=client_obj.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            order_date=near_calendar_date,
            meal_type="LUNCH",
            portion_qty=20,
            notes="subscription pattern one",
            status="PENDING_ADMIN_CONFIRMATION",
            idempotency_key=f"sub-a-{uuid4().hex}",
        )
        second_draft = PortalOrderDraft(
            user_id=user.id,
            branch_id=user.branch_id,
            client_id=client_obj.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            order_date=near_calendar_date + timedelta(days=1),
            meal_type="LUNCH",
            portion_qty=20,
            notes="subscription pattern two",
            status="PENDING_ADMIN_CONFIRMATION",
            idempotency_key=f"sub-b-{uuid4().hex}",
        )
        db.session.add_all([notification, attachment, approval, complaint, first_draft, second_draft])
        db.session.flush()
        username = user.username
        customer_username = customer.username
        notification_id = notification.id
        complaint_id = complaint.id
        attachment_id = attachment.id
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        _login(client, User.query.filter_by(username=username).first())

    checks = {
        "/portal/notifications": ["Jadwal kirim berubah", "notifications ERP existing"],
        "/portal/documents": ["portal-proof.pdf", "digital_attachments ERP existing"],
        "/portal/approvals": ["PORTAL_ORDER_APPROVAL", "approval_requests ERP existing"],
        "/portal/mandor/subscriptions": ["2x draft", "portal_order_drafts ERP existing"],
        "/portal/calendar": ["LUNCH 20 porsi", "Draft, invoice, kontrak, delivery ERP existing"],
    }

    for path, expected_texts in checks.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200, path
        assert "BuildError" not in html
        assert "UndefinedError" not in html
        assert "app-sidebar" not in html
        for expected_text in expected_texts:
            assert expected_text in html

    view_response = client.get(f"/portal/documents/{attachment_id}/view")
    download_response = client.get(f"/portal/documents/{attachment_id}/download")
    read_response = client.post(f"/portal/notifications/{notification_id}/read", follow_redirects=True)
    dismiss_response = client.post(f"/portal/notifications/{notification_id}/dismiss", follow_redirects=True)

    with app.app_context():
        updated_notification = Notification.query.get(notification_id)

    assert view_response.status_code == 200
    assert view_response.headers["Cache-Control"] == "no-store"
    assert download_response.status_code == 200
    assert "attachment" in download_response.headers["Content-Disposition"]
    assert read_response.status_code == 200
    assert dismiss_response.status_code == 200
    assert updated_notification.status == "DISMISSED"

    customer_client = app.test_client()
    with app.app_context():
        _login(customer_client, User.query.filter_by(username=customer_username).first())
    returns_response = customer_client.get("/portal/customer/returns")
    returns_html = returns_response.get_data(as_text=True)
    evidence_response = customer_client.post(
        f"/portal/customer/complaints/{complaint_id}/evidence",
        data={
            "notes": "Foto menu salah",
            "evidence_file": (BytesIO(b"%PDF-1.4\ncomplaint evidence\n%%EOF"), "complaint-evidence.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    evidence_html = evidence_response.get_data(as_text=True)

    assert returns_response.status_code == 200
    assert "Menu salah kirim" in returns_html
    assert "customer_complaints ERP existing" in returns_html
    assert evidence_response.status_code == 200
    assert "complaint-evidence.pdf" in evidence_html or "berhasil diupload" in evidence_html
    with app.app_context():
        evidence = DigitalAttachment.query.filter_by(
            module="CUSTOMER_COMPLAINT",
            reference_type="CUSTOMER_COMPLAINT",
            reference_id=complaint_id,
            uploaded_by=User.query.filter_by(username=customer_username).first().id,
        ).first()
    assert evidence is not None


def test_portal_sidebar_exposes_role_pages_for_external_portal_user(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CLIENT)
        username = user.username
        client_obj, _client_pic, _mandor, _location = _create_scope_master_data(user)
        _create_portal_mapping(user, principal_type=PRINCIPAL_CLIENT, client=client_obj)
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        _login(client, user)
    response = client.get("/portal/my-dashboard", follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/portal/my-dashboard"' in html
    assert "portal-mobile-shell" in html
    assert "app-sidebar" not in html
    assert 'href="/portal/orders/draft"' not in html
    assert 'href="/portal/orders/status"' not in html
    assert 'href="/customer-success' not in html


def test_portal_customer_general_pages_render_with_financial_guards(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user = _create_test_user(ROLE_PORTAL_CUSTOMER)
        username = user.username
        db.session.commit()

    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        _login(client, user)

    guarded_pages = {
        "/portal/my-dashboard": [
            'data-endpoint="portal.customer_dashboard"',
            "portal-mobile-shell",
        ],
        "/portal/invoices": [
            "Pembayaran Awal",
            "Pelanggan umum tidak memiliki fasilitas kredit.",
        ],
        "/portal/payments": [
            "Pembayaran Awal",
            "Customer tidak memakai kredit",
        ],
        "/portal/debts": [
            'data-endpoint="portal.customer_dashboard"',
            "Pesan catering, bayar, lalu kami proses.",
        ],
        "/portal/closing": [
            'data-endpoint="portal.customer_dashboard"',
            "Pelanggan umum tidak memakai kredit.",
        ],
    }

    for path, texts in guarded_pages.items():
        response = client.get(path, follow_redirects=True)
        html = response.get_data(as_text=True)

        assert response.status_code == 200, path
        assert "Halaman tidak ditemukan" not in html
        assert "BuildError" not in html
        assert "UndefinedError" not in html
        for text in texts:
            assert text in html
