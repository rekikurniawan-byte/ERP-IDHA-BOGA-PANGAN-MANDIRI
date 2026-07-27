"""Mandor, location, worker, and driver master routes.

Route functions moved out of app.routes.master_routes without changing URL rules or endpoint names.
"""
from app.routes.master_routes import *  # noqa: F401,F403


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
        create_mandor_record(
            branch_id=current_user.branch_id,
            client_id=client_id,
            name=name,
            phone=phone,
            is_active=is_active,
        )

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
        client_id = request.form.get("client_id") or None
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash("Nama mandor wajib diisi.", "warning")
            return redirect(url_for("master.edit_mandor", mandor_id=mandor.id))

        if mandor_name_is_used(name, current_user.branch_id, exclude_id=mandor.id):
            flash("Nama mandor sudah digunakan oleh data lain. Perubahan tidak disimpan.", "warning")
            return redirect(url_for("master.edit_mandor", mandor_id=mandor.id))

        update_mandor_record(
            mandor,
            client_id=client_id,
            name=name,
            phone=phone,
            is_active=is_active,
        )

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

    toggle_mandor_active(mandor)

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

        try:
            create_location_record(
                mandor_id=mandor_id,
                location_name=location_name,
                description=description,
                is_active=is_active,
            )
        except IntegrityError:
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
        mandor_id = request.form.get("mandor_id")
        location_name = (request.form.get("location_name") or "").strip()
        description = (request.form.get("description") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not mandor_id or not location_name:
            flash("Mandor dan nama lokasi wajib diisi.", "warning")
            return redirect(url_for("master.edit_location", location_id=location.id))

        try:
            update_location_record(
                location,
                mandor_id=mandor_id,
                location_name=location_name,
                description=description,
                is_active=is_active,
            )
        except IntegrityError:
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

    toggle_location_active(location)

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

        worker = create_worker_record(
            mandor_id=mandor_id,
            worker_code=generate_worker_code(),
            full_name=full_name,
            phone=phone,
            status=status,
            notes=notes,
        )

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
        mandor_id = request.form.get("mandor_id")
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        status = request.form.get("status") or "ACTIVE"
        notes = (request.form.get("notes") or "").strip()

        if not mandor_id or not full_name:
            flash("Mandor dan nama pekerja wajib diisi.", "warning")
            return redirect(url_for("master.edit_worker", worker_id=worker.id))

        update_worker_record(
            worker,
            mandor_id=mandor_id,
            worker_code=generate_worker_code(),
            full_name=full_name,
            phone=phone,
            status=status,
            notes=notes,
        )

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

    toggle_worker_status(worker)

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

    delete_worker_record(worker)

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

        create_driver_record(
            branch_id=current_user.branch_id,
            name=name,
            phone=phone,
            license_number=license_number,
            is_active=is_active,
        )

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
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        license_number = (request.form.get("license_number") or "").strip()
        is_active = True if request.form.get("is_active") == "on" else False

        if not name:
            flash("Nama driver wajib diisi.", "warning")
            return redirect(url_for("master.edit_driver", driver_id=driver.id))

        update_driver_record(
            driver,
            name=name,
            phone=phone,
            license_number=license_number,
            is_active=is_active,
        )

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

    toggle_driver_active(driver)

    flash("Status driver berhasil diubah.", "success")
    return redirect(url_for("master.drivers"))
