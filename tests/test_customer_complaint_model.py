from datetime import datetime

from app.extensions import db
from app.models.complaint import CustomerComplaint
from tests.test_customer_contract_service import _contract_fixture


def test_customer_complaint_model_can_reference_existing_scope_without_mutating_transactions(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, _ = _contract_fixture()
            complaint = CustomerComplaint(
                branch_id=user.branch_id,
                complaint_number=f"CMP-QA-{user.id}",
                category="LATE_DELIVERY",
                status="OPEN",
                title="Delivery terlambat",
                description="Delivery terlambat dari jadwal.",
                client_id=client.id,
                submitted_by=user.id,
                submitted_at=datetime.utcnow(),
            )
            db.session.add(complaint)
            db.session.flush()

            loaded = CustomerComplaint.query.filter_by(id=complaint.id).one()

            assert loaded.branch_id == user.branch_id
            assert loaded.client_id == client.id
            assert loaded.status == "OPEN"
            assert loaded.version_id == 1
            assert loaded.client.name == client.name
            assert loaded.submitter.id == user.id
            assert loaded.invoice_id is None
            assert loaded.delivery_id is None
        finally:
            transaction.rollback()
