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
FORBIDDEN_CSS_FILENAME_WORDS = ("final", "lock", "fix", "override", "repair", "cleanup", "polish")
STATUS_TOKEN_NAMES = ("success", "warning", "danger", "info")
VAR_REFERENCE_RE = re.compile(r"var\(\s*--([a-zA-Z0-9_-]+)(?:\s*,\s*([^)]+))?\)")
IMPORTANT_COUNT_METHOD = "literal-token-count-in-source-order"
# Literal-token count across the ordered source files. Ratchet DOWNWARD only:
# lower it whenever a cleanup lands, never raise it to make a build pass.
# 8,643 (counted matching lines, not declarations) -> 8,728 (declarations)
# -> 6,625 after Fase 4 removed 1,874 dead !important declarations that a
# later rule with the same selector set and at-rule context already beat
# -> 6,618 after dropping rules keyed to legacy data-theme values that
# base.html can no longer produce
# -> 6,372 after dropping rules that require a class no element ever carries
# -> 6,363 after dropping the half of 157_dark_card_contrast_rescue_lock.css
# whose selectors matched nothing across 1,984 page visits.
# See tools/css_dead_declarations.py and tools/css_selector_liveness.py.
IMPORTANT_BASELINE_COUNT = 6363

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
    "29_module_master.css",
    "30_ui_primitives.css",
    "31_ui_patterns.css",
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
    "142_portal_responsive_web.css",
    "143_erp_ui_system_final_override.css",
    "144_end_to_end_ui_ux_sweep.css",
    "145_no_gradient_lock.css",
    "146_portal_contrast_lock.css",
    "147_global_ui_ux_density_lock.css",
    "148_portal_executive_polish_lock.css",
    "149_portal_topbar_compact_lock.css",
    "150_portal_topbar_single_row_lock.css",
    "151_portal_topbar_collision_fix.css",
    "152_portal_topbar_structural_grid_fix.css",
    "153_portal_topbar_no_avatar_lock.css",
    "154_global_calm_interface_lock.css",
    "155_global_layout_balance_lock.css",
    "156_global_minimal_clarity_lock.css",
    "157_dark_card_contrast_rescue_lock.css",
    "158_portal_feature_dark_summary_contrast_lock.css",
    "159_portal_summary_grid_spacing_lock.css",
    "160_global_typography_weight_slim_lock.css",
    "161_portal_component_precision_lock.css",
    "162_portal_neutral_metric_card_lock.css",
    "163_portal_active_button_inner_box_lock.css",
    "164_global_flash_toast_compact_lock.css",
    "165_global_flash_toast_redesign_lock.css",
    "166_password_button_surface_lock.css",
    "167_public_auth_register_clean_lock.css",
]

