import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "app" / "static" / "css" / "style.css"
SOURCE_PATH = ROOT / "app" / "static" / "css" / "src" / "143_erp_ui_system_final_override.css"
BUILD_SCRIPT_PATH = ROOT / "tools" / "build_css.py"
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


def _git_hash_object(path):
    return subprocess.check_output(
        ["git", "hash-object", str(path.relative_to(ROOT))],
        cwd=ROOT,
        text=True,
    ).strip()


def test_recovered_css_exact_object_is_still_served():
    """Guards the specific historical incident this file is named after: a bad
    revert silently reintroducing the pre-recovery UI. It intentionally does
    NOT pin style.css to an exact byte hash anymore -- that would fail on
    every legitimate CSS change, which is exactly what the ongoing Fase 0-4
    CSS audit/refactor requires (see RINCIAN_AUDIT_UI_UX_CSS_ERP_IDHA_BOGA.md).
    Content markers are still checked so a silent revert is still caught.
    """
    css = STYLE_PATH.read_text(encoding="utf-8")
    assert "UI polish v11" in css
    assert "UI polish v15" in css
    assert "UI repair v16" in css
    assert "V17 Visual Restore" not in css
    assert "1000_v17_visual_restore" not in css


def test_recovered_css_source_and_cache_are_locked():
    assert SOURCE_PATH.exists()
    source_css = SOURCE_PATH.read_text(encoding="utf-8")
    assert "UI polish v11" in source_css
    assert "UI polish v15" in source_css
    assert "UI repair v16" in source_css

    build_css = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    assert SOURCE_NAME in build_css
    assert SWEEP_SOURCE_NAME in build_css
    assert NO_GRADIENT_SOURCE_NAME in build_css
    assert PORTAL_CONTRAST_SOURCE_NAME in build_css
    assert GLOBAL_UX_SOURCE_NAME in build_css
    assert PORTAL_EXECUTIVE_SOURCE_NAME in build_css
    assert PORTAL_TOPBAR_SOURCE_NAME in build_css
    assert PORTAL_TOPBAR_SINGLE_ROW_SOURCE_NAME in build_css
    assert PORTAL_TOPBAR_COLLISION_SOURCE_NAME in build_css
    assert PORTAL_TOPBAR_STRUCTURAL_SOURCE_NAME in build_css
    assert PORTAL_TOPBAR_NO_AVATAR_SOURCE_NAME in build_css
    assert GLOBAL_CALM_SOURCE_NAME in build_css
    assert GLOBAL_LAYOUT_BALANCE_SOURCE_NAME in build_css
    assert GLOBAL_MINIMAL_CLARITY_SOURCE_NAME in build_css
    assert DARK_CARD_CONTRAST_SOURCE_NAME in build_css
    assert PORTAL_FEATURE_DARK_SUMMARY_SOURCE_NAME in build_css
    assert PORTAL_SUMMARY_GRID_SPACING_SOURCE_NAME in build_css
    assert GLOBAL_TYPOGRAPHY_WEIGHT_SLIM_SOURCE_NAME in build_css
    assert PORTAL_COMPONENT_PRECISION_SOURCE_NAME in build_css
    assert PORTAL_NEUTRAL_METRIC_CARD_SOURCE_NAME in build_css
    assert PORTAL_ACTIVE_BUTTON_INNER_BOX_SOURCE_NAME in build_css
    assert GLOBAL_FLASH_TOAST_COMPACT_SOURCE_NAME in build_css
    assert GLOBAL_FLASH_TOAST_REDESIGN_SOURCE_NAME in build_css
    assert PASSWORD_BUTTON_SURFACE_SOURCE_NAME in build_css
    assert PUBLIC_AUTH_REGISTER_SOURCE_NAME in build_css


def test_static_assets_are_vendored_locally_with_automatic_cache_busting():
    """CDN links and hand-edited cache markers were replaced (Fase 0 CSS audit):
    Bootstrap/bootstrap-icons ship from app/static/vendor/, and style.css/main.js
    are cache-busted with a content hash computed once at app startup
    (see app/__init__.py::_static_asset_fingerprint), not a manually bumped string.
    """
    for layout_name in ("base.html", "portal_mobile.html"):
        layout_html = (ROOT / "app" / "templates" / "layouts" / layout_name).read_text(encoding="utf-8")
        assert "cdn.jsdelivr.net" not in layout_html
        assert "vendor/bootstrap/css/bootstrap.min.css" in layout_html
        assert "vendor/bootstrap-icons/font/bootstrap-icons.min.css" in layout_html
        assert "vendor/bootstrap/js/bootstrap.bundle.min.js" in layout_html
        assert "v=css_asset_version" in layout_html
        assert "v=js_asset_version" in layout_html

    for vendored_file in (
        "app/static/vendor/bootstrap/css/bootstrap.min.css",
        "app/static/vendor/bootstrap/js/bootstrap.bundle.min.js",
        "app/static/vendor/bootstrap-icons/font/bootstrap-icons.min.css",
        "app/static/vendor/bootstrap-icons/font/fonts/bootstrap-icons.woff2",
    ):
        assert (ROOT / vendored_file).exists(), f"missing vendored asset: {vendored_file}"
