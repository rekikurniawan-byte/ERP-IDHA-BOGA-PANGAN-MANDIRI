from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Mandor, User
from app.services.portal_access_service import build_portal_access_scope


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


def _login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


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
                assert "Portal Pelanggan" in html
                assert "Preview internal" in html
                assert "Scope read-only dari master client" in html
                assert "Role eksternal dan mapping portal masih ditunda sampai approval owner." in html
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
            assert "Portal Pelanggan" not in html
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
            assert 'href="/portal/customers"' in html
            assert 'href="/portal/mandors"' in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_hidden_for_non_preview_role_even_when_enabled(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("FINANCE")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal' not in html
            assert "Portal Pelanggan" not in html
        finally:
            transaction.rollback()


def test_portal_enabled_rejects_unauthorized_internal_role(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("FINANCE")
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

            customers_html = customers_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)

            assert customers_response.status_code == 200
            assert mandors_response.status_code == 200
            assert "Client/PT Read-only" in customers_html
            assert "Mandor Read-only" in mandors_html
            assert "AAA Test Portal Client" in customers_html
            assert "AAA Test Portal Mandor" in mandors_html
            assert "ZZZ Other Branch Client" not in customers_html
            assert "ZZZ Other Branch Mandor" not in mandors_html
            assert 'action="/portal' not in customers_html.lower()
            assert 'action="/portal' not in mandors_html.lower()
        finally:
            transaction.rollback()


def test_portal_access_service_has_no_session_commit_or_rollback():
    source = open("app/services/portal_access_service.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source
