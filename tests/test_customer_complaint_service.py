import pytest

from app.extensions import db
from app.services.customer_complaint_service import (
    COMPLAINT_CATEGORY_LATE_DELIVERY,
    COMPLAINT_CATEGORY_PORTION_SHORTAGE,
    COMPLAINT_STATUS_CLOSED,
    COMPLAINT_STATUS_IN_PROGRESS,
    COMPLAINT_STATUS_OPEN,
    COMPLAINT_STATUS_RESOLVED,
    CustomerComplaintError,
    list_customer_complaints,
    submit_customer_complaint,
    transition_customer_complaint,
)
from tests.test_portal_financial_visibility_service import _create_client_family, _create_user


def _complaint_fixture():
    user = _create_user("ADMIN")
    client, _, mandor, _ = _create_client_family(user.branch, "COMPLAINT")
    return user, client, mandor


def test_submit_customer_complaint_creates_open_record_without_transaction_mutation(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, mandor = _complaint_fixture()

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

            assert complaint.id is not None
            assert complaint.complaint_number.startswith("CMP-")
            assert complaint.status == COMPLAINT_STATUS_OPEN
            assert complaint.client_id == client.id
            assert complaint.mandor_id == mandor.id
            assert complaint.invoice_id is None
            assert complaint.delivery_id is None
            assert list_customer_complaints(user.branch_id, status=COMPLAINT_STATUS_OPEN)[0].id == complaint.id
        finally:
            transaction.rollback()


def test_submit_customer_complaint_rejects_cross_branch_mandor(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, _ = _complaint_fixture()
            other_user, _, other_mandor = _complaint_fixture()

            with pytest.raises(CustomerComplaintError):
                submit_customer_complaint(
                    branch_id=user.branch_id,
                    category=COMPLAINT_CATEGORY_PORTION_SHORTAGE,
                    title="Porsi kurang",
                    description="Porsi kurang dari pesanan.",
                    submitted_by=user.id,
                    client_id=client.id,
                    mandor_id=other_mandor.id,
                    commit=False,
                )

            assert user.branch_id != other_user.branch_id
        finally:
            transaction.rollback()


def test_transition_customer_complaint_enforces_lifecycle_and_resolution_note(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, mandor = _complaint_fixture()
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

            with pytest.raises(CustomerComplaintError):
                transition_customer_complaint(
                    complaint.id,
                    branch_id=user.branch_id,
                    new_status=COMPLAINT_STATUS_CLOSED,
                    updated_by=user.id,
                    commit=False,
                )

            transition_customer_complaint(
                complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_IN_PROGRESS,
                updated_by=user.id,
                commit=False,
            )
            assert complaint.status == COMPLAINT_STATUS_IN_PROGRESS
            assert complaint.assigned_to == user.id

            with pytest.raises(CustomerComplaintError):
                transition_customer_complaint(
                    complaint.id,
                    branch_id=user.branch_id,
                    new_status=COMPLAINT_STATUS_RESOLVED,
                    updated_by=user.id,
                    commit=False,
                )

            transition_customer_complaint(
                complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_RESOLVED,
                updated_by=user.id,
                resolution_note="Sudah dikirim kompensasi porsi.",
                commit=False,
            )
            assert complaint.status == COMPLAINT_STATUS_RESOLVED
            assert complaint.resolved_by == user.id
            assert complaint.resolved_at is not None

            transition_customer_complaint(
                complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_CLOSED,
                updated_by=user.id,
                commit=False,
            )
            assert complaint.status == COMPLAINT_STATUS_CLOSED
            assert complaint.closed_by == user.id
            assert complaint.closed_at is not None
        finally:
            transaction.rollback()


def test_list_customer_complaints_is_branch_scoped(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, mandor = _complaint_fixture()
            other_user, other_client, other_mandor = _complaint_fixture()
            own = submit_customer_complaint(
                branch_id=user.branch_id,
                category=COMPLAINT_CATEGORY_LATE_DELIVERY,
                title="Delivery terlambat",
                description="Delivery terlambat dari jadwal.",
                submitted_by=user.id,
                client_id=client.id,
                mandor_id=mandor.id,
                commit=False,
            )
            other = submit_customer_complaint(
                branch_id=other_user.branch_id,
                category=COMPLAINT_CATEGORY_LATE_DELIVERY,
                title="Delivery terlambat branch lain",
                description="Delivery terlambat dari jadwal.",
                submitted_by=other_user.id,
                client_id=other_client.id,
                mandor_id=other_mandor.id,
                commit=False,
            )

            rows = list_customer_complaints(user.branch_id)

            assert own.id in {row.id for row in rows}
            assert other.id not in {row.id for row in rows}
        finally:
            transaction.rollback()
