from datetime import datetime, time

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.master import Item, Menu, RecipeHeader, RecipeItem, PackagingProfile, OverheadProfile
from app.models.operational import DailyOrder, OrderHppSnapshot
from app.services.hpp_service import calculate_menu_hpp, normalize_unit
from app.utils.decorators import role_required
from app.services.audit_log_service import record_audit_log
from app.services.costing_transaction_service import (
    add_recipe_item_record,
    create_menu_record,
    create_overhead_profile_record,
    create_packaging_profile_record,
    delete_recipe_item_record,
    save_recipe_header_record,
    toggle_menu_active,
    toggle_overhead_profile_active,
    toggle_packaging_profile_active,
    update_menu_record,
    update_overhead_profile_record,
    update_packaging_profile_record,
)
from app.services.recipe_version_service import RecipeVersionError

costing_bp = Blueprint("costing", __name__, url_prefix="/costing")

MENU_TYPES = ["CATERING", "BOX", "SNACK", "CUSTOM", "OTHER"]
RECIPE_ITEM_CATEGORIES = ["RAW_MATERIAL", "PACKAGING", "GAS", "OTHER"]
RECIPE_UNITS = ["GRAM", "KG", "ML", "LITER", "PCS", "PACK", "DUS", "KARUNG", "TABUNG", "BOTOL", "PORSI"]
RECIPE_STATUSES = ["DRAFT", "FINAL"]


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
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except (TypeError, ValueError):
        return None


def snapshot_margin_status(snapshot):
    margin = to_float(snapshot.gross_margin_percentage)
    target = to_float(snapshot.target_margin_percentage)

    if margin < 0:
        return "NEGATIVE"

    if margin < target:
        return "LOW"

    return "HEALTHY"


def generate_menu_code():
    latest = Menu.query.order_by(Menu.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        menu_code = f"MNU-{next_number:04d}"
        if not Menu.query.filter_by(menu_code=menu_code).first():
            return menu_code
        next_number += 1


def generate_packaging_profile_code():
    latest = PackagingProfile.query.order_by(PackagingProfile.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        profile_code = f"PKG-{next_number:04d}"
        if not PackagingProfile.query.filter_by(profile_code=profile_code).first():
            return profile_code
        next_number += 1


def generate_overhead_profile_code():
    latest = OverheadProfile.query.order_by(OverheadProfile.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        profile_code = f"OVH-{next_number:04d}"
        if not OverheadProfile.query.filter_by(profile_code=profile_code).first():
            return profile_code
        next_number += 1


def packaging_profile_name_is_used(name, branch_id, exclude_id=None):
    query = PackagingProfile.query.filter(
        PackagingProfile.branch_id == branch_id,
        func.lower(PackagingProfile.profile_name) == name.lower(),
    )
    if exclude_id:
        query = query.filter(PackagingProfile.id != exclude_id)
    return query.first() is not None


def overhead_profile_name_is_used(name, branch_id, exclude_id=None):
    query = OverheadProfile.query.filter(
        OverheadProfile.branch_id == branch_id,
        func.lower(OverheadProfile.profile_name) == name.lower(),
    )
    if exclude_id:
        query = query.filter(OverheadProfile.id != exclude_id)
    return query.first() is not None


def menu_name_is_used(name, branch_id, exclude_id=None):
    query = Menu.query.filter(
        Menu.branch_id == branch_id,
        func.lower(Menu.menu_name) == name.lower(),
    )
    if exclude_id:
        query = query.filter(Menu.id != exclude_id)
    return query.first() is not None


def get_recipe_for_menu(menu):
    return RecipeHeader.query.filter_by(menu_id=menu.id, branch_id=menu.branch_id).first()


def create_default_recipe(menu):
    recipe = RecipeHeader(
        branch_id=menu.branch_id,
        menu_id=menu.id,
        recipe_name=f"Resep {menu.menu_name}",
        base_portion=1,
        recipe_status="DRAFT",
        version_label="v1",
        version_note=None,
        finalized_at=None,
        finalized_by=None,
        notes=None,
        is_active=True,
        updated_by=current_user.id,
    )
    db.session.add(recipe)
    return recipe


# Domain route modules. Imported after shared helpers are defined so decorators bind to the same blueprint.
from app.routes.costing import snapshot_routes as _costing_snapshot_routes  # noqa: F401,E402
from app.routes.costing import menu_routes as _costing_menu_routes  # noqa: F401,E402
from app.routes.costing import profile_routes as _costing_profile_routes  # noqa: F401,E402
from app.routes.costing import calculator_routes as _costing_calculator_routes  # noqa: F401,E402
