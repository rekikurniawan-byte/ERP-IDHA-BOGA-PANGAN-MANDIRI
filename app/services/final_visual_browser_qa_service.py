"""PRODUCTION Final Visual Browser QA Lock service.

Read-only final UI QA lock after PRODUCTION..F. This service does not mutate
business data, does not require a migration, and does not execute active
restore. It consolidates static browser QA readiness, critical route/template
coverage, CSS build/theme/filter locks, print/export checks, and the manual
browser matrix that must be executed on a real browser before production use.
"""
from __future__ import annotations
import logging

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)

APP_VERSION = "PRODUCTION"
FINAL_BROWSER_QA_VERSION = "PRODUCTION_VISUAL_ALIGNMENT_EMERGENCY_LOCK_V1"

VIEWPORT_MATRIX = [
    {
        "name": "Desktop 1366px",
        "viewport": "1366 × 768",
        "target": "Owner/Admin command center, dense finance/accounting table, sidebar full width.",
        "expected": "Tidak horizontal overflow, KPI/chart/filter/action kanan tetap rapih.",
    },
    {
        "name": "Laptop 1280px",
        "viewport": "1280 × 720",
        "target": "Dashboard, report, finance detail, settings/recovery pages.",
        "expected": "Header tidak dobel, action tetap kanan, card grid tidak pecah.",
    },
    {
        "name": "Tablet",
        "viewport": "768 × 1024",
        "target": "Sidebar responsive, global filter, table wrapper, dashboard cards.",
        "expected": "Menu tidak nutup konten, filter turun rapi, tabel tetap scroll lokal jika perlu.",
    },
    {
        "name": "Mobile 390px",
        "viewport": "390 × 844",
        "target": "Web di HP owner/admin seperti request owner.",
        "expected": "Tidak berantakan, tidak overflow global, tombol apply/reset dekat, card compact.",
    },
    {
        "name": "Chrome Print Preview",
        "viewport": "A4 print",
        "target": "Invoice, payment receipt, accounting reports, AP aging, profit report.",
        "expected": "Print tidak kepotong, tombol/sidebar/topbar tidak ikut print, tabel tetap terbaca.",
    },
]

CRITICAL_ENDPOINTS = [
    {"endpoint": "dashboard.owner", "label": "Dashboard Owner Command Center", "role": "OWNER", "area": "Dashboard"},
    {"endpoint": "dashboard.admin", "label": "Dashboard Admin Command Center", "role": "ADMIN", "area": "Dashboard"},
    {"endpoint": "dashboard.revenue_explorer", "label": "Revenue Explorer", "role": "OWNER/ADMIN", "area": "Dashboard"},
    {"endpoint": "accounting.expense_drilldown", "label": "Expense Drilldown", "role": "OWNER/ACCOUNTING", "area": "Accounting"},
    {"endpoint": "accounting.posting_status", "label": "Posting Status", "role": "OWNER/ACCOUNTING", "area": "Accounting"},
    {"endpoint": "accounting.reports", "label": "Accounting Reports", "role": "OWNER/ACCOUNTING", "area": "Accounting"},
    {"endpoint": "settings.system_health", "label": "Kesehatan Sistem", "role": "OWNER/ADMIN", "area": "Recovery"},
    {"endpoint": "settings.recovery_center", "label": "Recovery Center", "role": "OWNER/ADMIN", "area": "Recovery"},
    {"endpoint": "settings.backups", "label": "Backup & Restore", "role": "OWNER", "area": "Recovery"},
    {"endpoint": "settings.audit_logs", "label": "Audit Logs", "role": "OWNER", "area": "Recovery"},
    {"endpoint": "settings.visual_sweep", "label": "Visual Sweep", "role": "OWNER/ADMIN", "area": "QA"},
    {"endpoint": "settings.final_visual_browser_qa", "label": "Final Browser QA", "role": "OWNER/ADMIN", "area": "QA"},
    {"endpoint": "delivery.history", "label": "Delivery History", "role": "OWNER/ADMIN/PENGANTAR", "area": "Delivery"},
    {"endpoint": "production.index", "label": "Production Index", "role": "OWNER/ADMIN/DAPUR", "area": "Production"},
    {"endpoint": "finance.payment_history", "label": "Payment History", "role": "OWNER/ADMIN/FINANCE", "area": "Finance"},
    {"endpoint": "finance.receivables", "label": "Receivables Statement", "role": "OWNER/ADMIN/FINANCE", "area": "Finance"},
    {"endpoint": "finance.supplier_bills", "label": "Supplier Bills/AP", "role": "OWNER/ADMIN/FINANCE", "area": "Finance"},
    {"endpoint": "finance.invoice_profit_report", "label": "Invoice Profit Report", "role": "OWNER/ADMIN/FINANCE", "area": "Finance"},
    {"endpoint": "finance.fixed_asset_installments", "label": "Asset Installments", "role": "OWNER/ADMIN/FINANCE/ACCOUNTING", "area": "Finance"},
    {"endpoint": "canteen.index", "label": "Warung/Canteen", "role": "OWNER/ADMIN", "area": "Canteen"},
    {"endpoint": "hr.index", "label": "HR Dashboard", "role": "OWNER/ADMIN/HR", "area": "HR"},
    {"endpoint": "sop.disaster_recovery", "label": "SOP Disaster Recovery", "role": "OWNER/ADMIN", "area": "SOP"},
    {"endpoint": "sop.backup_restore", "label": "SOP Backup Restore", "role": "OWNER/ADMIN", "area": "SOP"},
]

