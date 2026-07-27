"""Supplier, bank account, and fixed asset master routes.

Route functions moved out of app.routes.master_routes without changing URL rules or endpoint names.
"""
from app.routes.master_routes import *  # noqa: F401,F403


@master_bp.route("/suppliers")
@role_required("OWNER", "LOGISTICS")
def suppliers():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"
    supplier_type = request.args.get("supplier_type") or "ALL"

    query = Supplier.query.filter_by(branch_id=current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                Supplier.supplier_code.ilike(f"%{q}%"),
                Supplier.supplier_name.ilike(f"%{q}%"),
                Supplier.contact_person.ilike(f"%{q}%"),
                Supplier.phone.ilike(f"%{q}%"),
                Supplier.whatsapp.ilike(f"%{q}%")
            )
        )

    if supplier_type != "ALL":
        query = query.filter(Supplier.supplier_type == supplier_type)

    if status == "ACTIVE":
        query = query.filter(Supplier.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(Supplier.is_active == False)

    suppliers = query.order_by(Supplier.supplier_name.asc()).all()

    return render_template(
        "master/suppliers.html",
        suppliers=suppliers,
        q=q,
        status=status,
        supplier_type=supplier_type,
        supplier_types=SUPPLIER_TYPES
    )


@master_bp.route("/suppliers/create", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def create_supplier():
    if request.method == "POST":
        supplier_name = (request.form.get("supplier_name") or "").strip()
        supplier_type = request.form.get("supplier_type") or "GENERAL"
        contact_person = (request.form.get("contact_person") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        whatsapp = (request.form.get("whatsapp") or "").strip()
        address = (request.form.get("address") or "").strip()
        default_payment_terms_days = int(to_float(request.form.get("default_payment_terms_days")))
        bank_name = (request.form.get("bank_name") or "").strip()
        bank_account_number = (request.form.get("bank_account_number") or "").strip()
        bank_account_holder = (request.form.get("bank_account_holder") or "").strip()
        npwp = (request.form.get("npwp") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not supplier_name:
            flash("Nama supplier wajib diisi.", "warning")
            return redirect(url_for("master.create_supplier"))

        if supplier_type not in SUPPLIER_TYPES:
            supplier_type = "GENERAL"

        if default_payment_terms_days < 0:
            default_payment_terms_days = 0

        if supplier_name_is_used(supplier_name, current_user.branch_id):
            flash("Nama supplier sudah ada di cabang ini. Data tidak disimpan agar tidak duplikat.", "warning")
            return redirect(url_for("master.create_supplier"))

        supplier = create_supplier_record(
            branch_id=current_user.branch_id,
            supplier_code=generate_supplier_code(),
            supplier_name=supplier_name,
            supplier_type=supplier_type,
            contact_person=contact_person,
            phone=phone,
            whatsapp=whatsapp,
            address=address,
            default_payment_terms_days=default_payment_terms_days,
            bank_name=bank_name,
            bank_account_number=bank_account_number,
            bank_account_holder=bank_account_holder,
            npwp=npwp,
            notes=notes,
            is_active=is_active
        )

        record_audit_log(
            module="MASTER",
            event_type="SUPPLIER_CREATED",
            action="CREATE",
            table_name="suppliers",
            record_id=supplier.id,
            description=f"Supplier dibuat: {supplier.supplier_name}.",
        )
        flash(f"Supplier berhasil ditambahkan dengan kode {supplier.supplier_code}.", "success")
        return redirect(url_for("master.suppliers"))

    return render_template(
        "master/supplier_form.html",
        supplier=None,
        supplier_types=SUPPLIER_TYPES
    )


@master_bp.route("/suppliers/<int:supplier_id>/edit", methods=["GET", "POST"])
@role_required("OWNER", "LOGISTICS")
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)

    if supplier.branch_id != current_user.branch_id:
        flash("Data supplier tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.suppliers"))

    if request.method == "POST":
        supplier_name = (request.form.get("supplier_name") or "").strip()
        supplier_type = request.form.get("supplier_type") or "GENERAL"
        contact_person = (request.form.get("contact_person") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        whatsapp = (request.form.get("whatsapp") or "").strip()
        address = (request.form.get("address") or "").strip()
        default_payment_terms_days = int(to_float(request.form.get("default_payment_terms_days")))
        bank_name = (request.form.get("bank_name") or "").strip()
        bank_account_number = (request.form.get("bank_account_number") or "").strip()
        bank_account_holder = (request.form.get("bank_account_holder") or "").strip()
        npwp = (request.form.get("npwp") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not supplier_name:
            flash("Nama supplier wajib diisi.", "warning")
            return redirect(url_for("master.edit_supplier", supplier_id=supplier.id))

        if supplier_type not in SUPPLIER_TYPES:
            supplier_type = "GENERAL"

        if default_payment_terms_days < 0:
            default_payment_terms_days = 0

        if supplier_name_is_used(supplier_name, current_user.branch_id, exclude_id=supplier.id):
            flash("Nama supplier sudah digunakan oleh data lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_supplier", supplier_id=supplier.id))

        update_supplier_record(
            supplier,
            supplier_name=supplier_name,
            supplier_type=supplier_type,
            contact_person=contact_person,
            phone=phone,
            whatsapp=whatsapp,
            address=address,
            default_payment_terms_days=default_payment_terms_days,
            bank_name=bank_name,
            bank_account_number=bank_account_number,
            bank_account_holder=bank_account_holder,
            npwp=npwp,
            notes=notes,
            is_active=is_active,
        )

        record_audit_log(
            module="MASTER",
            event_type="SUPPLIER_UPDATED",
            action="UPDATE",
            table_name="suppliers",
            record_id=supplier.id,
            description=f"Supplier diperbarui: {supplier.supplier_name}.",
        )
        flash("Supplier berhasil diperbarui.", "success")
        return redirect(url_for("master.suppliers"))

    return render_template(
        "master/supplier_form.html",
        supplier=supplier,
        supplier_types=SUPPLIER_TYPES
    )


@master_bp.route("/suppliers/<int:supplier_id>/toggle", methods=["POST"])
@role_required("OWNER", "LOGISTICS")
def toggle_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)

    if supplier.branch_id != current_user.branch_id:
        flash("Data supplier tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.suppliers"))

    toggle_supplier_active(supplier)

    record_audit_log(
        module="MASTER",
        event_type="SUPPLIER_TOGGLED",
        action="UPDATE",
        table_name="suppliers",
        record_id=supplier.id,
        description=f"Status supplier diubah: {supplier.supplier_name}.",
        new_value={"is_active": supplier.is_active},
    )
    flash("Status supplier berhasil diubah.", "success")
    return redirect(url_for("master.suppliers"))


# =========================
# REKENING BANK
# =========================

@master_bp.route("/bank-accounts")
@role_required("OWNER", "FINANCE")
def bank_accounts():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"

    query = BankAccount.query.filter_by(branch_id=current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                BankAccount.account_name.ilike(f"%{q}%"),
                BankAccount.bank_name.ilike(f"%{q}%"),
                BankAccount.account_number.ilike(f"%{q}%")
            )
        )

    if status == "ACTIVE":
        query = query.filter(BankAccount.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(BankAccount.is_active == False)

    accounts = query.order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    return render_template(
        "master/bank_accounts.html",
        accounts=accounts,
        q=q,
        status=status
    )


@master_bp.route("/bank-accounts/create", methods=["GET", "POST"])
@role_required("OWNER", "FINANCE")
def create_bank_account():
    if request.method == "POST":
        account_name = (request.form.get("account_name") or "").strip()
        bank_name = (request.form.get("bank_name") or "").strip()
        account_number = (request.form.get("account_number") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not account_name or not bank_name or not account_number:
            flash("Nama rekening, nama bank, dan nomor rekening wajib diisi.", "warning")
            return redirect(url_for("master.create_bank_account"))

        if bank_account_number_is_used(account_number):
            flash("Nomor rekening sudah digunakan. Data tidak disimpan agar tidak duplikat.", "warning")
            return redirect(url_for("master.create_bank_account"))

        account = create_bank_account_record(
            branch_id=current_user.branch_id,
            account_name=account_name,
            bank_name=bank_name,
            account_number=account_number,
            is_active=is_active
        )

        record_audit_log(
            module="MASTER",
            event_type="BANK_ACCOUNT_CREATED",
            action="CREATE",
            table_name="bank_accounts",
            record_id=account.id,
            description=f"Rekening bank dibuat: {account.bank_name} - {account.account_name}.",
            metadata={"bank_name": account.bank_name, "account_name": account.account_name, "is_active": account.is_active},
        )

        flash("Rekening bank berhasil ditambahkan.", "success")
        return redirect(url_for("master.bank_accounts"))

    return render_template("master/bank_account_form.html", account=None)


@master_bp.route("/bank-accounts/<int:account_id>/edit", methods=["GET", "POST"])
@role_required("OWNER", "FINANCE")
def edit_bank_account(account_id):
    account = BankAccount.query.get_or_404(account_id)

    if account.branch_id != current_user.branch_id:
        flash("Data rekening tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.bank_accounts"))

    if request.method == "POST":
        account_name = (request.form.get("account_name") or "").strip()
        bank_name = (request.form.get("bank_name") or "").strip()
        account_number = (request.form.get("account_number") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not account_name or not bank_name or not account_number:
            flash("Nama rekening, nama bank, dan nomor rekening wajib diisi.", "warning")
            return redirect(url_for("master.edit_bank_account", account_id=account.id))

        if bank_account_number_is_used(account_number, exclude_id=account.id):
            flash("Nomor rekening sudah digunakan oleh rekening lain.", "warning")
            return redirect(url_for("master.edit_bank_account", account_id=account.id))

        old_snapshot = {
            "account_name": account.account_name,
            "bank_name": account.bank_name,
            "account_number": account.account_number,
            "is_active": account.is_active,
        }

        update_bank_account_record(
            account,
            account_name=account_name,
            bank_name=bank_name,
            account_number=account_number,
            is_active=is_active,
        )

        record_audit_log(
            module="MASTER",
            event_type="BANK_ACCOUNT_UPDATED",
            action="UPDATE",
            table_name="bank_accounts",
            record_id=account.id,
            description=f"Rekening bank diperbarui: {account.bank_name} - {account.account_name}.",
            old_value=old_snapshot,
            new_value={"account_name": account.account_name, "bank_name": account.bank_name, "is_active": account.is_active},
        )

        flash("Rekening bank berhasil diperbarui.", "success")
        return redirect(url_for("master.bank_accounts"))

    return render_template("master/bank_account_form.html", account=account)


@master_bp.route("/bank-accounts/<int:account_id>/toggle", methods=["POST"])
@role_required("OWNER", "FINANCE")
def toggle_bank_account(account_id):
    account = BankAccount.query.get_or_404(account_id)

    if account.branch_id != current_user.branch_id:
        flash("Data rekening tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.bank_accounts"))

    toggle_bank_account_active(account)

    record_audit_log(
        module="MASTER",
        event_type="BANK_ACCOUNT_TOGGLED",
        action="UPDATE",
        table_name="bank_accounts",
        record_id=account.id,
        description=f"Status rekening bank diubah: {account.bank_name} - {account.account_name}.",
        metadata={"is_active": account.is_active},
    )

    flash("Status rekening bank berhasil diubah.", "success")
    return redirect(url_for("master.bank_accounts"))


# =========================
# ASET TETAP
# =========================

@master_bp.route("/fixed-assets")
@role_required("OWNER")
def fixed_assets():
    q = (request.args.get("q") or "").strip()
    category = request.args.get("category") or "ALL"
    status = request.args.get("status") or "ALL"

    query = FixedAsset.query.filter_by(branch_id=current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                FixedAsset.asset_code.ilike(f"%{q}%"),
                FixedAsset.asset_name.ilike(f"%{q}%"),
                FixedAsset.asset_category.ilike(f"%{q}%")
            )
        )

    if category != "ALL":
        query = query.filter(FixedAsset.asset_category == category)

    if status != "ALL":
        query = query.filter(FixedAsset.status == status)

    assets = query.order_by(FixedAsset.asset_code.asc()).all()

    return render_template(
        "master/fixed_assets.html",
        assets=assets,
        q=q,
        category=category,
        status=status,
        categories=ASSET_CATEGORIES,
        statuses=ASSET_STATUSES
    )


