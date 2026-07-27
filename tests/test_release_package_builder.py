from pathlib import Path

from tools.build_release_package import should_include


def test_release_package_excludes_local_secrets_and_git():
    root = Path.cwd()

    assert not should_include(root / ".env")
    assert not should_include(root / ".git" / "config")
    assert not should_include(root / "instance" / "logs" / "app.log")
    assert not should_include(root / "instance" / "uploads" / "nota.pdf")
    assert not should_include(root / "instance" / "backups" / "backup.dump")
    assert not should_include(root / "app" / "__pycache__" / "module.pyc")
    assert not should_include(root / "dist" / "old-release.zip")
    assert not should_include(root / "manual-audit.zip")


def test_release_package_allows_source_and_examples():
    root = Path.cwd()

    assert should_include(root / "app" / "__init__.py")
    assert should_include(root / ".env.example")
    assert should_include(root / ".env.production.example")
    assert should_include(root / "migrations" / "versions" / "revision.py")
