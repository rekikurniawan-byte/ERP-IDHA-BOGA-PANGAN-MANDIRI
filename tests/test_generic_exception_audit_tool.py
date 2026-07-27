from pathlib import Path

from tools.audit_generic_exceptions import collect_generic_exception_findings, render_report


def test_generic_exception_audit_flags_unlogged_route_handler(tmp_path: Path):
    route_dir = tmp_path / "app" / "routes"
    route_dir.mkdir(parents=True)
    source = route_dir / "sample_routes.py"
    source.write_text(
        "\n".join([
            "def handler():",
            "    try:",
            "        risky()",
            "    except Exception:",
            "        pass",
        ]),
        encoding="utf-8",
    )

    findings = collect_generic_exception_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].scope == "route"
    assert findings[0].logged is False
    assert findings[0].priority == "P1"


def test_generic_exception_audit_marks_logged_handler_lower_priority(tmp_path: Path):
    service_dir = tmp_path / "app" / "services"
    service_dir.mkdir(parents=True)
    source = service_dir / "sample_service.py"
    source.write_text(
        "\n".join([
            "def handler(logger):",
            "    try:",
            "        risky()",
            "    except Exception:",
            "        logger.exception('failed')",
            "        raise",
        ]),
        encoding="utf-8",
    )

    findings = collect_generic_exception_findings(tmp_path)
    report = render_report(findings)

    assert findings[0].logged is True
    assert findings[0].reraised is True
    assert findings[0].priority == "P2"
    assert "Total except Exception" in report
