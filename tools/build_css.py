#!/usr/bin/env python3
"""Final CSS build lock for PT Idha Boga Pangan Mandiri.

Do not edit app/static/css/style.css directly after PRODUCTION.
Edit app/static/css/src/*.css, then run:

    python tools/build_css.py

The builder keeps one browser-loaded output file while making the CSS source
modular and auditable.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

PROJECT_NAME = "PT Idha Boga Pangan Mandiri"
BUILD_VERSION = "FINAL-ZERO-DATA"
ROOT = Path(__file__).resolve().parents[1]
CSS_SRC_DIR = ROOT / "app" / "static" / "css" / "src"
CSS_OUTPUT = ROOT / "app" / "static" / "css" / "style.css"
REPORT_OUTPUT = ROOT / "app" / "static" / "css" / "css_build_report.json"

SOURCE_ORDER = [
    "00_tokens.css",
    "01_reset_base.css",
    "02_typography.css",
    "03_layout_shell.css",
    "04_sidebar_topbar.css",
    "05_page_header.css",
    "06_buttons_actions.css",
    "07_dropdowns.css",
    "08_cards_stats.css",
    "09_tables.css",
    "10_forms_filters.css",
    "11_badges_alerts_empty_state.css",
    "12_dashboard_charts.css",
    "13_print.css",
    "20_module_accounting.css",
    "21_module_finance.css",
    "22_module_operational.css",
    "23_module_production_delivery.css",
    "24_module_logistics.css",
    "25_module_canteen.css",
    "26_module_hr.css",
    "27_module_sop.css",
    "28_module_settings_security.css",
    "90_responsive.css",
    "99_utilities.css",
    "100_theme_black_white_lock.css",
    "101_dashboard_command_center.css",
    "102_global_filter_bar_v2.css",
    "103_zero_empty_visual_sweep.css",
    "104_asset_installment_foundation.css",
    "105_final_visual_browser_qa_lock.css",
    "106_visual_emergency_alignment.css",
    "107_ui_contrast_table_login_toggle_spacing_lock.css",
    "108_final_ui_system_consolidation_regression_repair.css",
    "109_final_targeted_ui_regression_cleanup.css",
    "112_universal_page_card_rhythm_lock.css",
    "113_full_module_spacing_coverage_lock.css",
    "114_card_body_utility_spacing_guard.css",
    "115_full_route_spacing_smoke_outlier_lock.css",
    "116_final_card_density_release_lock.css",
    "117_outlier_template_card_wrapper_symmetry_patch.css",
    "118_full_page_visual_outlier_sweep_lock.css",
    "119_dashboard_header_alignment_rebaseline_lock.css",
    "120_dashboard_owner_header_icon_color_lock.css",
    "121_revenue_explorer_icon_color_lock.css",
    "122_dashboard_demo_data_visual_balance_polish.css",
    "123_dark_mode_table_dashboard_contrast_polish.css",
    "124_form_grid_input_alignment_polish.css",
    "125_manual_backfill_row_ux_polish.css",
    "126_atomic_select_date_input_foundation.css",
    "127_atomic_date_select_rollout_hardening.css",
    "128_atomic_field_validation_mobile_polish.css",
    "129_atomic_confirm_alert_toast_foundation.css",
    "130_atomic_file_checkbox_numeric_polish.css",
    "131_centered_flash_notification_polish.css",
    "132_atomic_action_loading_double_submit_guard.css",
    "133_atomic_time_password_dropdown_ui_polish.css",
    "134_atomic_static_alert_empty_state_polish.css",
    "135_atomic_table_scroll_density_polish.css",
    "136_atomic_print_export_ui_polish.css",
    "137_atomic_textarea_filter_input_polish.css",
    "138_atomic_page_header_navigation_context_polish.css",
    "139_atomic_badge_metric_progress_polish.css",
    "140_atomic_card_section_layout_polish.css",
    "141_ui_regression_inline_js_cleanup.css",
]

HEADER = """/* ==================================================
   GENERATED FILE - DO NOT EDIT DIRECTLY
   Source: app/static/css/src/*.css
   Build: python tools/build_css.py
   Project: PT Idha Boga Pangan Mandiri
   Build version: FINAL-ZERO-DATA
   ================================================== */
