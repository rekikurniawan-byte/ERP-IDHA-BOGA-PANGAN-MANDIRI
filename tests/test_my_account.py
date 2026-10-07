"""Tests for Akun Saya (Bagian 1).

Memastikan:
1. Tiap role (OWNER, ADMIN, DAPUR, PENGANTAR, portal) bisa membuka halaman Akun Saya.
2. User bisa mengubah nama dan nomor HP/WA serta alamat.
3. Username, role, dan branch tidak bisa diubah lewat form Akun Saya.
4. Ganti password: salah password lama ditolak, berhasil jika sesuai.
5. Email bentrok ditolak, dan mengubah email mewajibkan password saat ini.
6. Upload dan hapus foto profil avatar.
7. Kontrol akses avatar: user lain yang tidak berhak ditolak (403).
"""
import io
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import AuditLog, DigitalAttachment, PortalUserMapping
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_DELEGATE
from app.services.user_profile_service import (
    UserProfileError,
    can_view_avatar,
    change_user_password,
    delete_user_avatar,
    update_user_profile,
    upload_user_avatar,
)


def _fake_image_file(filename="avatar.jpg"):
    # 1x1 JPEG bytes
    content = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05"
        b"\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c"
        b" $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
        b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05"
        b"\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    )
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type="image/jpeg")


