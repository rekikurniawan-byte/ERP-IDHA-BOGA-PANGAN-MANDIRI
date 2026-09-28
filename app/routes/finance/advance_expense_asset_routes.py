"""Advance, expense, and fixed asset routes.

Route functions moved out of app.routes.finance_routes without changing URL rules or endpoint names.
"""
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance.payment_routes import _parse_payment_amount


@finance_bp.route("/advances")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def advances():
    from app.models.finance import AdvanceTransaction
    from app.services.advance_service import (
        ADVANCE_TYPES,
        get_advance_status_summary,
        get_party_label,
        is_advance_schema_ready,
    )

    schema_ready = is_advance_schema_ready()
    selected_type = (request.args.get("type") or "ALL").strip().upper()
    selected_status = (request.args.get("status") or "ALL").strip().upper()

    rows = []
    summary = {"total": 0, "open": 0, "settled": 0, "remaining": 0}

    if schema_ready:
        query = AdvanceTransaction.query.filter_by(branch_id=current_user.branch_id)
        if selected_type != "ALL":
            query = query.filter(AdvanceTransaction.advance_type == selected_type)
        if selected_status != "ALL":
            query = query.filter(AdvanceTransaction.status == selected_status)
        rows = query.order_by(AdvanceTransaction.advance_date.desc(), AdvanceTransaction.id.desc()).all()
        summary = get_advance_status_summary(current_user.branch_id)
    else:
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION sebelum memakai fitur ini.", "warning")

    return render_template(
        "finance/advances.html",
        advances=rows,
        summary=summary,
        advance_types=ADVANCE_TYPES,
        selected_type=selected_type,
        selected_status=selected_status,
        get_party_label=get_party_label,
        schema_ready=schema_ready,
    )


@finance_bp.route("/advances/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def advance_create():
    from datetime import datetime, date
    from app.models.finance import BankAccount
    from app.models.master import Client, Mandor, Supplier
    from app.services.advance_service import create_advance_transaction_record, get_advance_type_choices, is_advance_schema_ready

    schema_ready = is_advance_schema_ready()
    if not schema_ready:
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.advances"))

    if request.method == "POST":
        advance_date_raw = (request.form.get("advance_date") or "").strip()
        advance_type = (request.form.get("advance_type") or "").strip().upper()
        payment_method = (request.form.get("payment_method") or "").strip().upper()
        bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
        amount_raw = (request.form.get("amount") or "").strip()
        client_id_raw = (request.form.get("client_id") or "").strip()
        supplier_id_raw = (request.form.get("supplier_id") or "").strip()
        mandor_id_raw = (request.form.get("mandor_id") or "").strip()
        reference_number = (request.form.get("reference_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            advance_date = datetime.strptime(advance_date_raw, "%Y-%m-%d").date()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6117")
            flash("Tanggal DP/uang muka tidak valid.", "warning")
            return redirect(url_for("finance.advance_create"))

        try:
            amount = _parse_payment_amount(amount_raw)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6123")
            flash("Nominal DP/uang muka tidak valid.", "warning")
            return redirect(url_for("finance.advance_create"))

        def _to_int(value):
            try:
                return int(value) if value else None
            except Exception:
                logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6130")
                return None

        try:
            ok, message, advance = create_advance_transaction_record(
                branch_id=current_user.branch_id,
                advance_date=advance_date,
                advance_type=advance_type,
                payment_method=payment_method,
                amount=amount,
                created_by=current_user.id,
                client_id=_to_int(client_id_raw),
                supplier_id=_to_int(supplier_id_raw),
                mandor_id=_to_int(mandor_id_raw),
                bank_account_id=_to_int(bank_account_id_raw),
                reference_number=reference_number,
                notes=notes,
            )
            flash(message, "success")
            return redirect(url_for("finance.advance_detail", advance_id=advance.id))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6150")
            flash(str(exc), "danger")
            return redirect(url_for("finance.advance_create"))

    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    suppliers = Supplier.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all()
    mandors = Mandor.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Mandor.name.asc()).all()
    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    return render_template(
        "finance/advance_form.html",
        today_date=date.today().isoformat(),
        advance_type_choices=get_advance_type_choices(),
        clients=clients,
        suppliers=suppliers,
        mandors=mandors,
        bank_accounts=bank_accounts,
    )


@finance_bp.route("/advances/<int:advance_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def advance_detail(advance_id):
    from datetime import date
    from app.models.finance import AdvanceTransaction, AdvanceSettlement
    from app.services.advance_service import (
        ADVANCE_TYPES,
        SETTLEMENT_TYPES,
        get_party_label,
        get_mandor_expense_proof_choices,
        get_settlement_reference_options,
        is_advance_schema_ready,
    )
    from app.services.field_transaction_service import find_field_transaction_linked_source

    if not is_advance_schema_ready():
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.advances"))

    advance = AdvanceTransaction.query.get_or_404(advance_id)
    if advance.branch_id != current_user.branch_id:
        abort(404)

    settlements = AdvanceSettlement.query.filter_by(
        branch_id=current_user.branch_id,
        advance_id=advance.id,
    ).order_by(AdvanceSettlement.settlement_date.desc(), AdvanceSettlement.id.desc()).all()
    reference_options = get_settlement_reference_options(current_user.branch_id, advance)
    field_transaction_link = find_field_transaction_linked_source(
        "ADVANCE_TRANSACTION",
        advance.id,
        branch_id=current_user.branch_id,
    )
    settlement_field_transaction_links = {
        settlement.id: find_field_transaction_linked_source(
            "ADVANCE_SETTLEMENT",
            settlement.id,
            branch_id=current_user.branch_id,
        )
        for settlement in settlements
    }

    from app.models.finance import BankAccount

    return render_template(
        "finance/advance_detail.html",
        bank_accounts=BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True)
        .order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc())
        .all(),
        advance=advance,
        settlements=settlements,
        rule=ADVANCE_TYPES.get(advance.advance_type, {}),
        settlement_types=SETTLEMENT_TYPES,
        get_party_label=get_party_label,
        mandor_expense_proof_choices=get_mandor_expense_proof_choices(),
        today_date=date.today().isoformat(),
        reference_options=reference_options,
        field_transaction_link=field_transaction_link,
        settlement_field_transaction_links=settlement_field_transaction_links,
    )


