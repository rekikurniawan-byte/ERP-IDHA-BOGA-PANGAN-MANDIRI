from datetime import date
from decimal import Decimal
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.canteen import CanteenSale, DebtPayment, WorkerDebt
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User, Worker
from app.models.system import PortalUserMapping
from app.services.portal_debt_visibility_service import build_portal_worker_debt_read_model
from app.services.portal_mapping_service import PRINCIPAL_CLIENT, PRINCIPAL_DELEGATE, PRINCIPAL_MANDOR
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
)


def _suffix():
    return uuid4().hex[:10]


def _create_user(role, branch=None):
    suffix = _suffix()
    if not branch:
        branch = Branch(
            code=f"T-PDV-BR-{suffix}",
            name="Test Portal Debt Branch",
            address="Test",
            phone="0800000000",
            is_active=True,
        )
        db.session.add(branch)
        db.session.flush()

    user = User(
        branch_id=branch.id,
        full_name=f"Test Portal Debt {role}",
        username=f"portal-debt-{role.lower()}-{suffix}",
        password_hash=generate_password_hash("portal-debt-password"),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _create_client_and_mandor(branch, prefix):
    suffix = _suffix()
    client = Client(
        client_code=f"{prefix}-CLIENT-{suffix}",
        name=f"{prefix} Client",
        address="Test",
        phone="0800000001",
        is_active=True,
    )
    db.session.add(client)
    db.session.flush()
    mandor = Mandor(
        branch_id=branch.id,
        client_id=client.id,
        name=f"{prefix} Mandor",
        phone="0800000002",
        is_active=True,
    )
    db.session.add(mandor)
    db.session.flush()
    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name=f"{prefix} Location",
        description="Test",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return client, mandor, location


def _create_mapping(user, principal_type, *, client=None, mandor=None, location=None):
    mapping = PortalUserMapping(
        user_id=user.id,
        principal_type=principal_type,
        client_id=client.id if client else None,
        mandor_id=mandor.id if mandor else None,
        delivery_location_id=location.id if location else None,
        access_level="READ_ONLY",
        is_active=True,
    )
    db.session.add(mapping)
    db.session.flush()
    return mapping


def _create_worker_debt(user, mandor, *, amount="20000", paid="5000", status="PARTIAL"):
    suffix = _suffix()
    worker = Worker(
        mandor_id=mandor.id,
        worker_code=f"T-PDV-WORKER-{suffix}",
        full_name=f"T PDV Worker {suffix}",
        phone="0800000003",
        status="ACTIVE",
    )
    db.session.add(worker)
    db.session.flush()
    sale = CanteenSale(
        branch_id=user.branch_id,
        sale_date=date(2099, 2, 1),
        sale_type="DEBT",
        payment_method="DEBT",
        buyer_type="WORKER",
        buyer_name=worker.full_name,
        total_amount=Decimal(amount),
        notes="Portal debt visibility test",
        created_by=user.id,
    )
    db.session.add(sale)
    db.session.flush()
    debt = WorkerDebt(
        branch_id=user.branch_id,
        worker_id=worker.id,
        sale_id=sale.id,
        debt_amount=Decimal(amount),
        status=status,
    )
    db.session.add(debt)
    db.session.flush()
    paid_amount = Decimal(paid)
    if paid_amount > 0:
        db.session.add(
            DebtPayment(
                worker_debt_id=debt.id,
                payment_date=date(2099, 2, 2),
                amount=paid_amount,
                payment_method="CASH",
                payment_reference=f"REF-{suffix}",
                created_by=user.id,
            )
        )
        db.session.flush()
    return debt


def _debt_ids(rows):
    return {row["worker_debt_id"] for row in rows}


def test_portal_client_worker_debt_read_model_returns_client_mandor_debts(app, monkeypatch):
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(AssertionError("read model must not commit")))
    monkeypatch.setattr(db.session, "rollback", lambda: (_ for _ in ()).throw(AssertionError("read model must not rollback")))

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            owned_client, owned_mandor, _ = _create_client_and_mandor(user.branch, "OWN")
            other_client, other_mandor, _ = _create_client_and_mandor(user.branch, "OTHER")
            _create_mapping(user, PRINCIPAL_CLIENT, client=owned_client)

            owned_debt = _create_worker_debt(user, owned_mandor)
            other_debt = _create_worker_debt(user, other_mandor)

            read_model = build_portal_worker_debt_read_model(user)

            assert read_model["allowed"] is True
            assert _debt_ids(read_model["debts"]) == {owned_debt.id}
            assert other_debt.id not in _debt_ids(read_model["debts"])
            assert read_model["totals"]["debt_count"] == 1
            assert read_model["totals"]["debt_amount"] == Decimal("20000")
            assert read_model["totals"]["paid_amount"] == Decimal("5000")
            assert read_model["totals"]["active_remaining_amount"] == Decimal("15000")
        finally:
            transaction.rollback()


