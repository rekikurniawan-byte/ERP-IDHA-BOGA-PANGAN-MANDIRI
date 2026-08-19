import re
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_global_action_collapse_never_moves_forms_into_dropdowns():
    js = _read("app/static/js/main.js")

    assert 'node.matches("a.btn, button.btn, form")' not in js
    assert 'child.matches && child.matches("form") && child.querySelector("button.btn, .btn")' not in js
    assert 'if (child.matches && child.matches("form")) return false;' in js


def test_text_white_utility_keeps_semantic_white_text():
    css = _read("app/static/css/src/147_global_ui_ux_density_lock.css")
    text_white_block = css.split(".bg-white,", 1)[0].rsplit(".text-white,", 1)[-1]

    assert ".text-white,\n.text-light" in css
    assert "color: var(--ux-text) !important;" not in text_white_block
    assert "color: #ffffff !important;" in text_white_block


def test_portal_command_center_uses_real_portal_roles():
    template = _read("app/templates/portal/_command_center.html")

    assert "PORTkL" not in template
    assert "MkNDOR" not in template
    assert 'current_user.role == "PORTAL_CUSTOMER"' in template
    assert 'current_user.role == "PORTAL_MANDOR"' in template
    assert 'current_user.role == "PORTAL_PT"' in template


def test_portal_desktop_dashboard_density_contract_is_present():
    css = _read("app/static/css/src/162_portal_neutral_metric_card_lock.css")

    assert "portal-dashboard-desktop-density" in css
    assert "@media (min-width: 1024px)" in css
    assert "body.portal-web-body .portal-home-hero" in css
    assert "body.portal-web-body .portal-home-metric-row > article" in css


def test_css_architecture_guard_contract_is_present():
    build_css = _read("tools/build_css.py")

    assert "FORBIDDEN_CSS_FILENAME_WORDS" in build_css
    assert 'IMPORTANT_COUNT_METHOD = "literal-token-count-in-source-order"' in build_css
    assert "IMPORTANT_BASELINE_COUNT = 8728" in build_css
    assert "LEGACY_FORBIDDEN_CSS_SOURCE_NAMES" in build_css
    assert "_important_guard" in build_css
    assert "_status_token_report" in build_css
    assert '"architecture_guard": architecture_report' in build_css


def test_css_status_tokens_are_distinct_in_build_order():
    namespace = runpy.run_path(str(ROOT / "tools" / "build_css.py"), run_name="css_build_contract")
    source_order = namespace["SOURCE_ORDER"]
    status_report = namespace["_status_token_report"]

    css = "\n".join(_read(f"app/static/css/src/{filename}") for filename in source_order)
    report, errors = status_report(css)

    assert errors == []
    assert report["status_tokens_distinct"] is True
    assert len(set(report["status_tokens"].values())) == 4


def test_css_important_count_uses_literal_tokens_not_matching_lines():
    namespace = runpy.run_path(str(ROOT / "tools" / "build_css.py"), run_name="css_build_contract")
    source_order = namespace["SOURCE_ORDER"]
    occurrences = namespace["_important_occurrences"](
        [(filename, _read(f"app/static/css/src/{filename}")) for filename in source_order]
    )
    css = "\n".join(_read(f"app/static/css/src/{filename}") for filename in source_order)

    assert len(occurrences) == len(re.findall(r"!important", css))
    assert len(occurrences) == 8728


def test_css_forbidden_patch_names_are_legacy_only():
    namespace = runpy.run_path(str(ROOT / "tools" / "build_css.py"), run_name="css_build_contract")
    filename_has_forbidden_word = namespace["_filename_has_forbidden_word"]
    legacy_names = set(namespace["LEGACY_FORBIDDEN_CSS_SOURCE_NAMES"])

    css_files = sorted((ROOT / "app" / "static" / "css" / "src").glob("*.css"))
    violations = [
        path.name
        for path in css_files
        if filename_has_forbidden_word(path.name) and path.name not in legacy_names
    ]

    assert violations == []


