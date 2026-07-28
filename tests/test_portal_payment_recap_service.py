from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.finance import Invoice, Payment
from app.services.portal_payment_recap_service import build_branch_receivable_recap, build_invoice_payment_recap
from tests.test_portal_financial_visibility_service import _create_user


def _invoice(user, *, total="100000", paid="0", remaining="100000", status="OPEN"):
    today = date.today()
    invoice = Invoice(
        branch_id=user.branch_id,
        invoice_number=f"T-RECAP-INV-{uuid4().hex[:10]}",
        invoice_date=today - timedelta(days=1),
        due_date=today + timedelta(days=7),
        period_start=today - timedelta(days=1),
        period_end=today - timedelta(days=1),
        bill_to_type="CLIENT",
        total_amount=Decimal(total),
        paid_amount=Decimal(paid),
        remaining_amount=Decimal(remaining),
        status=status,
        source_type="PORTAL_PAYMENT_RECAP_TEST",
        source_order_id=None,
        input_source="REALTIME",
        created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


def _payment(user, invoice, amount):
    payment = Payment(
        payment_number=f"T-RECAP-PAY-{uuid4().hex[:10]}",
        branch_id=user.branch_id,
        payment_date=date.today(),
        invoice_id=invoice.id,
        payment_method="TRANSFER",
        amount=Decimal(amount),
        reference_number=f"REF-{invoice.invoice_number}",
        received_by=user.id,
    )
    db.session.add(payment)
    db.session.flush()
    return payment


def test_invoice_payment_recap_accepts_valid_partial_invoice(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user, paid="40000", remaining="60000", status="PARTIAL")
            _payment(user, invoice, "40000")

            recap = build_invoice_payment_recap(invoice_id=invoice.id, branch_id=user.branch_id)

            assert recap["is_valid"] is True
            assert recap["payment_total"] == Decimal("40000.00")
            assert recap["expected_remaining"] == Decimal("60000.00")
            assert recap["active_receivable"] is True
        finally:
            transaction.rollback()


def test_invoice_payment_recap_accepts_valid_paid_invoice(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user, paid="100000", remaining="0", status="PAID")
            _payment(user, invoice, "100000")

            recap = build_invoice_payment_recap(invoice_id=invoice.id, branch_id=user.branch_id)

            assert recap["is_valid"] is True
            assert recap["active_receivable"] is False
        finally:
            transaction.rollback()


def test_invoice_payment_recap_flags_over_allocation(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user, paid="120000", remaining="0", status="PAID")
            _payment(user, invoice, "120000")

            recap = build_invoice_payment_recap(invoice_id=invoice.id, branch_id=user.branch_id)

            assert recap["is_valid"] is False
            assert recap["over_allocated"] is True
            assert any(row["name"] == "payment_not_over_invoice_total" and row["status"] == "FAIL" for row in recap["checks"])
        finally:
            transaction.rollback()


def test_invoice_payment_recap_flags_remaining_mismatch(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user, paid="25000", remaining="80000", status="PARTIAL")
            _payment(user, invoice, "25000")

            recap = build_invoice_payment_recap(invoice_id=invoice.id, branch_id=user.branch_id)

            assert recap["is_valid"] is False
            assert any(row["name"] == "remaining_vs_total_minus_payment" and row["status"] == "FAIL" for row in recap["checks"])
        finally:
            transaction.rollback()


def test_branch_receivable_recap_excludes_cancelled_invoice_from_active_total(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            active = _invoice(user, paid="10000", remaining="90000", status="PARTIAL")
            cancelled = _invoice(user, paid="0", remaining="0", status="CANCELLED")
            _payment(user, active, "10000")

            recap = build_branch_receivable_recap(branch_id=user.branch_id)
            row_by_id = {row["invoice_id"]: row for row in recap["rows"]}

            assert row_by_id[active.id]["active_receivable"] is True
            assert row_by_id[cancelled.id]["active_receivable"] is False
            assert recap["active_receivable_total"] == Decimal("90000.00")
        finally:
            transaction.rollback()
