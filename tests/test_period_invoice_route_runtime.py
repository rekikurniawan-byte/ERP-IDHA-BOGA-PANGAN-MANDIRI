from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.finance import Invoice, InvoiceItem
from app.models.master import DeliveryLocation, Mandor, Menu, User
from app.models.operational import DailyOrder, DailyOrderDetail
from tools.seed_dynamic_route_smoke_data import seed as seed_qa_smoke_data


def _owner_user():
    return (
        User.query.filter_by(role="OWNER", is_active=True).order_by(User.id.asc()).first()
        or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
    )


def _login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_period_invoice_preview_renders_ready_and_already_invoiced_branches(app):
    """Exercise route-template-service integration for the period invoice preview."""
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        seed_qa_smoke_data()
        user = _owner_user()
        mandor = Mandor.query.filter(Mandor.client_id.isnot(None), Mandor.branch_id == user.branch_id).order_by(Mandor.id.asc()).first()
        menu = Menu.query.filter_by(branch_id=user.branch_id, is_active=True).order_by(Menu.id.asc()).first()
        location = DeliveryLocation.query.filter_by(mandor_id=mandor.id, is_active=True).order_by(DeliveryLocation.id.asc()).first()
        assert user and mandor and menu and location

        unique = uuid4().hex[:10].upper()
        order_date = date(2098, 1, 15)
        transaction = db.session.begin_nested()
        try:
            order = DailyOrder(
                order_number=f"QA-ADV-{unique}",
                branch_id=user.branch_id,
                order_date=order_date,
                status="LOCKED",
                is_locked=True,
                locked_at=datetime(2098, 1, 15, 8, 0),
                lunch_menu_id=menu.id,
                notes="QA adversarial period invoice route test",
                created_by=user.id,
            )
            db.session.add(order)
            db.session.flush()

            detail = DailyOrderDetail(
                daily_order_id=order.id,
                mandor_id=mandor.id,
                delivery_location_id=location.id,
                price_per_portion=Decimal("17000"),
                lunch_qty=3,
                dinner_qty=2,
                total_qty=5,
                notes="QA adversarial billable line",
            )
            db.session.add(detail)
            db.session.flush()

            with app.test_client() as client:
                _login(client, user)
                response = client.post(
                    "/finance/invoices/generate-period",
                    data={
                        "mandor_id": str(mandor.id),
                        "period_start": order_date.isoformat(),
                        "period_end": order_date.isoformat(),
                    },
                )
                html = response.get_data(as_text=True)
                assert response.status_code == 200
                assert "Rincian Lihat Data Invoice Periode" in html
                assert order.order_number in html
                assert "Terkunci: Siang 3, Sore 2" in html
                assert ">Masuk<" in html
                assert ">true<" not in html and ">false<" not in html

                invoice = Invoice(
                    branch_id=user.branch_id,
                    invoice_number=f"QA-ADV-INV-{unique}",
                    invoice_date=order_date,
                    due_date=order_date + timedelta(days=7),
                    period_start=order_date,
                    period_end=order_date,
                    bill_to_type="CLIENT",
                    client_id=mandor.client_id,
                    mandor_id=mandor.id,
                    total_amount=Decimal("85000"),
                    paid_amount=Decimal("0"),
                    remaining_amount=Decimal("85000"),
                    status="DRAFT",
                    source_type="PERIOD_INVOICE",
                    source_order_id=9000000 + detail.id,
                    input_source="REALTIME",
                    created_by=user.id,
                )
                db.session.add(invoice)
                db.session.flush()
                db.session.add(
                    InvoiceItem(
                        invoice_id=invoice.id,
                        item_type="CATERING",
                        description="QA adversarial already invoiced marker",
                        qty=Decimal("5"),
                        unit_price=Decimal("17000"),
                        subtotal=Decimal("85000"),
                        source_type="ORDER_DETAIL",
                        source_id=detail.id,
                        input_source="REALTIME",
                    )
                )
                db.session.flush()

                blocked_response = client.post(
                    "/finance/invoices/generate-period",
                    data={
                        "mandor_id": str(mandor.id),
                        "period_start": order_date.isoformat(),
                        "period_end": order_date.isoformat(),
                    },
                )
                blocked_html = blocked_response.get_data(as_text=True)
                assert blocked_response.status_code == 200
                assert order.order_number in blocked_html
                assert "Terkunci: Siang 3, Sore 2" in blocked_html
                assert ">Dilewati<" in blocked_html
                assert "Sudah pernah masuk invoice periode" in blocked_html
                assert ">true<" not in blocked_html and ">false<" not in blocked_html
        finally:
            transaction.rollback()
