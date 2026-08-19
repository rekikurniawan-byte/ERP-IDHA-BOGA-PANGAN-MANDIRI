from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account, Journal
from app.models.finance import BankAccount, CashBankTransaction, Invoice, InvoiceCollectionLog, Payment
from app.models.system import DigitalAttachment, Notification
from app.services.portal_mapping_service import PRINCIPAL_CLIENT
from app.services.portal_payment_creation_service import (
    PAYMENT_PROOF_PAYMENT_CREATED_TYPE,
    PortalPaymentCreationError,
    create_payment_from_verified_proof,
)
from app.services.portal_payment_proof_service import upload_portal_payment_proof
from app.services.portal_payment_verification_queue_service import decide_payment_proof
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_mapping,
    _create_user,
)
from tests.test_portal_payment_proof_service import _file_storage


def _ensure_account(code, name, account_type):
    account = Account.query.filter_by(account_code=code).first()
    if account:
        return account
    account = Account(
        account_code=code,
        account_name=name,
        account_type=account_type,
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def _create_invoice_journal(invoice, user_id):
    journal = Journal(
        journal_number=f"T-INV-JRN-{uuid4().hex[:10]}",
        journal_date=invoice.invoice_date,
        reference_type="INVOICE",
        reference_id=invoice.id,
        description=f"Test invoice journal for {invoice.invoice_number}",
        created_by=user_id,
    )
    db.session.add(journal)
    db.session.flush()
    return journal


def _create_payment_ready_invoice(portal_user):
    today = date.today()
    client, _, mandor, _ = _create_client_family(portal_user.branch, "PAYCREATE")
    _create_mapping(portal_user, PRINCIPAL_CLIENT, client=client)
    invoice = Invoice(
        branch_id=portal_user.branch_id,
        invoice_number=f"T-PAYCREATE-INV-{uuid4().hex[:10]}",
        invoice_date=today - timedelta(days=1),
        due_date=today + timedelta(days=7),
        period_start=today - timedelta(days=1),
        period_end=today - timedelta(days=1),
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor.id,
        total_amount=Decimal("100000"),
        paid_amount=Decimal("0"),
        remaining_amount=Decimal("100000"),
        status="OPEN",
        source_type="PORTAL_PAYMENT_CREATE_TEST",
        source_order_id=None,
        input_source="REALTIME",
        created_by=portal_user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    _create_invoice_journal(invoice, portal_user.id)
    return invoice


def _create_bank_account(branch):
    account = BankAccount(
        branch_id=branch.id,
        account_name="Test Payment Creation Bank",
        bank_name="Bank QA",
        account_number=f"T-PAYCREATE-BANK-{uuid4().hex[:10]}",
        coa_account_code="1002",
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    return account


def _setup_verified_proof():
    _ensure_account("1001", "Kas", "ASSET")
    _ensure_account("1002", "Bank 1", "ASSET")
    _ensure_account("1004", "Piutang Usaha", "ASSET")
    portal_user = _create_user("PORTAL_CLIENT")
    finance_user = _create_user("FINANCE", branch=portal_user.branch)
    invoice = _create_payment_ready_invoice(portal_user)
    bank_account = _create_bank_account(portal_user.branch)
    upload_result = upload_portal_payment_proof(
        portal_user,
        invoice_id=invoice.id,
        file_storage=_file_storage(),
        notes="Proof untuk payment creation",
        commit=False,
    )
    attachment = DigitalAttachment.query.get(upload_result["attachment_id"])
    decide_payment_proof(
        finance_user,
        attachment_id=attachment.id,
        decision="VERIFIED",
        notes="Verified untuk payment creation.",
        commit=False,
    )
    db.session.refresh(attachment)
    return finance_user, invoice, bank_account, attachment


def test_create_payment_from_verified_proof_posts_payment_journal_ledger_and_consumes_proof(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            finance_user, invoice, bank_account, attachment = _setup_verified_proof()
            payment_count_before = Payment.query.count()

            result = create_payment_from_verified_proof(
                finance_user,
                attachment_id=attachment.id,
                payment_date=date.today(),
                amount="60000",
                payment_method="TRANSFER",
                bank_account_id=bank_account.id,
                reference_number="PORTAL-PROOF-REF",
                notes="Payment dari proof verified.",
                idempotency_key=f"T-PAYCREATE-{uuid4().hex}",
                commit=False,
            )

            db.session.refresh(invoice)
            db.session.refresh(attachment)
            payment = Payment.query.get(result["payment_id"])

            assert Payment.query.count() == payment_count_before + 1
            assert payment.invoice_id == invoice.id
            assert payment.amount == Decimal("60000.00")
            assert invoice.status == "PARTIAL"
            assert invoice.paid_amount == Decimal("60000.00")
            assert invoice.remaining_amount == Decimal("40000.00")
            assert Journal.query.filter_by(reference_type="PAYMENT", reference_id=payment.id).first()
            assert CashBankTransaction.query.filter_by(reference_type="PAYMENT", reference_id=payment.id).first()
            assert InvoiceCollectionLog.query.filter_by(invoice_id=invoice.id, collection_status="PARTIAL").first()
            assert attachment.attachment_type == PAYMENT_PROOF_PAYMENT_CREATED_TYPE
            assert result["payment_created"] is True
            assert result["idempotent_replay"] is False
            notification = Notification.query.filter_by(
                notification_type="PORTAL_PAYMENT_CREATED",
                target_user_id=attachment.uploaded_by,
                reference_type="PAYMENT",
                reference_id=payment.id,
            ).first()
            assert notification is not None
            assert notification.branch_id == invoice.branch_id
            assert payment.payment_number in notification.title
            assert notification.action_url == f"/portal/invoices/{invoice.id}/payment"
        finally:
            transaction.rollback()


def test_create_payment_from_verified_proof_idempotency_replay_does_not_duplicate(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            finance_user, _, bank_account, attachment = _setup_verified_proof()
            key = f"T-PAYCREATE-{uuid4().hex}"

            first = create_payment_from_verified_proof(
                finance_user,
                attachment_id=attachment.id,
                payment_date=date.today(),
                amount="25000",
                payment_method="TRANSFER",
                bank_account_id=bank_account.id,
                reference_number="IDEMPOTENT-REF",
                notes="First call.",
                idempotency_key=key,
                commit=False,
            )
            payment_count_after_first = Payment.query.count()
            second = create_payment_from_verified_proof(
                finance_user,
                attachment_id=attachment.id,
                payment_date=date.today(),
                amount="25000",
                payment_method="TRANSFER",
                bank_account_id=bank_account.id,
                reference_number="IDEMPOTENT-REF",
                notes="First call.",
                idempotency_key=key,
                commit=False,
            )

            assert Payment.query.count() == payment_count_after_first
            assert second["payment_id"] == first["payment_id"]
            assert second["idempotent_replay"] is True
        finally:
            transaction.rollback()


def test_create_payment_from_verified_proof_rejects_overpayment(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            finance_user, _, bank_account, attachment = _setup_verified_proof()

            with pytest.raises(PortalPaymentCreationError):
                create_payment_from_verified_proof(
                    finance_user,
                    attachment_id=attachment.id,
                    payment_date=date.today(),
                    amount="150000",
                    payment_method="TRANSFER",
                    bank_account_id=bank_account.id,
                    reference_number="OVERPAY",
                    idempotency_key=f"T-PAYCREATE-{uuid4().hex}",
                    commit=False,
                )
        finally:
            transaction.rollback()


def test_create_payment_from_verified_proof_rejects_pending_proof(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            finance_user, invoice, bank_account, attachment = _setup_verified_proof()
            attachment.attachment_type = "PAYMENT_PROOF_PENDING"
            db.session.flush()

            with pytest.raises(PortalPaymentCreationError):
                create_payment_from_verified_proof(
                    finance_user,
                    attachment_id=attachment.id,
                    payment_date=date.today(),
                    amount="25000",
                    payment_method="TRANSFER",
                    bank_account_id=bank_account.id,
                    reference_number="PENDING",
                    idempotency_key=f"T-PAYCREATE-{uuid4().hex}",
                    commit=False,
                )
            db.session.refresh(invoice)
            assert invoice.paid_amount == Decimal("0.00")
        finally:
            transaction.rollback()
