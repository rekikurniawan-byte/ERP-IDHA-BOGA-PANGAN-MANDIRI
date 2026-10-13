from flask import Blueprint, abort, render_template, redirect, request, url_for
from flask import current_app
from flask_login import current_user

from app.utils.decorators import role_required
from app.utils.roles import effective_role
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_SUBCLIENT,
)
from app.services.dashboard_service import (
    get_owner_dashboard_data,
    get_admin_dashboard_data,
    get_dapur_dashboard_data,
    get_pengantar_dashboard_data,
)
from app.services.dashboard_analytics_service import get_revenue_explorer_data
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context
from app.utils.terms import T


dashboard_bp = Blueprint("dashboard", __name__)


def _nested_get(data, *keys, default=None):
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return default
    return current


def _analytics_request_filters():
    """Resolve read-only analytics filter values from the dashboard query string."""
    include_asset_purchase = str(request.args.get("include_asset_purchase") or "").lower() in {"1", "true", "yes", "on"}
    return {
        "analytics_year": request.args.get("analytics_year"),
        "analytics_month": request.args.get("analytics_month"),
        "include_asset_purchase": include_asset_purchase,
        "revenue_period": request.args.get("revenue_period"),
        "revenue_start_date": request.args.get("revenue_start_date"),
        "revenue_end_date": request.args.get("revenue_end_date"),
        "revenue_group_by": request.args.get("revenue_group_by"),
        "revenue_source": request.args.get("revenue_source"),
        "revenue_client_id": request.args.get("revenue_client_id"),
        "revenue_mandor_id": request.args.get("revenue_mandor_id"),
        "revenue_branch_id": request.args.get("revenue_branch_id"),
    }


def _role_landing_endpoint(role):
    """Return the safest landing endpoint for each role.

    PRODUCTION keeps this redirect-only/landing behavior read-only:
    no database write, no user mutation, and no notification generation.
    """
    # Retired roles land where their successor does. The finance, accounting,
    # logistics and HR dashboards still exist and ADMIN can open them; they
    # are just no longer anyone's front door.
    role = effective_role(role)
    landing_map = {
        "OWNER": "dashboard.owner",
        "ADMIN": "dashboard.admin",
        "ADMIN_OPERASIONAL": "dashboard.ops",
        "DAPUR": "dashboard.dapur",
        "PENGANTAR": "dashboard.pengantar",
    }
    if role in {ROLE_PORTAL_CLIENT, ROLE_PORTAL_SUBCLIENT, ROLE_PORTAL_CUSTOMER}:
        return "portal.my_dashboard" if current_app.config.get("PORTAL_ENABLED", False) else None
    return landing_map.get(role)


@dashboard_bp.route("/")
def index():
    if not current_user.is_authenticated:
        from app.services.public_site_service import landing_context

        return render_template("public/landing.html", site=landing_context())

    endpoint = _role_landing_endpoint(current_user.role)
    if not endpoint:
        abort(403)

    return redirect(url_for(endpoint))


@dashboard_bp.route("/dashboard/owner")
@role_required("OWNER")
def owner():
    from app.services.opening_balance_service import branches_without_opening
    from app.services.path_report_service import build_path_summary

    from app.services.dashboard_pulse_service import build_owner_pulse

    data = get_owner_dashboard_data(**_analytics_request_filters())
    return render_template("dashboard/owner.html", data=data, path_summary=build_path_summary(current_user.branch_id),
                           branches_without_opening=branches_without_opening(),
                           pulse=build_owner_pulse(current_user.branch_id, data["command_center"]))


@dashboard_bp.route("/dashboard/admin")
@role_required("ADMIN")
def admin():
    from app.services.dashboard_pulse_service import build_admin_pulse

    data = get_admin_dashboard_data(current_user.branch_id, **_analytics_request_filters())
    return render_template("dashboard/admin.html", data=data,
                           pulse=build_admin_pulse(current_user.branch_id, data["command_center"]))


