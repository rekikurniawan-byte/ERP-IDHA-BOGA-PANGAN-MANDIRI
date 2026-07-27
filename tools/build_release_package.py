"""Build a clean ERP release/UAT ZIP without local secrets or runtime artifacts."""

from __future__ import annotations

import argparse
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "dist"

EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "node_modules",
}

EXCLUDED_FILES = {
    ".env",
    ".coverage",
}

EXCLUDED_PREFIXES = {
    "instance/logs/",
    "instance/uploads/",
    "instance/backups/",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".zip",
}


def _is_git_dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    parts = set(path.relative_to(ROOT).parts)

    if parts & EXCLUDED_DIR_NAMES:
        return False
    if path.name in EXCLUDED_FILES:
        return False
    if any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def build_release_package(output: Path, *, allow_dirty: bool = False) -> Path:
    if not allow_dirty and _is_git_dirty():
        raise RuntimeError("Working tree belum clean. Gunakan --allow-dirty hanya untuk UAT development.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path == output or output in path.parents:
                continue
            if path.is_dir() or not should_include(path):
                continue
            archive.write(path, path.relative_to(ROOT).as_posix())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or DEFAULT_OUTPUT_DIR / f"ERP_PT_IDHA_BOGA_RELEASE_{timestamp}.zip"
    package_path = build_release_package(output, allow_dirty=args.allow_dirty)
    print(f"Release package written: {package_path}")


if __name__ == "__main__":
    main()
