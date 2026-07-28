from app.extensions import db
from app.models.system import Notification
from app.services.customer_complaint_notification_service import (
    COMPLAINT_NOTIFICATION_TYPE,
    build_customer_complaint_queue,
    generate_customer_complaint_notifications,
)
from app.services.customer_complaint_service import (
    COMPLAINT_CATEGORY_LATE_DELIVERY,
    COMPLAINT_STATUS_CLOSED,
    COMPLAINT_STATUS_IN_PROGRESS,
    COMPLAINT_STATUS_RESOLVED,
    submit_customer_complaint,
    transition_customer_complaint,
)
from tests.test_portal_financial_visibility_service import _create_client_family, _create_user


def _complaint_fixture():
    user = _create_user("ADMIN")
    client, _, mandor, _ = _create_client_family(user.branch, "CMPNOTIF")
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
    return user, complaint


def test_build_customer_complaint_queue_lists_only_active_branch_complaints(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, open_complaint = _complaint_fixture()
            other_user, other_complaint = _complaint_fixture()
            transition_customer_complaint(
                open_complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_IN_PROGRESS,
                updated_by=user.id,
                commit=False,
            )

            rows = build_customer_complaint_queue(branch_id=user.branch_id)

            row_ids = {row["complaint_id"] for row in rows}
            assert open_complaint.id in row_ids
            assert other_complaint.id not in row_ids
            assert rows[0]["status"] == COMPLAINT_STATUS_IN_PROGRESS
            assert rows[0]["client_name"] != "-"
            assert other_user.branch_id != user.branch_id
        finally:
            transaction.rollback()


def test_generate_customer_complaint_notifications_is_idempotent(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, complaint = _complaint_fixture()

            first = generate_customer_complaint_notifications(branch_id=user.branch_id, generated_by=user.id, commit=False)
            second = generate_customer_complaint_notifications(branch_id=user.branch_id, generated_by=user.id, commit=False)

            notifications = Notification.query.filter_by(
                branch_id=user.branch_id,
                notification_type=COMPLAINT_NOTIFICATION_TYPE,
                reference_id=complaint.id,
            ).all()

            assert first["created"] == 1
            assert second["created"] == 0
            assert second["updated"] == 1
            assert len(notifications) == 1
            assert notifications[0].target_role == "ADMIN"
            assert notifications[0].reference_type == "CUSTOMER_COMPLAINT"
            assert complaint.status != COMPLAINT_STATUS_RESOLVED
        finally:
            transaction.rollback()


def test_generate_customer_complaint_notifications_resolves_closed_items(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, complaint = _complaint_fixture()
            generate_customer_complaint_notifications(branch_id=user.branch_id, generated_by=user.id, commit=False)
            notification = Notification.query.filter_by(
                branch_id=user.branch_id,
                notification_type=COMPLAINT_NOTIFICATION_TYPE,
                reference_id=complaint.id,
            ).one()
            assert notification.status == "UNREAD"

            transition_customer_complaint(
                complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_IN_PROGRESS,
                updated_by=user.id,
                commit=False,
            )
            transition_customer_complaint(
                complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_RESOLVED,
                updated_by=user.id,
                resolution_note="Selesai ditangani.",
                commit=False,
            )
            transition_customer_complaint(
                complaint.id,
                branch_id=user.branch_id,
                new_status=COMPLAINT_STATUS_CLOSED,
                updated_by=user.id,
                commit=False,
            )

            result = generate_customer_complaint_notifications(branch_id=user.branch_id, generated_by=user.id, commit=False)

            assert result["active"] == 0
            assert result["resolved"] == 1
            assert notification.status == "RESOLVED"
            assert complaint.status == COMPLAINT_STATUS_CLOSED
        finally:
            transaction.rollback()
