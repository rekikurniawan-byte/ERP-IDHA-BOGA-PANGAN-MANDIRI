"""Costing packaging and overhead profile routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.costing_routes import *  # noqa: F401,F403


@costing_bp.route("/packaging-profiles")
@role_required("ADMIN")
def packaging_profiles():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ACTIVE"

    query = PackagingProfile.query.filter(PackagingProfile.branch_id == current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                PackagingProfile.profile_code.ilike(f"%{q}%"),
                PackagingProfile.profile_name.ilike(f"%{q}%"),
                PackagingProfile.notes.ilike(f"%{q}%"),
            )
        )

    if status == "ACTIVE":
        query = query.filter(PackagingProfile.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(PackagingProfile.is_active == False)

    profiles = query.order_by(PackagingProfile.profile_name.asc()).all()
    active_count = PackagingProfile.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()

    return render_template(
        "costing/packaging_profiles.html",
        profiles=profiles,
        q=q,
        status=status,
        active_count=active_count,
    )


@costing_bp.route("/packaging-profiles/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_packaging_profile():
    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        cost_per_portion = to_float(request.form.get("cost_per_portion"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        if not profile_name:
            flash("Nama profil kemasan wajib diisi.", "warning")
            return redirect(url_for("costing.create_packaging_profile"))

        if cost_per_portion < 0:
            flash("Biaya kemasan per porsi tidak boleh minus.", "warning")
            return redirect(url_for("costing.create_packaging_profile"))

        if packaging_profile_name_is_used(profile_name, current_user.branch_id):
            flash("Nama profil kemasan sudah ada di cabang ini.", "warning")
            return redirect(url_for("costing.create_packaging_profile"))

        create_packaging_profile_record(
            branch_id=current_user.branch_id,
            profile_code=generate_packaging_profile_code(),
            profile_name=profile_name,
            cost_per_portion=cost_per_portion,
            notes=notes,
            is_active=is_active,
            updated_by=current_user.id,
        )

        flash("Profil kemasan berhasil dibuat. Data ini belum memotong stok dan belum masuk jurnal.", "success")
        return redirect(url_for("costing.packaging_profiles"))

    return render_template("costing/packaging_profile_form.html", profile=None)


@costing_bp.route("/packaging-profiles/<int:profile_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_packaging_profile(profile_id):
    profile = PackagingProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil kemasan tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.packaging_profiles"))

    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        cost_per_portion = to_float(request.form.get("cost_per_portion"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        if not profile_name:
            flash("Nama profil kemasan wajib diisi.", "warning")
            return redirect(url_for("costing.edit_packaging_profile", profile_id=profile.id))

        if cost_per_portion < 0:
            flash("Biaya kemasan per porsi tidak boleh minus.", "warning")
            return redirect(url_for("costing.edit_packaging_profile", profile_id=profile.id))

        if packaging_profile_name_is_used(profile_name, current_user.branch_id, exclude_id=profile.id):
            flash("Nama profil kemasan sudah digunakan data lain.", "warning")
            return redirect(url_for("costing.edit_packaging_profile", profile_id=profile.id))

        update_packaging_profile_record(
            profile,
            profile_name=profile_name,
            cost_per_portion=cost_per_portion,
            notes=notes,
            is_active=is_active,
            updated_by=current_user.id,
        )

        record_audit_log(module="HPP", event_type="PACKAGING_PROFILE_UPDATED", action="UPDATE", table_name="packaging_profiles", record_id=profile.id, description=f"Profil kemasan diperbarui: {profile.profile_name}.")
        flash("Profil kemasan berhasil diperbarui.", "success")
        return redirect(url_for("costing.packaging_profiles"))

    return render_template("costing/packaging_profile_form.html", profile=profile)


@costing_bp.route("/packaging-profiles/<int:profile_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_packaging_profile(profile_id):
    profile = PackagingProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil kemasan tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.packaging_profiles"))

    toggle_packaging_profile_active(profile, updated_by=current_user.id)
    record_audit_log(module="HPP", event_type="PACKAGING_PROFILE_TOGGLED", action="UPDATE", table_name="packaging_profiles", record_id=profile.id, description=f"Status profil kemasan diubah: {profile.profile_name}.", new_value={"is_active": profile.is_active})
    flash("Status profil kemasan berhasil diubah.", "success")
    return redirect(url_for("costing.packaging_profiles"))


@costing_bp.route("/overhead-profiles")
@role_required("ADMIN")
def overhead_profiles():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "ACTIVE"

    query = OverheadProfile.query.filter(OverheadProfile.branch_id == current_user.branch_id)

    if q:
        query = query.filter(
            or_(
                OverheadProfile.profile_code.ilike(f"%{q}%"),
                OverheadProfile.profile_name.ilike(f"%{q}%"),
                OverheadProfile.notes.ilike(f"%{q}%"),
            )
        )

    if status == "ACTIVE":
        query = query.filter(OverheadProfile.is_active == True)
    elif status == "INACTIVE":
        query = query.filter(OverheadProfile.is_active == False)

    profiles = query.order_by(OverheadProfile.profile_name.asc()).all()
    active_count = OverheadProfile.query.filter_by(branch_id=current_user.branch_id, is_active=True).count()

    return render_template(
        "costing/overhead_profiles.html",
        profiles=profiles,
        q=q,
        status=status,
        active_count=active_count,
    )


@costing_bp.route("/overhead-profiles/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_overhead_profile():
    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        gas_cost_per_portion = to_float(request.form.get("gas_cost_per_portion"))
        electricity_cost_per_portion = to_float(request.form.get("electricity_cost_per_portion"))
        water_cost_per_portion = to_float(request.form.get("water_cost_per_portion"))
        labor_cost_per_portion = to_float(request.form.get("labor_cost_per_portion"))
        spices_cost_per_portion = to_float(request.form.get("spices_cost_per_portion"))
        other_cost_per_portion = to_float(request.form.get("other_cost_per_portion"))
        overhead_percentage = to_float(request.form.get("overhead_percentage"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        costs = [gas_cost_per_portion, electricity_cost_per_portion, water_cost_per_portion, labor_cost_per_portion, spices_cost_per_portion, other_cost_per_portion, overhead_percentage]
        if not profile_name:
            flash("Nama profil overhead wajib diisi.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        if any(value < 0 for value in costs):
            flash("Biaya overhead dan persentase tidak boleh minus.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        if overhead_percentage >= 100:
            flash("Overhead persentase harus di bawah 100%.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        if overhead_profile_name_is_used(profile_name, current_user.branch_id):
            flash("Nama profil overhead sudah ada di cabang ini.", "warning")
            return redirect(url_for("costing.create_overhead_profile"))

        create_overhead_profile_record(
            branch_id=current_user.branch_id,
            profile_code=generate_overhead_profile_code(),
            profile_name=profile_name,
            gas_cost_per_portion=gas_cost_per_portion,
            electricity_cost_per_portion=electricity_cost_per_portion,
            water_cost_per_portion=water_cost_per_portion,
            labor_cost_per_portion=labor_cost_per_portion,
            spices_cost_per_portion=spices_cost_per_portion,
            other_cost_per_portion=other_cost_per_portion,
            overhead_percentage=overhead_percentage,
            notes=notes,
            is_active=is_active,
            updated_by=current_user.id,
        )

        flash("Profil overhead berhasil dibuat. Data ini masih read-only untuk kalkulator HPP.", "success")
        return redirect(url_for("costing.overhead_profiles"))

    return render_template("costing/overhead_profile_form.html", profile=None)


@costing_bp.route("/overhead-profiles/<int:profile_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN")
def edit_overhead_profile(profile_id):
    profile = OverheadProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil overhead tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.overhead_profiles"))

    if request.method == "POST":
        profile_name = (request.form.get("profile_name") or "").strip()
        gas_cost_per_portion = to_float(request.form.get("gas_cost_per_portion"))
        electricity_cost_per_portion = to_float(request.form.get("electricity_cost_per_portion"))
        water_cost_per_portion = to_float(request.form.get("water_cost_per_portion"))
        labor_cost_per_portion = to_float(request.form.get("labor_cost_per_portion"))
        spices_cost_per_portion = to_float(request.form.get("spices_cost_per_portion"))
        other_cost_per_portion = to_float(request.form.get("other_cost_per_portion"))
        overhead_percentage = to_float(request.form.get("overhead_percentage"))
        notes = (request.form.get("notes") or "").strip() or None
        is_active = True if request.form.get("is_active") == "on" else False

        costs = [gas_cost_per_portion, electricity_cost_per_portion, water_cost_per_portion, labor_cost_per_portion, spices_cost_per_portion, other_cost_per_portion, overhead_percentage]
        if not profile_name:
            flash("Nama profil overhead wajib diisi.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        if any(value < 0 for value in costs):
            flash("Biaya overhead dan persentase tidak boleh minus.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        if overhead_percentage >= 100:
            flash("Overhead persentase harus di bawah 100%.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        if overhead_profile_name_is_used(profile_name, current_user.branch_id, exclude_id=profile.id):
            flash("Nama profil overhead sudah digunakan data lain.", "warning")
            return redirect(url_for("costing.edit_overhead_profile", profile_id=profile.id))

        update_overhead_profile_record(
            profile,
            profile_name=profile_name,
            gas_cost_per_portion=gas_cost_per_portion,
            electricity_cost_per_portion=electricity_cost_per_portion,
            water_cost_per_portion=water_cost_per_portion,
            labor_cost_per_portion=labor_cost_per_portion,
            spices_cost_per_portion=spices_cost_per_portion,
            other_cost_per_portion=other_cost_per_portion,
            overhead_percentage=overhead_percentage,
            notes=notes,
            is_active=is_active,
            updated_by=current_user.id,
        )

        record_audit_log(module="HPP", event_type="OVERHEAD_PROFILE_UPDATED", action="UPDATE", table_name="overhead_profiles", record_id=profile.id, description=f"Profil overhead diperbarui: {profile.profile_name}.")
        flash("Profil overhead berhasil diperbarui.", "success")
        return redirect(url_for("costing.overhead_profiles"))

    return render_template("costing/overhead_profile_form.html", profile=profile)


@costing_bp.route("/overhead-profiles/<int:profile_id>/toggle", methods=["POST"])
@role_required("ADMIN")
def toggle_overhead_profile(profile_id):
    profile = OverheadProfile.query.get_or_404(profile_id)
    if profile.branch_id != current_user.branch_id:
        flash("Profil overhead tidak sesuai cabang user.", "danger")
        return redirect(url_for("costing.overhead_profiles"))

    toggle_overhead_profile_active(profile, updated_by=current_user.id)
    record_audit_log(module="HPP", event_type="OVERHEAD_PROFILE_TOGGLED", action="UPDATE", table_name="overhead_profiles", record_id=profile.id, description=f"Status profil overhead diubah: {profile.profile_name}.", new_value={"is_active": profile.is_active})
    flash("Status profil overhead berhasil diubah.", "success")
    return redirect(url_for("costing.overhead_profiles"))
