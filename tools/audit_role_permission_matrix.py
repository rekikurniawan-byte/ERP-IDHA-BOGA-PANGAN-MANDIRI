"""Generate a route permission matrix from Flask route decorators."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOT = ROOT / "app" / "routes"
DEFAULT_OUTPUT = ROOT / "ROLE_PERMISSION_MATRIX_ERP_IDHA_BOGA.md"


@dataclass(frozen=True)
class RoutePermission:
    endpoint: str
    path: str
    methods: tuple[str, ...]
    auth: str
    roles: tuple[str, ...]
    file: Path
    line: int

    @property
    def relative_file(self) -> str:
        try:
            return self.file.relative_to(ROOT).as_posix()
        except ValueError:
            return self.file.as_posix()


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _route_methods(call: ast.Call) -> tuple[str, ...]:
    for keyword in call.keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
            methods = [_literal_string(item) for item in keyword.value.elts]
            return tuple(method for method in methods if method) or ("GET",)
    return ("GET",)


def _decorator_call(decorator: ast.AST) -> ast.Call | None:
    return decorator if isinstance(decorator, ast.Call) else None


def _extract_routes(path: Path) -> list[RoutePermission]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: list[RoutePermission] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        route_path = None
        methods = ("GET",)
        auth = "public"
        roles: tuple[str, ...] = ()

        for decorator in node.decorator_list:
            call = _decorator_call(decorator)
            if call is None:
                if isinstance(decorator, ast.Name) and decorator.id == "login_required":
                    auth = "login_required"
                continue

            name = _call_name(call)
            if name == "route" and call.args:
                route_path = _literal_string(call.args[0]) or "<dynamic>"
                methods = _route_methods(call)
            elif name == "role_required":
                roles = tuple(
                    value
                    for value in (_literal_string(arg) for arg in call.args)
                    if value
                )
                auth = "role_required"
            elif name == "login_required":
                auth = "login_required"

        if route_path is not None:
            routes.append(
                RoutePermission(
                    endpoint=node.name,
                    path=route_path,
                    methods=methods,
                    auth=auth,
                    roles=roles,
                    file=path,
                    line=node.lineno,
                )
            )

    return routes


def collect_route_permissions(scan_root: Path = DEFAULT_SCAN_ROOT) -> list[RoutePermission]:
    routes: list[RoutePermission] = []
    for path in sorted(scan_root.rglob("*_routes.py")):
        routes.extend(_extract_routes(path))
    return sorted(routes, key=lambda row: (row.relative_file, row.line))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(routes: list[RoutePermission]) -> str:
    public_routes = [route for route in routes if route.auth == "public"]
    login_only_routes = [route for route in routes if route.auth == "login_required"]
    role_routes = [route for route in routes if route.auth == "role_required"]

    role_names = sorted({role for route in role_routes for role in route.roles})
    role_rows = []
    for role in role_names:
        allowed = [route for route in role_routes if role in route.roles]
        role_rows.append([role, str(len(allowed)), ", ".join(sorted({route.relative_file for route in allowed}))])

    route_rows = [
        [
            route.relative_file,
            str(route.line),
            ",".join(route.methods),
            route.path,
            route.auth,
            ", ".join(route.roles) if route.roles else "-",
        ]
        for route in routes
    ]

    return "\n\n".join(
        [
            "# Role Permission Matrix ERP Idha Boga",
            "Laporan ini dihasilkan otomatis dari decorator route agar matrix tidak terpisah dari kode.",
            "## Ringkasan",
            _table(
                ["Metrik", "Nilai"],
                [
                    ["Total route", str(len(routes))],
                    ["Role guarded", str(len(role_routes))],
                    ["Login only", str(len(login_only_routes))],
                    ["Public", str(len(public_routes))],
                ],
            ),
            "## Per Role",
            _table(["Role", "Route Count", "File"], role_rows),
            "## Detail Route",
            _table(["File", "Line", "Methods", "Path", "Auth", "Roles"], route_rows),
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-root", type=Path, default=DEFAULT_SCAN_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    routes = collect_route_permissions(args.scan_root)
    args.output.write_text(render_report(routes), encoding="utf-8")
    print(f"Role permission matrix written: {args.output}")
    print(f"Total routes: {len(routes)}")


if __name__ == "__main__":
    main()
