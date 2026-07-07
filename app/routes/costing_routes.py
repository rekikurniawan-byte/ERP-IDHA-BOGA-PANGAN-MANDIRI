from datetime import datetime, time

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.master import Item, Menu, RecipeHeader, RecipeItem, RecipeVersion, PackagingProfile, OverheadProfile
from app.models.operational import DailyOrder, OrderHppSnapshot
from app.services.hpp_service import calculate_menu_hpp, normalize_unit
from app.utils.decorators import role_required
from app.services.audit_log_service import record_audit_log
from app.services.recipe_version_service import create_recipe_version_snapshot, RecipeVersionError

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


@costing_bp.route("/order-hpp-snapshots")
@role_required("ADMIN")
def order_hpp_snapshots():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "ALL").strip().upper()
    margin_status = (request.args.get("margin_status") or "ALL").strip().upper()
    date_from_raw = request.args.get("date_from") or ""
    date_to_raw = request.args.get("date_to") or ""
    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)

    query = OrderHppSnapshot.query.join(DailyOrder).filter(
        OrderHppSnapshot.branch_id == current_user.branch_id
    )

    if q:
        query = query.filter(
            or_(
                OrderHppSnapshot.snapshot_number.ilike(f"%{q}%"),
                DailyOrder.order_number.ilike(f"%{q}%"),
                OrderHppSnapshot.notes.ilike(f"%{q}%"),
            )
        )

    if status != "ALL":
        query = query.filter(OrderHppSnapshot.status == status)

    if date_from:
        query = query.filter(OrderHppSnapshot.snapshot_date >= datetime.combine(date_from, time.min))

    if date_to:
        query = query.filter(OrderHppSnapshot.snapshot_date <= datetime.combine(date_to, time.max))

    snapshots = query.order_by(
        OrderHppSnapshot.snapshot_date.desc(),
        OrderHppSnapshot.id.desc(),
    ).all()

    if margin_status != "ALL":
        snapshots = [
            snapshot for snapshot in snapshots
            if snapshot_margin_status(snapshot) == margin_status
        ]

    total_revenue = sum(to_float(snapshot.revenue_total) for snapshot in snapshots)
    total_hpp = sum(to_float(snapshot.hpp_total) for snapshot in snapshots)
    total_margin = sum(to_float(snapshot.gross_margin_amount) for snapshot in snapshots)
    margin_percentage = (total_margin / total_revenue * 100) if total_revenue > 0 else 0
    low_margin_count = sum(
        1 for snapshot in snapshots
        if snapshot_margin_status(snapshot) in ["LOW", "NEGATIVE"]
    )
    unique_order_count = len({snapshot.daily_order_id for snapshot in snapshots})

    summary = {
        "snapshot_count": len(snapshots),
        "order_count": unique_order_count,
        "total_revenue": total_revenue,
        "total_hpp": total_hpp,
        "total_margin": total_margin,
        "margin_percentage": margin_percentage,
        "low_margin_count": low_margin_count,
    }

    return render_template(
        "costing/order_hpp_snapshots.html",
        snapshots=snapshots,
        summary=summary,
        q=q,
        status=status,
        margin_status=margin_status,
        date_from=date_from_raw,
        date_to=date_to_raw,
        snapshot_margin_status=snapshot_margin_status,
    )


