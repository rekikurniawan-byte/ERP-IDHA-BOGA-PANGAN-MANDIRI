from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from app.utils.decorators import role_required
from app.services.audit_log_service import record_audit_log

from app.models.operational import DailyOrder, DailyOrderDetail, OrderHppSnapshot, OrderHppStockConsumption
from app.models.master import Mandor, DeliveryLocation
from app.services.operational_service import (
    get_or_create_daily_order,
    add_or_update_order_detail,
    add_increase_after_lock,
    lock_daily_order,
    revise_order_detail,
    update_order_hpp_defaults,
)

from app.services.production_service import generate_production_from_order
from app.services.delivery_service import (
    get_delivery_summary_for_order,
    get_delivery_next_actions_for_order,
    get_ready_delivery_next_actions_for_order,
)

from app.services.order_hpp_snapshot_service import (
    create_order_hpp_snapshot,
    get_active_hpp_master_data,
    get_order_meal_summary,
)
from app.services.hpp_stock_consumption_service import (
    build_hpp_stock_consumption_dry_run,
    commit_hpp_stock_consumption,
    get_existing_stock_consumption,
)
from app.services.catering_report_service import (
    build_daily_catering_log,
    build_monthly_catering_recap,
    get_active_mandors,
    parse_date,
    parse_month,
)
from app.services.global_filter_service import (
    build_filter_bar_context,
    resolve_date_filter,
)
from app.utils.terms import T


operational_bp = Blueprint("operational", __name__, url_prefix="/operational")


def _is_active_record(record):
    """
    Filter aman untuk master data aktif.
    Support beberapa kemungkinan field:
    - is_active = True/False
    - status = ACTIVE/INACTIVE
    """
    if hasattr(record, "is_active"):
        return bool(record.is_active)

    if hasattr(record, "status"):
        return str(record.status).upper() in ["ACTIVE", "AKTIF"]

    return True


def _belongs_to_user_branch(record):
    """
    Filter aman untuk cabang.
    Beberapa tabel punya branch_id langsung.
    DeliveryLocation tidak punya branch_id, jadi dicek lewat mandor.branch_id.
    """
    user_branch_id = current_user.branch_id

    if hasattr(record, "branch_id"):
        return record.branch_id == user_branch_id

    if hasattr(record, "mandor") and record.mandor:
        if hasattr(record.mandor, "branch_id"):
            return record.mandor.branch_id == user_branch_id

    if hasattr(record, "mandor_id") and record.mandor_id:
        mandor = Mandor.query.get(record.mandor_id)
        if mandor and hasattr(mandor, "branch_id"):
            return mandor.branch_id == user_branch_id

    return True


def get_form_master_data():
    mandors = [
        mandor for mandor in Mandor.query.order_by(Mandor.name.asc()).all()
        if _is_active_record(mandor) and _belongs_to_user_branch(mandor)
    ]

    locations = [
        location for location in DeliveryLocation.query.order_by(DeliveryLocation.location_name.asc()).all()
        if _is_active_record(location) and _belongs_to_user_branch(location)
    ]

    return mandors, locations


def validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
    location = DeliveryLocation.query.get(delivery_location_id)

    if not location:
        return False

    return location.mandor_id == mandor_id




# === PRODUCTION_LOG_CATERING_REKAP_BULANAN_READONLY ===
@operational_bp.route("/daily-log")
@role_required("ADMIN", "FINANCE")
def daily_catering_log():
    today = date.today()
    selected_date_value = request.args.get("date", today.strftime("%Y-%m-%d")).strip()
    selected_date = parse_date(selected_date_value, today)

    if selected_date_value and selected_date_value != selected_date.strftime("%Y-%m-%d"):
        flash("Tanggal log catering tidak valid. Sistem menampilkan tanggal hari ini.", "warning")
        selected_date_value = selected_date.strftime("%Y-%m-%d")

    report = build_daily_catering_log(
        branch_id=current_user.branch_id,
        target_date=selected_date,
    )

    return render_template(
        "operational/daily_log.html",
        report=report,
        selected_date=selected_date,
        selected_date_value=selected_date.strftime("%Y-%m-%d"),
    )


