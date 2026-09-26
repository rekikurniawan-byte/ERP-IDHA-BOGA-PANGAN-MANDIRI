from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.finance import Invoice, Payment
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Mandor, User
from app.models.system import PortalUserMapping
from app.services.portal_financial_visibility_service import (
    build_portal_invoice_read_model,
    build_portal_payment_history_read_model,
)
from app.services.portal_mapping_service import (
    PRINCIPAL_CLIENT,
    PRINCIPAL_DELEGATE,
    PRINCIPAL_MANDOR,
)
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_SUBCLIENT,
)


def _suffix():
    return uuid4().hex[:10]


def _create_user(role, branch=None):
    suffix = _suffix()
    if not branch:
        branch = Branch(
            code=f"T-PFV-BR-{suffix}",
            name="Test Portal Finance Branch",
            address="Test",
            phone="0800000000",
            is_active=True,
        )
        db.session.add(branch)
        db.session.flush()

    user = User(
        branch_id=branch.id,
        full_name=f"Test Portal Finance {role}",
        username=f"portal-finance-{role.lower()}-{suffix}",
        password_hash=generate_password_hash("portal-finance-password"),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _create_client_family(branch, prefix="T-PFV"):
    suffix = _suffix()
    client = Client(
        client_code=f"{prefix}-CLIENT-{suffix}",
        name=f"{prefix} Client {suffix}",
        address="Test",
        phone="0800000001",
        is_active=True,
    )
    db.session.add(client)
    db.session.flush()
    pic = ClientPic(
        client_id=client.id,
        name=f"{prefix} PIC {suffix}",
        phone="0800000002",
        email=f"{suffix}@example.test",
        position="PIC",
        is_active=True,
    )
    mandor = Mandor(
        branch_id=branch.id,
        client_id=client.id,
        name=f"{prefix} Mandor {suffix}",
        phone="0800000003",
        is_active=True,
    )
    db.session.add(pic)
    db.session.add(mandor)
    db.session.flush()
    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name=f"{prefix} Location {suffix}",
        description="Test location",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return client, pic, mandor, location


def _create_mapping(user, principal_type, *, client=None, mandor=None, client_pic=None, location=None):
    mapping = PortalUserMapping(
        user_id=user.id,
        principal_type=principal_type,
        client_id=client.id if client else None,
        mandor_id=mandor.id if mandor else None,
        client_pic_id=client_pic.id if client_pic else None,
        delivery_location_id=location.id if location else None,
        access_level="READ_ONLY",
        is_active=True,
    )
    db.session.add(mapping)
    db.session.flush()
    return mapping


def _create_invoice(
    user,
    *,
    invoice_number,
    client=None,
    mandor=None,
    client_pic=None,
    total="100000",
    paid="25000",
    remaining="75000",
    status="PARTIAL",
):
    invoice_date = date(2099, 1, 15)
    invoice = Invoice(
        branch_id=user.branch_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=14),
        period_start=invoice_date,
        period_end=invoice_date,
        bill_to_type="CLIENT" if client else "MANDOR",
        client_id=client.id if client else (mandor.client_id if mandor else None),
        mandor_id=mandor.id if mandor else None,
        client_pic_id=client_pic.id if client_pic else None,
        total_amount=Decimal(total),
        paid_amount=Decimal(paid),
        remaining_amount=Decimal(remaining),
        status=status,
        source_type="PORTAL_FINANCE_VISIBILITY_TEST",
        source_order_id=None,
        input_source="REALTIME",
        created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    payment_amount = Decimal(paid)
    if payment_amount > 0:
        db.session.add(
            Payment(
                payment_number=f"PAY-{invoice_number}",
                branch_id=user.branch_id,
                payment_date=invoice_date,
                invoice_id=invoice.id,
                payment_method="TRANSFER",
                amount=payment_amount,
                reference_number=f"REF-{invoice_number}",
                received_by=user.id,
            )
        )
        db.session.flush()
    return invoice


def _numbers(rows):
    return {row["invoice_number"] for row in rows}


def test_portal_client_invoice_read_model_only_returns_owned_client_invoices(app, monkeypatch):
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(AssertionError("read model must not commit")))
    monkeypatch.setattr(db.session, "rollback", lambda: (_ for _ in ()).throw(AssertionError("read model must not rollback")))

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            owned_client, owned_pic, owned_mandor, _ = _create_client_family(user.branch, "OWN")
            other_client, _, other_mandor, _ = _create_client_family(user.branch, "OTHER")
            _create_mapping(user, PRINCIPAL_CLIENT, client=owned_client)

            owned_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=owned_client, mandor=owned_mandor, client_pic=owned_pic)
            other_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=other_client, mandor=other_mandor)

            read_model = build_portal_invoice_read_model(user)

            assert read_model["allowed"] is True
            assert _numbers(read_model["invoices"]) == {owned_invoice.invoice_number}
            assert other_invoice.invoice_number not in _numbers(read_model["invoices"])
            assert read_model["totals"]["invoice_count"] == 1
            assert read_model["totals"]["active_outstanding_amount"] == Decimal("75000")
            assert read_model["totals"]["payment_total"] == Decimal("25000")
            assert read_model["totals"]["payment_mismatch_count"] == 0
        finally:
            transaction.rollback()


