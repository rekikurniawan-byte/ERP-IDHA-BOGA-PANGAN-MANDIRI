from pathlib import Path

from scripts.baseline_safety_audit import (
    collect_literal_endpoint_references,
    collect_template_file_references,
    is_safe_smoke_route,
    sanitize_database_url,
)


def test_sanitize_database_url_redacts_password():
    url = "postgresql+psycopg://erp_user:secret123@localhost:5432/idha_boga"

    sanitized = sanitize_database_url(url)

    assert "secret123" not in sanitized
    assert "erp_user:***@localhost" in sanitized
    assert sanitized.endswith("/idha_boga")


def test_is_safe_smoke_route_only_allows_non_parameterized_get():
    assert is_safe_smoke_route("/master/items", ["GET"], [])
    assert not is_safe_smoke_route("/master/items/<int:item_id>/edit", ["GET"], ["item_id"])
    assert not is_safe_smoke_route("/finance/invoices/export.csv", ["GET"], [])
    assert not is_safe_smoke_route("/finance/invoices/<int:invoice_id>/payments/create", ["POST"], ["invoice_id"])


def test_collect_literal_endpoint_references_from_python_and_templates(tmp_path):
    app_dir = tmp_path / "app"
    routes_dir = app_dir / "routes"
    templates_dir = app_dir / "templates"
    routes_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)
    (routes_dir / "demo.py").write_text(
        'url_for("master.items")\ncard = {"endpoint": "finance.invoices"}\n',
        encoding="utf-8",
    )
    (templates_dir / "base.html").write_text(
        "{{ url_for('dashboard.owner') }}",
        encoding="utf-8",
    )

    refs = collect_literal_endpoint_references(Path(tmp_path))

    assert refs["master.items"] == ["app/routes/demo.py"]
    assert refs["finance.invoices"] == ["app/routes/demo.py"]
    assert refs["dashboard.owner"] == ["app/templates/base.html"]


def test_collect_template_file_references_from_python_and_jinja(tmp_path):
    app_dir = tmp_path / "app"
    routes_dir = app_dir / "routes"
    templates_dir = app_dir / "templates"
    routes_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)
    (routes_dir / "demo.py").write_text('render_template("dashboard/owner.html")\n', encoding="utf-8")
    (templates_dir / "child.html").write_text('{% extends "layouts/base.html" %}', encoding="utf-8")

    refs = collect_template_file_references(Path(tmp_path))

    assert refs["dashboard/owner.html"] == ["app/routes/demo.py"]
    assert refs["layouts/base.html"] == ["app/templates/child.html"]
