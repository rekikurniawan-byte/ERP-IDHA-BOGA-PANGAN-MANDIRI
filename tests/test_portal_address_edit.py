import io
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.system import AuditLog, PortalUserMapping
from app.services.location_photo_service import (
    LocationPhotoError,
    location_photos,
    remove_photo,
)
from app.services.portal_address_service import (
    PortalAddressError,
    add_address,
    address_book,
    update_address,
)
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_DELEGATE
from app.services.user_management_service import ROLE_PORTAL_CUSTOMER


def _fake_image_file(filename="test.jpg", content=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"):
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type="image/jpeg")


def _setup_portal_user(branch_code="ADDR"):
    uid = uuid4().hex[:6]
    branch = Branch(
        code=f"BR_{branch_code}_{uid}",
        name=f"Branch {uid}",
        address="Jl. Test",
        phone="0812345678",
        is_active=True,
    )
    db.session.add(branch)
    db.session.flush()

    user = User(
        branch_id=branch.id,
        full_name=f"Portal User {uid}",
        username=f"portal_user_{uid}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_PORTAL_CUSTOMER,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()

    client = Client(
        client_code=f"CL-{uid}",
        name=f"Client {uid}",
        address="Jl. Proyek",
        is_active=True,
    )
    db.session.add(client)
    db.session.flush()

    mandor = Mandor(
        client_id=client.id,
        branch_id=branch.id,
        name=f"Mandor {uid}",
        is_active=True,
    )
    db.session.add(mandor)
    db.session.flush()

    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name=f"Lokasi Awal {uid}",
        description="Patokan gerbang merah",
        latitude="-6.2000000",
        longitude="106.8166660",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()

    mapping = PortalUserMapping(
        user_id=user.id,
        principal_type=PRINCIPAL_DELEGATE,
        client_id=client.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        access_level=ACCESS_DRAFT_ORDER,
        is_active=True,
    )
    db.session.add(mapping)
    db.session.flush()

    return user, branch, client, mandor, location


def test_portal_user_can_update_own_address(app):
    with app.app_context():
        user, branch, client, mandor, location = _setup_portal_user("OWN")

        # Pastikan location masuk di address_book dan editable
        book = address_book(user)
        assert book["allowed"] is True
        row = next((r for r in book["rows"] if r["location"].id == location.id), None)
        assert row is not None
        assert row["editable"] is True

        # Update nama, patokan, dan titik koordinat
        update_form = {
            "location_name": "Rumah Utama",
            "address": "Jl. Melati No. 45, dekat masjid",
            "latitude": "-6.2088000",
            "longitude": "106.8456000",
            "gps_accuracy": "10",
        }

        updated = update_address(user, location.id, update_form)
        db.session.flush()

        assert updated.location_name == "Rumah Utama"
        assert updated.description == "Jl. Melati No. 45, dekat masjid"
        assert str(updated.latitude).startswith("-6.2088")
        assert str(updated.longitude).startswith("106.8456")

        # Cek audit log tercatat
        log = AuditLog.query.filter_by(
            module="PORTAL",
            event_type="PORTAL_ADDRESS_SAVED",
            record_id=location.id,
        ).order_by(AuditLog.id.desc()).first()
        assert log is not None
        assert log.action == "UPDATE"
        assert log.user_id == user.id


def test_portal_user_cannot_update_other_user_address(app):
    with app.app_context():
        user1, _, _, _, loc1 = _setup_portal_user("U1")
        user2, _, _, _, loc2 = _setup_portal_user("U2")

        update_form = {
            "location_name": "Bajak Alamat",
            "address": "Jl. Ilegal No. 1",
            "latitude": "-6.2000000",
            "longitude": "106.8166660",
        }

        with pytest.raises(PortalAddressError) as exc_info:
            update_address(user1, loc2.id, update_form)
        assert "tidak bisa diubah dari akun Anda" in str(exc_info.value)


def test_location_photo_management_minimum_one_rule(app):
    with app.app_context():
        user, branch, client, mandor, location = _setup_portal_user("PH")

        # Unggah foto pertama menggunakan add_address
        add_form = {
            "location_name": "Pos Jaga",
            "address": "Pintu masuk proyek",
            "latitude": "-6.2100000",
            "longitude": "106.8200000",
        }
        f1 = _fake_image_file("foto1.jpg")
        new_loc = add_address(user, add_form, files=[f1])
        db.session.flush()

        photos = location_photos(new_loc.id)
        assert len(photos) == 1

        # Coba hapus saat hanya ada 1 foto -> harus ditolak
        with pytest.raises(LocationPhotoError) as exc_info:
            remove_photo(user, new_loc, photos[0].id)
        assert "minimal 1 foto" in str(exc_info.value)

        # Tambah foto kedua lewat update_address
        f2 = _fake_image_file("foto2.jpg")
        update_form = {
            "location_name": "Pos Jaga Diperbarui",
            "address": "Pintu masuk proyek sebelah pos satpam",
            "latitude": "-6.2100000",
            "longitude": "106.8200000",
        }
        update_address(user, new_loc.id, update_form, files=[f2])
        db.session.flush()

        photos_now = location_photos(new_loc.id)
        assert len(photos_now) == 2

        # Sekarang foto pertama bisa dihapus
        removed = remove_photo(user, new_loc, photos_now[0].id)
        assert removed.is_deleted is True

        photos_after = location_photos(new_loc.id)
        assert len(photos_after) == 1