@master_bp.route("/fixed-assets/create", methods=["GET", "POST"])
@role_required("OWNER")
def create_fixed_asset():
    if request.method == "POST":
        asset_name = (request.form.get("asset_name") or "").strip()
        asset_category = request.form.get("asset_category") or "OTHER"
        purchase_date = parse_date(request.form.get("purchase_date"))
        purchase_value = to_float(request.form.get("purchase_value"))
        useful_life_years = int(to_float(request.form.get("useful_life_years")))
        residual_value = to_float(request.form.get("residual_value"))
        accumulated_depreciation = to_float(request.form.get("accumulated_depreciation"))
        status = request.form.get("status") or "ACTIVE"
        notes = (request.form.get("notes") or "").strip()

        if not asset_name or not asset_category or not purchase_date:
            flash("Nama aset, kategori aset, dan tanggal pembelian wajib diisi.", "warning")
            return redirect(url_for("master.create_fixed_asset"))

        if asset_category not in ASSET_CATEGORIES:
            asset_category = "OTHER"

        if status not in ASSET_STATUSES:
            status = "ACTIVE"

        asset = create_fixed_asset_record(
            branch_id=current_user.branch_id,
            asset_code=generate_asset_code(),
            asset_name=asset_name,
            asset_category=asset_category,
            purchase_date=purchase_date,
            purchase_value=purchase_value,
            useful_life_years=useful_life_years,
            residual_value=residual_value,
            accumulated_depreciation=accumulated_depreciation,
            book_value=calculate_asset_book_value(purchase_value, accumulated_depreciation),
            status=status,
            notes=notes
        )

        flash(f"Aset tetap berhasil ditambahkan dengan kode {asset.asset_code}.", "success")
        return redirect(url_for("master.fixed_assets"))

    return render_template(
        "master/fixed_asset_form.html",
        asset=None,
        categories=ASSET_CATEGORIES,
        statuses=ASSET_STATUSES
    )


