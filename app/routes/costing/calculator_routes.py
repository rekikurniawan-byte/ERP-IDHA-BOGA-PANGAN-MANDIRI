"""Costing HPP calculator routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.costing_routes import *  # noqa: F401,F403


@costing_bp.route("/hpp-calculator")
@role_required("ADMIN")
def hpp_calculator():
    menu_id = request.args.get("menu_id")
    packaging_profile_id = request.args.get("packaging_profile_id")
    overhead_profile_id = request.args.get("overhead_profile_id")
    portion_qty = to_float(request.args.get("portion_qty") or 0)
    target_margin_percentage = to_float(request.args.get("target_margin_percentage") or 30)
    selling_price_raw = (request.args.get("selling_price_per_portion") or "").strip()

    menus = Menu.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Menu.menu_name.asc()).all()
    packaging_profiles = PackagingProfile.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(PackagingProfile.profile_name.asc()).all()
    overhead_profiles = OverheadProfile.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(OverheadProfile.profile_name.asc()).all()

    selected_menu = None
    selected_packaging_profile = None
    selected_overhead_profile = None
    result = None

    if menu_id:
        selected_menu = Menu.query.filter_by(
            id=menu_id,
            branch_id=current_user.branch_id,
        ).first()

        if not selected_menu:
            flash("Menu tidak ditemukan atau tidak sesuai cabang user.", "warning")
            return redirect(url_for("costing.hpp_calculator"))

        if portion_qty <= 0:
            portion_qty = 1

        if packaging_profile_id:
            selected_packaging_profile = PackagingProfile.query.filter_by(
                id=packaging_profile_id,
                branch_id=current_user.branch_id,
                is_active=True,
            ).first()
            if not selected_packaging_profile:
                flash("Profil kemasan tidak ditemukan atau tidak aktif.", "warning")
                return redirect(url_for("costing.hpp_calculator"))

        if overhead_profile_id:
            selected_overhead_profile = OverheadProfile.query.filter_by(
                id=overhead_profile_id,
                branch_id=current_user.branch_id,
                is_active=True,
            ).first()
            if not selected_overhead_profile:
                flash("Profil overhead tidak ditemukan atau tidak aktif.", "warning")
                return redirect(url_for("costing.hpp_calculator"))

        selling_price = None if selling_price_raw == "" else to_float(selling_price_raw)
        result = calculate_menu_hpp(
            selected_menu,
            portion_qty=portion_qty,
            selling_price_per_portion=selling_price,
            target_margin_percentage=target_margin_percentage,
            packaging_profile=selected_packaging_profile,
            overhead_profile=selected_overhead_profile,
        )

    return render_template(
        "costing/hpp_calculator.html",
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
        selected_menu=selected_menu,
        selected_packaging_profile=selected_packaging_profile,
        selected_overhead_profile=selected_overhead_profile,
        portion_qty=portion_qty,
        selling_price_raw=selling_price_raw,
        target_margin_percentage=target_margin_percentage,
        result=result,
    )
