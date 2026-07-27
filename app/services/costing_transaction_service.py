from datetime import datetime

from app.extensions import db
from app.models.master import Menu, OverheadProfile, PackagingProfile, RecipeHeader, RecipeItem, RecipeVersion
from app.services.recipe_version_service import RecipeVersionError, create_recipe_version_snapshot


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def create_menu_record(
    *,
    branch_id,
    menu_code,
    menu_name,
    menu_type,
    default_selling_price,
    notes,
    is_active,
    updated_by,
):
    menu = Menu(
        branch_id=branch_id,
        menu_code=menu_code,
        menu_name=menu_name,
        menu_type=menu_type,
        default_selling_price=default_selling_price,
        notes=notes,
        is_active=is_active,
    )
    db.session.add(menu)
    db.session.flush()

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
        updated_by=updated_by,
    )
    db.session.add(recipe)
    _commit_or_rollback()
    return menu


def create_default_recipe_for_menu(menu, *, updated_by):
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
        updated_by=updated_by,
    )
    db.session.add(recipe)
    db.session.flush()
    return recipe


def save_recipe_header_record(
    recipe,
    *,
    menu,
    recipe_name,
    base_portion,
    recipe_status,
    version_label,
    version_note,
    notes,
    is_active,
    updated_by,
):
    try:
        if recipe is None:
            recipe = create_default_recipe_for_menu(menu, updated_by=updated_by)

        previous_status = recipe.recipe_status
        previous_recipe_payload = {
            "recipe_name": recipe.recipe_name,
            "base_portion": float(recipe.base_portion or 0),
            "version_label": recipe.version_label,
            "version_note": recipe.version_note,
            "notes": recipe.notes,
        }
        incoming_recipe_payload = {
            "recipe_name": recipe_name,
            "base_portion": float(base_portion or 0),
            "version_label": version_label[:50],
            "version_note": version_note,
            "notes": notes,
        }
        has_existing_version = RecipeVersion.query.filter_by(
            branch_id=recipe.branch_id,
            recipe_id=recipe.id,
        ).first() is not None

        recipe.recipe_name = recipe_name
        recipe.base_portion = base_portion
        recipe.recipe_status = recipe_status
        recipe.version_label = version_label[:50]
        recipe.version_note = version_note
        recipe.notes = notes
        recipe.is_active = is_active
        recipe.updated_by = updated_by

        created_version = None
        finalized_at = datetime.utcnow() if recipe_status == "FINAL" else None

        if recipe_status == "FINAL":
            recipe.finalized_at = finalized_at
            recipe.finalized_by = updated_by

            header_changed_while_final = (
                previous_status == "FINAL"
                and previous_recipe_payload != incoming_recipe_payload
            )
            should_create_version = previous_status != "FINAL" or not has_existing_version or header_changed_while_final
            if should_create_version:
                created_version = create_recipe_version_snapshot(
                    recipe,
                    finalized_by=updated_by,
                    finalized_at=finalized_at,
                )
        else:
            recipe.finalized_at = None
            recipe.finalized_by = None

        _commit_or_rollback()
        return recipe, created_version
    except RecipeVersionError:
        db.session.rollback()
        raise


def add_recipe_item_record(recipe, *, menu, item, qty_per_portion, unit, notes, updated_by):
    if recipe is None:
        recipe = create_default_recipe_for_menu(menu, updated_by=updated_by)

    recipe_item = RecipeItem(
        recipe_id=recipe.id,
        item_id=item.id,
        qty_per_portion=qty_per_portion,
        unit=unit,
        notes=notes,
    )
    db.session.add(recipe_item)
    recipe.recipe_status = "DRAFT"
    recipe.finalized_at = None
    recipe.finalized_by = None
    recipe.updated_by = updated_by
    _commit_or_rollback()
    return recipe, recipe_item


