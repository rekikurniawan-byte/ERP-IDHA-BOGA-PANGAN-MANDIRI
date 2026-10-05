"""PRODUCTION Dashboard Command Center read-only service.

Tujuan service ini adalah merapikan dashboard Owner/Admin menjadi command
center ringkas: KPI penting, chart-first untuk owner, reminder operasional,
recovery/backup signal, dan link detail. Service ini read-only dan tidak
melakukan commit/flush/mutation database.
"""
from __future__ import annotations
import logging

from typing import Any, Dict, Iterable, List
from app.services.branch_module_service import WARUNG, WORKER_DEBT, module_enabled
from app.utils.terms import T

logger = logging.getLogger(__name__)


APP_VERSION = "PRODUCTION"
DASHBOARD_COMMAND_CENTER_VERSION = "PRODUCTION_DASHBOARD_COMMAND_CENTER_FINAL_V1"


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/dashboard_command_center_service.py:20")
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/dashboard_command_center_service.py:27")
        return 0


def _money(value: Any) -> str:
    return "Rp {:,.0f}".format(_num(value)).replace(",", ".")


def _status_class(status: str) -> str:
    normalized = str(status or "").upper()
    if normalized in {"AMAN", "READY", "PASS", "OK", "VERIFIED", "TERKENDALI"}:
        return "success"
    if normalized in {"PERLU CEK", "WARNING", "CHECK", "PENDING", "DIPANTAU"}:
        return "warning"
    return "danger"


def _kpi(label: str, value: Any, caption: str, icon: str, tone: str = "neutral") -> Dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "caption": caption,
        "icon": icon,
        "tone": tone,
    }


def _reminder(title: str, detail: str, severity: str, endpoint: str, icon: str = "bi-exclamation-circle") -> Dict[str, Any]:
    severity = str(severity or "warning").lower()
    return {
        "title": title,
        "detail": detail,
        "severity": severity,
        "status_class": "danger" if severity == "danger" else ("warning" if severity == "warning" else "info"),
        "endpoint": endpoint,
        "icon": icon,
    }


def _link(title: str, detail: str, endpoint: str, icon: str = "bi-arrow-right-circle", owner_only: bool = False) -> Dict[str, Any]:
    return {
        "title": title,
        "detail": detail,
        "endpoint": endpoint,
        "icon": icon,
        "owner_only": owner_only,
    }


def _backup_signal() -> Dict[str, Any]:
    """Return a lightweight backup/recovery signal for dashboard cards.

    Defensive by design: dashboard tetap render kalau backup service gagal.
    """
    try:
        from app.services.backup_service import get_backup_status
        from app.services.ttl_cache_service import get_cached_value

        # Status backup menghitung sha256 semua file backup; cukup diperbarui
        # tiap 5 menit untuk kartu dashboard (halaman Backup tetap segar).
        status = get_cached_value(("dashboard_backup_status",), get_backup_status, ttl_seconds=300)
        full_backups = list(status.get("full_backups") or [])
        verified = [item for item in full_backups if item.get("is_verified_backup")]
        latest_verified = verified[0] if verified else None
        restore_status = latest_verified.get("restore_dry_run_status") if latest_verified else "BELUM ADA"
        return {
            "status": "PASS" if latest_verified else "WARNING",
            "label": "Terverifikasi" if latest_verified else "Belum Terverifikasi",
            "verified_count": len(verified),
            "full_backup_count": len(full_backups),
            "latest_verified": latest_verified,
            "restore_dry_run_status": restore_status or "BELUM ADA",
            "message": "Cadangan data terverifikasi tersedia." if latest_verified else "Buat cadangan data lengkap sebelum pembaruan besar.",
        }
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/services/dashboard_command_center_service.py:98")
        return {
            "status": "WARNING",
            "label": "Perlu Cek",
            "verified_count": 0,
            "full_backup_count": 0,
            "latest_verified": None,
            "restore_dry_run_status": "BELUM TERBACA",
            "message": f"Status cadangan data belum terbaca: {exc}",
        }


def _decision(reminders: Iterable[Dict[str, Any]], backup: Dict[str, Any]) -> Dict[str, Any]:
    reminders = list(reminders or [])
    danger_count = sum(1 for item in reminders if item.get("severity") == "danger")
    warning_count = sum(1 for item in reminders if item.get("severity") == "warning")

    if danger_count:
        label = "BAHAYA"
        summary = f"{danger_count} risiko tinggi perlu diselesaikan dulu."
    elif not backup.get("verified_count"):
        label = "BACKUP DULU"
        summary = "Belum ada backup verified yang terbaca."
    elif warning_count:
        label = "PERLU CEK"
        summary = f"{warning_count} item operasional perlu dicek."
    else:
        label = "READY"
        summary = "Kondisi dashboard utama terkendali."

    return {
        "label": label,
        "summary": summary,
        "status_class": _status_class(label),
    }


