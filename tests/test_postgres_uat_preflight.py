from tools import postgres_uat_preflight as preflight


def test_load_environment_file_reads_dotenv_without_overriding_existing_value(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql+psycopg://file:value@localhost/db\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    preflight.load_environment_file(env_file)

    assert preflight.check_database_url().status == "PASS"

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://explicit:value@localhost/db")
    preflight.load_environment_file(env_file)

    assert "explicit" in preflight.check_database_url().message


def test_check_database_url_requires_postgres_url():
    assert preflight.check_database_url({}).status == "FAIL"
    assert preflight.check_database_url({"DATABASE_URL": "sqlite:///local.db"}).status == "FAIL"
    result = preflight.check_database_url({"DATABASE_URL": "postgresql+psycopg://user:secret@localhost/db"})
    assert result.status == "PASS"
    assert "***" in result.message


def test_check_postgres_tools_reports_missing_and_present_tools():
    paths = {"psql": "C:/pgsql/bin/psql.exe"}

    results = preflight.check_postgres_tools(lambda name: paths.get(name))

    assert results[0].status == "PASS"
    assert results[0].name == "tool:psql"
    assert any(result.status == "FAIL" and result.name == "tool:pg_restore" for result in results)


def test_preflight_local_static_checks_are_callable_without_db(monkeypatch):
    monkeypatch.setattr(preflight, "check_database_url", lambda: preflight._fail("DATABASE_URL", "missing"))
    monkeypatch.setattr(preflight, "check_postgres_tools", lambda: [])
    monkeypatch.setattr(preflight, "check_restore_dump", lambda dump_path: preflight._skip("restore", "skip"))

    checks = preflight.build_checks(from_db=False)
    report = preflight.render_report(checks)

    assert any(check.name == "model:float_inventory" and check.status == "PASS" for check in checks)
    assert any(check.name == "model:raw_sql_dynamic" and check.status == "PASS" for check in checks)
    assert "Preflight PostgreSQL UAT" in report
