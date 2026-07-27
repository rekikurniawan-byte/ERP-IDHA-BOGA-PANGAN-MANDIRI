"""Logistics procurement and attachment routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.logistics_routes import *  # noqa: F401,F403
from app.routes.logistics_routes import _procurement_attachment_or_404, _procurement_or_404


@logistics_bp.route("/purchases")
@role_required("OWNER", "LOGISTICS")
def purchases():
    from app.models.logistics import Procurement
    from app.models.finance import CashBankTransaction, SupplierBill

    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    purchase_type_filter = (request.args.get("purchase_type") or "ALL").upper().strip()
    if purchase_type_filter not in ["ALL", "CASH", "CREDIT"]:
        purchase_type_filter = "ALL"

    purchases_query = Procurement.query.filter_by(branch_id=current_user.branch_id)
    purchases_query = apply_date_range_to_query(purchases_query, Procurement.procurement_date, date_filter)
    if purchase_type_filter != "ALL":
        purchases_query = purchases_query.filter(Procurement.purchase_type == purchase_type_filter)

    purchases = purchases_query.order_by(
        Procurement.procurement_date.desc(),
        Procurement.id.desc()
    ).all()

    procurement_ids = [purchase.id for purchase in purchases]
    ledger_by_procurement = {}
    supplier_bill_by_procurement = {}
    attachment_count_by_procurement = {}

    if procurement_ids:
        ledger_rows = CashBankTransaction.query.filter(
            CashBankTransaction.branch_id == current_user.branch_id,
            CashBankTransaction.reference_type == "PROCUREMENT",
            CashBankTransaction.reference_id.in_(procurement_ids)
        ).all()

        ledger_by_procurement = {row.reference_id: row for row in ledger_rows}

        supplier_bills = SupplierBill.query.filter(
            SupplierBill.branch_id == current_user.branch_id,
            SupplierBill.procurement_id.in_(procurement_ids)
        ).all()

        supplier_bill_by_procurement = {bill.procurement_id: bill for bill in supplier_bills}

        for procurement_id in procurement_ids:
            attachment_count_by_procurement[procurement_id] = count_reference_attachments(
                module=PROCUREMENT_ATTACHMENT_MODULE,
                reference_type=PROCUREMENT_ATTACHMENT_REFERENCE,
                reference_id=procurement_id,
                branch_id=current_user.branch_id,
            )

    return render_template(
        "logistics/purchase_index.html",
        purchases=purchases,
        ledger_by_procurement=ledger_by_procurement,
        supplier_bill_by_procurement=supplier_bill_by_procurement,
        attachment_count_by_procurement=attachment_count_by_procurement,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("logistics.purchases"),
            reset_url=url_for("logistics.purchases"),
            title="Filter Pembelian",
            description="Custom tanggal dan tipe pembelian cash/credit.",
            status_name="purchase_type",
            status_value=purchase_type_filter,
            status_options=[
                {"value": "ALL", "label": "Semua Tipe"},
                {"value": "CASH", "label": "Tunai"},
                {"value": "CREDIT", "label": "Hutang/Credit"},
            ],
        )
    )


@logistics_bp.route("/purchases/create", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def create_purchase():
    from app.extensions import db
    from app.models.logistics import Procurement, ProcurementItem, StockMovement
    from app.models.finance import BankAccount
    from app.services.stock_service import get_stock_items, is_integer_unit

    items = get_stock_items()
    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc()
    ).all()

    suppliers = Supplier.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(Supplier.supplier_name.asc()).all()

    selected_supplier_id = (request.args.get("supplier_id") or "").strip()
    if selected_supplier_id and not any(str(supplier.id) == selected_supplier_id for supplier in suppliers):
        selected_supplier_id = ""

    if request.method == "POST":
        procurement_date = datetime.strptime(request.form.get("procurement_date"), "%Y-%m-%d").date()
        supplier_id_raw = request.form.get("supplier_id") or ""
        selected_supplier = None

        if supplier_id_raw:
            try:
                supplier_id = int(supplier_id_raw)
            except ValueError:
                flash("Supplier tetap tidak valid.", "warning")
                return redirect(url_for("logistics.create_purchase"))

            selected_supplier = Supplier.query.filter_by(
                id=supplier_id,
                branch_id=current_user.branch_id,
                is_active=True
            ).first()

            if not selected_supplier:
                flash("Supplier tetap tidak ditemukan atau sudah nonaktif.", "warning")
                return redirect(url_for("logistics.create_purchase"))

        purchase_place_input = (request.form.get("purchase_place") or "").strip()
        purchase_place = purchase_place_input or (selected_supplier.supplier_name if selected_supplier else "Pembelian sendiri")
        supplier_name_snapshot = selected_supplier.supplier_name if selected_supplier else purchase_place
        purchase_type = (request.form.get("purchase_type") or "CASH").strip().upper()
        notes = (request.form.get("notes") or "").strip()

        if purchase_type not in ["CASH", "CREDIT"]:
            flash("Tipe pembelian tidak valid. Pilih CASH atau CREDIT.", "warning")
            return redirect(url_for("logistics.create_purchase"))

        supplier_bill_due_date = None

        if purchase_type == "CREDIT":
            due_date_raw = (request.form.get("supplier_bill_due_date") or "").strip()

            if due_date_raw:
                supplier_bill_due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date()
            else:
                default_terms_days = int(getattr(selected_supplier, "default_payment_terms_days", 0) or 0) if selected_supplier else 0
                supplier_bill_due_date = procurement_date + timedelta(days=max(default_terms_days, 0))

            if supplier_bill_due_date < procurement_date:
                flash("Jatuh tempo hutang supplier tidak boleh lebih awal dari tanggal pembelian.", "warning")
                return redirect(url_for("logistics.create_purchase"))

        payment_account_type = (request.form.get("payment_account_type") or "CASH").strip().upper()
        purchase_bank_account_id = None

        if purchase_type == "CASH":
            if payment_account_type not in ["CASH", "BANK"]:
                flash("Sumber pembayaran pembelian tunai harus Kas atau Bank.", "warning")
                return redirect(url_for("logistics.create_purchase"))

            if payment_account_type == "BANK":
                bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()

                if not bank_account_id_raw:
                    flash("Pembelian tunai dari bank wajib memilih rekening bank keluar.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                try:
                    purchase_bank_account_id = int(bank_account_id_raw)
                except (TypeError, ValueError):
                    flash("Rekening bank keluar tidak valid.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                bank_account = BankAccount.query.filter_by(
                    id=purchase_bank_account_id,
                    branch_id=current_user.branch_id,
                    is_active=True
                ).first()

                if not bank_account:
                    flash("Rekening bank keluar tidak ditemukan atau tidak aktif.", "warning")
                    return redirect(url_for("logistics.create_purchase"))
        else:
            payment_account_type = None
            purchase_bank_account_id = None

        item_ids = request.form.getlist("item_id[]")
        qtys = request.form.getlist("qty[]")
        unit_prices = request.form.getlist("unit_price[]")

        valid_rows = []

        try:
            for item_id, qty_raw, price_raw in zip(item_ids, qtys, unit_prices):
                if not item_id:
                    continue

                item = Item.query.get(int(item_id))

                if not item:
                    flash("Ada item yang tidak ditemukan.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                if not item.is_active:
                    flash(f"Item {item.item_name} tidak aktif.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                if not item.is_stock_tracked:
                    flash(f"Item {item.item_name} tidak dilacak stoknya.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                qty = float(qty_raw or 0)
                unit_price = float(price_raw or 0)

                if qty <= 0:
                    flash(f"Qty untuk {item.item_name} wajib lebih dari 0.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                if is_integer_unit(item.unit) and not qty.is_integer():
                    flash(f"Untuk satuan {item.unit}, qty {item.item_name} harus angka bulat.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                if unit_price <= 0:
                    flash(f"Harga satuan untuk {item.item_name} wajib lebih dari 0.", "warning")
                    return redirect(url_for("logistics.create_purchase"))

                subtotal = round(qty * unit_price, 2)

                valid_rows.append({
                    "item": item,
                    "qty": qty,
                    "unit_price": unit_price,
                    "subtotal": subtotal
                })

            if not valid_rows:
                flash("Minimal isi 1 item pembelian.", "warning")
                return redirect(url_for("logistics.create_purchase"))

            total_amount = round(sum(row["subtotal"] for row in valid_rows), 2)

            same_day_count = Procurement.query.filter_by(
                branch_id=current_user.branch_id,
                procurement_date=procurement_date
            ).count()

            procurement_number = f"PB-{procurement_date.strftime('%Y%m%d')}-{same_day_count + 1:03d}"

            procurement = Procurement(
                procurement_number=procurement_number,
                branch_id=current_user.branch_id,
                procurement_date=procurement_date,
                purchase_type=purchase_type,
                supplier_id=selected_supplier.id if selected_supplier else None,
                supplier_name=supplier_name_snapshot,
                purchase_place=purchase_place,
                total_amount=total_amount,
                notes=notes,
                created_by=current_user.id
            )

            proof_file = request.files.get("proof_file")
            proof_uploaded = False

            with atomic_business_action(
                module="LOGISTICS",
                action="PROCUREMENT_CREATE",
                description=f"Create pembelian {procurement_number} + stok + AP/ledger + nota secara atomic.",
                reference_type="procurements",
                user_id=current_user.id,
                branch_id=current_user.branch_id,
                metadata={"procurement_number": procurement_number, "purchase_type": purchase_type, "item_count": len(valid_rows), "total_amount": total_amount},
            ) as atomic:
                db.session.add(procurement)
                db.session.flush()

                for row in valid_rows:
                    procurement_item = ProcurementItem(
                        procurement_id=procurement.id,
                        item_id=row["item"].id,
                        qty=row["qty"],
                        unit_price=row["unit_price"],
                        subtotal=row["subtotal"]
                    )

                    db.session.add(procurement_item)

                    type_label = "Tunai" if purchase_type == "CASH" else "Hutang"
                    movement_notes = f"Pembelian {type_label} | Tempat belanja: {purchase_place}"

                    if selected_supplier:
                        movement_notes += f" | Supplier tetap: {selected_supplier.supplier_name}"

                    if notes:
                        movement_notes += f" | {notes}"

                    validate_stock_movement_guard(
                        "IN",
                        row["qty"],
                        item_unit=row["item"].unit,
                        is_integer_unit=is_integer_unit(row["item"].unit),
                    )

                    stock_movement = StockMovement(
                        branch_id=current_user.branch_id,
                        item_id=row["item"].id,
                        movement_date=procurement_date,
                        movement_type="IN",
                        reference_type="PEMBELIAN_BARANG",
                        reference_id=procurement.id,
                        qty=row["qty"],
                        notes=movement_notes,
                        created_by=current_user.id
                    )

                    db.session.add(stock_movement)

                supplier_bill = None

                if purchase_type == "CASH":
                    # PRODUCTION_CASH_BANK_LEDGER_PROCUREMENT_OUT
                    from app.services.cash_bank_service import create_procurement_cash_bank_transaction

                    create_procurement_cash_bank_transaction(
                        procurement=procurement,
                        created_by=current_user.id,
                        account_type=payment_account_type,
                        bank_account_id=purchase_bank_account_id,
                        commit=False
                    )
                else:
                    # PRODUCTION_SUPPLIER_BILL_AP_CREATE
                    from app.services.accounts_payable_service import create_supplier_bill_for_procurement

                    _, _, supplier_bill = create_supplier_bill_for_procurement(
                        procurement=procurement,
                        created_by=current_user.id,
                        due_date=supplier_bill_due_date,
                        commit=False
                    )

                db.session.flush()

                if proof_file and proof_file.filename:
                    attachment = save_digital_attachment(
                        file_storage=proof_file,
                        module=PROCUREMENT_ATTACHMENT_MODULE,
                        reference_type=PROCUREMENT_ATTACHMENT_REFERENCE,
                        reference_id=procurement.id,
                        attachment_type=request.form.get("proof_type") or "NOTA_PEMBELIAN",
                        branch_id=current_user.branch_id,
                        uploaded_by=current_user.id,
                        notes=request.form.get("proof_notes") or None,
                        commit=False,
                    )
                    atomic.track_attachment(attachment)
                    proof_uploaded = True
                    record_audit_log(
                        module="ATTACHMENT",
                        event_type="DIGITAL_ATTACHMENT_UPLOADED",
                        action="CREATE",
                        table_name="digital_attachments",
                        record_id=attachment.id,
                        description=f"Nota/struk pembelian diunggah secara atomic untuk {procurement.procurement_number}.",
                        metadata={
                            "module": PROCUREMENT_ATTACHMENT_MODULE,
                            "reference_type": PROCUREMENT_ATTACHMENT_REFERENCE,
                            "reference_id": procurement.id,
                            "attachment_type": attachment.attachment_type,
                            "original_filename": attachment.original_filename,
                            "file_size": attachment.file_size,
                            "sha256": attachment.sha256_hash,
                            "atomic_guard": "PRODUCTION",
                        },
                        commit=False,
                    )

            record_audit_log(
                module="LOGISTICS",
                event_type="PROCUREMENT_CREATED",
                action="CREATE",
                table_name="procurements",
                record_id=procurement.id,
                description=f"Pembelian barang dicatat atomic: {procurement.procurement_number} ({purchase_type}).",
                metadata={
                    "procurement_number": procurement.procurement_number,
                    "purchase_type": purchase_type,
                    "supplier_id": procurement.supplier_id,
                    "supplier_name": procurement.supplier_name,
                    "purchase_place": procurement.purchase_place,
                    "total_amount": procurement.total_amount,
                    "item_count": len(valid_rows),
                    "atomic_guard": "PRODUCTION",
                },
            )

            if supplier_bill:
                record_audit_log(
                    module="FINANCE",
                    event_type="SUPPLIER_BILL_CREATED",
                    action="CREATE",
                    table_name="supplier_bills",
                    record_id=supplier_bill.id,
                    description=f"Supplier bill otomatis dibuat atomic dari pembelian: {supplier_bill.bill_number}.",
                    metadata={
                        "procurement_id": procurement.id,
                        "procurement_number": procurement.procurement_number,
                        "bill_number": supplier_bill.bill_number,
                        "supplier_name": supplier_bill.supplier_name,
                        "total_amount": supplier_bill.total_amount,
                        "due_date": supplier_bill.due_date,
                        "atomic_guard": "PRODUCTION",
                    },
                )

            if proof_uploaded:
                flash("Nota/struk pembelian berhasil diunggah dalam transaksi atomic.", "success")

            if purchase_type == "CASH":
                flash("Pembelian tunai berhasil disimpan, stok bertambah, dan ledger kas/bank keluar dibuat.", "success")
            else:
                bill_number = supplier_bill.bill_number if supplier_bill else "supplier bill"
                flash(f"Pembelian hutang berhasil disimpan, stok bertambah, dan {bill_number} otomatis masuk Hutang Supplier/AP.", "success")
            return redirect(url_for("logistics.purchase_detail", procurement_id=procurement.id))

        except Exception as error:
            logger.exception("Suppressed unexpected exception in app/routes/logistics_routes.py:723")
            flash(f"Gagal menyimpan pembelian: {error}", "danger")
            return redirect(url_for("logistics.create_purchase"))

    return render_template(
        "logistics/purchase_form.html",
        items=items,
        suppliers=suppliers,
        active_bank_accounts=active_bank_accounts,
        selected_supplier_id=selected_supplier_id,
        today=date.today(),
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
    )

@logistics_bp.route("/purchases/<int:procurement_id>")
@role_required("OWNER", "LOGISTICS")
def purchase_detail(procurement_id):
    from app.models.logistics import Procurement, StockMovement
    from app.models.finance import CashBankTransaction, SupplierBill

    procurement = Procurement.query.get_or_404(procurement_id)

    if procurement.branch_id != current_user.branch_id:
        flash("Data pembelian tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.purchases"))

    stock_movements = StockMovement.query.filter_by(
        branch_id=current_user.branch_id,
        reference_type="PEMBELIAN_BARANG",
        reference_id=procurement.id
    ).all()

    ledger_transaction = CashBankTransaction.query.filter_by(
        branch_id=current_user.branch_id,
        reference_type="PROCUREMENT",
        reference_id=procurement.id
    ).first()

    supplier_bill = SupplierBill.query.filter_by(
        branch_id=current_user.branch_id,
        procurement_id=procurement.id
    ).first()

    from app.services.accounting_posting_status_service import build_single_source_posting_status
    posting_status = build_single_source_posting_status("PROCUREMENT", procurement)

    return render_template(
        "logistics/purchase_detail.html",
        procurement=procurement,
        stock_movements=stock_movements,
        ledger_transaction=ledger_transaction,
        supplier_bill=supplier_bill,
        posting_status=posting_status,
        procurement_attachments=list_reference_attachments(
            module=PROCUREMENT_ATTACHMENT_MODULE,
            reference_type=PROCUREMENT_ATTACHMENT_REFERENCE,
            reference_id=procurement.id,
            branch_id=current_user.branch_id,
        ),
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


@logistics_bp.route("/purchases/<int:procurement_id>/attachments/upload", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def upload_procurement_attachment(procurement_id):
    procurement = _procurement_or_404(procurement_id)

    proof_file = request.files.get("proof_file")
    try:
        save_digital_attachment(
            file_storage=proof_file,
            module=PROCUREMENT_ATTACHMENT_MODULE,
            reference_type=PROCUREMENT_ATTACHMENT_REFERENCE,
            reference_id=procurement.id,
            attachment_type=request.form.get("proof_type") or "NOTA_PEMBELIAN",
            branch_id=current_user.branch_id,
            uploaded_by=current_user.id,
            notes=request.form.get("proof_notes") or None,
        )
        flash("Nota/struk pembelian berhasil diunggah.", "success")
    except AttachmentValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/logistics_routes.py:809")
        flash(f"Nota/struk pembelian gagal diunggah: {exc}", "danger")

    return redirect(url_for("logistics.purchase_detail", procurement_id=procurement.id))


@logistics_bp.route("/purchases/attachments/<int:attachment_id>/view")
@role_required("OWNER", "LOGISTICS")
def view_procurement_attachment(attachment_id):
    attachment, procurement = _procurement_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/logistics_routes.py:822")
        flash(f"File nota/struk tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("logistics.purchase_detail", procurement_id=procurement.id))

    return send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@logistics_bp.route("/purchases/attachments/<int:attachment_id>/download")
@role_required("OWNER", "LOGISTICS")
def download_procurement_attachment(attachment_id):
    attachment, procurement = _procurement_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/logistics_routes.py:841")
        flash(f"File nota/struk tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("logistics.purchase_detail", procurement_id=procurement.id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@logistics_bp.route("/purchases/attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def delete_procurement_attachment(attachment_id):
    attachment, procurement = _procurement_attachment_or_404(attachment_id)
    note = (request.form.get("delete_note") or "Nota/struk pembelian salah upload.").strip()
    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    flash("Nota/struk pembelian berhasil dihapus lunak. File fisik tetap tersimpan untuk audit.", "success")
    return redirect(url_for("logistics.purchase_detail", procurement_id=procurement.id))
