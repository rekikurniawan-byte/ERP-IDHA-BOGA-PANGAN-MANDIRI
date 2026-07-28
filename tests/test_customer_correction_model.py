from decimal import Decimal

from app.extensions import db
from app.models.correction import CustomerCorrection
from app.services.customer_complaint_service import COMPLAINT_CATEGORY_LATE_DELIVERY, submit_customer_complaint
from tests.test_portal_financial_visibility_service import _create_client_family, _create_user


def test_customer_correction_model_is_additive_and_does_not_post_financial_or_stock_effects(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("ADMIN")
            client, _, mandor, _ = _create_client_family(user.branch, "CORRECTION")
            complaint = submit_customer_complaint(
                branch_id=user.branch_id,
                category=COMPLAINT_CATEGORY_LATE_DELIVERY,
                title="Delivery terlambat",
                description="Delivery terlambat dari jadwal.",
                submitted_by=user.id,
                client_id=client.id,
                mandor_id=mandor.id,
                commit=False,
            )

            correction = CustomerCorrection(
                branch_id=user.branch_id,
                correction_number=f"CRC-QA-{user.id}",
                correction_type="COMPENSATION",
                status="DRAFT",
                complaint_id=complaint.id,
                client_id=client.id,
                mandor_id=mandor.id,
                reason="Complaint valid dan perlu kompensasi.",
                proposed_action="Berikan kompensasi pada order berikutnya.",
                correction_amount=Decimal("25000.00"),
                stock_effect="NONE",
                financial_effect="NONE",
                submitted_by=user.id,
            )
            db.session.add(correction)
            db.session.flush()

            loaded = CustomerCorrection.query.filter_by(id=correction.id).one()

            assert loaded.version_id == 1
            assert loaded.correction_amount == Decimal("25000.00")
            assert loaded.complaint_id == complaint.id
            assert loaded.complaint.complaint_number == complaint.complaint_number
            assert loaded.stock_effect == "NONE"
            assert loaded.financial_effect == "NONE"
            assert loaded.invoice_id is None
            assert loaded.approval_request_id is None
        finally:
            transaction.rollback()
