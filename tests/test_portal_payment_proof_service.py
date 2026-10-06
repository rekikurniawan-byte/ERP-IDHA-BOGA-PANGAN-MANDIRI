from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.finance import Payment
from app.models.system import DigitalAttachment, Notification, PortalOrderDraft, PortalPaymentProofClaim
from app.services.digital_attachment_service import AttachmentValidationError
from app.services.portal_mapping_service import PRINCIPAL_CLIENT, PRINCIPAL_MANDOR
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_PENDING_TYPE,
    PORTAL_PAYMENT_MODULE,
    PortalPaymentProofError,
    upload_portal_order_draft_payment_proof,
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


def _create_draft_order(user, client, mandor, location):
    draft = PortalOrderDraft(
        user_id=user.id,
        branch_id=user.branch_id,
        client_id=client.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        order_date=date.today() + timedelta(days=2),
        meal_type="LUNCH",
        portion_qty=10,
        price_per_portion=Decimal("25000"),
        price_source="STANDAR",
        delivery_fee=Decimal("15000"),
        idempotency_key=uuid4().hex,
        status="PENDING_ADMIN_CONFIRMATION",
    )
    db.session.add(draft)
    db.session.flush()
    return draft


def test_upload_draft_payment_proof_with_claim_saves_claim_row(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "DCLAIM")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            draft = _create_draft_order(user, client, mandor, location)

            res = upload_portal_order_draft_payment_proof(
                user,
                draft_id=draft.id,
                file_storage=_file_storage(filename="bukti_klaim.pdf", payload=PDF_BYTES + b"%claim1"),
                notes="Catatan transfer",
                claimed_amount="265000",
                sender_name="Budi Santoso",
                transfer_reference="TRX12345",
                commit=False,
            )

            assert res["uploaded"] is True
            claim = PortalPaymentProofClaim.query.filter_by(attachment_id=res["attachment_id"]).first()
            assert claim is not None
            assert claim.claimed_amount == Decimal("265000.00")
            assert claim.sender_name == "Budi Santoso"
            assert claim.transfer_reference == "TRX12345"
            assert claim.branch_id == user.branch_id
        finally:
            transaction.rollback()


def test_upload_draft_payment_proof_duplicate_file_rejected_and_cleaned(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        user = _create_user(ROLE_PORTAL_CUSTOMER)
        client, _, mandor, location = _create_client_family(user.branch, "DUPFILE")
        _create_mapping(user, PRINCIPAL_CLIENT, client=client)
        draft1 = _create_draft_order(user, client, mandor, location)
        draft2 = _create_draft_order(user, client, mandor, location)
        db.session.commit()

        # Upload first file with commit=True (normal flow)
        payload = PDF_BYTES + b"%identical_file_payload"
        res1 = upload_portal_order_draft_payment_proof(
            user,
            draft_id=draft1.id,
            file_storage=_file_storage(filename="file_pertama.pdf", payload=payload),
            commit=True,
        )
        assert res1["uploaded"] is True

        att1 = db.session.get(DigitalAttachment, res1["attachment_id"])
        att_count_before = DigitalAttachment.query.count()
        files_before = list(tmp_path.rglob("*.pdf"))
        assert len(files_before) >= 1

        # Upload exact same file payload for draft2
        with pytest.raises(PortalPaymentProofError, match="sudah pernah diunggah sebelumnya"):
            upload_portal_order_draft_payment_proof(
                user,
                draft_id=draft2.id,
                file_storage=_file_storage(filename="file_kedua.pdf", payload=payload),
                commit=True,
            )

        # No new attachment created
        assert DigitalAttachment.query.count() == att_count_before
        # Upload directory has no leftover file from failed upload
        files_after = list(tmp_path.rglob("*.pdf"))
        assert len(files_after) == len(files_before)


def test_upload_draft_payment_proof_rejected_if_already_pending(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "PENDINGPROOF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            draft = _create_draft_order(user, client, mandor, location)

            # Bukti pertama
            upload_portal_order_draft_payment_proof(
                user,
                draft_id=draft.id,
                file_storage=_file_storage(filename="first.pdf", payload=PDF_BYTES + b"%first"),
                commit=False,
            )

            # Bukti kedua saat bukti pertama masih pending -> tolak
            with pytest.raises(PortalPaymentProofError, match="Bukti sebelumnya masih diperiksa"):
                upload_portal_order_draft_payment_proof(
                    user,
                    draft_id=draft.id,
                    file_storage=_file_storage(filename="second.pdf", payload=PDF_BYTES + b"%second"),
                    commit=False,
                )
        finally:
            transaction.rollback()


def test_upload_draft_payment_proof_allowed_after_previous_rejected(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "REJPROOF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            draft = _create_draft_order(user, client, mandor, location)

            res1 = upload_portal_order_draft_payment_proof(
                user,
                draft_id=draft.id,
                file_storage=_file_storage(filename="first_rej.pdf", payload=PDF_BYTES + b"%first_rej"),
                commit=False,
            )
            # Admin menolak bukti
            att1 = db.session.get(DigitalAttachment, res1["attachment_id"])
            att1.attachment_type = "PAYMENT_PROOF_REJECTED"
            db.session.flush()

            # Upload bukti baru sekarang harus berhasil
            res2 = upload_portal_order_draft_payment_proof(
                user,
                draft_id=draft.id,
                file_storage=_file_storage(filename="second_ok.pdf", payload=PDF_BYTES + b"%second_ok"),
                commit=False,
            )
            assert res2["uploaded"] is True
            assert res2["attachment_id"] != res1["attachment_id"]
        finally:
            transaction.rollback()


def test_upload_draft_payment_proof_duplicate_reference_rejected(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "DUPREF")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            draft1 = _create_draft_order(user, client, mandor, location)
            draft2 = _create_draft_order(user, client, mandor, location)

            # Bukti 1 dengan referensi "TRX-REF-777"
            upload_portal_order_draft_payment_proof(
                user,
                draft_id=draft1.id,
                file_storage=_file_storage(filename="ref1.pdf", payload=PDF_BYTES + b"%ref1"),
                claimed_amount="150000",
                sender_name="Pengirim 1",
                transfer_reference="TRX-REF-777",
                commit=False,
            )

            # Bukti 2 pada draft 2 dengan referensi sama (case insensitive / uppercase)
            with pytest.raises(PortalPaymentProofError, match="No. referensi ini sudah dipakai"):
                upload_portal_order_draft_payment_proof(
                    user,
                    draft_id=draft2.id,
                    file_storage=_file_storage(filename="ref2.pdf", payload=PDF_BYTES + b"%ref2"),
                    claimed_amount="150000",
                    sender_name="Pengirim 2",
                    transfer_reference="trx-ref-777",
                    commit=False,
                )
        finally:
            transaction.rollback()