def test_portal_mandor_invoice_read_model_does_not_show_client_level_invoice(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_SUBCLIENT)
            owned_client, _, owned_mandor, _ = _create_client_family(user.branch, "MANDOR")
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=owned_mandor)

            mandor_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=owned_client, mandor=owned_mandor)
            client_level_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=owned_client, mandor=None)

            read_model = build_portal_invoice_read_model(user)

            assert _numbers(read_model["invoices"]) == {mandor_invoice.invoice_number}
            assert client_level_invoice.invoice_number not in _numbers(read_model["invoices"])
        finally:
            transaction.rollback()


def test_retired_portal_delegate_role_sees_no_invoices(app):
    # PORTAL_DELEGATE dipensiunkan tanpa penerus. Akun yang (seandainya)
    # masih memegangnya bukan role portal lagi: walaupun punya pemetaan
    # akses, tidak ada satu invoice pun yang terlihat.
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user("PORTAL_DELEGATE")
            client, _, mandor, location = _create_client_family(user.branch, "RETIRED")
            _create_mapping(user, PRINCIPAL_DELEGATE, location=location)
            _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=client, mandor=mandor)

            read_model = build_portal_invoice_read_model(user)

            assert _numbers(read_model["invoices"]) == set()
        finally:
            transaction.rollback()


def test_portal_customer_financial_visibility_is_blocked(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "CUSTOMER")
            _create_mapping(user, PRINCIPAL_DELEGATE, client=client, mandor=mandor, location=location)
            _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=client, mandor=mandor)

            read_model = build_portal_invoice_read_model(user)

            assert read_model["allowed"] is False
            assert read_model["scope_mode"] == "PORTAL_CUSTOMER_FINANCIAL_BLOCKED"
            assert read_model["invoices"] == []
            assert read_model["totals"]["invoice_count"] == 0
        finally:
            transaction.rollback()


def test_cancelled_invoice_is_visible_but_excluded_from_active_outstanding(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "CANCELLED")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)

            active_invoice = _create_invoice(
                user,
                invoice_number=f"T-PFV-INV-{_suffix()}",
                client=client,
                mandor=mandor,
                total="100000",
                paid="10000",
                remaining="90000",
                status="PARTIAL",
            )
            cancelled_invoice = _create_invoice(
                user,
                invoice_number=f"T-PFV-INV-{_suffix()}",
                client=client,
                mandor=mandor,
                total="50000",
                paid="0",
                remaining="50000",
                status="CANCELLED",
            )

            read_model = build_portal_invoice_read_model(user)
            rows_by_number = {row["invoice_number"]: row for row in read_model["invoices"]}

            assert rows_by_number[active_invoice.invoice_number]["active_receivable"] is True
            assert rows_by_number[cancelled_invoice.invoice_number]["active_receivable"] is False
            assert read_model["totals"]["invoice_count"] == 2
            assert read_model["totals"]["active_invoice_count"] == 1
            assert read_model["totals"]["remaining_amount"] == Decimal("140000")
            assert read_model["totals"]["active_outstanding_amount"] == Decimal("90000")
        finally:
            transaction.rollback()


def test_portal_client_payment_history_only_returns_owned_invoice_payments(app, monkeypatch):
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(AssertionError("read model must not commit")))
    monkeypatch.setattr(db.session, "rollback", lambda: (_ for _ in ()).throw(AssertionError("read model must not rollback")))

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            owned_client, owned_pic, owned_mandor, _ = _create_client_family(user.branch, "PAYOWN")
            other_client, _, other_mandor, _ = _create_client_family(user.branch, "PAYOTHER")
            _create_mapping(user, PRINCIPAL_CLIENT, client=owned_client)

            owned_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=owned_client, mandor=owned_mandor, client_pic=owned_pic)
            other_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=other_client, mandor=other_mandor)

            read_model = build_portal_payment_history_read_model(user)
            invoice_numbers = {row["invoice_number"] for row in read_model["payments"]}

            assert read_model["allowed"] is True
            assert invoice_numbers == {owned_invoice.invoice_number}
            assert other_invoice.invoice_number not in invoice_numbers
            assert read_model["totals"]["payment_count"] == 1
            assert read_model["totals"]["payment_amount"] == Decimal("25000")
        finally:
            transaction.rollback()


def test_portal_mandor_payment_history_does_not_return_client_level_payments(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_SUBCLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "PAYMANDOR")
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=mandor)

            mandor_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=client, mandor=mandor)
            client_level_invoice = _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=client, mandor=None)

            read_model = build_portal_payment_history_read_model(user)
            invoice_numbers = {row["invoice_number"] for row in read_model["payments"]}

            assert invoice_numbers == {mandor_invoice.invoice_number}
            assert client_level_invoice.invoice_number not in invoice_numbers
        finally:
            transaction.rollback()


def test_portal_customer_payment_history_is_blocked(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, location = _create_client_family(user.branch, "PAYCUSTOMER")
            _create_mapping(user, PRINCIPAL_DELEGATE, client=client, mandor=mandor, location=location)
            _create_invoice(user, invoice_number=f"T-PFV-INV-{_suffix()}", client=client, mandor=mandor)

            read_model = build_portal_payment_history_read_model(user)

            assert read_model["allowed"] is False
            assert read_model["scope_mode"] == "PORTAL_CUSTOMER_PAYMENT_HISTORY_BLOCKED"
            assert read_model["payments"] == []
            assert read_model["totals"]["payment_count"] == 0
        finally:
            transaction.rollback()