LEGACY_FORBIDDEN_CSS_SOURCE_NAMES = {
    "100_theme_black_white_lock.css",
    "105_final_visual_browser_qa_lock.css",
    "107_ui_contrast_table_login_toggle_spacing_lock.css",
    "108_final_ui_system_consolidation_regression_repair.css",
    "109_final_targeted_ui_regression_cleanup.css",
    "112_universal_page_card_rhythm_lock.css",
    "113_full_module_spacing_coverage_lock.css",
    "115_full_route_spacing_smoke_outlier_lock.css",
    "116_final_card_density_release_lock.css",
    "118_full_page_visual_outlier_sweep_lock.css",
    "119_dashboard_header_alignment_rebaseline_lock.css",
    "120_dashboard_owner_header_icon_color_lock.css",
    "121_revenue_explorer_icon_color_lock.css",
    "122_dashboard_demo_data_visual_balance_polish.css",
    "123_dark_mode_table_dashboard_contrast_polish.css",
    "124_form_grid_input_alignment_polish.css",
    "125_manual_backfill_row_ux_polish.css",
    "128_atomic_field_validation_mobile_polish.css",
    "130_atomic_file_checkbox_numeric_polish.css",
    "131_centered_flash_notification_polish.css",
    "133_atomic_time_password_dropdown_ui_polish.css",
    "134_atomic_static_alert_empty_state_polish.css",
    "135_atomic_table_scroll_density_polish.css",
    "136_atomic_print_export_ui_polish.css",
    "137_atomic_textarea_filter_input_polish.css",
    "138_atomic_page_header_navigation_context_polish.css",
    "139_atomic_badge_metric_progress_polish.css",
    "140_atomic_card_section_layout_polish.css",
    "141_ui_regression_inline_js_cleanup.css",
    "143_erp_ui_system_final_override.css",
    "145_no_gradient_lock.css",
    "146_portal_contrast_lock.css",
    "147_global_ui_ux_density_lock.css",
    "148_portal_executive_polish_lock.css",
    "149_portal_topbar_compact_lock.css",
    "150_portal_topbar_single_row_lock.css",
    "151_portal_topbar_collision_fix.css",
    "152_portal_topbar_structural_grid_fix.css",
    "153_portal_topbar_no_avatar_lock.css",
    "154_global_calm_interface_lock.css",
    "155_global_layout_balance_lock.css",
    "156_global_minimal_clarity_lock.css",
    "157_dark_card_contrast_rescue_lock.css",
    "158_portal_feature_dark_summary_contrast_lock.css",
    "159_portal_summary_grid_spacing_lock.css",
    "160_global_typography_weight_slim_lock.css",
    "161_portal_component_precision_lock.css",
    "162_portal_neutral_metric_card_lock.css",
    "163_portal_active_button_inner_box_lock.css",
    "164_global_flash_toast_compact_lock.css",
    "165_global_flash_toast_redesign_lock.css",
    "166_password_button_surface_lock.css",
    "167_public_auth_register_clean_lock.css",
}

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