def build_owner_command_center(data: Dict[str, Any]) -> Dict[str, Any]:
    finance = data.get("finance") or {}
    cash_bank = data.get("cash_bank") or {}
    ap = data.get("accounts_payable") or {}
    hpp = data.get("hpp_snapshot") or {}
    operations = data.get("operations") or {}
    logistics = data.get("logistics") or {}
    accounting = data.get("accounting") or {}

    delivery_risk = max(_int(operations.get("today_deliveries")) - _int(operations.get("delivered_today")), 0)
    low_stock_count = len(logistics.get("low_stock_items") or [])
    backup = _backup_signal()

    reminders: List[Dict[str, Any]] = []
    if _int(finance.get("overdue_count")):
        reminders.append(_reminder(
            "Piutang overdue",
            f"{_int(finance.get('overdue_count'))} invoice lewat jatuh tempo.",
            "danger",
            "finance.receivables",
            "bi-cash-coin",
        ))
    if _int(ap.get("overdue_count")):
        reminders.append(_reminder(
            "Hutang supplier overdue",
            f"{_int(ap.get('overdue_count'))} bill supplier lewat jatuh tempo.",
            "warning",
            "finance.supplier_bills",
            "bi-receipt-cutoff",
        ))
    if delivery_risk:
        reminders.append(_reminder(
            "Delivery belum selesai",
            f"{delivery_risk} delivery hari ini belum delivered.",
            "warning",
            "delivery.today",
            "bi-truck",
        ))
    if low_stock_count:
        reminders.append(_reminder(
            "Stok kritis",
            f"{low_stock_count} item berada di/minimum stok.",
            "warning",
            "logistics.index",
            "bi-box-seam",
        ))
    if _int(accounting.get("unbalanced_journal_count")):
        reminders.append(_reminder(
            "Jurnal tidak balance",
            f"{_int(accounting.get('unbalanced_journal_count'))} jurnal harus dicek.",
            "danger",
            "accounting.journals",
            "bi-journal-x",
        ))
    if not backup.get("verified_count"):
        reminders.append(_reminder(
            "Cadangan data belum terverifikasi",
            backup.get("message") or "Buat cadangan data lengkap sebelum pembaruan besar.",
            "danger",
            "settings.backups",
            "bi-database-exclamation",
        ))

    kpis = [
        _kpi("Omzet", _money(finance.get("total_invoice_active")), f"{_int(finance.get('active_invoice_count'))} invoice aktif", "bi-receipt", "info"),
        _kpi("Kas Masuk", _money(finance.get("total_payment") or cash_bank.get("total_in")), f"{_int(finance.get('payment_count'))} pembayaran", "bi-cash-stack", "success"),
        _kpi("Piutang", _money(finance.get("remaining_invoice_active")), f"{_int(finance.get('receivable_invoice_count'))} invoice belum lunas", "bi-cash-coin", "danger" if _num(finance.get("remaining_invoice_active")) else "success"),
        _kpi("Beban", _money(cash_bank.get("total_out")), "Total kas/bank keluar tercatat", "bi-graph-down-arrow", "warning"),
        _kpi("Profit Estimasi", _money(hpp.get("total_margin")), f"Margin {round(_num(hpp.get('margin_percentage')), 1)}%", "bi-graph-up-arrow", "success"),
        _kpi("Risiko Pengiriman", delivery_risk, "Pengiriman hari ini belum diterima", "bi-truck", "warning" if delivery_risk else "success"),
    ]

    detail_links = [
        _link("Omzet & Kas", "Analisis omzet, kas masuk, piutang, dan sumber pendapatan.", "dashboard.revenue_explorer", "bi-graph-up-arrow"),
        _link("Rincian Beban", "Baca beban per kategori dan akun.", "accounting.expense_drilldown", "bi-graph-down-arrow"),
        _link("Status Posting", "Cek jurnal otomatis/manual dan status posting.", "accounting.posting_status", "bi-clipboard-check"),
        _link("Kesehatan Sistem", "Cek database, cadangan data, unggahan, dan migrasi.", "settings.system_health", "bi-heart-pulse", True),
        _link("Pusat Pemulihan", "Langkah aman sebelum pembaruan atau pemulihan data.", "settings.recovery_center", "bi-life-preserver", True),
        _link("SOP Pemulihan", "Panduan darurat cadangan dan pemulihan data.", "sop.disaster_recovery", "bi-journal-medical"),
    ]

    return {
        "schema_version": DASHBOARD_COMMAND_CENTER_VERSION,
        "role": "OWNER",
        "title": "Pusat Kendali Owner",
        "subtitle": "Ringkasan bisnis, kas, piutang, beban, pengiriman, dan risiko operasional.",
        "decision": _decision(reminders, backup),
        "kpis": kpis,
        "reminders": reminders[:8],
        "backup": backup,
        "detail_links": detail_links,
        "low_stock_items": logistics.get("low_stock_items") or [],
    }


