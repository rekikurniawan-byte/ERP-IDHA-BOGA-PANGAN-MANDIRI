"""Read-only Alembic migration integrity audit.

The audit parses migration files, verifies revision/down_revision structure, and
records SHA-256 checksums so old migration files can be compared across ZIP,
repository, laptop, backup, and production environments.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSIONS_DIR = ROOT / "migrations" / "versions"
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_MIGRATION_INTEGRITY_ERP_IDHA_BOGA.md"
DEFAULT_MANIFEST = ROOT / "MIGRATION_CHECKSUM_MANIFEST_ERP_IDHA_BOGA.tsv"


@dataclass(frozen=True)
class MigrationRevision:
    path: Path
    revision: str | None
    down_revisions: tuple[str, ...]
    sha256: str

    @property
    def relative_path(self) -> str:
        try:
            return self.path.relative_to(ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()


def _literal_name_value(tree: ast.AST, name: str) -> Any:
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        try:
            return ast.literal_eval(node.value)
        except Exception:
            return None
    return None


def _normalize_down_revision(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list, set)):
        return tuple(str(item) for item in value if item)
    return ()


def parse_migration_file(path: Path) -> MigrationRevision:
    raw = path.read_bytes()
    tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    revision = _literal_name_value(tree, "revision")
    down_revision = _literal_name_value(tree, "down_revision")
    return MigrationRevision(
        path=path,
        revision=str(revision) if revision else None,
        down_revisions=_normalize_down_revision(down_revision),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def collect_migrations(versions_dir: Path = DEFAULT_VERSIONS_DIR) -> list[MigrationRevision]:
    return [
        parse_migration_file(path)
        for path in sorted(versions_dir.glob("*.py"))
        if path.name != "__init__.py"
    ]


def audit_migrations(migrations: list[MigrationRevision]) -> dict[str, Any]:
    revision_counts = Counter(migration.revision for migration in migrations if migration.revision)
    revision_ids = {migration.revision for migration in migrations if migration.revision}
    down_revision_ids = {
        down_revision
        for migration in migrations
        for down_revision in migration.down_revisions
    }
    children: dict[str, list[str]] = defaultdict(list)
    for migration in migrations:
        for down_revision in migration.down_revisions:
            children[down_revision].append(migration.revision or migration.relative_path)

    duplicate_revisions = sorted(revision for revision, count in revision_counts.items() if count > 1)
    missing_revision_files = [migration.relative_path for migration in migrations if not migration.revision]
    missing_parents = sorted(down_revision for down_revision in down_revision_ids if down_revision not in revision_ids)
    roots = sorted(migration.revision for migration in migrations if migration.revision and not migration.down_revisions)
    # Alembic heads are revisions that no other migration names as parent.
    heads = sorted(revision_ids - down_revision_ids)
    branch_points = sorted(parent for parent, child_revisions in children.items() if len(child_revisions) > 1)

    return {
        "total": len(migrations),
        "duplicate_revisions": duplicate_revisions,
        "missing_revision_files": missing_revision_files,
        "missing_parents": missing_parents,
        "roots": roots,
        "heads": heads,
        "branch_points": branch_points,
    }


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(migrations: list[MigrationRevision]) -> str:
    audit = audit_migrations(migrations)
    status = "PASS"
    if audit["duplicate_revisions"] or audit["missing_revision_files"] or audit["missing_parents"] or len(audit["heads"]) != 1:
        status = "FAIL"

    summary_rows = [
        ["Status", status],
        ["Total migration file", str(audit["total"])],
        ["Root revision", str(len(audit["roots"]))],
        ["Head revision", str(len(audit["heads"]))],
        ["Branch point", str(len(audit["branch_points"]))],
        ["Duplicate revision", str(len(audit["duplicate_revisions"]))],
        ["Missing revision var", str(len(audit["missing_revision_files"]))],
        ["Missing parent", str(len(audit["missing_parents"]))],
    ]
    issue_rows = []
    for revision in audit["duplicate_revisions"]:
        issue_rows.append(["Duplicate revision", revision])
    for path in audit["missing_revision_files"]:
        issue_rows.append(["Missing revision var", path])
    for revision in audit["missing_parents"]:
        issue_rows.append(["Missing parent", revision])
    if len(audit["heads"]) != 1:
        issue_rows.append(["Unexpected head count", ", ".join(audit["heads"])])

    revision_rows = [
        [
            migration.relative_path,
            migration.revision or "-",
            ", ".join(migration.down_revisions) or "-",
            migration.sha256,
        ]
        for migration in migrations
    ]

    return "\n\n".join([
        "# Audit Migration Integrity ERP Idha Boga",
        "Laporan ini read-only. Checksum digunakan untuk membuktikan file migration lama tidak berubah antar lingkungan.",
        "## Ringkasan",
        _table(["Metrik", "Nilai"], summary_rows),
        "## Heads",
        _table(["Revision"], [[head] for head in audit["heads"]]),
        "## Roots",
        _table(["Revision"], [[root] for root in audit["roots"]]),
        "## Branch Points",
        _table(["Revision"], [[branch] for branch in audit["branch_points"]]),
        "## Issues",
        _table(["Jenis", "Detail"], issue_rows),
        "## Checklist Verifikasi Database",
        "- Jalankan `flask db heads` dan pastikan sama dengan Head revision di report ini.",
        "- Jalankan `flask db current` pada database target dan pastikan tidak tertinggal.",
        "- Jalankan `flask db upgrade` pada database kosong.",
        "- Jalankan `flask db upgrade` pada snapshot versi sebelumnya.",
        "- Bandingkan `MIGRATION_CHECKSUM_MANIFEST_ERP_IDHA_BOGA.tsv` antar repository, laptop, backup, ZIP, dan production.",
        "- Jika revision yang sama punya checksum berbeda, jangan deploy. Buat migration koreksi baru.",
        "## Manifest",
        _table(["File", "Revision", "Down Revision", "SHA-256"], revision_rows),
        "",
    ])


def render_manifest(migrations: list[MigrationRevision]) -> str:
    lines = ["file\trevision\tdown_revision\tsha256"]
    for migration in migrations:
        lines.append(
            "\t".join([
                migration.relative_path,
                migration.revision or "",
                ",".join(migration.down_revisions),
                migration.sha256,
            ])
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions-dir", type=Path, default=DEFAULT_VERSIONS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    migrations = collect_migrations(args.versions_dir)
    args.output.write_text(render_report(migrations), encoding="utf-8")
    args.manifest.write_text(render_manifest(migrations), encoding="utf-8")
    audit = audit_migrations(migrations)
    print(f"Migration integrity audit written: {args.output}")
    print(f"Migration checksum manifest written: {args.manifest}")
    print(f"Total migrations: {audit['total']}")
    print(f"Heads: {', '.join(audit['heads']) or '-'}")


if __name__ == "__main__":
    main()
