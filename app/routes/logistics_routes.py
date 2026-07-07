from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file
from flask_login import current_user

from app.models.master import Item, Supplier
from app.services.stock_service import (
    get_stock_items,
    get_stock_summary,
    get_recent_movements,
    get_item_stock,
    get_item_movements,
    create_stock_movement,
)
from app.utils.decorators import role_required
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context, apply_date_range_to_query
from app.services.audit_log_service import record_audit_log
from app.services.atomic_transaction_service import atomic_business_action
from app.services.business_logic_guard_service import validate_stock_movement_guard
from app.services.material_forecast_service import build_material_requirement_forecast
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    format_file_size,
    get_allowed_extensions,
    get_attachment_file_path,
    get_attachment_or_none,
    get_max_upload_bytes,
    list_reference_attachments,
    count_reference_attachments,
    save_digital_attachment,
    soft_delete_attachment,
)


logistics_bp = Blueprint("logistics", __name__, url_prefix="/logistics")


PROCUREMENT_ATTACHMENT_MODULE = "PROCUREMENT"
PROCUREMENT_ATTACHMENT_REFERENCE = "PROCUREMENT"


def _procurement_or_404(procurement_id):
    from app.models.logistics import Procurement

    procurement = Procurement.query.get_or_404(procurement_id)
    if procurement.branch_id != current_user.branch_id:
        abort(404)
    return procurement


def _procurement_attachment_or_404(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if not attachment or attachment.module != PROCUREMENT_ATTACHMENT_MODULE or attachment.reference_type != PROCUREMENT_ATTACHMENT_REFERENCE:
        abort(404)

    procurement = _procurement_or_404(attachment.reference_id)
    return attachment, procurement


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



# === PATCH_PROCUREMENT_ROUTES ===
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
            db.session.rollback()
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
        flash(f"Nota/struk pembelian gagal diunggah: {exc}", "danger")

    return redirect(url_for("logistics.purchase_detail", procurement_id=procurement.id))


@logistics_bp.route("/purchases/attachments/<int:attachment_id>/view")
@role_required("OWNER", "LOGISTICS")
def view_procurement_attachment(attachment_id):
    attachment, procurement = _procurement_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
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



# === PATCH_DAMAGED_ITEM_ROUTES ===
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
    from app.extensions import db
    from app.models.logistics import StockMovement
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

        system_stock = get_item_stock(current_user.branch_id, item.id)
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

        movement = StockMovement(
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

        db.session.add(movement)
        db.session.commit()

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



# === PATCH_ITEM_REQUEST_ROUTES ===
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
    from app.extensions import db
    from app.models.logistics import ItemRequest, ItemRequestDetail
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

            item_request = ItemRequest(
                request_number=request_number,
                branch_id=current_user.branch_id,
                request_date=request_date,
                requested_by=current_user.id,
                status="PENDING",
                purpose=purpose,
                notes=notes
            )

            db.session.add(item_request)
            db.session.flush()

            for row in valid_rows:
                detail = ItemRequestDetail(
                    item_request_id=item_request.id,
                    item_id=row["item"].id,

                    # Kompatibel dengan struktur lama blueprint
                    qty=row["requested_qty"],
                    unit=row["item"].unit,

                    # Kolom baru untuk alur approval/fulfillment
                    requested_qty=row["requested_qty"],
                    approved_qty=0,
                    fulfilled_qty=0,
                    notes=row["notes"]
                )

                db.session.add(detail)

            db.session.commit()

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
            db.session.rollback()
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
    from app.services.stock_service import get_item_stock, is_integer_unit

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
        stock_map=stock_map
    )



# === PATCH_ITEM_REQUEST_APPROVE_REJECT ===
@logistics_bp.route("/item-requests/<int:request_id>/approve", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def approve_item_request(request_id):
    from app.extensions import db
    from app.models.logistics import ItemRequest

    item_request = ItemRequest.query.get_or_404(request_id)

    if item_request.branch_id != current_user.branch_id:
        flash("Data permintaan barang tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.item_requests"))

    if item_request.status != "PENDING":
        flash("Permintaan hanya bisa disetujui jika status masih PENDING.", "warning")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    owner_note = (request.form.get("owner_note") or "").strip()

    for detail in item_request.details:
        requested_qty = float(getattr(detail, "requested_qty", 0) or getattr(detail, "qty", 0) or 0)
        detail.approved_qty = requested_qty

    item_request.status = "APPROVED"

    if owner_note:
        old_notes = item_request.notes or ""
        item_request.notes = (old_notes + f" | Catatan owner: {owner_note}").strip(" |")

    db.session.commit()

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
    from app.extensions import db
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

    for detail in item_request.details:
        detail.approved_qty = 0
        detail.fulfilled_qty = 0

    old_notes = item_request.notes or ""
    item_request.notes = (old_notes + f" | Alasan ditolak: {reject_reason}").strip(" |")
    item_request.status = "REJECTED"

    db.session.commit()

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
    from app.extensions import db
    from app.models.logistics import ItemRequest, StockMovement
    from app.services.stock_service import get_item_stock, get_item_stock_for_update, is_integer_unit

    item_request = ItemRequest.query.get_or_404(request_id)

    if item_request.branch_id != current_user.branch_id:
        flash("Data permintaan barang tidak sesuai cabang user.", "danger")
        return redirect(url_for("logistics.item_requests"))

    if item_request.status != "APPROVED":
        flash("Permintaan hanya bisa dipenuhi jika status sudah APPROVED.", "warning")
        return redirect(url_for("logistics.item_request_detail", request_id=item_request.id))

    fulfill_note = (request.form.get("fulfill_note") or "").strip()

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

        # 2. Kalau semua stok cukup, baru buat movement OUT
        for detail in item_request.details:
            item = detail.item
            approved_qty = float(getattr(detail, "approved_qty", 0) or 0)

            if approved_qty <= 0:
                approved_qty = float(getattr(detail, "requested_qty", 0) or getattr(detail, "qty", 0) or 0)

            notes = (
                f"Pemenuhan permintaan dapur {item_request.request_number} | "
                f"Tujuan: {item_request.purpose}"
            )

            if fulfill_note:
                notes += f" | Catatan owner: {fulfill_note}"

            current_stock = get_item_stock_for_update(current_user.branch_id, item.id)
            validate_stock_movement_guard(
                "OUT",
                approved_qty,
                current_stock=current_stock,
                item_unit=item.unit,
                is_integer_unit=is_integer_unit(item.unit),
            )

            movement = StockMovement(
                branch_id=current_user.branch_id,
                item_id=item.id,
                movement_date=item_request.request_date,
                movement_type="OUT",
                reference_type="PERMINTAAN_BARANG_DAPUR",
                reference_id=item_request.id,
                qty=approved_qty,
                notes=notes,
                created_by=current_user.id
            )

            db.session.add(movement)

            detail.fulfilled_qty = approved_qty

        old_notes = item_request.notes or ""

        if fulfill_note:
            item_request.notes = (old_notes + f" | Catatan pemenuhan: {fulfill_note}").strip(" |")

        item_request.status = "FULFILLED"

        db.session.commit()

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
        db.session.rollback()
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

