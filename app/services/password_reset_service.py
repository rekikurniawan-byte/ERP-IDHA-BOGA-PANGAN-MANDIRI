import hashlib
import secrets
from contextlib import nullcontext
from datetime import timedelta
from email.message import EmailMessage
import smtplib

from flask import current_app
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import User
from app.models.system import PasswordResetToken
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_critical_audit_log
from app.services.user_management_service import validate_password_pair
from app.utils.clock import now_wib

RESET_TOKEN_EXPIRY_MINUTES = 30
GENERIC_RESET_REQUEST_MESSAGE = "Kalau email terdaftar, link reset sudah dikirim."


def create_password_reset_token(user, commit=True) -> tuple[PasswordResetToken, str]:
    """Buat token reset password acak (32 bytes urlsafe), simpan hash-nya, berlaku 30 menit."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = now_wib() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)

    token_record = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    boundary = (
        atomic_business_action(
            module="AUTH",
            action="PASSWORD_RESET_TOKEN_GENERATED",
            description=f"Token reset password dibuat untuk {user.username}.",
            user_id=user.id,
            branch_id=user.branch_id,
            reference_type="password_reset_tokens",
            severity="LOW",
        )
        if commit
        else nullcontext()
    )

    with boundary:
        db.session.add(token_record)

    return token_record, raw_token


def send_password_reset_email(to_email: str, reset_url: str) -> tuple[bool, str | None]:
    """Kirim email reset password via SMTP stdlib.

    Jika konfigurasi email belum diatur, catat ke log dan jangan crash.
    """
    mail_server = current_app.config.get("MAIL_SERVER")
    mail_port = int(current_app.config.get("MAIL_PORT") or 587)
    mail_username = current_app.config.get("MAIL_USERNAME")
    mail_password = current_app.config.get("MAIL_PASSWORD")
    mail_use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    mail_from = current_app.config.get("MAIL_FROM") or mail_username or "noreply@idhabogapangan.co.id"

    if not mail_server or not mail_username:
        current_app.logger.warning(
            "Konfigurasi SMTP belum lengkap (MAIL_SERVER/MAIL_USERNAME kosong). Email reset password ke %s dilewati.",
            to_email,
        )
        return False, "Konfigurasi SMTP belum lengkap."

    msg = EmailMessage()
    msg["Subject"] = "Permintaan Reset Password - PT Idha Boga Pangan Mandiri"
    msg["From"] = mail_from
    msg["To"] = to_email
    msg.set_content(
        f"Halo,\n\n"
        f"Kami menerima permintaan untuk mereset password akun Anda di ERP PT Idha Boga Pangan Mandiri.\n\n"
        f"Silakan klik tautan berikut untuk membuat password baru:\n"
        f"{reset_url}\n\n"
        f"Tautan ini berlaku selama {RESET_TOKEN_EXPIRY_MINUTES} menit dan hanya dapat digunakan 1 (satu) kali.\n"
        f"Jika Anda tidak merasa meminta reset password, silakan abaikan email ini.\n\n"
        f"Salam,\n"
        f"PT Idha Boga Pangan Mandiri\n"
    )

    try:
        server = smtplib.SMTP(mail_server, mail_port, timeout=15)
        if mail_use_tls:
            server.starttls()
        if mail_username and mail_password:
            server.login(mail_username, mail_password)
        server.send_message(msg)
        server.quit()
        return True, None
    except Exception as err:
        current_app.logger.exception("Gagal mengirim email reset password ke %s: %s", to_email, err)
        return False, str(err)


def request_password_reset(identifier: str, reset_url_builder, commit=True) -> tuple[bool, str]:
    """Proses permintaan reset password berdasarkan email atau username.

    Pesan respon selalu konsisten agar tidak membocorkan keberadaan email/akun.
    """
    cleaned_input = (identifier or "").strip()
    if not cleaned_input:
        return True, GENERIC_RESET_REQUEST_MESSAGE

    user = User.query.filter(
        or_(
            func.lower(User.email) == cleaned_input.lower(),
            func.lower(User.username) == cleaned_input.lower(),
        ),
        User.is_active == True,
    ).first()

    if user and user.email:
        _, raw_token = create_password_reset_token(user, commit=commit)
        reset_url = reset_url_builder(raw_token)
        send_password_reset_email(user.email, reset_url)

    return True, GENERIC_RESET_REQUEST_MESSAGE


def verify_reset_token(raw_token: str) -> tuple[PasswordResetToken | None, str | None]:
    """Cek keabsahan token reset password."""
    if not raw_token or not raw_token.strip():
        return None, "Link reset password tidak valid."

    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    token_record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()

    if not token_record:
        return None, "Link reset password tidak valid atau sudah kadaluarsa."

    if token_record.used_at is not None:
        return None, "Link reset password sudah pernah digunakan."

    if now_wib() > token_record.expires_at:
        return None, "Link reset password sudah kadaluarsa (lebih dari 30 menit)."

    return token_record, None


def execute_password_reset(
    raw_token: str,
    new_password: str,
    confirmation: str,
    commit=True,
) -> tuple[bool, str]:
    """Eksekusi ganti password dari link reset token."""
    token_record, verify_err = verify_reset_token(raw_token)
    if verify_err:
        return False, verify_err

    valid_password, pass_err = validate_password_pair(new_password, confirmation)
    if not valid_password:
        return False, pass_err or "Password tidak valid."

    user = token_record.user
    user.password_hash = generate_password_hash(new_password)
    used_at = now_wib()
    token_record.used_at = used_at
    # Link reset lain milik user ini yang belum dipakai ikut hangus, supaya link
    # lama (mis. dari email yang bocor) tidak bisa dipakai setelah password diganti.
    PasswordResetToken.query.filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != token_record.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: used_at}, synchronize_session=False)

    boundary = (
        atomic_business_action(
            module="AUTH",
            action="PASSWORD_RESET_SUCCESS",
            description=f"Password user {user.username} berhasil direset via email link.",
            user_id=user.id,
            branch_id=user.branch_id,
            reference_type="users",
            reference_id=user.id,
            severity="HIGH",
        )
        if commit
        else nullcontext()
    )

    with boundary:
        db.session.add(user)
        db.session.add(token_record)

    record_critical_audit_log(
        module="AUTH",
        event_type="PASSWORD_RESET_SUCCESS",
        action="UPDATE",
        table_name="users",
        record_id=user.id,
        description=f"Password user {user.username} berhasil direset lewat link email.",
        user_id=user.id,
        branch_id=user.branch_id,
        username_snapshot=user.username,
        user_role_snapshot=user.role,
        severity="HIGH",
    )

    return True, "Password berhasil diperbarui. Silakan login dengan password baru Anda."
