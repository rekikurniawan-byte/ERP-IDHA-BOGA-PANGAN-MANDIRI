from io import BytesIO
from pathlib import Path
from uuid import uuid4

from app.extensions import db
from app.models.complaint import CustomerComplaint
from app.models.contract import CustomerContract
from app.models.correction import CustomerCorrection
from app.models.system import DigitalAttachment
from app.services.customer_correction_service import (
    CORRECTION_STATUS_SUBMITTED,
    create_customer_correction,
)
from app.services.user_management_service import ALLOWED_ROLES, ROLE_CUSTOMER_SUCCESS, ROLE_LABELS
from tests.test_portal_financial_visibility_service import _create_client_family, _create_user


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_customer_success_requires_login(app):
    response = app.test_client().get("/customer-success/contracts")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_customer_success_sidebar_and_index_render_for_admin(app):
    with app.app_context():
        user = _create_user("ADMIN")
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login_user_id(client, user_id)

    response = client.get("/customer-success/contracts")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Customer Success" in html
    assert "Kontrak Customer" in html
    assert "Komplain" in html
    assert "Koreksi" in html
    assert "Return Management" in html
    assert "Approval Engine" in html
    assert "Notification Center" in html
    assert "Document Management" in html
    assert "Subscription Order" in html
    assert "Operational Calendar" in html


def test_customer_success_role_is_available_and_lands_on_customer_success(app):
    assert ROLE_CUSTOMER_SUCCESS in ALLOWED_ROLES
    assert ROLE_LABELS[ROLE_CUSTOMER_SUCCESS] == "Customer Success"

    with app.app_context():
        user = _create_user(ROLE_CUSTOMER_SUCCESS)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login_user_id(client, user_id)

    dashboard_response = client.get("/", follow_redirects=False)
    page_response = client.get("/customer-success/complaints")
    html = page_response.get_data(as_text=True)

    assert dashboard_response.status_code == 302
    assert "/customer-success/contracts" in dashboard_response.headers["Location"]
    assert page_response.status_code == 200
    assert "Customer Success" in html
    assert "Komplain Customer" in html


