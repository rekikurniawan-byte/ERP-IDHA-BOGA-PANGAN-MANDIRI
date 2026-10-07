"""Pengujian kewajiban email untuk akun portal, banner pengingat, dan reset password."""
import base64
import io
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import PasswordResetToken, PortalUserMapping
from app.services.password_reset_service import (
    create_password_reset_token,
    request_password_reset,
    send_password_reset_email,
)
from app.services.portal_customer_registration_service import (
    register_portal_customer,
    validate_customer_registration_form,
)
from app.services.user_management_service import (
    ROLE_ADMIN,
    ROLE_DAPUR,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_SUBCLIENT,
    create_user,
    reset_user_password,
    update_portal_user_email,
    update_user,
    validate_user_payload,
)

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _photo(name="foto.png"):
    return FileStorage(stream=io.BytesIO(TINY_PNG), filename=name, content_type="image/png")


def _login(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client


def _create_branch():
    uid = uuid4().hex[:6]
    branch = Branch(
        code=f"BR-{uid}",
        name=f"Cabang {uid}",
        is_active=True,
    )
    db.session.add(branch)
    db.session.flush()
    return branch


def _create_user(branch, role=ROLE_ADMIN, email=None, username=None, password="Password#123"):
    uid = uuid4().hex[:8]
    user = User(
        branch_id=branch.id,
        full_name=f"User {uid}",
        username=username or f"user_{uid}",
        email=email,
        role=role,
        is_active=True,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.flush()
    return user


def test_customer_registration_email_validation(app):
    with app.app_context():
        branch = _create_branch()
        base_form = {
            "full_name": "Pelanggan Uji",
            "phone": "081234567890",
            "address": "Jl. Merdeka No. 10",
            "branch_id": branch.id,
            "password": "Password#123",
            "password_confirmation": "Password#123",
            "latitude": "-2.9850000",
            "longitude": "105.7280000",
        }

        # 1. Tanpa email ditolak
        form_no_email = {**base_form, "username": f"u_{uuid4().hex[:8]}"}
        with pytest.raises(ValueError, match="Email wajib diisi."):
            validate_customer_registration_form(form_no_email)

        form_empty_email = {**base_form, "username": f"u_{uuid4().hex[:8]}", "email": "   "}
        with pytest.raises(ValueError, match="Email wajib diisi."):
            validate_customer_registration_form(form_empty_email)

        # 2. Format email salah ditolak
        for bad_email in ("bukan-email", "user@domain", "@nodomain.com", "spasi @domain.com"):
            form_bad = {**base_form, "username": f"u_{uuid4().hex[:8]}", "email": bad_email}
            with pytest.raises(ValueError, match="Format email tidak valid."):
                validate_customer_registration_form(form_bad)

        # 3. Email dipakai akun lain (case-insensitive) ditolak
        existing_email = f"ada_{uuid4().hex[:6]}@example.com"
        _create_user(branch, email=existing_email)

        form_duplicate = {**base_form, "username": f"u_{uuid4().hex[:8]}", "email": existing_email.upper()}
        with pytest.raises(ValueError, match="Email ini sudah dipakai akun lain."):
            validate_customer_registration_form(form_duplicate)

        # 4. Registrasi valid menyimpan email lowercase
        new_email_raw = f"  Pelanggan.{uuid4().hex[:6]}@EXAMPLE.com  "
        valid_username = f"u_{uuid4().hex[:8]}"
        form_valid = {**base_form, "username": valid_username, "email": new_email_raw}

        with patch.object(db.session, "commit"):
            user = register_portal_customer(form_valid, files=[_photo()])
            assert user.email == new_email_raw.strip().lower()


def test_admin_create_user_email_rules(app):
    with app.app_context():
        branch = _create_branch()

        client = Client(name="PT Kontrak Test", customer_path="KONTRAK", is_active=True)
        mandor = Mandor(branch=branch, client=client, name="Mandor Test", is_active=True)
        db.session.add_all([client, mandor])
        db.session.flush()

        # 1. Admin buat akun portal tanpa email -> DITOLAK
        portal_roles_and_links = [
            (ROLE_PORTAL_CLIENT, {"portal_client_id": client.id}),
            (ROLE_PORTAL_SUBCLIENT, {"portal_mandor_id": mandor.id}),
        ]
        for role, link in portal_roles_and_links:
            payload, err = validate_user_payload({
                "full_name": f"User {role}",
                "username": f"u_{uuid4().hex[:6]}",
                "role": role,
                "branch_id": branch.id,
                **link,
            })
            assert payload is None
            assert err == "Email wajib diisi untuk akun portal."

        # Akun PORTAL_CUSTOMER di create_user ditolak karena harus daftar sendiri,
        # tetapi jika divalidasi dengan role portal, email tetap wajib
        payload_cust, err_cust = validate_user_payload({
            "full_name": "Cust",
            "username": f"c_{uuid4().hex[:6]}",
            "role": ROLE_PORTAL_CUSTOMER,
            "branch_id": branch.id,
        })
        assert payload_cust is None
        assert "Email wajib diisi" in err_cust or "mendaftar sendiri" in err_cust

        # 2. Akun staf internal tanpa email -> TETAP BOLEH
        for staff_role in (ROLE_ADMIN, ROLE_DAPUR, ROLE_PENGANTAR):
            payload, err = validate_user_payload({
                "full_name": f"Staf {staff_role}",
                "username": f"staf_{uuid4().hex[:6]}",
                "role": staff_role,
                "branch_id": branch.id,
            })
            assert err is None
            assert payload["email"] is None

        # 3. Akun staf internal dengan email format salah -> DITOLAK
        payload, err = validate_user_payload({
            "full_name": "Staf Error",
            "username": f"staf_{uuid4().hex[:6]}",
            "role": ROLE_ADMIN,
            "branch_id": branch.id,
            "email": "invalid-email-format",
        })
        assert payload is None
        assert err == "Format email tidak valid."

        # 4. Akun portal dengan email valid dibuat dengan email lowercase
        existing_email = f"pt_{uuid4().hex[:6]}@example.com"
        with patch.object(db.session, "commit"):
            created_pt, err_create = create_user({
                "full_name": "PT Maju Portal",
                "username": f"pt_{uuid4().hex[:6]}",
                "role": ROLE_PORTAL_CLIENT,
                "branch_id": branch.id,
                "portal_client_id": client.id,
                "email": f"  {existing_email.upper()}  ",
                "password": "Password#123",
                "password_confirmation": "Password#123",
            })
            assert err_create is None
            assert created_pt.email == existing_email.lower()

        # 5. Admin buat user baru dengan email yang sudah dipakai -> DITOLAK
        payload_dup, err_dup = validate_user_payload({
            "full_name": "Staf Lain",
            "username": f"other_{uuid4().hex[:6]}",
            "role": ROLE_ADMIN,
            "branch_id": branch.id,
            "email": existing_email.upper(),
        })
        assert payload_dup is None
        assert err_dup == "Email ini sudah dipakai akun lain."


def test_portal_user_update_profile_email(app):
    with app.app_context():
        branch = _create_branch()
        user = _create_user(
            branch,
            role=ROLE_PORTAL_CUSTOMER,
            email="cust.old@example.com",
            password="CorrectPassword#123",
        )
        other_user = _create_user(
            branch,
            role=ROLE_PORTAL_SUBCLIENT,
            email="other.mandor@example.com",
            password="OtherPassword#123",
        )

        # 1. Konfirmasi password salah -> DITOLAK
        with patch.object(db.session, "commit"):
            ok, err = update_portal_user_email(user, "new.email@example.com", "WrongPassword#123")
            assert ok is False
            assert "Password saat ini tidak sesuai." in err
            assert user.email == "cust.old@example.com"

        # 2. Email kosong -> DITOLAK
        with patch.object(db.session, "commit"):
            ok, err = update_portal_user_email(user, "   ", "CorrectPassword#123")
            assert ok is False
            assert err == "Email wajib diisi."

        # 3. Format email tidak valid -> DITOLAK
        with patch.object(db.session, "commit"):
            ok, err = update_portal_user_email(user, "not-an-email", "CorrectPassword#123")
            assert ok is False
            assert err == "Format email tidak valid."

        # 4. Email bentrok dengan user lain (case-insensitive) -> DITOLAK
        with patch.object(db.session, "commit"):
            ok, err = update_portal_user_email(user, "OTHER.MANDOR@example.com", "CorrectPassword#123")
            assert ok is False
            assert err == "Email ini sudah dipakai akun lain."

        # 5. Email valid -> BERHASIL & dinormalisasi lowercase
        with patch.object(db.session, "commit"):
            ok, err = update_portal_user_email(user, "  CUST.New@Example.COM  ", "CorrectPassword#123")
            assert ok is True
            assert err is None
            assert user.email == "cust.new@example.com"


def test_portal_dashboard_banner_visibility(app):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        branch = _create_branch()
        user = _create_user(branch, role=ROLE_PORTAL_CUSTOMER, email=None)

        client = _login(app, user)

        # 1. Email kosong -> banner muncul dengan petunjuk dan tautan ke Profil
        resp = client.get("/portal/customer")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Lengkapi email Anda agar bisa reset password jika lupa." in html
        assert "/portal/profile" in html

        # 2. Isi email -> banner hilang
        user.email = "sudah.terisi@example.com"
        db.session.flush()

        resp2 = client.get("/portal/customer")
        assert resp2.status_code == 200
        html2 = resp2.get_data(as_text=True)
        assert "Lengkapi email Anda agar bisa reset password jika lupa." not in html2


def test_portal_user_forgot_password_with_mocked_smtp(app):
    with app.app_context():
        branch = _create_branch()
        portal_email = f"portal.{uuid4().hex[:6]}@example.com"
        portal_username = f"portal_cust_{uuid4().hex[:6]}"
        user = _create_user(
            branch,
            role=ROLE_PORTAL_CUSTOMER,
            email=portal_email,
            username=portal_username,
        )

        # 1. Reset password via service dengan mock email
        with patch("app.services.password_reset_service.send_password_reset_email") as mock_send:
            mock_send.return_value = (True, None)

            # Cari via email
            ok, msg = request_password_reset(
                portal_email,
                lambda tok: f"http://test.local/reset/{tok}",
                commit=False,
            )
            assert ok is True
            assert mock_send.called
            assert mock_send.call_args[0][0] == portal_email

            mock_send.reset_mock()

            # Cari via username
            ok2, msg2 = request_password_reset(
                portal_username,
                lambda tok: f"http://test.local/reset/{tok}",
                commit=False,
            )
            assert ok2 is True
            assert mock_send.called
            assert mock_send.call_args[0][0] == portal_email

        # 2. Kirim email via SMTP stdlib di-mock
        app.config["MAIL_SERVER"] = "smtp.test.local"
        app.config["MAIL_PORT"] = 587
        app.config["MAIL_USERNAME"] = "mailer_user"
        app.config["MAIL_PASSWORD"] = "mailer_pass"

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server

            token_rec, raw_token = create_password_reset_token(user, commit=False)
            reset_url = f"http://test.local/reset/{raw_token}"
            sent, send_err = send_password_reset_email(user.email, reset_url)

            assert sent is True
            assert send_err is None
            mock_server.send_message.assert_called_once()
            mock_server.quit.assert_called_once()


def test_admin_reset_password_for_portal_user(app):
    with app.app_context():
        branch = _create_branch()
        admin = _create_user(branch, role=ROLE_ADMIN)
        portal_user = _create_user(branch, role=ROLE_PORTAL_CUSTOMER, email=None, password="OldPassword#123")

        # Admin reset password akun portal langsung (berguna bila pelanggan belum isi email)
        with patch.object(db.session, "commit"):
            ok, err = reset_user_password(portal_user, "NewSecret#2026", "NewSecret#2026", current_user=admin)
            assert ok is True
            assert err is None
            assert check_password_hash(portal_user.password_hash, "NewSecret#2026")