def _load_previous_architecture_guard() -> Dict[str, object]:
    if not REPORT_OUTPUT.exists():
        return {}
    try:
        report = json.loads(REPORT_OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    guard = report.get("architecture_guard", {})
    return guard if isinstance(guard, dict) else {}


def _filename_has_forbidden_word(filename: str) -> bool:
    name = Path(filename).stem.lower()
    pattern = r"(?:^|[^a-z])(" + "|".join(FORBIDDEN_CSS_FILENAME_WORDS) + r")(?:[^a-z]|$)"
    return re.search(pattern, name) is not None


def _important_occurrences(loaded: List[Tuple[str, str]]) -> List[Dict[str, object]]:
    occurrences: List[Dict[str, object]] = []
    for filename, text in loaded:
        rel = f"app/static/css/src/{filename}"
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in re.finditer(r"!important", line):
                occurrences.append(
                    {
                        "file": rel,
                        "line": line_number,
                        "column": match.start() + 1,
                        "text": line.strip()[:180],
                    }
                )
    return occurrences


def _important_guard(
    occurrences: List[Dict[str, object]],
    previous_guard: Dict[str, object],
) -> Tuple[Dict[str, object], List[str]]:
    errors: List[str] = []
    current_by_source = Counter(str(item["file"]) for item in occurrences)
    current_total = len(occurrences)
    previous_total = previous_guard.get("important_count")
    previous_by_source = previous_guard.get("important_by_source", {})
    previous_method = previous_guard.get("important_count_method")

    # A report produced by the first guard used matching-line counts. Migrate
    # once to the literal-token metric instead of comparing incompatible data.
    if previous_method != IMPORTANT_COUNT_METHOD:
        previous_total = IMPORTANT_BASELINE_COUNT
        previous_by_source = {}
    elif not isinstance(previous_total, int):
        previous_total = IMPORTANT_BASELINE_COUNT
    if not isinstance(previous_by_source, dict):
        previous_by_source = {}

    source_increases = {
        source: count - int(previous_by_source.get(source, count))
        for source, count in current_by_source.items()
        if count > int(previous_by_source.get(source, count))
    }
    if current_total > previous_total or source_increases:
        suspect_sources = set(source_increases)
        if not suspect_sources:
            suspect_sources = set(current_by_source)
        suspect_lines = [
            item for item in occurrences if str(item["file"]) in suspect_sources
        ][:80]
        errors.append(
            "New !important usage detected. "
            f"Previous total: {previous_total}; current total: {current_total}; "
            "suspect file/line entries: " + json.dumps(suspect_lines, ensure_ascii=False)
        )

    return (
        {
            "important_count": current_total,
            "important_count_method": IMPORTANT_COUNT_METHOD,
            "important_by_source": dict(sorted(current_by_source.items())),
            "important_previous_count": previous_total,
            "important_source_increases": dict(sorted(source_increases.items())),
        },
        errors,
    )


def _custom_property_values(css: str) -> Dict[str, str]:
    declarations: Dict[str, str] = {}
    for match in re.finditer(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);", css):
        value = match.group(2).replace("!important", "").strip()
        declarations[match.group(1)] = re.sub(r"\s+", " ", value)
    return declarations


def _resolve_custom_property(name: str, values: Dict[str, str], seen: set[str] | None = None) -> str:
    seen = seen or set()
    if name in seen:
        return values.get(name, "")
    seen.add(name)
    value = values.get(name, "")

    def replace_var(match: re.Match[str]) -> str:
        target = match.group(1)
        fallback = (match.group(2) or "").strip()
        resolved = _resolve_custom_property(target, values, seen.copy())
        return resolved or fallback

    previous = None
    while previous != value and "var(" in value:
        previous = value
        value = VAR_REFERENCE_RE.sub(replace_var, value)
    return value.strip()


def _status_token_report(css: str) -> Tuple[Dict[str, object], List[str]]:
    values = _custom_property_values(css)
    resolved = {
        token: _resolve_custom_property(token, values)
        for token in STATUS_TOKEN_NAMES
    }
    normalized = {
        token: re.sub(r"\s+", "", value.lower())
        for token, value in resolved.items()
    }
    missing = [token for token, value in resolved.items() if not value]
    duplicate_groups: Dict[str, List[str]] = {}
    for token, value in normalized.items():
        duplicate_groups.setdefault(value, []).append(token)
    duplicates = [
        {"value": value, "tokens": tokens}
        for value, tokens in duplicate_groups.items()
        if value and len(tokens) > 1
    ]
    errors = []
    if missing or duplicates:
        errors.append(
            "Status token values must be present and distinct for success, warning, danger, and info. "
            + json.dumps({"missing": missing, "resolved": resolved, "duplicates": duplicates}, ensure_ascii=False)
        )
    return (
        {
            "status_tokens": resolved,
            "status_tokens_distinct": not missing and not duplicates,
            "status_token_duplicates": duplicates,
        },
        errors,
    )


def _architecture_guard(
    loaded: List[Tuple[str, str]],
    output_css: str,
    previous_guard: Dict[str, object],
) -> Tuple[Dict[str, object], List[str]]:
    errors: List[str] = []
    source_files = sorted(p.name for p in CSS_SRC_DIR.glob("*.css"))
    forbidden_sources = {
        filename for filename in source_files if _filename_has_forbidden_word(filename)
    }
    new_forbidden_sources = sorted(forbidden_sources - LEGACY_FORBIDDEN_CSS_SOURCE_NAMES)
    if new_forbidden_sources:
        errors.append(
            "Forbidden CSS source filename(s): " + ", ".join(new_forbidden_sources)
        )

    important_report, important_errors = _important_guard(
        _important_occurrences(loaded),
        previous_guard,
    )
    status_report, status_errors = _status_token_report(output_css)
    errors.extend(important_errors)
    errors.extend(status_errors)

    report: Dict[str, object] = {
        "forbidden_filename_words": list(FORBIDDEN_CSS_FILENAME_WORDS),
        "legacy_forbidden_source_names": sorted(LEGACY_FORBIDDEN_CSS_SOURCE_NAMES),
        "forbidden_filename_violations": new_forbidden_sources,
        "source_order_locked": True,
        "unexpected_source_files_fail_build": True,
    }
    report.update(important_report)
    report.update(status_report)
    return report, errors


def build() -> int:
    previous_guard = _load_previous_architecture_guard()
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

    architecture_report, architecture_errors = _architecture_guard(
        loaded,
        output_css,
        previous_guard,
    )
    if architecture_errors:
        for error in architecture_errors:
            print(f"ERROR: {error}", file=sys.stderr)
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
        "architecture_guard": architecture_report,
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
