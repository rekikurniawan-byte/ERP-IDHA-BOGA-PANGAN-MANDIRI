from __future__ import annotations
import logging

import ast
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from flask import current_app

logger = logging.getLogger(__name__)


ATOMIC_AUDIT_MAP_VERSION = "PRODUCTION"
ATOMIC_AUDIT_MAP_SCHEMA_VERSION = "PRODUCTION_ATOMIC_TRANSACTION_AUDIT_MAP_V3"
ATOMIC_TRANSACTION_POLICY_VERSION = "PRODUCTION_ATOMIC_TRANSACTION_POLICY_V3"

_SCAN_DIRS = ("app/routes", "app/services")
_EXCLUDED_FILES = {
    "app/services/atomic_transaction_audit_map_service.py",
}

_COMMIT_PATTERN = re.compile(r"\bdb\.session\.commit\s*\(")
_ROLLBACK_PATTERN = re.compile(r"\bdb\.session\.rollback\s*\(")
_BEGIN_PATTERN = re.compile(r"\bdb\.session\.begin\s*\(")
_FLUSH_PATTERN = re.compile(r"\bdb\.session\.flush\s*\(")
_ADD_PATTERN = re.compile(r"\bdb\.session\.add(?:_all)?\s*\(")
_DELETE_PATTERN = re.compile(r"\bdb\.session\.delete\s*\(")
_AUDIT_PATTERN = re.compile(r"\brecord_(?:critical_)?audit_log\s*\(")
_ATOMIC_GUARD_PATTERN = re.compile(r"\batomic_business_action\s*\(")

_BUSINESS_KEYWORDS = {
    "invoice": ("Invoice", "invoice", "INVOICE"),
    "payment": ("Payment", "payment", "PAYMENT", "paid", "piutang"),
    "journal": ("Journal", "journal", "JOURNAL", "debit", "credit", "posting"),
    "cash_bank": ("CashBank", "cash_bank", "ledger", "kas", "bank"),
    "stock": ("Stock", "stock", "movement", "warehouse", "item_id"),
    "procurement": ("Procurement", "procurement", "supplier_bill", "SupplierBill", "supplier_payment"),
    "payroll": ("Payroll", "payroll", "salary", "employee"),
    "delivery": ("Delivery", "delivery", "received", "proof", "driver"),
    "canteen": ("Canteen", "canteen", "debt", "warung", "sale"),
    "order": ("Order", "order", "production", "snapshot", "hpp"),
    "asset": ("FixedAsset", "fixed_asset", "depreciation", "asset"),
    "upload": ("upload", "save", "file_path", "DigitalAttachment", "attachment"),
    "user_role": ("User", "Role", "password", "is_active", "permission"),
}

_AREA_RULES: Tuple[Tuple[str, str], ...] = (
    ("accounting", "Accounting"),
    ("finance", "Finance"),
    ("cash_bank", "Finance"),
    ("accounts_payable", "Finance/AP"),
    ("advance", "Finance"),
    ("fixed_asset", "Finance/Fixed Asset"),
    ("transport_expense", "Finance"),
    ("operational_expense", "Finance"),
    ("invoice", "Finance"),
    ("logistics", "Logistics"),
    ("stock", "Logistics"),
    ("hpp", "Logistics/HPP"),
    ("hr", "HR"),
    ("payroll", "HR"),
    ("delivery", "Delivery"),
    ("canteen", "Canteen"),
    ("operational", "Operational"),
    ("production", "Production"),
    ("costing", "Costing/HPP"),
    ("master", "Master Data"),
    ("settings", "Settings/Security"),
    ("user_management", "Settings/Security"),
    ("company_settings", "Settings/Security"),
    ("digital_attachment", "Settings/Security"),
    ("backup", "Backup/Recovery"),
    ("system_health", "Backup/Recovery"),
    ("audit_log", "Audit/Security"),
    ("auth", "Auth/Security"),
    ("notification", "Notification"),
)

