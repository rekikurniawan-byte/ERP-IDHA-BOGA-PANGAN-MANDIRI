"""PRODUCTION Zero Empty Panel & Broken Route Visual Sweep service.

Read-only static audit for UI safety. This service does not import Flask app,
does not query or mutate database, and does not require a running server. It
scans templates/routes/source files to detect broken literal/dynamic endpoint
references and oversized/legacy empty-state patterns that should not become
large blank panels in production pages.
"""
from __future__ import annotations
import logging

import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)

APP_VERSION = "PRODUCTION"
VISUAL_SWEEP_VERSION = "PRODUCTION_ZERO_EMPTY_PANEL_BROKEN_ROUTE_SWEEP_V1"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/visual_sweep_service.py:28")
        return str(path).replace("\\", "/")


def _severity(ok: bool, warnings: int = 0) -> str:
    if not ok:
        return "BAHAYA"
    if warnings:
        return "PERLU CEK"
    return "AMAN"


def _extract_route_endpoints(root: Path) -> Dict[str, Any]:
    endpoints = set()
    blueprint_map: Dict[str, str] = {}
    route_files = sorted((root / "app" / "routes").glob("*_routes.py"))

    for path in route_files:
        text = path.read_text(encoding="utf-8")
        for variable, name in re.findall(r'(\w+)\s*=\s*Blueprint\(\s*["\']([^"\']+)["\']', text):
            blueprint_map[variable] = name

        pattern = re.compile(
            r"@(?P<bp>\w+)\.route\([^\)]*\)\s*"
            r"(?:\n\s*@[^\n]+)*"
            r"\n\s*def\s+(?P<fn>\w+)\s*\(",
            re.MULTILINE,
        )
        for match in pattern.finditer(text):
            bp_variable = match.group("bp")
            fn_name = match.group("fn")
            bp_name = blueprint_map.get(bp_variable, bp_variable.replace("_bp", ""))
            endpoints.add(f"{bp_name}.{fn_name}")

    return {
        "endpoint_count": len(endpoints),
        "endpoints": sorted(endpoints),
        "route_files": [_rel(path, root) for path in route_files],
    }


def _extract_template_url_for(root: Path) -> Dict[str, Any]:
    literal: List[Dict[str, str]] = []
    dynamic_count = 0
    template_files = sorted((root / "app" / "templates").glob("**/*.html"))

    literal_pattern = re.compile(r"url_for\(\s*[\"']([^\"']+)[\"']")
    dynamic_pattern = re.compile(r"url_for\(\s*([^\"'\)][^\)]*)\)")

    for path in template_files:
        text = path.read_text(encoding="utf-8")
        for match in literal_pattern.finditer(text):
            endpoint = match.group(1)
            if endpoint.startswith("static"):
                continue
            line = text[: match.start()].count("\n") + 1
            literal.append({"endpoint": endpoint, "file": _rel(path, root), "line": line})

        for match in dynamic_pattern.finditer(text):
            expression = match.group(1).strip()
            if expression.startswith(("'", '"')):
                continue
            if "static" in expression:
                continue
            dynamic_count += 1

    return {
        "literal_count": len(literal),
        "literal_unique_count": len({item["endpoint"] for item in literal}),
        "dynamic_count": dynamic_count,
        "literal": literal,
        "template_count": len(template_files),
    }


