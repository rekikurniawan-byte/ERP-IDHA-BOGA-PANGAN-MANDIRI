"""Client and client PIC master routes.

Route functions moved out of app.routes.master_routes without changing URL rules or endpoint names.
"""
from app.routes.master_routes import *  # noqa: F401,F403
from app.services.pricing_service import CUSTOMER_PATH_LABELS, CUSTOMER_PATHS, PATH_CONTRACT
from app.utils.terms import T


@master_bp.route("/")
@role_required("ADMIN", "LOGISTICS")
def index():
    mandor_count = Mandor.query.filter_by(branch_id=current_user.branch_id).count()
    location_count = DeliveryLocation.query.join(Mandor).filter(
        Mandor.branch_id == current_user.branch_id
    ).count()
    worker_count = Worker.query.join(Mandor).filter(
        Mandor.branch_id == current_user.branch_id
    ).count()
    driver_count = Driver.query.filter_by(branch_id=current_user.branch_id).count()
    item_count = Item.query.count()
    bank_account_count = BankAccount.query.filter_by(branch_id=current_user.branch_id).count()
    fixed_asset_count = FixedAsset.query.filter_by(branch_id=current_user.branch_id).count()
    supplier_count = Supplier.query.filter_by(branch_id=current_user.branch_id).count()
    item_cost_profile_count = ItemCostProfile.query.filter_by(branch_id=current_user.branch_id).count()
    menu_count = Menu.query.filter_by(branch_id=current_user.branch_id).count()
    recipe_count = RecipeHeader.query.filter_by(branch_id=current_user.branch_id).count()
    packaging_profile_count = PackagingProfile.query.filter_by(branch_id=current_user.branch_id).count()
    overhead_profile_count = OverheadProfile.query.filter_by(branch_id=current_user.branch_id).count()

    return render_template(
        "master/index.html",
        mandor_count=mandor_count,
        location_count=location_count,
        worker_count=worker_count,
        driver_count=driver_count,
        item_count=item_count,
        bank_account_count=bank_account_count,
        fixed_asset_count=fixed_asset_count,
        supplier_count=supplier_count,
        item_cost_profile_count=item_cost_profile_count,
        menu_count=menu_count,
        recipe_count=recipe_count,
        packaging_profile_count=packaging_profile_count,
        overhead_profile_count=overhead_profile_count
    )


# =========================
# CLIENT
# =========================


def _requested_customer_path():
    value = (request.form.get("customer_path") or "").strip().upper()
    return value if value in CUSTOMER_PATHS else PATH_CONTRACT


def _clean_client_code(value):
    return str(value or "").strip().upper()


def _client_code_is_used(client_code, exclude_id=None):
    if not client_code or not hasattr(Client, "client_code"):
        return False
    query = Client.query.filter(Client.client_code == client_code)
    if exclude_id:
        query = query.filter(Client.id != exclude_id)
    return query.first() is not None

@master_bp.route("/clients")
@role_required("OWNER", "FINANCE")
def clients():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"

    query = Client.query

    if hasattr(Client, "branch_id"):
        query = query.filter(Client.branch_id == current_user.branch_id)

    if q:
        filters = [Client.name.ilike(f"%{q}%")]

        if hasattr(Client, "phone"):
            filters.append(Client.phone.ilike(f"%{q}%"))

        if hasattr(Client, "client_code"):
            filters.append(Client.client_code.ilike(f"%{q}%"))

        query = query.filter(or_(*filters))

    if hasattr(Client, "is_active"):
        if status == "ACTIVE":
            query = query.filter(Client.is_active == True)
        elif status == "INACTIVE":
            query = query.filter(Client.is_active == False)

    clients = query.order_by(Client.name.asc()).all()

    return render_template(
        "master/clients.html",
        clients=clients,
        q=q,
        status=status
    )


