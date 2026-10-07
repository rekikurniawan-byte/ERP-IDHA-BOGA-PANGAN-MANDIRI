from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models.master import Branch, User
from app.models.system import PasswordResetToken
from app.services.password_reset_service import (
    create_password_reset_token,
    execute_password_reset,
    request_password_reset,
    send_password_reset_email,
    verify_reset_token,
)
from app.utils.clock import now_wib


def _create_branch_and_user(role="ADMIN", email=None):
    uid = uuid4().hex[:8]
    branch = Branch(
        code=f"BR_{uid[:4]}",
        name=f"Branch Test {uid[:4]}",
        address="Jl. Test No. 1",
        phone="0812345678",
        is_active=True,
    )
    db.session.add(branch)
    db.session.flush()

    user = User(
        branch_id=branch.id,
        full_name=f"User {uid[:6]}",
        username=f"user_{uid}",
        email=email or f"user_{uid}@example.com",
        password_hash="pbkdf2:sha256:dummy",
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return branch, user


def test_request_password_reset_existing_and_nonexistent_email(app):
    with app.app_context():
        branch, user = _create_branch_and_user(email="registered@example.com")

        with patch("app.services.password_reset_service.send_password_reset_email") as mock_send:
            mock_send.return_value = (True, None)

            # Email terdaftar
            success, msg = request_password_reset(
                "registered@example.com",
                lambda tok: f"http://test.local/reset/{tok}",
                commit=False,
            )
            assert success is True
            assert msg == "Kalau email terdaftar, link reset sudah dikirim."
            assert mock_send.called
            assert mock_send.call_args[0][0] == "registered@example.com"

            mock_send.reset_mock()

            # Email tidak terdaftar -> pesan harus persis sama, email tidak dikirim
            success2, msg2 = request_password_reset(
                "unknown@example.com",
                lambda tok: f"http://test.local/reset/{tok}",
                commit=False,
            )
            assert success2 is True
            assert msg2 == "Kalau email terdaftar, link reset sudah dikirim."
            assert not mock_send.called


def test_token_lifecycle_valid_expired_and_single_use(app):
    with app.app_context():
        branch, user = _create_branch_and_user()

        # 1. Buat token
        token_record, raw_token = create_password_reset_token(user, commit=False)
        db.session.flush()

        # 2. Verifikasi valid
        rec, err = verify_reset_token(raw_token)
        assert err is None
        assert rec is not None
        assert rec.id == token_record.id

        # 3. Token salah
        rec_bad, err_bad = verify_reset_token("invalid-random-token")
        assert rec_bad is None
        assert "tidak valid" in err_bad

        # 4. Token expired
        token_record.expires_at = now_wib() - timedelta(minutes=5)
        db.session.flush()
        rec_exp, err_exp = verify_reset_token(raw_token)
        assert rec_exp is None
        assert "kadaluarsa" in err_exp

        # 5. Token sekali pakai (used_at)
        token_record.expires_at = now_wib() + timedelta(minutes=30)
        token_record.used_at = now_wib()
        db.session.flush()
        rec_used, err_used = verify_reset_token(raw_token)
        assert rec_used is None
        assert "pernah digunakan" in err_used


def test_execute_password_reset_success_and_validation(app):
    with app.app_context():
        branch, user = _create_branch_and_user()
        _, raw_token = create_password_reset_token(user, commit=False)
        db.session.flush()

        # Validasi password pendek (< 6 char)
        ok, err = execute_password_reset(raw_token, "123", "123", commit=False)
        assert ok is False
        assert "minimal" in err.lower()

        # Validasi konfirmasi tidak cocok
        ok, err = execute_password_reset(raw_token, "Secret1234", "Different1234", commit=False)
        assert ok is False
        assert "tidak sama" in err.lower()

        # Berhasil reset
        ok, msg = execute_password_reset(raw_token, "NewPassword123", "NewPassword123", commit=False)
        assert ok is True
        assert "berhasil" in msg.lower()

        db.session.flush()
        assert check_password_hash(user.password_hash, "NewPassword123")

        # Coba pakai token yang sama lagi -> harus ditolak karena used_at sudah terisi
        ok2, err2 = execute_password_reset(raw_token, "AnotherPass123", "AnotherPass123", commit=False)
        assert ok2 is False
        assert "pernah digunakan" in err2


def test_send_password_reset_email_smtp_mocked(app):
    with app.app_context():
        app.config["MAIL_SERVER"] = "smtp.mailtrap.io"
        app.config["MAIL_PORT"] = 587
        app.config["MAIL_USERNAME"] = "user_test"
        app.config["MAIL_PASSWORD"] = "pass_test"
        app.config["MAIL_USE_TLS"] = True
        app.config["MAIL_FROM"] = "no-reply@idhabogapangan.co.id"

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server

            ok, err = send_password_reset_email("target@example.com", "http://example.com/reset/abc")
            assert ok is True
            assert err is None
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("user_test", "pass_test")
            mock_server.send_message.assert_called_once()
            mock_server.quit.assert_called_once()


def test_staff_reset_password_by_admin_and_owner(app):
    with app.app_context():
        from app.services.user_management_service import reset_user_password

        branch, owner = _create_branch_and_user(role="OWNER")
        _, admin = _create_branch_and_user(role="ADMIN")
        _, dapur = _create_branch_and_user(role="DAPUR")

        # Admin reset staf Dapur -> Boleh
        with patch.object(db.session, "commit"):
            ok, err = reset_user_password(dapur, "NewPass123", "NewPass123", current_user=admin)
            assert ok is True
            assert err is None

            # Admin reset OWNER -> Ditolak
            ok, err = reset_user_password(owner, "NewPass123", "NewPass123", current_user=admin)
            assert ok is False
            assert "hanya boleh dilakukan oleh OWNER" in err

            # OWNER reset OWNER lain -> Boleh
            _, owner2 = _create_branch_and_user(role="OWNER")
            ok, err = reset_user_password(owner2, "NewPass123", "NewPass123", current_user=owner)
            assert ok is True
            assert err is None
