from datetime import datetime

from sqlalchemy import func

from app.extensions import db
from app.models.master import RecipeHeader, RecipeItem, RecipeVersion, RecipeVersionItem


class RecipeVersionError(ValueError):
    """Raised when a recipe cannot be snapshotted as a final version."""


def _next_version_number(recipe):
    latest_number = (
        db.session.query(func.max(RecipeVersion.version_number))
        .filter(
            RecipeVersion.branch_id == recipe.branch_id,
            RecipeVersion.recipe_id == recipe.id,
        )
        .scalar()
    )
    return int(latest_number or 0) + 1


def validate_recipe_ready_for_version(recipe):
    """Validate active/current recipe before it is archived as a FINAL version."""
    if not recipe:
        raise RecipeVersionError("Resep tidak ditemukan.")

    if not recipe.menu:
        raise RecipeVersionError("Menu untuk resep tidak ditemukan.")

    if not recipe.recipe_name or not recipe.recipe_name.strip():
        raise RecipeVersionError("Nama resep wajib diisi sebelum FINAL.")

    if float(recipe.base_portion or 0) <= 0:
        raise RecipeVersionError("Base porsi resep wajib lebih dari 0 sebelum FINAL.")

    items = list(recipe.items or [])
    if not items:
        raise RecipeVersionError("Resep belum bisa difinalkan karena item bahan/BOM masih kosong.")

    for line in items:
        if float(line.qty_per_portion or 0) <= 0:
            raise RecipeVersionError("Semua qty item resep wajib lebih dari 0 sebelum FINAL.")
        if not line.unit:
            raise RecipeVersionError("Semua item resep wajib punya satuan sebelum FINAL.")
        if not line.item:
            raise RecipeVersionError("Ada item resep yang master item-nya tidak ditemukan.")
        if not line.item.is_active:
            raise RecipeVersionError(f"Item resep tidak aktif: {line.item.item_name}.")

    return True


def create_recipe_version_snapshot(recipe, finalized_by=None, finalized_at=None):
    """Create immutable snapshot rows for the current active recipe.

    Caller is responsible for committing the session. This function only adds rows.
    """
    if not isinstance(recipe, RecipeHeader):
        raise RecipeVersionError("Objek resep tidak valid.")

    validate_recipe_ready_for_version(recipe)

    finalized_at = finalized_at or datetime.utcnow()
    version_number = _next_version_number(recipe)
    version_label = (recipe.version_label or f"v{version_number}").strip() or f"v{version_number}"

    version = RecipeVersion(
        branch_id=recipe.branch_id,
        recipe_id=recipe.id,
        menu_id=recipe.menu_id,
        version_number=version_number,
        version_label=version_label[:50],
        version_note=recipe.version_note,
        recipe_name_snapshot=recipe.recipe_name,
        menu_code_snapshot=getattr(recipe.menu, "menu_code", None),
        menu_name_snapshot=getattr(recipe.menu, "menu_name", "Menu"),
        base_portion=recipe.base_portion,
        status="FINAL",
        finalized_at=finalized_at,
        finalized_by=finalized_by,
    )
    db.session.add(version)
    db.session.flush()

    for line in sorted(recipe.items or [], key=lambda row: (row.id or 0)):
        item = line.item
        version_item = RecipeVersionItem(
            recipe_version_id=version.id,
            item_id=getattr(item, "id", None),
            item_code_snapshot=getattr(item, "item_code", None),
            item_name_snapshot=getattr(item, "item_name", "Item"),
            item_category_snapshot=getattr(item, "category", None),
            qty_per_portion=line.qty_per_portion,
            unit=line.unit,
            notes=line.notes,
        )
        db.session.add(version_item)

    return version


def has_recipe_versions(recipe):
    if not recipe:
        return False
    return RecipeVersion.query.filter_by(branch_id=recipe.branch_id, recipe_id=recipe.id).first() is not None
