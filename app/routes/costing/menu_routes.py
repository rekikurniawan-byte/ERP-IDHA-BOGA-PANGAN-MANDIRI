"""Costing menu and recipe routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.costing_routes import *  # noqa: F401,F403


@costing_bp.route("/menus")
@role_required("ADMIN", "DAPUR")
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
                Menu.description.ilike(f"%{q}%"),
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

    from app.services.menu_schedule_service import get_primary_menu_photo

    primary_photos = {m.id: get_primary_menu_photo(m.id) for m in menus}

    return render_template(
        "costing/menus.html",
        menus=menus,
        primary_photos=primary_photos,
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
@role_required("ADMIN", "DAPUR")
def create_menu():
    from app.services.menu_schedule_service import MenuScheduleError, add_menu_photos

    if request.method == "POST":
        menu_name = (request.form.get("menu_name") or "").strip()
        menu_type = (request.form.get("menu_type") or "CATERING").strip().upper()
        default_selling_price = to_float(request.form.get("default_selling_price"))
        description = (request.form.get("description") or "").strip() or None
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

        menu = create_menu_record(
            branch_id=current_user.branch_id,
            menu_code=generate_menu_code(),
            menu_name=menu_name,
            menu_type=menu_type,
            default_selling_price=default_selling_price,
            description=description,
            notes=notes,
            is_active=is_active,
            updated_by=current_user.id,
        )

        photos_uploaded = request.files.getlist("menu_photos")
        if photos_uploaded and any(p.filename for p in photos_uploaded):
            try:
                add_menu_photos(menu, photos_uploaded, acted_by=current_user.id)
            except MenuScheduleError as photo_err:
                flash(f"Menu dibuat, namun foto gagal disimpan: {photo_err}", "warning")

        record_audit_log(module="HPP", event_type="MENU_CREATED", action="CREATE", table_name="menus", record_id=menu.id, description=f"Menu dibuat: {menu.menu_name}.")
        flash("Menu berhasil dibuat. Lanjut lengkapi resep/BOM per porsi.", "success")
        return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

    return render_template("costing/menu_form.html", menu=None, menu_types=MENU_TYPES, menu_photos=[])


@costing_bp.route("/menus/<int:menu_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "DAPUR")
def edit_menu(menu_id):
    from app.services.menu_schedule_service import MenuScheduleError, add_menu_photos, get_menu_photos

    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    if request.method == "POST":
        menu_name = (request.form.get("menu_name") or "").strip()
        menu_type = (request.form.get("menu_type") or "CATERING").strip().upper()
        default_selling_price = to_float(request.form.get("default_selling_price"))
        description = (request.form.get("description") or "").strip() or None
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

        update_menu_record(
            menu,
            menu_name=menu_name,
            menu_type=menu_type,
            default_selling_price=default_selling_price,
            description=description,
            notes=notes,
            is_active=is_active,
        )

        photos_uploaded = request.files.getlist("menu_photos")
        if photos_uploaded and any(p.filename for p in photos_uploaded):
            try:
                add_menu_photos(menu, photos_uploaded, acted_by=current_user.id)
            except MenuScheduleError as photo_err:
                flash(f"Data menu disimpan, namun foto gagal diunggah: {photo_err}", "warning")

        record_audit_log(module="HPP", event_type="MENU_UPDATED", action="UPDATE", table_name="menus", record_id=menu.id, description=f"Menu diperbarui: {menu.menu_name}.")
        flash("Menu berhasil diperbarui.", "success")
        return redirect(url_for("costing.menus"))

    menu_photos = get_menu_photos(menu.id)
    return render_template("costing/menu_form.html", menu=menu, menu_types=MENU_TYPES, menu_photos=menu_photos)


@costing_bp.route("/menus/<int:menu_id>/photos/<int:attachment_id>/delete", methods=["POST"])
@role_required("ADMIN", "DAPUR")
def delete_menu_photo_route(menu_id, attachment_id):
    from app.services.menu_schedule_service import MenuScheduleError, delete_menu_photo

    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    try:
        delete_menu_photo(menu, attachment_id, acted_by=current_user.id)
        flash("Foto menu berhasil dihapus.", "success")
    except MenuScheduleError as err:
        flash(str(err), "warning")

    return redirect(url_for("costing.edit_menu", menu_id=menu.id))


@costing_bp.route("/menus/<int:menu_id>/toggle", methods=["POST"])
@role_required("ADMIN", "DAPUR")
def toggle_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    toggle_menu_active(menu)
    record_audit_log(module="HPP", event_type="MENU_TOGGLED", action="UPDATE", table_name="menus", record_id=menu.id, description=f"Status menu diubah: {menu.menu_name}.", new_value={"is_active": menu.is_active})
    flash("Status menu berhasil diubah.", "success")
    return redirect(url_for("costing.menus"))


@costing_bp.route("/menus/<int:menu_id>/recipe", methods=["GET", "POST"])
@role_required("ADMIN", "DAPUR")
def menu_recipe(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    if menu.branch_id != current_user.branch_id:
        flash("Menu tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    recipe = get_recipe_for_menu(menu)

    if request.method == "POST":
        action = request.form.get("action") or "add_item"

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

            if recipe_status == "FINAL" and (not recipe or not recipe.items):
                flash("Resep belum bisa difinalkan karena item bahan/BOM masih kosong.", "warning")
                return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

            try:
                recipe, created_version = save_recipe_header_record(
                    recipe,
                    menu=menu,
                    recipe_name=recipe_name,
                    base_portion=base_portion,
                    recipe_status=recipe_status,
                    version_label=version_label,
                    version_note=version_note,
                    notes=notes,
                    is_active=is_active,
                    updated_by=current_user.id,
                )
            except RecipeVersionError as exc:
                flash(str(exc), "warning")
                return redirect(url_for("costing.menu_recipe", menu_id=menu.id))

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

        try:
            recipe, recipe_item = add_recipe_item_record(
                recipe,
                menu=menu,
                item=item,
                qty_per_portion=qty_per_portion,
                unit=unit,
                notes=notes,
                updated_by=current_user.id,
            )
        except IntegrityError:
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
@role_required("ADMIN", "DAPUR")
def delete_recipe_item(recipe_item_id):
    recipe_item = RecipeItem.query.get_or_404(recipe_item_id)
    menu = recipe_item.recipe.menu

    if menu.branch_id != current_user.branch_id:
        flash("Item resep tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.menus"))

    menu_id = menu.id
    recipe = recipe_item.recipe
    item_name = recipe_item.item.item_name if recipe_item.item else "item"
    delete_recipe_item_record(recipe_item, updated_by=current_user.id)

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