@master_bp.route("/fixed-assets/<int:asset_id>/edit", methods=["GET", "POST"])
@role_required("OWNER")
def edit_fixed_asset(asset_id):
    asset = FixedAsset.query.get_or_404(asset_id)

    if asset.branch_id != current_user.branch_id:
        flash("Data aset tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.fixed_assets"))

    if request.method == "POST":
        asset_name = (request.form.get("asset_name") or "").strip()
        asset_category = request.form.get("asset_category") or "OTHER"
        purchase_date = parse_date(request.form.get("purchase_date"))
        purchase_value = to_float(request.form.get("purchase_value"))
        useful_life_years = int(to_float(request.form.get("useful_life_years")))
        residual_value = to_float(request.form.get("residual_value"))
        accumulated_depreciation = to_float(request.form.get("accumulated_depreciation"))
        status = request.form.get("status") or "ACTIVE"
        notes = (request.form.get("notes") or "").strip()

        if not asset_name or not asset_category or not purchase_date:
            flash("Nama aset, kategori aset, dan tanggal pembelian wajib diisi.", "warning")
            return redirect(url_for("master.edit_fixed_asset", asset_id=asset.id))

        if asset_category not in ASSET_CATEGORIES:
            asset_category = "OTHER"

        if status not in ASSET_STATUSES:
            status = "ACTIVE"

        update_fixed_asset_record(
            asset,
            asset_code=asset.asset_code or generate_asset_code(),
            asset_name=asset_name,
            asset_category=asset_category,
            purchase_date=purchase_date,
            purchase_value=purchase_value,
            useful_life_years=useful_life_years,
            residual_value=residual_value,
            accumulated_depreciation=accumulated_depreciation,
            book_value=calculate_asset_book_value(purchase_value, accumulated_depreciation),
            status=status,
            notes=notes,
        )

        flash("Aset tetap berhasil diperbarui.", "success")
        return redirect(url_for("master.fixed_assets"))

    return render_template(
        "master/fixed_asset_form.html",
        asset=asset,
        categories=ASSET_CATEGORIES,
        statuses=ASSET_STATUSES
    )


@master_bp.route("/fixed-assets/<int:asset_id>/toggle", methods=["POST"])
@role_required("OWNER")
def toggle_fixed_asset(asset_id):
    asset = FixedAsset.query.get_or_404(asset_id)

    if asset.branch_id != current_user.branch_id:
        flash("Data aset tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.fixed_assets"))

    toggle_fixed_asset_status(asset)

    flash("Status aset tetap berhasil diubah.", "success")
    return redirect(url_for("master.fixed_assets"))