@dashboard_bp.route("/dashboard/revenue-explorer")
@role_required("ADMIN")
def revenue_explorer():
    filters = _analytics_request_filters()
    branch_id = None if current_user.role == "OWNER" else current_user.branch_id
    explorer = get_revenue_explorer_data(
        branch_id=branch_id,
        role=current_user.role,
        period_preset=filters.get("revenue_period"),
        start_date=filters.get("revenue_start_date"),
        end_date=filters.get("revenue_end_date"),
        group_by=filters.get("revenue_group_by"),
        source=filters.get("revenue_source"),
        client_id=filters.get("revenue_client_id"),
        mandor_id=filters.get("revenue_mandor_id"),
        selected_branch_id=filters.get("revenue_branch_id"),
    )
    date_filter = resolve_date_filter(
        request.args,
        start_key="revenue_start_date",
        end_key="revenue_end_date",
        preset_key="revenue_period",
        default_preset=_nested_get(explorer, "filters", "period_preset", default="this_month"),
    )
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("dashboard.revenue_explorer"),
        reset_url=url_for("dashboard.revenue_explorer"),
        title="Filter Omzet & Kas",
        description=f"Custom tanggal untuk omzet, kas masuk, invoice, warung, {T.client_lower}, dan {T.sub_client_lower}.",
        start_name="revenue_start_date",
        end_name="revenue_end_date",
        preset_name="revenue_period",
        source_name="revenue_source",
        source_value=_nested_get(explorer, "filters", "source", default="ALL"),
        source_options=_nested_get(explorer, "options", "sources", default=[]),
        hidden_fields={
            "revenue_group_by": _nested_get(explorer, "filters", "group_by", default="day"),
            "revenue_client_id": _nested_get(explorer, "filters", "client_id", default=""),
            "revenue_mandor_id": _nested_get(explorer, "filters", "mandor_id", default=""),
            "revenue_branch_id": _nested_get(explorer, "filters", "requested_branch_id", default=""),
        },
    )
    return render_template("dashboard/revenue_explorer.html", explorer=explorer, filter_bar=filter_bar)


@dashboard_bp.route("/dashboard/dapur")
@role_required("DAPUR")
def dapur():
    data = get_dapur_dashboard_data(current_user.branch_id)
    return render_template("dashboard/dapur.html", data=data)


@dashboard_bp.route("/dashboard/pengantar")
@role_required("PENGANTAR")
def pengantar():
    data = get_pengantar_dashboard_data(current_user.branch_id)
    template_name = "driver/dashboard.html" if current_user.role == "PENGANTAR" else "dashboard/pengantar.html"
    return render_template(template_name, data=data)


@dashboard_bp.route("/ops")
@role_required("OWNER", "ADMIN", "ADMIN_OPERASIONAL")
def ops_door():
    """Satu pintu masuk mode HP operasional untuk OWNER, ADMIN, dan ADMIN_OPERASIONAL."""
    from flask import session
    if current_user.role in ("OWNER", "ADMIN"):
        session["ops_mode"] = True
    return redirect(url_for("dashboard.ops"))


@dashboard_bp.route("/ops/exit", methods=["POST"])
@role_required("OWNER", "ADMIN")
def ops_exit():
    """Keluar dari mode HP operasional untuk OWNER dan ADMIN kembali ke tampilan desktop."""
    from flask import session
    session.pop("ops_mode", None)
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/dashboard/ops")
@role_required("OWNER", "ADMIN", "ADMIN_OPERASIONAL")
def ops():
    """Beranda operasional mobile: ringkasan kondisi hari ini tanpa tombol pintasan."""
    from app.services.ops_navigation_service import get_ops_dashboard_data

    from app.services.workforce_attendance_service import staffing_forecast

    data = get_ops_dashboard_data(current_user.branch_id)
    return render_template("ops/dashboard.html", data=data, staffing=staffing_forecast(current_user.branch_id))


