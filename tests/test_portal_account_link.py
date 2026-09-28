"""Akun portal PT / Mandor dihubungkan OWNER di form User.

Keputusan owner 2026-09-28 (gladi pilot): satu akun = satu PT atau satu
mandor; Portal PT memantau seluruh mandornya dan memesan hanya lewat Order
langsung; Portal Mandor memesan untuk lokasinya sendiri; pelanggan umum
mendaftar sendiri, tidak dibuat dari form User.
"""
from uuid import uuid4

from app.models.master import Client, DeliveryLocation, Mandor, User
from app.models.system import PortalUserMapping
from app.services.portal_mapping_service import build_portal_external_scope
from tests.test_prepaid_orders import ctx  # noqa: F401 - fixture

GUARD_PASSWORD = "OwnerGladi#2026"


def _owner_client(app, db):
    from werkzeug.security import generate_password_hash

    from app.models.master import Branch

    branch = Branch(code=f"LNK-{uuid4().hex[:6]}", name="Cabang Uji Portal", is_active=True)
    db.session.add(branch)
    db.session.flush()
    owner = User(branch_id=branch.id, full_name="Owner Uji", username=f"own-{uuid4().hex[:8]}",
                 password_hash=generate_password_hash(GUARD_PASSWORD), role="OWNER", is_active=True)
    db.session.add(owner)
    db.session.flush()
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(owner.id)
        session["_fresh"] = True
    return branch, owner, client


def _contract(db, branch, name):
    client = Client(name=f"{name} {uuid4().hex[:6]}", customer_path="KONTRAK", is_active=True)
    db.session.add(client)
    db.session.flush()
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {name} {uuid4().hex[:6]}", is_active=True)
    db.session.add(mandor)
    db.session.flush()
    db.session.add(DeliveryLocation(mandor_id=mandor.id, location_name=f"Proyek {name}", is_active=True))
    db.session.flush()
    return client, mandor


def _form(branch, **extra):
    return {
        "full_name": "Akun Portal Uji", "branch_id": branch.id, "is_active": "on",
        "sensitive_action_confirmed": "1", "sensitive_reason": "Uji hubungkan akun portal",
        "confirm_password": GUARD_PASSWORD, **extra,
    }


def _active_links(user):
    return [(row.principal_type, row.client_id, row.mandor_id, row.access_level)
            for row in PortalUserMapping.query.filter_by(user_id=user.id, is_active=True).all()]


def test_owner_menghubungkan_akun_portal_mandor_lalu_bisa_memesan(app, ctx):
    app.config.update(WTF_CSRF_ENABLED=False, PORTAL_ENABLED=True)
    branch, _owner, owner_client = _owner_client(app, ctx)
    _client, mandor = _contract(ctx, branch, "Maju")
    username = f"mandor-{uuid4().hex[:8]}"

    owner_client.post("/settings/users/create", data=_form(
        branch, username=username, role="PORTAL_SUBCLIENT", password="PortalUji#2026",
        password_confirmation="PortalUji#2026", portal_mandor_id=mandor.id))

    user = User.query.filter_by(username=username).one()
    assert _active_links(user) == [("MANDOR", None, mandor.id, "DRAFT_ORDER")]
    scope = build_portal_external_scope(user)
    assert scope.allowed and scope.mandor_ids == {mandor.id} and len(scope.delivery_location_ids) == 1


def test_pindah_pt_dan_ganti_role_tidak_meninggalkan_akses_lama(app, ctx):
    app.config.update(WTF_CSRF_ENABLED=False)
    branch, _owner, owner_client = _owner_client(app, ctx)
    first, _ = _contract(ctx, branch, "Satu")
    second, _ = _contract(ctx, branch, "Dua")
    username = f"pt-{uuid4().hex[:8]}"
    owner_client.post("/settings/users/create", data=_form(
        branch, username=username, role="PORTAL_CLIENT", password="PortalUji#2026",
        password_confirmation="PortalUji#2026", portal_client_id=first.id))
    user = User.query.filter_by(username=username).one()

    owner_client.post(f"/settings/users/{user.id}/edit", data=_form(branch, username=username, role="PORTAL_CLIENT", portal_client_id=second.id))
    owner_client.post(f"/settings/users/{user.id}/edit", data=_form(branch, username=username, role="PORTAL_CLIENT", portal_client_id=second.id))

    assert _active_links(user) == [("CLIENT", second.id, None, "DRAFT_ORDER")]

    owner_client.post(f"/settings/users/{user.id}/edit", data=_form(branch, username=username, role="ADMIN"))

    assert User.query.get(user.id).role == "ADMIN"
    assert _active_links(user) == []


def test_akun_portal_tanpa_pt_atau_mandor_dan_pelanggan_umum_ditolak(app, ctx):
    app.config.update(WTF_CSRF_ENABLED=False)
    branch, _owner, owner_client = _owner_client(app, ctx)
    general = Client(name=f"Pelanggan {uuid4().hex[:6]}", customer_path="UMUM", is_active=True)
    ctx.session.add(general)
    ctx.session.flush()
    general_mandor = Mandor(branch_id=branch.id, client_id=general.id, name=general.name, is_active=True)
    ctx.session.add(general_mandor)
    ctx.session.flush()

    for role, extra in (("PORTAL_CLIENT", {}), ("PORTAL_SUBCLIENT", {"portal_mandor_id": general_mandor.id}),
                        ("PORTAL_CUSTOMER", {})):
        username = f"tolak-{uuid4().hex[:8]}"
        owner_client.post("/settings/users/create", data=_form(
            branch, username=username, role=role, password="PortalUji#2026",
            password_confirmation="PortalUji#2026", **extra))
        assert User.query.filter_by(username=username).first() is None, role