def build_admin_command_center(data: Dict[str, Any]) -> Dict[str, Any]:
    backup = _backup_signal()
    delivery_action_count = _int(data.get("delivery_next_action_count"))
    low_stock_count = _int(data.get("low_stock_count"))
    active_delivery = _int(data.get("preparing_delivery")) + _int(data.get("on_the_way_delivery"))

    reminders: List[Dict[str, Any]] = []
    if delivery_action_count:
        reminders.append(_reminder(
            "Delivery perlu dibuat",
            f"{delivery_action_count} produksi sudah completed tetapi delivery belum lengkap.",
            "danger",
            "delivery.today",
            "bi-truck",
        ))
    if active_delivery:
        reminders.append(_reminder(
            "Delivery berjalan",
            f"{active_delivery} delivery masih preparing/on the way.",
            "warning",
            "delivery.index",
            "bi-truck-front",
        ))
    warung_on = module_enabled(WARUNG)
    worker_debt_on = module_enabled(WORKER_DEBT)
    if worker_debt_on and _int(data.get("unpaid_worker_debt")):
        reminders.append(_reminder(
            f"Hutang {T.worker_lower} belum lunas",
            f"{_int(data.get('unpaid_worker_debt'))} catatan hutang {T.worker_lower} perlu dipantau.",
            "warning",
            "master.workers",
            "bi-people",
        ))
    if low_stock_count:
        reminders.append(_reminder(
            "Stok kritis",
            f"{low_stock_count} item berada di/minimum stok.",
            "warning",
            "logistics.index",
            "bi-box-seam",
        ))
    if not backup.get("verified_count"):
        reminders.append(_reminder(
            "Cadangan data belum terverifikasi",
            backup.get("message") or "Buat cadangan data lengkap sebelum pembaruan besar.",
            "warning",
            "settings.backups",
            "bi-database-exclamation",
        ))

    kpis = [
        _kpi("Order Hari Ini", _int(data.get("today_orders")), "Order cabang sesuai tanggal sistem", "bi-calendar-check", "info"),
        _kpi("Produksi Hari Ini", _int(data.get("today_productions")), "Batch produksi tanggal sistem", "bi-egg-fried", "success"),
        _kpi("Pengiriman Aktif", active_delivery, f"{_int(data.get('preparing_delivery'))} disiapkan · {_int(data.get('on_the_way_delivery'))} di jalan", "bi-truck", "warning" if active_delivery else "success"),
        *([_kpi("Warung Hari Ini", _money(data.get("today_cash_sales")), "Penjualan tunai cabang hari ini", "bi-shop", "success")] if warung_on else []),
        _kpi("Stok Kritis", low_stock_count, "Item di/minimum stok", "bi-box-seam", "warning" if low_stock_count else "success"),
        _kpi("Cadangan Data", backup.get("label"), backup.get("message"), "bi-database-check", "success" if backup.get("verified_count") else "warning"),
    ]

    detail_links = [
        _link("Input Order Harian", "Input dan cek order cabang.", "operational.orders", "bi-journal-text"),
        _link("Produksi", "Pantau produksi dapur dan realisasi.", "production.index", "bi-egg-fried"),
        _link("Pengiriman", "Pantau pengiriman dan penerimaan.", "delivery.index", "bi-truck"),
        *([_link(
            "Warung Cepat",
            f"Input transaksi warung/cash/hutang {T.worker_lower}." if worker_debt_on else "Input transaksi warung.",
            "canteen.quick_sale",
            "bi-lightning-charge",
        )] if warung_on else []),
        _link("Stok", "Pantau stok kritis dan pembelian.", "logistics.index", "bi-box-seam"),
        _link("Pengingat", "Cek pengingat operasional hari ini.", "settings.live_reminders", "bi-bell"),
    ]

    return {
        "schema_version": DASHBOARD_COMMAND_CENTER_VERSION,
        "role": "ADMIN",
        "title": "Pusat Kendali Admin",
        "subtitle": "Kontrol cabang untuk order, produksi, pengiriman, warung, stok, dan pengingat operasional.",
        "decision": _decision(reminders, backup),
        "kpis": kpis,
        "reminders": reminders[:8],
        "backup": backup,
        "detail_links": detail_links,
    }