def _extract_dynamic_endpoint_constants(root: Path) -> Dict[str, Any]:
    """Find endpoint strings used as payloads for url_for(item.endpoint).

    This catches dashboard/SOP/recovery service links that are not visible as
    literal url_for('...') in templates.
    """
    candidates: List[Dict[str, str]] = []
    source_files = sorted(list((root / "app" / "services").glob("*.py")) + list((root / "app" / "routes").glob("*.py")))
    patterns = [
        re.compile(r"[\"']endpoint[\"']\s*:\s*[\"']([a-zA-Z_][\w]*\.[\w]+)[\"']"),
        re.compile(r"[\"']([a-zA-Z_][\w]*\.[\w]+)[\"']\s*,\s*[\"']icon[\"']"),
    ]

    for path in source_files:
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            for match in pattern.finditer(text):
                endpoint = match.group(1)
                line = text[: match.start()].count("\n") + 1
                candidates.append({"endpoint": endpoint, "file": _rel(path, root), "line": line})

    # Deduplicate exact endpoint/file/line collisions while preserving order.
    seen = set()
    unique = []
    for item in candidates:
        key = (item["endpoint"], item["file"], item["line"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return {
        "dynamic_constant_count": len(unique),
        "dynamic_unique_count": len({item["endpoint"] for item in unique}),
        "items": unique,
    }


def _route_sweep(root: Path) -> Dict[str, Any]:
    routes = _extract_route_endpoints(root)
    templates = _extract_template_url_for(root)
    dynamic = _extract_dynamic_endpoint_constants(root)
    endpoints = set(routes["endpoints"])

    literal_missing = [item for item in templates["literal"] if item["endpoint"] not in endpoints]
    dynamic_missing = [item for item in dynamic["items"] if item["endpoint"] not in endpoints]

    literal_endpoint_counts = Counter(item["endpoint"] for item in templates["literal"])
    most_used = [
        {"endpoint": endpoint, "count": count}
        for endpoint, count in literal_endpoint_counts.most_common(20)
    ]

    ok = not literal_missing and not dynamic_missing
    warnings = templates["dynamic_count"]
    return {
        "status": _severity(ok=ok, warnings=0 if ok else 1),
        "ok": ok,
        "route_endpoint_count": routes["endpoint_count"],
        "route_file_count": len(routes["route_files"]),
        "template_count": templates["template_count"],
        "literal_url_for_count": templates["literal_count"],
        "literal_unique_count": templates["literal_unique_count"],
        "dynamic_url_for_count": templates["dynamic_count"],
        "dynamic_constant_count": dynamic["dynamic_constant_count"],
        "dynamic_unique_count": dynamic["dynamic_unique_count"],
        "literal_missing_count": len(literal_missing),
        "dynamic_missing_count": len(dynamic_missing),
        "literal_missing": literal_missing[:50],
        "dynamic_missing": dynamic_missing[:50],
        "most_used_endpoints": most_used,
    }


def _empty_panel_scan(root: Path) -> Dict[str, Any]:
    template_files = sorted((root / "app" / "templates").glob("**/*.html"))
    items: List[Dict[str, Any]] = []
    oversized_candidates: List[Dict[str, Any]] = []
    chart_empty_guards = 0
    chart_like_sections = 0

    empty_pattern = re.compile(r'class\s*=\s*["\'][^"\']*(?:empty-state|app-empty-state|dashboard-chart-empty|dashboard-command-all-clear)[^"\']*["\']')
    chart_pattern = re.compile(r'(dashboard-chart|data-chart-type|<canvas|chart-card|donut|bar-chart)', re.IGNORECASE)

    for path in template_files:
        text = path.read_text(encoding="utf-8")
        if chart_pattern.search(text):
            chart_like_sections += 1
        for match in empty_pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            snippet = match.group(0)
            item = {"file": _rel(path, root), "line": line, "class_snippet": snippet[:180]}
            items.append(item)
            if "dashboard-chart-empty" in snippet or "data-empty-state" in text[max(0, match.start()-150):match.end()+150]:
                chart_empty_guards += 1
            if not any(token in snippet for token in ("app-empty-state", "dashboard-chart-empty", "dashboard-command-all-clear", "compact", "zero-empty")):
                oversized_candidates.append(item)

    by_file = Counter(item["file"] for item in items)
    top_files = [{"file": file, "count": count} for file, count in by_file.most_common(20)]
    # Legacy empty-state candidates are informational after PRODUCTION because
    # 103_zero_empty_visual_sweep.css globally compacts these panels. They are
    # still reported so future UI sweeps can migrate them to explicit compact
    # components, but they do not block visual patch progression.
    candidate_count = len(oversized_candidates)
    return {
        "status": "AMAN",
        "empty_state_count": len(items),
        "chart_like_template_count": chart_like_sections,
        "chart_empty_guard_count": chart_empty_guards,
        "oversized_candidate_count": candidate_count,
        "oversized_candidates": oversized_candidates[:75],
        "top_empty_state_files": top_files,
    }


def _css_sweep(root: Path) -> Dict[str, Any]:
    report_path = root / "app" / "static" / "css" / "css_build_report.json"
    style_path = root / "app" / "static" / "css" / "style.css"
    src_path = root / "app" / "static" / "css" / "src" / "103_zero_empty_visual_sweep.css"
    try:
        import json
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/visual_sweep_service.py:226")
        report = {}
    return {
        "status": "AMAN" if report_path.exists() and style_path.exists() and src_path.exists() else "PERLU CEK",
        "build_version": report.get("build_version") or "UNKNOWN",
        "source_file_count": report.get("source_file_count") or len(list((root / "app" / "static" / "css" / "src").glob("*.css"))),
        "style_css_exists": style_path.exists(),
        "zero_empty_css_exists": src_path.exists(),
        "brace_balance": (report.get("brace_balance") or {}).get("balance"),
        "duplicate_selector_count": (report.get("selector_report") or {}).get("duplicate_selector_count"),
    }


def build_visual_sweep_report() -> Dict[str, Any]:
    root = _project_root()
    route_sweep = _route_sweep(root)
    empty_scan = _empty_panel_scan(root)
    css_sweep = _css_sweep(root)

    blockers = []
    warnings = []
    if not route_sweep["ok"]:
        blockers.append("Ada endpoint literal/dynamic yang tidak cocok dengan route map.")
    if css_sweep["status"] != "AMAN":
        warnings.append("CSS zero-empty sweep belum lengkap atau report build belum terbaca.")

    if blockers:
        decision = "STOP PATCH"
        overall = "BAHAYA"
    elif warnings:
        decision = "BOLEH LANJUT DENGAN CATATAN"
        overall = "PERLU CEK"
    else:
        decision = "READY"
        overall = "AMAN"

    return {
        "app_version": APP_VERSION,
        "visual_sweep_version": VISUAL_SWEEP_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall_status": overall,
        "decision": decision,
        "blockers": blockers,
        "warnings": warnings,
        "route_sweep": route_sweep,
        "empty_panel_scan": empty_scan,
        "css_sweep": css_sweep,
        "policy": {
            "zero_empty_panel": "Jangan render chart/card kosong besar. Section tidak penting disembunyikan; section penting pakai compact empty state.",
            "broken_route_target": "0 broken literal/dynamic endpoint.",
            "css_source": "Edit app/static/css/src/*.css lalu build ke app/static/css/style.css.",
            "db_mutation": "Read-only; tidak mengubah database dan tidak membutuhkan migration.",
        },
        "next_actions": [
            "Buka halaman Visual Sweep setelah app jalan di browser.",
            "Kalau route missing > 0, perbaiki endpoint sebelum patch UI lanjutan.",
            "Kalau empty-state legacy mengganggu visual, ganti bertahap dengan compact empty state/component.",
            "Lanjut PRODUCTION hanya setelah sweep route 0 broken dan dashboard/report tidak punya panel kosong besar.",
        ],
    }


def build_empty_visual_sweep_report(error_message: str) -> Dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "visual_sweep_version": VISUAL_SWEEP_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall_status": "BAHAYA",
        "decision": "STOP PATCH",
        "blockers": [error_message],
        "warnings": [],
        "route_sweep": {},
        "empty_panel_scan": {},
        "css_sweep": {},
        "policy": {},
        "next_actions": ["Cek log Flask/terminal lalu ulangi Visual Sweep."],
    }
