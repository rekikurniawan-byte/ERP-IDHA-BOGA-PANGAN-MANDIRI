"""Pagar arsitektur UI (keputusan owner 2026-09-29).

CSS dirakit dari satu set sumber kecil di app/static/css/app/, tanpa mode
gelap, tanpa file tambalan, dengan !important dan warna literal yang dibatasi.
main.js hanya perilaku; tampilan sepenuhnya urusan CSS.
"""
import re
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _build_namespace():
    return runpy.run_path(str(ROOT / "tools" / "build_css.py"), run_name="css_build_contract")


def test_css_sources_are_the_small_fixed_set():
    namespace = _build_namespace()

    assert namespace["SOURCE_ORDER"] == [
        "tokens.css",
        "base.css",
        "layout.css",
        "components.css",
        "pages.css",
        "portal.css",
        "print.css",
    ]
    loaded, errors = namespace["load_sources"]()
    assert errors == []
    assert [name for name, _ in loaded] == namespace["SOURCE_ORDER"]
    assert not (ROOT / "app" / "static" / "css" / "src").exists()


def test_css_architecture_guard_passes_and_budgets_only_go_down():
    namespace = _build_namespace()
    loaded, _ = namespace["load_sources"]()
    report, errors = namespace["check_sources"](loaded)

    assert errors == []
    assert namespace["IMPORTANT_BUDGET"] <= 12
    assert namespace["HEX_OUTSIDE_TOKENS_BUDGET"] <= 40
    assert report["important_total"] <= namespace["IMPORTANT_BUDGET"]


def test_patch_style_filenames_are_rejected():
    filename_has_forbidden_word = _build_namespace()["filename_has_forbidden_word"]

    for bad in ("200_final_lock.css", "hotfix.css", "portal_override.css", "polish-v2.css"):
        assert filename_has_forbidden_word(bad), bad
    for good in ("tokens.css", "components.css", "portal.css", "pages.css"):
        assert not filename_has_forbidden_word(good), good


def test_built_style_css_matches_sources():
    """style.css adalah hasil rakit; mengeditnya langsung akan tertimpa."""
    namespace = _build_namespace()
    loaded, _ = namespace["load_sources"]()
    expected = namespace["HEADER"] + "".join(f"\n/* --- {name} --- */\n{text}" for name, text in loaded)

    assert _read("app/static/css/style.css") == expected, "Jalankan: python tools/build_css.py"


def test_dark_mode_is_gone_everywhere():
    js = _read("app/static/js/main.js")
    css = _read("app/static/css/style.css")

    assert "[data-theme" not in css
    assert "data-theme" not in js
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "data-theme" not in text, path.relative_to(ROOT)
        assert "themeToggle" not in text, path.relative_to(ROOT)


def test_main_js_is_behavior_only():
    js = _read("app/static/js/main.js")

    # Tidak ada lagi penataan ulang DOM untuk tampilan (select kustom,
    # penggulung aksi, dsb.) dan tidak ada gaya inline dari JS.
    assert ".style.cssText" not in js
    assert "insertAdjacentHTML" not in js
    assert "window.appConfirm" in js
    assert "window.appToast" in js
    assert len(js.splitlines()) < 900


def test_primary_orange_passes_contrast_with_white_text():
    tokens = _read("app/static/css/app/tokens.css")
    components = _read("app/static/css/app/components.css")

    assert "--brand-700: #c2410c;" in tokens
    primary_block = components.split(".app-btn-primary {", 1)[1].split("}", 1)[0]
    assert "--bs-btn-bg: var(--brand-700);" in primary_block


def test_status_codes_show_indonesian_labels():
    from app.utils.labels import status_label

    assert status_label("LOCKED") == "Terkunci"
    assert status_label("PAID") == "Lunas"
    assert status_label("DRAFT", "invoice") == "Belum Dibayar"
    assert status_label("LUNCH") == "Siang"
    assert status_label("SOMETHING_NEW") == "Something New"
    assert status_label(None) == "-"


def test_badges_do_not_hardcode_english_status_codes():
    pattern = re.compile(r'class="(?:status-badge|badge)[^"]*"[^>]*>(PAID|UNPAID|PARTIAL|LOCKED|DRAFT|CANCELLED|DELIVERED|ON THE WAY|COMPLETED|ACTIVE|INACTIVE)<')
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_portal_command_center_uses_real_portal_roles():
    template = _read("app/templates/portal/_command_center.html")

    assert "PORTkL" not in template
    assert "MkNDOR" not in template
    assert "kksi Portal" not in template
    assert 'current_user.role == "PORTAL_CUSTOMER"' in template
    assert 'current_user.role == "PORTAL_SUBCLIENT"' in template
    assert 'current_user.role == "PORTAL_CLIENT"' in template


def test_master_items_uses_standard_markup():
    template = _read("app/templates/master/items.html")

    assert "ui-scope" not in template
    assert "ui_macros" not in template
    assert not (TEMPLATES / "components" / "ui_macros.html").exists()
    assert 'class="table app-table' in template
    for endpoint in ("master.index", "master.create_item", "master.edit_item", "master.toggle_item", "master.delete_item"):
        assert f"url_for('{endpoint}'" in template
    assert "Yakin ingin menghapus item ini?" in template


def test_static_assets_are_vendored_locally_with_automatic_cache_busting():
    """Bootstrap/bootstrap-icons dari app/static/vendor/; style.css dan main.js
    diberi hash isi saat aplikasi start (app/__init__.py::_static_asset_fingerprint).
    """
    for layout_name in ("base.html", "portal_mobile.html"):
        layout_html = _read(f"app/templates/layouts/{layout_name}")
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