_PRIORITY_HINTS = {
    "Accounting": "Journal post/reverse/generate harus dipusatkan ke service atomic agar tidak ada jurnal/header/detail yatim.",
    "Finance": "Invoice/payment/cash-bank ledger wajib satu transaksi atomic karena menyentuh invoice, payment, ledger, dan jurnal.",
    "Finance/AP": "Supplier bill/payment perlu atomic guard agar hutang, kas/bank, dan jurnal tidak setengah masuk.",
    "Finance/Fixed Asset": "Pembelian aset, penyusutan, dan posting akuntansi perlu service boundary tunggal.",
    "Logistics": "Procurement, stock movement, adjustment, dan supplier flow harus rollback bersama jika salah satu langkah gagal.",
    "Logistics/HPP": "Commit konsumsi stok dari snapshot HPP wajib atomic karena efeknya ke stok, HPP, dan audit produksi.",
    "HR": "Payroll finalize/pay/posting perlu atomic guard supaya payroll, payment, ledger, dan jurnal tetap sinkron.",
    "Delivery": "Receive delivery + proof upload + status update wajib atomic semantik; file fisik perlu cleanup jika DB rollback.",
    "Canteen": "Warung cash/debt/payment perlu atomic service agar sale, debt, payment, dan ledger tidak yatim.",
    "Operational": "Order lock/revision/production generation perlu boundary agar order, detail, production, dan snapshot konsisten.",
    "Production": "Generate/complete production harus sinkron dengan order/delivery/stok jika nanti ada konsumsi bahan otomatis.",
    "Master Data": "Master data banyak route-level commit; risiko bisnis lebih rendah tetapi tetap perlu service pattern dan audit konsisten.",
    "Settings/Security": "Aksi user/company/lampiran sudah mulai guard; tetap perlu atomic helper untuk mutasi sensitif.",
    "Backup/Recovery": "Backup/restore harus tetap tidak memakai transaksi bisnis aktif; restore active nanti wajib terpisah dan manual guarded.",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _project_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_audit_map_service.py:115")
        return path.as_posix()


def _business_area(relative_path: str) -> str:
    lowered = relative_path.lower()
    for needle, area in _AREA_RULES:
        if needle in lowered:
            return area
    return "General"


def _function_ranges(source: str) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [
            {
                "name": "<syntax-error>",
                "qualname": "<syntax-error>",
                "lineno": 1,
                "end_lineno": max(len(source.splitlines()), 1),
                "kind": "module",
            }
        ]

    ranges: List[Dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: List[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:  # noqa: ANN401
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:  # noqa: ANN401
            qualname = ".".join([*self.parents, node.name]) if self.parents else node.name
            ranges.append(
                {
                    "name": node.name,
                    "qualname": qualname,
                    "lineno": getattr(node, "lineno", 1),
                    "end_lineno": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                    "kind": "function",
                }
            )
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    ranges.sort(key=lambda item: (int(item.get("lineno") or 1), -int(item.get("end_lineno") or 1)))
    return ranges


def _count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def _keyword_hits(text: str) -> Dict[str, int]:
    hits: Dict[str, int] = {}
    for key, words in _BUSINESS_KEYWORDS.items():
        total = sum(text.count(word) for word in words)
        if total:
            hits[key] = total
    return hits


def _extract_commit_lines(lines: List[str], start_lineno: int) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    patterns = (
        ("commit", _COMMIT_PATTERN),
        ("rollback", _ROLLBACK_PATTERN),
        ("begin", _BEGIN_PATTERN),
        ("flush", _FLUSH_PATTERN),
    )
    for offset, line in enumerate(lines):
        for kind, pattern in patterns:
            if pattern.search(line):
                findings.append(
                    {
                        "kind": kind,
                        "line": start_lineno + offset,
                        "snippet": line.strip()[:180],
                    }
                )
    return findings[:12]


def _risk_score(*, relative_path: str, area: str, counts: Dict[str, int], keyword_hits: Dict[str, int], is_route: bool, audit_calls: int) -> Tuple[str, int, List[str]]:
    score = 0
    reasons: List[str] = []

    commit_count = counts.get("commit", 0)
    rollback_count = counts.get("rollback", 0)
    begin_count = counts.get("begin", 0)
    atomic_guard_count = counts.get("atomic_guard", 0)
    flush_count = counts.get("flush", 0)
    add_count = counts.get("add", 0)
    delete_count = counts.get("delete", 0)

    if commit_count:
        score += commit_count * 10
        reasons.append(f"Ada {commit_count} db.session.commit().")
    if rollback_count:
        score += max(rollback_count * 2, 1)
    if begin_count == 0 and atomic_guard_count == 0 and commit_count:
        score += 12
        reasons.append("Belum terlihat db.session.begin()/atomic_business_action sebagai boundary atomic eksplisit.")
    if commit_count and rollback_count == 0:
        score += 8
        reasons.append("Commit ada, rollback eksplisit tidak terlihat pada scope ini.")
    if commit_count > 1:
        score += 10
        reasons.append("Lebih dari satu commit dalam scope yang sama.")
    if is_route and commit_count:
        score += 8
        reasons.append("Commit berada di route; lebih aman dipindah ke service atomic.")
    if flush_count and commit_count:
        score += 4
        reasons.append("Ada flush sebelum commit; perlu pastikan rollback menyapu semua efek.")
    if delete_count:
        score += 6
        reasons.append("Ada delete DB; perlu audit + guard + rollback jelas.")
    if add_count > 3 and commit_count:
        score += 5
        reasons.append("Banyak add sebelum commit; rawan header/detail yatim jika error tengah jalan.")

    critical_keyword_count = sum(keyword_hits.values())
    if critical_keyword_count:
        score += min(critical_keyword_count * 2, 18)
        reasons.append("Terdeteksi keyword transaksi bisnis kritis.")

    if area in {"Accounting", "Finance", "Finance/AP", "Logistics", "Logistics/HPP", "HR", "Delivery", "Canteen"} and commit_count:
        score += 8
        reasons.append(f"Area {area} punya dampak lintas data/jurnal/stok/kas.")

    if audit_calls == 0 and commit_count and area in {"Accounting", "Finance", "Finance/AP", "Logistics", "HR", "Delivery", "Canteen", "Settings/Security"}:
        score += 4
        reasons.append("Audit call tidak terlihat dalam scope ini; perlu dicek di service pemanggil/lanjutan.")

    if begin_count:
        score = max(score - 15, 0)
        reasons.append("Ada db.session.begin(); tetap perlu review boundary dan nesting.")
    if atomic_guard_count:
        score = max(score - 18, 0)
        reasons.append("Sudah memakai atomic_business_action PRODUCTION; tetap perlu smoke test runtime.")

    if score >= 55:
        level = "CRITICAL"
    elif score >= 35:
        level = "HIGH"
    elif score >= 16:
        level = "MEDIUM"
    else:
        level = "LOW"

    return level, score, list(dict.fromkeys(reasons))


def _scan_scope(relative_path: str, source_lines: List[str], scope: Dict[str, Any], area: str) -> Dict[str, Any] | None:
    start = int(scope.get("lineno") or 1)
    end = int(scope.get("end_lineno") or start)
    text = "\n".join(source_lines[start - 1 : end])
    counts = {
        "commit": _count(_COMMIT_PATTERN, text),
        "rollback": _count(_ROLLBACK_PATTERN, text),
        "begin": _count(_BEGIN_PATTERN, text),
        "atomic_guard": _count(_ATOMIC_GUARD_PATTERN, text),
        "flush": _count(_FLUSH_PATTERN, text),
        "add": _count(_ADD_PATTERN, text),
        "delete": _count(_DELETE_PATTERN, text),
    }
    audit_calls = _count(_AUDIT_PATTERN, text)
    if not any(counts.values()) and not audit_calls:
        return None

    keyword_hits = _keyword_hits(text)
    is_route = "/routes/" in f"/{relative_path}"
    level, score, reasons = _risk_score(
        relative_path=relative_path,
        area=area,
        counts=counts,
        keyword_hits=keyword_hits,
        is_route=is_route,
        audit_calls=audit_calls,
    )

    return {
        "file": relative_path,
        "area": area,
        "scope": scope.get("qualname") or scope.get("name") or "<module>",
        "kind": scope.get("kind") or "function",
        "line_start": start,
        "line_end": end,
        "counts": counts,
        "audit_calls": audit_calls,
        "keyword_hits": keyword_hits,
        "risk_level": level,
        "risk_score": score,
        "risk_reasons": reasons,
        "transaction_boundary_status": "EXPLICIT_BEGIN" if counts.get("begin") else ("COMMIT_WITHOUT_EXPLICIT_BEGIN" if counts.get("commit") else "NO_COMMIT"),
        "recommendation": _recommendation(area, counts, keyword_hits, is_route),
        "line_findings": _extract_commit_lines(source_lines[start - 1 : end], start),
    }


def _recommendation(area: str, counts: Dict[str, int], keyword_hits: Dict[str, int], is_route: bool) -> str:
    if not counts.get("commit"):
        return "Tidak ada commit pada scope ini; cukup pastikan caller memiliki transaksi atomic."

    if is_route:
        return "Pindahkan mutasi bisnis ke service function atomic; route cukup validasi input, panggil service, lalu render/redirect."

    if area in {"Accounting", "Finance", "Finance/AP", "Logistics", "Logistics/HPP", "HR", "Delivery", "Canteen"}:
        return "Bungkus seluruh aksi bisnis dalam satu boundary atomic, validasi sebelum commit, dan pastikan audit dicatat setelah state konsisten."

    if keyword_hits:
        return "Review apakah commit ini menyentuh lebih dari satu tabel. Jika iya, jadikan service atomic reusable."

    return "Risiko rendah-menengah; tetap standarize commit/rollback dan audit jika data sensitif."


def _scan_file(path: Path, root: Path) -> Dict[str, Any]:
    relative_path = _relative(path, root)
    source = _safe_read(path)
    source_lines = source.splitlines()
    area = _business_area(relative_path)
    scopes = _function_ranges(source)

    records: List[Dict[str, Any]] = []
    for scope in scopes:
        record = _scan_scope(relative_path, source_lines, scope, area)
        if record:
            records.append(record)

    file_counts = {
        "commit": _count(_COMMIT_PATTERN, source),
        "rollback": _count(_ROLLBACK_PATTERN, source),
        "begin": _count(_BEGIN_PATTERN, source),
        "atomic_guard": _count(_ATOMIC_GUARD_PATTERN, source),
        "flush": _count(_FLUSH_PATTERN, source),
        "add": _count(_ADD_PATTERN, source),
        "delete": _count(_DELETE_PATTERN, source),
        "audit": _count(_AUDIT_PATTERN, source),
    }

    return {
        "file": relative_path,
        "area": area,
        "counts": file_counts,
        "records": records,
        "has_commit_without_begin": file_counts["commit"] > 0 and file_counts["begin"] == 0,
    }


def _status_class(level: str) -> str:
    return {
        "CRITICAL": "danger",
        "HIGH": "danger",
        "MEDIUM": "warning",
        "LOW": "info",
        "PASS": "success",
        "WARNING": "warning",
    }.get(str(level or "").upper(), "secondary")


def _build_area_rollups(file_reports: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rollups: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "area": "",
        "file_count": 0,
        "function_count": 0,
        "commit_count": 0,
        "rollback_count": 0,
        "begin_count": 0,
        "flush_count": 0,
        "critical_count": 0,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "risk_score": 0,
        "top_files": [],
    })

    for file_report in file_reports:
        area = str(file_report.get("area") or "General")
        rollup = rollups[area]
        rollup["area"] = area
        rollup["file_count"] += 1
        counts = file_report.get("counts") or {}
        rollup["commit_count"] += int(counts.get("commit") or 0)
        rollup["rollback_count"] += int(counts.get("rollback") or 0)
        rollup["begin_count"] += int(counts.get("begin") or 0)
        rollup["flush_count"] += int(counts.get("flush") or 0)
        if counts.get("commit"):
            rollup["top_files"].append({"file": file_report.get("file"), "commit_count": counts.get("commit"), "begin_count": counts.get("begin")})
        for record in file_report.get("records") or []:
            rollup["function_count"] += 1
            level = str(record.get("risk_level") or "LOW")
            if level == "CRITICAL":
                rollup["critical_count"] += 1
            elif level == "HIGH":
                rollup["high_count"] += 1
            elif level == "MEDIUM":
                rollup["medium_count"] += 1
            else:
                rollup["low_count"] += 1
            rollup["risk_score"] += int(record.get("risk_score") or 0)

    results: List[Dict[str, Any]] = []
    for item in rollups.values():
        if item["critical_count"] > 0 or item["risk_score"] >= 100:
            level = "CRITICAL"
        elif item["high_count"] > 0 or item["risk_score"] >= 50:
            level = "HIGH"
        elif item["medium_count"] > 0 or item["commit_count"] > 0:
            level = "MEDIUM"
        else:
            level = "LOW"
        item["risk_level"] = level
        item["status_class"] = _status_class(level)
        item["recommendation"] = _PRIORITY_HINTS.get(item["area"], "Standarkan transaksi ke service atomic jika ada mutasi lebih dari satu tabel.")
        item["top_files"] = sorted(item["top_files"], key=lambda row: int(row.get("commit_count") or 0), reverse=True)[:5]
        results.append(item)

    return sorted(results, key=lambda row: (int(row.get("risk_score") or 0), int(row.get("commit_count") or 0)), reverse=True)


def _build_priority_patches(area_rollups: List[Dict[str, Any]], records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    priority_order = [
        "Finance",
        "Accounting",
        "Logistics",
        "Logistics/HPP",
        "HR",
        "Canteen",
        "Delivery",
        "Finance/AP",
        "Operational",
        "Production",
        "Master Data",
        "Settings/Security",
    ]
    rollup_by_area = {str(item.get("area")): item for item in area_rollups}
    priorities: List[Dict[str, Any]] = []

    for area in priority_order:
        rollup = rollup_by_area.get(area)
        if not rollup or int(rollup.get("commit_count") or 0) <= 0:
            continue
        area_records = [record for record in records if record.get("area") == area and record.get("counts", {}).get("commit")]
        top_records = sorted(area_records, key=lambda row: int(row.get("risk_score") or 0), reverse=True)[:5]
        priorities.append(
            {
                "area": area,
                "risk_level": rollup.get("risk_level"),
                "status_class": rollup.get("status_class"),
                "commit_count": rollup.get("commit_count"),
                "begin_count": rollup.get("begin_count"),
                "why": rollup.get("recommendation"),
                "next_patch": _next_patch_label(area),
                "top_records": top_records,
            }
        )

    return priorities


def _next_patch_label(area: str) -> str:
    labels = {
        "Finance": "PRODUCTION Finance atomic guard",
        "Accounting": "PRODUCTION Accounting posting atomic guard",
        "Logistics": "PRODUCTION Logistics/procurement/stock atomic guard",
        "Logistics/HPP": "PRODUCTION HPP stock consumption atomic guard",
        "HR": "PRODUCTION Payroll atomic guard",
        "Canteen": "PRODUCTION Canteen sale/debt/payment atomic guard",
        "Delivery": "PRODUCTION Delivery receive/proof atomic guard",
        "Finance/AP": "PRODUCTION Supplier payable atomic guard",
        "Operational": "PRODUCTION Order lock/revision atomic guard",
        "Production": "PRODUCTION Production atomic guard",
        "Master Data": "PRODUCTION Master data commit cleanup",
        "Settings/Security": "PRODUCTION Settings sensitive mutation atomic helper",
    }
    return labels.get(area, "PRODUCTION atomic guard follow-up")


def _format_summary(records: List[Dict[str, Any]], file_reports: List[Dict[str, Any]], area_rollups: List[Dict[str, Any]]) -> Dict[str, Any]:
    commit_total = sum(int(file_report.get("counts", {}).get("commit") or 0) for file_report in file_reports)
    rollback_total = sum(int(file_report.get("counts", {}).get("rollback") or 0) for file_report in file_reports)
    begin_total = sum(int(file_report.get("counts", {}).get("begin") or 0) for file_report in file_reports)
    atomic_guard_total = sum(int(file_report.get("counts", {}).get("atomic_guard") or 0) for file_report in file_reports)
    route_commit_total = sum(int(file_report.get("counts", {}).get("commit") or 0) for file_report in file_reports if "/routes/" in f"/{file_report.get('file')}")
    service_commit_total = sum(int(file_report.get("counts", {}).get("commit") or 0) for file_report in file_reports if "/services/" in f"/{file_report.get('file')}")
    high_or_more = [record for record in records if record.get("risk_level") in {"CRITICAL", "HIGH"}]
    without_begin_files = [file_report for file_report in file_reports if file_report.get("has_commit_without_begin")]

    if commit_total and begin_total == 0 and atomic_guard_total == 0:
        status = "PERLU C2"
        status_class = "danger"
        summary = "Banyak commit ditemukan tanpa boundary db.session.begin()/atomic_business_action eksplisit. C2 wajib patch bertahap per modul."
    elif high_or_more:
        status = "C2 BERJALAN" if atomic_guard_total else "PERLU REVIEW"
        status_class = "warning"
        summary = "Atomic guard PRODUCTION sudah mulai terpasang, tapi masih ada transaksi high risk yang perlu review/patch lanjutan." if atomic_guard_total else "Ada transaksi high risk yang perlu review atomic boundary."
    else:
        status = "TERKONTROL"
        status_class = "success"
        summary = "Tidak ada temuan atomic high risk besar dari static scan."

    return {
        "status": status,
        "status_class": status_class,
        "summary": summary,
        "file_scanned_count": len(file_reports),
        "function_record_count": len(records),
        "commit_total": commit_total,
        "rollback_total": rollback_total,
        "begin_total": begin_total,
        "atomic_guard_total": atomic_guard_total,
        "route_commit_total": route_commit_total,
        "service_commit_total": service_commit_total,
        "file_without_begin_count": len(without_begin_files),
        "critical_record_count": sum(1 for record in records if record.get("risk_level") == "CRITICAL"),
        "high_record_count": sum(1 for record in records if record.get("risk_level") == "HIGH"),
        "medium_record_count": sum(1 for record in records if record.get("risk_level") == "MEDIUM"),
        "low_record_count": sum(1 for record in records if record.get("risk_level") == "LOW"),
        "area_count": len(area_rollups),
        "c2_scope_note": "PRODUCTION melanjutkan atomic_business_action pada modul prioritas tanpa migration dan tanpa mengubah DB aktif.",
    }


def build_atomic_transaction_audit_map() -> Dict[str, Any]:
    """Build a read-only atomic transaction risk map from project source code.

    PRODUCTION has started patching priority atomic guard flows. This page still scans Python
    routes/services so the next C2 patches can target the highest-risk business
    actions first instead of changing many forms/routes blindly.
    """
    root = _project_root()
    file_reports: List[Dict[str, Any]] = []

    for scan_dir in _SCAN_DIRS:
        base = root / scan_dir
        if not base.exists():
            continue
        for path in sorted(base.glob("*.py")):
            relative_path = _relative(path, root)
            if relative_path in _EXCLUDED_FILES:
                continue
            file_report = _scan_file(path, root)
            counts = file_report.get("counts") or {}
            if any(int(counts.get(key) or 0) for key in ("commit", "rollback", "begin", "flush", "delete")) or file_report.get("records"):
                file_reports.append(file_report)

    records = [record for file_report in file_reports for record in (file_report.get("records") or [])]
    records = sorted(records, key=lambda row: (int(row.get("risk_score") or 0), int(row.get("counts", {}).get("commit") or 0)), reverse=True)
    area_rollups = _build_area_rollups(file_reports)
    priorities = _build_priority_patches(area_rollups, records)
    summary = _format_summary(records, file_reports, area_rollups)

    return {
        "schema_version": ATOMIC_AUDIT_MAP_SCHEMA_VERSION,
        "app_version": ATOMIC_AUDIT_MAP_VERSION,
        "policy_version": ATOMIC_TRANSACTION_POLICY_VERSION,
        "checked_at": _now_iso(),
        "summary": summary,
        "area_rollups": area_rollups,
        "priority_patches": priorities,
        "top_risk_records": records[:40],
        "file_reports": sorted(file_reports, key=lambda row: (int(row.get("counts", {}).get("commit") or 0), str(row.get("file") or "")), reverse=True),
        "rules": {
            "atomic_rule": "Satu aksi bisnis = satu transaksi database atomic. Jika satu langkah gagal, semua rollback.",
            "c2_boundary": "C2 memasang atomic guard bertahap. Sisa commit yang belum ter-patch tetap terlihat untuk C2 lanjutan.",
            "preferred_pattern": "Route validasi input → service atomic → commit sekali → audit → redirect/render.",
            "avoid_pattern": "Commit banyak tersebar di route/service tanpa boundary eksplisit dan tanpa rollback terukur.",
        },
    }
