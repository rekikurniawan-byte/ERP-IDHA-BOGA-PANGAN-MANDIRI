from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
OUT_PATH = ROOT / "database_share" / "idha_boga_staging_dump.sql"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def psycopg_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg2://")
    return url


def safe_url_label(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path.lstrip("/")
    return urlunsplit((parsed.scheme, f"{host}{port}", f"/{database}", "", ""))


def table_list(conn: psycopg.Connection) -> list[tuple[str, str]]:
    query = """
        select schemaname, tablename
        from pg_tables
        where schemaname = 'public'
        order by schemaname, tablename
    """
    with conn.cursor() as cur:
        return [(schema, table) for schema, table in cur.execute(query).fetchall()]


def ordered_tables(conn: psycopg.Connection) -> list[tuple[str, str]]:
    tables = table_list(conn)
    table_set = set(tables)
    dependencies: dict[tuple[str, str], set[tuple[str, str]]] = {
        table: set() for table in tables
    }
    query = """
        select
            child_ns.nspname as child_schema,
            child.relname as child_table,
            parent_ns.nspname as parent_schema,
            parent.relname as parent_table
        from pg_constraint c
        join pg_class child on child.oid = c.conrelid
        join pg_namespace child_ns on child_ns.oid = child.relnamespace
        join pg_class parent on parent.oid = c.confrelid
        join pg_namespace parent_ns on parent_ns.oid = parent.relnamespace
        where c.contype = 'f'
          and child_ns.nspname = 'public'
          and parent_ns.nspname = 'public'
    """
    with conn.cursor() as cur:
        for child_schema, child_table, parent_schema, parent_table in cur.execute(query).fetchall():
            child_key = (child_schema, child_table)
            parent_key = (parent_schema, parent_table)
            if child_key in table_set and parent_key in table_set and child_key != parent_key:
                dependencies[child_key].add(parent_key)

    ordered: list[tuple[str, str]] = []
    remaining = dict(dependencies)
    while remaining:
        ready = sorted(
            table for table, deps in remaining.items() if not deps.intersection(remaining)
        )
        if not ready:
            ordered.extend(sorted(remaining))
            break
        ordered.extend(ready)
        for table in ready:
            remaining.pop(table, None)
    return ordered


def table_columns(conn: psycopg.Connection, schema: str, table: str) -> list[str]:
    query = """
        select column_name
        from information_schema.columns
        where table_schema = %s and table_name = %s
        order by ordinal_position
    """
    with conn.cursor() as cur:
        return [row[0] for row in cur.execute(query, (schema, table)).fetchall()]


def sequence_resets(conn: psycopg.Connection) -> list[str]:
    query = """
        select
            quote_ident(sequence_schema) || '.' || quote_ident(sequence_name) as seq_name,
            quote_ident(table_schema) || '.' || quote_ident(table_name) as table_name,
            quote_ident(column_name) as column_name
        from information_schema.sequences s
        join lateral (
            select table_schema, table_name, column_name
            from information_schema.columns c
            where c.column_default like '%' || s.sequence_name || '%'
              and c.table_schema = s.sequence_schema
            limit 1
        ) c on true
        where sequence_schema = 'public'
        order by sequence_name
    """
    statements: list[str] = []
    with conn.cursor() as cur:
        for seq_name, table_name, column_name in cur.execute(query).fetchall():
            statements.append(
                "select setval('{seq}'::regclass, "
                "coalesce((select max({col}) from {tbl}), 1), "
                "coalesce((select max({col}) from {tbl}), 0) > 0);".format(
                    seq=seq_name,
                    col=column_name,
                    tbl=table_name,
                )
            )
    return statements


def main() -> None:
    load_env_file(ENV_PATH)
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        raise SystemExit("DATABASE_URL is empty. Set it in .env before exporting.")
    if not raw_url.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        raise SystemExit("DATABASE_URL must point to PostgreSQL.")

    url = psycopg_url(raw_url)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(url) as conn, OUT_PATH.open("w", encoding="utf-8", newline="\n") as out:
        tables = ordered_tables(conn)
        out.write("-- IDHA BOGA latest shared PostgreSQL data dump\n")
        out.write(f"-- Source: {safe_url_label(url)}\n")
        out.write("-- Restore after creating schema/running migrations.\n\n")
        out.write("begin;\n")
        if tables:
            table_names = [
                sql.Identifier(schema, table).as_string(conn) for schema, table in tables
            ]
            out.write(f"truncate table {', '.join(table_names)} restart identity cascade;\n\n")

        for schema, table in tables:
            columns = table_columns(conn, schema, table)
            if not columns:
                continue
            copy_sql = sql.SQL("copy {} ({}) to stdout").format(
                sql.Identifier(schema, table),
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            )
            copy_header = sql.SQL("copy {} ({}) from stdin;").format(
                sql.Identifier(schema, table),
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            )
            out.write(copy_header.as_string(conn))
            out.write("\n")
            with conn.cursor() as cur:
                with cur.copy(copy_sql) as copy:
                    for chunk in copy:
                        out.write(bytes(chunk).decode("utf-8") if isinstance(chunk, memoryview) else chunk)
            out.write("\\.\n\n")

        for statement in sequence_resets(conn):
            out.write(statement)
            out.write("\n")
        out.write("commit;\n")

    print(f"Exported {OUT_PATH}")


if __name__ == "__main__":
    main()
