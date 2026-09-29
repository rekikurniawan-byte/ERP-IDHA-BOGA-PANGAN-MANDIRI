"""Logistics damaged item and stock audit routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.logistics_routes import *  # noqa: F401,F403


@logistics_bp.route("/damaged")
@role_required("OWNER", "LOGISTICS")
def damaged():
    from datetime import date
    from app.models.logistics import StockMovement

    movements = StockMovement.query.filter_by(
        branch_id=current_user.branch_id,
        movement_type="DAMAGED"
    ).order_by(
        StockMovement.movement_date.desc(),
        StockMovement.id.desc()
    ).all()

    today_count = sum(1 for movement in movements if movement.movement_date == date.today())
    unique_items = len(set(movement.item_id for movement in movements))

    return render_template(
        "logistics/damaged_index.html",
        movements=movements,
        today_count=today_count,
        unique_items=unique_items
    )


@logistics_bp.route("/damaged/create", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def create_damaged():
    from app.services.stock_service import get_stock_items, create_stock_movement

    items = get_stock_items()

    if request.method == "POST":
        item_id = request.form.get("item_id")
        movement_date_text = request.form.get("movement_date")
        qty = request.form.get("qty")
        damage_reason = (request.form.get("damage_reason") or "").strip()
        damage_location = (request.form.get("damage_location") or "").strip()
        notes_input = (request.form.get("notes") or "").strip()

        if not item_id:
            flash("Item wajib dipilih.", "warning")
            return redirect(url_for("logistics.create_damaged"))

        if not damage_reason:
            flash("Alasan barang rusak wajib diisi.", "warning")
            return redirect(url_for("logistics.create_damaged"))

        movement_date = datetime.strptime(movement_date_text, "%Y-%m-%d").date()

        notes = f"Alasan rusak: {damage_reason}"

        if damage_location:
            notes += f" | Lokasi: {damage_location}"

        if notes_input:
            notes += f" | Catatan: {notes_input}"

        success, message, movement = create_stock_movement(
            branch_id=current_user.branch_id,
            item_id=int(item_id),
            movement_date=movement_date,
            movement_type="DAMAGED",
            reference_type="BARANG_RUSAK",
            qty=qty,
            notes=notes,
            created_by=current_user.id
        )

        if success and movement:
            record_audit_log(
                module="LOGISTICS",
                event_type="DAMAGED_STOCK_CREATED",
                action="CREATE",
                table_name="stock_movements",
                record_id=movement.id,
                description=f"Barang rusak dicatat untuk item #{item_id} sebanyak {qty}.",
                metadata={"item_id": item_id, "qty": qty, "damage_reason": damage_reason, "damage_location": damage_location},
            )

        flash(message, "success" if success else "warning")

        if success:
            return redirect(url_for("logistics.damaged"))

        return redirect(url_for("logistics.create_damaged"))

    return render_template(
        "logistics/damaged_form.html",
        items=items,
        today=date.today()
    )



# === PATCH_STOCK_AUDIT_ROUTES ===
@logistics_bp.route("/audit")
@role_required("OWNER", "LOGISTICS")
def audit():
    from app.models.logistics import StockMovement

    movements = StockMovement.query.filter_by(
        branch_id=current_user.branch_id,
        reference_type="AUDIT_STOK"
    ).order_by(
        StockMovement.movement_date.desc(),
        StockMovement.id.desc()
    ).all()

    plus_count = sum(1 for movement in movements if movement.movement_type == "ADJUSTMENT_IN")
    minus_count = sum(1 for movement in movements if movement.movement_type == "ADJUSTMENT_OUT")
    same_count = sum(1 for movement in movements if movement.movement_type == "AUDIT_OK")

    return render_template(
        "logistics/audit_index.html",
        movements=movements,
        plus_count=plus_count,
        minus_count=minus_count,
        same_count=same_count
    )


@logistics_bp.route("/audit/create", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def create_audit():
    from app.models.master import Item
    from app.services.stock_service import get_stock_items, get_item_stock, is_integer_unit

    items = get_stock_items()

    item_rows = []

    for item in items:
        item_rows.append({
            "item": item,
            "stock_qty": get_item_stock(current_user.branch_id, item.id)
        })

    if request.method == "POST":
        item_id = request.form.get("item_id")
        audit_date_text = request.form.get("audit_date")
        physical_stock_raw = request.form.get("physical_stock")
        reason = (request.form.get("reason") or "").strip()
        notes_input = (request.form.get("notes") or "").strip()

        if not item_id:
            flash("Item wajib dipilih.", "warning")
            return redirect(url_for("logistics.create_audit"))

        if not audit_date_text:
            flash("Tanggal audit wajib diisi.", "warning")
            return redirect(url_for("logistics.create_audit"))

        if physical_stock_raw is None or physical_stock_raw == "":
            flash("Stok fisik wajib diisi.", "warning")
            return redirect(url_for("logistics.create_audit"))

        if not reason:
            flash("Alasan audit wajib diisi.", "warning")
            return redirect(url_for("logistics.create_audit"))

        item = Item.query.get(int(item_id))

        if not item:
            flash("Item tidak ditemukan.", "warning")
            return redirect(url_for("logistics.create_audit"))

        if not item.is_active:
            flash("Item tidak aktif.", "warning")
            return redirect(url_for("logistics.create_audit"))

        if not item.is_stock_tracked:
            flash("Item ini tidak dilacak stoknya.", "warning")
            return redirect(url_for("logistics.create_audit"))

        audit_date = datetime.strptime(audit_date_text, "%Y-%m-%d").date()
        physical_stock = float(physical_stock_raw or 0)

        if physical_stock < 0:
            flash("Stok fisik tidak boleh minus.", "warning")
            return redirect(url_for("logistics.create_audit"))

        if is_integer_unit(item.unit) and not physical_stock.is_integer():
            flash(f"Untuk satuan {item.unit}, stok fisik harus angka bulat.", "warning")
            return redirect(url_for("logistics.create_audit"))

        # get_item_stock mengembalikan Decimal; stok fisik dari form float.
        system_stock = float(get_item_stock(current_user.branch_id, item.id))
        difference = round(physical_stock - system_stock, 4)

        notes = (
            f"Audit stok | Stok sistem: {system_stock:g} {item.unit} | "
            f"Stok fisik: {physical_stock:g} {item.unit} | "
            f"Selisih: {difference:g} {item.unit} | "
            f"Alasan: {reason}"
        )

        if notes_input:
            notes += f" | Catatan: {notes_input}"

        if difference > 0:
            movement_type = "ADJUSTMENT_IN"
            qty = difference
            success_message = "Audit stok berhasil. Stok sistem ditambah sesuai stok fisik."
        elif difference < 0:
            movement_type = "ADJUSTMENT_OUT"
            qty = abs(difference)
            success_message = "Audit stok berhasil. Stok sistem dikurangi sesuai stok fisik."
        else:
            movement_type = "AUDIT_OK"
            qty = 0
            success_message = "Audit stok berhasil. Stok sistem sudah sama dengan stok fisik."

        validate_stock_movement_guard(
            movement_type,
            qty,
            current_stock=system_stock,
            item_unit=item.unit,
            is_integer_unit=is_integer_unit(item.unit),
            allow_zero=True,
            allow_audit_ok=True,
        )

        movement = create_stock_audit_movement(
            branch_id=current_user.branch_id,
            item_id=item.id,
            movement_date=audit_date,
            movement_type=movement_type,
            reference_type="AUDIT_STOK",
            reference_id=None,
            qty=qty,
            notes=notes,
            created_by=current_user.id
        )

        record_audit_log(
            module="LOGISTICS",
            event_type="STOCK_AUDIT_CREATED",
            action="CREATE",
            table_name="stock_movements",
            record_id=movement.id,
            description=f"Audit stok dicatat untuk {item.item_name}: sistem {system_stock:g}, fisik {physical_stock:g}, selisih {difference:g}.",
            metadata={
                "item_id": item.id,
                "system_stock": system_stock,
                "physical_stock": physical_stock,
                "difference": difference,
                "movement_type": movement_type,
                "qty": qty,
                "reason": reason,
            },
        )

        flash(success_message, "success")
        return redirect(url_for("logistics.audit"))

    return render_template(
        "logistics/audit_form.html",
        item_rows=item_rows,
        today=date.today()
    )
