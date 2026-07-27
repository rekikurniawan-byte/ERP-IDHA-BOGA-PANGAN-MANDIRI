"""Item, cost profile, and unit conversion master routes.

Route functions moved out of app.routes.master_routes without changing URL rules or endpoint names.
"""
from app.routes.master_routes import *  # noqa: F401,F403


@master_bp.route("/items")
@role_required("ADMIN", "LOGISTICS")
def items():
    q = (request.args.get("q") or "").strip()
    category = request.args.get("category") or "ALL"
    status = request.args.get("status") or "ALL"

    query = Item.query

    if q:
        query = query.filter(
            or_(
                Item.item_code.ilike(f"%{q}%"),
                Item.item_name.ilike(f"%{q}%"),
                Item.unit.ilike(f"%{q}%")
            )
        )

    if category != "ALL":
        query = query.filter(Item.category == category)

    if status == "ACTIVE":
        query = query.filter(Item.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(Item.is_active == False)

    items = query.order_by(Item.category.asc(), Item.item_name.asc()).all()

    return render_template(
        "master/items.html",
        items=items,
        q=q,
        category=category,
        status=status,
        categories=ITEM_CATEGORIES
    )


@master_bp.route("/items/create", methods=["GET", "POST"])
@role_required("ADMIN", "LOGISTICS")
def create_item():
    if request.method == "POST":
        item_name = (request.form.get("item_name") or "").strip()
        category = request.form.get("category")
        unit = (request.form.get("unit") or "").strip()
        minimum_stock = float(request.form.get("minimum_stock") or 0)
        selling_price = float(request.form.get("selling_price") or 0)
        is_stock_tracked = True if request.form.get("is_stock_tracked") == "on" else False
        is_active = True if request.form.get("is_active") == "on" else False

        if not item_name or not category or not unit:
            flash("Nama, kategori, dan satuan barang wajib diisi.", "warning")
            return redirect(url_for("master.create_item"))

        item = create_item_record(
            item_name=item_name,
            item_code=generate_item_code(category),
            category=category,
            unit=unit,
            minimum_stock=minimum_stock,
            selling_price=selling_price,
            is_stock_tracked=is_stock_tracked,
            is_active=is_active
        )

        record_audit_log(
            module="MASTER",
            event_type="ITEM_CREATED",
            action="CREATE",
            table_name="items",
            record_id=item.id,
            description=f"Item master dibuat: {item.item_code} - {item.item_name}.",
            metadata={"item_code": item.item_code, "category": item.category, "unit": item.unit, "is_stock_tracked": item.is_stock_tracked},
        )

        flash(f"Item berhasil ditambahkan dengan kode {item.item_code}.", "success")
        return redirect(url_for("master.items"))

    return render_template(
        "master/item_form.html",
        item=None,
        categories=ITEM_CATEGORIES
    )


@master_bp.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "LOGISTICS")
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)

    if request.method == "POST":
        old_category = item.category

        item_name = (request.form.get("item_name") or "").strip()
        category = request.form.get("category")
        unit = (request.form.get("unit") or "").strip()
        minimum_stock = float(request.form.get("minimum_stock") or 0)
        selling_price = float(request.form.get("selling_price") or 0)
        is_stock_tracked = True if request.form.get("is_stock_tracked") == "on" else False
        is_active = True if request.form.get("is_active") == "on" else False

        if not item_name or not category or not unit:
            flash("Nama, kategori, dan satuan barang wajib diisi.", "warning")
            return redirect(url_for("master.edit_item", item_id=item.id))

        update_item_record(
            item,
            item_name=item_name,
            item_code=item.item_code or generate_item_code(category),
            category=category,
            unit=unit,
            minimum_stock=minimum_stock,
            selling_price=selling_price,
            is_stock_tracked=is_stock_tracked,
            is_active=is_active,
        )

        record_audit_log(
            module="MASTER",
            event_type="ITEM_UPDATED",
            action="UPDATE",
            table_name="items",
            record_id=item.id,
            description=f"Item master diperbarui: {item.item_code} - {item.item_name}.",
            metadata={"item_code": item.item_code, "old_category": old_category, "new_category": item.category, "unit": item.unit, "is_active": item.is_active},
        )

        if old_category != item.category:
            flash("Item berhasil diperbarui. Kategori berubah, jadi item akan muncul sesuai modul barunya.", "success")
        else:
            flash("Item berhasil diperbarui.", "success")

        return redirect(url_for("master.items"))

    return render_template(
        "master/item_form.html",
        item=item,
        categories=ITEM_CATEGORIES
    )


