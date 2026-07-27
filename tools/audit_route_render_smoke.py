"""Smoke-render GET routes that do not require dynamic URL parameters.

This catches BuildError/template regressions after route splitting. It uses an
existing active OWNER user from the configured database and only sends GET
requests. No data is mutated.
"""

from __future__ import annotations

from pathlib import Path
import sys

from werkzeug.routing import BuildError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.models.master import User


REPORT_PATH = Path("RINCIAN_AUDIT_ROUTE_RENDER_SMOKE_ERP_IDHA_BOGA.md")


SKIP_ENDPOINTS = {
    "static",
    "auth.logout",
}


def _get_owner_user():
    return (
        User.query.filter_by(role="OWNER", is_active=True).order_by(User.id.asc()).first()
        or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
    )


def _eligible_rules(app):
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        if "GET" not in rule.methods:
            continue
        if rule.arguments:
            continue
        yield rule


def run_smoke():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    rows = []

    with app.app_context():
        user = _get_owner_user()
        if not user:
            raise RuntimeError("Tidak ada user aktif untuk route render smoke.")

        with app.test_client() as client:
            with client.session_transaction() as session:
                session["_user_id"] = str(user.id)
                session["_fresh"] = True

            for rule in _eligible_rules(app):
                status = "PASS"
                detail = ""
                try:
                    response = client.get(rule.rule, follow_redirects=False)
                    if response.status_code >= 500:
                        status = "FAIL"
                        detail = f"HTTP {response.status_code}"
                    else:
                        detail = f"HTTP {response.status_code}"
                except BuildError as exc:
                    status = "FAIL"
                    detail = f"BuildError: {exc}"
                except Exception as exc:  # noqa: BLE001 - audit report must capture unexpected render failures.
                    status = "FAIL"
                    detail = f"{exc.__class__.__name__}: {exc}"
                rows.append({
                    "endpoint": rule.endpoint,
                    "rule": rule.rule,
                    "status": status,
                    "detail": detail,
                })

    return rows


def render_report(rows):
    failed = [row for row in rows if row["status"] == "FAIL"]
    lines = [
        "# Audit Route Render Smoke ERP Idha Boga",
        "",
        "Audit ini melakukan GET render pada route tanpa parameter dinamis memakai user aktif dari database lokal.",
        "",
        "## Ringkasan",
        "",
        "| Metrik | Nilai |",
        "| --- | ---: |",
        f"| Total route dicek | {len(rows)} |",
        f"| Gagal | {len(failed)} |",
        "",
        "## Detail",
        "",
        "| Status | Endpoint | Rule | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| {row['status']} | `{row['endpoint']}` | `{row['rule']}` | {row['detail']} |")
    lines.append("")
    return "\n".join(lines)


def main():
    rows = run_smoke()
    report = render_report(rows)
    REPORT_PATH.write_text(report, encoding="utf-8")
    failed = [row for row in rows if row["status"] == "FAIL"]
    print(f"Route render smoke written: {REPORT_PATH.resolve()}")
    print(f"Routes checked: {len(rows)}")
    print(f"Failed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
