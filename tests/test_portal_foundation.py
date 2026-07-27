from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Mandor, User
from app.models.system import PortalUserMapping
from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_location_directory,
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
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
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


def _create_portal_mapping(user, *, principal_type, mandor=None, client=None, client_pic=None, location=None):
    mapping = PortalUserMapping(
        user_id=user.id,
        principal_type=principal_type,
        client_id=client.id if client else None,
        mandor_id=mandor.id if mandor else None,
        client_pic_id=client_pic.id if client_pic else None,
        delivery_location_id=location.id if location else None,
        access_level="READ_ONLY",
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
                assert "OWNER/ADMIN melihat preview internal. User eksternal memakai mapping portal eksplisit." in html
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
            assert 'href="/portal/locations"' in html
            assert 'href="/portal/status"' in html
            assert 'href="/portal/ownership"' in html
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
                    "role": ROLE_PORTAL_MANDOR,
                    "branch_id": str(owner.branch_id),
                    "is_active": "on",
                }
            )

            assert error is None
            assert payload["role"] == ROLE_PORTAL_MANDOR
            assert payload["branch_id"] == owner.branch_id
        finally:
            transaction.rollback()


def test_portal_external_mandor_scope_uses_mapping_and_hides_other_branch(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user(ROLE_PORTAL_MANDOR)
            client_obj, client_pic, mandor, location = _create_scope_master_data(user)
            sibling_mandor, sibling_location = _create_extra_mandor_location(user, client_obj, "BBB Same Client")
            _create_portal_mapping(user, principal_type=PRINCIPAL_MANDOR, mandor=mandor)
            _create_other_branch_scope_data()

            scope = build_portal_external_scope(user)
            access_scope = build_portal_access_scope(user)

            assert scope.allowed is True
            assert scope.scope_mode == "PORTAL_MANDOR_SCOPE"
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
                dashboard_response = client.get("/portal/dashboard")
                customers_response = client.get("/portal/customers")
                mandors_response = client.get("/portal/mandors")
                locations_response = client.get("/portal/locations")
                ownership_response = client.get("/portal/ownership")

            assert index_response.status_code == 302
            assert index_response.headers["Location"].endswith("/portal/dashboard")

            dashboard_html = dashboard_response.get_data(as_text=True)
            customers_html = customers_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)
            locations_html = locations_response.get_data(as_text=True)

            assert dashboard_response.status_code == 200
            assert customers_response.status_code == 200
            assert mandors_response.status_code == 200
            assert locations_response.status_code == 200
            assert "PORTAL_MANDOR_SCOPE" in dashboard_html
            assert "AAA Test Portal Client" in dashboard_html
            assert "AAA Test Portal Mandor" in dashboard_html
            assert "BBB Same Client Mandor" not in dashboard_html
            assert "ZZZ Other Branch Client" not in dashboard_html
            assert "ZZZ Other Branch Mandor" not in dashboard_html
            assert "Ownership" not in dashboard_html
            assert "AAA Test Portal Client" in customers_html
            assert "ZZZ Other Branch Client" not in customers_html
            assert "AAA Test Portal Mandor" in mandors_html
            assert "BBB Same Client Mandor" not in mandors_html
            assert "ZZZ Other Branch Mandor" not in mandors_html
            assert "AAA Test Portal Location" in locations_html
            assert "BBB Same Client Location" not in locations_html
            assert "ZZZ Other Branch Location" not in locations_html
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

            assert scope.allowed is True
            assert scope.scope_mode == "PORTAL_CLIENT_SCOPE"
            assert scope.client_ids == {client_obj.id}
            assert {mandor.id, sibling_mandor.id}.issubset(scope.mandor_ids)
            assert {location.id, sibling_location.id}.issubset(scope.delivery_location_ids)

            with app.test_client() as client:
                _login(client, user)
                profile_response = client.get("/portal/profile")
                mandors_response = client.get("/portal/mandors")

            profile_html = profile_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)

            assert profile_response.status_code == 200
            assert mandors_response.status_code == 200
            assert "PORTAL_CLIENT_SCOPE" in profile_html
            assert "AAA Test Portal Mandor" in mandors_html
            assert "BBB Same Client Mandor" in mandors_html
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

            assert scope.allowed is True
            assert scope.scope_mode == "PORTAL_DELEGATE_SCOPE"
            assert scope.client_ids == {client_obj.id}
            assert scope.mandor_ids == {mandor.id}
            assert scope.delivery_location_ids == {location.id}
            assert sibling_location.id not in scope.delivery_location_ids
            assert directory["allowed"] is True
            assert len(directory["rows"]) == 1
            assert directory["rows"][0]["name"] == "AAA Test Portal Location"

            with app.test_client() as client:
                _login(client, user)
                profile_response = client.get("/portal/profile")
                mandors_response = client.get("/portal/mandors")
                locations_response = client.get("/portal/locations")

            profile_html = profile_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)
            locations_html = locations_response.get_data(as_text=True)

            assert profile_response.status_code == 200
            assert locations_response.status_code == 200
            assert "PORTAL_DELEGATE_SCOPE" in profile_html
            assert "AAA Test Portal Location" in profile_html
            assert "BBB Same Mandor Other Location" not in profile_html
            assert "AAA Test Portal Mandor" in mandors_html
            assert "CCC Same Client Other Mandor" not in mandors_html
            assert "AAA Test Portal Location" in locations_html
            assert "BBB Same Mandor Other Location" not in locations_html
            assert "CCC Same Client Other Location" not in locations_html
        finally:
            transaction.rollback()


def test_unmapped_portal_external_user_does_not_receive_master_data(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user(ROLE_PORTAL_MANDOR)
            _create_scope_master_data(user)

            access_scope = build_portal_access_scope(user)
            assert access_scope["allowed"] is False
            assert access_scope["scope_mode"] == "NO_PORTAL_SCOPE"
            assert access_scope["counts"]["clients"] == 0
            assert access_scope["counts"]["mandors"] == 0

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/dashboard")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert "AAA Test Portal Client" not in html
            assert "User belum memiliki mapping portal aktif" in html
        finally:
            transaction.rollback()


def test_portal_mapping_service_has_no_session_commit_or_rollback():
    source = open("app/services/portal_mapping_service.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source
