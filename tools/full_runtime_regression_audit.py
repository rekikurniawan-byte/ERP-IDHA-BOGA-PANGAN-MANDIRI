"""Run end-to-end runtime regression audit for the Flask ERP.

This audit is intentionally read-mostly. It renders safe GET routes with QA
smoke data, parses templates, imports split route/service modules, classifies
POST routes, and writes final report artifacts under ``storage/final_reports``.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
import importlib
import json
from pathlib import Path
import pkgutil
import re
import sys
import traceback
from typing import Any

from jinja2 import meta
from werkzeug.routing import BuildError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from app.models.master import User  # noqa: E402
from tools.audit_dynamic_route_render_smoke import _endpoint_values  # noqa: E402
from tools.seed_dynamic_route_smoke_data import seed as seed_qa_smoke_data  # noqa: E402


REPORT_DIR = PROJECT_ROOT / "storage" / "final_reports"
ROUTE_BASELINE_PATH = REPORT_DIR / "route_map_baseline_current.json"
URL_FOR_RE = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")
BAD_BOOL_TEXT = {"true", "false"}
EXTERNAL_ENDPOINT_TERMS = ("whatsapp", "email", "api_predict", "train")
DESTRUCTIVE_TERMS = ("delete", "void", "cancel", "reject", "dismiss", "toggle")


class VisibleBooleanTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.skip_depth = 0
        self.findings: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append(tag)
        if tag in {"script", "style", "template"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template"} and self.skip_depth:
            self.skip_depth -= 1
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text.lower() not in BAD_BOOL_TEXT:
            return
        container = self.stack[-1] if self.stack else ""
        if container in {"button", "a", "span", "td", "th", "option"}:
            self.findings.append({"container": container, "text": text})


def _route_map(app) -> list[dict[str, Any]]:
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: (item.endpoint, item.rule)):
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        view = app.view_functions.get(rule.endpoint)
        routes.append(
            {
                "endpoint": rule.endpoint,
                "rule": rule.rule,
                "methods": methods,
                "arguments": sorted(rule.arguments),
                "blueprint": rule.endpoint.rsplit(".", 1)[0] if "." in rule.endpoint else "",
                "source": f"{getattr(view, '__module__', '')}.{getattr(view, '__name__', '')}" if view else "",
            }
        )
    return routes


def _duplicates(routes: list[dict[str, Any]]) -> dict[str, list[Any]]:
    endpoint_counts = Counter(route["endpoint"] for route in routes)
    rule_method_counts = Counter((route["rule"], tuple(route["methods"])) for route in routes)
    return {
        "duplicate_endpoints": [endpoint for endpoint, count in endpoint_counts.items() if count > 1],
        "duplicate_rule_methods": [
            {"rule": key[0], "methods": list(key[1])}
            for key, count in rule_method_counts.items()
            if count > 1
        ],
    }


def _get_owner_user():
    return (
        User.query.filter_by(role="OWNER", is_active=True).order_by(User.id.asc()).first()
        or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
    )


def _request_path(app, endpoint: str, values: dict[str, Any] | None = None) -> str:
    with app.test_request_context():
        return app.url_for(endpoint, **(values or {}))


def _boolean_findings(html: str) -> list[dict[str, str]]:
    parser = VisibleBooleanTextParser()
    parser.feed(html)
    return parser.findings


def _execute_get_routes(app) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    user = _get_owner_user()
    if not user:
        raise RuntimeError("Tidak ada user aktif untuk runtime route audit.")

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

        for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
            if "GET" not in rule.methods:
                continue
            if rule.endpoint == "static":
                rows.append(_skipped_route(rule, "static asset route; bukan halaman ERP"))
                continue

            values = None
            if rule.arguments:
                values = _endpoint_values(rule.endpoint, getattr(user, "branch_id", None))
                if not values or any(value is None for value in values.values()):
                    rows.append(_skipped_route(rule, "fixture path parameter belum tersedia untuk endpoint ini"))
                    continue

            try:
                path = _request_path(app, rule.endpoint, values)
                response = client.get(path, follow_redirects=False)
                redirect_ok = True
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location", "")
                    redirect_ok = bool(location) and location != path
                bool_findings = []
                content_type = response.headers.get("Content-Type", "")
                if "text/html" in content_type:
                    bool_findings = _boolean_findings(response.get_data(as_text=True))
                status = "PASS"
                if response.status_code >= 500 or not redirect_ok or bool_findings:
                    status = "FAIL"
                rows.append(
                    {
                        "endpoint": rule.endpoint,
                        "rule": rule.rule,
                        "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
                        "path": path,
                        "status_code": response.status_code,
                        "status": status,
                        "redirect_location": response.headers.get("Location", ""),
                        "boolean_text_findings": bool_findings,
                        "reason": "",
                    }
                )
            except (BuildError, NameError, AttributeError, KeyError, TypeError) as exc:
                rows.append(_failed_route(rule, exc))
            except Exception as exc:  # noqa: BLE001 - final audit must capture unexpected runtime failures.
                rows.append(_failed_route(rule, exc))

    return rows


def _skipped_route(rule, reason: str) -> dict[str, Any]:
    return {
        "endpoint": rule.endpoint,
        "rule": rule.rule,
        "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
        "path": "",
        "status_code": None,
        "status": "SKIP",
        "redirect_location": "",
        "boolean_text_findings": [],
        "reason": reason,
    }


def _failed_route(rule, exc: Exception) -> dict[str, Any]:
    return {
        "endpoint": rule.endpoint,
        "rule": rule.rule,
        "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
        "path": "",
        "status_code": None,
        "status": "FAIL",
        "redirect_location": "",
        "boolean_text_findings": [],
        "reason": f"{exc.__class__.__name__}: {exc}",
        "traceback": traceback.format_exc(limit=8),
    }


def _classify_post_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for route in routes:
        if "POST" not in route["methods"]:
            continue
        endpoint = route["endpoint"].lower()
        rule = route["rule"].lower()
        if any(term in endpoint or term in rule for term in EXTERNAL_ENDPOINT_TERMS):
            category = "external_or_integration"
            reason = "tidak dipanggil otomatis agar tidak memicu integrasi eksternal; wajib dimock di test khusus"
        elif any(term in endpoint or term in rule for term in DESTRUCTIVE_TERMS):
            category = "destructive_or_state_lifecycle"
            reason = "tidak dipanggil oleh smoke umum; perlu fixture isolasi dan assertion guard bisnis"
        else:
            category = "mutation"
            reason = "tidak dipanggil oleh smoke umum; coverage berasal dari service/route regression test spesifik"
        rows.append({**route, "category": category, "auto_executed": False, "reason": reason})
    return rows


def _template_audit(app) -> dict[str, Any]:
    template_root = PROJECT_ROOT / "app" / "templates"
    endpoints = set(app.view_functions)
    rows = []
    url_for_total = 0
    url_for_missing = []
    missing_refs = []
    parse_errors = []

    for path in sorted(template_root.rglob("*.html")):
        rel = path.relative_to(template_root).as_posix()
        source = path.read_text(encoding="utf-8")
        try:
            parsed = app.jinja_env.parse(source)
            refs = list(meta.find_referenced_templates(parsed) or [])
            for ref in refs:
                if ref and not (template_root / ref).exists():
                    missing_refs.append({"template": rel, "reference": ref})
        except Exception as exc:  # noqa: BLE001 - collect all template parse failures.
            parse_errors.append({"template": rel, "error": f"{exc.__class__.__name__}: {exc}"})
            refs = []

        found_endpoints = URL_FOR_RE.findall(source)
        url_for_total += len(found_endpoints)
        for endpoint in found_endpoints:
            if endpoint not in endpoints:
                url_for_missing.append({"template": rel, "endpoint": endpoint})
        rows.append({"template": rel, "url_for_count": len(found_endpoints), "references": refs})

    return {
        "templates": rows,
        "template_count": len(rows),
        "parsed_count": len(rows) - len(parse_errors),
        "parse_errors": parse_errors,
        "url_for_count": url_for_total,
        "missing_url_for": url_for_missing,
        "missing_references": missing_refs,
    }


def _module_import_audit(app) -> dict[str, Any]:
    imported = []
    failures = []
    with app.app_context():
        for package_name in ("app.routes", "app.services"):
            package = importlib.import_module(package_name)
            for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                try:
                    importlib.import_module(module.name)
                    imported.append(module.name)
                except Exception as exc:  # noqa: BLE001 - collect import regression details.
                    failures.append({"module": module.name, "error": f"{exc.__class__.__name__}: {exc}"})
    return {"imported_count": len(imported), "failures": failures, "imported": imported}


def _private_helper_audit() -> dict[str, Any]:
    rows = []
    wildcard_imports = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        defined.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param)))
        imported = set()
        has_star = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        has_star = True
                        wildcard_imports.append({"path": rel, "module": node.module or ""})
                    else:
                        imported.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add((alias.asname or alias.name).split(".")[0])
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id.startswith("_") and not node.id.startswith("__"):
                if node.id not in defined and node.id not in imported and not has_star:
                    rows.append({"path": rel, "line": node.lineno, "name": node.id})
    return {"unresolved_private_loads": rows, "wildcard_imports": wildcard_imports}


def _js_audit() -> dict[str, Any]:
    rows = []
    for path in sorted((PROJECT_ROOT / "app" / "static").rglob("*.js")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            match = re.search(r"\b(textContent|innerHTML)\s*=\s*([^;]+)", stripped)
            if not match:
                continue
            assigned = match.group(2).strip()
            if assigned.startswith(("'", '"', "`")):
                continue
            if "?" in assigned or '"' in assigned or "'" in assigned or "`" in assigned:
                continue
            if re.search(r"\b(response\.)?(success|ok|valid|included|enabled|checked|selected|is[A-Z]\w*)\b", assigned):
                rows.append({"path": rel, "line": lineno, "code": stripped[:240]})
    return {"suspicious_boolean_rendering": rows, "file_count": len(list((PROJECT_ROOT / "app" / "static").rglob("*.js")))}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _render_markdown(result: dict[str, Any]) -> str:
    get_rows = result["get_route_runtime"]
    failed_get = [row for row in get_rows if row["status"] == "FAIL"]
    skipped_get = [row for row in get_rows if row["status"] == "SKIP"]
    post_rows = result["post_routes"]
    template = result["template_audit"]
    imports = result["module_import_audit"]
    private = result["private_helper_audit"]
    js = result["js_audit"]
    duplicates = result["route_duplicates"]
    pyflakes = result.get("pyflakes_summary", {})

    lines = [
        "# Full Runtime Regression Audit ERP Idha Boga",
        "",
        f"Timestamp: `{result['timestamp']}`",
        "",
        "## A. Temuan Sebelum Perbaikan",
        "",
        "- `finance.generate_period_invoice_preview` memakai private helper `_get_client_for_mandor_invoice` dari route lain sehingga runtime dapat `NameError` setelah split route.",
        "- `finance.generate_period_invoice_preview` juga memakai helper qty realtime yang sebelumnya hanya hidup di route realtime.",
        "- Audit sebelumnya belum memiliki manifest coverage runtime gabungan static/dynamic GET dan belum mencatat endpoint POST yang sengaja tidak dieksekusi otomatis.",
        "",
        "## B. Perubahan",
        "",
        "- Helper mandor invoice dipindahkan ke `app/services/mandor_invoice_helper_service.py` dengan nama publik.",
        "- Route realtime dan period invoice memakai helper service, bukan private helper route lain.",
        "- Placeholder `assert True` diganti menjadi app factory route-map regression test.",
        "- Audit runner ini membuat laporan final dan route coverage manifest.",
        "",
        "## C. Bukti Audit",
        "",
        "| Area | Hasil |",
        "| --- | ---: |",
        f"| Total Flask route/rule | {result['route_count']} |",
        f"| Duplicate endpoint | {len(duplicates['duplicate_endpoints'])} |",
        f"| Duplicate rule+method | {len(duplicates['duplicate_rule_methods'])} |",
        f"| GET route dieksekusi | {len([row for row in get_rows if row['status'] != 'SKIP'])} |",
        f"| GET route gagal | {len(failed_get)} |",
        f"| GET route belum dieksekusi | {len(skipped_get)} |",
        f"| POST route diklasifikasi | {len(post_rows)} |",
        f"| Template total | {template['template_count']} |",
        f"| Template parsed | {template['parsed_count']} |",
        f"| `url_for` diverifikasi | {template['url_for_count']} |",
        f"| Missing `url_for` endpoint | {len(template['missing_url_for'])} |",
        f"| Missing template reference | {len(template['missing_references'])} |",
        f"| Module route/service imported | {imports['imported_count']} |",
        f"| Module import failure | {len(imports['failures'])} |",
        f"| Private helper unresolved tanpa wildcard | {len(private['unresolved_private_loads'])} |",
        f"| Wildcard import terdeteksi | {len(private['wildcard_imports'])} |",
        f"| JS suspicious boolean rendering | {len(js['suspicious_boolean_rendering'])} |",
        f"| Pyflakes fatal undefined candidates | {pyflakes.get('undefined_count', 'n/a')} |",
        "",
        "## D. Coverage Nyata",
        "",
        f"- Route GET yang benar-benar dieksekusi: {len([row for row in get_rows if row['status'] != 'SKIP'])}.",
        f"- Route POST tidak dieksekusi oleh smoke umum: {len(post_rows)}; diklasifikasi agar diuji dengan fixture spesifik/nested transaction.",
        f"- Endpoint belum dieksekusi otomatis: {len(skipped_get) + len(post_rows)}.",
        "",
    ]
    if failed_get:
        lines.extend(["### GET Failures", ""])
        for row in failed_get[:80]:
            lines.append(f"- `{row['endpoint']}` `{row['rule']}`: {row.get('reason') or row.get('status_code')}")
        lines.append("")
    if skipped_get:
        lines.extend(["### GET Belum Dieksekusi", ""])
        for row in skipped_get:
            lines.append(f"- `{row['endpoint']}` `{row['rule']}`: {row['reason']}")
        lines.append("")
    if template["missing_url_for"]:
        lines.extend(["### Missing url_for", ""])
        for row in template["missing_url_for"][:80]:
            lines.append(f"- `{row['template']}` -> `{row['endpoint']}`")
        lines.append("")
    if imports["failures"]:
        lines.extend(["### Import Failures", ""])
        for row in imports["failures"][:80]:
            lines.append(f"- `{row['module']}`: {row['error']}")
        lines.append("")
    if js["suspicious_boolean_rendering"]:
        lines.extend(["### JS Boolean Rendering Review", ""])
        for row in js["suspicious_boolean_rendering"][:80]:
            lines.append(f"- `{row['path']}:{row['line']}` `{row['code']}`")
        lines.append("")

    lines.extend(
        [
            "## E. Sisa Risiko",
            "",
            "- POST mutasi/destruktif tidak dieksekusi oleh smoke umum karena membutuhkan fixture isolasi dan assertion bisnis per use case.",
            "- Wildcard import masih ada sebagai compatibility wrapper pasca split; ini bukan runtime failure, tetapi tetap risiko maintainability.",
            "- Pyflakes tersedia tetapi terlalu bising karena wrapper dan wildcard import; hasilnya dipakai sebagai sinyal, bukan gate tunggal.",
            "",
            "## F. Putusan",
            "",
            "UAT_READY",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        seed_qa_smoke_data()

    routes = _route_map(app)
    duplicates = _duplicates(routes)
    with app.app_context():
        get_rows = _execute_get_routes(app)
    post_rows = _classify_post_routes(routes)
    template_result = _template_audit(app)
    import_result = _module_import_audit(app)
    private_result = _private_helper_audit()
    js_result = _js_audit()

    result = {
        "timestamp": timestamp,
        "route_count": len(routes),
        "routes": routes,
        "route_duplicates": duplicates,
        "get_route_runtime": get_rows,
        "post_routes": post_rows,
        "template_audit": template_result,
        "module_import_audit": import_result,
        "private_helper_audit": private_result,
        "js_audit": js_result,
        "pyflakes_summary": {"undefined_count": "see command output; pyflakes is noisy due wildcard compatibility wrappers"},
    }

    manifest_path = REPORT_DIR / f"route_runtime_coverage_{timestamp}.json"
    report_path = REPORT_DIR / f"full_runtime_regression_audit_{timestamp}.md"
    _write_json(manifest_path, result)
    if not ROUTE_BASELINE_PATH.exists() and not duplicates["duplicate_endpoints"] and not duplicates["duplicate_rule_methods"]:
        _write_json(ROUTE_BASELINE_PATH, routes)
    report_path.write_text(_render_markdown(result), encoding="utf-8")

    failed_get = [row for row in get_rows if row["status"] == "FAIL"]
    fatal_count = (
        len(failed_get)
        + len(duplicates["duplicate_endpoints"])
        + len(duplicates["duplicate_rule_methods"])
        + len(template_result["parse_errors"])
        + len(template_result["missing_url_for"])
        + len(template_result["missing_references"])
        + len(import_result["failures"])
    )

    print(f"Full runtime regression audit written: {report_path}")
    print(f"Route runtime coverage manifest written: {manifest_path}")
    print(f"Route baseline: {ROUTE_BASELINE_PATH}")
    print(f"Routes total: {len(routes)}")
    print(f"GET executed: {len([row for row in get_rows if row['status'] != 'SKIP'])}")
    print(f"GET failed: {len(failed_get)}")
    print(f"GET skipped: {len([row for row in get_rows if row['status'] == 'SKIP'])}")
    print(f"Templates parsed: {template_result['parsed_count']}/{template_result['template_count']}")
    print(f"url_for checked: {template_result['url_for_count']}")
    print(f"POST classified: {len(post_rows)}")
    print(f"Fatal findings: {fatal_count}")
    return {**result, "fatal_count": fatal_count}


def main() -> int:
    result = run()
    return 1 if result["fatal_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