def test_portal_mandor_worker_debt_read_model_does_not_show_sibling_mandor_debt(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_MANDOR)
            client, owned_mandor, _ = _create_client_and_mandor(user.branch, "MANDOR")
            sibling_mandor = Mandor(
                branch_id=user.branch_id,
                client_id=client.id,
                name="Sibling Mandor",
                phone="0800000099",
                is_active=True,
            )
            db.session.add(sibling_mandor)
            db.session.flush()
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=owned_mandor)

            owned_debt = _create_worker_debt(user, owned_mandor)
            sibling_debt = _create_worker_debt(user, sibling_mandor)

            read_model = build_portal_worker_debt_read_model(user)

            assert _debt_ids(read_model["debts"]) == {owned_debt.id}
            assert sibling_debt.id not in _debt_ids(read_model["debts"])
        finally:
            transaction.rollback()


def test_portal_delegate_location_worker_debt_scope_stays_on_delegated_mandor(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_DELEGATE)
            client, delegated_mandor, delegated_location = _create_client_and_mandor(user.branch, "DELEGATED")
            sibling_mandor = Mandor(
                branch_id=user.branch_id,
                client_id=client.id,
                name="Sibling Delegate Debt Mandor",
                phone="0800000098",
                is_active=True,
            )
            db.session.add(sibling_mandor)
            db.session.flush()
            _create_mapping(user, PRINCIPAL_DELEGATE, location=delegated_location)

            delegated_debt = _create_worker_debt(user, delegated_mandor)
            sibling_debt = _create_worker_debt(user, sibling_mandor)

            read_model = build_portal_worker_debt_read_model(user)

            assert _debt_ids(read_model["debts"]) == {delegated_debt.id}
            assert sibling_debt.id not in _debt_ids(read_model["debts"])
        finally:
            transaction.rollback()


def test_portal_customer_worker_debt_visibility_is_blocked(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, mandor, location = _create_client_and_mandor(user.branch, "CUSTOMER")
            _create_mapping(user, PRINCIPAL_DELEGATE, client=client, mandor=mandor, location=location)
            _create_worker_debt(user, mandor)

            read_model = build_portal_worker_debt_read_model(user)

            assert read_model["allowed"] is False
            assert read_model["scope_mode"] == "PORTAL_CUSTOMER_DEBT_BLOCKED"
            assert read_model["debts"] == []
            assert read_model["totals"]["debt_count"] == 0
        finally:
            transaction.rollback()


def test_paid_worker_debt_is_visible_but_excluded_from_active_remaining(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_MANDOR)
            _, mandor, _ = _create_client_and_mandor(user.branch, "PAID")
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=mandor)

            active_debt = _create_worker_debt(user, mandor, amount="30000", paid="10000", status="PARTIAL")
            paid_debt = _create_worker_debt(user, mandor, amount="20000", paid="20000", status="PAID")

            read_model = build_portal_worker_debt_read_model(user)
            rows_by_id = {row["worker_debt_id"]: row for row in read_model["debts"]}

            assert rows_by_id[active_debt.id]["active_debt"] is True
            assert rows_by_id[paid_debt.id]["active_debt"] is False
            assert read_model["totals"]["debt_count"] == 2
            assert read_model["totals"]["active_debt_count"] == 1
            assert read_model["totals"]["remaining_amount"] == Decimal("20000")
            assert read_model["totals"]["active_remaining_amount"] == Decimal("20000")
        finally:
            transaction.rollback()
