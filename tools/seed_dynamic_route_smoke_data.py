"""Create local QA sample data for dynamic route smoke tests.

The data is deliberately prefixed with ``QA-SMOKE`` and is idempotent. It exists
only to exercise detail/download pages in an isolated local database so
route/template errors are caught before manual clicking.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.accounting import (  # noqa: E402
    Account,
    AssetFinancingContract,
    AssetInstallmentSchedule,
    FixedAsset,
    FixedAssetPurchase,
    Journal,
    JournalDetail,
    PeriodClosing,
)
from app.models.canteen import CashDaily, CanteenExternalReceivable, CanteenSale, CanteenSaleItem, WorkerDebt  # noqa: E402
from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt  # noqa: E402
from app.models.field_transaction import FieldCounterparty, FieldTransaction, FieldTransactionAttachment  # noqa: E402
from app.models.finance import (  # noqa: E402
    AdvanceTransaction,
    BankAccount,
    CashBankTransaction,
    Invoice,
    InvoiceItem,
    OperationalExpense,
    Payment,
    SupplierBill,
    SupplierPayment,
    TransportVehicleExpense,
)
from app.models.hr import Payroll, PayrollDetail  # noqa: E402
from app.models.logistics import ItemRequest, ItemRequestDetail, Procurement, ProcurementItem, StockMovement  # noqa: E402
from app.models.master import (  # noqa: E402
    Branch,
    Client,
    ClientPic,
    DeliveryLocation,
    Driver,
    Employee,
    Item,
    ItemCostProfile,
    Mandor,
    Menu,
    OverheadProfile,
    PackagingProfile,
    RecipeHeader,
    RecipeItem,
    Supplier,
    User,
    Worker,
)
from app.models.operational import (  # noqa: E402
    DailyOrder,
    DailyOrderDetail,
    OrderHppSnapshot,
    OrderHppSnapshotComponent,
    OrderHppSnapshotLine,
    OrderHppStockConsumption,
    OrderHppStockConsumptionLine,
)
from app.models.production import Production, ProductionDetail  # noqa: E402
from app.models.system import DigitalAttachment  # noqa: E402
from app.services.digital_attachment_service import get_attachment_file_path, get_upload_root  # noqa: E402


PREFIX = "QA-SMOKE"
SMOKE_DATE = date(2026, 7, 27)
SMOKE_DATETIME = datetime(2026, 7, 27, 8, 0, 0)
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF\n"


def _money(value: str | int | float) -> Decimal:
    return Decimal(str(value))


def _first_user() -> User:
    user = (
        User.query.filter_by(role="OWNER", is_active=True).order_by(User.id.asc()).first()
        or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
    )
    if user:
        return user

    branch, _ = _get_or_create(
        Branch,
        {"code": f"{PREFIX}-BRANCH"},
        {
            "name": "QA Smoke Branch",
            "address": "Local test branch",
            "phone": "0800000000",
            "is_active": True,
        },
    )
    user, _ = _get_or_create(
        User,
        {"username": f"{PREFIX.lower()}-owner"},
        {
            "branch_id": branch.id,
            "full_name": "QA Smoke Owner",
            "password_hash": generate_password_hash("qa-smoke-password"),
            "role": "OWNER",
            "is_active": True,
        },
    )
    return user


def _get_or_create(model, filters: dict, defaults: dict | None = None):
    row = model.query.filter_by(**filters).first()
    created = False
    if not row:
        row = model(**filters, **(defaults or {}))
        db.session.add(row)
        db.session.flush()
        created = True
    return row, created


def _ensure_pdf_attachment(
    *,
    branch_id: int,
    user_id: int,
    module: str,
    reference_type: str,
    reference_id: int,
    attachment_type: str,
) -> DigitalAttachment:
    existing = (
        DigitalAttachment.query.filter_by(
            branch_id=branch_id,
            module=module,
            reference_type=reference_type,
            reference_id=reference_id,
            attachment_type=attachment_type,
            is_deleted=False,
        )
        .order_by(DigitalAttachment.id.asc())
        .first()
    )
    if existing:
        try:
            get_attachment_file_path(existing)
            return existing
        except FileNotFoundError:
            pass

    upload_root = get_upload_root()
    stored_filename = f"{PREFIX}_{module}_{reference_type}_{reference_id}.pdf".replace("/", "_")
    target_path = upload_root / stored_filename
    target_path.write_bytes(PDF_BYTES)
    digest = hashlib.sha256(PDF_BYTES).hexdigest()

    attachment = DigitalAttachment.query.filter_by(stored_filename=stored_filename).first()
    if not attachment:
        attachment = DigitalAttachment(stored_filename=stored_filename)
        db.session.add(attachment)

    attachment.branch_id = branch_id
    attachment.module = module
    attachment.reference_type = reference_type
    attachment.reference_id = reference_id
    attachment.attachment_type = attachment_type
    attachment.original_filename = f"{stored_filename}"
    attachment.file_path = stored_filename
    attachment.mime_type = "application/pdf"
    attachment.file_size = len(PDF_BYTES)
    attachment.sha256_hash = digest
    attachment.notes = "QA smoke attachment sample."
    attachment.uploaded_by = user_id
    attachment.is_deleted = False
    db.session.flush()
    return attachment


def seed() -> dict[str, int]:
    user = _first_user()
    branch_id = user.branch_id
    user_id = user.id
    created_counts: dict[str, int] = {}

    def count(name: str, created: bool = True):
        if created:
            created_counts[name] = created_counts.get(name, 0) + 1

    account_cash, created = _get_or_create(
        Account,
        {"account_code": "QA1000"},
        {"account_name": "QA Smoke Cash", "account_type": "ASSET", "is_active": True},
    )
    count("account", created)
    account_equity, created = _get_or_create(
        Account,
        {"account_code": "QA3000"},
        {"account_name": "QA Smoke Equity", "account_type": "EQUITY", "is_active": True},
    )
    count("account", created)

    client, created = _get_or_create(
        Client,
        {"client_code": f"{PREFIX}-CLIENT"},
        {"name": "QA Smoke Client", "address": "Alamat QA", "phone": "0800000000", "is_active": True},
    )
    count("client", created)
    client_pic, created = _get_or_create(
        ClientPic,
        {"client_id": client.id, "name": "QA Smoke PIC"},
        {"phone": "0800000001", "email": "qa@example.local", "position": "PIC", "is_active": True},
    )
    count("client_pic", created)
    mandor, created = _get_or_create(
        Mandor,
        {"branch_id": branch_id, "name": "QA Smoke Mandor"},
        {"client_id": client.id, "phone": "0800000002", "is_active": True},
    )
    count("mandor", created)
    location, created = _get_or_create(
        DeliveryLocation,
        {"mandor_id": mandor.id, "location_name": "QA Smoke Site"},
        {"description": "Lokasi QA smoke", "is_active": True},
    )
    count("location", created)
    worker, created = _get_or_create(
        Worker,
        {"mandor_id": mandor.id, "worker_code": f"{PREFIX}-WORKER"},
        {"full_name": "QA Smoke Worker", "phone": "0800000003", "status": "ACTIVE", "notes": "QA smoke"},
    )
    count("worker", created)
    driver, created = _get_or_create(
        Driver,
        {"branch_id": branch_id, "name": "QA Smoke Driver"},
        {"phone": "0800000004", "license_number": f"{PREFIX}-SIM", "is_active": True},
    )
    count("driver", created)
    supplier, created = _get_or_create(
        Supplier,
        {"branch_id": branch_id, "supplier_code": f"{PREFIX}-SUP"},
        {
            "supplier_name": "QA Smoke Supplier",
            "supplier_type": "GENERAL",
            "contact_person": "QA Supplier PIC",
            "phone": "0800000005",
            "is_active": True,
        },
    )
    count("supplier", created)
    item, created = _get_or_create(
        Item,
        {"item_code": f"{PREFIX}-ITEM"},
        {
            "item_name": "QA Smoke Item",
            "category": "BAHAN",
            "unit": "kg",
            "minimum_stock": _money("1"),
            "selling_price": _money("10000"),
            "is_stock_tracked": True,
            "is_active": True,
        },
    )
    count("item", created)
    _, created = _get_or_create(
        ItemCostProfile,
        {"item_id": item.id},
        {
            "branch_id": branch_id,
            "purchase_unit": "kg",
            "purchase_qty": _money("1"),
            "base_unit": "kg",
            "conversion_factor": _money("1"),
            "yield_percentage": _money("100"),
            "waste_percentage": _money("0"),
            "standard_purchase_price": _money("5000"),
            "effective_cost_per_base_unit": _money("5000"),
            "cost_source": "STANDARD",
            "updated_by": user_id,
        },
    )
    count("item_cost_profile", created)
    menu, created = _get_or_create(
        Menu,
        {"branch_id": branch_id, "menu_code": f"{PREFIX}-MENU"},
        {"menu_name": "QA Smoke Menu", "menu_type": "CATERING", "default_selling_price": _money("15000"), "is_active": True},
    )
    count("menu", created)
    recipe, created = _get_or_create(
        RecipeHeader,
        {"branch_id": branch_id, "menu_id": menu.id},
        {"recipe_name": "QA Smoke Recipe", "base_portion": _money("1"), "recipe_status": "DRAFT", "version_label": "v1", "updated_by": user_id},
    )
    count("recipe", created)
    _, created = _get_or_create(
        RecipeItem,
        {"recipe_id": recipe.id, "item_id": item.id, "unit": "kg"},
        {"qty_per_portion": _money("0.1"), "notes": "QA smoke"},
    )
    count("recipe_item", created)
    packaging, created = _get_or_create(
        PackagingProfile,
        {"branch_id": branch_id, "profile_code": f"{PREFIX}-PACK"},
        {"profile_name": "QA Smoke Packaging", "cost_per_portion": _money("1000"), "is_active": True, "updated_by": user_id},
    )
    count("packaging", created)
    overhead, created = _get_or_create(
        OverheadProfile,
        {"branch_id": branch_id, "profile_code": f"{PREFIX}-OVH"},
        {
            "profile_name": "QA Smoke Overhead",
            "gas_cost_per_portion": _money("100"),
            "electricity_cost_per_portion": _money("100"),
            "water_cost_per_portion": _money("50"),
            "labor_cost_per_portion": _money("200"),
            "spices_cost_per_portion": _money("100"),
            "other_cost_per_portion": _money("50"),
            "is_active": True,
            "updated_by": user_id,
        },
    )
    count("overhead", created)
    bank, created = _get_or_create(
        BankAccount,
        {"branch_id": branch_id, "account_number": f"{PREFIX}-BANK-001"},
        {"account_name": "QA Smoke Bank", "bank_name": "Bank QA", "coa_account_code": "QA1000", "is_active": True},
    )
    count("bank", created)

    journal, created = _get_or_create(
        Journal,
        {"journal_number": f"{PREFIX}-JRN-001"},
        {"journal_date": SMOKE_DATE, "reference_type": "QA_SMOKE", "reference_id": 900001, "description": "QA smoke balanced journal", "created_by": user_id},
    )
    count("journal", created)
    _, created = _get_or_create(JournalDetail, {"journal_id": journal.id, "account_id": account_cash.id}, {"debit": _money("1000"), "credit": _money("0")})
    count("journal_detail", created)
    _, created = _get_or_create(JournalDetail, {"journal_id": journal.id, "account_id": account_equity.id}, {"debit": _money("0"), "credit": _money("1000")})
    count("journal_detail", created)

    _, created = _get_or_create(
        PeriodClosing,
        {"branch_id": branch_id, "period_year": 2099, "period_month": 12},
        {
            "closing_number": f"{PREFIX}-CLS-209912",
            "period_start": date(2099, 12, 1),
            "period_end": date(2099, 12, 31),
            "closing_date": date(2099, 12, 31),
            "revenue_total": _money("1000"),
            "expense_total": _money("500"),
            "net_income": _money("500"),
            "retained_earnings_account_code": "3002",
            "status": "POSTED",
            "journal_id": journal.id,
            "created_by": user_id,
        },
    )
    count("period_closing", created)

    daily_order, created = _get_or_create(
        DailyOrder,
        {"order_number": f"{PREFIX}-ORDER-001"},
        {
            "branch_id": branch_id,
            "order_date": SMOKE_DATE,
            "status": "LOCKED",
            "is_locked": True,
            "locked_at": SMOKE_DATETIME,
            "lunch_menu_id": menu.id,
            "packaging_profile_id": packaging.id,
            "overhead_profile_id": overhead.id,
            "notes": "QA smoke order",
            "created_by": user_id,
        },
    )
    count("daily_order", created)
    order_detail, created = _get_or_create(
        DailyOrderDetail,
        {"daily_order_id": daily_order.id, "mandor_id": mandor.id, "delivery_location_id": location.id},
        {"price_per_portion": _money("15000"), "lunch_qty": 10, "dinner_qty": 0, "total_qty": 10, "notes": "QA smoke detail"},
    )
    count("daily_order_detail", created)
    snapshot, created = _get_or_create(
        OrderHppSnapshot,
        {"snapshot_number": f"{PREFIX}-HPP-001"},
        {
            "branch_id": branch_id,
            "daily_order_id": daily_order.id,
            "snapshot_date": SMOKE_DATETIME,
            "status": "LOCKED",
            "total_portion": _money("10"),
            "food_cost_total": _money("50000"),
            "packaging_cost_total": _money("10000"),
            "overhead_cost_total": _money("6000"),
            "hpp_total": _money("66000"),
            "hpp_per_portion": _money("6600"),
            "revenue_total": _money("150000"),
            "gross_margin_amount": _money("84000"),
            "gross_margin_percentage": _money("56"),
            "created_by": user_id,
        },
    )
    count("hpp_snapshot", created)
    snapshot_line, created = _get_or_create(
        OrderHppSnapshotLine,
        {"snapshot_id": snapshot.id, "meal_type": "LUNCH"},
        {
            "menu_id": menu.id,
            "menu_code_snapshot": menu.menu_code,
            "menu_name_snapshot": menu.menu_name,
            "recipe_id": recipe.id,
            "recipe_name_snapshot": recipe.recipe_name,
            "packaging_profile_id": packaging.id,
            "packaging_name_snapshot": packaging.profile_name,
            "overhead_profile_id": overhead.id,
            "overhead_name_snapshot": overhead.profile_name,
            "portion_qty": _money("10"),
            "selling_price_per_portion": _money("15000"),
            "food_cost_total": _money("50000"),
            "packaging_cost_total": _money("10000"),
            "overhead_cost_total": _money("6000"),
            "hpp_total": _money("66000"),
            "hpp_per_portion": _money("6600"),
            "revenue_total": _money("150000"),
            "gross_margin_amount": _money("84000"),
            "gross_margin_percentage": _money("56"),
            "calculation_status": "COMPLETE",
        },
    )
    count("hpp_snapshot_line", created)
    _, created = _get_or_create(
        OrderHppSnapshotComponent,
        {"snapshot_line_id": snapshot_line.id, "component_type": "FOOD", "item_id": item.id},
        {
            "item_code_snapshot": item.item_code,
            "item_name_snapshot": item.item_name,
            "qty_per_portion": _money("0.1"),
            "recipe_unit": "kg",
            "base_unit": "kg",
            "conversion_multiplier": _money("1"),
            "base_qty_per_portion": _money("0.1"),
            "base_qty_total": _money("1"),
            "cost_per_base_unit_snapshot": _money("5000"),
            "cost_per_portion": _money("500"),
            "cost_total": _money("5000"),
        },
    )
    count("hpp_component", created)
    consumption, created = _get_or_create(
        OrderHppStockConsumption,
        {"snapshot_id": snapshot.id},
        {
            "branch_id": branch_id,
            "daily_order_id": daily_order.id,
            "consumption_number": f"{PREFIX}-CONS-001",
            "consumption_date": SMOKE_DATE,
            "status": "COMMITTED",
            "total_item_count": 1,
            "total_required_qty": _money("1"),
            "total_cost": _money("5000"),
            "committed_by": user_id,
            "committed_at": SMOKE_DATETIME,
        },
    )
    count("hpp_consumption", created)
    _, created = _get_or_create(
        OrderHppStockConsumptionLine,
        {"consumption_id": consumption.id, "item_id": item.id},
        {
            "item_code_snapshot": item.item_code,
            "item_name_snapshot": item.item_name,
            "stock_unit_snapshot": item.unit,
            "required_stock_qty": _money("1"),
            "stock_before_qty": _money("10"),
            "stock_after_qty": _money("9"),
            "estimated_cost_total": _money("5000"),
            "component_count": 1,
        },
    )
    count("hpp_consumption_line", created)

    delivery, created = _get_or_create(
        Delivery,
        {"delivery_number": f"{PREFIX}-DLV-001"},
        {"branch_id": branch_id, "delivery_date": SMOKE_DATE, "driver_id": driver.id, "status": "PREPARING", "created_by": user_id},
    )
    count("delivery", created)
    delivery_detail, created = _get_or_create(
        DeliveryDetail,
        {"delivery_id": delivery.id, "daily_order_detail_id": order_detail.id},
        {"mandor_id": mandor.id, "delivery_location_id": location.id, "planned_qty": 10, "delivered_qty": 10, "shortage_qty": 0, "sla_status": "ON_TIME"},
    )
    count("delivery_detail", created)
    receipt, created = _get_or_create(
        DeliveryReceipt,
        {"delivery_detail_id": delivery_detail.id},
        {"receiver_name": "QA Smoke Receiver", "receive_time": SMOKE_DATETIME, "notes": "QA smoke receipt"},
    )
    count("delivery_receipt", created)
    _ensure_pdf_attachment(branch_id=branch_id, user_id=user_id, module="DELIVERY", reference_type="DELIVERY_RECEIPT", reference_id=receipt.id, attachment_type="RECEIPT")

    procurement, created = _get_or_create(
        Procurement,
        {"procurement_number": f"{PREFIX}-PROC-001"},
        {
            "purchase_place": "QA Smoke Store",
            "branch_id": branch_id,
            "supplier_id": supplier.id,
            "procurement_date": SMOKE_DATE,
            "purchase_type": "CASH",
            "supplier_name": supplier.supplier_name,
            "total_amount": _money("50000"),
            "notes": "QA smoke procurement",
            "created_by": user_id,
        },
    )
    count("procurement", created)
    _, created = _get_or_create(
        ProcurementItem,
        {"procurement_id": procurement.id, "item_id": item.id},
        {"qty": _money("10"), "unit_price": _money("5000"), "subtotal": _money("50000")},
    )
    count("procurement_item", created)
    _, created = _get_or_create(
        StockMovement,
        {"branch_id": branch_id, "reference_type": "PEMBELIAN_BARANG", "reference_id": procurement.id, "item_id": item.id},
        {"movement_date": SMOKE_DATE, "movement_type": "IN", "qty": _money("10"), "notes": "QA smoke stock movement", "created_by": user_id},
    )
    count("stock_movement", created)
    _ensure_pdf_attachment(branch_id=branch_id, user_id=user_id, module="PROCUREMENT", reference_type="PROCUREMENT", reference_id=procurement.id, attachment_type="NOTA_PEMBELIAN")

    supplier_bill, created = _get_or_create(
        SupplierBill,
        {"procurement_id": procurement.id},
        {
            "branch_id": branch_id,
            "bill_number": f"{PREFIX}-SB-001",
            "supplier_id": supplier.id,
            "bill_date": SMOKE_DATE,
            "due_date": SMOKE_DATE + timedelta(days=14),
            "supplier_name": supplier.supplier_name,
            "total_amount": _money("50000"),
            "paid_amount": _money("10000"),
            "remaining_amount": _money("40000"),
            "status": "OPEN",
            "created_by": user_id,
        },
    )
    count("supplier_bill", created)
    supplier_payment, created = _get_or_create(
        SupplierPayment,
        {"payment_number": f"{PREFIX}-SPAY-001"},
        {
            "branch_id": branch_id,
            "supplier_bill_id": supplier_bill.id,
            "payment_date": SMOKE_DATE,
            "bank_account_id": bank.id,
            "payment_method": "TRANSFER",
            "amount": _money("10000"),
            "reference_number": f"{PREFIX}-SPAY-REF",
            "paid_by": user_id,
        },
    )
    count("supplier_payment", created)
    _ensure_pdf_attachment(branch_id=branch_id, user_id=user_id, module="SUPPLIER_PAYMENT", reference_type="SUPPLIER_PAYMENT", reference_id=supplier_payment.id, attachment_type="BUKTI_TRANSFER")

    invoice, created = _get_or_create(
        Invoice,
        {"invoice_number": f"{PREFIX}-INV-001"},
        {
            "branch_id": branch_id,
            "invoice_date": SMOKE_DATE,
            "due_date": SMOKE_DATE + timedelta(days=7),
            "period_start": SMOKE_DATE,
            "period_end": SMOKE_DATE,
            "bill_to_type": "CLIENT",
            "client_id": client.id,
            "mandor_id": mandor.id,
            "client_pic_id": client_pic.id,
            "client_name_snapshot": client.name,
            "client_code_snapshot": client.client_code,
            "client_pic_name_snapshot": client_pic.name,
            "expected_payment_percent": _money("100"),
            "total_amount": _money("150000"),
            "paid_amount": _money("50000"),
            "remaining_amount": _money("100000"),
            "status": "PARTIAL",
            "source_type": "QA_SMOKE",
            "source_order_id": 900001,
            "input_source": "REALTIME",
            "created_by": user_id,
        },
    )
    count("invoice", created)
    _, created = _get_or_create(
        InvoiceItem,
        {"invoice_id": invoice.id, "source_type": "QA_SMOKE", "source_id": 900001},
        {"item_type": "CATERING", "description": "QA smoke invoice item", "qty": _money("10"), "unit_price": _money("15000"), "subtotal": _money("150000"), "input_source": "REALTIME"},
    )
    count("invoice_item", created)
    payment, created = _get_or_create(
        Payment,
        {"payment_number": f"{PREFIX}-PAY-001"},
        {
            "branch_id": branch_id,
            "payment_date": SMOKE_DATE,
            "invoice_id": invoice.id,
            "bank_account_id": bank.id,
            "payment_method": "TRANSFER",
            "amount": _money("50000"),
            "reference_number": f"{PREFIX}-PAY-REF",
            "received_by": user_id,
        },
    )
    count("payment", created)
    _ensure_pdf_attachment(branch_id=branch_id, user_id=user_id, module="CUSTOMER_PAYMENT", reference_type="PAYMENT", reference_id=payment.id, attachment_type="BUKTI_TRANSFER")

    cash_tx, created = _get_or_create(
        CashBankTransaction,
        {"branch_id": branch_id, "reference_type": "QA_SMOKE", "reference_id": 900001},
        {
            "transaction_date": SMOKE_DATE,
            "account_type": "BANK",
            "bank_account_id": bank.id,
            "transaction_type": "IN",
            "amount": _money("50000"),
            "description": "QA smoke cash bank transaction",
            "is_reconciled": False,
            "created_by": user_id,
        },
    )
    count("cash_bank_transaction", created)
    advance, created = _get_or_create(
        AdvanceTransaction,
        {"advance_number": f"{PREFIX}-ADV-001"},
        {
            "branch_id": branch_id,
            "advance_date": SMOKE_DATE,
            "advance_type": "CUSTOMER_DP",
            "party_type": "CLIENT",
            "client_id": client.id,
            "account_type": "BANK",
            "bank_account_id": bank.id,
            "payment_method": "TRANSFER",
            "amount": _money("25000"),
            "settled_amount": _money("0"),
            "remaining_amount": _money("25000"),
            "status": "OPEN",
            "reference_number": f"{PREFIX}-ADV-REF",
            "cash_bank_transaction_id": cash_tx.id,
            "journal_id": journal.id,
            "created_by": user_id,
        },
    )
    count("advance", created)
    _, created = _get_or_create(
        CashDaily,
        {"branch_id": branch_id, "cash_date": SMOKE_DATE},
        {
            "status": "OPEN",
            "opening_balance": _money("100000"),
            "cash_sales": _money("10000"),
            "debt_payments": _money("0"),
            "other_income": _money("0"),
            "expenses": _money("5000"),
            "closing_balance": _money("105000"),
            "actual_cash": _money("105000"),
            "cash_difference": _money("0"),
            "created_by": user_id,
        },
    )
    count("cash_daily", created)

    fixed_asset, created = _get_or_create(
        FixedAsset,
        {"asset_code": f"{PREFIX}-ASSET-001"},
        {
            "branch_id": branch_id,
            "asset_name": "QA Smoke Asset",
            "asset_category": "OTHER",
            "purchase_date": SMOKE_DATE,
            "purchase_value": _money("1000000"),
            "useful_life_years": 5,
            "residual_value": _money("100000"),
            "accumulated_depreciation": _money("0"),
            "book_value": _money("1000000"),
            "status": "ACTIVE",
        },
    )
    count("fixed_asset", created)
    fixed_asset_purchase, created = _get_or_create(
        FixedAssetPurchase,
        {"fixed_asset_id": fixed_asset.id},
        {
            "branch_id": branch_id,
            "purchase_number": f"{PREFIX}-FAP-001",
            "purchase_date": SMOKE_DATE,
            "asset_account_code": "QA1000",
            "payment_method": "TRANSFER",
            "account_type": "BANK",
            "bank_account_id": bank.id,
            "amount": _money("1000000"),
            "vendor_name": "QA Smoke Vendor",
            "cash_bank_transaction_id": cash_tx.id,
            "journal_id": journal.id,
            "created_by": user_id,
        },
    )
    count("fixed_asset_purchase", created)
    contract, created = _get_or_create(
        AssetFinancingContract,
        {"contract_number": f"{PREFIX}-AFC-001"},
        {
            "branch_id": branch_id,
            "contract_date": SMOKE_DATE,
            "fixed_asset_id": fixed_asset.id,
            "asset_account_code": "QA1000",
            "liability_account_code": "2001",
            "interest_expense_account_code": "5008",
            "admin_expense_account_code": "5008",
            "vendor_name": "QA Smoke Vendor",
            "financing_provider": "QA Finance",
            "principal_amount": _money("1000000"),
            "total_interest_amount": _money("100000"),
            "total_admin_amount": _money("10000"),
            "total_contract_amount": _money("1110000"),
            "installment_count": 1,
            "first_due_date": SMOKE_DATE + timedelta(days=30),
            "status": "ACTIVE",
            "acquisition_journal_id": journal.id,
            "created_by": user_id,
        },
    )
    count("asset_financing_contract", created)
    _, created = _get_or_create(
        AssetInstallmentSchedule,
        {"contract_id": contract.id, "installment_no": 1},
        {
            "branch_id": branch_id,
            "due_date": SMOKE_DATE + timedelta(days=30),
            "principal_amount": _money("1000000"),
            "interest_amount": _money("100000"),
            "admin_amount": _money("10000"),
            "total_amount": _money("1110000"),
            "paid_amount": _money("0"),
            "remaining_amount": _money("1110000"),
            "status": "UNPAID",
        },
    )
    count("asset_installment_schedule", created)

    _, created = _get_or_create(
        OperationalExpense,
        {"expense_number": f"{PREFIX}-OPEX-001"},
        {
            "branch_id": branch_id,
            "expense_date": SMOKE_DATE,
            "expense_category": "GENERAL",
            "account_code": "5008",
            "payment_method": "TRANSFER",
            "account_type": "BANK",
            "bank_account_id": bank.id,
            "supplier_id": supplier.id,
            "vendor_name": supplier.supplier_name,
            "amount": _money("25000"),
            "reference_number": f"{PREFIX}-OPEX-REF",
            "posting_status": "POSTED",
            "cash_bank_transaction_id": cash_tx.id,
            "journal_id": journal.id,
            "created_by": user_id,
        },
    )
    count("operational_expense", created)
    _, created = _get_or_create(
        TransportVehicleExpense,
        {"expense_number": f"{PREFIX}-TVE-001"},
        {
            "branch_id": branch_id,
            "expense_date": SMOKE_DATE,
            "expense_type": "FUEL",
            "account_code": "5003",
            "payment_method": "TRANSFER",
            "account_type": "BANK",
            "bank_account_id": bank.id,
            "amount": _money("30000"),
            "vehicle_label": "QA Smoke Vehicle",
            "driver_id": driver.id,
            "delivery_id": delivery.id,
            "vendor_name": "QA Fuel",
            "reference_number": f"{PREFIX}-TVE-REF",
            "cash_bank_transaction_id": cash_tx.id,
            "journal_id": journal.id,
            "created_by": user_id,
        },
    )
    count("transport_expense", created)

    employee, created = _get_or_create(
        Employee,
        {"branch_id": branch_id, "full_name": "QA Smoke Employee"},
        {"phone": "0800000006", "join_date": SMOKE_DATE, "status": "ACTIVE"},
    )
    count("employee", created)
    payroll, created = _get_or_create(
        Payroll,
        {"branch_id": branch_id, "period_month": 12, "period_year": 2099},
        {"status": "DRAFT", "created_by": user_id},
    )
    count("payroll", created)
    _, created = _get_or_create(
        PayrollDetail,
        {"payroll_id": payroll.id, "employee_id": employee.id},
        {"base_salary": _money("1000000"), "bonus": _money("0"), "deduction": _money("0"), "final_salary": _money("1000000")},
    )
    count("payroll_detail", created)

    item_request, created = _get_or_create(
        ItemRequest,
        {"request_number": f"{PREFIX}-REQ-001"},
        {"branch_id": branch_id, "request_date": SMOKE_DATE, "requested_by": user_id, "status": "PENDING", "purpose": "QA smoke", "notes": "QA smoke"},
    )
    count("item_request", created)
    _, created = _get_or_create(
        ItemRequestDetail,
        {"item_request_id": item_request.id, "item_id": item.id},
        {"qty": _money("1"), "unit": "kg", "requested_qty": _money("1"), "approved_qty": _money("0"), "fulfilled_qty": _money("0")},
    )
    count("item_request_detail", created)

    production, created = _get_or_create(
        Production,
        {"branch_id": branch_id, "production_date": SMOKE_DATE, "production_type": "QA_SMOKE"},
        {"status": "DRAFT", "target_ready_time": SMOKE_DATETIME, "late_tolerance_minutes": 0, "notes": "QA smoke", "created_by": user_id},
    )
    count("production", created)
    _, created = _get_or_create(
        ProductionDetail,
        {"production_id": production.id, "item_id": item.id},
        {"planned_qty": _money("1"), "actual_qty": _money("0"), "unit": "kg", "notes": "QA smoke"},
    )
    count("production_detail", created)

    field_counterparty, created = _get_or_create(
        FieldCounterparty,
        {"branch_id": branch_id, "name": "QA Smoke Counterparty"},
        {"counterparty_type": "LAINNYA", "phone": "0800000007", "is_active": True, "created_by": user_id},
    )
    count("field_counterparty", created)
    field_transaction, created = _get_or_create(
        FieldTransaction,
        {"transaction_number": f"{PREFIX}-FTX-001"},
        {
            "branch_id": branch_id,
            "transaction_date": SMOKE_DATE,
            "entry_date": SMOKE_DATE,
            "transaction_direction": "IN",
            "business_event_type": "OTHER_INCOME",
            "field_channel": "MANUAL",
            "counterparty_id": field_counterparty.id,
            "counterparty_type_snapshot": field_counterparty.counterparty_type,
            "party_snapshot_name": field_counterparty.name,
            "amount": _money("10000"),
            "payment_status": "PAID",
            "payment_method": "CASH",
            "review_status": "RECORDED",
            "posting_status": "NOT_POSTED",
            "evidence_status": "ATTACHED",
            "is_manual": True,
            "created_by": user_id,
        },
    )
    count("field_transaction", created)
    field_attachment = _ensure_pdf_attachment(branch_id=branch_id, user_id=user_id, module="FIELD_TRANSACTION", reference_type="FIELD_TRANSACTION", reference_id=field_transaction.id, attachment_type="EVIDENCE")
    _, created = _get_or_create(
        FieldTransactionAttachment,
        {"field_transaction_id": field_transaction.id, "digital_attachment_id": field_attachment.id},
        {"attachment_role": "EVIDENCE", "status": "ATTACHED", "created_by": user_id},
    )
    count("field_transaction_attachment", created)

    debt_sale, created = _get_or_create(
        CanteenSale,
        {"branch_id": branch_id, "notes": f"{PREFIX}-DEBT-SALE"},
        {
            "sale_date": SMOKE_DATE,
            "sale_type": "DEBT",
            "total_amount": _money("10000"),
            "payment_method": "CASH",
            "buyer_type": "PEKERJA",
            "buyer_name": worker.full_name,
            "is_external_debt": False,
            "created_by": user_id,
        },
    )
    count("canteen_sale", created)
    _, created = _get_or_create(CanteenSaleItem, {"sale_id": debt_sale.id, "item_id": item.id}, {"qty": 1, "price": _money("10000"), "subtotal": _money("10000")})
    count("canteen_sale_item", created)
    _, created = _get_or_create(
        WorkerDebt,
        {"branch_id": branch_id, "sale_id": debt_sale.id},
        {"worker_id": worker.id, "debt_amount": _money("10000"), "status": "UNPAID"},
    )
    count("worker_debt", created)
    external_sale, created = _get_or_create(
        CanteenSale,
        {"branch_id": branch_id, "notes": f"{PREFIX}-EXT-SALE"},
        {
            "sale_date": SMOKE_DATE,
            "sale_type": "DEBT",
            "total_amount": _money("12000"),
            "payment_method": "CASH",
            "buyer_type": "BUYER_EKSTERNAL",
            "buyer_name": "QA Smoke External Buyer",
            "buyer_phone": "0800000008",
            "is_external_debt": True,
            "created_by": user_id,
        },
    )
    count("canteen_sale", created)
    _, created = _get_or_create(CanteenSaleItem, {"sale_id": external_sale.id, "item_id": item.id}, {"qty": 1, "price": _money("12000"), "subtotal": _money("12000")})
    count("canteen_sale_item", created)
    _, created = _get_or_create(
        CanteenExternalReceivable,
        {"branch_id": branch_id, "sale_id": external_sale.id},
        {
            "buyer_name": "QA Smoke External Buyer",
            "buyer_phone": "0800000008",
            "receivable_amount": _money("12000"),
            "paid_amount": _money("0"),
            "remaining_amount": _money("12000"),
            "status": "UNPAID",
            "created_by": user_id,
        },
    )
    count("external_receivable", created)

    _ensure_pdf_attachment(branch_id=branch_id, user_id=user_id, module="QA_SMOKE", reference_type="GENERAL", reference_id=900001, attachment_type="GENERAL")

    db.session.commit()
    return created_counts


def main() -> int:
    app = create_app()
    with app.app_context():
        created_counts = seed()
    print("QA smoke sample data ready.")
    if created_counts:
        for key in sorted(created_counts):
            print(f"{key}: +{created_counts[key]}")
    else:
        print("No new rows created; existing QA smoke data reused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