@dashboard_bp.route("/search")
@role_required("OWNER", "ADMIN", "DAPUR", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR")
def search():
    """Pencarian global internal (Ctrl+K).

    Hanya baca, branch-scoped, maksimal 5 hasil per kategori:
    1. Pelanggan (Client) -> tautan ke 360° Pelanggan
    2. Sub client (Mandor) -> tautan ke master mandor
    3. Invoice -> tautan ke rincian invoice
    4. Pesanan -> tautan ke rincian pesanan harian
    5. Karyawan -> tautan ke daftar karyawan HR
    """
    from flask import jsonify
    from sqlalchemy import or_
    from app.models.master import Client, Mandor, Employee
    from app.models.finance import Invoice
    from app.models.operational import DailyOrder
    from app.utils.labels import status_label

    q = (request.args.get("q") or "").strip()
    if not q or len(q) < 2:
        return jsonify({"q": q, "results": [], "total": 0})

    branch_id = current_user.branch_id

    results = []

    # 1. Pelanggan / Client
    client_q = Client.query.filter(
        or_(
            Client.name.ilike(f"%{q}%"),
            Client.client_code.ilike(f"%{q}%"),
            Client.phone.ilike(f"%{q}%"),
        )
    )
    if branch_id:
        client_q = client_q.filter(Client.mandors.any(Mandor.branch_id == branch_id))
    clients = client_q.limit(5).all()
    if clients:
        results.append({
            "category": "Pelanggan",
            "icon": "bi-building",
            "items": [
                {
                    "title": c.name,
                    "subtitle": f"Kode: {c.client_code or '-'} · Jalur: {c.customer_path or 'KONTRAK'}",
                    "url": url_for("master.client_360", client_id=c.id),
                    "badge": "Aktif" if getattr(c, "is_active", True) else "Nonaktif",
                }
                for c in clients
            ],
        })

    # 2. Sub client / Mandor
    mandor_q = Mandor.query.filter(
        or_(
            Mandor.name.ilike(f"%{q}%"),
            Mandor.phone.ilike(f"%{q}%"),
            Mandor.id_number.ilike(f"%{q}%"),
        )
    )
    if branch_id:
        mandor_q = mandor_q.filter(Mandor.branch_id == branch_id)
    mandors = mandor_q.limit(5).all()
    if mandors:
        results.append({
            "category": "Sub Client (Mandor)",
            "icon": "bi-person-badge",
            "items": [
                {
                    "title": m.name,
                    "subtitle": f"Client: {m.client.name if m.client else '-'} · Telp: {m.phone or '-'}",
                    "url": url_for("master.mandors") + f"?q={m.name}",
                    "badge": "Aktif" if getattr(m, "is_active", True) else "Nonaktif",
                }
                for m in mandors
            ],
        })

    # 3. Invoice
    invoice_q = Invoice.query.filter(Invoice.invoice_number.ilike(f"%{q}%"))
    if branch_id:
        invoice_q = invoice_q.filter(Invoice.branch_id == branch_id)
    invoices = invoice_q.order_by(Invoice.id.desc()).limit(5).all()
    if invoices:
        results.append({
            "category": "Invoice",
            "icon": "bi-receipt",
            "items": [
                {
                    "title": inv.invoice_number,
                    "subtitle": f"Rp {float(inv.total_amount or 0):,.0f} · Jatuh Tempo: {inv.due_date.strftime('%d/%m/%Y') if inv.due_date else '-'}".replace(",", "."),
                    "url": url_for("finance.invoice_detail", invoice_id=inv.id),
                    "badge": status_label(inv.status or "DRAFT"),
                }
                for inv in invoices
            ],
        })

    # 4. Pesanan
    order_q = DailyOrder.query.filter(DailyOrder.order_number.ilike(f"%{q}%"))
    if branch_id:
        order_q = order_q.filter(DailyOrder.branch_id == branch_id)
    orders = order_q.order_by(DailyOrder.id.desc()).limit(5).all()
    if orders:
        results.append({
            "category": "Pesanan",
            "icon": "bi-journal-text",
            "items": [
                {
                    "title": order.order_number or f"Order #{order.id}",
                    "subtitle": f"Tanggal: {order.order_date.strftime('%d/%m/%Y') if order.order_date else '-'} · Shift: {order.meal_type or '-'}",
                    "url": url_for("operational.order_detail", order_id=order.id),
                    "badge": status_label(order.status or "DRAFT"),
                }
                for order in orders
            ],
        })

    # 5. Karyawan
    emp_q = Employee.query.filter(
        or_(
            Employee.full_name.ilike(f"%{q}%"),
            Employee.nik.ilike(f"%{q}%"),
            Employee.phone.ilike(f"%{q}%"),
        )
    )
    if branch_id:
        emp_q = emp_q.filter(Employee.branch_id == branch_id)
    employees = emp_q.limit(5).all()
    if employees:
        results.append({
            "category": "Karyawan",
            "icon": "bi-people",
            "items": [
                {
                    "title": emp.full_name,
                    "subtitle": f"NIK: {emp.nik or '-'} · Posisi: {emp.position or '-'}",
                    "url": url_for("hr.employees"),
                    "badge": status_label(emp.status or "ACTIVE"),
                }
                for emp in employees
            ],
        })

    total_count = sum(len(cat["items"]) for cat in results)
    return jsonify({
        "q": q,
        "results": results,
        "total": total_count,
    })





