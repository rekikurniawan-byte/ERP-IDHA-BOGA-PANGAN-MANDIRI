from datetime import date, timedelta

from app.extensions import db
from app.models.system import Notification
from app.services.customer_contract_expiry_notification_service import (
    CONTRACT_EXPIRY_NOTIFICATION_TYPE,
    build_contract_expiry_candidates,
    generate_contract_expiry_notifications,
)
from app.services.customer_contract_service import (
    CONTRACT_STATUS_ACTIVE,
    CONTRACT_STATUS_DRAFT,
    CONTRACT_STATUS_SUPERSEDED,
    create_customer_contract,
)
from tests.test_customer_contract_service import _contract_fixture


def _create_contract(user, client, pic, *, title, end_offset, status=CONTRACT_STATUS_ACTIVE):
    create_status = status if status in {CONTRACT_STATUS_ACTIVE, CONTRACT_STATUS_DRAFT} else CONTRACT_STATUS_ACTIVE
    contract = create_customer_contract(
        branch_id=user.branch_id,
        client_id=client.id,
        client_pic_id=pic.id,
        title=title,
        start_date=date.today() - timedelta(days=10),
        end_date=date.today() + timedelta(days=end_offset),
        payment_terms="NET 14",
        credit_limit="1000000",
        created_by=user.id,
        status=create_status,
        commit=False,
    )
    if status != create_status:
        contract.status = status
        db.session.flush()
    return contract


def test_build_contract_expiry_candidates_is_read_only_and_filters_active_window(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()
            due_soon = _create_contract(user, client, pic, title="Due Soon", end_offset=5)
            overdue = _create_contract(user, client, pic, title="Overdue", end_offset=-1)
            far = _create_contract(user, client, pic, title="Far Future", end_offset=90)
            draft = _create_contract(user, client, pic, title="Draft Contract", end_offset=5, status=CONTRACT_STATUS_DRAFT)
            superseded = _create_contract(user, client, pic, title="Superseded Contract", end_offset=5, status=CONTRACT_STATUS_SUPERSEDED)

            candidates = build_contract_expiry_candidates(branch_id=user.branch_id, as_of_date=date.today(), due_days=30)

            candidate_ids = {row["contract_id"] for row in candidates}
            assert due_soon.id in candidate_ids
            assert overdue.id in candidate_ids
            assert far.id not in candidate_ids
            assert draft.id not in candidate_ids
            assert superseded.id not in candidate_ids
            assert overdue.status == CONTRACT_STATUS_ACTIVE
            assert due_soon.status == CONTRACT_STATUS_ACTIVE
            assert any(row["priority"] == "CRITICAL" for row in candidates if row["contract_id"] == overdue.id)
        finally:
            transaction.rollback()


def test_generate_contract_expiry_notifications_is_idempotent(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()
            contract = _create_contract(user, client, pic, title="Notify Contract", end_offset=7)

            first = generate_contract_expiry_notifications(
                branch_id=user.branch_id,
                as_of_date=date.today(),
                due_days=30,
                generated_by=user.id,
                commit=False,
            )
            second = generate_contract_expiry_notifications(
                branch_id=user.branch_id,
                as_of_date=date.today(),
                due_days=30,
                generated_by=user.id,
                commit=False,
            )

            notifications = Notification.query.filter_by(
                branch_id=user.branch_id,
                notification_type=CONTRACT_EXPIRY_NOTIFICATION_TYPE,
                reference_id=contract.id,
            ).all()
            assert first["created"] == 1
            assert second["created"] == 0
            assert second["updated"] == 1
            assert len(notifications) == 1
            assert notifications[0].target_role == "ADMIN"
            assert notifications[0].reference_type == "CUSTOMER_CONTRACT"
            assert contract.status == CONTRACT_STATUS_ACTIVE
        finally:
            transaction.rollback()


def test_generate_contract_expiry_notifications_resolves_stale_generated_rows(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()
            contract = _create_contract(user, client, pic, title="Resolve Contract", end_offset=7)

            generate_contract_expiry_notifications(
                branch_id=user.branch_id,
                as_of_date=date.today(),
                due_days=30,
                generated_by=user.id,
                commit=False,
            )
            notification = Notification.query.filter_by(
                branch_id=user.branch_id,
                notification_type=CONTRACT_EXPIRY_NOTIFICATION_TYPE,
                reference_id=contract.id,
            ).one()
            assert notification.status == "UNREAD"

            contract.end_date = date.today() + timedelta(days=90)
            result = generate_contract_expiry_notifications(
                branch_id=user.branch_id,
                as_of_date=date.today(),
                due_days=30,
                generated_by=user.id,
                commit=False,
            )

            assert result["active"] == 0
            assert result["resolved"] == 1
            assert notification.status == "RESOLVED"
            assert contract.status == CONTRACT_STATUS_ACTIVE
        finally:
            transaction.rollback()
