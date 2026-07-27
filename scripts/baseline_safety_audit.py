"""Read-only baseline safety audit for the existing ERP.

This script is intentionally non-mutating. It builds the Flask app, snapshots
the route map, parses templates, validates literal endpoint references, runs a
safe GET smoke pass, and writes reports under storage/final_reports.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "storage" / "final_reports"
TEMPLATE_URL_FOR_RE = re.compile(r"""url_for\(\s*['"]([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)['"]""")
PY_TEMPLATE_REFS_RE = re.compile(r"""render_template\(\s*['"]([^'"]+\.html)['"]""")
JINJA_FILE_REF_RE = re.compile(r"""{%\s*(?:extends|include|import|from)\s+['"]([^'"]+)['"]""")

SKIP_PATH_FRAGMENTS = (
    "/download",
    "/export",
    "/print",
    "/view",
    "/api/",
    "/attachments/",
    "/whatsapp/",
)
ERROR_MARKERS = (
    "Traceback (most recent call last)",
    "BuildError",
    "NameError",
    "UndefinedError",
    "AttributeError",
    "TypeError",
    "KeyError",
    "OperationalError",
)


@dataclass
class RouteRow:
    rule: str
    endpoint: str
    methods: list[str]
    blueprint: str
    source: str
    arguments: list[str]


def sanitize_database_url(url: str) -> str:
    """Return a database URL safe for reports."""
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.password:
        return url
    redacted_netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
    return parsed._replace(netloc=redacted_netloc).geturl()


def is_safe_smoke_route(rule: str, methods: Iterable[str], arguments: Iterable[str]) -> bool:
    """Only smoke non-parameterized read-only GET routes."""
    method_set = set(methods)
    if "GET" not in method_set or set(arguments):
        return False
    if rule == "/static/<path:filename>":
        return False
    lowered = rule.lower()
    return not any(fragment in lowered for fragment in SKIP_PATH_FRAGMENTS)


def collect_literal_endpoint_references(root: Path = ROOT) -> dict[str, list[str]]:
    endpoints: dict[str, set[str]] = {}

    def add(endpoint: str, path: Path) -> None:
        endpoints.setdefault(endpoint, set()).add(str(path.relative_to(root)).replace("\\", "/"))

    for path in (root / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "url_for":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        add(node.args[0].value, path)
                if isinstance(node.func, ast.Name) and node.func.id == "_landing_card":
                    if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant) and isinstance(node.args[2].value, str):
                        add(node.args[2].value, path)

            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "endpoint"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        add(value.value, path)

    for path in (root / "app" / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for match in TEMPLATE_URL_FOR_RE.finditer(source):
            add(match.group(1), path)

    return {endpoint: sorted(paths) for endpoint, paths in sorted(endpoints.items())}


def collect_template_file_references(root: Path = ROOT) -> dict[str, list[str]]:
    refs: dict[str, set[str]] = {}

    def add(template_name: str, path: Path) -> None:
        refs.setdefault(template_name, set()).add(str(path.relative_to(root)).replace("\\", "/"))

    for path in (root / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for match in PY_TEMPLATE_REFS_RE.finditer(source):
            add(match.group(1), path)

    for path in (root / "app" / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for match in JINJA_FILE_REF_RE.finditer(source):
            add(match.group(1), path)

    return {template: sorted(paths) for template, paths in sorted(refs.items())}


def scan_session_calls(root: Path = ROOT) -> dict[str, list[dict[str, object]]]:
    results = {"route_commit": [], "route_rollback": [], "service_commit": [], "service_rollback": []}
    patterns = {
        "commit": re.compile(r"db\.session\.commit\s*\("),
        "rollback": re.compile(r"db\.session\.rollback\s*\("),
    }
    scopes = {
        "route": root / "app" / "routes",
        "service": root / "app" / "services",
    }
    for scope_name, folder in scopes.items():
        for path in folder.rglob("*.py"):
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                for action, pattern in patterns.items():
                    if pattern.search(line):
                        results[f"{scope_name}_{action}"].append(
                            {
                                "file": str(path.relative_to(root)),
                                "line": line_no,
                                "text": line.strip(),
                            }
                        )
    return results


def collect_migration_heads(root: Path = ROOT) -> list[str]:
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    for path in (root / "migrations" / "versions").glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in {"revision", "down_revision"}:
                    try:
                        values[node.targets[0].id] = ast.literal_eval(node.value)
                    except ValueError:
                        values[node.targets[0].id] = None
        revision = values.get("revision")
        down_revision = values.get("down_revision")
        if isinstance(revision, str):
            revisions.add(revision)
        if isinstance(down_revision, str):
            down_revisions.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            down_revisions.update(item for item in down_revision if isinstance(item, str))
    return sorted(revisions - down_revisions)


def build_route_rows(app) -> list[RouteRow]:
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: (item.rule, item.endpoint)):
        view_func = app.view_functions.get(rule.endpoint)
        source_file = inspect.getsourcefile(view_func) if view_func else None
        if source_file:
            try:
                source = str(Path(source_file).resolve().relative_to(ROOT))
            except ValueError:
                source = str(source_file)
        else:
            source = ""
        rows.append(
            RouteRow(
                rule=rule.rule,
                endpoint=rule.endpoint,
                methods=sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"}),
                blueprint=rule.endpoint.split(".", 1)[0] if "." in rule.endpoint else "",
                source=source,
                arguments=sorted(rule.arguments),
            )
        )
    return rows


def collect_database_snapshot(app, db) -> dict[str, object]:
    from sqlalchemy import inspect as sqlalchemy_inspect, text

    snapshot: dict[str, object] = {
        "database_url": sanitize_database_url(str(db.engine.url)),
        "tables": [],
        "alembic_version": None,
        "migration_heads": collect_migration_heads(ROOT),
        "alembic_current_is_head": None,
        "users_total": None,
        "active_admin_or_owner": None,
        "orphan_users": None,
        "qa_marker_hits": None,
    }
    inspector = sqlalchemy_inspect(db.engine)
    table_names = sorted(inspector.get_table_names())
    snapshot["tables"] = table_names

    with db.engine.connect() as connection:
        if "alembic_version" in table_names:
            snapshot["alembic_version"] = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            snapshot["alembic_current_is_head"] = snapshot["alembic_version"] in set(snapshot["migration_heads"])
        if "users" in table_names:
            snapshot["users_total"] = connection.execute(text("SELECT COUNT(*) FROM users")).scalar()
            snapshot["active_admin_or_owner"] = connection.execute(
                text("SELECT COUNT(*) FROM users WHERE is_active = true AND role IN ('OWNER', 'ADMIN')")
            ).scalar()
            snapshot["orphan_users"] = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM users u
                    LEFT JOIN branches b ON b.id = u.branch_id
                    WHERE b.id IS NULL
                    """
                )
            ).scalar()
        qa_hits = 0
        for table in table_names:
            columns = [column["name"] for column in inspector.get_columns(table) if str(column.get("type", "")).upper().find("CHAR") >= 0 or str(column.get("type", "")).upper().find("TEXT") >= 0]
            if not columns:
                continue
            clauses = " OR ".join(f'CAST("{column}" AS TEXT) ILIKE :marker' for column in columns)
            qa_hits += connection.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE {clauses}'), {"marker": "%QA-SMOKE%"}).scalar() or 0
            qa_hits += connection.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE {clauses}'), {"marker": "%QA Smoke%"}).scalar() or 0
            qa_hits += connection.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE {clauses}'), {"marker": "%QA_SMOKE%"}).scalar() or 0
        snapshot["qa_marker_hits"] = qa_hits
    return snapshot


def audit_templates(app) -> dict[str, object]:
    template_root = ROOT / "app" / "templates"
    templates = sorted(str(path.relative_to(template_root)).replace("\\", "/") for path in template_root.rglob("*.html"))
    parse_errors = []
    for template in templates:
        try:
            app.jinja_env.get_template(template)
        except Exception as error:  # noqa: BLE001 - audit must capture parser failures as data.
            parse_errors.append({"template": template, "error": f"{type(error).__name__}: {error}"})

    refs = collect_template_file_references(ROOT)
    missing_refs = {
        template: paths
        for template, paths in refs.items()
        if not (template_root / template).exists()
    }
    return {
        "total": len(templates),
        "parsed": len(templates) - len(parse_errors),
        "parse_errors": parse_errors,
        "file_references": refs,
        "missing_file_references": missing_refs,
    }


def audit_endpoint_references(app) -> dict[str, object]:
    referenced = collect_literal_endpoint_references(ROOT)
    existing = set(app.view_functions)
    known_blueprints = {endpoint.split(".", 1)[0] for endpoint in existing if "." in endpoint}
    missing = {
        endpoint: paths
        for endpoint, paths in referenced.items()
        if endpoint.split(".", 1)[0] in known_blueprints and endpoint not in existing
    }
    return {
        "total_literal_references": len(referenced),
        "referenced": referenced,
        "missing": missing,
    }


def login_first_active_owner_or_admin(client, db) -> dict[str, object]:
    from app.models.master import User

    user = (
        User.query.filter(User.is_active.is_(True), User.role == "OWNER").order_by(User.id.asc()).first()
        or User.query.filter(User.is_active.is_(True), User.role == "ADMIN").order_by(User.id.asc()).first()
        or User.query.filter(User.is_active.is_(True)).order_by(User.id.asc()).first()
    )
    if not user:
        return {"logged_in": False, "reason": "Tidak ada user aktif."}
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return {"logged_in": True, "user_id": user.id, "role": user.role, "branch_id": user.branch_id}


def smoke_get_routes(app, db, route_rows: list[RouteRow]) -> dict[str, object]:
    candidates = [row for row in route_rows if is_safe_smoke_route(row.rule, row.methods, row.arguments)]
    results = []
    with app.test_client() as client:
        login_info = login_first_active_owner_or_admin(client, db)
        for row in candidates:
            if row.endpoint in {"static"}:
                continue
            try:
                response = client.get(row.rule, follow_redirects=False)
                body = response.get_data(as_text=True)[:20000]
                location = response.headers.get("Location", "")
                markers = [marker for marker in ERROR_MARKERS if marker in body]
                redirect_ok = response.status_code != 302 or (location and urlparse(location).path != row.rule)
                ok_status = response.status_code in {200, 302, 401, 403}
                results.append(
                    {
                        "rule": row.rule,
                        "endpoint": row.endpoint,
                        "status": response.status_code,
                        "location": location,
                        "ok": bool(ok_status and redirect_ok and not markers),
                        "error_markers": markers,
                        "template_rendered": response.status_code == 200 and "text/html" in response.content_type,
                    }
                )
            except Exception as error:  # noqa: BLE001 - runtime smoke should record crashes.
                results.append(
                    {
                        "rule": row.rule,
                        "endpoint": row.endpoint,
                        "status": "EXCEPTION",
                        "location": "",
                        "ok": False,
                        "error_markers": [f"{type(error).__name__}: {error}"],
                        "template_rendered": False,
                    }
                )
    failures = [row for row in results if not row["ok"]]
    return {
        "login": login_info,
        "candidate_count": len(candidates),
        "executed_count": len(results),
        "failures": failures,
        "results": results,
    }


def write_reports(payload: dict[str, object], timestamp: str) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    route_map_path = REPORT_DIR / f"baseline_route_map_{timestamp}.json"
    template_path = REPORT_DIR / f"baseline_template_audit_{timestamp}.json"
    smoke_path = REPORT_DIR / f"baseline_runtime_smoke_{timestamp}.json"
    report_path = REPORT_DIR / f"BASELINE_SAFETY_AUDIT_{timestamp}.md"
    latest_path = REPORT_DIR / "BASELINE_SAFETY_AUDIT_LATEST.md"

    route_map_path.write_text(json.dumps(payload["routes"], indent=2, ensure_ascii=False), encoding="utf-8")
    template_path.write_text(json.dumps(payload["templates"], indent=2, ensure_ascii=False), encoding="utf-8")
    smoke_path.write_text(json.dumps(payload["smoke"], indent=2, ensure_ascii=False), encoding="utf-8")

    status = payload["status"]
    db_snapshot = payload["database"]
    session_calls = payload["session_calls"]
    lines = [
        "# Baseline Safety Audit ERP PT Idha Boga Pangan Mandiri",
        "",
        f"Timestamp: {timestamp}",
        f"Status: {status}",
        "",
        "## Scope",
        "- Read-only Flask startup audit.",
        "- Route map snapshot.",
        "- Template parse and literal url_for endpoint validation.",
        "- Safe GET smoke for non-parameterized, non-download/export/API routes.",
        "- Database identity and user safety check.",
        "- Route transaction boundary scan.",
        "",
        "## Database",
        f"- URL: `{db_snapshot.get('database_url')}`",
        f"- Tabel: {len(db_snapshot.get('tables', []))}",
        f"- Alembic revision: `{db_snapshot.get('alembic_version')}`",
        f"- Alembic heads: `{', '.join(db_snapshot.get('migration_heads') or [])}`",
        f"- Current is head: {db_snapshot.get('alembic_current_is_head')}",
        f"- Users: {db_snapshot.get('users_total')}",
        f"- Active OWNER/ADMIN: {db_snapshot.get('active_admin_or_owner')}",
        f"- Orphan users: {db_snapshot.get('orphan_users')}",
        f"- QA marker hits: {db_snapshot.get('qa_marker_hits')}",
        "",
        "## Route Map",
        f"- Total route: {len(payload['routes'])}",
        f"- Duplicate rule/method: {len(payload['duplicate_rule_methods'])}",
        f"- Safe GET candidates: {payload['smoke']['candidate_count']}",
        f"- Safe GET executed: {payload['smoke']['executed_count']}",
        f"- Smoke failures: {len(payload['smoke']['failures'])}",
        "",
        "## Template And url_for",
        f"- Total template: {payload['templates']['total']}",
        f"- Parsed: {payload['templates']['parsed']}",
        f"- Template parse errors: {len(payload['templates']['parse_errors'])}",
        f"- Literal endpoint references: {payload['endpoint_references']['total_literal_references']}",
        f"- Missing endpoint references: {len(payload['endpoint_references']['missing'])}",
        f"- Missing template file references: {len(payload['templates']['missing_file_references'])}",
        "",
        "## Transaction Boundary Static Scan",
        f"- Route commit: {len(session_calls['route_commit'])}",
        f"- Route rollback: {len(session_calls['route_rollback'])}",
        f"- Service commit: {len(session_calls['service_commit'])}",
        f"- Service rollback: {len(session_calls['service_rollback'])}",
        "",
        "## Smoke Failures",
    ]
    if payload["smoke"]["failures"]:
        for failure in payload["smoke"]["failures"]:
            lines.append(f"- `{failure['endpoint']}` `{failure['rule']}` status={failure['status']} markers={failure['error_markers']} location=`{failure['location']}`")
    else:
        lines.append("- Tidak ada status 500/exception/error marker pada safe GET smoke.")

    lines.extend(["", "## Missing Endpoint References"])
    if payload["endpoint_references"]["missing"]:
        for endpoint, paths in payload["endpoint_references"]["missing"].items():
            lines.append(f"- `{endpoint}`: {', '.join(paths)}")
    else:
        lines.append("- Tidak ada literal endpoint hilang yang terdeteksi.")

    lines.extend(["", "## Files"])
    lines.append(f"- Route map JSON: `{route_map_path}`")
    lines.append(f"- Template audit JSON: `{template_path}`")
    lines.append(f"- Runtime smoke JSON: `{smoke_path}`")

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")
    latest_path.write_text(report_text, encoding="utf-8")

    return {
        "report": str(report_path),
        "latest": str(latest_path),
        "route_map": str(route_map_path),
        "template": str(template_path),
        "smoke": str(smoke_path),
    }


def run() -> dict[str, object]:
    sys.path.insert(0, str(ROOT))
    from app import create_app
    from app.extensions import db

    app = create_app()
    route_rows = build_route_rows(app)
    routes = [asdict(row) for row in route_rows]
    route_method_keys = {}
    for row in route_rows:
        key = (row.rule, tuple(row.methods))
        route_method_keys.setdefault(key, []).append(row.endpoint)
    duplicate_rule_methods = [
        {"rule": rule, "methods": list(methods), "endpoints": endpoints}
        for (rule, methods), endpoints in route_method_keys.items()
        if len(endpoints) > 1
    ]

    with app.app_context():
        templates = audit_templates(app)
        endpoint_references = audit_endpoint_references(app)
        session_calls = scan_session_calls(ROOT)
        database = collect_database_snapshot(app, db)
        smoke = smoke_get_routes(app, db, route_rows)

    critical_count = (
        len(duplicate_rule_methods)
        + len(templates["parse_errors"])
        + len(templates["missing_file_references"])
        + len(endpoint_references["missing"])
        + len(smoke["failures"])
        + len(session_calls["route_commit"])
        + len(session_calls["route_rollback"])
        + (0 if database.get("alembic_current_is_head") else 1)
    )
    status = "READY_FOR_STAGE_1" if critical_count == 0 else "NEEDS_FIX"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "status": status,
        "timestamp": timestamp,
        "routes": routes,
        "duplicate_rule_methods": duplicate_rule_methods,
        "templates": templates,
        "endpoint_references": endpoint_references,
        "session_calls": session_calls,
        "database": database,
        "smoke": smoke,
    }
    payload["files"] = write_reports(payload, timestamp)
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "files": result["files"]}, indent=2, ensure_ascii=False))