"""


def _read_source_files() -> Tuple[List[Tuple[str, str]], List[str]]:
    errors: List[str] = []
    loaded: List[Tuple[str, str]] = []

    if not CSS_SRC_DIR.exists():
        return [], [f"CSS source folder missing: {CSS_SRC_DIR.relative_to(ROOT)}"]

    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            errors.append(f"Missing required CSS source: app/static/css/src/{filename}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            errors.append(f"Empty CSS source file: app/static/css/src/{filename}")
        loaded.append((filename, text.rstrip() + "\n"))

    extra_files = sorted(
        p.name for p in CSS_SRC_DIR.glob("*.css") if p.name not in set(SOURCE_ORDER)
    )
    if extra_files:
        errors.append("Unexpected CSS source file(s): " + ", ".join(extra_files))

    return loaded, errors


def _strip_comments_and_strings(css: str) -> str:
    """Return CSS with comments and string content neutralized for brace checks."""
    out: List[str] = []
    i = 0
    n = len(css)
    in_comment = False
    in_string: str | None = None
    escaped = False

    while i < n:
        ch = css[i]
        nxt = css[i + 1] if i + 1 < n else ""

        if in_comment:
            if ch == "*" and nxt == "/":
                in_comment = False
                out.append("  ")
                i += 2
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

        if in_string:
            if escaped:
                escaped = False
                out.append(" ")
            elif ch == "\\":
                escaped = True
                out.append(" ")
            elif ch == in_string:
                in_string = None
                out.append(" ")
            else:
                out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if ch == "/" and nxt == "*":
            in_comment = True
            out.append("  ")
            i += 2
            continue

        if ch in ('"', "'"):
            in_string = ch
            out.append(" ")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _brace_balance(css: str) -> Dict[str, object]:
    cleaned = _strip_comments_and_strings(css)
    balance = 0
    min_balance = 0
    for ch in cleaned:
        if ch == "{":
            balance += 1
        elif ch == "}":
            balance -= 1
            min_balance = min(min_balance, balance)
    return {
        "balance": balance,
        "has_negative_balance": min_balance < 0,
        "open_braces": cleaned.count("{"),
        "close_braces": cleaned.count("}"),
    }


def _normalize_selector(selector: str) -> str:
    selector = re.sub(r"\s+", " ", selector.strip())
    selector = re.sub(r"\s*([>+~,:])\s*", r"\1", selector)
    return selector


def _selector_report(css: str) -> Dict[str, object]:
    cleaned = _strip_comments_and_strings(css)
    selectors: List[str] = []
    cursor = 0

    for match in re.finditer(r"([^{}]+)\{", cleaned):
        raw = match.group(1)
        # Keep only text after the previous close brace/semicolon/newline-heavy at-rule marker.
        candidate = raw.split("}")[-1].strip()
        if not candidate or candidate.startswith("@"):
            cursor = match.end()
            continue
        if "@" in candidate and candidate.rfind("@") > candidate.rfind(";"):
            candidate = candidate[candidate.rfind("@") + 1 :].strip()
        normalized = _normalize_selector(candidate)
        # PRODUCTION: do not count keyframe steps as duplicate CSS selectors.
        # The previous flat selector audit counted `from` and `to` inside
        # @keyframes blocks as normal selectors, creating LOW-risk false positives.
        if normalized in {"from", "to"} or re.fullmatch(r"(?:\d+(?:\.\d+)?%)(?:,(?:\d+(?:\.\d+)?%))*", normalized):
            cursor = match.end()
            continue
        if normalized:
            selectors.append(normalized)
        cursor = match.end()

    counts = Counter(selectors)
    duplicates = [
        {"selector": selector, "count": count}
        for selector, count in counts.most_common()
        if count > 1
    ]
    return {
        "selector_count": len(selectors),
        "unique_selector_count": len(counts),
        "duplicate_selector_count": len(duplicates),
        "top_duplicates": duplicates[:75],
    }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> int:
    loaded, errors = _read_source_files()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output_parts = [HEADER]
    source_reports = []
    for filename, text in loaded:
        rel = f"app/static/css/src/{filename}"
        output_parts.append(
            "\n/* ==================================================\n"
            f"   BEGIN SOURCE: {rel}\n"
            "   ================================================== */\n\n"
        )
        output_parts.append(text)
        source_reports.append(
            {
                "file": rel,
                "bytes": len(text.encode("utf-8")),
                "lines": text.count("\n"),
                "sha256": _sha256(text),
            }
        )

    output_css = "".join(output_parts).rstrip() + "\n"
    brace = _brace_balance(output_css)
    selectors = _selector_report(output_css)

    if brace["balance"] != 0 or brace["has_negative_balance"]:
        print("ERROR: CSS brace balance failed.", file=sys.stderr)
        print(json.dumps(brace, indent=2), file=sys.stderr)
        return 1

    CSS_OUTPUT.write_text(output_css, encoding="utf-8")

    report = {
        "build_version": BUILD_VERSION,
        "project": PROJECT_NAME,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(CSS_SRC_DIR.relative_to(ROOT)),
        "output_file": str(CSS_OUTPUT.relative_to(ROOT)),
        "source_file_count": len(loaded),
        "source_order": SOURCE_ORDER,
        "sources": source_reports,
        "output": {
            "bytes": len(output_css.encode("utf-8")),
            "lines": output_css.count("\n"),
            "sha256": _sha256(output_css),
        },
        "checks": {
            "required_sources_present": True,
            "empty_source_files": 0,
            "unexpected_source_files": 0,
            "brace_balance": brace,
            "duplicate_selector_report_generated": True,
        },
        "selector_report": selectors,
        "notes": [
            "PRODUCTION keeps the modular build lock and adds final compact empty-state and card-density rules across dashboard, operational, delivery, production, warung, receivables, and expense drilldown pages.",
            "Duplicate selectors are reported for audit and are not treated as build failures; final browser QA styles live in 105_final_visual_browser_qa_lock.css and visual alignment overrides live in 106_visual_emergency_alignment.css final density overrides live in 111_empty_state_card_density_final_lock.css, and the PRODUCTION universal spacing guard lives in 112_universal_page_card_rhythm_lock.css, and PRODUCTION full module coverage lives in 113_full_module_spacing_coverage_lock.css, and PRODUCTION card body/utility spacing guard lives in 114_card_body_utility_spacing_guard.css, PRODUCTION route-smoke outlier lock lives in 115_full_route_spacing_smoke_outlier_lock.css, and PRODUCTION final release lock lives in 116_final_card_density_release_lock.css, PRODUCTION outlier template card symmetry lives in 117_outlier_template_card_wrapper_symmetry_patch.css, and PRODUCTION full page visual outlier sweep lives in 118_full_page_visual_outlier_sweep_lock.css. PRODUCTION performs legacy CSS/JSON/HTML deletion audit and removes stale root validation artifacts only. PRODUCTION performs non-destructive CSS consolidation and duplicate selector reduction audit; CSS sources are not removed in that stage because they are still part of the locked build chain. PRODUCTION starts CSS Consolidation Batch 1 by removing exact same-file duplicate low-risk rules only, without touching core layout/theme/table/button/card selectors or deleting runtime CSS sources. PRODUCTION reduces selected low-risk cross-file exact duplicates, and PRODUCTION performs protected duplicate selector semantic audit without deleting CSS source/runtime templates, and PRODUCTION performs low-risk-only consolidation by deleting the redundant legacy posting-status overflow rule and excluding keyframe steps from duplicate-selector reporting. PRODUCTION performs medium-risk semantic audit only and does not delete medium-risk CSS, while PRODUCTION performs final low-risk cleanup stop lock and does not delete the remaining complementary cascade selectors. PRODUCTION performs release stability and runtime-smoke final static lock; it does not delete runtime CSS/template/source files. PRODUCTION adds dashboard owner header left-alignment and rebaselines the final production guard after the approved visual change. PRODUCTION is the final release handoff and clean-install lock; it does not change runtime CSS sources, templates, database, routes, models, services, or transaction logic. PRODUCTION polishes Dashboard Owner only: title/header alignment to the left and colored icons for KPI, reminder, and detail link cards.",
            "Do not edit app/static/css/style.css directly after this build lock.",
        ],
    }
    REPORT_OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("CSS build PASS")
    print(f"Output: {CSS_OUTPUT.relative_to(ROOT)}")
    print(f"Report: {REPORT_OUTPUT.relative_to(ROOT)}")
    print(f"Sources: {len(loaded)}")
    print(f"Lines: {report['output']['lines']}")
    print(f"Duplicate selector groups: {selectors['duplicate_selector_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
