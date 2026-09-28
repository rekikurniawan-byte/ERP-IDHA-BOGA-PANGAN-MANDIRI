from datetime import date, timedelta
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.system import DigitalAttachment
from app.services.customer_contract_document_service import (
    CONTRACT_AMENDMENT_TYPE,
    CONTRACT_DOCUMENT_TYPE,
    CUSTOMER_CONTRACT_DOCUMENT_MODULE,
    CUSTOMER_CONTRACT_REFERENCE_TYPE,
    CustomerContractDocumentError,
    attach_customer_contract_document,
    list_customer_contract_documents,
)
from app.services.customer_contract_service import CONTRACT_STATUS_ACTIVE, create_customer_contract
from app.services.digital_attachment_service import AttachmentValidationError
from tests.test_customer_contract_service import _contract_fixture
from tests.test_portal_financial_visibility_service import _create_user


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF\n"


def _file_storage(filename="contract.pdf", payload=PDF_BYTES, content_type="application/pdf"):
    return FileStorage(
        stream=BytesIO(payload),
        filename=filename,
        content_type=content_type,
    )


def _create_contract():
    user, client, pic = _contract_fixture()
    contract = create_customer_contract(
        branch_id=user.branch_id,
        client_id=client.id,
        client_pic_id=pic.id,
        title="Kontrak Arsip QA",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=90),
        payment_terms="NET 14",
        credit_limit="3000000",
        created_by=user.id,
        status=CONTRACT_STATUS_ACTIVE,
        commit=False,
    )
    return user, contract


def test_attach_customer_contract_document_archives_private_attachment(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, contract = _create_contract()
            original_status = contract.status
            original_terms = contract.payment_terms
            original_limit = contract.credit_limit

            attachment = attach_customer_contract_document(
                contract_id=contract.id,
                branch_id=user.branch_id,
                file_storage=_file_storage(),
                uploaded_by=user.id,
                notes="Dokumen kontrak utama",
                commit=False,
            )

            db.session.refresh(contract)
            listed = list_customer_contract_documents(contract_id=contract.id, branch_id=user.branch_id)

            assert attachment.id is not None
            assert attachment.module == CUSTOMER_CONTRACT_DOCUMENT_MODULE
            assert attachment.reference_type == CUSTOMER_CONTRACT_REFERENCE_TYPE
            assert attachment.reference_id == contract.id
            assert attachment.attachment_type == CONTRACT_DOCUMENT_TYPE
            assert attachment.branch_id == user.branch_id
            assert attachment.mime_type == "application/pdf"
            assert attachment.notes == "CONTRACT_DOCUMENT: Dokumen kontrak utama"
            assert listed[0].id == attachment.id
            assert contract.status == original_status
            assert contract.payment_terms == original_terms
            assert contract.credit_limit == original_limit
        finally:
            transaction.rollback()


def test_contract_document_list_is_branch_scoped(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, contract = _create_contract()
            other_user = _create_user("ADMIN")

            attachment = attach_customer_contract_document(
                contract_id=contract.id,
                branch_id=user.branch_id,
                file_storage=_file_storage(),
                uploaded_by=user.id,
                commit=False,
            )

            assert list_customer_contract_documents(contract_id=contract.id, branch_id=user.branch_id)[0].id == attachment.id
            with pytest.raises(CustomerContractDocumentError):
                list_customer_contract_documents(contract_id=contract.id, branch_id=other_user.branch_id)
        finally:
            transaction.rollback()


def test_attach_customer_contract_document_supports_allowed_document_types(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, contract = _create_contract()

            attachment = attach_customer_contract_document(
                contract_id=contract.id,
                branch_id=user.branch_id,
                file_storage=_file_storage("amendment.pdf"),
                uploaded_by=user.id,
                attachment_type=CONTRACT_AMENDMENT_TYPE,
                commit=False,
            )

            listed = list_customer_contract_documents(
                contract_id=contract.id,
                branch_id=user.branch_id,
                attachment_type=CONTRACT_AMENDMENT_TYPE,
            )
            assert attachment.attachment_type == CONTRACT_AMENDMENT_TYPE
            assert [row.id for row in listed] == [attachment.id]
        finally:
            transaction.rollback()


def test_attach_customer_contract_document_rejects_invalid_type(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, contract = _create_contract()
            before_count = DigitalAttachment.query.filter_by(module=CUSTOMER_CONTRACT_DOCUMENT_MODULE).count()

            with pytest.raises(CustomerContractDocumentError):
                attach_customer_contract_document(
                    contract_id=contract.id,
                    branch_id=user.branch_id,
                    file_storage=_file_storage(),
                    uploaded_by=user.id,
                    attachment_type="RANDOM_FILE",
                    commit=False,
                )

            assert DigitalAttachment.query.filter_by(module=CUSTOMER_CONTRACT_DOCUMENT_MODULE).count() == before_count
        finally:
            transaction.rollback()


def test_attach_customer_contract_document_rejects_unsafe_payload(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, contract = _create_contract()
            before_count = DigitalAttachment.query.filter_by(module=CUSTOMER_CONTRACT_DOCUMENT_MODULE).count()

            with pytest.raises(AttachmentValidationError):
                attach_customer_contract_document(
                    contract_id=contract.id,
                    branch_id=user.branch_id,
                    file_storage=_file_storage(payload=b"<html><script>alert(1)</script></html>"),
                    uploaded_by=user.id,
                    commit=False,
                )

            assert DigitalAttachment.query.filter_by(module=CUSTOMER_CONTRACT_DOCUMENT_MODULE).count() == before_count
        finally:
            transaction.rollback()