def test_master_items_template_preserves_actions_and_filter_contract():
    template = _read("app/templates/master/items.html")
    macros = _read("app/templates/components/ui_macros.html")
    js = _read("app/static/js/main.js")

    assert 'class="ui-scope ui-page ui-master-items-page"' in template
    assert 'class="ui-filter-grid"' in template
    assert 'class="ui-table-scroll"' in template
    assert 'class="ui-data-table" data-ui-table' in template
    assert "ui-table-cell--sticky-code" in template
    assert "ui-table-cell--sticky-name" in template
    assert "ui-table-cell--sticky-actions" in template
    assert "ui-table-code" in template
    assert 'title="{{ item.item_code }}"' in template
    assert 'method="GET" action="{{ url_for(\'master.items\') }}"' in template
    assert "'q', 'Pencarian'" in template
    assert "'category', 'Kategori'" in template
    assert "'status', 'Status'" in template
    for endpoint in (
        "master.index",
        "master.create_item",
        "master.edit_item",
        "master.toggle_item",
        "master.delete_item",
    ):
        assert f"url_for('{endpoint}'" in template
    assert "Yakin ingin menghapus item ini?" in template
    assert 'data-app-confirm="{{ delete_confirm }}"' in macros
    assert 'method="POST" action="{{ toggle_url }}"' in macros
    assert 'method="POST" action="{{ delete_url }}"' in macros
    assert 'data-ui-foundation-form' in macros
    assert 'components/csrf_token.html' in macros
    assert "ui_button('Hapus', 'danger'" in macros
    assert "data-ui-action-menu-trigger" in macros
    assert 'table.matches(".ui-data-table, [data-ui-table]")' in js
    assert 'form.matches("[data-ui-foundation-form]")' in js
    assert len(re.findall(r"<th(?:\s|>)", template)) == 10
    assert "'Belum ada barang'" in template


def test_master_items_css_is_local_and_has_no_new_important():
    css = _read("app/static/css/src/29_module_master.css")

    assert "!important" not in css
    assert ".ui-master-items-page" in css
    assert "--ui-table-min-width: 1740px" in css
    assert ".master-items-page" not in css


def test_atomic_ui_foundation_is_ordered_prefixed_and_important_free():
    namespace = runpy.run_path(str(ROOT / "tools" / "build_css.py"), run_name="css_build_contract")
    source_order = namespace["SOURCE_ORDER"]
    primitives_index = source_order.index("30_ui_primitives.css")
    patterns_index = source_order.index("31_ui_patterns.css")

    assert source_order[primitives_index - 1] == "29_module_master.css"
    assert patterns_index == primitives_index + 1
    assert source_order[patterns_index + 1] == "90_responsive.css"

    for filename in ("30_ui_primitives.css", "31_ui_patterns.css"):
        css = _read(f"app/static/css/src/{filename}")
        assert "!important" not in css
        selector_blocks = re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
        selectors = [
            selector.strip()
            for block in selector_blocks
            if not block.strip().startswith("@")
            for selector in block.split(",")
        ]
        assert selectors
        assert all(".ui-" in selector for selector in selectors)


def test_atomic_ui_tokens_and_master_items_opt_in_contract():
    primitives = _read("app/static/css/src/30_ui_primitives.css")
    patterns = _read("app/static/css/src/31_ui_patterns.css")
    template = _read("app/templates/master/items.html")

    # Fase 1 CSS audit rewired these onto the theme contract in
    # 100_theme_black_white_lock.css (var(--success, <original literal>))
    # instead of standalone hex, so .ui-scope follows dark mode automatically.
    # The fallback after the comma is the pre-Fase-1 literal, kept so the
    # contract still holds if that theme token is ever missing.
    token_values = dict(re.findall(r"(--ui-(?:primary|warning|danger|info)):\s*([^;]+);", primitives))
    assert token_values["--ui-primary"] == "var(--success, #166534)"
    assert token_values["--ui-danger"] == "var(--danger, #b91c1c)"
    assert len(set(token_values.values())) == 4
    assert "#f97316" not in primitives
    assert ".ui-button--primary" in primitives
    assert ".ui-button--secondary" in primitives
    assert ".ui-button--ghost" in primitives
    assert ".ui-button--danger" in primitives
    assert ".ui-status-badge--success" in primitives
    assert ".ui-status-badge--warning" in primitives
    assert ".ui-status-badge--danger" in primitives
    assert ".ui-status-badge--info" in primitives
    assert ".ui-status-badge--neutral" in primitives
    assert ".ui-filter-toolbar" in patterns
    assert ".ui-data-table" in patterns
    assert ".ui-row-actions" in patterns
    assert ".ui-empty-state" in patterns
    for class_name in ("ui-button", "ui-field", "ui-search-field", "ui-select", "ui-filter-toolbar", "ui-data-table", "ui-status-badge", "ui-empty-state"):
        assert class_name in template or class_name in _read("app/templates/components/ui_macros.html")
