from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.system import DigitalAttachment
from app.services.customer_complaint_attachment_service import (
    COMPLAINT_EVIDENCE_TYPE,
    COMPLAINT_RESOLUTION_EVIDENCE_TYPE,
    CUSTOMER_COMPLAINT_ATTACHMENT_MODULE,
    CUSTOMER_COMPLAINT_REFERENCE_TYPE,
    CustomerComplaintAttachmentError,
    attach_customer_complaint_evidence,
    list_customer_complaint_evidence,
)
from app.services.customer_complaint_service import COMPLAINT_CATEGORY_LATE_DELIVERY, submit_customer_complaint
from app.services.digital_attachment_service import AttachmentValidationError
from tests.test_portal_financial_visibility_service import _create_client_family, _create_user


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF\n"


def _file_storage(filename="complaint.pdf", payload=PDF_BYTES, content_type="application/pdf"):
    return FileStorage(stream=BytesIO(payload), filename=filename, content_type=content_type)


def _complaint_fixture():
    user = _create_user("ADMIN")
    client, _, mandor, _ = _create_client_family(user.branch, "CMPATT")
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


def test_attach_customer_complaint_evidence_creates_private_attachment_without_status_mutation(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, complaint = _complaint_fixture()
            original_status = complaint.status

            attachment = attach_customer_complaint_evidence(
                complaint_id=complaint.id,
                branch_id=user.branch_id,
                file_storage=_file_storage(),
                uploaded_by=user.id,
                notes="Foto bukti terlambat",
                commit=False,
            )

            listed = list_customer_complaint_evidence(complaint_id=complaint.id, branch_id=user.branch_id)

            assert attachment.module == CUSTOMER_COMPLAINT_ATTACHMENT_MODULE
            assert attachment.reference_type == CUSTOMER_COMPLAINT_REFERENCE_TYPE
            assert attachment.reference_id == complaint.id
            assert attachment.attachment_type == COMPLAINT_EVIDENCE_TYPE
            assert attachment.branch_id == user.branch_id
            assert attachment.notes == "COMPLAINT_EVIDENCE: Foto bukti terlambat"
            assert listed[0].id == attachment.id
            assert complaint.status == original_status
        finally:
            transaction.rollback()


def test_complaint_evidence_is_branch_scoped(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, complaint = _complaint_fixture()
            other_user = _create_user("ADMIN")

            attach_customer_complaint_evidence(
                complaint_id=complaint.id,
                branch_id=user.branch_id,
                file_storage=_file_storage(),
                uploaded_by=user.id,
                commit=False,
            )

            with pytest.raises(CustomerComplaintAttachmentError):
                list_customer_complaint_evidence(complaint_id=complaint.id, branch_id=other_user.branch_id)
        finally:
            transaction.rollback()


def test_complaint_evidence_supports_resolution_type(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, complaint = _complaint_fixture()

            attachment = attach_customer_complaint_evidence(
                complaint_id=complaint.id,
                branch_id=user.branch_id,
                file_storage=_file_storage("resolution.pdf"),
                uploaded_by=user.id,
                attachment_type=COMPLAINT_RESOLUTION_EVIDENCE_TYPE,
                commit=False,
            )

            listed = list_customer_complaint_evidence(
                complaint_id=complaint.id,
                branch_id=user.branch_id,
                attachment_type=COMPLAINT_RESOLUTION_EVIDENCE_TYPE,
            )
            assert attachment.attachment_type == COMPLAINT_RESOLUTION_EVIDENCE_TYPE
            assert [row.id for row in listed] == [attachment.id]
        finally:
            transaction.rollback()


def test_complaint_evidence_rejects_invalid_type_and_unsafe_payload(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, complaint = _complaint_fixture()
            before_count = DigitalAttachment.query.filter_by(module=CUSTOMER_COMPLAINT_ATTACHMENT_MODULE).count()

            with pytest.raises(CustomerComplaintAttachmentError):
                attach_customer_complaint_evidence(
                    complaint_id=complaint.id,
                    branch_id=user.branch_id,
                    file_storage=_file_storage(),
                    uploaded_by=user.id,
                    attachment_type="RANDOM",
                    commit=False,
                )

            with pytest.raises(AttachmentValidationError):
                attach_customer_complaint_evidence(
                    complaint_id=complaint.id,
                    branch_id=user.branch_id,
                    file_storage=_file_storage(payload=b"<script>alert(1)</script>"),
                    uploaded_by=user.id,
                    commit=False,
                )

            assert DigitalAttachment.query.filter_by(module=CUSTOMER_COMPLAINT_ATTACHMENT_MODULE).count() == before_count
        finally:
            transaction.rollback()
