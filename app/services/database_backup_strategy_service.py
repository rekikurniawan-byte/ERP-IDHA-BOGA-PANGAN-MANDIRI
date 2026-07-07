"""PostgreSQL-only database backup strategy.

POSTGRES-ONLY LOCK: SQLite backup strategy has been removed from runtime.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.engine.url import make_url


class DatabaseBackupError(RuntimeError):
    """Raised when database backup or restore drill requirements fail."""


@dataclass(frozen=True)
class DatabaseBackendInfo:
    backend: str
    drivername: str
    database: str | None
    username: str | None = None
    host: str | None = None
    port: int | None = None

    @property
    def is_postgres(self) -> bool:
        return self.backend == "postgresql"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def detect_database_backend(database_url: str) -> DatabaseBackendInfo:
    parsed = make_url(database_url)
    driver = (parsed.drivername or "").lower()
    backend = "postgresql" if driver.startswith("postgresql") or driver.startswith("postgres") else "unknown"
    return DatabaseBackendInfo(
        backend=backend,
        drivername=driver,
        database=parsed.database,
        username=parsed.username,
        host=parsed.host,
        port=parsed.port,
    )


def ensure_command_available(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        raise DatabaseBackupError(f"Command `{command}` tidak ditemukan di server.")
    return resolved


def missing_commands(commands: Iterable[str]) -> list[str]:
    return [command for command in commands if not shutil.which(command)]


class PostgresBackupStrategy:
    backend = "postgresql"
    suffix = ".dump"
    required_backup_commands = ("pg_dump",)
    required_restore_drill_commands = ("pg_restore", "createdb", "dropdb")

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.backend_info = detect_database_backend(database_url)
        if not self.backend_info.is_postgres:
            raise DatabaseBackupError("POSTGRES-ONLY LOCK: backup hanya mendukung PostgreSQL.")

    def validate_tools(self, *, include_restore_drill: bool = False) -> None:
        commands = list(self.required_backup_commands)
        if include_restore_drill:
            commands += list(self.required_restore_drill_commands)
        missing = missing_commands(commands)
        if missing:
            raise DatabaseBackupError("Command PostgreSQL belum lengkap: " + ", ".join(missing))

    def build_pg_dump_command(self, output_path: Path) -> list[str]:
        return [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(output_path),
            self.database_url,
        ]

    def build_pg_restore_command(self, backup_path: Path, restore_database_url: str) -> list[str]:
        return [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            restore_database_url,
            str(backup_path),
        ]

    def build_restore_drill_plan(self, *, backup_path: Path, restore_database_url: str) -> dict[str, object]:
        return {
            "backend": self.backend,
            "backup_path": str(backup_path),
            "restore_database_url": restore_database_url,
            "required_commands": list(self.required_restore_drill_commands),
            "commands": {
                "pg_restore": self.build_pg_restore_command(backup_path, restore_database_url),
                "post_restore_checker": ["python", "tools/check_restore_database.py"],
            },
            "safety_rules": [
                "Jalankan restore drill ke database test, bukan database production aktif.",
                "Matikan app sebelum active restore production.",
                "Verifikasi checksum dump sebelum restore.",
                "Jalankan checker migration, journal balance, dan smoke test setelah restore.",
            ],
        }

    def create_backup(self, *, output_dir: Path, prefix: str = "IDHA_BOGA_POSTGRES_BACKUP") -> Path:
        self.validate_tools(include_restore_drill=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        backup_path = output_dir / f"{prefix}_{_timestamp()}{self.suffix}"
        completed = subprocess.run(self.build_pg_dump_command(backup_path), check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            raise DatabaseBackupError("pg_dump gagal: " + (completed.stderr or completed.stdout or "unknown error"))
        if not backup_path.exists() or backup_path.stat().st_size <= 0:
            raise DatabaseBackupError("pg_dump selesai tetapi file backup kosong/tidak ada.")
        return backup_path


def select_database_backup_strategy(database_url: str):
    strategy = PostgresBackupStrategy(database_url)
    return strategy


def create_database_backup_by_backend(*, database_url: str, output_dir: Path, project_root: Path | None = None) -> Path:
    del project_root
    return select_database_backup_strategy(database_url).create_backup(output_dir=output_dir)


def postgres_restore_drill_requirements(database_url: str, backup_path: Path, restore_database_url: str) -> dict[str, object]:
    strategy = PostgresBackupStrategy(database_url)
    missing = missing_commands(strategy.required_restore_drill_commands)
    return {
        "backend": "postgresql",
        "backup_path": str(backup_path),
        "restore_database_url": restore_database_url,
        "missing_commands": missing,
        "ready": not missing,
        "plan": strategy.build_restore_drill_plan(backup_path=backup_path, restore_database_url=restore_database_url),
    }


def offsite_backup_environment_status() -> dict[str, object]:
    provider = os.getenv("OFFSITE_BACKUP_PROVIDER", "").strip().upper()
    bucket = os.getenv("OFFSITE_BACKUP_BUCKET", "").strip()
    endpoint = os.getenv("OFFSITE_BACKUP_ENDPOINT", "").strip()
    enabled = os.getenv("OFFSITE_BACKUP_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
    configured = bool(provider and bucket and endpoint)
    return {
        "enabled": enabled,
        "provider": provider or None,
        "bucket_configured": bool(bucket),
        "endpoint_configured": bool(endpoint),
        "configured": configured,
        "ready": enabled and configured,
        "note": "Credential secret dicek di server production, tidak ditulis ke repo/ZIP.",
    }
