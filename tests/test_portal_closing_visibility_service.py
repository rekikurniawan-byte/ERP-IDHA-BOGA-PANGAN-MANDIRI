from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.accounting import PeriodClosing
from app.models.master import Mandor
from app.services.portal_closing_visibility_service import build_portal_closing_visibility
from app.services.portal_mapping_service import PRINCIPAL_CLIENT, PRINCIPAL_DELEGATE, PRINCIPAL_MANDOR
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
)
from tests.test_portal_debt_visibility_service import _create_worker_debt
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_invoice,
    _create_mapping,
    _create_user,
)


def _closing_number():
    return f"T-PCV-CLS-{uuid4().hex[:10]}"


def _create_period_closing(user, *, year=2099, month=1):
    closing = PeriodClosing(
        branch_id=user.branch_id,
        closing_number=_closing_number(),
        period_year=year,
        period_month=month,
        period_start=date(year, month, 1),
        period_end=date(year, month, 31),
        closing_date=date(year, month, 31),
        revenue_total=Decimal("999999999"),
        expense_total=Decimal("888888888"),
        net_income=Decimal("111111111"),
        retained_earnings_account_code="3002",
        status="POSTED",
        notes="Portal closing visibility test",
        created_by=user.id,
    )
    db.session.add(closing)
    db.session.flush()
    return closing


def test_portal_client_closing_visibility_summarizes_owned_period_data_without_internal_closing_values(app, monkeypatch):
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(AssertionError("read model must not commit")))
    monkeypatch.setattr(db.session, "rollback", lambda: (_ for _ in ()).throw(AssertionError("read model must not rollback")))

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, pic, mandor, _ = _create_client_family(user.branch, "CLOSING")
            other_client, _, other_mandor, _ = _create_client_family(user.branch, "CLOSINGOTHER")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=client, mandor=mandor, client_pic=pic)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=other_client, mandor=other_mandor)
            _create_worker_debt(user, mandor, amount="30000", paid="10000", status="PARTIAL", sale_date=date(2099, 1, 15))
            _create_period_closing(user)

            visibility = build_portal_closing_visibility(user, year=2099, month=1)

            assert visibility["allowed"] is True
            assert visibility["closing"]["is_closed"] is True
            assert visibility["closing"]["status"] == "POSTED"
            assert "closing_number" not in visibility["closing"]
            assert "journal_id" not in visibility["closing"]
            assert "revenue_total" not in visibility["closing"]
            assert "expense_total" not in visibility["closing"]
            assert "net_income" not in visibility["closing"]
            assert visibility["totals"]["invoice_count"] == 1
            assert visibility["totals"]["invoice_total"] == Decimal("100000")
            assert visibility["totals"]["invoice_remaining"] == Decimal("75000")
            assert visibility["totals"]["payment_count"] == 1
            assert visibility["totals"]["payment_amount"] == Decimal("25000")
            assert visibility["totals"]["worker_debt_count"] == 1
            assert visibility["totals"]["worker_debt_remaining"] == Decimal("20000")
        finally:
            transaction.rollback()


def test_portal_mandor_closing_visibility_does_not_summarize_sibling_mandor(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_MANDOR)
            client, _, mandor, _ = _create_client_family(user.branch, "CLOSEMANDOR")
            sibling_mandor = Mandor(
                branch_id=user.branch_id,
                client_id=client.id,
                name="Closing Sibling Mandor",
                phone="0800000999",
                is_active=True,
            )
            db.session.add(sibling_mandor)
            db.session.flush()
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=mandor)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=client, mandor=mandor)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=client, mandor=sibling_mandor)
            _create_worker_debt(user, mandor, sale_date=date(2099, 1, 15))
            _create_worker_debt(user, sibling_mandor, sale_date=date(2099, 1, 15))

            visibility = build_portal_closing_visibility(user, year=2099, month=1)

            assert visibility["totals"]["invoice_count"] == 1
            assert visibility["totals"]["payment_count"] == 1
            assert visibility["totals"]["worker_debt_count"] == 1
        finally:
            transaction.rollback()


def test_portal_delegate_closing_visibility_stays_on_delegated_location_mandor(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_DELEGATE)
            client, _, mandor, location = _create_client_family(user.branch, "CLOSEDEL")
            sibling_mandor = Mandor(
                branch_id=user.branch_id,
                client_id=client.id,
                name="Closing Delegate Sibling",
                phone="0800000888",
                is_active=True,
            )
            db.session.add(sibling_mandor)
            db.session.flush()
            _create_mapping(user, PRINCIPAL_DELEGATE, location=location)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=client, mandor=mandor)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=client, mandor=sibling_mandor)
            _create_worker_debt(user, mandor, sale_date=date(2099, 1, 15))
            _create_worker_debt(user, sibling_mandor, sale_date=date(2099, 1, 15))

            visibility = build_portal_closing_visibility(user, year=2099, month=1)

            assert visibility["totals"]["invoice_count"] == 1
            assert visibility["totals"]["worker_debt_count"] == 1
        finally:
            transaction.rollback()


def test_portal_customer_closing_visibility_is_blocked(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "CLOSECUSTOMER")
            _create_mapping(user, PRINCIPAL_DELEGATE, client=client, mandor=mandor, location=location)
            _create_invoice(user, invoice_number=f"T-PCV-INV-{uuid4().hex[:10]}", client=client, mandor=mandor)

            visibility = build_portal_closing_visibility(user, year=2099, month=1)

            assert visibility["allowed"] is False
            assert visibility["scope_mode"] == "PORTAL_CUSTOMER_CLOSING_VISIBILITY_BLOCKED"
            assert visibility["totals"]["invoice_count"] == 0
            assert visibility["closing"]["is_closed"] is False
        finally:
            transaction.rollback()
