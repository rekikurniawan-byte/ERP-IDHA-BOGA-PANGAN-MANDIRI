from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.master import Client, Mandor, DeliveryLocation, Worker, Driver, Supplier, Item, UnitConversion, ItemCostProfile, Menu, RecipeHeader, PackagingProfile, OverheadProfile
from app.models.finance import BankAccount
from app.models.accounting import FixedAsset
from app.models.canteen import WorkerDebt, CanteenSaleItem
from app.models.production import ProductionDetail
from app.models.logistics import ItemRequestDetail
from app.utils.decorators import role_required
from app.services.audit_log_service import record_audit_log
from app.services.master_data_service import generate_worker_code, generate_item_code, generate_client_code

master_bp = Blueprint("master", __name__, url_prefix="/master")


ITEM_CATEGORIES = ["RAW_MATERIAL", "MERCHANDISE", "PACKAGING", "GAS", "OTHER"]
WORKER_STATUSES = ["ACTIVE", "MOVED", "LEFT"]
ASSET_CATEGORIES = ["KITCHEN_EQUIPMENT", "VEHICLE", "OFFICE_EQUIPMENT", "BUILDING", "OTHER"]
ASSET_STATUSES = ["ACTIVE", "INACTIVE", "RETIRED", "SOLD"]
SUPPLIER_TYPES = ["GENERAL", "RAW_MATERIAL", "PACKAGING", "GAS", "SERVICE", "OTHER"]
COST_PROFILE_CATEGORIES = ["RAW_MATERIAL", "PACKAGING", "GAS", "OTHER"]
COST_UNITS = ["GRAM", "KG", "ML", "LITER", "PCS", "PACK", "DUS", "KARUNG", "TABUNG", "BOTOL", "PORSI"]
COST_SOURCES = ["STANDARD", "MANUAL", "LAST_PURCHASE"]



def to_float(value):
    try:
        cleaned = str(value or "0").strip()
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        return float(cleaned or 0)
    except (TypeError, ValueError):
        return 0


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def bank_account_number_is_used(account_number, exclude_id=None):
    query = BankAccount.query.filter(
        func.lower(BankAccount.account_number) == account_number.lower()
    )

    if exclude_id:
        query = query.filter(BankAccount.id != exclude_id)

    return query.first() is not None


