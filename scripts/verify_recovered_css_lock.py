"""Guard the recovered ERP UI stylesheet from accidental overwrite.

This check is intentionally narrow. It does not rebuild CSS and it does not
change files. It verifies that the exact recovered stylesheet is still the one
served by the app layouts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STYLE_OBJECT = "ddf14d9501124f8fb347db49959fc643243d3072"
STYLE_PATH = ROOT / "app" / "static" / "css" / "style.css"
SOURCE_PATH = ROOT / "app" / "static" / "css" / "src" / "143_erp_ui_system_final_override.css"
BUILD_SCRIPT_PATH = ROOT / "tools" / "build_css.py"
LAYOUT_PATHS = [
    ROOT / "app" / "templates" / "layouts" / "base.html",
    ROOT / "app" / "templates" / "layouts" / "portal_mobile.html",
]

REQUIRED_MARKERS = [
    "UI polish v11",
    "UI polish v15",
    "UI repair v16",
]
FORBIDDEN_MARKERS = [
    "V17 Visual Restore",
    "1000_v17_visual_restore",
]
CACHE_MARKER = "20260810-public-auth-register-clean"
SOURCE_NAME = "143_erp_ui_system_final_override.css"
SWEEP_SOURCE_NAME = "144_end_to_end_ui_ux_sweep.css"
NO_GRADIENT_SOURCE_NAME = "145_no_gradient_lock.css"
PORTAL_CONTRAST_SOURCE_NAME = "146_portal_contrast_lock.css"
GLOBAL_UX_SOURCE_NAME = "147_global_ui_ux_density_lock.css"
PORTAL_EXECUTIVE_SOURCE_NAME = "148_portal_executive_polish_lock.css"
PORTAL_TOPBAR_SOURCE_NAME = "149_portal_topbar_compact_lock.css"
PORTAL_TOPBAR_SINGLE_ROW_SOURCE_NAME = "150_portal_topbar_single_row_lock.css"
PORTAL_TOPBAR_COLLISION_SOURCE_NAME = "151_portal_topbar_collision_fix.css"
PORTAL_TOPBAR_STRUCTURAL_SOURCE_NAME = "152_portal_topbar_structural_grid_fix.css"
PORTAL_TOPBAR_NO_AVATAR_SOURCE_NAME = "153_portal_topbar_no_avatar_lock.css"
GLOBAL_CALM_SOURCE_NAME = "154_global_calm_interface_lock.css"
GLOBAL_LAYOUT_BALANCE_SOURCE_NAME = "155_global_layout_balance_lock.css"
GLOBAL_MINIMAL_CLARITY_SOURCE_NAME = "156_global_minimal_clarity_lock.css"
DARK_CARD_CONTRAST_SOURCE_NAME = "157_dark_card_contrast_rescue_lock.css"
PORTAL_FEATURE_DARK_SUMMARY_SOURCE_NAME = "158_portal_feature_dark_summary_contrast_lock.css"
PORTAL_SUMMARY_GRID_SPACING_SOURCE_NAME = "159_portal_summary_grid_spacing_lock.css"
GLOBAL_TYPOGRAPHY_WEIGHT_SLIM_SOURCE_NAME = "160_global_typography_weight_slim_lock.css"
PORTAL_COMPONENT_PRECISION_SOURCE_NAME = "161_portal_component_precision_lock.css"
PORTAL_NEUTRAL_METRIC_CARD_SOURCE_NAME = "162_portal_neutral_metric_card_lock.css"
PORTAL_ACTIVE_BUTTON_INNER_BOX_SOURCE_NAME = "163_portal_active_button_inner_box_lock.css"
GLOBAL_FLASH_TOAST_COMPACT_SOURCE_NAME = "164_global_flash_toast_compact_lock.css"
GLOBAL_FLASH_TOAST_REDESIGN_SOURCE_NAME = "165_global_flash_toast_redesign_lock.css"
PASSWORD_BUTTON_SURFACE_SOURCE_NAME = "166_password_button_surface_lock.css"
PUBLIC_AUTH_REGISTER_SOURCE_NAME = "167_public_auth_register_clean_lock.css"


def _git_hash_object(path: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", str(path.relative_to(ROOT))],
        cwd=ROOT,
        text=True,
    ).strip()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _failures() -> list[str]:
    failures: list[str] = []
    if not STYLE_PATH.exists():
        return [f"{STYLE_PATH} tidak ditemukan."]

    actual_hash = _git_hash_object(STYLE_PATH)
    if actual_hash != EXPECTED_STYLE_OBJECT:
        failures.append(
            f"style.css berubah: expected {EXPECTED_STYLE_OBJECT}, actual {actual_hash}."
        )

    style_text = _read(STYLE_PATH)
    for marker in REQUIRED_MARKERS:
        if marker not in style_text:
            failures.append(f"style.css kehilangan marker wajib: {marker}.")
    for marker in FORBIDDEN_MARKERS:
        if marker in style_text:
            failures.append(f"style.css memuat marker terlarang: {marker}.")

    if not SOURCE_PATH.exists():
        failures.append(f"Source lock {SOURCE_NAME} tidak ditemukan.")
    else:
        source_text = _read(SOURCE_PATH)
        for marker in REQUIRED_MARKERS:
            if marker not in source_text:
                failures.append(f"{SOURCE_NAME} kehilangan marker wajib: {marker}.")

    build_text = _read(BUILD_SCRIPT_PATH)
    if SOURCE_NAME not in build_text:
        failures.append(f"{SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if SWEEP_SOURCE_NAME not in build_text:
        failures.append(f"{SWEEP_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if NO_GRADIENT_SOURCE_NAME not in build_text:
        failures.append(f"{NO_GRADIENT_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_CONTRAST_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_CONTRAST_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_UX_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_UX_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_EXECUTIVE_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_EXECUTIVE_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_TOPBAR_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_TOPBAR_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_TOPBAR_SINGLE_ROW_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_TOPBAR_SINGLE_ROW_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_TOPBAR_COLLISION_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_TOPBAR_COLLISION_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_TOPBAR_STRUCTURAL_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_TOPBAR_STRUCTURAL_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_TOPBAR_NO_AVATAR_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_TOPBAR_NO_AVATAR_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_CALM_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_CALM_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_LAYOUT_BALANCE_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_LAYOUT_BALANCE_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_MINIMAL_CLARITY_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_MINIMAL_CLARITY_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if DARK_CARD_CONTRAST_SOURCE_NAME not in build_text:
        failures.append(f"{DARK_CARD_CONTRAST_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_FEATURE_DARK_SUMMARY_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_FEATURE_DARK_SUMMARY_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_SUMMARY_GRID_SPACING_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_SUMMARY_GRID_SPACING_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_TYPOGRAPHY_WEIGHT_SLIM_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_TYPOGRAPHY_WEIGHT_SLIM_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_COMPONENT_PRECISION_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_COMPONENT_PRECISION_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_NEUTRAL_METRIC_CARD_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_NEUTRAL_METRIC_CARD_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PORTAL_ACTIVE_BUTTON_INNER_BOX_SOURCE_NAME not in build_text:
        failures.append(f"{PORTAL_ACTIVE_BUTTON_INNER_BOX_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_FLASH_TOAST_COMPACT_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_FLASH_TOAST_COMPACT_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if GLOBAL_FLASH_TOAST_REDESIGN_SOURCE_NAME not in build_text:
        failures.append(f"{GLOBAL_FLASH_TOAST_REDESIGN_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PASSWORD_BUTTON_SURFACE_SOURCE_NAME not in build_text:
        failures.append(f"{PASSWORD_BUTTON_SURFACE_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")
    if PUBLIC_AUTH_REGISTER_SOURCE_NAME not in build_text:
        failures.append(f"{PUBLIC_AUTH_REGISTER_SOURCE_NAME} belum masuk SOURCE_ORDER tools/build_css.py.")

    for layout_path in LAYOUT_PATHS:
        layout_text = _read(layout_path)
        if CACHE_MARKER not in layout_text:
            failures.append(f"{layout_path.relative_to(ROOT)} belum memakai cache {CACHE_MARKER}.")

    return failures


def main() -> int:
    failures = _failures()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("OK: recovered CSS lock aman.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
