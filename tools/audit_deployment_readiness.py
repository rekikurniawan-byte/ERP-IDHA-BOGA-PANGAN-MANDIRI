"""Audit deployment readiness items that can be verified from local config."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_DEPLOYMENT_READINESS_ERP_IDHA_BOGA.md"


@dataclass(frozen=True)
class DeploymentCheck:
    name: str
    status: str
    critical: bool
    message: str


def _env(env: dict[str, str], name: str, default: str = "") -> str:
    return env.get(name, os.getenv(name, default))


def _bool_env(env: dict[str, str], name: str, default: bool = False) -> bool:
    value = _env(env, name, "")
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _redact(value: str) -> str:
    if "://" not in value or "@" not in value:
        return value
    scheme, rest = value.split("://", 1)
    userinfo, host = rest.rsplit("@", 1)
    username = userinfo.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def collect_checks(*, env_file: Path = ROOT / ".env", assume_production: bool = False) -> list[DeploymentCheck]:
    env = {key: str(value) for key, value in dotenv_values(env_file).items() if value is not None} if env_file.exists() else {}

    app_env = _env(env, "APP_ENV", _env(env, "FLASK_ENV", "production")).strip().lower()
    is_production = assume_production or app_env in {"production", "prod"}
    database_url = _env(env, "DATABASE_URL", "")
    rate_limit_uri = _env(env, "RATELIMIT_STORAGE_URI", "memory://")
    trusted_hosts = [item.strip() for item in _env(env, "TRUSTED_HOSTS", _env(env, "APP_TRUSTED_HOSTS", "")).split(",") if item.strip()]
    proxy_headers_enabled = _bool_env(env, "PROXY_HEADERS_ENABLED", is_production)
    session_cookie_secure = _bool_env(env, "SESSION_COOKIE_SECURE", is_production)
    backup_root = _env(env, "BACKUP_ROOT", str(ROOT / "instance" / "backups"))
    upload_root = _env(env, "UPLOAD_ROOT", str(ROOT / "instance" / "uploads"))

    checks = [
        DeploymentCheck(
            "DATABASE_URL",
            "PASS" if database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")) else "FAIL",
            True,
            _redact(database_url) if database_url else "DATABASE_URL kosong atau bukan PostgreSQL.",
        ),
        DeploymentCheck(
            "RATELIMIT_STORAGE_URI",
            "PASS" if (not is_production or not rate_limit_uri.lower().startswith("memory")) else "FAIL",
            True,
            rate_limit_uri if rate_limit_uri else "kosong",
        ),
        DeploymentCheck(
            "TRUSTED_HOSTS",
            "PASS" if (not is_production or trusted_hosts) else "FAIL",
            True,
            ", ".join(trusted_hosts) if trusted_hosts else "kosong",
        ),
        DeploymentCheck(
            "SESSION_COOKIE_SECURE",
            "PASS" if (not is_production or session_cookie_secure) else "FAIL",
            True,
            str(session_cookie_secure),
        ),
        DeploymentCheck(
            "PROXY_HEADERS_ENABLED",
            "REVIEW" if proxy_headers_enabled else ("PASS" if not is_production else "FAIL"),
            True,
            "Aktif: pastikan Gunicorn tidak bisa diakses langsung dan hanya di belakang satu proxy tepercaya."
            if proxy_headers_enabled
            else "Nonaktif.",
        ),
        DeploymentCheck(
            "BACKUP_ROOT",
            "REVIEW",
            False,
            f"{backup_root} | wajib diuji restore off-host dan retensi/enkripsi.",
        ),
        DeploymentCheck(
            "UPLOAD_ROOT",
            "REVIEW",
            False,
            f"{upload_root} | wajib ikut backup attachment.",
        ),
    ]
    return checks


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(checks: list[DeploymentCheck]) -> str:
    critical_failed = [check for check in checks if check.critical and check.status == "FAIL"]
    rows = [[check.status, check.name, "ya" if check.critical else "tidak", check.message] for check in checks]
    return "\n\n".join(
        [
            "# Audit Deployment Readiness ERP Idha Boga",
            "Laporan ini memvalidasi hal yang bisa dicek dari konfigurasi lokal. Validasi Nginx/firewall/Redis nyata tetap harus dilakukan di server.",
            "## Ringkasan",
            _table(
                ["Metrik", "Nilai"],
                [
                    ["Total check", str(len(checks))],
                    ["Critical failed", str(len(critical_failed))],
                ],
            ),
            "## Detail",
            _table(["Status", "Check", "Critical", "Pesan"], rows),
            "## Checklist Server",
            "- Gunicorn bind ke `127.0.0.1` atau Unix socket.",
            "- Port internal ditutup dari jaringan publik.",
            "- `PROXY_HEADERS_ENABLED=1` hanya jika tepat satu reverse proxy tepercaya di depan aplikasi.",
            "- `RATELIMIT_STORAGE_URI` memakai Redis/storage bersama untuk multi-worker.",
            "- Jalankan restore drill off-host: backup, restore, migrate, login, rekonsiliasi.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--assume-production", action="store_true")
    args = parser.parse_args()

    checks = collect_checks(env_file=args.env_file, assume_production=args.assume_production)
    args.output.write_text(render_report(checks), encoding="utf-8")
    critical_failed = sum(1 for check in checks if check.critical and check.status == "FAIL")
    print(f"Deployment readiness audit written: {args.output}")
    print(f"Critical failed: {critical_failed}")


if __name__ == "__main__":
    main()
