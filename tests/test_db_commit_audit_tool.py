from pathlib import Path

from tools.audit_db_commits import collect_db_session_calls, render_report


def test_db_commit_audit_counts_real_commit_calls_only():
    calls = collect_db_session_calls(Path("app"))

    commit_calls = [call for call in calls if call.method == "commit"]
    rollback_calls = [call for call in calls if call.method == "rollback"]

    assert len(commit_calls) == 101
    assert len(rollback_calls) == 47
    assert all("atomic_transaction_audit_map_service.py:222" not in f"{call.relative_path}:{call.line}" for call in calls)


def test_db_commit_audit_report_prioritizes_route_commits():
    calls = collect_db_session_calls(Path("app"))
    report = render_report(calls)

    assert "| Commit di route | 0 |" in report
    assert "| Rollback di route | 0 |" in report
    assert "| Commit di service | 101 |" in report
    assert "| Fungsi dengan lebih dari satu commit | 0 |" in report
    assert "| Service call ke fungsi ber-commit | 0 |" in report
    assert "| Call eksplisit commit=True | 32 |" in report
    assert "| P0 | 0 |" in report
    assert all(call.layer != "route" for call in calls if call.method == "commit")
    assert all(call.layer != "route" for call in calls if call.method == "rollback")
    assert "commit langsung di route" in report
