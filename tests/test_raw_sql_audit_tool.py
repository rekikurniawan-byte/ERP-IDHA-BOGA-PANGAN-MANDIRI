from pathlib import Path

from tools.audit_raw_sql import collect_raw_sql_findings, render_report


def test_raw_sql_audit_flags_dynamic_identifier_sql(tmp_path: Path):
    source = tmp_path / "service.py"
    source.write_text(
        "\n".join([
            "from sqlalchemy import text",
            "def count(table):",
            "    return text(f'SELECT COUNT(*) FROM {table}')",
            "def fixed():",
            "    return text('SELECT 1 WHERE id = :id')",
        ]),
        encoding="utf-8",
    )

    findings = collect_raw_sql_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].priority == "P1"
    assert findings[0].kind == "text f-string SQL"


def test_raw_sql_report_contains_summary(tmp_path: Path):
    source = tmp_path / "service.py"
    source.write_text("db.session.execute(f'SELECT * FROM {table}')\n", encoding="utf-8")

    report = render_report(collect_raw_sql_findings(tmp_path))

    assert "Total temuan raw SQL dinamis" in report
    assert "P1 perlu whitelist identifier" in report
