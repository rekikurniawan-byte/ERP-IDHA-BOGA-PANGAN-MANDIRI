"""Cek kesiapan produksi (flask --app run ops-check)."""
from datetime import date
from uuid import uuid4

from app.services.readiness_service import FAIL, PASS, WARN, run_readiness_checks


def test_cek_kesiapan_melaporkan_cabang_tanpa_harga_dan_cutover(app, monkeypatch):
    with app.app_context():
        from app.extensions import db
        from app.models.master import Branch

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        app.config["ACCOUNTING_LEGACY_CUTOVER"] = {"invoice": 2}
        branch = Branch(code=f"RDY-{uuid4().hex[:8]}", name="Cabang Siap Uji", is_active=True)
        db.session.add(branch)
        db.session.flush()
        try:
            checks = {check.name: check for check in run_readiness_checks(branch_ids=[branch.id])}
        finally:
            db.session.rollback()
            app.config["ACCOUNTING_LEGACY_CUTOVER"] = {}

    assert checks["Cabang Cabang Siap Uji: harga"].status == FAIL
    assert checks["Cutover akuntansi"].status == WARN
    assert checks["Migrasi"].status == PASS
    assert checks["Hak akses tabel"].status == PASS


def test_harga_standar_membuat_cek_cabang_lulus(app, monkeypatch):
    with app.app_context():
        from app.extensions import db
        from app.models.master import Branch, User
        from app.services.pricing_service import set_portion_price

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        branch = Branch(code=f"RDY-{uuid4().hex[:8]}", name="Cabang Berharga", is_active=True)
        db.session.add(branch)
        db.session.flush()
        owner = User(branch_id=branch.id, full_name="O", username=f"rdy-{uuid4().hex[:8]}", password_hash="x", role="OWNER")
        db.session.add(owner)
        db.session.flush()
        set_portion_price(branch_id=branch.id, price=25000, effective_from=date.today(), created_by=owner.id)
        try:
            checks = {check.name: check for check in run_readiness_checks(branch_ids=[branch.id])}
        finally:
            db.session.rollback()

    assert checks["Cabang Cabang Berharga: harga"].status == PASS
