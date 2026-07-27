from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, User


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
                assert "Batch 1A tidak membuat atau mengubah order." in html
                assert "Tidak ada posting payment" in html
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