CRITICAL_TEMPLATES = [
    "dashboard/owner.html",
    "dashboard/admin.html",
    "dashboard/revenue_explorer.html",
    "accounting/expense_drilldown.html",
    "accounting/posting_status.html",
    "accounting/reports.html",
    "settings/system_health.html",
    "settings/recovery_center.html",
    "settings/backup.html",
    "settings/audit_logs.html",
    "settings/visual_sweep.html",
    "settings/final_visual_browser_qa.html",
    "delivery/history.html",
    "production/index.html",
    "finance/payment_history.html",
    "finance/receivables_statement.html",
    "finance/supplier_bills.html",
    "finance/invoice_profit_report.html",
    "finance/fixed_asset_installments.html",
    "canteen/index.html",
    "hr/index.html",
    "sop/disaster_recovery.html",
    "sop/backup_restore.html",
]

PRINT_TEMPLATES = [
    "finance/invoice_print.html",
    "finance/payment_receipt.html",
    "finance/print_cash_bank_ledger.html",
    "finance/print_invoice_profit_report.html",
    "finance/print_accounts_payable_aging.html",
    "finance/print_supplier_payable_card.html",
    "accounting/print_journals.html",
    "accounting/print_journal_detail.html",
    "accounting/print_trial_balance.html",
    "accounting/print_general_ledger.html",
    "accounting/print_income_summary.html",
    "accounting/print_daily_closing.html",
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/final_visual_browser_qa_service.py:128")
        return str(path).replace("\\", "/")


def _extract_route_endpoints(root: Path) -> Set[str]:
    endpoints: Set[str] = set()
    blueprint_map: Dict[str, str] = {}
    route_files = sorted((root / "app" / "routes").glob("*_routes.py"))

    for path in route_files:
        text = path.read_text(encoding="utf-8")
        for variable, name in re.findall(r'(\w+)\s*=\s*Blueprint\(\s*["\']([^"\']+)["\']', text):
            blueprint_map[variable] = name

        pattern = re.compile(
            r"@(?P<bp>\w+)\.route\([^\n]*\)\s*"
            r"(?:\n\s*@[^\n]+)*"
            r"\n\s*def\s+(?P<fn>\w+)\s*\(",
            re.MULTILINE,
        )
        for match in pattern.finditer(text):
            bp_variable = match.group("bp")
            fn_name = match.group("fn")
            bp_name = blueprint_map.get(bp_variable, bp_variable.replace("_bp", ""))
            endpoints.add(f"{bp_name}.{fn_name}")

    return endpoints


def _css_report(root: Path) -> Dict[str, Any]:
    report_path = root / "app" / "static" / "css" / "css_build_report.json"
    style_path = root / "app" / "static" / "css" / "style.css"
    src_dir = root / "app" / "static" / "css" / "src"
    theme_lock = src_dir / "100_theme_black_white_lock.css"
    filter_lock = src_dir / "102_global_filter_bar_v2.css"
    zero_empty_lock = src_dir / "103_zero_empty_visual_sweep.css"
    installment_lock = src_dir / "104_asset_installment_foundation.css"
    browser_qa_lock = src_dir / "105_final_visual_browser_qa_lock.css"

    try:
        raw_report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/final_visual_browser_qa_service.py:169")
        raw_report = {}

    style_text = style_path.read_text(encoding="utf-8") if style_path.exists() else ""
    theme_text = theme_lock.read_text(encoding="utf-8") if theme_lock.exists() else ""
    source_files = sorted(src_dir.glob("*.css")) if src_dir.exists() else []
    required_ok = all(path.exists() for path in [style_path, report_path, theme_lock, filter_lock, zero_empty_lock, installment_lock, browser_qa_lock])
    theme_ok = "dark-mono" in theme_text and "light-mono" in theme_text
    generated_ok = "GENERATED FILE - DO NOT EDIT DIRECTLY" in style_text
    build_ok = raw_report.get("build_version") == APP_VERSION
    brace = (raw_report.get("checks") or {}).get("brace_balance") or raw_report.get("brace_balance") or {}
    brace_ok = brace.get("balance") == 0 and not brace.get("has_negative_balance", False)

    status = "AMAN" if all([required_ok, theme_ok, generated_ok, build_ok, brace_ok]) else "PERLU CEK"
    return {
        "status": status,
        "build_version": raw_report.get("build_version", "UNKNOWN"),
        "source_file_count": raw_report.get("source_file_count") or len(source_files),
        "style_css_generated_lock": generated_ok,
        "theme_lock_ok": theme_ok,
        "filter_lock_ok": filter_lock.exists(),
        "zero_empty_lock_ok": zero_empty_lock.exists(),
        "asset_installment_lock_ok": installment_lock.exists(),
        "browser_qa_lock_ok": browser_qa_lock.exists(),
        "brace_balance": brace.get("balance"),
        "duplicate_selector_count": (raw_report.get("selector_report") or {}).get("duplicate_selector_count"),
        "report_path": _rel(report_path, root),
    }


def _critical_route_matrix(root: Path, endpoints: Set[str]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    missing = []
    for item in CRITICAL_ENDPOINTS:
        ok = item["endpoint"] in endpoints
        row = dict(item)
        row["status"] = "PASS" if ok else "MISSING"
        row["status_class"] = "success" if ok else "danger"
        items.append(row)
        if not ok:
            missing.append(row)

    return {
        "status": "AMAN" if not missing else "BAHAYA",
        "endpoint_count": len(endpoints),
        "critical_count": len(items),
        "missing_count": len(missing),
        "items": items,
        "missing": missing,
    }


def _template_matrix(root: Path) -> Dict[str, Any]:
    items = []
    missing = []
    for rel in CRITICAL_TEMPLATES:
        path = root / "app" / "templates" / rel
        ok = path.exists()
        row = {"template": rel, "status": "PASS" if ok else "MISSING", "status_class": "success" if ok else "danger"}
        items.append(row)
        if not ok:
            missing.append(row)
    return {
        "status": "AMAN" if not missing else "BAHAYA",
        "template_count": len(items),
        "missing_count": len(missing),
        "items": items,
        "missing": missing,
    }


def _print_matrix(root: Path) -> Dict[str, Any]:
    style_files = [
        root / "app" / "templates" / "finance" / "_finance_print_report_styles.html",
        root / "app" / "templates" / "accounting" / "_accounting_print_report_styles.html",
        root / "app" / "static" / "css" / "src" / "13_print.css",
    ]
    items = []
    missing = []
    for rel in PRINT_TEMPLATES:
        path = root / "app" / "templates" / rel
        ok = path.exists()
        row = {"template": rel, "status": "PASS" if ok else "MISSING", "status_class": "success" if ok else "danger"}
        items.append(row)
        if not ok:
            missing.append(row)
    style_ok = all(path.exists() for path in style_files)
    return {
        "status": "AMAN" if not missing and style_ok else "PERLU CEK",
        "template_count": len(items),
        "missing_count": len(missing),
        "print_style_ok": style_ok,
        "items": items,
        "missing": missing,
    }


def _manual_browser_matrix() -> Dict[str, Any]:
    items = []
    for view in VIEWPORT_MATRIX:
        row = dict(view)
        row["status"] = "MANUAL_REQUIRED"
        row["status_class"] = "warning"
        row["note"] = "Wajib dicek di browser real setelah app dijalankan; static lock hanya memastikan route/template/CSS siap diuji."
        items.append(row)
    return {
        "status": "PERLU CEK",
        "items": items,
        "manual_required_count": len(items),
    }


def _policy_stack(css: Dict[str, Any], route: Dict[str, Any], templates: Dict[str, Any], print_matrix: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dark_light_theme_lock": "PASS" if css.get("theme_lock_ok") else "CHECK",
        "css_build_lock": "PASS" if css.get("style_css_generated_lock") and css.get("build_version") == APP_VERSION else "CHECK",
        "global_filter_bar_v2": "PASS" if css.get("filter_lock_ok") else "CHECK",
        "zero_empty_panel": "PASS" if css.get("zero_empty_lock_ok") else "CHECK",
        "critical_routes": "PASS" if route.get("missing_count") == 0 else "CHECK",
        "critical_templates": "PASS" if templates.get("missing_count") == 0 else "CHECK",
        "print_preview_foundation": "PASS" if print_matrix.get("status") == "AMAN" else "CHECK",
        "db_mutation": "READ_ONLY_NO_DB_CHANGE",
    }


def build_final_visual_browser_qa_report() -> Dict[str, Any]:
    root = _project_root()
    endpoints = _extract_route_endpoints(root)
    css = _css_report(root)
    route = _critical_route_matrix(root, endpoints)
    templates = _template_matrix(root)
    print_matrix = _print_matrix(root)
    browser = _manual_browser_matrix()
    policy = _policy_stack(css, route, templates, print_matrix)

    blockers = []
    warnings = []
    if route["missing_count"]:
        blockers.append(f"Ada {route['missing_count']} critical endpoint hilang.")
    if templates["missing_count"]:
        blockers.append(f"Ada {templates['missing_count']} critical template hilang.")
    if css["status"] != "AMAN":
        warnings.append("CSS/theme/filter/zero-empty/browser QA lock perlu dicek.")
    if print_matrix["status"] != "AMAN":
        warnings.append("Fondasi print preview perlu dicek sebelum final browser sign-off.")
    warnings.append("Browser real QA tetap wajib dilakukan manual di desktop/tablet/mobile/print preview karena sandbox tidak menjalankan Flask browser penuh.")

    if blockers:
        decision = "STOP PATCH"
        overall = "BAHAYA"
        status_class = "danger"
    elif css["status"] == "AMAN" and print_matrix["status"] == "AMAN":
        decision = "READY FOR MANUAL BROWSER QA"
        overall = "AMAN DENGAN QA MANUAL"
        status_class = "success"
    else:
        decision = "BOLEH LANJUT DENGAN CATATAN"
        overall = "PERLU CEK"
        status_class = "warning"

    return {
        "app_version": APP_VERSION,
        "qa_version": FINAL_BROWSER_QA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall": {
            "status": overall,
            "decision": decision,
            "status_class": status_class,
            "summary": "Final visual browser QA lock menggabungkan route/template/CSS/print readiness dan matriks uji manual browser.",
            "blockers": blockers,
            "warnings": warnings,
        },
        "css": css,
        "critical_routes": route,
        "critical_templates": templates,
        "print_preview": print_matrix,
        "browser_matrix": browser,
        "policy_stack": policy,
        "next_actions": [
            "Jalankan app lokal setelah backup VERIFIED dan migration PRODUCTION jika fitur cicilan aset mau dipakai.",
            "Buka /settings/final-visual-qa lalu cek status route/template/CSS/print readiness.",
            "Lakukan manual browser QA di 1366px, 1280px, tablet, mobile 390px, dan Chrome Print Preview.",
            "Jika ada overflow/card kosong/print kepotong, patch visual kecil per halaman, jangan ubah DB.",
            "Setelah manual QA PASS, simpan full backup VERIFIED baru sebagai lock produksi.",
        ],
    }


def build_empty_final_visual_browser_qa_report(error_message: str) -> Dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "qa_version": FINAL_BROWSER_QA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall": {
            "status": "BAHAYA",
            "decision": "STOP PATCH",
            "status_class": "danger",
            "summary": "Final browser QA gagal dibangun.",
            "blockers": [error_message],
            "warnings": [],
        },
        "css": {},
        "critical_routes": {"items": []},
        "critical_templates": {"items": []},
        "print_preview": {"items": []},
        "browser_matrix": {"items": []},
        "policy_stack": {},
        "next_actions": ["Cek log Flask/terminal lalu ulangi Final Browser QA."],
    }
