from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.finance import BankAccount, CashBankTransaction, Invoice, Payment
from app.services.portal_cash_confirmation_service import build_branch_cash_confirmation_recap, build_customer_payment_cash_confirmation
from tests.test_portal_financial_visibility_service import _create_user


def _invoice(user):
    today = date.today()
    invoice = Invoice(
        branch_id=user.branch_id,
        invoice_number=f"T-CASHCONF-INV-{uuid4().hex[:10]}",
        invoice_date=today - timedelta(days=1),
        due_date=today + timedelta(days=7),
        period_start=today - timedelta(days=1),
        period_end=today - timedelta(days=1),
        bill_to_type="CLIENT",
        total_amount=Decimal("100000"),
        paid_amount=Decimal("50000"),
        remaining_amount=Decimal("50000"),
        status="PARTIAL",
        source_type="PORTAL_CASH_CONFIRMATION_TEST",
        input_source="REALTIME",
        created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


def _bank_account(user):
    account = BankAccount(
        branch_id=user.branch_id,
        account_name="Cash Confirmation Bank",
        bank_name="Bank QA",
        account_number=f"T-CASHCONF-BANK-{uuid4().hex[:10]}",
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def _payment(user, invoice, *, method="TRANSFER", amount="50000", bank_account_id=None):
    payment = Payment(
        payment_number=f"T-CASHCONF-PAY-{uuid4().hex[:10]}",
        branch_id=user.branch_id,
        payment_date=date.today(),
        invoice_id=invoice.id,
        bank_account_id=bank_account_id,
        payment_method=method,
        amount=Decimal(amount),
        reference_number=f"REF-{invoice.invoice_number}",
        received_by=user.id,
    )
    db.session.add(payment)
    db.session.flush()
    return payment


def _ledger(user, payment, *, amount=None, account_type=None, bank_account_id=None):
    ledger = CashBankTransaction(
        branch_id=user.branch_id,
        transaction_date=payment.payment_date,
        account_type=account_type or ("BANK" if payment.payment_method == "TRANSFER" else "CASH"),
        bank_account_id=bank_account_id,
        transaction_type="IN",
        amount=Decimal(amount) if amount is not None else payment.amount,
        description=f"Ledger for {payment.payment_number}",
        reference_type="PAYMENT",
        reference_id=payment.id,
        created_by=user.id,
    )
    db.session.add(ledger)
    db.session.flush()
    return ledger


def test_cash_confirmation_accepts_valid_transfer_ledger(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user)
            bank = _bank_account(user)
            payment = _payment(user, invoice, bank_account_id=bank.id)
            _ledger(user, payment, bank_account_id=bank.id)

            recap = build_customer_payment_cash_confirmation(payment_id=payment.id, branch_id=user.branch_id)

            assert recap["is_valid"] is True
            assert recap["ledger_count"] == 1
        finally:
            transaction.rollback()


def test_cash_confirmation_accepts_valid_cash_ledger(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user)
            payment = _payment(user, invoice, method="CASH", bank_account_id=None)
            _ledger(user, payment, account_type="CASH", bank_account_id=None)

            recap = build_customer_payment_cash_confirmation(payment_id=payment.id, branch_id=user.branch_id)

            assert recap["is_valid"] is True
        finally:
            transaction.rollback()


def test_cash_confirmation_flags_missing_ledger(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user)
            payment = _payment(user, invoice, method="CASH")

            recap = build_customer_payment_cash_confirmation(payment_id=payment.id, branch_id=user.branch_id)

            assert recap["is_valid"] is False
            assert recap["checks"][0]["name"] == "ledger_exists"
        finally:
            transaction.rollback()


def test_cash_confirmation_flags_duplicate_ledger(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user)
            payment = _payment(user, invoice, method="CASH")
            _ledger(user, payment, account_type="CASH")
            _ledger(user, payment, account_type="CASH")

            recap = build_customer_payment_cash_confirmation(payment_id=payment.id, branch_id=user.branch_id)

            assert recap["is_valid"] is False
            assert recap["ledger_count"] == 2
        finally:
            transaction.rollback()


def test_branch_cash_confirmation_recap_flags_amount_mismatch(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("FINANCE")
            invoice = _invoice(user)
            payment = _payment(user, invoice, method="CASH")
            _ledger(user, payment, amount="40000", account_type="CASH")

            recap = build_branch_cash_confirmation_recap(branch_id=user.branch_id)

            assert recap["is_valid"] is False
            assert recap["invalid_count"] == 1
            assert any(
                check["name"] == "ledger_amount_matches_payment" and check["status"] == "FAIL"
                for check in recap["rows"][0]["checks"]
            )
        finally:
            transaction.rollback()
