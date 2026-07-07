"""PostgreSQL-only atomic transaction smoke service.

POSTGRES-ONLY LOCK: old SQLite file-copy failure injection has been removed.
This smoke test uses a PostgreSQL transaction with a temporary table and rolls it back.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import text

from app.extensions import db

APP_VERSION = "POSTGRES_ONLY_PRODUCTION"
ATOMIC_SMOKE_SCHEMA_VERSION = "POSTGRES_ONLY_ATOMIC_SMOKE_SCHEMA_V1"
FAILURE_INJECTION_POLICY_VERSION = "POSTGRES_ONLY_TRANSACTION_ROLLBACK_DRY_RUN_V1"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _scenario_result(name: str, title: str, status: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "status": status,
        "status_class": "success" if status == "PASS" else "danger" if status == "FAIL" else "warning",
        "message": message,
        **extra,
    }


def run_atomic_failure_injection_smoke() -> Dict[str, Any]:
    scenarios: list[Dict[str, Any]] = []
    failed: list[str] = []
    backend = "unknown"
    try:
        backend = str(db.engine.url).split(":", 1)[0]
        if not backend.startswith("postgresql"):
            raise RuntimeError("POSTGRES-ONLY LOCK: atomic smoke hanya berjalan pada PostgreSQL.")

        with db.engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text("CREATE TEMP TABLE idha_atomic_smoke_tmp (id integer, note text) ON COMMIT DROP"))
                conn.execute(text("INSERT INTO idha_atomic_smoke_tmp (id, note) VALUES (1, 'rollback-check')"))
                count_before = conn.execute(text("SELECT COUNT(*) FROM idha_atomic_smoke_tmp")).scalar_one()
                trans.rollback()
                scenarios.append(_scenario_result(
                    "postgres_transaction_rollback",
                    "PostgreSQL transaction rollback",
                    "PASS" if int(count_before) == 1 else "FAIL",
                    "Temporary insert berhasil dibuat lalu transaction di-rollback tanpa menyentuh data bisnis.",
                    count_before_rollback=int(count_before),
                ))
            except Exception:
                if trans.is_active:
                    trans.rollback()
                raise

        try:
            db.session.execute(text("SELECT 1"))
            scenarios.append(_scenario_result(
                "session_alive_after_rollback",
                "Session alive after rollback",
                "PASS",
                "Session database tetap sehat setelah rollback smoke.",
            ))
        except Exception as exc:
            failed.append("session_alive_after_rollback")
            scenarios.append(_scenario_result(
                "session_alive_after_rollback",
                "Session alive after rollback",
                "FAIL",
                f"Session bermasalah setelah rollback smoke: {exc}",
            ))
    except Exception as exc:
        failed.append("postgres_transaction_rollback")
        scenarios.append(_scenario_result(
            "postgres_transaction_rollback",
            "PostgreSQL transaction rollback",
            "FAIL",
            str(exc),
        ))

    failed += [s["name"] for s in scenarios if s.get("status") == "FAIL" and s["name"] not in failed]
    status = "PASS" if not failed else "FAIL"
    return {
        "schema_version": ATOMIC_SMOKE_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "policy_version": FAILURE_INJECTION_POLICY_VERSION,
        "generated_at": _now_iso(),
        "status": status,
        "status_class": "success" if status == "PASS" else "danger",
        "backend": backend,
        "summary": "PostgreSQL atomic rollback smoke PASS." if status == "PASS" else "PostgreSQL atomic rollback smoke FAIL.",
        "scenarios": scenarios,
        "failed_scenarios": failed,
        "notes": [
            "Tidak ada copy file database karena PostgreSQL tidak memakai file SQLite lokal.",
            "Tes ini memakai TEMP TABLE di transaction terpisah dan rollback, bukan data bisnis.",
        ],
    }


def build_empty_atomic_failure_injection_report(error_message: str) -> Dict[str, Any]:
    return {
        "schema_version": ATOMIC_SMOKE_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "policy_version": FAILURE_INJECTION_POLICY_VERSION,
        "generated_at": _now_iso(),
        "status": "FAIL",
        "status_class": "danger",
        "backend": "postgresql",
        "summary": "Atomic smoke tidak bisa dijalankan.",
        "scenarios": [],
        "failed_scenarios": ["service_error"],
        "error": error_message,
        "notes": ["POSTGRES-ONLY LOCK aktif."],
    }