@master_bp.route("/items/<int:item_id>/toggle", methods=["POST"])
@role_required("ADMIN", "LOGISTICS")
def toggle_item(item_id):
    item = Item.query.get_or_404(item_id)
    toggle_item_active(item)

    record_audit_log(
        module="MASTER",
        event_type="ITEM_TOGGLED",
        action="UPDATE",
        table_name="items",
        record_id=item.id,
        description=f"Status item diubah: {item.item_code} - {item.item_name}.",
        metadata={"item_code": item.item_code, "is_active": item.is_active},
    )

    flash("Status item berhasil diubah.", "success")
    return redirect(url_for("master.items"))

@master_bp.route("/items/<int:item_id>/delete", methods=["POST"])
@role_required("ADMIN", "LOGISTICS")
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)

    if item_is_used(item.id):
        flash("Item sudah pernah digunakan pada transaksi/produksi. Data tidak bisa dihapus, silakan nonaktifkan.", "warning")
        return redirect(url_for("master.items"))

    deleted_snapshot = {"item_code": item.item_code, "item_name": item.item_name, "category": item.category}
    item_id_snapshot = item.id
    try:
        delete_item_record(item)
    except SQLAlchemyError:
        current_app.logger.exception("Gagal menghapus item master.")
        flash("Item gagal dihapus karena database menolak operasi hapus. Silakan nonaktifkan item atau cek dependency data.", "danger")
        return redirect(url_for("master.items"))

    record_audit_log(
        module="MASTER",
        event_type="ITEM_DELETED",
        action="DELETE",
        table_name="items",
        record_id=item_id_snapshot,
        description=f"Item master dihapus: {deleted_snapshot.get('item_code')} - {deleted_snapshot.get('item_name')}.",
        old_value=deleted_snapshot,
    )

    flash("Item berhasil dihapus karena belum pernah digunakan transaksi.", "success")
    return redirect(url_for("master.items"))


# =========================
# HPP COST PROFILE TAHAP 1
# =========================

def normalize_unit(value):
    return (value or "").strip().upper()


def calculate_effective_cost_per_base_unit(standard_purchase_price, purchase_qty, conversion_factor, yield_percentage):
    usable_base_qty = float(purchase_qty or 0) * float(conversion_factor or 0) * (float(yield_percentage or 0) / 100)
    if usable_base_qty <= 0:
        return 0
    return float(standard_purchase_price or 0) / usable_base_qty