@operational_bp.route("/monthly-recap")
@role_required("ADMIN", "FINANCE")
def monthly_catering_recap():
    today = date.today()
    selected_mandor_id = request.args.get("mandor_id", "").strip()

    # Backward compatibility: if an old ?month=YYYY-MM URL is opened,
    # translate it into the new custom date range once, then keep the
    # Global Filter Bar V2 contract as the visible UI.
    legacy_month_value = request.args.get("month", "").strip()
    mutable_args = request.args.copy()
    if legacy_month_value and not mutable_args.get("start_date") and not mutable_args.get("end_date"):
        legacy_year, legacy_month = parse_month(legacy_month_value, today)
        legacy_start, legacy_end = date(legacy_year, legacy_month, 1), date(legacy_year, legacy_month, 1)
        from calendar import monthrange
        legacy_end = date(legacy_year, legacy_month, monthrange(legacy_year, legacy_month)[1])
        mutable_args["period_preset"] = "custom"
        mutable_args["start_date"] = legacy_start.isoformat()
        mutable_args["end_date"] = legacy_end.isoformat()

    date_filter = resolve_date_filter(
        mutable_args,
        start_key="start_date",
        end_key="end_date",
        preset_key="period_preset",
        default_preset="this_month",
        today=today,
    )

    range_anchor = date_filter.start_date or today
    year, month = range_anchor.year, range_anchor.month

    mandor_id = None
    if selected_mandor_id:
        try:
            mandor_id = int(selected_mandor_id)
        except (TypeError, ValueError):
            mandor_id = None
            selected_mandor_id = ""
            flash(f"Filter {T.sub_client_lower} tidak valid. Filter {T.sub_client_lower} diabaikan.", "warning")

    mandors = get_active_mandors(current_user.branch_id)
    if mandor_id and all(int(mandor.id) != mandor_id for mandor in mandors):
        flash(f"{T.sub_client}/PIC lapangan tidak sesuai cabang user. Filter {T.sub_client_lower} diabaikan.", "warning")
        mandor_id = None
        selected_mandor_id = ""

    report = build_monthly_catering_recap(
        branch_id=current_user.branch_id,
        year=year,
        month=month,
        mandor_id=mandor_id,
        start_date=date_filter.start_date,
        end_date=date_filter.end_date,
    )

    mandor_options = [{"value": "", "label": f"Semua {T.sub_client_lower}"}] + [
        {"value": str(mandor.id), "label": mandor.name}
        for mandor in mandors
    ]
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("operational.monthly_catering_recap"),
        reset_url=url_for("operational.monthly_catering_recap"),
        title="Filter Rekap Catering",
        description=f"Pilih preset atau tanggal custom untuk rekap catering, lalu filter {T.sub_client_lower}/PIC jika dibutuhkan.",
        preset_name="period_preset",
        start_name="start_date",
        end_name="end_date",
        extra_selects=[{
            "name": "mandor_id",
            "label": f"{T.sub_client} / PIC",
            "value": str(mandor_id or ""),
            "options": mandor_options,
        }],
    )

    return render_template(
        "operational/monthly_recap.html",
        report=report,
        mandors=mandors,
        selected_mandor_id=str(mandor_id or ""),
        month_value=report["month_value"],
        filter_bar=filter_bar,
    )

@operational_bp.route("/orders")
@role_required("ADMIN")
def orders():
    daily_orders = DailyOrder.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(DailyOrder.order_date.desc(), DailyOrder.id.desc()).all()

    return render_template("operational/orders.html", daily_orders=daily_orders)


@operational_bp.route("/orders/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_order():
    mandors, locations = get_form_master_data()
    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)

    if request.method == "POST":
        order_date = datetime.strptime(request.form.get("order_date"), "%Y-%m-%d").date()
        mandor_id = int(request.form.get("mandor_id"))
        delivery_location_id = int(request.form.get("delivery_location_id"))
        price_per_portion = float(request.form.get("price_per_portion") or 0)
        lunch_qty = int(request.form.get("lunch_qty") or 0)
        dinner_qty = int(request.form.get("dinner_qty") or 0)
        notes = request.form.get("notes")

        if not validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
            flash(f"{T.location} tidak sesuai dengan {T.sub_client_lower} yang dipilih.", "warning")
            return redirect(url_for("operational.create_order"))

        daily_order = get_or_create_daily_order(
            branch_id=current_user.branch_id,
            order_date=order_date,
            created_by=current_user.id,
            notes=notes
        )

        if daily_order.is_locked:
            flash(
                "Order untuk tanggal ini sudah LOCKED. Gunakan tombol Tambah Revisi Setelah Lock dari halaman Kelola Order.",
                "warning"
            )
            return redirect(url_for("operational.order_detail", order_id=daily_order.id))

        defaults_success, defaults_message = update_order_hpp_defaults(daily_order, request.form)
        if not defaults_success:
            flash(defaults_message, "warning")
            return redirect(url_for("operational.create_order"))

        success, message, detail = add_or_update_order_detail(
            daily_order=daily_order,
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
            price_per_portion=price_per_portion,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            notes=notes,
            actor_role=current_user.role,
        )

        flash(message, "success" if success else "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_form.html",
        mandors=mandors,
        locations=locations,
        daily_order=None,
        form_action=url_for("operational.create_order"),
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
        show_hpp_defaults=True,
    )