def update_menu_record(menu, *, menu_name, menu_type, default_selling_price, notes, is_active):
    menu.menu_name = menu_name
    menu.menu_type = menu_type
    menu.default_selling_price = default_selling_price
    menu.notes = notes
    menu.is_active = is_active
    _commit_or_rollback()
    return menu


def toggle_menu_active(menu):
    menu.is_active = not menu.is_active
    _commit_or_rollback()
    return menu


def delete_recipe_item_record(recipe_item, *, updated_by):
    recipe = recipe_item.recipe
    db.session.delete(recipe_item)
    recipe.recipe_status = "DRAFT"
    recipe.finalized_at = None
    recipe.finalized_by = None
    recipe.updated_by = updated_by
    _commit_or_rollback()
    return recipe


def create_packaging_profile_record(
    *,
    branch_id,
    profile_code,
    profile_name,
    cost_per_portion,
    notes,
    is_active,
    updated_by,
):
    profile = PackagingProfile(
        branch_id=branch_id,
        profile_code=profile_code,
        profile_name=profile_name,
        cost_per_portion=cost_per_portion,
        notes=notes,
        is_active=is_active,
        updated_by=updated_by,
    )
    db.session.add(profile)
    _commit_or_rollback()
    return profile


def update_packaging_profile_record(profile, *, profile_name, cost_per_portion, notes, is_active, updated_by):
    profile.profile_name = profile_name
    profile.cost_per_portion = cost_per_portion
    profile.notes = notes
    profile.is_active = is_active
    profile.updated_by = updated_by
    _commit_or_rollback()
    return profile


def toggle_packaging_profile_active(profile, *, updated_by):
    profile.is_active = not profile.is_active
    profile.updated_by = updated_by
    _commit_or_rollback()
    return profile


def create_overhead_profile_record(
    *,
    branch_id,
    profile_code,
    profile_name,
    gas_cost_per_portion,
    electricity_cost_per_portion,
    water_cost_per_portion,
    labor_cost_per_portion,
    spices_cost_per_portion,
    other_cost_per_portion,
    overhead_percentage,
    notes,
    is_active,
    updated_by,
):
    profile = OverheadProfile(
        branch_id=branch_id,
        profile_code=profile_code,
        profile_name=profile_name,
        gas_cost_per_portion=gas_cost_per_portion,
        electricity_cost_per_portion=electricity_cost_per_portion,
        water_cost_per_portion=water_cost_per_portion,
        labor_cost_per_portion=labor_cost_per_portion,
        spices_cost_per_portion=spices_cost_per_portion,
        other_cost_per_portion=other_cost_per_portion,
        overhead_percentage=overhead_percentage,
        notes=notes,
        is_active=is_active,
        updated_by=updated_by,
    )
    db.session.add(profile)
    _commit_or_rollback()
    return profile


def update_overhead_profile_record(
    profile,
    *,
    profile_name,
    gas_cost_per_portion,
    electricity_cost_per_portion,
    water_cost_per_portion,
    labor_cost_per_portion,
    spices_cost_per_portion,
    other_cost_per_portion,
    overhead_percentage,
    notes,
    is_active,
    updated_by,
):
    profile.profile_name = profile_name
    profile.gas_cost_per_portion = gas_cost_per_portion
    profile.electricity_cost_per_portion = electricity_cost_per_portion
    profile.water_cost_per_portion = water_cost_per_portion
    profile.labor_cost_per_portion = labor_cost_per_portion
    profile.spices_cost_per_portion = spices_cost_per_portion
    profile.other_cost_per_portion = other_cost_per_portion
    profile.overhead_percentage = overhead_percentage
    profile.notes = notes
    profile.is_active = is_active
    profile.updated_by = updated_by
    _commit_or_rollback()
    return profile


def toggle_overhead_profile_active(profile, *, updated_by):
    profile.is_active = not profile.is_active
    profile.updated_by = updated_by
    _commit_or_rollback()
    return profile