@master_bp.route("/item-cost-profiles")
@role_required("ADMIN", "LOGISTICS")
def item_cost_profiles():
    q = (request.args.get("q") or "").strip()
    category = request.args.get("category") or "ALL"
    status = request.args.get("status") or "ALL"

    query = Item.query.outerjoin(ItemCostProfile, Item.id == ItemCostProfile.item_id)

    if q:
        query = query.filter(
            or_(
                Item.item_code.ilike(f"%{q}%"),
                Item.item_name.ilike(f"%{q}%"),
                Item.unit.ilike(f"%{q}%")
            )
        )

    if category == "HPP_RELEVANT":
        query = query.filter(Item.category.in_(COST_PROFILE_CATEGORIES))
    elif category != "ALL":
        query = query.filter(Item.category == category)

    if status == "HAS_PROFILE":
        query = query.filter(ItemCostProfile.id.isnot(None))
    elif status == "MISSING_PROFILE":
        query = query.filter(ItemCostProfile.id.is_(None), Item.category.in_(COST_PROFILE_CATEGORIES), Item.is_active == True)
    elif status == "ACTIVE":
        query = query.filter(Item.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(Item.is_active == False)

    items = query.order_by(Item.category.asc(), Item.item_name.asc()).all()

    hpp_items_query = Item.query.filter(Item.category.in_(COST_PROFILE_CATEGORIES), Item.is_active == True)
    hpp_item_count = hpp_items_query.count()
    profiled_count = ItemCostProfile.query.join(Item, Item.id == ItemCostProfile.item_id).filter(
        Item.category.in_(COST_PROFILE_CATEGORIES),
        Item.is_active == True
    ).count()
    missing_count = max(hpp_item_count - profiled_count, 0)
    conversion_count = UnitConversion.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()

    return render_template(
        "master/item_cost_profiles.html",
        items=items,
        q=q,
        category=category,
        status=status,
        categories=ITEM_CATEGORIES,
        hpp_item_count=hpp_item_count,
        profiled_count=profiled_count,
        missing_count=missing_count,
        conversion_count=conversion_count
    )


@master_bp.route("/items/<int:item_id>/cost-profile", methods=["GET", "POST"])
@role_required("ADMIN", "LOGISTICS")
def edit_item_cost_profile(item_id):
    item = Item.query.get_or_404(item_id)
    profile = ItemCostProfile.query.filter_by(item_id=item.id, branch_id=current_user.branch_id).first()
    conversions = UnitConversion.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(
        UnitConversion.unit_from.asc(),
        UnitConversion.unit_to.asc()
    ).all()

    if request.method == "POST":
        purchase_unit = normalize_unit(request.form.get("purchase_unit"))
        base_unit = normalize_unit(request.form.get("base_unit"))
        purchase_qty = to_float(request.form.get("purchase_qty"))
        conversion_factor = to_float(request.form.get("conversion_factor"))
        yield_percentage = to_float(request.form.get("yield_percentage") or 100)
        waste_percentage = to_float(request.form.get("waste_percentage") or 0)
        standard_purchase_price = to_float(request.form.get("standard_purchase_price"))
        cost_source = (request.form.get("cost_source") or "STANDARD").strip().upper()
        notes = (request.form.get("notes") or "").strip() or None

        if not purchase_unit or not base_unit:
            flash("Satuan beli dan satuan dasar wajib diisi.", "warning")
            return redirect(url_for("master.edit_item_cost_profile", item_id=item.id))

        if purchase_qty <= 0:
            flash("Jumlah beli wajib lebih dari 0.", "warning")
            return redirect(url_for("master.edit_item_cost_profile", item_id=item.id))

        if conversion_factor <= 0:
            flash("Faktor konversi wajib lebih dari 0.", "warning")
            return redirect(url_for("master.edit_item_cost_profile", item_id=item.id))

        if yield_percentage <= 0 or yield_percentage > 100:
            flash("Yield wajib di atas 0 dan maksimal 100 persen.", "warning")
            return redirect(url_for("master.edit_item_cost_profile", item_id=item.id))

        if waste_percentage < 0 or waste_percentage > 100:
            flash("Waste wajib 0 sampai 100 persen.", "warning")
            return redirect(url_for("master.edit_item_cost_profile", item_id=item.id))

        if standard_purchase_price < 0:
            flash("Harga standar tidak boleh minus.", "warning")
            return redirect(url_for("master.edit_item_cost_profile", item_id=item.id))

        if cost_source not in COST_SOURCES:
            cost_source = "STANDARD"

        effective_cost = calculate_effective_cost_per_base_unit(
            standard_purchase_price,
            purchase_qty,
            conversion_factor,
            yield_percentage
        )

        profile = save_item_cost_profile(
            profile,
            item_id=item.id,
            branch_id=current_user.branch_id,
            purchase_unit=purchase_unit,
            purchase_qty=purchase_qty,
            base_unit=base_unit,
            conversion_factor=conversion_factor,
            yield_percentage=yield_percentage,
            waste_percentage=waste_percentage,
            standard_purchase_price=standard_purchase_price,
            effective_cost_per_base_unit=effective_cost,
            cost_source=cost_source,
            notes=notes,
            updated_by=current_user.id,
        )
        record_audit_log(
            module="HPP",
            event_type="ITEM_COST_PROFILE_UPDATED",
            action="UPDATE",
            table_name="item_cost_profiles",
            record_id=profile.id,
            description=f"Profil HPP item disimpan: {item.item_name}.",
        )
        flash("Profil HPP item berhasil disimpan. Data ini belum mengubah stok/jurnal.", "success")
        return redirect(url_for("master.item_cost_profiles"))

    return render_template(
        "master/item_cost_profile_form.html",
        item=item,
        profile=profile,
        conversions=conversions,
        cost_units=COST_UNITS,
        cost_sources=COST_SOURCES
    )


@master_bp.route("/unit-conversions", methods=["GET", "POST"])
@role_required("ADMIN", "LOGISTICS")
def unit_conversions():
    if request.method == "POST":
        unit_from = normalize_unit(request.form.get("unit_from"))
        unit_to = normalize_unit(request.form.get("unit_to"))
        multiplier = to_float(request.form.get("multiplier"))
        notes = (request.form.get("notes") or "").strip() or None

        if not unit_from or not unit_to:
            flash("Satuan asal dan satuan tujuan wajib diisi.", "warning")
            return redirect(url_for("master.unit_conversions"))

        if unit_from == unit_to:
            flash("Satuan asal dan tujuan tidak boleh sama.", "warning")
            return redirect(url_for("master.unit_conversions"))

        if multiplier <= 0:
            flash("Multiplier konversi wajib lebih dari 0.", "warning")
            return redirect(url_for("master.unit_conversions"))

        existing = UnitConversion.query.filter(
            UnitConversion.branch_id == current_user.branch_id,
            func.lower(UnitConversion.unit_from) == unit_from.lower(),
            func.lower(UnitConversion.unit_to) == unit_to.lower()
        ).first()

        was_existing = existing is not None
        upsert_unit_conversion(
            existing,
            branch_id=current_user.branch_id,
            unit_from=unit_from,
            unit_to=unit_to,
            multiplier=multiplier,
            notes=notes,
            created_by=current_user.id,
        )

        if was_existing:
            flash("Konversi satuan sudah ada, datanya diperbarui.", "success")
        else:
            flash("Konversi satuan berhasil ditambahkan.", "success")

        record_audit_log(
            module="HPP",
            event_type="UNIT_CONVERSION_SAVED",
            action="UPSERT",
            table_name="unit_conversions",
            record_id=(existing.id if was_existing else None),
            description=f"Konversi satuan disimpan: {unit_from} ke {unit_to}.",
            metadata={"unit_from": unit_from, "unit_to": unit_to, "multiplier": multiplier},
        )
        return redirect(url_for("master.unit_conversions"))

    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ACTIVE"

    query = UnitConversion.query.filter(UnitConversion.branch_id == current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                UnitConversion.unit_from.ilike(f"%{q}%"),
                UnitConversion.unit_to.ilike(f"%{q}%"),
                UnitConversion.notes.ilike(f"%{q}%")
            )
        )

    if status == "ACTIVE":
        query = query.filter(UnitConversion.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(UnitConversion.is_active == False)

    conversions = query.order_by(UnitConversion.unit_from.asc(), UnitConversion.unit_to.asc()).all()

    return render_template(
        "master/unit_conversions.html",
        conversions=conversions,
        q=q,
        status=status,
        cost_units=COST_UNITS
    )


@master_bp.route("/unit-conversions/<int:conversion_id>/toggle", methods=["POST"])
@role_required("ADMIN", "LOGISTICS")
def toggle_unit_conversion(conversion_id):
    conversion = UnitConversion.query.get_or_404(conversion_id)

    if conversion.branch_id != current_user.branch_id:
        flash("Konversi satuan tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.unit_conversions"))

    toggle_unit_conversion_active(conversion)

    record_audit_log(
        module="HPP",
        event_type="UNIT_CONVERSION_TOGGLED",
        action="UPDATE",
        table_name="unit_conversions",
        record_id=conversion.id,
        description="Status konversi satuan diubah.",
        new_value={"is_active": conversion.is_active},
    )
    flash("Status konversi satuan berhasil diubah.", "success")
    return redirect(url_for("master.unit_conversions"))