def generate_asset_code():
    latest = FixedAsset.query.order_by(FixedAsset.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        asset_code = f"AST-{next_number:04d}"
        if not FixedAsset.query.filter_by(asset_code=asset_code).first():
            return asset_code
        next_number += 1


def generate_supplier_code():
    latest = Supplier.query.order_by(Supplier.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1

    while True:
        supplier_code = f"SUP-{next_number:04d}"
        if not Supplier.query.filter_by(supplier_code=supplier_code).first():
            return supplier_code
        next_number += 1


def supplier_name_is_used(name, branch_id, exclude_id=None):
    query = Supplier.query.filter(
        Supplier.branch_id == branch_id,
        func.lower(Supplier.supplier_name) == name.lower()
    )

    if exclude_id:
        query = query.filter(Supplier.id != exclude_id)

    return query.first() is not None


def calculate_asset_book_value(purchase_value, accumulated_depreciation):
    value = float(purchase_value or 0) - float(accumulated_depreciation or 0)
    return max(value, 0)


def mandor_name_is_used(name, branch_id, exclude_id=None):
    query = Mandor.query.filter(
        Mandor.branch_id == branch_id,
        func.lower(Mandor.name) == name.lower()
    )

    if exclude_id:
        query = query.filter(Mandor.id != exclude_id)

    return query.first() is not None


def client_name_is_used(name, branch_id, exclude_id=None):
    query = Client.query.filter(
        func.lower(Client.name) == name.lower()
    )

    if hasattr(Client, "branch_id"):
        query = query.filter(Client.branch_id == branch_id)

    if exclude_id:
        query = query.filter(Client.id != exclude_id)

    return query.first() is not None


def set_if_has_column(model_object, column_name, value):
    if hasattr(model_object.__class__, column_name):
        setattr(model_object, column_name, value)

def worker_is_used(worker_id):
    has_debt = WorkerDebt.query.filter_by(worker_id=worker_id).first()
    return has_debt is not None


def item_is_used(item_id):
    used_in_warung = CanteenSaleItem.query.filter_by(item_id=item_id).first()
    used_in_production = ProductionDetail.query.filter_by(item_id=item_id).first()
    used_in_request = ItemRequestDetail.query.filter_by(item_id=item_id).first()

    return (
        used_in_warung is not None
        or used_in_production is not None
        or used_in_request is not None
    )

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
            flash("Nama client wajib diisi.", "warning")
            return redirect(url_for("master.create_client"))

        if client_name_is_used(name, current_user.branch_id):
            flash("Nama client sudah ada. Data client tidak disimpan agar tidak duplikat.", "warning")
            return redirect(url_for("master.create_client"))

        if _client_code_is_used(client_code):
            flash("Kode client sudah digunakan. Gunakan kode client lain.", "warning")
            return redirect(url_for("master.create_client"))

        client = Client()

        set_if_has_column(client, "branch_id", current_user.branch_id)
        set_if_has_column(client, "client_code", client_code)
        set_if_has_column(client, "name", name)
        set_if_has_column(client, "phone", phone)
        set_if_has_column(client, "address", address)
        set_if_has_column(client, "is_active", is_active)

        db.session.add(client)
        db.session.commit()

        flash("Client berhasil ditambahkan.", "success")
        return redirect(url_for("master.clients"))

    return render_template("master/client_form.html", client=None)


@master_bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@role_required("OWNER", "FINANCE")
def edit_client(client_id):
    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash("Data client tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        client_code = _clean_client_code(request.form.get("client_code")) or generate_client_code()
        phone = (request.form.get("phone") or "").strip()
        address = (request.form.get("address") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash("Nama client wajib diisi.", "warning")
            return redirect(url_for("master.edit_client", client_id=client.id))

        if client_name_is_used(name, current_user.branch_id, exclude_id=client.id):
            flash("Nama client sudah digunakan oleh data lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_client", client_id=client.id))

        if _client_code_is_used(client_code, exclude_id=client.id):
            flash("Kode client sudah digunakan oleh client lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_client", client_id=client.id))

        set_if_has_column(client, "client_code", client_code)
        set_if_has_column(client, "name", name)
        set_if_has_column(client, "phone", phone)
        set_if_has_column(client, "address", address)
        set_if_has_column(client, "is_active", is_active)

        db.session.commit()

        flash("Client berhasil diperbarui.", "success")
        return redirect(url_for("master.clients"))

    return render_template("master/client_form.html", client=client)


@master_bp.route("/clients/<int:client_id>/toggle", methods=["POST"])
@role_required("OWNER", "FINANCE")
def toggle_client(client_id):
    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash("Data client tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    if hasattr(Client, "is_active"):
        client.is_active = not client.is_active
        db.session.commit()
        flash("Status client berhasil diubah.", "success")
    else:
        flash("Model client belum memiliki kolom is_active.", "warning")

    return redirect(url_for("master.clients"))


# =========================
# MANDOR
# =========================

@master_bp.route("/mandors")
@role_required("ADMIN")
def mandors():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"

    query = Mandor.query.filter_by(branch_id=current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                Mandor.name.ilike(f"%{q}%"),
                Mandor.phone.ilike(f"%{q}%")
            )
        )

    if status == "ACTIVE":
        query = query.filter(Mandor.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(Mandor.is_active == False)

    mandors = query.order_by(Mandor.name.asc()).all()

    return render_template(
        "master/mandors.html",
        mandors=mandors,
        q=q,
        status=status
    )


@master_bp.route("/mandors/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_mandor():
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()

    if request.method == "POST":
        client_id = request.form.get("client_id") or None
        name = (request.form.get("name") or "").strip()
        client_code = _clean_client_code(request.form.get("client_code")) or generate_client_code()
        phone = (request.form.get("phone") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash("Nama mandor wajib diisi.", "warning")
            return redirect(url_for("master.create_mandor"))
        if mandor_name_is_used(name, current_user.branch_id):
            flash("Nama mandor sudah ada di cabang ini. Data tidak disimpan agar tidak terjadi duplikasi.", "warning")
            return redirect(url_for("master.create_mandor"))
        mandor = Mandor(
            branch_id=current_user.branch_id,
            client_id=client_id,
            name=name,
            phone=phone,
            is_active=is_active
        )

        db.session.add(mandor)
        db.session.commit()

        flash("Mandor berhasil ditambahkan.", "success")
        return redirect(url_for("master.mandors"))

    return render_template("master/mandor_form.html", clients=clients, mandor=None)


@master_bp.route("/mandors/<int:mandor_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_mandor(mandor_id):
    mandor = Mandor.query.get_or_404(mandor_id)

    if mandor.branch_id != current_user.branch_id:
        flash("Data mandor tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.mandors"))

    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()

    if request.method == "POST":
        mandor.client_id = request.form.get("client_id") or None
        mandor.name = (request.form.get("name") or "").strip()
        mandor.phone = (request.form.get("phone") or "").strip()
        mandor.is_active = True if request.form.get("is_active") == "on" else False

        if not mandor.name:
            flash("Nama mandor wajib diisi.", "warning")
            return redirect(url_for("master.edit_mandor", mandor_id=mandor.id))

        if mandor_name_is_used(mandor.name, current_user.branch_id, exclude_id=mandor.id):
            flash("Nama mandor sudah digunakan oleh data lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_mandor", mandor_id=mandor.id))

        db.session.commit()

        flash("Mandor berhasil diperbarui.", "success")
        return redirect(url_for("master.mandors"))

    return render_template("master/mandor_form.html", clients=clients, mandor=mandor)


@master_bp.route("/mandors/<int:mandor_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_mandor(mandor_id):
    mandor = Mandor.query.get_or_404(mandor_id)

    if mandor.branch_id != current_user.branch_id:
        flash("Data mandor tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.mandors"))

    mandor.is_active = not mandor.is_active
    db.session.commit()

    flash("Status mandor berhasil diubah.", "success")
    return redirect(url_for("master.mandors"))


# =========================
# LOKASI
# =========================

@master_bp.route("/locations")
@role_required("ADMIN")
def locations():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"

    query = DeliveryLocation.query.join(Mandor).filter(
        Mandor.branch_id == current_user.branch_id
    )

    if q:
        query = query.filter(
            or_(
                DeliveryLocation.location_name.ilike(f"%{q}%"),
                DeliveryLocation.description.ilike(f"%{q}%"),
                Mandor.name.ilike(f"%{q}%")
            )
        )

    if status == "ACTIVE":
        query = query.filter(DeliveryLocation.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(DeliveryLocation.is_active == False)

    locations = query.order_by(Mandor.name.asc(), DeliveryLocation.location_name.asc()).all()

    return render_template(
        "master/locations.html",
        locations=locations,
        q=q,
        status=status
    )


@master_bp.route("/locations/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_location():
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(Mandor.name.asc()).all()

    if request.method == "POST":
        mandor_id = request.form.get("mandor_id")
        location_name = (request.form.get("location_name") or "").strip()
        description = (request.form.get("description") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not mandor_id or not location_name:
            flash("Mandor dan nama lokasi wajib diisi.", "warning")
            return redirect(url_for("master.create_location"))

        location = DeliveryLocation(
            mandor_id=mandor_id,
            location_name=location_name,
            description=description,
            is_active=is_active
        )

        try:
            db.session.add(location)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Lokasi ini sudah ada untuk mandor tersebut.", "warning")
            return redirect(url_for("master.create_location"))

        flash("Lokasi mandor berhasil ditambahkan.", "success")
        return redirect(url_for("master.locations"))

    return render_template("master/location_form.html", mandors=mandors, location=None)


@master_bp.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_location(location_id):
    location = DeliveryLocation.query.get_or_404(location_id)

    if not location.mandor or location.mandor.branch_id != current_user.branch_id:
        flash("Data lokasi tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.locations"))

    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(Mandor.name.asc()).all()

    if request.method == "POST":
        location.mandor_id = request.form.get("mandor_id")
        location.location_name = (request.form.get("location_name") or "").strip()
        location.description = (request.form.get("description") or "").strip()
        location.is_active = True if request.form.get("is_active") == "on" else False

        if not location.mandor_id or not location.location_name:
            flash("Mandor dan nama lokasi wajib diisi.", "warning")
            return redirect(url_for("master.edit_location", location_id=location.id))

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Lokasi ini sudah ada untuk mandor tersebut.", "warning")
            return redirect(url_for("master.edit_location", location_id=location.id))

        flash("Lokasi berhasil diperbarui.", "success")
        return redirect(url_for("master.locations"))

    return render_template("master/location_form.html", mandors=mandors, location=location)


@master_bp.route("/locations/<int:location_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_location(location_id):
    location = DeliveryLocation.query.get_or_404(location_id)

    if not location.mandor or location.mandor.branch_id != current_user.branch_id:
        flash("Data lokasi tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.locations"))

    location.is_active = not location.is_active
    db.session.commit()

    flash("Status lokasi berhasil diubah.", "success")
    return redirect(url_for("master.locations"))


# =========================
# PEKERJA
# =========================

@master_bp.route("/workers")
@role_required("ADMIN")
def workers():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"

    query = Worker.query.join(Mandor).filter(
        Mandor.branch_id == current_user.branch_id
    )

    if q:
        query = query.filter(
            or_(
                Worker.full_name.ilike(f"%{q}%"),
                Worker.worker_code.ilike(f"%{q}%"),
                Worker.phone.ilike(f"%{q}%"),
                Mandor.name.ilike(f"%{q}%")
            )
        )

    if status != "ALL":
        query = query.filter(Worker.status == status)

    workers = query.order_by(Worker.full_name.asc()).all()

    return render_template(
        "master/workers.html",
        workers=workers,
        q=q,
        status=status,
        statuses=WORKER_STATUSES
    )


@master_bp.route("/workers/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_worker():
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(Mandor.name.asc()).all()

    if request.method == "POST":
        mandor_id = request.form.get("mandor_id")
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        status = request.form.get("status") or "ACTIVE"
        notes = (request.form.get("notes") or "").strip()

        if not mandor_id or not full_name:
            flash("Mandor dan nama pekerja wajib diisi.", "warning")
            return redirect(url_for("master.create_worker"))

        worker = Worker(
            mandor_id=mandor_id,
            worker_code=generate_worker_code(),
            full_name=full_name,
            phone=phone,
            status=status,
            notes=notes
        )

        db.session.add(worker)
        db.session.commit()

        flash(f"Pekerja berhasil ditambahkan dengan kode {worker.worker_code}.", "success")
        return redirect(url_for("master.workers"))

    return render_template(
        "master/worker_form.html",
        mandors=mandors,
        worker=None,
        statuses=WORKER_STATUSES
    )


@master_bp.route("/workers/<int:worker_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)

    if not worker.mandor or worker.mandor.branch_id != current_user.branch_id:
        flash("Data pekerja tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.workers"))

    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(Mandor.name.asc()).all()

    if request.method == "POST":
        worker.mandor_id = request.form.get("mandor_id")
        worker.full_name = (request.form.get("full_name") or "").strip()
        worker.phone = (request.form.get("phone") or "").strip()
        worker.status = request.form.get("status") or "ACTIVE"
        worker.notes = (request.form.get("notes") or "").strip()

        if not worker.mandor_id or not worker.full_name:
            flash("Mandor dan nama pekerja wajib diisi.", "warning")
            return redirect(url_for("master.edit_worker", worker_id=worker.id))

        if not worker.worker_code:
            worker.worker_code = generate_worker_code()

        db.session.commit()

        flash("Pekerja berhasil diperbarui.", "success")
        return redirect(url_for("master.workers"))

    return render_template(
        "master/worker_form.html",
        mandors=mandors,
        worker=worker,
        statuses=WORKER_STATUSES
    )


@master_bp.route("/workers/<int:worker_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)

    if not worker.mandor or worker.mandor.branch_id != current_user.branch_id:
        flash("Data pekerja tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.workers"))

    if worker.status == "ACTIVE":
        worker.status = "LEFT"
    else:
        worker.status = "ACTIVE"

    db.session.commit()

    flash("Status pekerja berhasil diubah.", "success")
    return redirect(url_for("master.workers"))

@master_bp.route("/workers/<int:worker_id>/delete", methods=["POST"])
@role_required("ADMIN")
def delete_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)

    if not worker.mandor or worker.mandor.branch_id != current_user.branch_id:
        flash("Data pekerja tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.workers"))

    if worker_is_used(worker.id):
        flash("Pekerja sudah pernah digunakan pada transaksi hutang warung. Data tidak bisa dihapus, silakan nonaktifkan.", "warning")
        return redirect(url_for("master.workers"))

    db.session.delete(worker)
    db.session.commit()

    flash("Pekerja berhasil dihapus karena belum pernah digunakan transaksi.", "success")
    return redirect(url_for("master.workers"))

# =========================
# DRIVER
# =========================

@master_bp.route("/drivers")
@role_required("ADMIN")
def drivers():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ALL"

    query = Driver.query.filter_by(branch_id=current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                Driver.name.ilike(f"%{q}%"),
                Driver.phone.ilike(f"%{q}%"),
                Driver.license_number.ilike(f"%{q}%")
            )
        )

    if status == "ACTIVE":
        query = query.filter(Driver.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(Driver.is_active == False)

    drivers = query.order_by(Driver.name.asc()).all()

    return render_template(
        "master/drivers.html",
        drivers=drivers,
        q=q,
        status=status
    )


@master_bp.route("/drivers/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_driver():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        client_code = _clean_client_code(request.form.get("client_code")) or generate_client_code()
        phone = (request.form.get("phone") or "").strip()
        license_number = (request.form.get("license_number") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash("Nama driver wajib diisi.", "warning")
            return redirect(url_for("master.create_driver"))

        driver = Driver(
            branch_id=current_user.branch_id,
            name=name,
            phone=phone,
            license_number=license_number,
            is_active=is_active
        )

        db.session.add(driver)
        db.session.commit()

        flash("Driver berhasil ditambahkan.", "success")
        return redirect(url_for("master.drivers"))

    return render_template("master/driver_form.html", driver=None)


@master_bp.route("/drivers/<int:driver_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)

    if driver.branch_id != current_user.branch_id:
        flash("Data driver tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.drivers"))

    if request.method == "POST":
        driver.name = (request.form.get("name") or "").strip()
        driver.phone = (request.form.get("phone") or "").strip()
        driver.license_number = (request.form.get("license_number") or "").strip()
        driver.is_active = True if request.form.get("is_active") == "on" else False

        if not driver.name:
            flash("Nama driver wajib diisi.", "warning")
            return redirect(url_for("master.edit_driver", driver_id=driver.id))

        db.session.commit()

        flash("Driver berhasil diperbarui.", "success")
        return redirect(url_for("master.drivers"))

    return render_template("master/driver_form.html", driver=driver)


@master_bp.route("/drivers/<int:driver_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)

    if driver.branch_id != current_user.branch_id:
        flash("Data driver tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.drivers"))

    driver.is_active = not driver.is_active
    db.session.commit()

    flash("Status driver berhasil diubah.", "success")
    return redirect(url_for("master.drivers"))


# =========================
# ITEM
# =========================

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

        item = Item(
            item_code=generate_item_code(category),
            item_name=item_name,
            category=category,
            unit=unit,
            minimum_stock=minimum_stock,
            selling_price=selling_price,
            is_stock_tracked=is_stock_tracked,
            is_active=is_active
        )

        db.session.add(item)
        db.session.commit()

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

        item.item_name = (request.form.get("item_name") or "").strip()
        item.category = request.form.get("category")
        item.unit = (request.form.get("unit") or "").strip()
        item.minimum_stock = float(request.form.get("minimum_stock") or 0)
        item.selling_price = float(request.form.get("selling_price") or 0)
        item.is_stock_tracked = True if request.form.get("is_stock_tracked") == "on" else False
        item.is_active = True if request.form.get("is_active") == "on" else False

        if not item.item_name or not item.category or not item.unit:
            flash("Nama, kategori, dan satuan barang wajib diisi.", "warning")
            return redirect(url_for("master.edit_item", item_id=item.id))

        if not item.item_code:
            item.item_code = generate_item_code(item.category)

        db.session.commit()

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
    item.is_active = not item.is_active
    db.session.commit()

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
    db.session.delete(item)
    db.session.commit()

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

        if not profile:
            profile = ItemCostProfile(
                item_id=item.id,
                branch_id=current_user.branch_id,
                updated_by=current_user.id
            )
            db.session.add(profile)

        profile.purchase_unit = purchase_unit
        profile.purchase_qty = purchase_qty
        profile.base_unit = base_unit
        profile.conversion_factor = conversion_factor
        profile.yield_percentage = yield_percentage
        profile.waste_percentage = waste_percentage
        profile.standard_purchase_price = standard_purchase_price
        profile.effective_cost_per_base_unit = effective_cost
        profile.cost_source = cost_source
        profile.notes = notes
        profile.updated_by = current_user.id

        db.session.commit()
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

        if existing:
            existing.multiplier = multiplier
            existing.notes = notes
            existing.is_active = True
            flash("Konversi satuan sudah ada, datanya diperbarui.", "success")
        else:
            db.session.add(UnitConversion(
                branch_id=current_user.branch_id,
                unit_from=unit_from,
                unit_to=unit_to,
                multiplier=multiplier,
                notes=notes,
                created_by=current_user.id,
                is_active=True
            ))
            flash("Konversi satuan berhasil ditambahkan.", "success")

        db.session.commit()
        record_audit_log(
            module="HPP",
            event_type="UNIT_CONVERSION_SAVED",
            action="UPSERT",
            table_name="unit_conversions",
            record_id=(existing.id if existing else None),
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

    conversion.is_active = not conversion.is_active
    db.session.commit()

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


# =========================
# SUPPLIER
# =========================

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

        supplier = Supplier(
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

        db.session.add(supplier)
        db.session.commit()

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

        supplier.supplier_name = supplier_name
        supplier.supplier_type = supplier_type
        supplier.contact_person = contact_person
        supplier.phone = phone
        supplier.whatsapp = whatsapp
        supplier.address = address
        supplier.default_payment_terms_days = default_payment_terms_days
        supplier.bank_name = bank_name
        supplier.bank_account_number = bank_account_number
        supplier.bank_account_holder = bank_account_holder
        supplier.npwp = npwp
        supplier.notes = notes
        supplier.is_active = is_active

        db.session.commit()

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

    supplier.is_active = not supplier.is_active
    db.session.commit()

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

        account = BankAccount(
            branch_id=current_user.branch_id,
            account_name=account_name,
            bank_name=bank_name,
            account_number=account_number,
            is_active=is_active
        )

        db.session.add(account)
        db.session.commit()

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

        account.account_name = account_name
        account.bank_name = bank_name
        account.account_number = account_number
        account.is_active = is_active

        db.session.commit()

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

    account.is_active = not account.is_active
    db.session.commit()

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

        asset = FixedAsset(
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

        db.session.add(asset)
        db.session.commit()

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

        asset.asset_name = asset_name
        asset.asset_category = asset_category
        asset.purchase_date = purchase_date
        asset.purchase_value = purchase_value
        asset.useful_life_years = useful_life_years
        asset.residual_value = residual_value
        asset.accumulated_depreciation = accumulated_depreciation
        asset.book_value = calculate_asset_book_value(purchase_value, accumulated_depreciation)
        asset.status = status
        asset.notes = notes

        if not asset.asset_code:
            asset.asset_code = generate_asset_code()

        db.session.commit()

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

    asset.status = "INACTIVE" if asset.status == "ACTIVE" else "ACTIVE"
    db.session.commit()

    flash("Status aset tetap berhasil diubah.", "success")
    return redirect(url_for("master.fixed_assets"))



# === PATCH_CLIENT_PIC_UI_STEP12A2B ===
@master_bp.route("/clients/<int:client_id>/pics/create", methods=["POST"])
@role_required("OWNER")
def create_client_pic(client_id):
    from app.models.master import ClientPic

    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash("Data client tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    name = (request.form.get("pic_name") or "").strip()
    phone = (request.form.get("pic_phone") or "").strip()
    email = (request.form.get("pic_email") or "").strip()
    position = (request.form.get("pic_position") or "").strip()

    if not name:
        flash("Nama PIC wajib diisi.", "warning")
        return redirect(url_for("master.edit_client", client_id=client.id))

    pic = ClientPic(
        client_id=client.id,
        name=name,
        phone=phone,
        email=email if hasattr(ClientPic, "email") else None,
        position=position,
        is_active=True
    )

    db.session.add(pic)
    db.session.commit()

    flash("PIC client berhasil ditambahkan.", "success")
    return redirect(url_for("master.edit_client", client_id=client.id))


@master_bp.route("/clients/<int:client_id>/pics/<int:pic_id>/toggle", methods=["POST"])
@role_required("OWNER")
def toggle_client_pic(client_id, pic_id):
    from app.models.master import ClientPic

    client = Client.query.get_or_404(client_id)

    if hasattr(Client, "branch_id") and client.branch_id != current_user.branch_id:
        flash("Data client tidak sesuai cabang user.", "danger")
        return redirect(url_for("master.clients"))

    pic = ClientPic.query.get_or_404(pic_id)

    if pic.client_id != client.id:
        flash("PIC tidak sesuai dengan client.", "danger")
        return redirect(url_for("master.edit_client", client_id=client.id))

    pic.is_active = not bool(pic.is_active)
    db.session.commit()

    flash("Status PIC client berhasil diubah.", "success")
    return redirect(url_for("master.edit_client", client_id=client.id))

