"""Setiap nama yang dipakai modul rute pecahan harus benar-benar tersedia.

Modul rute besar dipecah menjadi beberapa file yang memakai
`from app.routes.x_routes import *`. Impor bintang tidak membawa nama
berawalan `_`, jadi fungsi pembantu privat yang dipakai di file pecahan baru
gagal (NameError) ketika halamannya dibuka. Gladi pilot 2026-09-28 menemukan
tambah Mandor dan Pengantar crash karena ini, dan scan menemukan 9 file lain
(tutup periode, saldo awal kas/bank, detail invoice manual, ...).

pyflakes tidak bisa memeriksa file dengan impor bintang, jadi tes ini
menghitungnya sendiri: nama yang dibaca harus didefinisikan di file itu,
diimpor, builtin, atau ikut terbawa impor bintang.
"""
import ast
import builtins
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _star_modules(tree):
    return [
        node.module for node in tree.body
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
    ]


def _exported(module_name):
    module = importlib.import_module(module_name)
    names = getattr(module, "__all__", None)
    if names is not None:
        return set(names)
    return {name for name in dir(module) if not name.startswith("_")}


def _undefined_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = _star_modules(tree)
    if not modules:
        return []
    known = set(dir(builtins)) | {"__name__", "__file__", "__doc__"}
    for module_name in modules:
        known |= _exported(module_name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            known.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            known.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            known.add(node.id)
        elif isinstance(node, ast.arg):
            known.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            known.add(node.name)
    return sorted({
        f"{path.relative_to(ROOT)}:{node.lineno} {node.id}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in known
    })


def test_star_import_modules_define_every_name_they_use(app):
    with app.app_context():
        problems = []
        for path in sorted((ROOT / "app").rglob("*.py")):
            problems.extend(_undefined_names(path))
    assert problems == []