def test_customer_success_rejects_unrelated_internal_role(app):
    with app.app_context():
        user = _create_user("FINANCE")
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login_user_id(client, user_id)

    response = client.get("/customer-success/complaints", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_customer_success_contract_lifecycle_and_document_upload(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path / "attachments")
    title = f"Kontrak QA UI {uuid4().hex[:8]}"

    with app.app_context():
        user = _create_user("ADMIN")
        client_obj, pic, _mandor, _location = _create_client_family(user.branch, "CSUI-CONTRACT")
        db.session.commit()
        user_id = user.id
        client_id = client_obj.id
        pic_id = pic.id

    client = app.test_client()
    _login_user_id(client, user_id)

    create_response = client.post(
        "/customer-success/contracts",
        data={
            "client_id": str(client_id),
            "client_pic_id": str(pic_id),
            "title": title,
            "start_date": "2099-01-01",
            "end_date": "2099-12-31",
            "payment_terms": "NET 30",
            "credit_limit": "1250000",
            "status": "DRAFT",
        },
        follow_redirects=False,
    )

    with app.app_context():
        contract = CustomerContract.query.filter_by(title=title).one()
        contract_id = contract.id

    list_response = client.get("/customer-success/contracts")
    detail_response = client.get(f"/customer-success/contracts/{contract_id}")
    activate_response = client.post(f"/customer-success/contracts/{contract_id}/activate", follow_redirects=False)
    upload_response = client.post(
        f"/customer-success/contracts/{contract_id}/documents",
        data={
            "attachment_type": "CONTRACT_DOCUMENT",
            "notes": "Dokumen QA",
            "document_file": (BytesIO(b"%PDF-1.4\nqa contract\n%%EOF"), "contract-ui.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    with app.app_context():
        contract = db.session.get(CustomerContract, contract_id)
        attachment = DigitalAttachment.query.filter_by(
            module="CUSTOMER_CONTRACT",
            reference_type="CUSTOMER_CONTRACT",
            reference_id=contract_id,
        ).one()
        stored_path = Path(app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"]) / attachment.file_path

        assert create_response.status_code == 302
        assert list_response.status_code == 200
        assert detail_response.status_code == 200
        assert activate_response.status_code == 302
        assert upload_response.status_code == 302
        assert contract.status == "ACTIVE"
        assert attachment.original_filename == "contract-ui.pdf"
        assert stored_path.exists()


def test_customer_success_complaint_status_and_evidence_upload(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path / "complaint-attachments")
    title = f"Komplain QA UI {uuid4().hex[:8]}"

    with app.app_context():
        user = _create_user("ADMIN")
        client_obj, _pic, mandor, _location = _create_client_family(user.branch, "CSUI-COMPLAINT")
        db.session.commit()
        user_id = user.id
        client_id = client_obj.id
        mandor_id = mandor.id

    client = app.test_client()
    _login_user_id(client, user_id)

    create_response = client.post(
        "/customer-success/complaints",
        data={
            "category": "LATE_DELIVERY",
            "client_id": str(client_id),
            "mandor_id": str(mandor_id),
            "title": title,
            "description": "Delivery terlambat.",
        },
        follow_redirects=False,
    )

    with app.app_context():
        complaint = CustomerComplaint.query.filter_by(title=title).one()
        complaint_id = complaint.id

    detail_response = client.get(f"/customer-success/complaints/{complaint_id}")
    status_response = client.post(
        f"/customer-success/complaints/{complaint_id}/status",
        data={"new_status": "IN_PROGRESS"},
        follow_redirects=False,
    )
    upload_response = client.post(
        f"/customer-success/complaints/{complaint_id}/evidence",
        data={
            "attachment_type": "COMPLAINT_EVIDENCE",
            "notes": "Bukti QA",
            "evidence_file": (BytesIO(b"%PDF-1.4\nqa complaint\n%%EOF"), "complaint-ui.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    with app.app_context():
        complaint = db.session.get(CustomerComplaint, complaint_id)
        attachment = DigitalAttachment.query.filter_by(
            module="CUSTOMER_COMPLAINT",
            reference_type="CUSTOMER_COMPLAINT",
            reference_id=complaint_id,
        ).one()

        assert create_response.status_code == 302
        assert detail_response.status_code == 200
        assert status_response.status_code == 302
        assert upload_response.status_code == 302
        assert complaint.status == "IN_PROGRESS"
        assert attachment.original_filename == "complaint-ui.pdf"


def test_customer_success_correction_route_uses_real_service(app):
    app.config["WTF_CSRF_ENABLED"] = False
    reason = f"Porsi kurang {uuid4().hex[:8]}"

    with app.app_context():
        user = _create_user("ADMIN")
        client_obj, _pic, mandor, _location = _create_client_family(user.branch, "CSUI-CORRECTION")
        db.session.commit()
        user_id = user.id
        client_id = client_obj.id
        mandor_id = mandor.id

    client = app.test_client()
    _login_user_id(client, user_id)

    create_response = client.post(
        "/customer-success/corrections",
        data={
            "correction_type": "COMPENSATION",
            "client_id": str(client_id),
            "mandor_id": str(mandor_id),
            "reason": reason,
            "proposed_action": "Kompensasi order berikutnya",
            "correction_amount": "50000",
            "stock_effect": "NONE",
            "financial_effect": "PENDING",
        },
        follow_redirects=False,
    )

    with app.app_context():
        correction = CustomerCorrection.query.filter_by(reason=reason).one()
        correction_id = correction.id

    detail_response = client.get(f"/customer-success/corrections/{correction_id}")
    submit_response = client.post(f"/customer-success/corrections/{correction_id}/submit", follow_redirects=False)

    with app.app_context():
        correction = db.session.get(CustomerCorrection, correction_id)

        assert create_response.status_code == 302
        assert detail_response.status_code == 200
        assert submit_response.status_code == 302
        assert correction.status == CORRECTION_STATUS_SUBMITTED
        assert correction.financial_effect == "PENDING"
        assert correction.stock_effect == "NONE"


def test_customer_success_service_allows_correction_without_financial_or_stock_posting(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("ADMIN")
            client_obj, _pic, mandor, _location = _create_client_family(user.branch, "CSUI-SERVICE")

            correction = create_customer_correction(
                branch_id=user.branch_id,
                correction_type="RETURN",
                client_id=client_obj.id,
                mandor_id=mandor.id,
                reason="Barang return",
                proposed_action="Evaluasi dan ajukan approval jika perlu posting.",
                correction_amount="0",
                stock_effect="NONE",
                financial_effect="NONE",
                submitted_by=user.id,
                commit=False,
            )

            assert correction.correction_number.startswith("CRC-")
            assert correction.status == "DRAFT"
            assert correction.approval_request_id is None
            assert correction.stock_effect == "NONE"
            assert correction.financial_effect == "NONE"
        finally:
            transaction.rollback()


def test_customer_success_route_has_no_session_commit_or_rollback():
    source = Path("app/routes/customer_success_routes.py").read_text()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source


def test_customer_success_foundation_shell_pages_render(app):
    with app.app_context():
        user = _create_user(ROLE_CUSTOMER_SUCCESS)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login_user_id(client, user_id)

    pages = {
        "/customer-success/returns": "Return Management",
        "/customer-success/approval-engine": "Approval Engine",
        "/customer-success/notifications": "Notification Center",
        "/customer-success/documents": "Document Management",
        "/customer-success/subscriptions": "Subscription Order",
        "/customer-success/calendar": "Operational Calendar",
    }

    for path, title in pages.items():
        response = client.get(path)
        html = response.get_data(as_text=True)

        assert response.status_code == 200, path
        assert title in html
        assert "Integrasi Data" in html
        assert "tidak membuat tabel atau workflow paralel" in html
        assert "BuildError" not in html
        assert "UndefinedError" not in html
