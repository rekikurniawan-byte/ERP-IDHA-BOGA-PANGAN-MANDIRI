"""
Rebuild PostgreSQL schema from the current SQLAlchemy models.

Purpose:
- Fresh staging/production-cutover database preparation.
- Avoid replaying old SQLite-style Alembic migration SQL on PostgreSQL.
- Create the runtime schema exactly from app.models, then stamp Alembic head.

Safety:
- PostgreSQL only.
- Requires explicit --yes.
- Refuses to run if DATABASE_URL is not postgresql/postgres.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Branch, User  # noqa: E402,F401
import app.models  # noqa: E402,F401  # Ensure all model classes are registered in metadata.


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _assert_postgres_url(url: str) -> None:
    lowered = (url or "").lower()
    if not (lowered.startswith("postgresql") or lowered.startswith("postgres")):
        raise SystemExit(
            "[FAIL] DATABASE_URL bukan PostgreSQL. Script ini hanya untuk PostgreSQL staging/production."
        )


def _get_alembic_head() -> str:
    cfg = AlembicConfig(str(ROOT_DIR / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Alembic head tidak tunggal: {heads}")
    return heads[0]


def _drop_existing_model_tables(engine: sa.Engine) -> None:
    """Drop known model tables and Alembic marker.

    Flask-SQLAlchemy 3.x no longer accepts db.drop_all(bind=engine).
    Use SQLAlchemy metadata directly so the same script works on the
    installed runtime used by the user's Windows venv.
    """
    # SQLAlchemy sorts tables by FK dependency for safe drop.
    db.metadata.drop_all(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _stamp_alembic_head(engine: sa.Engine, head: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head": head})


def _bootstrap_owner(owner_password: str) -> None:
    branch = Branch.query.filter_by(code="PUSAT").first()
    if not branch:
        branch = Branch(
            code="PUSAT",
            name="PT Idha Boga Pangan Mandiri",
            address="",
            phone="",
            is_active=True,
        )
        db.session.add(branch)
        db.session.flush()

    user = User.query.filter_by(username="owner").first()
    if not user:
        user = User(
            branch_id=branch.id,
            full_name="Owner Idha Boga",
            username="owner",
            password_hash=generate_password_hash(owner_password),
            role="OWNER",
            is_active=True,
        )
        db.session.add(user)
    else:
        user.branch_id = branch.id
        user.full_name = "Owner Idha Boga"
        user.password_hash = generate_password_hash(owner_password)
        user.role = "OWNER"
        user.is_active = True

    db.session.commit()


def _check_model_schema_alignment(engine: sa.Engine) -> tuple[bool, list[str]]:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    errors: list[str] = []

    for table_name, table in sorted(db.metadata.tables.items()):
        if table_name not in existing_tables:
            errors.append(f"missing table: {table_name}")
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column_name in table.columns.keys():
            if column_name not in existing_columns:
                errors.append(f"missing column: {table_name}.{column_name}")

    return (len(errors) == 0), errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild PostgreSQL schema from SQLAlchemy models.")
    parser.add_argument("--yes", action="store_true", help="Wajib untuk konfirmasi DROP existing model tables.")
    parser.add_argument("--bootstrap-owner", action="store_true", help="Buat/reset akun OWNER awal.")
    parser.add_argument("--owner-password", default="Owner12345!", help="Password akun owner staging.")
    args = parser.parse_args()

    if not args.yes:
        print("[FAIL] Tambahkan --yes karena script ini menghapus dan membangun ulang schema PostgreSQL target.")
        return 2

    url = _database_url()
    _assert_postgres_url(url)

    app = create_app()
    with app.app_context():
        engine = db.engine
        backend = engine.url.get_backend_name()
        if not backend.startswith("postgresql"):
            print(f"[FAIL] Backend aktif bukan PostgreSQL: {backend}")
            return 2

        head = _get_alembic_head()

        print("[1/5] Drop existing model tables in target PostgreSQL...")
        _drop_existing_model_tables(engine)

        print("[2/5] Create all tables from SQLAlchemy models...")
        db.metadata.create_all(bind=engine, checkfirst=True)

        print(f"[3/5] Stamp Alembic head: {head}")
        _stamp_alembic_head(engine, head)

        if args.bootstrap_owner:
            print("[4/5] Bootstrap akun OWNER staging...")
            _bootstrap_owner(args.owner_password)
        else:
            print("[4/5] Bootstrap owner dilewati.")

        print("[5/5] Check model/schema alignment...")
        ok, errors = _check_model_schema_alignment(engine)
        if not ok:
            print("[FAIL] Schema belum match model:")
            for err in errors[:100]:
                print(" -", err)
            if len(errors) > 100:
                print(f" ... dan {len(errors) - 100} error lain")
            return 1

        print("[PASS] PostgreSQL schema rebuilt from models.")
        print(f"Alembic head: {head}")
        if args.bootstrap_owner:
            print("Username: owner")
            print(f"Password: {args.owner_password}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