def _create_user(role="ADMIN", branch=None, username=None, email=None):
    uid = uuid4().hex[:6]
    if not branch:
        branch = Branch(
            code=f"BR_{uid}",
            name=f"Cabang {uid}",
            address="Jl. Test No. 1",
            phone="0812345678",
            is_active=True,
        )
        db.session.add(branch)
        db.session.flush()

    user = User(
        branch_id=branch.id,
        full_name=f"Nama User {uid}",
        username=username or f"user_{uid}",
        email=email or f"user_{uid}@example.com",
        phone="0811111111",
        address="Alamat asal",
        password_hash=generate_password_hash("password123"),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()

    if role.startswith("PORTAL_"):
        client = Client(client_code=f"CL-{uid}", name=f"Client {uid}", is_active=True)
        db.session.add(client)
        db.session.flush()
        mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {uid}", is_active=True)
        db.session.add(mandor)
        db.session.flush()
        loc = DeliveryLocation(mandor_id=mandor.id, location_name=f"Lokasi {uid}", is_active=True)
        db.session.add(loc)
        db.session.flush()
        mapping = PortalUserMapping(
            user_id=user.id,
            principal_type=PRINCIPAL_DELEGATE,
            client_id=client.id,
            mandor_id=mandor.id,
            delivery_location_id=loc.id,
            access_level=ACCESS_DRAFT_ORDER,
            is_active=True,
        )
        db.session.add(mapping)
        db.session.flush()

    db.session.commit()
    return user, branch


def _login(client, user):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


@pytest.mark.parametrize(
    "role",
    ["OWNER", "ADMIN", "DAPUR", "PENGANTAR", "PORTAL_CUSTOMER", "PORTAL_CLIENT", "PORTAL_SUBCLIENT"],
)
def test_all_roles_can_open_my_account(app, client, role):
    """Semua role (OWNER, ADMIN, DAPUR, PENGANTAR, portal) bisa membuka Akun Saya."""
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user, branch = _create_user(role=role)
        _login(client, user)
        if role.startswith("PORTAL_"):
            # Portal membuka /portal/profile
            res = client.get("/portal/profile")
            assert res.status_code == 200
            html = res.get_data(as_text=True)
            assert "Akun Saya" in html or "Profil Portal" in html
            assert user.username in html

            # Portal mencoba /settings/account -> redirect ke /portal/profile
            res_redirect = client.get("/settings/account")
            assert res_redirect.status_code == 302
            assert "/portal/profile" in res_redirect.headers.get("Location", "")
        else:
            # Staf membuka /settings/account
            res = client.get("/settings/account")
            assert res.status_code == 200
            html = res.get_data(as_text=True)
            assert "Akun Saya" in html
            assert user.username in html


def test_update_profile_name_phone_address(app):
    """User bisa mengubah nama lengkap, no HP, dan alamat diri."""
    with app.app_context():
        user, _ = _create_user(role="ADMIN")

        form = {
            "full_name": "Nama Lengkap Baru",
            "phone": "089988776655",
            "address": "Jl. Merdeka No. 45",
            "email": user.email,
        }
        update_user_profile(user, form, is_portal=False)

        assert user.full_name == "Nama Lengkap Baru"
        assert user.phone == "089988776655"
        assert user.address == "Jl. Merdeka No. 45"

        # Audit log tercatat
        audit = AuditLog.query.filter_by(
            module="USER",
            user_id=user.id,
        ).filter(AuditLog.event_type.like("%UPDATE_PROFILE%")).first()
        assert audit is not None


def test_cannot_change_username_role_or_branch(app):
    """Username, role, dan branch tidak bisa diubah lewat form profil."""
    with app.app_context():
        user, branch = _create_user(role="PENGANTAR")
        orig_username = user.username
        orig_role = user.role
        orig_branch_id = user.branch_id

        # Mengirimkan field terlarang
        form = {
            "full_name": "Pengantar Handal",
            "username": "hacker_username",
            "role": "OWNER",
            "branch_id": 99999,
            "email": user.email,
        }
        update_user_profile(user, form, is_portal=False)

        # Harus tetap nilai semula
        assert user.username == orig_username
        assert user.role == orig_role
        assert user.branch_id == orig_branch_id
        assert user.full_name == "Pengantar Handal"


def test_change_password_logic(app):
    """Ganti password: salah password lama ditolak, benar berhasil, aturan minimal 8 karakter."""
    with app.app_context():
        user, _ = _create_user(role="DAPUR")

        # 1. Salah password lama -> gagal
        form_wrong_old = {
            "current_password": "wrongpassword",
            "password": "newpassword123",
            "password_confirmation": "newpassword123",
        }
        with pytest.raises(UserProfileError) as exc_info:
            change_user_password(user, form_wrong_old)
        assert "Password lama tidak sesuai" in str(exc_info.value)

        # 2. Konfirmasi beda -> gagal
        form_mismatch = {
            "current_password": "password123",
            "password": "newpassword123",
            "password_confirmation": "different123",
        }
        with pytest.raises(UserProfileError) as exc_info:
            change_user_password(user, form_mismatch)
        assert "Konfirmasi password tidak sama" in str(exc_info.value)

        # 3. Terlalu pendek (< 8 karakter) -> gagal
        form_short = {
            "current_password": "password123",
            "password": "short",
            "password_confirmation": "short",
        }
        with pytest.raises(UserProfileError) as exc_info:
            change_user_password(user, form_short)
        assert "minimal 8 karakter" in str(exc_info.value)

        # 4. Berhasil
        form_valid = {
            "current_password": "password123",
            "password": "newsecurepassword123",
            "password_confirmation": "newsecurepassword123",
        }
        change_user_password(user, form_valid)
        assert check_password_hash(user.password_hash, "newsecurepassword123")


def test_email_conflict_and_current_password_required(app):
    """Email bentrok ditolak, dan mengubah email mewajibkan password saat ini."""
    with app.app_context():
        u_suffix = uuid4().hex[:6]
        email1 = f"admin1_{u_suffix}@test.com"
        email2 = f"dapur2_{u_suffix}@test.com"
        new_email = f"dapur_baru_{u_suffix}@test.com"
        user1, _ = _create_user(role="ADMIN", email=email1)
        user2, _ = _create_user(role="DAPUR", email=email2)

        # Coba ubah email user2 ke email user1 -> ditolak
        form_conflict = {
            "full_name": user2.full_name,
            "email": email1,
            "current_password": "password123",
        }
        with pytest.raises(UserProfileError) as exc_info:
            update_user_profile(user2, form_conflict, is_portal=False)
        assert "sudah dipakai akun lain" in str(exc_info.value)

        # Ubah email tanpa password saat ini yang benar -> ditolak
        form_wrong_pwd = {
            "full_name": user2.full_name,
            "email": new_email,
            "current_password": "wrong_password",
        }
        with pytest.raises(UserProfileError) as exc_info:
            update_user_profile(user2, form_wrong_pwd, is_portal=False)
        assert "Password saat ini tidak sesuai" in str(exc_info.value)

        # Ubah email dengan password yang benar -> berhasil
        form_ok = {
            "full_name": user2.full_name,
            "email": new_email,
            "current_password": "password123",
        }
        update_user_profile(user2, form_ok, is_portal=False)
        assert user2.email == new_email


def test_avatar_upload_view_and_delete(app):
    """Unggah foto profil, lihat via route avatar, lalu hapus foto."""
    with app.app_context():
        user, _ = _create_user(role="OWNER")
        f = _fake_image_file("profil.jpg")

        # 1. Upload avatar
        att = upload_user_avatar(user, f)
        assert user.avatar_attachment_id is not None
        assert user.avatar_attachment_id == att.id

        # 2. View avatar via route /account/avatar/<user_id>
        with app.test_client() as client:
            _login(client, user)
            res = client.get(f"/account/avatar/{user.id}")
            assert res.status_code == 200
            assert "image" in res.content_type

        # 3. Delete avatar
        deleted = delete_user_avatar(user)
        assert deleted is True
        assert user.avatar_attachment_id is None

        # 4. View avatar lagi -> 404
        with app.test_client() as client:
            _login(client, user)
            res = client.get(f"/account/avatar/{user.id}")
            assert res.status_code == 404


def test_avatar_access_control_self(app, client):
    """User target sendiri bisa melihat avatar-nya -> 200."""
    with app.app_context():
        u = uuid4().hex[:6]
        branch = Branch(code=f"BR_{u}", name="Cabang", address="Jl", phone="08", is_active=True)
        db.session.add(branch)
        db.session.flush()
        user_target, _ = _create_user(role="PORTAL_CUSTOMER", branch=branch)
        upload_user_avatar(user_target, _fake_image_file("profil.jpg"))
        assert can_view_avatar(user_target, user_target) is True

        _login(client, user_target)
        res = client.get(f"/account/avatar/{user_target.id}")
        assert res.status_code == 200


def test_avatar_access_control_other_portal(app, client):
    """User portal lain tidak bisa melihat avatar user lain -> 403."""
    with app.app_context():
        u = uuid4().hex[:6]
        branch = Branch(code=f"BR_{u}", name="Cabang", address="Jl", phone="08", is_active=True)
        db.session.add(branch)
        db.session.flush()
        user_target, _ = _create_user(role="PORTAL_CUSTOMER", branch=branch)
        user_other, _ = _create_user(role="PORTAL_CUSTOMER", branch=branch)
        upload_user_avatar(user_target, _fake_image_file("profil.jpg"))
        assert can_view_avatar(user_other, user_target) is False

        _login(client, user_other)
        res = client.get(f"/account/avatar/{user_target.id}")
        assert res.status_code == 403


def test_avatar_access_control_other_branch_staff(app, client):
    """Staf cabang berbeda tidak bisa melihat avatar -> 403."""
    with app.app_context():
        u1, u2 = uuid4().hex[:6], uuid4().hex[:6]
        branch1 = Branch(code=f"BR_{u1}", name="Cabang 1", address="Jl", phone="08", is_active=True)
        branch2 = Branch(code=f"BR_{u2}", name="Cabang 2", address="Jl", phone="08", is_active=True)
        db.session.add_all([branch1, branch2])
        db.session.flush()
        user_target, _ = _create_user(role="PORTAL_CUSTOMER", branch=branch1)
        user_staff = _create_user(role="PENGANTAR", branch=branch2)[0]
        upload_user_avatar(user_target, _fake_image_file("profil.jpg"))
        assert can_view_avatar(user_staff, user_target) is False

        _login(client, user_staff)
        res = client.get(f"/account/avatar/{user_target.id}")
        assert res.status_code == 403


def test_avatar_access_control_owner(app, client):
    """Owner bisa melihat avatar siapa saja -> 200."""
    with app.app_context():
        u = uuid4().hex[:6]
        branch = Branch(code=f"BR_{u}", name="Cabang", address="Jl", phone="08", is_active=True)
        db.session.add(branch)
        db.session.flush()
        user_target, _ = _create_user(role="PORTAL_CUSTOMER", branch=branch)
        user_owner = _create_user(role="OWNER", branch=branch)[0]
        upload_user_avatar(user_target, _fake_image_file("profil.jpg"))
        assert can_view_avatar(user_owner, user_target) is True

        _login(client, user_owner)
        res = client.get(f"/account/avatar/{user_target.id}")
        assert res.status_code == 200
