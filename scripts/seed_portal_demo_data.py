"""Seed integrated local demo data for external portal roles.

This script is idempotent and additive. It creates/updates only clearly named
demo accounts and records prefixed with PORTAL-DEMO so portal pages can be
tested with real ERP tables instead of empty placeholders.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from werkzeug.security import generate_password_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.canteen import CanteenSale, CanteenSaleItem, DebtPayment, WorkerDebt  # noqa: E402
from app.models.complaint import CustomerComplaint  # noqa: E402
from app.models.contract import CustomerContract  # noqa: E402
from app.models.finance import BankAccount, Invoice, InvoiceItem, Payment  # noqa: E402
from app.models.master import (  # noqa: E402
    Branch,
    Client,
    ClientPic,
    DeliveryLocation,
    Item,
    Mandor,
    User,
    Worker,
)
from app.models.operational import DailyOrder, DailyOrderDetail  # noqa: E402
from app.models.system import PortalOrderDraft, PortalUserMapping  # noqa: E402
from app.services.user_management_service import (  # noqa: E402
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_MANDOR,
    ROLE_PORTAL_PT,
)


PREFIX = "PORTAL-DEMO"
DEMO_PASSWORD = "portal12345"
DEMO_DATE = date(2026, 7, 28)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SAFE_APP_ENVS = {"development", "testing", "test", "local"}


def money(value) -> Decimal:
    return Decimal(str(value))


def active_database_info() -> dict:
    url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(url)
    return {
        "driver": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": (parsed.path or "").lstrip("/"),
        "has_password": bool(parsed.password),
    }


def assert_local_database() -> None:
    app_env = (os.environ.get("APP_ENV") or "development").strip().lower()
    info = active_database_info()
    if app_env not in SAFE_APP_ENVS:
        raise RuntimeError(f"Refusing to seed portal demo data outside local/dev/test env: APP_ENV={app_env}")
    if info["host"] and info["host"] not in LOCAL_HOSTS:
        raise RuntimeError(f"Refusing to seed portal demo data on non-local database host: {info['host']}")


def get_or_create(model, filters: dict, defaults: dict | None = None):
    row = model.query.filter_by(**filters).first()
    created = False
    if row is None:
        row = model(**filters, **(defaults or {}))
        db.session.add(row)
        db.session.flush()
        created = True
    return row, created


def ensure_branch() -> Branch:
    existing_pt_user = User.query.filter_by(username="userpt1").first()
    if existing_pt_user and existing_pt_user.branch:
        return existing_pt_user.branch

    branch, _created = get_or_create(
        Branch,
        {"code": f"{PREFIX}-BRANCH"},
        {
            "name": "Portal Demo Branch",
            "address": "Local portal demo branch",
            "phone": "0800000000",
            "is_active": True,
        },
    )
    return branch


def ensure_user(username: str, role: str, branch: Branch, full_name: str) -> User:
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(
            branch_id=branch.id,
            full_name=full_name,
            username=username,
            password_hash=generate_password_hash(DEMO_PASSWORD),
            role=role,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        return user

    user.branch_id = branch.id
    user.full_name = full_name
    user.role = role
    user.is_active = True
    user.password_hash = generate_password_hash(DEMO_PASSWORD)
    db.session.flush()
    return user


def ensure_master_data(branch: Branch, owner: User) -> dict:
    client, _ = get_or_create(
        Client,
        {"client_code": f"{PREFIX}-PT-001"},
        {
            "name": "PT Portal Demo Terpadu",
            "address": "Kawasan Industri Portal Demo",
            "phone": "081100000001",
            "is_active": True,
        },
    )
    client_pic, _ = get_or_create(
        ClientPic,
        {"client_id": client.id, "name": "PIC Portal Demo"},
        {
            "phone": "081100000002",
            "email": "pic.portal.demo@example.test",
            "position": "GA",
            "is_active": True,
        },
    )
    mandor, _ = get_or_create(
        Mandor,
        {"branch_id": branch.id, "client_id": client.id, "name": "Mandor Portal Demo"},
        {"phone": "081100000003", "is_active": True},
    )
    location, _ = get_or_create(
        DeliveryLocation,
        {"mandor_id": mandor.id, "location_name": "Lokasi Portal Demo"},
        {"description": "Gedung proyek portal demo", "is_active": True},
    )
    worker, _ = get_or_create(
        Worker,
        {"mandor_id": mandor.id, "worker_code": f"{PREFIX}-WORKER-001"},
        {
            "full_name": "Pekerja Portal Demo",
            "phone": "081100000004",
            "status": "ACTIVE",
            "notes": "Demo worker for portal mandor.",
        },
    )
    item, _ = get_or_create(
        Item,
        {"item_code": f"{PREFIX}-CANTEEN-ITEM"},
        {
            "item_name": "Snack Portal Demo",
            "category": "CANTEEN",
            "unit": "PCS",
            "minimum_stock": 0,
            "selling_price": money(15000),
            "is_stock_tracked": False,
            "is_active": True,
        },
    )
    bank, _ = get_or_create(
        BankAccount,
        {"account_number": f"{PREFIX}-BANK-001"},
        {
            "branch_id": branch.id,
            "account_name": "PT Idha Boga Pangan Mandiri",
            "bank_name": "Bank Portal Demo",
            "coa_account_code": "1-1001",
            "is_active": True,
        },
    )
    return {
        "client": client,
        "client_pic": client_pic,
        "mandor": mandor,
        "location": location,
        "worker": worker,
        "item": item,
        "bank": bank,
        "owner": owner,
    }


def ensure_mapping(user: User, *, principal_type: str, access_level: str, **ids) -> PortalUserMapping:
    filters = {
        "user_id": user.id,
        "principal_type": principal_type,
        "client_id": ids.get("client_id"),
        "mandor_id": ids.get("mandor_id"),
        "client_pic_id": ids.get("client_pic_id"),
        "delivery_location_id": ids.get("delivery_location_id"),
    }
    mapping, _ = get_or_create(
        PortalUserMapping,
        filters,
        {"access_level": access_level, "is_active": True, "created_by": user.id},
    )
    mapping.access_level = access_level
    mapping.is_active = True
    mapping.updated_at = datetime.utcnow()
    mapping.updated_by = user.id
    return mapping


def ensure_order_and_invoice(branch: Branch, owner: User, data: dict) -> Invoice:
    order, _ = get_or_create(
        DailyOrder,
        {"order_number": f"{PREFIX}-ORDER-001"},
        {
            "branch_id": branch.id,
            "order_date": DEMO_DATE,
            "status": "LOCKED",
            "is_locked": True,
            "locked_at": datetime.utcnow(),
            "notes": "Portal demo order.",
            "created_by": owner.id,
        },
    )
    order.branch_id = branch.id
    order.status = "LOCKED"
    order.is_locked = True

    detail, _ = get_or_create(
        DailyOrderDetail,
        {
            "daily_order_id": order.id,
            "mandor_id": data["mandor"].id,
            "delivery_location_id": data["location"].id,
        },
        {
            "price_per_portion": money(15000),
            "lunch_qty": 20,
            "dinner_qty": 0,
            "total_qty": 20,
            "notes": "Portal demo catering order detail.",
        },
    )
    detail.price_per_portion = money(15000)
    detail.lunch_qty = 20
    detail.total_qty = 20

    invoice, _ = get_or_create(
        Invoice,
        {"invoice_number": f"{PREFIX}-INV-001"},
        {
            "branch_id": branch.id,
            "invoice_date": DEMO_DATE,
            "due_date": DEMO_DATE + timedelta(days=14),
            "period_start": DEMO_DATE,
            "period_end": DEMO_DATE,
            "bill_to_type": "CLIENT",
            "client_id": data["client"].id,
            "mandor_id": data["mandor"].id,
            "client_pic_id": data["client_pic"].id,
            "client_name_snapshot": data["client"].name,
            "client_code_snapshot": data["client"].client_code,
            "client_pic_name_snapshot": data["client_pic"].name,
            "company_bank_name_snapshot": data["bank"].bank_name,
            "company_bank_account_number_snapshot": data["bank"].account_number,
            "company_bank_account_name_snapshot": data["bank"].account_name,
            "expected_payment_percent": 100,
            "total_amount": money(300000),
            "paid_amount": money(100000),
            "remaining_amount": money(200000),
            "status": "PARTIAL",
            "notes": "Portal demo invoice integrated with PT and mandor scope.",
            "source_type": "PORTAL_DEMO",
            "source_order_id": order.id,
            "input_source": "REALTIME",
            "created_by": owner.id,
        },
    )
    invoice.branch_id = branch.id
    invoice.client_id = data["client"].id
    invoice.mandor_id = data["mandor"].id
    invoice.client_pic_id = data["client_pic"].id
    invoice.total_amount = money(300000)
    invoice.paid_amount = money(100000)
    invoice.remaining_amount = money(200000)
    invoice.status = "PARTIAL"

    item, _ = get_or_create(
        InvoiceItem,
        {"invoice_id": invoice.id, "source_type": "PORTAL_DEMO", "source_id": detail.id},
        {
            "item_type": "CATERING",
            "description": "20 porsi makan siang Portal Demo",
            "qty": money(20),
            "unit_price": money(15000),
            "subtotal": money(300000),
            "input_source": "REALTIME",
        },
    )
    item.qty = money(20)
    item.unit_price = money(15000)
    item.subtotal = money(300000)

    payment, _ = get_or_create(
        Payment,
        {"payment_number": f"{PREFIX}-PAY-001"},
        {
            "branch_id": branch.id,
            "payment_date": DEMO_DATE,
            "invoice_id": invoice.id,
            "bank_account_id": data["bank"].id,
            "payment_method": "TRANSFER",
            "amount": money(100000),
            "reference_number": f"{PREFIX}-PAY-REF",
            "notes": "Portal demo partial payment.",
            "received_by": owner.id,
        },
    )
    payment.invoice_id = invoice.id
    payment.amount = money(100000)
    payment.bank_account_id = data["bank"].id
    return invoice


def ensure_contract(branch: Branch, owner: User, data: dict) -> CustomerContract:
    contract, _ = get_or_create(
        CustomerContract,
        {"contract_number": f"{PREFIX}-CONTRACT-001"},
        {
            "branch_id": branch.id,
            "client_id": data["client"].id,
            "client_pic_id": data["client_pic"].id,
            "title": "Kontrak Catering Portal Demo",
            "start_date": DEMO_DATE,
            "end_date": date(2026, 12, 31),
            "payment_terms": "NET 14",
            "credit_limit": money(5000000),
            "status": "ACTIVE",
            "version_no": 1,
            "notes": "Demo contract for PT portal page.",
            "created_by": owner.id,
        },
    )
    contract.branch_id = branch.id
    contract.client_id = data["client"].id
    contract.client_pic_id = data["client_pic"].id
    contract.status = "ACTIVE"
    contract.credit_limit = money(5000000)
    return contract


def ensure_worker_debt(branch: Branch, owner: User, data: dict) -> WorkerDebt:
    sale = CanteenSale.query.filter_by(branch_id=branch.id, notes=f"{PREFIX}-CANTEEN-SALE-001").first()
    if sale is None:
        sale = CanteenSale(
            branch_id=branch.id,
            sale_date=DEMO_DATE,
            sale_type="DEBT",
            total_amount=money(45000),
            payment_method="CREDIT",
            buyer_type="WORKER",
            buyer_name=data["worker"].full_name,
            buyer_company=data["client"].name,
            buyer_phone=data["worker"].phone,
            is_external_debt=False,
            notes=f"{PREFIX}-CANTEEN-SALE-001",
            created_by=owner.id,
        )
        db.session.add(sale)
        db.session.flush()
    sale.total_amount = money(45000)

    sale_item = CanteenSaleItem.query.filter_by(sale_id=sale.id, item_id=data["item"].id).first()
    if sale_item is None:
        sale_item = CanteenSaleItem(sale_id=sale.id, item_id=data["item"].id)
        db.session.add(sale_item)
    sale_item.qty = 3
    sale_item.price = money(15000)
    sale_item.subtotal = money(45000)

    debt = WorkerDebt.query.filter_by(sale_id=sale.id, worker_id=data["worker"].id).first()
    if debt is None:
        debt = WorkerDebt(
            branch_id=branch.id,
            worker_id=data["worker"].id,
            sale_id=sale.id,
            debt_amount=money(45000),
            status="UNPAID",
        )
        db.session.add(debt)
    debt.debt_amount = money(45000)
    debt.status = "UNPAID"
    db.session.flush()

    payment = DebtPayment.query.filter_by(worker_debt_id=debt.id, payment_reference=f"{PREFIX}-DEBT-PAY-001").first()
    if payment is None:
        payment = DebtPayment(
            worker_debt_id=debt.id,
            payment_date=DEMO_DATE,
            amount=money(15000),
            payment_method="CASH",
            cash_bank_account_id=data["bank"].id,
            payment_reference=f"{PREFIX}-DEBT-PAY-001",
            notes="Portal demo worker debt installment.",
            created_by=owner.id,
        )
        db.session.add(payment)
    payment.amount = money(15000)
    return debt


def ensure_portal_drafts(branch: Branch, users: dict, data: dict) -> None:
    draft, _ = get_or_create(
        PortalOrderDraft,
        {"user_id": users["mandor"].id, "idempotency_key": f"{PREFIX}-MANDOR-DRAFT-001"},
        {
            "branch_id": branch.id,
            "client_id": data["client"].id,
            "mandor_id": data["mandor"].id,
            "delivery_location_id": data["location"].id,
            "order_date": DEMO_DATE + timedelta(days=1),
            "meal_type": "LUNCH",
            "portion_qty": 25,
            "notes": "Portal demo draft order waiting admin confirmation.",
            "status": "PENDING_ADMIN_CONFIRMATION",
            "submitted_at": datetime.utcnow(),
        },
    )
    draft.branch_id = branch.id
    draft.client_id = data["client"].id
    draft.mandor_id = data["mandor"].id
    draft.delivery_location_id = data["location"].id
    draft.status = "PENDING_ADMIN_CONFIRMATION"


def ensure_customer_complaint(branch: Branch, users: dict, data: dict) -> CustomerComplaint:
    complaint, _ = get_or_create(
        CustomerComplaint,
        {"complaint_number": f"{PREFIX}-CMP-001"},
        {
            "branch_id": branch.id,
            "category": "LATE_DELIVERY",
            "status": "OPEN",
            "title": "Pengiriman terlambat",
            "description": "Demo komplain pelanggan portal untuk alur Customer Success.",
            "client_id": data["client"].id,
            "mandor_id": data["mandor"].id,
            "submitted_by": users["customer"].id,
            "submitted_at": datetime.utcnow(),
        },
    )
    complaint.branch_id = branch.id
    complaint.client_id = data["client"].id
    complaint.mandor_id = data["mandor"].id
    complaint.submitted_by = users["customer"].id
    complaint.status = "OPEN"
    return complaint


def seed() -> dict:
    assert_local_database()
    app = create_app()
    with app.app_context():
        branch = ensure_branch()
        owner = (
            User.query.filter_by(role="OWNER", is_active=True).order_by(User.id.asc()).first()
            or User.query.filter_by(role="ADMIN", is_active=True).order_by(User.id.asc()).first()
        )
        if owner is None:
            owner = ensure_user("portaladmin1", "OWNER", branch, "Portal Demo Owner")

        users = {
            "pt": ensure_user("userpt1", ROLE_PORTAL_PT, branch, "User PT Portal Demo"),
            "mandor": ensure_user("usermandor1", ROLE_PORTAL_MANDOR, branch, "User Mandor Portal Demo"),
            "customer": ensure_user("usercustomer1", ROLE_PORTAL_CUSTOMER, branch, "User Customer Portal Demo"),
        }
        data = ensure_master_data(branch, owner)

        ensure_mapping(users["pt"], principal_type="CLIENT", client_id=data["client"].id, access_level="READ_ONLY")
        ensure_mapping(users["mandor"], principal_type="MANDOR", mandor_id=data["mandor"].id, access_level="DRAFT_ORDER")
        ensure_mapping(users["customer"], principal_type="MANDOR", mandor_id=data["mandor"].id, access_level="READ_ONLY")

        invoice = ensure_order_and_invoice(branch, owner, data)
        contract = ensure_contract(branch, owner, data)
        debt = ensure_worker_debt(branch, owner, data)
        ensure_portal_drafts(branch, users, data)
        complaint = ensure_customer_complaint(branch, users, data)

        db.session.commit()

        info = active_database_info()
        return {
            "database": {
                "driver": info["driver"],
                "host": info["host"],
                "port": info["port"],
                "database": info["database"],
            },
            "branch": {"id": branch.id, "code": branch.code, "name": branch.name},
            "users": {
                "pt": users["pt"].username,
                "mandor": users["mandor"].username,
                "customer": users["customer"].username,
                "default_password_for_new_users": DEMO_PASSWORD,
            },
            "master": {
                "client": data["client"].name,
                "mandor": data["mandor"].name,
                "location": data["location"].location_name,
                "worker": data["worker"].full_name,
            },
            "records": {
                "invoice": invoice.invoice_number,
                "contract": contract.contract_number,
                "worker_debt_id": debt.id,
                "complaint": complaint.complaint_number,
            },
            "urls": {
                "pt_contracts": "/portal/pt/contracts",
                "pt_invoices": "/portal/pt/invoices",
                "mandor_debts": "/portal/mandor/canteen-debts",
                "mandor_order": "/portal/mandor/order",
                "customer_complaints": "/portal/customer/complaints",
            },
        }


if __name__ == "__main__":
    result = seed()
    print("PORTAL DEMO SEED PASS")
    for section, value in result.items():
        print(f"{section}: {value}")
