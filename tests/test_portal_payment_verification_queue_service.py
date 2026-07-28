from uuid import uuid4

import pytest

from app.extensions import db
from app.models.finance import Payment
from app.models.system import DigitalAttachment
from app.services.portal_mapping_service import PRINCIPAL_CLIENT
from app.services.portal_payment_proof_service import PAYMENT_PROOF_PENDING_TYPE, upload_portal_payment_proof
from app.services.portal_payment_verification_queue_service import (
    PAYMENT_PROOF_REJECTED_TYPE,
    PAYMENT_PROOF_VERIFIED_TYPE,
    PaymentProofVerificationError,
    decide_payment_proof,
    list_payment_proof_verification_queue,
)
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_invoice,
    _create_mapping,
    _create_user,
)
from tests.test_portal_payment_proof_service import _file_storage


def _create_pending_proof():
    portal_user = _create_user("PORTAL_CLIENT")
    finance_user = _create_user("FINANCE", branch=portal_user.branch)
    client, _, mandor, _ = _create_client_family(portal_user.branch, "VERIFYPROOF")
    _create_mapping(portal_user, PRINCIPAL_CLIENT, client=client)
    invoice = _create_invoice(
        portal_user,
        invoice_number=f"T-VERIFY-INV-{uuid4().hex[:10]}",
        client=client,
        mandor=mandor,
        total="175000",
        paid="0",
        remaining="175000",
        status="OPEN",
    )
    result = upload_portal_payment_proof(
        portal_user,
        invoice_id=invoice.id,
        file_storage=_file_storage(),
        notes="Finance queue test",
        commit=False,
    )
    attachment = DigitalAttachment.query.get(result["attachment_id"])
    return portal_user, finance_user, invoice, attachment


def test_payment_proof_queue_lists_pending_branch_items_only(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            _, finance_user, invoice, attachment = _create_pending_proof()

            rows = list_payment_proof_verification_queue(finance_user)

            assert [row["attachment_id"] for row in rows] == [attachment.id]
            assert rows[0]["attachment_type"] == PAYMENT_PROOF_PENDING_TYPE
            assert rows[0]["invoice_id"] == invoice.id
            assert rows[0]["invoice_number"] == invoice.invoice_number
            assert rows[0]["payment_created"] is False
            assert rows[0]["mutation_scope"] == "ATTACHMENT_DECISION_ONLY"
        finally:
            transaction.rollback()


def test_finance_verify_payment_proof_does_not_create_payment_or_mutate_invoice(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            _, finance_user, invoice, attachment = _create_pending_proof()
            original_paid = invoice.paid_amount
            original_remaining = invoice.remaining_amount
            original_status = invoice.status
            payment_count_before = Payment.query.count()

            result = decide_payment_proof(
                finance_user,
                attachment_id=attachment.id,
                decision="VERIFIED",
                notes="Nominal cocok, lanjut batch payment creation.",
                commit=False,
            )

            db.session.refresh(invoice)
            db.session.refresh(attachment)

            assert result["changed"] is True
            assert result["decision"] == "VERIFIED"
            assert result["attachment_type"] == PAYMENT_PROOF_VERIFIED_TYPE
            assert result["payment_created"] is False
            assert result["payment_count_before"] == payment_count_before
            assert result["payment_count_after"] == payment_count_before
            assert Payment.query.count() == payment_count_before
            assert invoice.paid_amount == original_paid
            assert invoice.remaining_amount == original_remaining
            assert invoice.status == original_status
            assert attachment.attachment_type == PAYMENT_PROOF_VERIFIED_TYPE
            assert "FINANCE_VERIFICATION VERIFIED" in attachment.notes
        finally:
            transaction.rollback()


def test_finance_reject_payment_proof_is_idempotent_for_same_state(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            _, finance_user, _, attachment = _create_pending_proof()

            first = decide_payment_proof(
                finance_user,
                attachment_id=attachment.id,
                decision="REJECTED",
                notes="Bukti tidak sesuai.",
                commit=False,
            )
            second = decide_payment_proof(
                finance_user,
                attachment_id=attachment.id,
                decision="REJECTED",
                notes="Retry keputusan sama.",
                commit=False,
            )

            assert first["changed"] is True
            assert second["changed"] is False
            assert second["attachment_type"] == PAYMENT_PROOF_REJECTED_TYPE
        finally:
            transaction.rollback()


def test_finance_cannot_change_decided_payment_proof_to_other_state(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            _, finance_user, _, attachment = _create_pending_proof()
            decide_payment_proof(finance_user, attachment_id=attachment.id, decision="REJECTED", commit=False)

            with pytest.raises(PaymentProofVerificationError):
                decide_payment_proof(finance_user, attachment_id=attachment.id, decision="VERIFIED", commit=False)
        finally:
            transaction.rollback()


def test_finance_cannot_decide_payment_proof_from_other_branch(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            _, _, _, attachment = _create_pending_proof()
            other_branch_finance = _create_user("FINANCE")

            with pytest.raises(PaymentProofVerificationError):
                decide_payment_proof(
                    other_branch_finance,
                    attachment_id=attachment.id,
                    decision="VERIFIED",
                    commit=False,
                )
        finally:
            transaction.rollback()
