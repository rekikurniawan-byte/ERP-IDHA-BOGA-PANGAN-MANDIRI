"""Logistics stock movement routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.logistics_routes import *  # noqa: F401,F403


@logistics_bp.route("/")
@role_required("OWNER", "LOGISTICS")
def index():
    summary = get_stock_summary(current_user.branch_id)
    recent_movements = get_recent_movements(current_user.branch_id, limit=15)

    return render_template(
        "logistics/index.html",
        summary=summary,
        recent_movements=recent_movements
    )


@logistics_bp.route("/material-forecast")
@role_required("OWNER", "LOGISTICS", "DAPUR")
def material_forecast():
    date_from_raw = (request.args.get("date_from") or "").strip()
    date_to_raw = (request.args.get("date_to") or "").strip()
    status_filter = (request.args.get("status") or "ALL").strip().upper()

    try:
        date_from = datetime.strptime(date_from_raw, "%Y-%m-%d").date() if date_from_raw else date.today()
    except ValueError:
        flash("Tanggal awal prediksi tidak valid.", "warning")
        return redirect(url_for("logistics.material_forecast"))

    try:
        date_to = datetime.strptime(date_to_raw, "%Y-%m-%d").date() if date_to_raw else date_from + timedelta(days=6)
    except ValueError:
        flash("Tanggal akhir prediksi tidak valid.", "warning")
        return redirect(url_for("logistics.material_forecast", date_from=date_from.isoformat()))

    allowed_statuses = ["ALL", "LOCKED", "DRAFT"]
    if status_filter not in allowed_statuses:
        status_filter = "ALL"

    forecast = build_material_requirement_forecast(
        branch_id=current_user.branch_id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
    )

    return render_template(
        "logistics/material_forecast.html",
        forecast=forecast,
        date_from=forecast["date_from"].isoformat(),
        date_to=forecast["date_to"].isoformat(),
        status_filter=forecast["status_filter"],
    )


@logistics_bp.route("/stock-in", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def stock_in():
    items = get_stock_items()

    if request.method == "POST":
        item_id = int(request.form.get("item_id"))
        movement_date = datetime.strptime(request.form.get("movement_date"), "%Y-%m-%d").date()
        qty = request.form.get("qty")

        purchase_place = (request.form.get("purchase_place") or "").strip()
        notes_input = (request.form.get("notes") or "").strip()

        if not purchase_place:
            purchase_place = "Pembelian sendiri"

        notes = f"Tempat belanja: {purchase_place}"

        if notes_input:
            notes += f" | {notes_input}"

        success, message, movement = create_stock_movement(
            branch_id=current_user.branch_id,
            item_id=item_id,
            movement_date=movement_date,
            movement_type="IN",
            reference_type="PEMBELIAN_SENDIRI",
            qty=qty,
            notes=notes,
            created_by=current_user.id
        )

        if success and movement:
            record_audit_log(
                module="LOGISTICS",
                event_type="STOCK_IN_MANUAL_CREATED",
                action="CREATE",
                table_name="stock_movements",
                record_id=movement.id,
                description=f"Stok masuk manual dicatat untuk item #{item_id} sebanyak {qty}.",
                metadata={"item_id": item_id, "qty": qty, "reference_type": "PEMBELIAN_SENDIRI", "purchase_place": purchase_place},
            )

        flash(message, "success" if success else "warning")
        return redirect(url_for("logistics.index"))

    return render_template(
        "logistics/stock_form.html",
        title="Stok Masuk",
        description="Catat barang yang dibeli sendiri lalu masuk ke stok.",
        form_action=url_for("logistics.stock_in"),
        movement_type="IN",
        items=items,
        today=date.today()
    )


@logistics_bp.route("/stock-out", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def stock_out():
    items = get_stock_items()

    if request.method == "POST":
        item_id = int(request.form.get("item_id"))
        movement_date = datetime.strptime(request.form.get("movement_date"), "%Y-%m-%d").date()
        qty = request.form.get("qty")

        usage_purpose = request.form.get("usage_purpose") or "OPERASIONAL"
        notes_input = (request.form.get("notes") or "").strip()

        purpose_labels = {
            "PRODUKSI": "Kebutuhan produksi dapur",
            "OPERASIONAL": "Kebutuhan operasional",
            "LAINNYA": "Kebutuhan lainnya"
        }

        purpose_text = purpose_labels.get(usage_purpose, "Kebutuhan lainnya")
        notes = f"Tujuan pemakaian: {purpose_text}"

        if notes_input:
            notes += f" | {notes_input}"

        success, message, movement = create_stock_movement(
            branch_id=current_user.branch_id,
            item_id=item_id,
            movement_date=movement_date,
            movement_type="OUT",
            reference_type=f"PEMAKAIAN_{usage_purpose}",
            qty=qty,
            notes=notes,
            created_by=current_user.id
        )

        if success and movement:
            record_audit_log(
                module="LOGISTICS",
                event_type="STOCK_OUT_MANUAL_CREATED",
                action="CREATE",
                table_name="stock_movements",
                record_id=movement.id,
                description=f"Stok keluar manual dicatat untuk item #{item_id} sebanyak {qty}.",
                metadata={"item_id": item_id, "qty": qty, "reference_type": f"PEMAKAIAN_{usage_purpose}", "usage_purpose": usage_purpose},
            )

        flash(message, "success" if success else "warning")
        return redirect(url_for("logistics.index"))

    return render_template(
        "logistics/stock_form.html",
        title="Stok Keluar",
        description="Catat bahan/barang yang keluar untuk produksi atau kebutuhan operasional.",
        form_action=url_for("logistics.stock_out"),
        movement_type="OUT",
        items=items,
        today=date.today()
    )


@logistics_bp.route("/adjustment", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def adjustment():
    items = get_stock_items()

    if request.method == "POST":
        item_id = int(request.form.get("item_id"))
        movement_date = datetime.strptime(request.form.get("movement_date"), "%Y-%m-%d").date()
        adjustment_type = request.form.get("adjustment_type")
        qty = request.form.get("qty")
        notes = request.form.get("notes") or "Penyesuaian stok"

        allowed_types = ["ADJUSTMENT_IN", "ADJUSTMENT_OUT", "DAMAGED", "WASTE"]

        if adjustment_type not in allowed_types:
            flash("Jenis penyesuaian tidak valid.", "warning")
            return redirect(url_for("logistics.adjustment"))

        success, message, movement = create_stock_movement(
            branch_id=current_user.branch_id,
            item_id=item_id,
            movement_date=movement_date,
            movement_type=adjustment_type,
            reference_type="PENYESUAIAN_STOK",
            qty=qty,
            notes=notes,
            created_by=current_user.id
        )

        if success and movement:
            record_audit_log(
                module="LOGISTICS",
                event_type="STOCK_ADJUSTMENT_CREATED",
                action="CREATE",
                table_name="stock_movements",
                record_id=movement.id,
                description=f"Penyesuaian stok dicatat: {adjustment_type} untuk item #{item_id} sebanyak {qty}.",
                metadata={"item_id": item_id, "qty": qty, "movement_type": adjustment_type, "reference_type": "PENYESUAIAN_STOK"},
            )

        flash(message, "success" if success else "warning")
        return redirect(url_for("logistics.index"))

    return render_template(
        "logistics/adjustment.html",
        items=items,
        today=date.today()
    )


@logistics_bp.route("/opening-balances", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def stock_opening_balances():
    from app.models.logistics import StockOpeningBalance

    items = get_stock_items()

    if request.method == "POST":
        try:
            item_id = int(request.form.get("item_id"))
            opening_date = datetime.strptime(request.form.get("opening_date"), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            flash("Item atau tanggal saldo awal tidak valid.", "warning")
            return redirect(url_for("logistics.stock_opening_balances"))

        qty = request.form.get("qty")
        notes = (request.form.get("notes") or "").strip()
        idempotency_key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex
        idempotency_record = None

        try:
            idempotency_record, reserved = reserve_idempotency_key(
                scope="LOGISTICS_STOCK_OPENING_BALANCE",
                key=idempotency_key,
                branch_id=current_user.branch_id,
                user_id=current_user.id,
                request_payload={
                    "item_id": item_id,
                    "opening_date": opening_date.isoformat(),
                    "qty": str(qty or ""),
                    "notes": notes,
                },
            )
        except IdempotencyConflictError:
            flash("Submit saldo awal berbeda memakai idempotency key yang sama. Muat ulang halaman lalu coba lagi.", "warning")
            return redirect(url_for("logistics.stock_opening_balances"))

        if not reserved:
            flash("Submit saldo awal ini sudah pernah diproses.", "info")
            return redirect(url_for("logistics.stock_opening_balances"))

        success, message, opening = save_stock_opening_balance(
            branch_id=current_user.branch_id,
            item_id=item_id,
            opening_date=opening_date,
            qty=qty,
            notes=notes,
            created_by=current_user.id,
        )

        if success and opening:
            record_audit_log(
                module="LOGISTICS",
                event_type="STOCK_OPENING_BALANCE_SAVED",
                action="UPSERT",
                table_name="stock_opening_balances",
                record_id=opening.id,
                description=f"Saldo awal stok disimpan untuk item #{item_id} sebanyak {qty}.",
                metadata={"item_id": item_id, "opening_date": opening_date.isoformat(), "qty": str(qty or "")},
            )
            mark_idempotency_completed(
                idempotency_record,
                reference_type="STOCK_OPENING_BALANCE",
                reference_id=opening.id,
                response_payload={"opening_balance_id": opening.id},
                commit=True,
            )
        else:
            mark_idempotency_failed(idempotency_record, message, commit=True)

        flash(message, "success" if success else "warning")
        return redirect(url_for("logistics.stock_opening_balances"))

    openings = StockOpeningBalance.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        StockOpeningBalance.opening_date.desc(),
        StockOpeningBalance.id.desc(),
    ).all()

    opening_by_item = {
        opening.item_id: opening
        for opening in openings
    }

    return render_template(
        "logistics/stock_opening_balances.html",
        items=items,
        openings=openings,
        opening_by_item=opening_by_item,
        today=date.today(),
        form_idempotency_key=uuid4().hex,
    )


@logistics_bp.route("/items/<int:item_id>/card")
@role_required("OWNER", "LOGISTICS")
def item_card(item_id):
    item = Item.query.get_or_404(item_id)
    stock_qty = get_item_stock(current_user.branch_id, item.id)
    movements = get_item_movements(current_user.branch_id, item.id)

    return render_template(
        "logistics/item_card.html",
        item=item,
        stock_qty=stock_qty,
        movements=movements
    )