@operational_bp.route("/orders/<int:order_id>/add-detail", methods=["GET", "POST"])
@role_required("ADMIN")
def add_order_detail(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if daily_order.is_locked:
        flash(f"Order sudah LOCKED. Tambah lokasi/{T.sub_client_lower} biasa tidak bisa dilakukan. Gunakan revisi tambah jika diperlukan.", "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    mandors, locations = get_form_master_data()

    if request.method == "POST":
        mandor_id = int(request.form.get("mandor_id"))
        delivery_location_id = int(request.form.get("delivery_location_id"))
        price_per_portion = float(request.form.get("price_per_portion") or 0)
        lunch_qty = int(request.form.get("lunch_qty") or 0)
        dinner_qty = int(request.form.get("dinner_qty") or 0)
        notes = request.form.get("notes")

        if not validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
            flash(f"{T.location} tidak sesuai dengan {T.sub_client_lower} yang dipilih.", "warning")
            return redirect(url_for("operational.add_order_detail", order_id=daily_order.id))

        success, message, detail = add_or_update_order_detail(
            daily_order=daily_order,
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
            price_per_portion=price_per_portion,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            notes=notes,
            actor_role=current_user.role,
        )

        flash(message, "success" if success else "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_form.html",
        mandors=mandors,
        locations=locations,
        daily_order=daily_order,
        form_action=url_for("operational.add_order_detail", order_id=daily_order.id)
    )


@operational_bp.route("/orders/<int:order_id>/add-increase-after-lock", methods=["GET", "POST"])
@role_required("ADMIN")
def add_increase_after_lock_route(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if not daily_order.is_locked:
        flash(f"Order belum LOCKED. Gunakan tambah lokasi/{T.sub_client_lower} biasa.", "warning")
        return redirect(url_for("operational.add_order_detail", order_id=daily_order.id))

    mandors, locations = get_form_master_data()

    if request.method == "POST":
        mandor_id = int(request.form.get("mandor_id"))
        delivery_location_id = int(request.form.get("delivery_location_id"))
        price_per_portion = float(request.form.get("price_per_portion") or 0)
        lunch_qty = int(request.form.get("lunch_qty") or 0)
        dinner_qty = int(request.form.get("dinner_qty") or 0)
        notes = request.form.get("notes") or "Penambahan order setelah lock"

        if not validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
            flash(f"{T.location} tidak sesuai dengan {T.sub_client_lower} yang dipilih.", "warning")
            return redirect(url_for("operational.add_increase_after_lock_route", order_id=daily_order.id))

        success, message, detail = add_increase_after_lock(
            daily_order=daily_order,
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
            price_per_portion=price_per_portion,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            reason=notes,
            created_by=current_user.id,
            actor_role=current_user.role,
        )

        if success:
            production_success, production_message = generate_production_from_order(
                daily_order,
                current_user.id
            )

            if production_success:
                flash("Revisi tambah setelah lock berhasil disimpan dan produksi otomatis disinkronkan.", "success")
            else:
                flash(f"Revisi tambah tersimpan, tetapi produksi belum tersinkron: {production_message}", "warning")
        else:
            flash(message, "warning")

        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_form.html",
        mandors=mandors,
        locations=locations,
        daily_order=daily_order,
        form_action=url_for("operational.add_increase_after_lock_route", order_id=daily_order.id),
        is_after_lock=True
    )

@operational_bp.route("/orders/<int:order_id>")
@role_required("ADMIN")
def order_detail(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    total_lunch = sum(detail.lunch_qty for detail in daily_order.details)
    total_dinner = sum(detail.dinner_qty for detail in daily_order.details)
    total_locations = len(daily_order.details)
    unique_mandors = len(set(detail.mandor_id for detail in daily_order.details))

    lunch_delivery_data = get_delivery_summary_for_order(
        daily_order=daily_order,
        delivery_type="LUNCH"
    )

    dinner_delivery_data = get_delivery_summary_for_order(
        daily_order=daily_order,
        delivery_type="DINNER"
    )

    hpp_snapshots = OrderHppSnapshot.query.filter_by(
        daily_order_id=daily_order.id,
        branch_id=current_user.branch_id,
    ).order_by(OrderHppSnapshot.id.desc()).all()

    latest_hpp_snapshot = hpp_snapshots[0] if hpp_snapshots else None

    delivery_next_actions = get_delivery_next_actions_for_order(daily_order)
    delivery_ready_actions = get_ready_delivery_next_actions_for_order(daily_order)

    return render_template(
        "operational/order_detail.html",
        daily_order=daily_order,
        total_lunch=total_lunch,
        total_dinner=total_dinner,
        total_locations=total_locations,
        unique_mandors=unique_mandors,
        lunch_delivery_data=lunch_delivery_data,
        dinner_delivery_data=dinner_delivery_data,
        delivery_next_actions=delivery_next_actions,
        delivery_ready_actions=delivery_ready_actions,
        hpp_snapshots=hpp_snapshots,
        latest_hpp_snapshot=latest_hpp_snapshot,
    )


@operational_bp.route("/orders/<int:order_id>/hpp-defaults", methods=["GET", "POST"])
@role_required("ADMIN")
def update_order_hpp_defaults_route(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)

    if request.method == "POST":
        success, message = update_order_hpp_defaults(daily_order, request.form)
        if success:
            record_audit_log(
                module="HPP",
                event_type="ORDER_HPP_DEFAULT_UPDATED",
                action="UPDATE",
                table_name="daily_orders",
                record_id=daily_order.id,
                description=f"Default menu/profil HPP order diperbarui: {daily_order.order_number}.",
            )
        flash(message, "success" if success else "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_hpp_defaults_form.html",
        daily_order=daily_order,
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
    )


@operational_bp.route("/orders/<int:order_id>/lock", methods=["POST"])
@role_required("ADMIN")
def lock_order(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    success, message = lock_daily_order(daily_order, current_user.id)

    if not success:
        flash(message, "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    production_success, production_message = generate_production_from_order(
        daily_order,
        current_user.id
    )

    record_audit_log(
        module="OPERATIONAL",
        event_type="ORDER_LOCKED",
        action="UPDATE",
        table_name="daily_orders",
        record_id=daily_order.id,
        description=f"Order di-lock: {daily_order.order_number}.",
        metadata={"production_created": production_success},
    )

    if production_success:
        flash("Order berhasil di-lock dan produksi otomatis dibuat.", "success")
    else:
        flash(f"Order berhasil di-lock, tetapi produksi belum dibuat: {production_message}", "warning")

    return redirect(url_for("operational.order_detail", order_id=daily_order.id))


@operational_bp.route("/orders/<int:order_id>/generate-production", methods=["POST"])
@role_required("ADMIN")
def generate_production(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    success, message = generate_production_from_order(daily_order, current_user.id)

    flash(message, "success" if success else "warning")
    return redirect(url_for("production.index"))


@operational_bp.route("/order-details/<int:detail_id>/revision", methods=["GET", "POST"])
@role_required("ADMIN")
def create_revision(detail_id):
    detail = DailyOrderDetail.query.get_or_404(detail_id)
    daily_order = detail.daily_order

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if request.method == "POST":
        revision_type = request.form.get("revision_type")
        revision_direction = request.form.get("revision_direction")
        lunch_qty_change = request.form.get("lunch_qty_change")
        dinner_qty_change = request.form.get("dinner_qty_change")
        reason = request.form.get("reason")

        success, message = revise_order_detail(
            detail=detail,
            revision_type=revision_type,
            revision_direction=revision_direction,
            lunch_qty_change=lunch_qty_change,
            dinner_qty_change=dinner_qty_change,
            reason=reason,
            created_by=current_user.id
        )

        if success and daily_order.is_locked:
            production_success, production_message = generate_production_from_order(
                daily_order,
                current_user.id
            )

            if production_success:
                flash("Revisi berhasil disimpan dan produksi otomatis disinkronkan.", "success")
            else:
                flash(f"Revisi berhasil disimpan, tetapi produksi belum tersinkron: {production_message}", "warning")
        else:
            flash(message, "success" if success else "warning")

        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/revision_form.html",
        detail=detail,
        daily_order=daily_order
    )



@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_order_hpp_snapshot_route(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if not daily_order.is_locked:
        flash("Snapshot HPP hanya bisa dibuat setelah order LOCKED.", "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)
    meal_summary = get_order_meal_summary(daily_order)

    if request.method == "POST":
        success, message, snapshot = create_order_hpp_snapshot(
            daily_order=daily_order,
            form_data=request.form,
            created_by=current_user.id,
        )

        flash(message, "success" if success else "warning")
        if success and snapshot:
            record_audit_log(
                module="HPP",
                event_type="HPP_SNAPSHOT_CREATED",
                action="CREATE",
                table_name="order_hpp_snapshots",
                record_id=snapshot.id,
                description=f"Snapshot HPP dibuat untuk order {daily_order.order_number}.",
                metadata={"snapshot_number": snapshot.snapshot_number, "hpp_total": snapshot.hpp_total},
            )
            return redirect(url_for("operational.order_hpp_snapshot_detail", order_id=daily_order.id, snapshot_id=snapshot.id))

        return redirect(url_for("operational.create_order_hpp_snapshot_route", order_id=daily_order.id))

    return render_template(
        "operational/order_hpp_snapshot_form.html",
        daily_order=daily_order,
        meal_summary=meal_summary,
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
    )


@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>")
@role_required("ADMIN")
def order_hpp_snapshot_detail(order_id, snapshot_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_hpp_snapshot_detail.html",
        daily_order=daily_order,
        snapshot=snapshot,
    )

@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-dry-run")
@role_required("ADMIN")
def order_hpp_snapshot_stock_dry_run(order_id, snapshot_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    dry_run = build_hpp_stock_consumption_dry_run(snapshot)
    existing_consumption = get_existing_stock_consumption(snapshot.id)

    return render_template(
        "operational/order_hpp_stock_dry_run.html",
        daily_order=daily_order,
        snapshot=snapshot,
        dry_run=dry_run,
        existing_consumption=existing_consumption,
    )


@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-commit", methods=["POST"])
@role_required("ADMIN")
def order_hpp_snapshot_stock_commit(order_id, snapshot_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    success, message, consumption = commit_hpp_stock_consumption(
        snapshot=snapshot,
        committed_by=current_user.id,
        consumption_date=request.form.get("consumption_date"),
        notes=request.form.get("notes"),
    )

    flash(message, "success" if success else "warning")
    if success and consumption:
        record_audit_log(
            module="HPP",
            event_type="STOCK_CONSUMPTION_COMMITTED",
            action="CREATE",
            table_name="order_hpp_stock_consumptions",
            record_id=consumption.id,
            description=f"Pemakaian stok HPP di-commit untuk snapshot {snapshot.snapshot_number}.",
            metadata={"snapshot_id": snapshot.id, "total_cost": consumption.total_cost},
        )
        return redirect(url_for(
            "operational.order_hpp_stock_consumption_detail",
            order_id=daily_order.id,
            snapshot_id=snapshot.id,
            consumption_id=consumption.id,
        ))

    return redirect(url_for(
        "operational.order_hpp_snapshot_stock_dry_run",
        order_id=daily_order.id,
        snapshot_id=snapshot.id,
    ))


@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-consumption/<int:consumption_id>")
@role_required("ADMIN")
def order_hpp_stock_consumption_detail(order_id, snapshot_id, consumption_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    consumption = OrderHppStockConsumption.query.get_or_404(consumption_id)
    if consumption.snapshot_id != snapshot.id or consumption.branch_id != current_user.branch_id:
        flash("Data pemakaian stok tidak sesuai snapshot/cabang.", "danger")
        return redirect(url_for("operational.order_hpp_snapshot_detail", order_id=daily_order.id, snapshot_id=snapshot.id))

    return render_template(
        "operational/order_hpp_stock_consumption_detail.html",
        daily_order=daily_order,
        snapshot=snapshot,
        consumption=consumption,
    )

