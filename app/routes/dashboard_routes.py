from flask import Blueprint, abort, render_template, redirect, request, url_for
from flask import current_app
from flask_login import login_required, current_user

from app.utils.decorators import role_required
from app.utils.roles import effective_role
from app.services.user_management_service import (
    ROLE_ACCOUNTING,
    ROLE_FINANCE,
    ROLE_HR,
    ROLE_LOGISTICS,
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_SUBCLIENT,
)
from app.services.dashboard_service import (
    get_owner_dashboard_data,
    get_admin_dashboard_data,
    get_dapur_dashboard_data,
    get_pengantar_dashboard_data,
    get_role_dashboard_metrics,
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


def _landing_card(title, description, endpoint, icon="bi-arrow-right-circle", **url_values):
    return {
        "title": title,
        "description": description,
        "url": url_for(endpoint, **url_values),
        "icon": icon,
    }


def _role_landing_payload(role, branch_id=None):
    payloads = {
        ROLE_FINANCE: {
            "eyebrow": "Dashboard Finance",
            "title": "Keuangan & Pembayaran",
            "description": "Landing khusus finance untuk invoice, pembayaran, kas/bank, piutang, dan hutang supplier.",
            "badge_label": "FINANCE",
            "cards": [
                _landing_card("Invoice", f"Pantau dan kelola invoice {T.client_lower}.", "finance.invoices", "bi-receipt"),
                _landing_card("Pembayaran Customer", "Riwayat pembayaran masuk dan bukti transfer invoice.", "finance.payment_history", "bi-credit-card"),
                _landing_card(f"Piutang {T.client}", f"Follow-up tagihan dan sisa piutang {T.client_lower}.", "finance.receivables", "bi-cash-coin"),
                _landing_card("Profit Invoice", "Baca margin invoice dari alokasi HPP.", "finance.invoice_profit_report", "bi-graph-up-arrow"),
                _landing_card("Hutang Supplier", "Kelola supplier bill dan pembayaran hutang.", "finance.supplier_bills", "bi-wallet"),
                _landing_card("AP Aging", "Lihat umur hutang supplier secara read-only.", "finance.accounts_payable_aging", "bi-hourglass-split"),
                _landing_card("Kartu Hutang Supplier", "Kartu hutang per supplier.", "finance.supplier_payable_card", "bi-journal-text"),
                _landing_card("Buku Kas/Bank", "Pantau kas/bank, transfer, adjustment, dan rekonsiliasi.", "finance.cash_bank_ledger", "bi-wallet2"),
                _landing_card("Transport & BBM", "Catat biaya transport dan BBM ke COA 5003/5011.", "finance.transport_expenses", "bi-fuel-pump"),
                _landing_card("Biaya Operasional", "Catat listrik, gas, perawatan, administrasi, dan kemasan ke COA beban.", "finance.operational_expenses", "bi-receipt-cutoff"),
                _landing_card("Pembelian Aset Tetap", "Catat pembelian aset yang mempengaruhi kas/bank dan jurnal.", "finance.fixed_asset_purchases", "bi-archive"),
            ],
        },
        ROLE_ACCOUNTING: {
            "eyebrow": "Dashboard Accounting",
            "title": "Akuntansi & Jurnal",
            "description": "Landing khusus accounting untuk jurnal, laporan, mapping akun, opening balance, dan checking data.",
            "badge_label": "ACCOUNTING",
            "cards": [
                _landing_card("Jurnal Akuntansi", "Pantau jurnal dan status balance.", "accounting.journals", "bi-journal-check"),
                _landing_card("Laporan Akuntansi", "Buka laporan akuntansi utama.", "accounting.reports", "bi-bar-chart-line"),
                _landing_card("COA Mapping", "Atur peta akun untuk otomatisasi jurnal.", "accounting.coa_mapping", "bi-diagram-2"),
                _landing_card("Saldo Awal & Modal", "Kelola opening balance perusahaan.", "accounting.opening_balance", "bi-bank"),
                _landing_card("Data Health Check", "Cek kesehatan data akuntansi.", "accounting.data_health", "bi-clipboard-pulse"),
                _landing_card("Closing Harian", "Pantau kesiapan closing harian.", "accounting.daily_closing", "bi-calendar-check"),
                _landing_card("Jejak Order sampai Lunas", "Jejak order, invoice, payment, dan jurnal.", "accounting.order_to_cash_trace", "bi-signpost-split"),
            ],
        },
        ROLE_LOGISTICS: {
            "eyebrow": "Dashboard Logistics",
            "title": "Logistik, Stok & Pembelian",
            "description": "Landing khusus logistics untuk stok, prediksi bahan, pembelian, nota digital, dan permintaan dapur.",
            "badge_label": "LOGISTICS",
            "cards": [
                _landing_card("Dashboard Stok", "Pantau saldo stok dan item menipis.", "logistics.index", "bi-box-seam"),
                _landing_card("Prediksi Bahan", "Hitung kebutuhan bahan dari order dan recipe/BOM.", "logistics.material_forecast", "bi-clipboard-data"),
                _landing_card("Pembelian Barang", "Input pembelian dan nota/struk digital.", "logistics.purchases", "bi-basket"),
                _landing_card("Permintaan Dapur", "Proses permintaan bahan dari dapur.", "logistics.item_requests", "bi-inboxes"),
                _landing_card("Pemakaian Dapur", "Pantau pemakaian bahan dapur.", "logistics.kitchen_usage", "bi-egg-fried"),
                _landing_card("Stok Masuk", "Catat stok masuk manual.", "logistics.stock_in", "bi-plus-circle"),
                _landing_card("Stok Keluar", "Catat stok keluar manual.", "logistics.stock_out", "bi-dash-circle"),
                _landing_card("Audit Stok", "Stock opname/audit stok.", "logistics.audit", "bi-clipboard-check"),
                _landing_card("Master Item", "Kelola barang dan bahan baku.", "master.items", "bi-boxes"),
                _landing_card("Supplier", "Kelola supplier opsional.", "master.suppliers", "bi-truck-front"),
            ],
        },
        ROLE_HR: {
            "eyebrow": "Dashboard HR",
            "title": "SDM & Payroll",
            "description": f"Landing khusus HR untuk karyawan internal dan payroll. {T.sub_client} tetap bukan employee/payroll.",
            "badge_label": "HR",
            "cards": [
                _landing_card("Dashboard SDM", "Ringkasan karyawan internal dan payroll.", "hr.index", "bi-people"),
                _landing_card("Karyawan Internal", "Kelola data karyawan internal perusahaan.", "hr.employees", "bi-person-lines-fill"),
                _landing_card("Payroll", "Kelola payroll bulanan karyawan internal.", "hr.payrolls", "bi-cash-stack"),
                _landing_card("Generate Payroll", "Buat payroll periode berjalan.", "hr.generate_payroll_route", "bi-calendar-plus"),
                _landing_card("Riwayat Pembayaran Gaji", "Pantau histori pembayaran payroll.", "hr.payroll_payment_history", "bi-clock-history"),
            ],
        },
    }

    payload = payloads.get(role)
    if payload:
        payload["cards"].append(
            _landing_card("Reminder Live", "Cek reminder operasional tanpa menyimpan notifikasi.", "settings.live_reminders", "bi-bell")
        )
        payload["kpis"] = get_role_dashboard_metrics(role, branch_id)
        payload["primary_card"] = payload["cards"][0] if payload["cards"] else None
        payload["support_cards"] = payload["cards"][4:] if len(payload["cards"]) > 4 else []
    return payload


@dashboard_bp.route("/")
def index():
    if not current_user.is_authenticated:
        data = {
            "title": "PT Idha Boga Pangan Mandiri",
            "subtitle": "Portal pemesanan catering dan sistem operasional terintegrasi.",
            "description": f"Pelanggan umum membuat pesanan dan membayar di awal. {T.sub_client} mengelola pesanan, {T.worker_lower}, hutang, tagihan, dan pembayaran. {T.client} memantau seluruh {T.sub_client_lower}, invoice, piutang, pembayaran, dan kontrak dalam satu ERP.",
            "primary_url": url_for("auth.login"),
            "secondary_url": url_for("portal.register") if current_app.config.get("PORTAL_ENABLED", False) else url_for("auth.login"),
            "portal_enabled": bool(current_app.config.get("PORTAL_ENABLED", False)),
            "roles": [
                {
                    "title": "Pelanggan Umum",
                    "description": "Pesan catering, upload bukti bayar, lacak pesanan, komplain, dan retur. Tidak ada kredit.",
                    "icon": "bi-bag-check",
                    "steps": ["Pesan", "Bayar", "Diverifikasi", "Diproses"],
                },
                {
                    "title": T.sub_client,
                    "description": f"Kelola order, {T.worker_lower}, hutang catering, hutang warung, cicilan, invoice, dan pembayaran.",
                    "icon": "bi-people",
                    "steps": ["Order", T.worker, "Hutang", "Bayar"],
                },
                {
                    "title": T.client,
                    "description": f"Pantau seluruh {T.sub_client_lower}, total hutang, invoice diterbitkan, invoice belum lunas, riwayat pembayaran, dan rekap tagihan.",
                    "icon": "bi-building-check",
                    "steps": [T.sub_client, "Piutang", "Invoice", "Kontrak"],
                },
            ],
            "rules": [
                "ERP tetap menjadi satu sumber data.",
                "Akun portal terhubung ke data perusahaan yang sama.",
                "Customer umum bayar dulu sebelum pesanan diproses.",
                f"{T.sub_client} dan {T.client_lower} mengikuti aturan tempo/kredit yang sudah disetujui.",
            ],
        }
        return render_template("public/landing.html", data=data)

    endpoint = _role_landing_endpoint(current_user.role)
    if not endpoint:
        abort(403)

    return redirect(url_for(endpoint))


@dashboard_bp.route("/dashboard/owner")
@role_required("OWNER")
def owner():
    data = get_owner_dashboard_data(**_analytics_request_filters())
    return render_template("dashboard/owner.html", data=data)


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
        title="Filter Revenue Explorer",
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
    return render_template("dashboard/pengantar.html", data=data)


@dashboard_bp.route("/dashboard/finance")
@role_required("FINANCE")
def finance():
    return render_template("dashboard/role_landing.html", landing=_role_landing_payload(ROLE_FINANCE, current_user.branch_id))


@dashboard_bp.route("/dashboard/accounting")
@role_required("ACCOUNTING")
def accounting():
    return render_template("dashboard/role_landing.html", landing=_role_landing_payload(ROLE_ACCOUNTING, current_user.branch_id))


@dashboard_bp.route("/dashboard/logistics")
@role_required("LOGISTICS")
def logistics():
    return render_template("dashboard/role_landing.html", landing=_role_landing_payload(ROLE_LOGISTICS, current_user.branch_id))


@dashboard_bp.route("/dashboard/hr")
@role_required("HR")
def hr():
    return render_template("dashboard/role_landing.html", landing=_role_landing_payload(ROLE_HR, current_user.branch_id))


@dashboard_bp.route("/module/<module_name>")
@login_required
def module_placeholder(module_name):
    module_titles = {
        "master-data": "Master Data",
        "pengiriman": "Pengiriman",
        "warung": "Warung",
        "logistik-stok": "Logistik & Stok",
        "sdm": "SDM",
        "keuangan": "Keuangan",
        "akuntansi": "Akuntansi",
        "kas-harian": "Kas Harian",
        "invoice": "Invoice",
        "pembayaran": "Pembayaran",
        "mandor-pekerja": f"{T.sub_client} & {T.worker}",
        "permintaan-barang": "Permintaan Barang",
        "pemakaian-barang": "Pemakaian Barang",
        "penerimaan": "Penerimaan Pengiriman",
        "riwayat-pengiriman": "Riwayat Pengiriman",
        "notifikasi": "Notifikasi",
    }

    title = module_titles.get(module_name, "Modul Sistem")

    return render_template(
        "module_placeholder.html",
        title=title,
        module_name=module_name
    )