@finance_bp.route("/advances/<int:advance_id>/settle", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def advance_settle(advance_id):
    from datetime import datetime
    from app.models.finance import AdvanceTransaction
    from app.services.advance_service import create_advance_settlement_record, is_advance_schema_ready

    if not is_advance_schema_ready():
        flash("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.advances"))

    advance = AdvanceTransaction.query.get_or_404(advance_id)
    if advance.branch_id != current_user.branch_id:
        abort(404)

    settlement_date_raw = (request.form.get("settlement_date") or "").strip()
    settlement_type = (request.form.get("settlement_type") or "").strip().upper()
    reference_id_raw = (request.form.get("reference_id") or "").strip()
    expense_account_code = (request.form.get("expense_account_code") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    try:
        settlement_date = datetime.strptime(settlement_date_raw, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6251")
        flash("Tanggal settlement DP tidak valid.", "warning")
        return redirect(url_for("finance.advance_detail", advance_id=advance.id))

    try:
        amount = _parse_payment_amount(amount_raw)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6257")
        flash("Nominal settlement DP tidak valid.", "warning")
        return redirect(url_for("finance.advance_detail", advance_id=advance.id))

    try:
        reference_id = int(reference_id_raw) if reference_id_raw else None
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6263")
        reference_id = None

    try:
        ok, message, settlement = create_advance_settlement_record(
            advance=advance,
            settlement_date=settlement_date,
            settlement_type=settlement_type,
            amount=amount,
            created_by=current_user.id,
            reference_id=reference_id,
            expense_account_code=expense_account_code,
            notes=notes,
            # Dipakai pengembalian (uang keluar dari kas/bank).
            payment_method=(request.form.get("payment_method") or "").strip().upper() or None,
            bank_account_id=request.form.get("bank_account_id", type=int),
        )
        flash(message, "success")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6278")
        flash(str(exc), "danger")

    return redirect(url_for("finance.advance_detail", advance_id=advance.id))



# === PRODUCTION_TRANSPORT_VEHICLE_FUEL_EXPENSE_COA_MAPPING_ROUTES ===
@finance_bp.route("/transport-expenses")
@role_required("OWNER", "ADMIN", "FINANCE")
def transport_expenses():
    from app.models.finance import TransportVehicleExpense
    from app.services.transport_expense_service import (
        TRANSPORT_EXPENSE_TYPES,
        get_driver_label,
        get_delivery_label,
        get_transport_expense_status_summary,
        is_transport_expense_schema_ready,
    )

    schema_ready = is_transport_expense_schema_ready()
    selected_type = (request.args.get("type") or "ALL").strip().upper()
    selected_account = (request.args.get("account") or "ALL").strip().upper()
    rows = []
    summary = get_transport_expense_status_summary(current_user.branch_id)
    if schema_ready:
        query = TransportVehicleExpense.query.filter_by(branch_id=current_user.branch_id)
        if selected_type != "ALL":
            query = query.filter(TransportVehicleExpense.expense_type == selected_type)
        if selected_account != "ALL":
            query = query.filter(TransportVehicleExpense.account_type == selected_account)
        rows = query.order_by(TransportVehicleExpense.expense_date.desc(), TransportVehicleExpense.id.desc()).all()

    return render_template(
        "finance/transport_expenses.html",
        expenses=rows,
        summary=summary,
        expense_types=TRANSPORT_EXPENSE_TYPES,
        selected_type=selected_type,
        selected_account=selected_account,
        schema_ready=schema_ready,
        get_driver_label=get_driver_label,
        get_delivery_label=get_delivery_label,
    )


@finance_bp.route("/transport-expenses/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def transport_expense_create():
    from datetime import date, datetime
    from app.models.delivery import Delivery
    from app.models.finance import BankAccount
    from app.models.master import Driver
    from app.services.transport_expense_service import create_transport_vehicle_expense_record, get_transport_expense_type_choices, is_transport_expense_schema_ready

    if not is_transport_expense_schema_ready():
        flash("Tabel transport/BBM belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.transport_expenses"))

    if request.method == "POST":
        try:
            expense_date = datetime.strptime((request.form.get("expense_date") or "").strip(), "%Y-%m-%d").date()
            amount = _parse_payment_amount((request.form.get("amount") or "").strip())
            ok, message, expense = create_transport_vehicle_expense_record(
                branch_id=current_user.branch_id,
                expense_date=expense_date,
                expense_type=(request.form.get("expense_type") or "").strip().upper(),
                payment_method=(request.form.get("payment_method") or "").strip().upper(),
                amount=amount,
                created_by=current_user.id,
                vehicle_label=(request.form.get("vehicle_label") or "").strip(),
                driver_id=(request.form.get("driver_id") or "").strip() or None,
                delivery_id=(request.form.get("delivery_id") or "").strip() or None,
                bank_account_id=(request.form.get("bank_account_id") or "").strip() or None,
                vendor_name=(request.form.get("vendor_name") or "").strip(),
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
            )
            flash(message, "success")
            return redirect(url_for("finance.transport_expense_detail", expense_id=expense.id))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6358")
            flash(str(exc), "danger")
            return redirect(url_for("finance.transport_expense_create"))

    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    drivers = Driver.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Driver.name.asc()).all()
    deliveries = Delivery.query.filter_by(branch_id=current_user.branch_id).order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(100).all()
    return render_template(
        "finance/transport_expense_form.html",
        today_date=date.today().isoformat(),
        expense_type_choices=get_transport_expense_type_choices(),
        bank_accounts=bank_accounts,
        drivers=drivers,
        deliveries=deliveries,
    )


@finance_bp.route("/transport-expenses/<int:expense_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def transport_expense_detail(expense_id):
    from app.models.finance import TransportVehicleExpense
    from app.services.transport_expense_service import TRANSPORT_EXPENSE_TYPES, get_driver_label, get_delivery_label, is_transport_expense_schema_ready
    from app.services.field_transaction_service import find_field_transaction_linked_source

    if not is_transport_expense_schema_ready():
        flash("Tabel transport/BBM belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.transport_expenses"))
    expense = TransportVehicleExpense.query.get_or_404(expense_id)
    if expense.branch_id != current_user.branch_id:
        abort(404)
    field_transaction_link = find_field_transaction_linked_source(
        "TRANSPORT_VEHICLE_EXPENSE",
        expense.id,
        branch_id=current_user.branch_id,
    )
    return render_template(
        "finance/transport_expense_detail.html",
        expense=expense,
        rule=TRANSPORT_EXPENSE_TYPES.get(expense.expense_type, {}),
        get_driver_label=get_driver_label,
        get_delivery_label=get_delivery_label,
        field_transaction_link=field_transaction_link,
    )


# === PRODUCTION_OPERATIONAL_EXPENSE_COA_MAPPING_ROUTES ===
@finance_bp.route("/operational-expenses")
@role_required("OWNER", "ADMIN", "FINANCE")
def operational_expenses():
    from app.models.finance import OperationalExpense
    from app.services.operational_expense_service import (
        OPERATIONAL_EXPENSE_CATEGORIES,
        get_operational_expense_status_summary,
        get_supplier_label,
        is_operational_expense_schema_ready,
    )

    schema_ready = is_operational_expense_schema_ready()
    selected_category = (request.args.get("category") or "ALL").strip().upper()
    selected_account = (request.args.get("account") or "ALL").strip().upper()
    rows = []
    summary = get_operational_expense_status_summary(current_user.branch_id)
    if schema_ready:
        query = OperationalExpense.query.filter_by(branch_id=current_user.branch_id)
        if selected_category != "ALL":
            query = query.filter(OperationalExpense.expense_category == selected_category)
        if selected_account != "ALL":
            query = query.filter(OperationalExpense.account_type == selected_account)
        rows = query.order_by(OperationalExpense.expense_date.desc(), OperationalExpense.id.desc()).all()

    return render_template(
        "finance/operational_expenses.html",
        expenses=rows,
        summary=summary,
        expense_categories=OPERATIONAL_EXPENSE_CATEGORIES,
        selected_category=selected_category,
        selected_account=selected_account,
        schema_ready=schema_ready,
        get_supplier_label=get_supplier_label,
    )


@finance_bp.route("/operational-expenses/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def operational_expense_create():
    from datetime import date, datetime
    from app.models.finance import BankAccount
    from app.models.master import Supplier
    from app.services.operational_expense_service import create_operational_expense_record, get_operational_expense_category_choices, is_operational_expense_schema_ready

    if not is_operational_expense_schema_ready():
        flash("Tabel biaya operasional belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.operational_expenses"))

    if request.method == "POST":
        try:
            expense_date = datetime.strptime((request.form.get("expense_date") or "").strip(), "%Y-%m-%d").date()
            amount = _parse_payment_amount((request.form.get("amount") or "").strip())
            ok, message, expense = create_operational_expense_record(
                branch_id=current_user.branch_id,
                expense_date=expense_date,
                expense_category=(request.form.get("expense_category") or "").strip().upper(),
                payment_method=(request.form.get("payment_method") or "").strip().upper(),
                amount=amount,
                created_by=current_user.id,
                bank_account_id=(request.form.get("bank_account_id") or "").strip() or None,
                supplier_id=(request.form.get("supplier_id") or "").strip() or None,
                vendor_name=(request.form.get("vendor_name") or "").strip(),
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
            )
            flash(message, "success")
            return redirect(url_for("finance.operational_expense_detail", expense_id=expense.id))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6471")
            flash(str(exc), "danger")
            return redirect(url_for("finance.operational_expense_create"))

    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    suppliers = Supplier.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all()
    return render_template(
        "finance/operational_expense_form.html",
        today_date=date.today().isoformat(),
        expense_category_choices=get_operational_expense_category_choices(),
        bank_accounts=bank_accounts,
        suppliers=suppliers,
    )


@finance_bp.route("/operational-expenses/<int:expense_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def operational_expense_detail(expense_id):
    from app.models.finance import OperationalExpense
    from app.services.operational_expense_service import OPERATIONAL_EXPENSE_CATEGORIES, get_supplier_label, is_operational_expense_schema_ready
    from app.services.field_transaction_service import find_field_transaction_linked_source

    if not is_operational_expense_schema_ready():
        flash("Tabel biaya operasional belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.operational_expenses"))
    expense = OperationalExpense.query.get_or_404(expense_id)
    if expense.branch_id != current_user.branch_id:
        abort(404)
    field_transaction_link = find_field_transaction_linked_source(
        "OPERATIONAL_EXPENSE",
        expense.id,
        branch_id=current_user.branch_id,
    )
    return render_template(
        "finance/operational_expense_detail.html",
        expense=expense,
        rule=OPERATIONAL_EXPENSE_CATEGORIES.get(expense.expense_category, {}),
        get_supplier_label=get_supplier_label,
        field_transaction_link=field_transaction_link,
    )




# === PRODUCTION_OPTIONAL_FIXED_ASSET_DEPRECIATION_ENGINE_ROUTES ===
@finance_bp.route("/fixed-asset-depreciation")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_depreciation():
    from app.services.fixed_asset_depreciation_service import (
        get_asset_depreciation_rows,
        get_depreciation_summary,
        is_depreciation_schema_ready,
    )

    schema_ready = is_depreciation_schema_ready()
    status = (request.args.get("status") or "ALL").strip().upper()
    rows = []
    summary = get_depreciation_summary(current_user.branch_id)
    if schema_ready:
        rows = get_asset_depreciation_rows(current_user.branch_id, status=status)

    return render_template(
        "finance/fixed_asset_depreciation.html",
        schema_ready=schema_ready,
        rows=rows,
        summary=summary,
        status=status,
    )


@finance_bp.route("/fixed-asset-depreciation/<int:asset_id>/configure", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_depreciation_configure(asset_id):
    from datetime import datetime
    from app.models.accounting import FixedAsset
    from app.services.fixed_asset_depreciation_service import (
        DEPRECIATION_STATUS_OPTIONS,
        configure_asset_depreciation_record,
        get_accumulated_account_options,
        is_depreciation_schema_ready,
        preview_asset_depreciation,
        resolve_default_accumulated_account_code,
    )

    if not is_depreciation_schema_ready():
        flash("Tabel penyusutan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_depreciation"))

    asset = FixedAsset.query.filter_by(id=asset_id, branch_id=current_user.branch_id).first_or_404()
    config = getattr(asset, "depreciation_config", None)

    if request.method == "POST":
        try:
            start_date = datetime.strptime((request.form.get("depreciation_start_date") or "").strip(), "%Y-%m-%d").date()
            configure_asset_depreciation_record(
                branch_id=current_user.branch_id,
                asset_id=asset.id,
                depreciation_start_date=start_date,
                useful_life_months=(request.form.get("useful_life_months") or "").strip(),
                residual_value=(request.form.get("residual_value") or "0").strip(),
                accumulated_account_code=(request.form.get("accumulated_account_code") or "").strip(),
                status=(request.form.get("status") or "CONFIGURED").strip().upper(),
                notes=(request.form.get("notes") or "").strip(),
                created_by=current_user.id,
            )
            flash("Konfigurasi penyusutan aset berhasil disimpan. Jurnal belum dibuat sampai proses posting dijalankan.", "success")
            return redirect(url_for("finance.fixed_asset_depreciation"))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6578")
            flash(str(exc), "danger")
            return redirect(url_for("finance.fixed_asset_depreciation_configure", asset_id=asset.id))

    default_account_code = resolve_default_accumulated_account_code(asset.asset_category)
    preview_rows = preview_asset_depreciation(asset, months=12) if config else []
    return render_template(
        "finance/fixed_asset_depreciation_configure.html",
        asset=asset,
        config=config,
        default_account_code=default_account_code,
        accumulated_account_options=get_accumulated_account_options(),
        status_options=DEPRECIATION_STATUS_OPTIONS,
        preview_rows=preview_rows,
    )


@finance_bp.route("/fixed-asset-depreciation/<int:asset_id>/post", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_depreciation_post(asset_id):
    from app.services.fixed_asset_depreciation_service import is_depreciation_schema_ready, post_asset_depreciation_record

    if not is_depreciation_schema_ready():
        flash("Tabel penyusutan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_depreciation"))

    try:
        entry = post_asset_depreciation_record(
            branch_id=current_user.branch_id,
            asset_id=asset_id,
            period_year=(request.form.get("period_year") or "").strip(),
            period_month=(request.form.get("period_month") or "").strip(),
            created_by=current_user.id,
        )
        flash(f"Penyusutan {entry.depreciation_number} berhasil diposting ke jurnal.", "success")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6613")
        flash(str(exc), "danger")
    return redirect(url_for("finance.fixed_asset_depreciation"))


# === PRODUCTION_FIXED_ASSET_PURCHASE_CASH_BANK ===
@finance_bp.route("/fixed-asset-purchases")
@role_required("OWNER", "ADMIN", "FINANCE")
def fixed_asset_purchases():
    from app.services.fixed_asset_purchase_service import list_fixed_asset_purchases

    q = (request.args.get("q") or "").strip()
    payment_method = (request.args.get("payment_method") or "ALL").strip().upper()
    purchases = list_fixed_asset_purchases(
        branch_id=current_user.branch_id,
        q=q,
        payment_method=payment_method,
    )

    summary = {
        "count": len(purchases),
        "total_amount": sum(float(row.amount or 0) for row in purchases),
        "cash_amount": sum(float(row.amount or 0) for row in purchases if row.account_type == "CASH"),
        "bank_amount": sum(float(row.amount or 0) for row in purchases if row.account_type == "BANK"),
    }

    return render_template(
        "finance/fixed_asset_purchases.html",
        purchases=purchases,
        q=q,
        payment_method=payment_method,
        summary=summary,
    )


@finance_bp.route("/fixed-asset-purchases/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_fixed_asset_purchase():
    from datetime import datetime
    from app.models.accounting import FixedAsset
    from app.models.finance import BankAccount
    from app.services.fixed_asset_purchase_service import (
        ASSET_CATEGORY_OPTIONS,
        create_fixed_asset_purchase_record,
        get_asset_account_options,
    )

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    existing_assets = FixedAsset.query.filter_by(
        branch_id=current_user.branch_id,
        status="ACTIVE",
    ).order_by(FixedAsset.asset_code.asc()).all()

    if request.method == "POST":
        purchase_date_raw = (request.form.get("purchase_date") or "").strip()
        try:
            purchase_date = datetime.strptime(purchase_date_raw, "%Y-%m-%d").date()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6674")
            flash("Tanggal pembelian aset tidak valid.", "warning")
            return redirect(url_for("finance.create_fixed_asset_purchase"))

        asset_mode = (request.form.get("asset_mode") or "NEW").strip().upper()
        asset_id_raw = (request.form.get("asset_id") or "").strip()
        asset_id = None
        if asset_id_raw:
            try:
                asset_id = int(asset_id_raw)
            except (TypeError, ValueError):
                asset_id = None

        bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
        bank_account_id = None
        if bank_account_id_raw:
            try:
                bank_account_id = int(bank_account_id_raw)
            except (TypeError, ValueError):
                bank_account_id = None

        try:
            purchase, ledger_transaction, journal = create_fixed_asset_purchase_record(
                branch_id=current_user.branch_id,
                purchase_date=purchase_date,
                asset_mode=asset_mode,
                asset_id=asset_id,
                asset_name=(request.form.get("asset_name") or "").strip(),
                asset_category=(request.form.get("asset_category") or "OTHER").strip(),
                asset_account_code=(request.form.get("asset_account_code") or "").strip(),
                payment_method=(request.form.get("payment_method") or "").strip(),
                bank_account_id=bank_account_id,
                amount=(request.form.get("amount") or "").strip(),
                useful_life_years=(request.form.get("useful_life_years") or "0").strip(),
                residual_value=(request.form.get("residual_value") or "0").strip(),
                vendor_name=(request.form.get("vendor_name") or "").strip(),
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
                created_by=current_user.id,
            )
            flash(
                f"Pembelian aset tetap {purchase.purchase_number} berhasil disimpan. Ledger OUT dan jurnal {journal.journal_number} dibuat.",
                "success",
            )
            return redirect(url_for("finance.fixed_asset_purchase_detail", purchase_id=purchase.id))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6719")
            flash(f"Gagal menyimpan pembelian aset tetap: {exc}", "danger")
            return redirect(url_for("finance.create_fixed_asset_purchase"))

    return render_template(
        "finance/fixed_asset_purchase_form.html",
        active_bank_accounts=active_bank_accounts,
        existing_assets=existing_assets,
        asset_categories=ASSET_CATEGORY_OPTIONS,
        asset_account_options=get_asset_account_options(),
    )


@finance_bp.route("/fixed-asset-purchases/<int:purchase_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def fixed_asset_purchase_detail(purchase_id):
    from app.services.fixed_asset_purchase_service import get_fixed_asset_purchase_detail

    purchase = get_fixed_asset_purchase_detail(purchase_id, current_user.branch_id)
    if not purchase:
        flash("Pembelian aset tetap tidak ditemukan.", "warning")
        return redirect(url_for("finance.fixed_asset_purchases"))

    return render_template(
        "finance/fixed_asset_purchase_detail.html",
        purchase=purchase,
        asset=purchase.fixed_asset,
        ledger_transaction=purchase.cash_bank_transaction,
        journal=purchase.journal,
    )


# === PRODUCTION_ASSET_VEHICLE_INSTALLMENT_FOUNDATION_ROUTES ===
@finance_bp.route("/fixed-asset-installments")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_installments():
    from app.services.fixed_asset_installment_service import (
        build_installment_summary,
        is_installment_schema_ready,
        list_asset_financing_contracts,
    )

    schema_ready = is_installment_schema_ready()
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "ALL").strip().upper()
    contracts = list_asset_financing_contracts(current_user.branch_id, q=q, status=status) if schema_ready else []
    summary = build_installment_summary(contracts) if schema_ready else {
        "count": 0,
        "active_count": 0,
        "total_contract": 0,
        "paid": 0,
        "remaining": 0,
    }

    return render_template(
        "finance/fixed_asset_installments.html",
        schema_ready=schema_ready,
        contracts=contracts,
        summary=summary,
        q=q,
        status=status,
    )


@finance_bp.route("/fixed-asset-installments/create", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def create_fixed_asset_installment_contract():
    from datetime import datetime
    from app.extensions import db
    from app.models.accounting import FixedAsset
    from app.models.finance import BankAccount
    from app.services.fixed_asset_installment_service import (
        create_asset_financing_contract,
        get_installment_account_options,
        is_installment_schema_ready,
    )
    from app.services.fixed_asset_purchase_service import ASSET_CATEGORY_OPTIONS

    if not is_installment_schema_ready():
        flash("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    existing_assets = FixedAsset.query.filter_by(
        branch_id=current_user.branch_id,
        status="ACTIVE",
    ).order_by(FixedAsset.asset_code.asc()).all()

    if request.method == "POST":
        try:
            contract_date = datetime.strptime((request.form.get("contract_date") or "").strip(), "%Y-%m-%d").date()
            first_due_date = datetime.strptime((request.form.get("first_due_date") or "").strip(), "%Y-%m-%d").date()
            asset_id_raw = (request.form.get("asset_id") or "").strip()
            asset_id = int(asset_id_raw) if asset_id_raw else None

            with atomic_business_action(
                module="FIXED_ASSET",
                action="ASSET_FINANCING_CONTRACT_CREATE",
                description="Buat kontrak cicilan aset tetap/kendaraan.",
                reference_type="asset_financing_contracts",
                user_id=current_user.id,
                branch_id=current_user.branch_id,
                severity="HIGH",
                metadata={"app_version": "PRODUCTION", "scope": "asset_installment_contract"},
            ):
                contract = create_asset_financing_contract(
                    branch_id=current_user.branch_id,
                    contract_date=contract_date,
                    asset_mode=(request.form.get("asset_mode") or "NEW").strip().upper(),
                    asset_id=asset_id,
                    asset_name=(request.form.get("asset_name") or "").strip(),
                    asset_category=(request.form.get("asset_category") or "OTHER").strip(),
                    asset_account_code=(request.form.get("asset_account_code") or "").strip(),
                    liability_account_code=(request.form.get("liability_account_code") or "2001").strip(),
                    interest_expense_account_code=(request.form.get("interest_expense_account_code") or "5008").strip(),
                    admin_expense_account_code=(request.form.get("admin_expense_account_code") or "5008").strip(),
                    principal_amount=(request.form.get("principal_amount") or "").strip(),
                    total_interest_amount=(request.form.get("total_interest_amount") or "0").strip(),
                    total_admin_amount=(request.form.get("total_admin_amount") or "0").strip(),
                    installment_count=(request.form.get("installment_count") or "1").strip(),
                    first_due_date=first_due_date,
                    vendor_name=(request.form.get("vendor_name") or "").strip(),
                    financing_provider=(request.form.get("financing_provider") or "").strip(),
                    notes=(request.form.get("notes") or "").strip(),
                    created_by=current_user.id,
                    commit=False,
                )
            flash(f"Kontrak cicilan aset {contract.contract_number} berhasil dibuat. Jurnal akuisisi dan jadwal cicilan terbentuk.", "success")
            return redirect(url_for("finance.fixed_asset_installment_detail", contract_id=contract.id))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6851")
            flash(f"Gagal membuat kontrak cicilan aset: {exc}", "danger")
            return redirect(url_for("finance.create_fixed_asset_installment_contract"))

    return render_template(
        "finance/fixed_asset_installment_form.html",
        existing_assets=existing_assets,
        active_bank_accounts=active_bank_accounts,
        asset_categories=ASSET_CATEGORY_OPTIONS,
        account_options=get_installment_account_options(),
    )


@finance_bp.route("/fixed-asset-installments/<int:contract_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def fixed_asset_installment_detail(contract_id):
    from app.models.finance import BankAccount
    from app.services.fixed_asset_installment_service import calculate_contract_summary, get_contract_detail, is_installment_schema_ready

    if not is_installment_schema_ready():
        flash("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))
    contract = get_contract_detail(contract_id, current_user.branch_id)
    if not contract:
        flash("Kontrak cicilan aset tidak ditemukan.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))
    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    return render_template(
        "finance/fixed_asset_installment_detail.html",
        contract=contract,
        asset=contract.fixed_asset,
        summary=calculate_contract_summary(contract),
        active_bank_accounts=active_bank_accounts,
    )


@finance_bp.route("/fixed-asset-installments/<int:contract_id>/pay/<int:schedule_id>", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def pay_fixed_asset_installment(contract_id, schedule_id):
    from datetime import datetime
    from app.extensions import db
    from app.services.fixed_asset_installment_service import is_installment_schema_ready, pay_installment_schedule

    if not is_installment_schema_ready():
        flash("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.", "warning")
        return redirect(url_for("finance.fixed_asset_installments"))
    try:
        payment_date = datetime.strptime((request.form.get("payment_date") or "").strip(), "%Y-%m-%d").date()
        bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
        bank_account_id = int(bank_account_id_raw) if bank_account_id_raw else None
        with atomic_business_action(
            module="FIXED_ASSET",
            action="ASSET_INSTALLMENT_PAYMENT_CREATE",
            description="Bayar jadwal cicilan aset tetap/kendaraan.",
            reference_type="asset_installment_schedules",
            reference_id=schedule_id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            severity="HIGH",
            metadata={"app_version": "PRODUCTION", "contract_id": contract_id, "schedule_id": schedule_id},
        ):
            payment = pay_installment_schedule(
                branch_id=current_user.branch_id,
                contract_id=contract_id,
                schedule_id=schedule_id,
                payment_date=payment_date,
                payment_method=(request.form.get("payment_method") or "").strip(),
                bank_account_id=bank_account_id,
                reference_number=(request.form.get("reference_number") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
                created_by=current_user.id,
                commit=False,
            )
        flash(f"Pembayaran cicilan {payment.payment_number} berhasil dicatat ke ledger dan jurnal.", "success")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6928")
        flash(f"Gagal membayar cicilan aset: {exc}", "danger")
    return redirect(url_for("finance.fixed_asset_installment_detail", contract_id=contract_id))
