from pathlib import Path

from tools.audit_deployment_readiness import collect_checks, render_report


def _status(checks, name):
    return next(check.status for check in checks if check.name == name)


def test_deployment_readiness_flags_memory_rate_limit_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_HOSTS", "erp.example.com")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")

    checks = collect_checks(env_file=tmp_path / ".env", assume_production=True)

    assert _status(checks, "DATABASE_URL") == "PASS"
    assert _status(checks, "RATELIMIT_STORAGE_URI") == "FAIL"


def test_deployment_readiness_accepts_shared_rate_limit_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://127.0.0.1:6379/1")
    monkeypatch.setenv("TRUSTED_HOSTS", "erp.example.com")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")

    checks = collect_checks(env_file=tmp_path / ".env", assume_production=True)
    report = render_report(checks)

    assert _status(checks, "RATELIMIT_STORAGE_URI") == "PASS"
    assert "Checklist Server" in report


def test_production_example_has_no_critical_deployment_failure(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    monkeypatch.delenv("TRUSTED_HOSTS", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("PROXY_HEADERS_ENABLED", raising=False)

    checks = collect_checks(env_file=Path(".env.production.example"), assume_production=True)
    critical_failed = [check for check in checks if check.critical and check.status == "FAIL"]

    assert critical_failed == []
