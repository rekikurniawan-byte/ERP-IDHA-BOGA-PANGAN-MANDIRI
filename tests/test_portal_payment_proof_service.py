from io import BytesIO
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.finance import Payment
from app.models.system import DigitalAttachment, Notification
from app.services.digital_attachment_service import AttachmentValidationError
from app.services.portal_mapping_service import PRINCIPAL_CLIENT, PRINCIPAL_MANDOR
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_PENDING_TYPE,
    PORTAL_PAYMENT_MODULE,
    PortalPaymentProofError,
    list_pending_portal_payment_proofs,
    upload_portal_payment_proof,
)
from app.services.user_management_service import ROLE_PORTAL_CLIENT, ROLE_PORTAL_CUSTOMER, ROLE_PORTAL_SUBCLIENT
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_invoice,
    _create_mapping,
    _create_user,
)


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF\n"


def _file_storage(filename="proof.pdf", payload=PDF_BYTES, content_type="application/pdf"):
    return FileStorage(
        stream=BytesIO(payload),
        filename=filename,
        content_type=content_type,
    )


def test_upload_portal_payment_proof_creates_private_attachment_without_payment_mutation(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "UPROOF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            invoice = _create_invoice(
                user,
                invoice_number=f"T-UPROOF-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
                total="120000",
                paid="0",
                remaining="120000",
                status="OPEN",
            )
            original_paid = invoice.paid_amount
            original_remaining = invoice.remaining_amount
            payment_count_before = Payment.query.count()

            result = upload_portal_payment_proof(
                user,
                invoice_id=invoice.id,
                file_storage=_file_storage(),
                notes="Transfer dari portal",
                commit=False,
            )

            db.session.refresh(invoice)
            attachment = DigitalAttachment.query.get(result["attachment_id"])

            assert result["uploaded"] is True
            assert result["status"] == "PENDING_FINANCE_VERIFICATION"
            assert result["payment_created"] is False
            assert result["invoice_marked_paid"] is False
            assert result["mutation_scope"] == "ATTACHMENT_ONLY"
            assert attachment.module == PORTAL_PAYMENT_MODULE
            assert attachment.reference_type == "INVOICE"
            assert attachment.reference_id == invoice.id
            assert attachment.attachment_type == PAYMENT_PROOF_PENDING_TYPE
            assert attachment.mime_type == "application/pdf"
            assert attachment.notes.startswith("PENDING_FINANCE_VERIFICATION")
            assert Payment.query.count() == payment_count_before
            assert invoice.paid_amount == original_paid
            assert invoice.remaining_amount == original_remaining
            assert list_pending_portal_payment_proofs(branch_id=user.branch_id)[0].id == attachment.id
            # Addressed to ADMIN: FINANCE is retired and ADMIN verifies proofs.
            notification = Notification.query.filter_by(
                notification_type="PORTAL_PAYMENT_PROOF",
                target_role="ADMIN",
                reference_type="INVOICE",
                reference_id=invoice.id,
            ).first()
            assert notification is not None
            assert notification.branch_id == user.branch_id
            assert notification.action_url == "/finance/portal-payment-proofs"
        finally:
            transaction.rollback()


def test_upload_portal_payment_proof_rejects_invoice_outside_ownership(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_SUBCLIENT)
            client, _, owned_mandor, _ = _create_client_family(user.branch, "OWNUPROOF")
            _, _, other_mandor, _ = _create_client_family(user.branch, "OTHERUPROOF")
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=owned_mandor)
            other_invoice = _create_invoice(
                user,
                invoice_number=f"T-UPROOF-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=other_mandor,
                paid="0",
                remaining="100000",
            )
            attachment_count_before = DigitalAttachment.query.filter_by(module=PORTAL_PAYMENT_MODULE).count()

            with pytest.raises(PortalPaymentProofError):
                upload_portal_payment_proof(
                    user,
                    invoice_id=other_invoice.id,
                    file_storage=_file_storage(),
                    commit=False,
                )

            assert DigitalAttachment.query.filter_by(module=PORTAL_PAYMENT_MODULE).count() == attachment_count_before
        finally:
            transaction.rollback()


def test_upload_portal_payment_proof_rejects_cancelled_invoice(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "CANCELUPROOF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            invoice = _create_invoice(
                user,
                invoice_number=f"T-UPROOF-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
                paid="0",
                remaining="100000",
                status="CANCELLED",
            )

            with pytest.raises(PortalPaymentProofError):
                upload_portal_payment_proof(
                    user,
                    invoice_id=invoice.id,
                    file_storage=_file_storage(),
                    commit=False,
                )
        finally:
            transaction.rollback()


def test_upload_portal_payment_proof_rejects_customer_role(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, _ = _create_client_family(user.branch, "CUSTOMERUPROOF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            invoice = _create_invoice(
                user,
                invoice_number=f"T-UPROOF-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
                paid="0",
                remaining="100000",
            )

            with pytest.raises(PortalPaymentProofError):
                upload_portal_payment_proof(
                    user,
                    invoice_id=invoice.id,
                    file_storage=_file_storage(),
                    commit=False,
                )
        finally:
            transaction.rollback()


def test_upload_portal_payment_proof_rejects_unsafe_html_payload(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "HTMLUPROOF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            invoice = _create_invoice(
                user,
                invoice_number=f"T-UPROOF-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
                paid="0",
                remaining="100000",
            )

            with pytest.raises(AttachmentValidationError):
                upload_portal_payment_proof(
                    user,
                    invoice_id=invoice.id,
                    file_storage=_file_storage(filename="proof.pdf", payload=b"<script>alert(1)</script>"),
                    commit=False,
                )
        finally:
            transaction.rollback()
