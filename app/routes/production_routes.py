import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from datetime import datetime
from app.utils.clock import today_wib

from app.models.production import Production
from app.models.operational import DailyOrder
from app.services.delivery_service import build_delivery_next_action_for_order
from app.services.delivery_sla_service import calculate_production_sla, get_production_sla_defaults
from app.utils.decorators import role_required
from app.services.atomic_transaction_service import atomic_business_action
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context, apply_date_range_to_query
from app.services.ops_navigation_service import uses_ops_ui

from app.utils.labels import status_label

logger = logging.getLogger(__name__)


production_bp = Blueprint("production", __name__, url_prefix="/production")


ALLOWED_STATUS = ["DRAFT", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


@production_bp.route("/")
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def index():
    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    status_filter = (request.args.get("status") or "ALL").upper().strip()
    if status_filter not in ["ALL"] + ALLOWED_STATUS:
        status_filter = "ALL"

    query = Production.query.filter_by(branch_id=current_user.branch_id)
    query = apply_date_range_to_query(query, Production.production_date, date_filter)
    if status_filter != "ALL":
        query = query.filter(Production.status == status_filter)

    productions = query.order_by(
        Production.production_date.desc(),
        Production.production_type.asc(),
        Production.id.desc()
    ).all()

    template_name = "ops/production.html" if uses_ops_ui(current_user) else "production/index.html"
    return render_template(
        template_name,
        productions=productions,
        today=today_wib(),
        calculate_production_sla=calculate_production_sla,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("production.index"),
            reset_url=url_for("production.index"),
            title="Filter Produksi",
            description="Custom tanggal dan status produksi dapur.",
            status_name="status",
            status_value=status_filter,
            status_options=[{"value": "ALL", "label": "Semua Status"}] + [{"value": value, "label": status_label(value)} for value in ALLOWED_STATUS],
        ),
    )


@production_bp.route("/<int:production_id>")
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def detail(production_id):
    production = Production.query.get_or_404(production_id)

    if production.branch_id != current_user.branch_id:
        flash("Data produksi tidak sesuai cabang user.", "danger")
        return redirect(url_for("production.index"))

    can_update_production = current_user.role == "DAPUR"
    related_daily_order = DailyOrder.query.filter_by(
        branch_id=production.branch_id,
        order_date=production.production_date,
        is_locked=True,
    ).first()

    production_delivery_action = None
    if related_daily_order and production.production_type in ["LUNCH", "DINNER"]:
        production_delivery_action = build_delivery_next_action_for_order(
            related_daily_order,
            production.production_type,
        )

    production_sla = calculate_production_sla(production)

    template_name = "ops/production_detail.html" if uses_ops_ui(current_user) else "production/detail.html"
    return render_template(
        template_name,
        production=production,
        production_sla=production_sla,
        can_update_production=can_update_production,
        related_daily_order=related_daily_order,
        production_delivery_action=production_delivery_action,
    )


@production_bp.route("/<int:production_id>/realization", methods=["POST"])
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def update_realization(production_id):
    production = Production.query.get_or_404(production_id)

    if production.branch_id != current_user.branch_id:
        flash("Data produksi tidak sesuai cabang user.", "danger")
        return redirect(url_for("production.index"))

    if current_user.role != "DAPUR":
        flash("Akses ditolak. Realisasi produksi hanya boleh diinput oleh role DAPUR.", "danger")
        return redirect(url_for("production.detail", production_id=production.id))

    selected_status = request.form.get("status")
    actual_qty = float(request.form.get("actual_qty") or 0)
    notes = (request.form.get("notes") or "").strip()

    if selected_status not in ALLOWED_STATUS:
        flash("Status produksi tidak valid.", "warning")
        return redirect(url_for("production.detail", production_id=production.id))

    if actual_qty < 0:
        flash("Realisasi produksi tidak boleh minus.", "warning")
        return redirect(url_for("production.detail", production_id=production.id))

    detail = production.details[0] if production.details else None

    if not detail:
        flash("Detail produksi belum tersedia.", "warning")
        return redirect(url_for("production.detail", production_id=production.id))

    if selected_status == "COMPLETED" and actual_qty < detail.planned_qty:
        flash(
            "Produksi belum bisa COMPLETED karena realisasi masih kurang dari rencana produksi.",
            "warning"
        )
        return redirect(url_for("production.detail", production_id=production.id))

    if actual_qty > detail.planned_qty and not notes:
        flash(
            "Realisasi produksi melebihi rencana. Wajib isi catatan alasan selisih produksi.",
            "warning"
        )
        return redirect(url_for("production.detail", production_id=production.id))

    try:
        with atomic_business_action(
            module="PRODUCTION",
            action="PRODUCTION_REALIZATION_UPDATE",
            description=f"Update realisasi produksi #{production.id} secara atomic.",
            reference_type="productions",
            reference_id=production.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"production_id": production.id, "selected_status": selected_status, "actual_qty": actual_qty},
        ):
            detail.actual_qty = actual_qty
            detail.notes = notes

            previous_status = production.status

            if selected_status == "CANCELLED":
                production.status = "CANCELLED"
            elif actual_qty >= detail.planned_qty:
                production.status = "COMPLETED"
            elif actual_qty > 0:
                production.status = "IN_PROGRESS"
            else:
                production.status = "DRAFT"

            if production.status == "COMPLETED" and previous_status != "COMPLETED":
                production.actual_completed_time = datetime.utcnow()

            if not production.target_ready_time and production.production_type in ["LUNCH", "DINNER"]:
                defaults = get_production_sla_defaults(production.production_date, production.production_type)
                production.target_ready_time = defaults["target_ready_time"]
                production.late_tolerance_minutes = defaults["late_tolerance_minutes"]

            if notes:
                production.notes = notes
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/production_routes.py:172")
        flash(f"Gagal menyimpan realisasi produksi: {error}", "danger")
        return redirect(url_for("production.detail", production_id=production.id))

    if production.status == "COMPLETED":
        flash("Realisasi produksi tersimpan dan status otomatis menjadi COMPLETED.", "success")
    elif production.status == "IN_PROGRESS":
        flash("Realisasi produksi tersimpan dan status otomatis menjadi IN_PROGRESS.", "success")
    elif production.status == "DRAFT":
        flash("Realisasi produksi tersimpan dan status otomatis menjadi DRAFT.", "success")
    else:
        flash("Status produksi berhasil diperbarui.", "success")

    return redirect(url_for("production.detail", production_id=production.id))
