from io import BytesIO
from uuid import uuid4

from app.extensions import db
from app.models.finance import Invoice, Payment
from app.models.system import DigitalAttachment
from app.services.portal_mapping_service import PRINCIPAL_CLIENT
from app.services.portal_payment_proof_service import PAYMENT_PROOF_PENDING_TYPE, PORTAL_PAYMENT_MODULE
from app.services.user_management_service import ROLE_PORTAL_CLIENT, ROLE_PORTAL_CUSTOMER
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_invoice,
    _create_mapping,
    _create_user,
)


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF\n"


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _owned_portal_invoice(role=ROLE_PORTAL_CLIENT):
    user = _create_user(role)
    client_obj, _pic, mandor, _location = _create_client_family(user.branch, "PAYROUTE")
    _create_mapping(user, PRINCIPAL_CLIENT, client=client_obj)
    invoice = _create_invoice(
        user,
        invoice_number=f"T-PAYROUTE-INV-{uuid4().hex[:10]}",
        client=client_obj,
        mandor=mandor,
        total="175000",
        paid="25000",
        remaining="150000",
        status="PARTIAL",
    )
    invoice.company_bank_name_snapshot = "Bank Portal"
    invoice.company_bank_account_number_snapshot = "123456789"
    invoice.company_bank_account_name_snapshot = "PT Idha Boga Pangan Mandiri"
    db.session.commit()
    return user, invoice


def test_portal_invoice_payment_instruction_route_renders_owned_invoice(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user, invoice = _owned_portal_invoice()
        user_id = user.id
        invoice_id = invoice.id
        invoice_number = invoice.invoice_number
        payment_count_before = Payment.query.count()

    client = app.test_client()
    _login_user_id(client, user_id)

    response = client.get(f"/portal/invoices/{invoice_id}/payment")
    html = response.get_data(as_text=True)

    with app.app_context():
        payment_count_after = Payment.query.count()

    assert response.status_code == 200
    assert "Instruksi Pembayaran" in html
    assert invoice_number in html
    assert "Bank Portal" in html
    assert "123456789" in html
    assert "Upload Bukti" in html
    assert "Attachment only, finance verify" in html
    assert payment_count_after == payment_count_before


def test_portal_invoice_payment_upload_creates_attachment_without_payment_mutation(app, tmp_path):
    app.config["PORTAL_ENABLED"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        user, invoice = _owned_portal_invoice()
        user_id = user.id
        invoice_id = invoice.id
        original_paid = invoice.paid_amount
        original_remaining = invoice.remaining_amount
        payment_count_before = Payment.query.count()

    client = app.test_client()
    _login_user_id(client, user_id)

    response = client.post(
        f"/portal/invoices/{invoice_id}/payment",
        data={
            "proof_file": (BytesIO(PDF_BYTES), "portal-proof.pdf"),
            "notes": "Transfer portal route test",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        attachment = DigitalAttachment.query.filter_by(
            module=PORTAL_PAYMENT_MODULE,
            reference_type="INVOICE",
            reference_id=invoice_id,
            attachment_type=PAYMENT_PROOF_PENDING_TYPE,
        ).order_by(DigitalAttachment.id.desc()).first()
        payment_count_after = Payment.query.count()

    assert response.status_code == 200
    assert "berhasil diupload dan menunggu verifikasi finance" in html
    assert attachment is not None
    assert attachment.original_filename == "portal-proof.pdf"
    assert attachment.mime_type == "application/pdf"
    assert payment_count_after == payment_count_before
    assert invoice.paid_amount == original_paid
    assert invoice.remaining_amount == original_remaining


def test_portal_customer_payment_instruction_route_is_blocked(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        user, invoice = _owned_portal_invoice(ROLE_PORTAL_CUSTOMER)
        user_id = user.id
        invoice_id = invoice.id

    client = app.test_client()
    _login_user_id(client, user_id)

    response = client.get(f"/portal/invoices/{invoice_id}/payment")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Financial visibility pelanggan umum menunggu prepayment/payment flow Stage 3." in html
    assert "Upload Bukti" not in html
