"""Penjaga: kegagalan tidak boleh ditelan diam-diam.

Penilaian pra-produksi 2026-09-27: di jalur uang tidak ada except yang
menelan kegagalan posting. Tes ini menjaga supaya tidak ada yang muncul:
`except Exception`/`except:` yang isinya hanya pass/continue dilarang di app/.
Tangkapan sempit (ValueError saat membaca tanggal, dsb.) tetap boleh.
"""
import ast
from pathlib import Path

BROAD = {"Exception", "BaseException"}


def test_tidak_ada_except_luas_yang_diam():
    offenders = []
    for path in sorted(Path("app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or ast.unparse(node.type) in BROAD
            silent = len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Continue))
            if broad and silent:
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
