"""Order langsung untuk client kontrak tanpa sub client.

Keputusan owner 2026-09-25 yang dikunci di sini:
- client yang memesan sendiri mendapat unit "PT X — Langsung", tidak
  membongkar kewajiban mandor di enam tabel;
- satu unit langsung per client per cabang;
- dari portal, PT hanya boleh memesan untuk unit langsungnya sendiri;
- unit langsung ditagih ke client, tidak bisa disetel "ditagih ke mandor".
"""
from types import SimpleNamespace

import pytest

from app.services.client_direct_order_service import (
    DIRECT_UNIT_SUFFIX,
    DirectOrderError,
    activate_direct_ordering,
    direct_unit_ids,
    direct_unit_name,
    get_direct_unit,
)


@pytest.fixture
def db_session(app, monkeypatch):
    """Tanpa commit ke test_db: layanan master commit sendiri, di sini cukup flush."""
    with app.app_context():
        from app.extensions import db
        from app.services import master_data_service

        monkeypatch.setattr(master_data_service, "_commit_or_rollback", lambda: db.session.flush())
        try:
            yield db
        finally:
            db.session.rollback()


def _client_and_branch():
    from app.models.master import Branch, Client

    branch = Branch.query.order_by(Branch.id.asc()).first()
    client = Client.query.filter_by(is_active=True).order_by(Client.id.asc()).first()
    if branch is None or client is None:
        pytest.skip("cabang/client tidak ada di database uji")
    # Mulai dari keadaan tanpa unit langsung, apa pun yang ditinggal run lain.
    from app.models.master import Mandor

    Mandor.query.filter_by(branch_id=branch.id, client_id=client.id, is_direct_unit=True).update(
        {"is_direct_unit": False}
    )
    return client, branch


def test_nama_unit_langsung():
    assert direct_unit_name(SimpleNamespace(name="PT Maju")) == "PT Maju" + DIRECT_UNIT_SUFFIX
    assert DIRECT_UNIT_SUFFIX == " — Langsung"


def test_aktivasi_membuat_satu_unit_langsung(db_session):
    client, branch = _client_and_branch()

    unit, created = activate_direct_ordering(client, branch.id)

    assert created
    assert unit.is_direct_unit
    assert unit.client_id == client.id
    assert unit.branch_id == branch.id
    assert unit.name == direct_unit_name(client)
    assert get_direct_unit(branch.id, client.id).id == unit.id


def test_aktivasi_dua_kali_tidak_membuat_unit_kedua(db_session):
    client, branch = _client_and_branch()

    first, _ = activate_direct_ordering(client, branch.id)
    second, created = activate_direct_ordering(client, branch.id)

    assert not created
    assert second.id == first.id


def test_client_nonaktif_tidak_bisa_diaktifkan():
    with pytest.raises(DirectOrderError, match="nonaktif"):
        activate_direct_ordering(SimpleNamespace(id=1, name="PT Tutup", is_active=False), 1)


def test_nama_yang_sudah_dipakai_sub_client_lain_ditolak(db_session):
    from app.models.master import Mandor

    client, branch = _client_and_branch()
    db_session.session.add(Mandor(
        branch_id=branch.id, client_id=client.id, name=direct_unit_name(client), is_active=True,
    ))
    db_session.session.flush()

    with pytest.raises(DirectOrderError, match="Sudah ada"):
        activate_direct_ordering(client, branch.id)


def test_hanya_unit_langsung_yang_terpilih(db_session):
    from app.models.master import Mandor

    client, branch = _client_and_branch()
    unit, _ = activate_direct_ordering(client, branch.id)
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name="Mandor Biasa Uji", is_active=True)
    db_session.session.add(mandor)
    db_session.session.flush()

    assert direct_unit_ids({unit.id, mandor.id}) == {unit.id}
    assert direct_unit_ids(set()) == set()


def test_pt_hanya_bisa_memesan_untuk_lokasi_unit_langsungnya(db_session):
    from app.models.master import DeliveryLocation, Mandor
    from app.services.portal_order_draft_service import orderable_location_ids

    client, branch = _client_and_branch()
    unit, _ = activate_direct_ordering(client, branch.id)
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name="Mandor Lokasi Uji", is_active=True)
    db_session.session.add(mandor)
    db_session.session.flush()
    unit_location = DeliveryLocation(mandor_id=unit.id, location_name="Kantor PT Uji", is_active=True)
    mandor_location = DeliveryLocation(mandor_id=mandor.id, location_name="Proyek Mandor Uji", is_active=True)
    db_session.session.add_all([unit_location, mandor_location])
    db_session.session.flush()

    scope = SimpleNamespace(
        allowed=True,
        delivery_location_ids={unit_location.id, mandor_location.id},
        mandor_ids={unit.id, mandor.id},
    )
    pt = SimpleNamespace(role="PORTAL_CLIENT")
    sub_client = SimpleNamespace(role="PORTAL_SUBCLIENT")

    # PT memantau keduanya, tapi hanya memesan untuk unit langsungnya.
    assert orderable_location_ids(pt, scope) == {unit_location.id}
    # Sub client tetap memesan untuk seluruh lokasi dalam aksesnya.
    assert orderable_location_ids(sub_client, scope) == {unit_location.id, mandor_location.id}


def test_pt_tanpa_unit_langsung_tidak_bisa_memesan(db_session):
    from app.models.master import DeliveryLocation, Mandor
    from app.services.portal_order_draft_service import orderable_location_ids

    client, branch = _client_and_branch()
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name="Mandor Saja Uji", is_active=True)
    db_session.session.add(mandor)
    db_session.session.flush()
    location = DeliveryLocation(mandor_id=mandor.id, location_name="Proyek Saja Uji", is_active=True)
    db_session.session.add(location)
    db_session.session.flush()

    scope = SimpleNamespace(allowed=True, delivery_location_ids={location.id}, mandor_ids={mandor.id})
    assert orderable_location_ids(SimpleNamespace(role="PORTAL_CLIENT"), scope) == set()


def test_unit_langsung_tidak_bisa_disetel_ditagih_ke_mandor(db_session):
    from app.services.credit_account_service import CreditActionError, save_credit_settings

    client, branch = _client_and_branch()
    unit, _ = activate_direct_ordering(client, branch.id)
    form = {
        "billing_mode": "DIRECT", "credit_limit": "1.000.000", "payment_terms_days": "14",
        "deposit_percent": "20", "id_number": "3201000000000009", "address": "Jl. Uji",
    }
    with pytest.raises(CreditActionError, match="Unit order langsung"):
        save_credit_settings(unit, form, SimpleNamespace(id=1, role="OWNER"))