@costing_bp.route("/menus")
@role_required("ADMIN")
def menus():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ACTIVE"
    menu_type = request.args.get("menu_type") or "ALL"
    recipe_status = (request.args.get("recipe_status") or "ALL").strip().upper()

    query = Menu.query.filter(Menu.branch_id == current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                Menu.menu_code.ilike(f"%{q}%"),
                Menu.menu_name.ilike(f"%{q}%"),
                Menu.notes.ilike(f"%{q}%"),
            )
        )

    if status == "ACTIVE":
        query = query.filter(Menu.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(Menu.is_active == False)

    if menu_type != "ALL":
        query = query.filter(Menu.menu_type == menu_type)

    if recipe_status in RECIPE_STATUSES:
        query = query.join(RecipeHeader).filter(RecipeHeader.recipe_status == recipe_status)
    elif recipe_status == "MISSING":
        query = query.outerjoin(RecipeHeader).filter(RecipeHeader.id.is_(None))
    else:
        recipe_status = "ALL"

    menus = query.order_by(Menu.menu_name.asc()).all()
    active_count = Menu.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()
    recipe_count = RecipeHeader.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()
    recipe_draft_count = RecipeHeader.query.filter_by(branch_id=current_user.branch_id, recipe_status="DRAFT").count()
    recipe_final_count = RecipeHeader.query.filter_by(branch_id=current_user.branch_id, recipe_status="FINAL").count()

    return render_template(
        "costing/menus.html",
        menus=menus,
        q=q,
        status=status,
        menu_type=menu_type,
        recipe_status=recipe_status,
        menu_types=MENU_TYPES,
        recipe_statuses=RECIPE_STATUSES,
        active_count=active_count,
        recipe_count=recipe_count,
        recipe_draft_count=recipe_draft_count,
        recipe_final_count=recipe_final_count,
    )


@costing_bp.route("/menus/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_menu():
    if request.method == "POST":
        menu_name = (request.form.get("menu_name") or "").strip()
        menu_type = (request.form.get("menu_type") or "CATERING").strip().upper()
        default_selling_price = to_float(request.form.get("default_selling_price"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        if not menu_name:
            flash("Nama menu wajib diisi.", "warning")
            return redirect(url_for("costing.create_menu"))

        if menu_type not in MENU_TYPES:
            menu_type = "CATERING"

        if default_selling_price < 0:
            flash("Harga jual default tidak boleh minus.", "warning")
            return redirect(url_for("costing.create_menu"))

        if menu_name_is_used(menu_name, current_user.branch_id):
            flash("Nama menu sudah ada di cabang ini.", "warning")
            return redirect(url_for("costing.create_menu"))

        menu = Menu(
            branch_id=current_user.branch_id,
            menu_code=generate_menu_code(),
            menu_name=menu_name,
            menu_type=menu_type,
            default_selling_price=default_selling_price,
            notes=notes,
            is_active=is_active,
        )
        db.session.add(menu)
        db.session.flush()
        create_default_recipe(menu)
        db.session.commit()

        record_audit_log(module="HPP", event_type="MENU_CREATED", action="CREATE", table_name="menus", record_id=menu.id, description=f"Menu dibuat: {menu.menu_name}.")
        flash("Menu berhasil dibuat. Lanjut lengkapi resep/BOM per porsi.", "success")
        return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

    return render_template("costing/menu_form.html", menu=None, menu_types=MENU_TYPES)


@costing_bp.route("/menus/<int:menu_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    if request.method == "POST":
        menu_name = (request.form.get("menu_name") or "").strip()
        menu_type = (request.form.get("menu_type") or "CATERING").strip().upper()
        default_selling_price = to_float(request.form.get("default_selling_price"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        if not menu_name:
            flash("Nama menu wajib diisi.", "warning")
            return redirect(url_for("costing.edit_menu", menu_id=menu.id))

        if menu_name_is_used(menu_name, current_user.branch_id, exclude_id=menu.id):
            flash("Nama menu sudah digunakan data lain.", "warning")
            return redirect(url_for("costing.edit_menu", menu_id=menu.id))

        if menu_type not in MENU_TYPES:
            menu_type = "CATERING"

        if default_selling_price < 0:
            flash("Harga jual default tidak boleh minus.", "warning")
            return redirect(url_for("costing.edit_menu", menu_id=menu.id))

        menu.menu_name = menu_name
        menu.menu_type = menu_type
        menu.default_selling_price = default_selling_price
        menu.notes = notes
        menu.is_active = is_active

        db.session.commit()
        record_audit_log(module="HPP", event_type="MENU_UPDATED", action="UPDATE", table_name="menus", record_id=menu.id, description=f"Menu diperbarui: {menu.menu_name}.")
        flash("Menu berhasil diperbarui.", "success")
        return redirect(url_for("costing.menus"))

    return render_template("costing/menu_form.html", menu=menu, menu_types=MENU_TYPES)


@costing_bp.route("/menus/<int:menu_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    menu.is_active = not menu.is_active
    db.session.commit()
    record_audit_log(module="HPP", event_type="MENU_TOGGLED", action="UPDATE", table_name="menus", record_id=menu.id, description=f"Status menu diubah: {menu.menu_name}.", new_value={"is_active": menu.is_active})
    flash("Status menu berhasil diubah.", "success")
    return redirect(url_for("costing.menus"))


@costing_bp.route("/menus/<int:menu_id>/recipe", methods=["GET", "POST"])
@role_required("ADMIN")
def menu_recipe(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    recipe = get_recipe_for_menu(menu)

    if request.method == "POST":
        action = request.form.get("action") or "add_item"

        if not recipe:
            recipe = create_default_recipe(menu)
            db.session.flush()

        if action == "save_header":
            recipe_name = (request.form.get("recipe_name") or "").strip()
            base_portion = to_float(request.form.get("base_portion") or 1)
            recipe_status = (request.form.get("recipe_status") or "DRAFT").strip().upper()
            version_label = (request.form.get("version_label") or "v1").strip() or "v1"
            version_note = (request.form.get("version_note") or "").strip() or None
            notes = (request.form.get("notes") or "").strip() or None
            is_active = True if request.form.get("is_active") == "on" else False

            if recipe_status not in RECIPE_STATUSES:
                recipe_status = "DRAFT"

            if not recipe_name:
                flash("Nama resep wajib diisi.", "warning")
                return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

            if base_portion <= 0:
                flash("Base porsi resep wajib lebih dari 0.", "warning")
                return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

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

            if recipe_status == "FINAL" and not recipe.items:
                flash("Resep belum bisa difinalkan karena item bahan/BOM masih kosong.", "warning")
                return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

            recipe.recipe_name = recipe_name
            recipe.base_portion = base_portion
            recipe.recipe_status = recipe_status
            recipe.version_label = version_label[:50]
            recipe.version_note = version_note
            recipe.notes = notes
            recipe.is_active = is_active
            recipe.updated_by = current_user.id

            created_version = None
            finalized_at = datetime.utcnow() if recipe_status == "FINAL" else None

            if recipe_status == "FINAL":
                recipe.finalized_at = finalized_at
                recipe.finalized_by = current_user.id

                header_changed_while_final = (
                    previous_status == "FINAL"
                    and previous_recipe_payload != incoming_recipe_payload
                )
                should_create_version = previous_status != "FINAL" or not has_existing_version or header_changed_while_final
                if should_create_version:
                    try:
                        created_version = create_recipe_version_snapshot(
                            recipe,
                            finalized_by=current_user.id,
                            finalized_at=finalized_at,
                        )
                    except RecipeVersionError as exc:
                        db.session.rollback()
                        flash(str(exc), "warning")
                        return redirect(url_for("costing.menu_recipe", menu_id=menu.id))
            else:
                recipe.finalized_at = None
                recipe.finalized_by = None

            db.session.commit()
            record_audit_log(
                module="HPP",
                event_type="MENU_RECIPE_UPDATED",
                action="UPDATE",
                table_name="recipe_headers",
                record_id=recipe.id,
                description=f"Header resep disimpan: {menu.menu_name}.",
                new_value={
                    "recipe_status": recipe.recipe_status,
                    "version_label": recipe.version_label,
                    "version_note": recipe.version_note,
                    "is_active": recipe.is_active,
                    "created_recipe_version_id": created_version.id if created_version else None,
                    "created_recipe_version_number": created_version.version_number if created_version else None,
                },
            )

            if created_version:
                record_audit_log(
                    module="HPP",
                    event_type="MENU_RECIPE_VERSION_CREATED",
                    action="CREATE",
                    table_name="recipe_versions",
                    record_id=created_version.id,
                    description=f"Versi resep dibuat untuk menu {menu.menu_name}: {created_version.version_label}.",
                    new_value={
                        "recipe_id": recipe.id,
                        "menu_id": menu.id,
                        "version_number": created_version.version_number,
                        "version_label": created_version.version_label,
                        "item_count": len(created_version.items or []),
                    },
                )
                flash(f"Header resep berhasil disimpan dan versi resep {created_version.version_label} berhasil dibuat.", "success")
            else:
                flash("Header resep berhasil disimpan.", "success")
            return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

        item_id = request.form.get("item_id")
        qty_per_portion = to_float(request.form.get("qty_per_portion"))
        unit = normalize_unit(request.form.get("unit"))
        notes = (request.form.get("item_notes") or "").strip() or None

        item = Item.query.get(item_id) if item_id else None
        if not item or not item.is_active:
            flash("Item bahan/kemasan wajib dipilih dan harus aktif.", "warning")
            return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

        if qty_per_portion <= 0:
            flash("Qty per porsi wajib lebih dari 0.", "warning")
            return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

        if not unit:
            flash("Satuan resep wajib diisi.", "warning")
            return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

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
        recipe.updated_by = current_user.id

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Item dengan satuan yang sama sudah ada di resep ini. Edit/hapus baris lama dulu.", "warning")
            return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

        record_audit_log(
            module="HPP",
            event_type="MENU_RECIPE_ITEM_CREATED",
            action="CREATE",
            table_name="recipe_items",
            record_id=recipe_item.id,
            description=f"Item resep ditambahkan ke menu {menu.menu_name}: {item.item_name}.",
            new_value={
                "item_id": item.id,
                "qty_per_portion": qty_per_portion,
                "unit": unit,
                "recipe_status": recipe.recipe_status,
            },
        )
        flash("Item resep/BOM berhasil ditambahkan. Status resep otomatis kembali DRAFT supaya bisa dicek ulang sebelum FINAL.", "success")
        return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

    recipe_items = recipe.items if recipe else []
    items = Item.query.filter(
        Item.is_active == True,
        Item.category.in_(RECIPE_ITEM_CATEGORIES),
    ).order_by(Item.category.asc(), Item.item_name.asc()).all()

    return render_template(
        "costing/recipe_form.html",
        menu=menu,
        recipe=recipe,
        recipe_items=recipe_items,
        items=items,
        recipe_units=RECIPE_UNITS,
        recipe_statuses=RECIPE_STATUSES,
    )


@costing_bp.route("/recipe-items/<int:recipe_item_id>/delete", methods=["POST"])
@role_required("ADMIN")
def delete_recipe_item(recipe_item_id):
    recipe_item = RecipeItem.query.get_or_404(recipe_item_id)
    menu = recipe_item.recipe.menu

    if menu.branch_id != current_user.branch_id:
        flash("Item resep tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    menu_id = menu.id
    recipe = recipe_item.recipe
    item_name = recipe_item.item.item_name if recipe_item.item else "item"
    db.session.delete(recipe_item)
    recipe.recipe_status = "DRAFT"
    recipe.finalized_at = None
    recipe.finalized_by = None
    recipe.updated_by = current_user.id
    db.session.commit()

    record_audit_log(
        module="HPP",
        event_type="MENU_RECIPE_ITEM_DELETED",
        action="DELETE",
        table_name="recipe_items",
        record_id=recipe_item_id,
        description=f"Item resep dihapus dari menu {menu.menu_name}: {item_name}.",
        new_value={"recipe_status": recipe.recipe_status},
    )
    flash("Item resep berhasil dihapus. Status resep otomatis kembali DRAFT supaya bisa dicek ulang sebelum FINAL.", "success")
    return redirect(url_for("costing.menu_recipe", menu_id=menu_id))


@costing_bp.route("/packaging-profiles")
@role_required("ADMIN")
def packaging_profiles():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ACTIVE"

    query = PackagingProfile.query.filter(PackagingProfile.branch_id == current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                PackagingProfile.profile_code.ilike(f"%{q}%"),
                PackagingProfile.profile_name.ilike(f"%{q}%"),
                PackagingProfile.notes.ilike(f"%{q}%"),
            )
        )

    if status == "ACTIVE":
        query = query.filter(PackagingProfile.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(PackagingProfile.is_active == False)

    profiles = query.order_by(PackagingProfile.profile_name.asc()).all()
    active_count = PackagingProfile.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()

    return render_template(
        "costing/packaging_profiles.html",
        profiles=profiles,
        q=q,
        status=status,
        active_count=active_count,
    )


@costing_bp.route("/packaging-profiles/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_packaging_profile():
    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        cost_per_portion = to_float(request.form.get("cost_per_portion"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        if not profile_name:
            flash("Nama profil kemasan wajib diisi.", "warning")
            return redirect(url_for("costing.create_packaging_profile"))

        if cost_per_portion < 0:
            flash("Biaya kemasan per porsi tidak boleh minus.", "warning")
            return redirect(url_for("costing.create_packaging_profile"))

        if packaging_profile_name_is_used(profile_name, current_user.branch_id):
            flash("Nama profil kemasan sudah ada di cabang ini.", "warning")
            return redirect(url_for("costing.create_packaging_profile"))

        profile = PackagingProfile(
            branch_id=current_user.branch_id,
            profile_code=generate_packaging_profile_code(),
            profile_name=profile_name,
            cost_per_portion=cost_per_portion,
            notes=notes,
            is_active=is_active,
            updated_by=current_user.id,
        )
        db.session.add(profile)
        db.session.commit()

        flash("Profil kemasan berhasil dibuat. Data ini belum memotong stok dan belum masuk jurnal.", "success")
        return redirect(url_for("costing.packaging_profiles"))

    return render_template("costing/packaging_profile_form.html", profile=None)


@costing_bp.route("/packaging-profiles/<int:profile_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_packaging_profile(profile_id):
    profile = PackagingProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil kemasan tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.packaging_profiles"))

    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        cost_per_portion = to_float(request.form.get("cost_per_portion"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        if not profile_name:
            flash("Nama profil kemasan wajib diisi.", "warning")
            return redirect(url_for("costing.edit_packaging_profile", profile_id=profile.id))

        if cost_per_portion < 0:
            flash("Biaya kemasan per porsi tidak boleh minus.", "warning")
            return redirect(url_for("costing.edit_packaging_profile", profile_id=profile.id))

        if packaging_profile_name_is_used(profile_name, current_user.branch_id, exclude_id=profile.id):
            flash("Nama profil kemasan sudah digunakan data lain.", "warning")
            return redirect(url_for("costing.edit_packaging_profile", profile_id=profile.id))

        profile.profile_name = profile_name
        profile.cost_per_portion = cost_per_portion
        profile.notes = notes
        profile.is_active = is_active
        profile.updated_by = current_user.id
        db.session.commit()

        record_audit_log(module="HPP", event_type="PACKAGING_PROFILE_UPDATED", action="UPDATE", table_name="packaging_profiles", record_id=profile.id, description=f"Profil kemasan diperbarui: {profile.profile_name}.")
        flash("Profil kemasan berhasil diperbarui.", "success")
        return redirect(url_for("costing.packaging_profiles"))

    return render_template("costing/packaging_profile_form.html", profile=profile)


@costing_bp.route("/packaging-profiles/<int:profile_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_packaging_profile(profile_id):
    profile = PackagingProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil kemasan tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.packaging_profiles"))

    profile.is_active = not profile.is_active
    profile.updated_by = current_user.id
    db.session.commit()
    record_audit_log(module="HPP", event_type="PACKAGING_PROFILE_TOGGLED", action="UPDATE", table_name="packaging_profiles", record_id=profile.id, description=f"Status profil kemasan diubah: {profile.profile_name}.", new_value={"is_active": profile.is_active})
    flash("Status profil kemasan berhasil diubah.", "success")
    return redirect(url_for("costing.packaging_profiles"))


@costing_bp.route("/overhead-profiles")
@role_required("ADMIN")
def overhead_profiles():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ACTIVE"

    query = OverheadProfile.query.filter(OverheadProfile.branch_id == current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                OverheadProfile.profile_code.ilike(f"%{q}%"),
                OverheadProfile.profile_name.ilike(f"%{q}%"),
                OverheadProfile.notes.ilike(f"%{q}%"),
            )
        )

    if status == "ACTIVE":
        query = query.filter(OverheadProfile.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(OverheadProfile.is_active == False)

    profiles = query.order_by(OverheadProfile.profile_name.asc()).all()
    active_count = OverheadProfile.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()

    return render_template(
        "costing/overhead_profiles.html",
        profiles=profiles,
        q=q,
        status=status,
        active_count=active_count,
    )


@costing_bp.route("/overhead-profiles/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_overhead_profile():
    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        gas_cost_per_portion = to_float(request.form.get("gas_cost_per_portion"))
        electricity_cost_per_portion = to_float(request.form.get("electricity_cost_per_portion"))
        water_cost_per_portion = to_float(request.form.get("water_cost_per_portion"))
        labor_cost_per_portion = to_float(request.form.get("labor_cost_per_portion"))
        spices_cost_per_portion = to_float(request.form.get("spices_cost_per_portion"))
        other_cost_per_portion = to_float(request.form.get("other_cost_per_portion"))
        overhead_percentage = to_float(request.form.get("overhead_percentage"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        costs = [gas_cost_per_portion, electricity_cost_per_portion, water_cost_per_portion, labor_cost_per_portion, spices_cost_per_portion, other_cost_per_portion, overhead_percentage]
        if not profile_name:
            flash("Nama profil overhead wajib diisi.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        if any(value < 0 for value in costs):
            flash("Biaya overhead dan persentase tidak boleh minus.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        if overhead_percentage >= 100:
            flash("Overhead persentase harus di bawah 100%.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        if overhead_profile_name_is_used(profile_name, current_user.branch_id):
            flash("Nama profil overhead sudah ada di cabang ini.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        profile = OverheadProfile(
            branch_id=current_user.branch_id,
            profile_code=generate_overhead_profile_code(),
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
            updated_by=current_user.id,
        )
        db.session.add(profile)
        db.session.commit()

        flash("Profil overhead berhasil dibuat. Data ini masih read-only untuk kalkulator HPP.", "success")
        return redirect(url_for("costing.overhead_profiles"))

    return render_template("costing/overhead_profile_form.html", profile=None)


@costing_bp.route("/overhead-profiles/<int:profile_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_overhead_profile(profile_id):
    profile = OverheadProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil overhead tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.overhead_profiles"))

    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        gas_cost_per_portion = to_float(request.form.get("gas_cost_per_portion"))
        electricity_cost_per_portion = to_float(request.form.get("electricity_cost_per_portion"))
        water_cost_per_portion = to_float(request.form.get("water_cost_per_portion"))
        labor_cost_per_portion = to_float(request.form.get("labor_cost_per_portion"))
        spices_cost_per_portion = to_float(request.form.get("spices_cost_per_portion"))
        other_cost_per_portion = to_float(request.form.get("other_cost_per_portion"))
        overhead_percentage = to_float(request.form.get("overhead_percentage"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        costs = [gas_cost_per_portion, electricity_cost_per_portion, water_cost_per_portion, labor_cost_per_portion, spices_cost_per_portion, other_cost_per_portion, overhead_percentage]
        if not profile_name:
            flash("Nama profil overhead wajib diisi.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        if any(value < 0 for value in costs):
            flash("Biaya overhead dan persentase tidak boleh minus.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        if overhead_percentage >= 100:
            flash("Overhead persentase harus di bawah 100%.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        if overhead_profile_name_is_used(profile_name, current_user.branch_id, exclude_id=profile.id):
            flash("Nama profil overhead sudah digunakan data lain.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

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
        profile.updated_by = current_user.id
        db.session.commit()

        record_audit_log(module="HPP", event_type="OVERHEAD_PROFILE_UPDATED", action="UPDATE", table_name="overhead_profiles", record_id=profile.id, description=f"Profil overhead diperbarui: {profile.profile_name}.")
        flash("Profil overhead berhasil diperbarui.", "success")
        return redirect(url_for("costing.overhead_profiles"))

    return render_template("costing/overhead_profile_form.html", profile=profile)


@costing_bp.route("/overhead-profiles/<int:profile_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_overhead_profile(profile_id):
    profile = OverheadProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil overhead tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.overhead_profiles"))

    profile.is_active = not profile.is_active
    profile.updated_by = current_user.id
    db.session.commit()
    record_audit_log(module="HPP", event_type="OVERHEAD_PROFILE_TOGGLED", action="UPDATE", table_name="overhead_profiles", record_id=profile.id, description=f"Status profil overhead diubah: {profile.profile_name}.", new_value={"is_active": profile.is_active})
    flash("Status profil overhead berhasil diubah.", "success")
    return redirect(url_for("costing.overhead_profiles"))


@costing_bp.route("/hpp-calculator")
@role_required("ADMIN")
def hpp_calculator():
    menu_id = request.args.get("menu_id")
    packaging_profile_id = request.args.get("packaging_profile_id")
    overhead_profile_id = request.args.get("overhead_profile_id")
    portion_qty = to_float(request.args.get("portion_qty") or 0)
    target_margin_percentage = to_float(request.args.get("target_margin_percentage") or 30)
    selling_price_raw = (request.args.get("selling_price_per_portion") or "").strip()

    menus = Menu.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Menu.menu_name.asc()).all()
    packaging_profiles = PackagingProfile.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(PackagingProfile.profile_name.asc()).all()
    overhead_profiles = OverheadProfile.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(OverheadProfile.profile_name.asc()).all()

    selected_menu = None
    selected_packaging_profile = None
    selected_overhead_profile = None
    result = None

    if menu_id:
        selected_menu = Menu.query.filter_by(
            id=menu_id,
            branch_id=current_user.branch_id,
        ).first()

        if not selected_menu:
            flash("Menu tidak ditemukan atau tidak sesuai cabang user.", "warning")
            return redirect(url_for("costing.hpp_calculator"))

        if portion_qty <= 0:
            portion_qty = 1

        if packaging_profile_id:
            selected_packaging_profile = PackagingProfile.query.filter_by(
                id=packaging_profile_id,
                branch_id=current_user.branch_id,
                is_active=True,
            ).first()
            if not selected_packaging_profile:
                flash("Profil kemasan tidak ditemukan atau tidak aktif.", "warning")
                return redirect(url_for("costing.hpp_calculator"))

        if overhead_profile_id:
            selected_overhead_profile = OverheadProfile.query.filter_by(
                id=overhead_profile_id,
                branch_id=current_user.branch_id,
                is_active=True,
            ).first()
            if not selected_overhead_profile:
                flash("Profil overhead tidak ditemukan atau tidak aktif.", "warning")
                return redirect(url_for("costing.hpp_calculator"))

        selling_price = None if selling_price_raw == "" else to_float(selling_price_raw)
        result = calculate_menu_hpp(
            selected_menu,
            portion_qty=portion_qty,
            selling_price_per_portion=selling_price,
            target_margin_percentage=target_margin_percentage,
            packaging_profile=selected_packaging_profile,
            overhead_profile=selected_overhead_profile,
        )

    return render_template(
        "costing/hpp_calculator.html",
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
        selected_menu=selected_menu,
        selected_packaging_profile=selected_packaging_profile,
        selected_overhead_profile=selected_overhead_profile,
        portion_qty=portion_qty,
        selling_price_raw=selling_price_raw,
        target_margin_percentage=target_margin_percentage,
        result=result,
    )