@master_bp.route("/clients/create", methods=["GET", "POST"])
@role_required("OWNER", "FINANCE")
def create_client():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        client_code = _clean_client_code(request.form.get("client_code")) or generate_client_code()
        phone = (request.form.get("phone") or "").strip()
        address = (request.form.get("address") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash(f"Nama {T.client_lower} wajib diisi.", "warning")
            return redirect(url_for("master.create_client"))

        if client_name_is_used(name, current_user.branch_id):
            flash(f"Nama {T.client_lower} sudah ada. Data {T.client_lower} tidak disimpan agar tidak duplikat.", "warning")
            return redirect(url_for("master.create_client"))

        if _client_code_is_used(client_code):
            flash(f"Kode {T.client_lower} sudah digunakan. Gunakan kode {T.client_lower} lain.", "warning")
            return redirect(url_for("master.create_client"))

        create_client_record(
            branch_id=current_user.branch_id,
            client_code=client_code,
            name=name,
            phone=phone,
            address=address,
            is_active=is_active,
            customer_path=_requested_customer_path(),
        )

        flash(f"{T.client} berhasil ditambahkan.", "success")
        return redirect(url_for("master.clients"))

    return render_template("master/client_form.html", client=None, customer_paths=CUSTOMER_PATH_LABELS)


@master_bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@role_required("OWNER", "FINANCE")
def edit_client(client_id):
    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash(f"Data {T.client_lower} tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        client_code = _clean_client_code(request.form.get("client_code")) or generate_client_code()
        phone = (request.form.get("phone") or "").strip()
        address = (request.form.get("address") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash(f"Nama {T.client_lower} wajib diisi.", "warning")
            return redirect(url_for("master.edit_client", client_id=client.id))

        if client_name_is_used(name, current_user.branch_id, exclude_id=client.id):
            flash(f"Nama {T.client_lower} sudah digunakan oleh data lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_client", client_id=client.id))

        if _client_code_is_used(client_code, exclude_id=client.id):
            flash(f"Kode {T.client_lower} sudah digunakan oleh {T.client_lower} lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_client", client_id=client.id))

        # Memindah jalur mengubah cara pelanggan membayar: hanya OWNER.
        previous_path = client.customer_path
        new_path = _requested_customer_path() if current_user.role == "OWNER" else None
        update_client_record(
            client,
            client_code=client_code,
            name=name,
            phone=phone,
            address=address,
            is_active=is_active,
            customer_path=new_path,
        )
        if new_path and new_path != previous_path:
            record_audit_log(
                module="PRICING",
                event_type="CUSTOMER_PATH_CHANGED",
                action="UPDATE",
                table_name="clients",
                record_id=client.id,
                description=f"Jalur {client.name}: {previous_path} → {new_path}.",
                old_value={"customer_path": previous_path},
                new_value={"customer_path": new_path},
            )

        flash(f"{T.client} berhasil diperbarui.", "success")
        return redirect(url_for("master.clients"))

    from app.services.client_direct_order_service import get_direct_unit

    return render_template(
        "master/client_form.html",
        client=client,
        direct_unit=get_direct_unit(current_user.branch_id, client.id),
        customer_paths=CUSTOMER_PATH_LABELS,
    )


@master_bp.route("/clients/<int:client_id>/direct-ordering", methods=["POST"])
@role_required("ADMIN")
def activate_client_direct_ordering(client_id):
    """Aktifkan order langsung: buat unit "PT X — Langsung", lalu minta lokasinya."""
    from app.services.client_direct_order_service import DirectOrderError, activate_direct_ordering

    client = Client.query.get_or_404(client_id)
    try:
        unit, created = activate_direct_ordering(client, current_user.branch_id)
    except DirectOrderError as error:
        flash(str(error), "warning")
        return redirect(url_for("master.edit_client", client_id=client.id))

    if created:
        flash(f"Order langsung aktif lewat unit '{unit.name}'. Tambahkan lokasi antarnya.", "success")
    else:
        flash(f"Order langsung sudah aktif lewat unit '{unit.name}'.", "info")
    return redirect(url_for("master.create_location", mandor_id=unit.id))


@master_bp.route("/clients/<int:client_id>/toggle", methods=["POST"])
@role_required("OWNER", "FINANCE")
def toggle_client(client_id):
    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash(f"Data {T.client_lower} tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    if hasattr(Client, "is_active"):
        toggle_client_active(client)
        flash(f"Status {T.client_lower} berhasil diubah.", "success")
    else:
        flash(f"Model {T.client_lower} belum memiliki kolom is_active.", "warning")

    return redirect(url_for("master.clients"))


@master_bp.route("/clients/<int:client_id>/pics/create", methods=["POST"])
@role_required("OWNER")
def create_client_pic(client_id):
    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash(f"Data {T.client_lower} tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    name = (request.form.get("pic_name") or "").strip()
    phone = (request.form.get("pic_phone") or "").strip()
    email = (request.form.get("pic_email") or "").strip()
    position = (request.form.get("pic_position") or "").strip()

    if not name:
        flash("Nama PIC wajib diisi.", "warning")
        return redirect(url_for("master.edit_client", client_id=client.id))

    create_client_pic_record(
        client_id=client.id,
        name=name,
        phone=phone,
        email=email if hasattr(ClientPic, "email") else None,
        position=position,
        is_active=True
    )

    flash(f"PIC {T.client_lower} berhasil ditambahkan.", "success")
    return redirect(url_for("master.edit_client", client_id=client.id))


@master_bp.route("/clients/<int:client_id>/pics/<int:pic_id>/toggle", methods=["POST"])
@role_required("OWNER")
def toggle_client_pic(client_id, pic_id):
    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash(f"Data {T.client_lower} tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    pic = ClientPic.query.get_or_404(pic_id)

    if pic.client_id != client.id:
        flash(f"PIC tidak sesuai dengan {T.client_lower}.", "danger")
        return redirect(url_for("master.edit_client", client_id=client.id))

    toggle_client_pic_active(pic)

    flash(f"Status PIC {T.client_lower} berhasil diubah.", "success")
    return redirect(url_for("master.edit_client", client_id=client.id))


@master_bp.route("/clients/<int:client_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def client_360(client_id):
    from app.services.client_360_service import build_client_360

    data = build_client_360(client_id, current_user.branch_id)
    if not data:
        flash(f"Data {T.client_lower} tidak ditemukan.", "warning")
        return redirect(url_for("master.clients"))

    return render_template("master/client_360.html", c=data)

