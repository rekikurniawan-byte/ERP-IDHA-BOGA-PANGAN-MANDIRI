"""Logistics item request routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.logistics_routes import *  # noqa: F401,F403


@logistics_bp.route("/item-requests")
@role_required("OWNER", "LOGISTICS", "DAPUR")
def item_requests():
    from app.models.logistics import ItemRequest

    status_filter = request.args.get("status") or "ALL"

    query = ItemRequest.query.filter_by(
        branch_id=current_user.branch_id
    )

    if status_filter != "ALL":
        query = query.filter(ItemRequest.status == status_filter)

    requests_data = query.order_by(
        ItemRequest.request_date.desc(),
        ItemRequest.id.desc()
    ).all()

    pending_count = sum(1 for row in requests_data if row.status == "PENDING")
    approved_count = sum(1 for row in requests_data if row.status == "APPROVED")
    fulfilled_count = sum(1 for row in requests_data if row.status == "FULFILLED")

    return render_template(
        "logistics/item_request_index.html",
        requests_data=requests_data,
        status_filter=status_filter,
        pending_count=pending_count,
        approved_count=approved_count,
        fulfilled_count=fulfilled_count
    )


@logistics_bp.route("/item-requests/create", methods=["GET", "POST"])
@role_required("DAPUR")
def create_item_request():
    from app.models.logistics import ItemRequest
    from app.models.master import Item
    from app.services.stock_service import get_stock_items, is_integer_unit, get_item_stock

    items = get_stock_items()

    item_rows = []

    for item in items:
        item_rows.append({
            "item": item,
            "stock_qty": get_item_stock(current_user.branch_id, item.id)
        })

    if request.method == "POST":
        request_date = datetime.strptime(request.form.get("request_date"), "%Y-%m-%d").date()
        purpose = (request.form.get("purpose") or "Kebutuhan produksi dapur").strip()
        notes = (request.form.get("notes") or "").strip()

        item_ids = request.form.getlist("item_id[]")
        qtys = request.form.getlist("requested_qty[]")
        detail_notes = request.form.getlist("detail_notes[]")

        valid_rows = []

        try:
            for item_id, qty_raw, note in zip(item_ids, qtys, detail_notes):
                if not item_id:
                    continue

                item = Item.query.get(int(item_id))

                if not item:
                    flash("Ada item yang tidak ditemukan.", "warning")
                    return redirect(url_for("logistics.create_item_request"))

                if not item.is_active:
                    flash(f"Item {item.item_name} tidak aktif.", "warning")
                    return redirect(url_for("logistics.create_item_request"))

                if not item.is_stock_tracked:
                    flash(f"Item {item.item_name} tidak dilacak stoknya.", "warning")
                    return redirect(url_for("logistics.create_item_request"))

                requested_qty = float(qty_raw or 0)

                if requested_qty <= 0:
                    flash(f"Qty permintaan untuk {item.item_name} wajib lebih dari 0.", "warning")
                    return redirect(url_for("logistics.create_item_request"))

                if is_integer_unit(item.unit) and not requested_qty.is_integer():
                    flash(f"Untuk satuan {item.unit}, qty {item.item_name} harus angka bulat.", "warning")
                    return redirect(url_for("logistics.create_item_request"))

                valid_rows.append({
                    "item": item,
                    "requested_qty": requested_qty,
                    "notes": (note or "").strip()
                })

            if not valid_rows:
                flash("Minimal isi 1 item permintaan.", "warning")
                return redirect(url_for("logistics.create_item_request"))

            same_day_count = ItemRequest.query.filter_by(
                branch_id=current_user.branch_id,
                request_date=request_date
            ).count()

            request_number = f"REQ-{request_date.strftime('%Y%m%d')}-{same_day_count + 1:03d}"

            item_request = create_item_request_record(
                request_number=request_number,
                branch_id=current_user.branch_id,
                request_date=request_date,
                requested_by=current_user.id,
                purpose=purpose,
                notes=notes,
                rows=valid_rows,
            )

            record_audit_log(
                module="LOGISTICS",
                event_type="ITEM_REQUEST_CREATED",
                action="CREATE",
                table_name="item_requests",
                record_id=item_request.id,
                description=f"Permintaan barang dapur dibuat: {item_request.request_number}.",
                metadata={"request_number": item_request.request_number, "item_count": len(valid_rows), "purpose": purpose},
            )

            flash("Permintaan barang berhasil dibuat. Status masih PENDING dan belum mengurangi stok.", "success")
            return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

        except Exception as error:
            logger.exception("Suppressed unexpected exception in app/routes/logistics_routes.py:1261")
            flash(f"Gagal membuat permintaan barang: {error}", "danger")
            return redirect(url_for("logistics.create_item_request"))

    return render_template(
        "logistics/item_request_form.html",
        item_rows=item_rows,
        today=date.today()
    )


@logistics_bp.route("/item-requests/<int:request_id>")
@role_required("OWNER", "LOGISTICS", "DAPUR")
def item_request_detail(request_id):
    from app.models.logistics import ItemRequest
    from app.services.stock_service import get_item_stock

    item_request = ItemRequest.query.get_or_404(request_id)

    if item_request.branch_id != current_user.branch_id:
        flash("Data permintaan barang tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.item_requests"))

    stock_map = {}

    for detail in item_request.details:
        stock_map[detail.item_id] = get_item_stock(current_user.branch_id, detail.item_id)

    return render_template(
        "logistics/item_request_detail.html",
        item_request=item_request,
        stock_map=stock_map,
        fulfill_idempotency_key=uuid4().hex,
    )



# === PATCH_ITEM_REQUEST_APPROVE_REJECT ===
@logistics_bp.route("/item-requests/<int:request_id>/approve", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def approve_item_request(request_id):
    from app.models.logistics import ItemRequest

    item_request = ItemRequest.query.get_or_404(request_id)

    if item_request.branch_id != current_user.branch_id:
        flash("Data permintaan barang tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.item_requests"))

    if item_request.status != "PENDING":
        flash("Permintaan hanya bisa disetujui jika status masih PENDING.", "warning")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    owner_note = (request.form.get("owner_note") or "").strip()

    approve_item_request_record(item_request, owner_note=owner_note)

    record_audit_log(
        module="LOGISTICS",
        event_type="ITEM_REQUEST_APPROVED",
        action="UPDATE",
        table_name="item_requests",
        record_id=item_request.id,
        description=f"Permintaan barang disetujui: {item_request.request_number}.",
        metadata={"request_number": item_request.request_number, "owner_note": owner_note},
    )

    flash("Permintaan barang berhasil disetujui. Stok belum berkurang sampai permintaan dipenuhi.", "success")
    return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))


@logistics_bp.route("/item-requests/<int:request_id>/reject", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def reject_item_request(request_id):
    from app.models.logistics import ItemRequest

    item_request = ItemRequest.query.get_or_404(request_id)

    if item_request.branch_id != current_user.branch_id:
        flash("Data permintaan barang tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.item_requests"))

    if item_request.status != "PENDING":
        flash("Permintaan hanya bisa ditolak jika status masih PENDING.", "warning")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    reject_reason = (request.form.get("reject_reason") or "").strip()

    if not reject_reason:
        flash("Alasan penolakan wajib diisi.", "warning")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    reject_item_request_record(item_request, reject_reason=reject_reason)

    record_audit_log(
        module="LOGISTICS",
        event_type="ITEM_REQUEST_REJECTED",
        action="UPDATE",
        table_name="item_requests",
        record_id=item_request.id,
        description=f"Permintaan barang ditolak: {item_request.request_number}.",
        metadata={"request_number": item_request.request_number, "reject_reason": reject_reason},
    )

    flash("Permintaan barang berhasil ditolak.", "success")
    return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))



# === PATCH_ITEM_REQUEST_FULFILL ===
@logistics_bp.route("/item-requests/<int:request_id>/fulfill", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def fulfill_item_request(request_id):
    from app.models.logistics import ItemRequest
    from app.services.stock_service import get_item_stock

    item_request = ItemRequest.query.get_or_404(request_id)

    if item_request.branch_id != current_user.branch_id:
        flash("Data permintaan barang tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.item_requests"))

    if item_request.status != "APPROVED":
        flash("Permintaan hanya bisa dipenuhi jika status sudah APPROVED.", "warning")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    fulfill_note = (request.form.get("fulfill_note") or "").strip()
    idempotency_key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex

    try:
        # 1. Cek stok semua item dulu sebelum ada perubahan data
        for detail in item_request.details:
            item = detail.item

            if not item:
                flash("Ada item permintaan yang tidak ditemukan.", "warning")
                return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

            approved_qty = float(getattr(detail, "approved_qty", 0) or 0)

            if approved_qty <= 0:
                approved_qty = float(getattr(detail, "requested_qty", 0) or getattr(detail, "qty", 0) or 0)

            current_stock = get_item_stock(current_user.branch_id, item.id)

            if approved_qty <= 0:
                flash(f"Qty disetujui untuk {item.item_name} belum valid.", "warning")
                return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

            if approved_qty > current_stock:
                flash(
                    f"Stok {item.item_name} tidak cukup. "
                    f"Diminta {approved_qty:g} {item.unit}, stok tersedia {current_stock:g} {item.unit}.",
                    "warning"
                )
                return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

        try:
            idempotency_record, reserved = reserve_idempotency_key(
                scope="LOGISTICS_ITEM_REQUEST_FULFILL",
                key=idempotency_key,
                branch_id=current_user.branch_id,
                user_id=current_user.id,
                request_payload={"request_id": item_request.id, "fulfill_note": fulfill_note},
            )
        except IdempotencyConflictError:
            flash("Submit fulfill berbeda memakai idempotency key yang sama. Muat ulang halaman lalu coba lagi.", "warning")
            return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

        if not reserved:
            flash("Submit fulfill permintaan ini sudah pernah diproses.", "info")
            return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

        fulfill_item_request_record(
            item_request,
            branch_id=current_user.branch_id,
            fulfilled_by=current_user.id,
            fulfill_note=fulfill_note,
        )
        mark_idempotency_completed(
            idempotency_record,
            reference_type="ITEM_REQUEST",
            reference_id=item_request.id,
            response_payload={"request_id": item_request.id, "status": item_request.status},
            commit=True,
        )

        record_audit_log(
            module="LOGISTICS",
            event_type="ITEM_REQUEST_FULFILLED",
            action="UPDATE",
            table_name="item_requests",
            record_id=item_request.id,
            description=f"Permintaan barang dipenuhi dan stok keluar: {item_request.request_number}.",
            metadata={"request_number": item_request.request_number, "fulfill_note": fulfill_note, "line_count": len(item_request.details)},
        )

        flash("Permintaan barang berhasil dipenuhi. Stok sudah berkurang.", "success")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/logistics_routes.py:1436")
        flash(f"Gagal memenuhi permintaan barang: {error}", "danger")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))



# === PATCH_KITCHEN_USAGE_HISTORY ===
@logistics_bp.route("/kitchen-usage")
@role_required("OWNER", "LOGISTICS", "DAPUR")
def kitchen_usage():
    from app.models.logistics import ItemRequest

    item_requests = ItemRequest.query.filter_by(
        branch_id=current_user.branch_id,
        status="FULFILLED"
    ).order_by(
        ItemRequest.request_date.desc(),
        ItemRequest.id.desc()
    ).all()

    usage_rows = []

    for item_request in item_requests:
        for detail in item_request.details:
            fulfilled_qty = float(getattr(detail, "fulfilled_qty", 0) or 0)

            if fulfilled_qty <= 0:
                continue

            item = detail.item

            usage_rows.append({
                "date": item_request.request_date,
                "request_number": item_request.request_number,
                "request_id": item_request.id,
                "purpose": item_request.purpose,
                "item_name": item.item_name if item else "-",
                "item_code": item.item_code if item else "-",
                "unit": item.unit if item else "",
                "fulfilled_qty": fulfilled_qty,
                "detail_notes": detail.notes or "-",
                "request_notes": item_request.notes or "-"
            })

    total_usage = len(usage_rows)
    unique_items = len(set(row["item_code"] for row in usage_rows))
    total_requests = len(item_requests)

    return render_template(
        "logistics/kitchen_usage.html",
        usage_rows=usage_rows,
        total_usage=total_usage,
        unique_items=unique_items,
        total_requests=total_requests
    )
