"""Fase 6: invoice otomatis per siklus kontrak (data di-rollback setiap test)."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.credit import BILLING_CASH, PARTY_MANDOR, CreditAccount
from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.finance import Invoice, InvoiceItem
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Driver, Mandor, User
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.pricing import PortionPrice
from app.models.system import Notification, PortalUserMapping
from app.services.auto_invoice_service import (
    AUTO_INVOICE_FAILED_TYPE,
    build_period_invoice_lines,
    is_cutoff_day,
    run_auto_invoice_preview,
    run_auto_period_invoices,
    run_invoice_payment_reminders,
    unresolved_failure_count,
)
from app.services.customer_contract_service import CONTRACT_STATUS_ACTIVE, create_customer_contract
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_CLIENT, PRINCIPAL_MANDOR

ANCHOR = date(2026, 10, 1)        # siklus 14 hari: hari potong 15 Okt, 29 Okt, ...
CUTOFF = date(2026, 10, 15)
NEXT_CUTOFF = date(2026, 10, 29)


@pytest.fixture
def ctx(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _ensure_accounts():
    for code, name, kind in (
        ("1004", "Piutang Usaha", "ASSET"), ("1005", "Piutang Karyawan", "ASSET"),
        ("4001", "Pendapatan Catering Proyek", "REVENUE"), ("4002", "Pendapatan Catering Harian", "REVENUE"),
        ("4003", "Pendapatan Warung", "REVENUE"), ("4004", "Pendapatan Lain-Lain", "REVENUE"),
        ("4005", "Pendapatan Ongkos Kirim", "REVENUE"),
    ):
        if not Account.query.filter_by(account_code=code).first():
            db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    db.session.flush()


def _fixtures(with_pic=True):
    _ensure_accounts()
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"F6-{suffix}", name=f"Cabang F6 {suffix}", is_active=True)
    client = Client(name=f"PT Proyek {suffix}", is_active=True)
    db.session.add_all([branch, client])
    db.session.flush()

    def user(role, name):
        row = User(branch_id=branch.id, full_name=name, username=f"{name.lower()}_{suffix}",
                   password_hash="hash", role=role, is_active=True)
        db.session.add(row)
        return row

    owner = user("OWNER", "Owner")
    mandor_user = user("PORTAL_SUBCLIENT", "Mandorportal")
    client_user = user("PORTAL_CLIENT", "Ptportal")
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {suffix}", is_active=True)
    db.session.add(mandor)
    db.session.flush()
    pic = None
    if with_pic:
        pic = ClientPic(client_id=client.id, name="Bu PIC", phone="0811", is_active=True)
        db.session.add(pic)
    location = DeliveryLocation(mandor_id=mandor.id, location_name=f"Proyek {suffix}", is_active=True)
    driver = Driver(branch_id=branch.id, name=f"Driver {suffix}", is_active=True)
    db.session.add_all([location, driver])
    db.session.flush()
    db.session.add_all([
        PortalUserMapping(user_id=mandor_user.id, principal_type=PRINCIPAL_MANDOR, mandor_id=mandor.id,
                          access_level=ACCESS_DRAFT_ORDER, is_active=True),
        PortalUserMapping(user_id=client_user.id, principal_type=PRINCIPAL_CLIENT, client_id=client.id,
                          access_level=ACCESS_DRAFT_ORDER, is_active=True),
        PortionPrice(branch_id=branch.id, price_per_portion=Decimal("25000"),
                     effective_from=date(2026, 1, 1), created_by=owner.id),
    ])
    db.session.flush()
    contract = create_customer_contract(
        branch_id=branch.id, client_id=client.id, title="Kontrak Proyek", start_date=ANCHOR,
        end_date=date(2026, 12, 31), payment_terms="Net 7", status=CONTRACT_STATUS_ACTIVE,
        created_by=owner.id, billing_cycle="BIWEEKLY", billing_anchor_date=ANCHOR, due_days=7,
    )
    return dict(branch=branch, client=client, owner=owner, mandor=mandor, mandor_user=mandor_user,
                client_user=client_user, location=location, driver=driver, contract=contract, pic=pic)


def _order(f, on_date, lunch=10, *, received=True):
    order = DailyOrder(order_number=f"DO-{uuid4().hex[:10]}", branch_id=f["branch"].id, order_date=on_date,
                       status="LOCKED", is_locked=True, created_by=f["owner"].id)
    db.session.add(order)
    db.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id, mandor_id=f["mandor"].id, delivery_location_id=f["location"].id,
        price_per_portion=Decimal("25000"), price_source="CONTRACT", lunch_qty=lunch, dinner_qty=0,
        total_qty=lunch, lunch_delivery_fee=Decimal("0"), dinner_delivery_fee=Decimal("0"),
    )
    db.session.add(detail)
    db.session.flush()
    delivery = Delivery(delivery_number=f"DEL-{uuid4().hex[:10]}", branch_id=f["branch"].id, delivery_date=on_date,
                        driver_id=f["driver"].id, status="PREPARING", notes="delivery_type=LUNCH",
                        created_by=f["owner"].id)
    db.session.add(delivery)
    db.session.flush()
    delivery_detail = DeliveryDetail(delivery_id=delivery.id, daily_order_detail_id=detail.id,
                                     mandor_id=f["mandor"].id, delivery_location_id=f["location"].id,
                                     planned_qty=lunch)
    db.session.add(delivery_detail)
    db.session.flush()
    if received:
        _receive(delivery_detail, lunch)
    return detail, delivery_detail


def _receive(delivery_detail, qty):
    delivery_detail.delivered_qty = qty
    # Lewat relasi (seperti update_delivery_receipt), supaya objek di sesi ikut tahu.
    delivery_detail.receipt = DeliveryReceipt(receiver_name="Mandor", receive_time=datetime(2026, 10, 14, 12, 0))
    delivery_detail.delivery.status = "DELIVERED"
    db.session.flush()


def _auto_invoices(f):
    return Invoice.query.filter_by(branch_id=f["branch"].id, mandor_id=f["mandor"].id,
                                   source_type="PERIOD_INVOICE").order_by(Invoice.id).all()


def test_cutoff_days_follow_contract_cycle(ctx):
    f = _fixtures()
    assert is_cutoff_day(f["contract"], CUTOFF)
    assert is_cutoff_day(f["contract"], NEXT_CUTOFF)
    assert not is_cutoff_day(f["contract"], date(2026, 10, 16))


def test_issues_only_received_deliveries_with_journal_due_date_and_notifications(ctx):
    f = _fixtures()
    _order(f, date(2026, 10, 3))
    _order(f, date(2026, 10, 7))
    _, pending = _order(f, date(2026, 10, 14), received=False)

    result = run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)

    assert len(result["issued"]) == 1 and not result["failed"]
    (invoice,) = _auto_invoices(f)
    assert invoice.total_amount == Decimal("500000.00")          # 2 x 10 porsi x Rp25.000
    assert (invoice.period_start, invoice.period_end) == (ANCHOR, date(2026, 10, 14))
    assert invoice.due_date == CUTOFF + timedelta(days=7)
    assert invoice.status == "DRAFT" and invoice.remaining_amount == invoice.total_amount

    journal = Journal.query.filter_by(reference_type="INVOICE", reference_id=invoice.id).one()
    lines = JournalDetail.query.filter_by(journal_id=journal.id).all()
    assert sum(Decimal(str(l.debit)) for l in lines) == sum(Decimal(str(l.credit)) for l in lines) == Decimal("500000")

    billed = Notification.query.filter_by(notification_type="INVOICE_ISSUED", target_user_id=f["client_user"].id).count()
    copy = Notification.query.filter_by(notification_type="INVOICE_COPY", target_user_id=f["mandor_user"].id).count()
    assert (billed, copy) == (1, 1)  # lewat client: PT ditagih, sub client dapat salinan

    # Pengiriman yang belum diterima ikut invoice berikutnya, tidak dobel.
    _receive(pending, 10)
    run_auto_period_invoices(branch_id=f["branch"].id, period_key=NEXT_CUTOFF.isoformat(), commit=False)
    first, second = _auto_invoices(f)
    assert second.total_amount == Decimal("250000.00")
    assert second.period_start == date(2026, 10, 15)
    sources = [item.source_id for item in InvoiceItem.query.filter(InvoiceItem.invoice_id.in_([first.id, second.id]))]
    assert len(sources) == len(set(sources)) == 3


def test_rerun_same_day_is_idempotent_and_non_cutoff_day_does_nothing(ctx):
    f = _fixtures()
    _order(f, date(2026, 10, 5))
    run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)
    again = run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)
    assert len(_auto_invoices(f)) == 1
    assert any(row["reason"] == "sudah terbit" for row in again["skipped"])

    g = _fixtures()
    _order(g, date(2026, 10, 5))
    assert run_auto_period_invoices(branch_id=g["branch"].id, period_key="2026-10-16", commit=False)["issued"] == []


def test_failure_is_flagged_red_and_cleared_after_fix(ctx):
    f = _fixtures(with_pic=False)  # client belum punya PIC resmi
    _order(f, date(2026, 10, 5))

    result = run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)
    assert result["issued"] == [] and len(result["failed"]) == 1
    assert _auto_invoices(f) == []
    assert unresolved_failure_count(f["branch"].id) == 1

    db.session.add(ClientPic(client_id=f["client"].id, name="PIC Baru", is_active=True))
    db.session.flush()
    result = run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)
    assert len(result["issued"]) == 1
    assert unresolved_failure_count(f["branch"].id) == 0


def test_prepaid_sub_client_is_not_billed_periodically(ctx):
    f = _fixtures()
    db.session.add(CreditAccount(branch_id=f["branch"].id, party_type=PARTY_MANDOR, party_id=f["mandor"].id,
                                 billing_mode=BILLING_CASH, credit_limit=0, payment_terms_days=0,
                                 deposit_percent=Decimal("0")))
    _order(f, date(2026, 10, 5))
    run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)
    assert _auto_invoices(f) == []


def test_preview_and_payment_reminders(ctx):
    f = _fixtures()
    _order(f, date(2026, 10, 5))
    preview = run_auto_invoice_preview(branch_id=f["branch"].id, period_key="2026-10-14", commit=False)
    assert preview["ready"] == 1 and preview["total"] == "250000.00"
    assert Notification.query.filter_by(branch_id=f["branch"].id, notification_type="AUTO_INVOICE_PREVIEW").count() >= 1

    run_auto_period_invoices(branch_id=f["branch"].id, period_key=CUTOFF.isoformat(), commit=False)
    (invoice,) = _auto_invoices(f)
    reminders = run_invoice_payment_reminders(
        branch_id=f["branch"].id, period_key=invoice.due_date.isoformat(), commit=False
    )
    assert {"invoice": invoice.invoice_number, "label": "H"} in reminders["sent"]
    assert Notification.query.filter_by(notification_type="INVOICE_PAYMENT_REMINDER",
                                        target_user_id=f["client_user"].id).count() == 1


def test_manual_period_builder_still_bills_unreceived(ctx):
    f = _fixtures()
    _order(f, date(2026, 10, 5), received=False)
    manual = build_period_invoice_lines(f["mandor"].id, ANCHOR, date(2026, 10, 14), f["branch"].id)
    auto = build_period_invoice_lines(f["mandor"].id, ANCHOR, date(2026, 10, 14), f["branch"].id, require_receipt=True)
    assert len(manual) == 1 and auto == []
