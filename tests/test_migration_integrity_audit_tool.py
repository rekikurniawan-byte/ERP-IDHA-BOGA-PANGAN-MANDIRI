from pathlib import Path

from tools.audit_migration_integrity import (
    audit_migrations,
    collect_migrations,
    render_manifest,
    render_report,
)


def _write_migration(path: Path, revision: str, down_revision):
    path.write_text(
        "\n".join([
            f"revision = {revision!r}",
            f"down_revision = {down_revision!r}",
            "def upgrade():",
            "    pass",
            "def downgrade():",
            "    pass",
            "",
        ]),
        encoding="utf-8",
    )


def test_migration_audit_accepts_single_linear_head(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    _write_migration(versions / "001_init.py", "001", None)
    _write_migration(versions / "002_next.py", "002", "001")

    migrations = collect_migrations(versions)
    audit = audit_migrations(migrations)
    report = render_report(migrations)
    manifest = render_manifest(migrations)

    assert audit["total"] == 2
    assert audit["roots"] == ["001"]
    assert audit["heads"] == ["002"]
    assert audit["missing_parents"] == []
    assert "PASS" in report
    assert "sha256" in manifest


def test_migration_audit_flags_missing_parent_and_multiple_heads(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    _write_migration(versions / "001_init.py", "001", None)
    _write_migration(versions / "002_missing_parent.py", "002", "missing")

    audit = audit_migrations(collect_migrations(versions))

    assert audit["missing_parents"] == ["missing"]
    assert sorted(audit["heads"]) == ["001", "002"]


def test_migration_audit_flags_duplicate_revision(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    _write_migration(versions / "001_a.py", "001", None)
    _write_migration(versions / "001_b.py", "001", None)

    audit = audit_migrations(collect_migrations(versions))

    assert audit["duplicate_revisions"] == ["001"]
