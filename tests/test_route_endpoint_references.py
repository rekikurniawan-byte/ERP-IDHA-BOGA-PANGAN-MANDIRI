import ast
import re
from pathlib import Path

from app import create_app


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_URL_FOR_RE = re.compile(r"""url_for\(\s*['"]([A-Za-z0-9_]+\.[A-Za-z0-9_]+)['"]""")


def _collect_referenced_endpoints():
    endpoints = {}

    def add(endpoint, path):
        endpoints.setdefault(endpoint, set()).add(str(path.relative_to(ROOT)))

    for path in (ROOT / "app").rglob("*.py"):
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

    for path in (ROOT / "app" / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for match in TEMPLATE_URL_FOR_RE.finditer(source):
            add(match.group(1), path)

    return endpoints


def test_literal_route_endpoint_references_are_registered():
    app = create_app()
    existing = set(app.view_functions)
    known_blueprints = {endpoint.split(".", 1)[0] for endpoint in existing if "." in endpoint}
    referenced = _collect_referenced_endpoints()

    missing = {
        endpoint: sorted(paths)
        for endpoint, paths in referenced.items()
        if endpoint.split(".", 1)[0] in known_blueprints and endpoint not in existing
    }

    assert missing == {}
