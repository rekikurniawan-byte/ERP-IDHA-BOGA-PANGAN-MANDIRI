from datetime import datetime

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models.master import Client, ClientPic, Mandor, DeliveryLocation, Worker, Driver, Supplier, Item, UnitConversion, ItemCostProfile, Menu, RecipeHeader, RecipeItem, RecipeVersionItem, PackagingProfile, OverheadProfile
from app.models.finance import BankAccount
from app.models.accounting import FixedAsset
from app.models.canteen import WorkerDebt, CanteenSaleItem
from app.models.operational import OrderHppSnapshotComponent, OrderHppStockConsumptionLine
from app.models.production import ProductionDetail
from app.models.logistics import DamagedItem, ItemRequestDetail, ProcurementItem, StockAdjustment, StockMovement, StockOpeningBalance
from app.utils.decorators import role_required
from app.services.audit_log_service import record_audit_log
from app.services.master_data_service import (
    create_bank_account_record,
    create_client_pic_record,
    create_client_record,
    create_driver_record,
    create_fixed_asset_record,
    create_item_record,
    create_location_record,
    create_mandor_record,
    create_supplier_record,
    create_worker_record,
    delete_item_record,
    delete_worker_record,
    generate_worker_code,
    generate_item_code,
    generate_client_code,
    save_item_cost_profile,
    toggle_bank_account_active,
    toggle_client_active,
    toggle_client_pic_active,
    toggle_driver_active,
    toggle_fixed_asset_status,
    toggle_item_active,
    toggle_location_active,
    toggle_mandor_active,
    toggle_supplier_active,
    toggle_unit_conversion_active,
    toggle_worker_status,
    update_bank_account_record,
    update_client_record,
    update_driver_record,
    update_fixed_asset_record,
    update_item_record,
    update_location_record,
    update_mandor_record,
    update_supplier_record,
    update_worker_record,
    upsert_unit_conversion,
)

master_bp = Blueprint("master", __name__, url_prefix="/master")


ITEM_CATEGORIES = ["RAW_MATERIAL", "MERCHANDISE", "PACKAGING", "GAS", "OTHER"]
WORKER_STATUSES = ["ACTIVE", "MOVED", "LEFT"]
ASSET_CATEGORIES = ["KITCHEN_EQUIPMENT", "VEHICLE", "OFFICE_EQUIPMENT", "BUILDING", "OTHER"]
ASSET_STATUSES = ["ACTIVE", "INACTIVE", "RETIRED", "SOLD"]
SUPPLIER_TYPES = ["GENERAL", "RAW_MATERIAL", "PACKAGING", "GAS", "SERVICE", "OTHER"]
COST_PROFILE_CATEGORIES = ["RAW_MATERIAL", "PACKAGING", "GAS", "OTHER"]
COST_UNITS = ["GRAM", "KG", "ML", "LITER", "PCS", "PACK", "DUS", "KARUNG", "TABUNG", "BOTOL", "PORSI"]
COST_SOURCES = ["STANDARD", "MANUAL", "LAST_PURCHASE"]


def to_float(value):
    try:
        cleaned = str(value or "0").strip()
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        return float(cleaned or 0)
    except (TypeError, ValueError):
        return 0


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def bank_account_number_is_used(account_number, exclude_id=None):
    query = BankAccount.query.filter(
        func.lower(BankAccount.account_number) == account_number.lower()
    )

    if exclude_id:
        query = query.filter(BankAccount.id != exclude_id)

    return query.first() is not None


def generate_asset_code():
    latest = FixedAsset.query.order_by(FixedAsset.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        asset_code = f"AST-{next_number:04d}"
        if not FixedAsset.query.filter_by(asset_code=asset_code).first():
            return asset_code
        next_number += 1


def generate_supplier_code():
    latest = Supplier.query.order_by(Supplier.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        supplier_code = f"SUP-{next_number:04d}"
        if not Supplier.query.filter_by(supplier_code=supplier_code).first():
            return supplier_code
        next_number += 1


def supplier_name_is_used(name, branch_id, exclude_id=None):
    query = Supplier.query.filter(
        Supplier.branch_id == branch_id,
        func.lower(Supplier.supplier_name) == name.lower()
    )

    if exclude_id:
        query = query.filter(Supplier.id != exclude_id)

    return query.first() is not None


def calculate_asset_book_value(purchase_value, accumulated_depreciation):
    value = float(purchase_value or 0) - float(accumulated_depreciation or 0)
    return max(value, 0)


def mandor_name_is_used(name, branch_id, exclude_id=None):
    query = Mandor.query.filter(
        Mandor.branch_id == branch_id,
        func.lower(Mandor.name) == name.lower()
    )

    if exclude_id:
        query = query.filter(Mandor.id != exclude_id)

    return query.first() is not None


def client_name_is_used(name, branch_id, exclude_id=None):
    query = Client.query.filter(
        func.lower(Client.name) == name.lower()
    )

    if hasattr(Client, "branch_id"):
        query = query.filter(Client.branch_id == branch_id)

    if exclude_id:
        query = query.filter(Client.id != exclude_id)

    return query.first() is not None


def worker_is_used(worker_id):
    has_debt = WorkerDebt.query.filter_by(worker_id=worker_id).first()
    return has_debt is not None


def item_is_used(item_id):
    usage_models = (
        CanteenSaleItem,
        DamagedItem,
        ItemCostProfile,
        ItemRequestDetail,
        OrderHppSnapshotComponent,
        OrderHppStockConsumptionLine,
        ProcurementItem,
        ProductionDetail,
        RecipeItem,
        RecipeVersionItem,
        StockAdjustment,
        StockMovement,
        StockOpeningBalance,
    )
    return any(model.query.filter_by(item_id=item_id).first() is not None for model in usage_models)

# Domain route modules. Imported after shared helpers are defined so decorators bind to the same blueprint.
from app.routes.master import client_routes as _master_client_routes  # noqa: F401,E402
from app.routes.master import people_location_routes as _master_people_location_routes  # noqa: F401,E402
from app.routes.master import item_routes as _master_item_routes  # noqa: F401,E402
from app.routes.master import supplier_bank_asset_routes as _master_supplier_bank_asset_routes  # noqa: F401,E402
