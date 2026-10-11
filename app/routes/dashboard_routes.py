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

    data = get_owner_dashboard_data(**_analytics_request_filters())
    return render_template("dashboard/owner.html", data=data, path_summary=build_path_summary(current_user.branch_id),
                           branches_without_opening=branches_without_opening())


@dashboard_bp.route("/dashboard/admin")
@role_required("ADMIN")
def admin():
    data = get_admin_dashboard_data(current_user.branch_id, **_analytics_request_filters())
    return render_template("dashboard/admin.html", data=data)


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


