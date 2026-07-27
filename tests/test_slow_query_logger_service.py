from app.services.slow_query_logger_service import _compact_statement


def test_compact_statement_removes_excess_whitespace_and_limits_length():
    statement = "SELECT  *\nFROM invoices\nWHERE invoice_number = %s " + ("x" * 700)

    compact = _compact_statement(statement, limit=80)

    assert "\n" not in compact
    assert "SELECT * FROM invoices" in compact
    assert len(compact) == 83
    assert compact.endswith("...")
