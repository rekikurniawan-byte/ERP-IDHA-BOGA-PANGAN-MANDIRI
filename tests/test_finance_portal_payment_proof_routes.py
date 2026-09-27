from datetime import date
from uuid import uuid4

from app.extensions import db
from app.models.finance import Invoice, Payment
from app.models.system import DigitalAttachment
from app.services.portal_payment_proof_service import upload_portal_payment_proof
from app.services.portal_payment_verification_queue_service import (
    PAYMENT_PROOF_VERIFIED_TYPE,
)
from tests.test_portal_financial_visibility_service import _create_client_family, _create_mapping, _create_user
from tests.test_portal_payment_creation_service import (
    PAYMENT_PROOF_PAYMENT_CREATED_TYPE,
    _setup_verified_proof,
)
from tests.test_portal_payment_proof_service import _file_storage
from app.services.portal_mapping_service import PRINCIPAL_CLIENT


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _setup_pending_proof():
    portal_user = _create_user("PORTAL_CLIENT")
    finance_user = _create_user("FINANCE", branch=portal_user.branch)
    client_obj, _pic, mandor, _location = _create_client_family(portal_user.branch, "FINPROOF")
    _create_mapping(portal_user, PRINCIPAL_CLIENT, client=client_obj)
    invoice = Invoice(
        branch_id=portal_user.branch_id,
        invoice_number=f"T-FINPROOF-INV-{uuid4().hex[:10]}",
        invoice_date=date.today(),
        due_date=date.today(),
        period_start=date.today(),
        period_end=date.today(),
        bill_to_type="CLIENT",
        client_id=client_obj.id,
        mandor_id=mandor.id,
        total_amount=100000,
        paid_amount=0,
        remaining_amount=100000,
        status="OPEN",
        source_type="FINANCE_PORTAL_PROOF_ROUTE_TEST",
        input_source="REALTIME",
        created_by=portal_user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    result = upload_portal_payment_proof(
        portal_user,
        invoice_id=invoice.id,
        file_storage=_file_storage(),
        notes="Pending proof route test",
        commit=False,
    )
    attachment = db.session.get(DigitalAttachment, result["attachment_id"])
    db.session.commit()
    return finance_user.id, invoice.id, attachment.id


def test_finance_portal_payment_proof_queue_renders_pending_rows(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)

    with app.app_context():
        finance_user_id, _invoice_id, attachment_id = _setup_pending_proof()

    client = app.test_client()
    _login_user_id(client, finance_user_id)

    response = client.get("/finance/portal-payment-proofs")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Verifikasi Bukti Pembayaran Portal" in html
    # Label halaman sudah berbahasa Indonesia.
    assert f"Lampiran #{attachment_id}" in html
    assert "Verifikasi" in html
    assert "Tolak" in html
    assert "Buat Pembayaran Resmi" not in html
    assert f"/finance/portal-payment-proofs/attachments/{attachment_id}/view" in html

    proof_response = client.get(f"/finance/portal-payment-proofs/attachments/{attachment_id}/view")
    assert proof_response.status_code == 200
    assert proof_response.mimetype == "application/pdf"


def test_finance_can_verify_portal_payment_proof_from_queue(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        finance_user_id, _invoice_id, attachment_id = _setup_pending_proof()

    client = app.test_client()
    _login_user_id(client, finance_user_id)

    response = client.post(
        f"/finance/portal-payment-proofs/{attachment_id}/decide",
        data={"decision": "VERIFIED", "notes": "Route verified."},
        follow_redirects=False,
    )

    with app.app_context():
        attachment = db.session.get(DigitalAttachment, attachment_id)

    assert response.status_code == 302
    assert "status=VERIFIED" in response.headers["Location"]
    assert attachment.attachment_type == PAYMENT_PROOF_VERIFIED_TYPE


def test_finance_create_payment_from_verified_portal_proof_route(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        finance_user, invoice, bank_account, attachment = _setup_verified_proof()
        finance_user_id = finance_user.id
        invoice_id = invoice.id
        attachment_id = attachment.id
        bank_account_id = bank_account.id
        payment_count_before = Payment.query.count()
        db.session.commit()

    client = app.test_client()
    _login_user_id(client, finance_user_id)

    response = client.post(
        f"/finance/portal-payment-proofs/{attachment_id}/create-payment",
        data={
            "payment_date": date.today().isoformat(),
            "amount": "60000",
            "payment_method": "TRANSFER",
            "bank_account_id": str(bank_account_id),
            "reference_number": "ROUTE-PORTAL-PAY",
            "notes": "Payment route from verified portal proof.",
            "idempotency_key": f"T-FINPROOF-PAY-{uuid4().hex}",
        },
        follow_redirects=False,
    )

    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        attachment = db.session.get(DigitalAttachment, attachment_id)
        payment = Payment.query.filter_by(invoice_id=invoice_id, reference_number="ROUTE-PORTAL-PAY").first()
        payment_count_after = Payment.query.count()

    assert response.status_code == 302
    assert f"/finance/invoices/{invoice_id}" in response.headers["Location"]
    assert payment_count_after == payment_count_before + 1
    assert payment is not None
    assert float(invoice.remaining_amount) == 40000
    assert attachment.attachment_type == PAYMENT_PROOF_PAYMENT_CREATED_TYPE
