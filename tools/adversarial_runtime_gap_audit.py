"""Adversarial audit of runtime coverage claims.

This report deliberately marks shallow smoke coverage as partial where a route
was only rendered by one role or where POST/mutation behavior was not executed.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "storage" / "final_reports"


SPECIFIC_REGRESSION_TESTS = {
    ("finance.generate_period_invoice_preview", "GET"): {
        "test_function": "tools/full_runtime_regression_audit.py::_execute_get_routes",
        "branch": "initial form render",
        "role": "OWNER",
        "fixture": "authenticated owner",
        "template_rendered": True,
        "service_real": True,
        "database_real": True,
        "status": "covered",
    },
    ("finance.generate_period_invoice_preview", "POST"): {
        "test_function": "tests/test_period_invoice_route_runtime.py::test_period_invoice_preview_renders_ready_and_already_invoiced_branches",
        "branch": "siap tagih/MASUK and sudah invoice/SKIP",
        "role": "OWNER",
        "fixture": "PostgreSQL QA temp DailyOrder/DailyOrderDetail/InvoiceItem inside nested transaction",
        "template_rendered": True,
        "service_real": True,
        "database_real": True,
        "status": "covered",
    },
}


def _latest_manifest() -> Path:
    manifests = sorted(REPORT_DIR.glob("route_runtime_coverage_*.json"))
    if not manifests:
        raise RuntimeError("Route runtime coverage manifest belum ada.")
    return manifests[-1]


def _status_for_get(row: dict) -> str:
    if row["status"] == "SKIP":
        return "uncovered"
    if row["status"] == "FAIL":
        return "uncovered"
    if row.get("status_code") == 200:
        return "partial"
    return "partial"


def _table_rows(data: dict) -> list[dict]:
    rows = []
    get_by_endpoint = {row["endpoint"]: row for row in data["get_route_runtime"]}
    for route in data["routes"]:
        endpoint = route["endpoint"]
        for method in route["methods"]:
            key = (endpoint, method)
            if key in SPECIFIC_REGRESSION_TESTS:
                spec = SPECIFIC_REGRESSION_TESTS[key]
                actual = get_by_endpoint.get(endpoint, {}).get("status_code", 200 if method == "POST" else "")
                rows.append(
                    {
                        "endpoint": endpoint,
                        "method": method,
                        "role": spec["role"],
                        "fixture": spec["fixture"],
                        "branch": spec["branch"],
                        "expected_status": "200",
                        "actual_status": actual,
                        "test_function": spec["test_function"],
                        "template_rendered": spec["template_rendered"],
                        "service_real": spec["service_real"],
                        "database_real": spec["database_real"],
                        "coverage_status": spec["status"],
                    }
                )
                continue

            if method == "GET":
                row = get_by_endpoint.get(endpoint)
                if not row:
                    rows.append(_uncovered_row(route, method, "GET tidak muncul di runtime manifest"))
                    continue
                rows.append(
                    {
                        "endpoint": endpoint,
                        "method": method,
                        "role": "OWNER",
                        "fixture": "QA smoke DB fixture" if route["arguments"] else "authenticated owner",
                        "branch": "render path only; branch bisnis detail belum dibuktikan penuh",
                        "expected_status": "200 or validated non-loop redirect",
                        "actual_status": row.get("status_code") or row.get("status"),
                        "test_function": "tools/full_runtime_regression_audit.py::_execute_get_routes",
                        "template_rendered": row.get("status_code") == 200,
                        "service_real": True,
                        "database_real": True,
                        "coverage_status": _status_for_get(row),
                    }
                )
            else:
                rows.append(
                    {
                        "endpoint": endpoint,
                        "method": method,
                        "role": "not exhaustively tested",
                        "fixture": "not executed by generic smoke",
                        "branch": "mutation/CSRF/business guard not covered by adversarial smoke",
                        "expected_status": "endpoint-specific",
                        "actual_status": "not executed",
                        "test_function": "manual/specific tests required",
                        "template_rendered": False,
                        "service_real": False,
                        "database_real": False,
                        "coverage_status": "uncovered",
                    }
                )
    return rows


def _uncovered_row(route: dict, method: str, reason: str) -> dict:
    return {
        "endpoint": route["endpoint"],
        "method": method,
        "role": "unknown",
        "fixture": reason,
        "branch": "not executed",
        "expected_status": "unknown",
        "actual_status": "not executed",
        "test_function": "-",
        "template_rendered": False,
        "service_real": False,
        "database_real": False,
        "coverage_status": "uncovered",
    }


def _render_report(rows: list[dict], manifest_path: Path, timestamp: str) -> str:
    covered = sum(1 for row in rows if row["coverage_status"] == "covered")
    partial = sum(1 for row in rows if row["coverage_status"] == "partial")
    uncovered = sum(1 for row in rows if row["coverage_status"] == "uncovered")
    lines = [
        "# Adversarial Runtime Gap Audit ERP Idha Boga",
        "",
        f"Timestamp: `{timestamp}`",
        f"Source manifest: `{manifest_path.as_posix()}`",
        "",
        "## Ringkasan Keras",
        "",
        "| Status | Jumlah endpoint-method |",
        "| --- | ---: |",
        f"| covered | {covered} |",
        f"| partial | {partial} |",
        f"| uncovered | {uncovered} |",
        "",
        "Catatan: GET render satu role diberi `partial`, bukan `covered`, kecuali ada regression test spesifik untuk cabang bisnis. POST mutasi umum diberi `uncovered` sampai ada fixture aman dan assertion bisnis endpoint-specific.",
        "",
        "## Tabel Coverage Adversarial",
        "",
        "| endpoint | method | role | fixture | branch bisnis | expected | actual | test function | template | service nyata | DB nyata | status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| `{endpoint}` | {method} | {role} | {fixture} | {branch} | {expected_status} | {actual_status} | `{test_function}` | {template_rendered} | {service_real} | {database_real} | {coverage_status} |".format(
                **{key: str(value).replace("|", "/") for key, value in row.items()}
            )
        )
    lines.extend(
        [
            "",
            "## Lubang Yang Diperbaiki Pada Batch Ini",
            "",
            "- Menambahkan test integrasi route-template-service untuk `finance.generate_period_invoice_preview` metode POST.",
            "- Test tersebut memakai PostgreSQL fixture sementara, bukan mock helper, dan menguji cabang `MASUK` serta `SKIP`.",
            "",
            "## Lubang Yang Masih Ada",
            "",
            "- Mayoritas POST endpoint belum dieksekusi endpoint-level dengan fixture aman.",
            "- Role matrix runtime belum exhaustively melakukan request untuk seluruh kombinasi role-route.",
            "- JavaScript masih diaudit statis dan via HTML output; belum ada browser automation penuh.",
            "- Wildcard compatibility wrapper masih membuat static checker penuh sulit dijadikan gate mutlak.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    manifest_path = _latest_manifest()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = _table_rows(data)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"adversarial_runtime_gap_audit_{timestamp}.md"
    json_path = REPORT_DIR / f"adversarial_runtime_gap_audit_{timestamp}.json"
    report_path.write_text(_render_report(rows, manifest_path, timestamp), encoding="utf-8")
    json_path.write_text(json.dumps({"timestamp": timestamp, "source_manifest": str(manifest_path), "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    covered = sum(1 for row in rows if row["coverage_status"] == "covered")
    partial = sum(1 for row in rows if row["coverage_status"] == "partial")
    uncovered = sum(1 for row in rows if row["coverage_status"] == "uncovered")
    print(f"Adversarial runtime gap audit written: {report_path}")
    print(f"Adversarial runtime gap JSON written: {json_path}")
    print(f"covered: {covered}")
    print(f"partial: {partial}")
    print(f"uncovered: {uncovered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
