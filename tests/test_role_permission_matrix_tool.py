from pathlib import Path

from tools.audit_role_permission_matrix import collect_route_permissions, render_report


def test_role_permission_matrix_reads_decorators(tmp_path):
    routes_dir = tmp_path / "routes"
    routes_dir.mkdir()
    (routes_dir / "sample_routes.py").write_text(
        "\n".join(
            [
                "from flask_login import login_required",
                "from app.utils.decorators import role_required",
                "bp = object()",
                "",
                "@bp.route('/secure', methods=['GET', 'POST'])",
                "@role_required('OWNER', 'FINANCE')",
                "def secure():",
                "    pass",
                "",
                "@bp.route('/login-only')",
                "@login_required",
                "def login_only():",
                "    pass",
                "",
                "@bp.route('/public')",
                "def public():",
                "    pass",
            ]
        ),
        encoding="utf-8",
    )

    routes = collect_route_permissions(routes_dir)

    assert len(routes) == 3
    assert routes[0].auth == "role_required"
    assert routes[0].roles == ("OWNER", "FINANCE")
    assert routes[0].methods == ("GET", "POST")
    assert routes[1].auth == "login_required"
    assert routes[2].auth == "public"


def test_role_permission_matrix_report_contains_summary(tmp_path):
    routes_dir = tmp_path / "routes"
    routes_dir.mkdir()
    (routes_dir / "sample_routes.py").write_text(
        "@bp.route('/')\n@role_required('OWNER')\ndef index():\n    pass\n",
        encoding="utf-8",
    )

    report = render_report(collect_route_permissions(routes_dir))

    assert "Role Permission Matrix" in report
    assert "OWNER" in report
    assert "Total route" in report
