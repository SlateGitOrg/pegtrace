"""Locate and run the planning SQL.

The SQL lives in ``sql/`` at the repository root. A built wheel carries the same
directory as ``pegtrace/sql``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def sql_dir() -> Path:
    """Directory holding the planning SQL (installed package first, then the checkout)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "sql", here.parents[1] / "sql"):
        if (candidate / "explode.sql").is_file():
            return candidate
    raise FileNotFoundError("cannot find the sql/ directory next to the pegtrace package")


def read_sql(name: str) -> str:
    """Text of ``sql/<name>`` (``name`` may include a sub-directory such as ``tests/x.sql``)."""
    return (sql_dir() / name).read_text(encoding="utf-8")


def execute_script(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """Run every statement of a SQL file, in order."""
    for statement in con.extract_statements(read_sql(name)):
        con.execute(statement)


def query_file(con: duckdb.DuckDBPyConnection, name: str) -> tuple[list[str], list[tuple]]:
    """Run a single-query SQL file; return (column names, rows)."""
    cursor = con.execute(read_sql(name))
    columns = [d[0] for d in cursor.description]
    return columns, cursor.fetchall()


def invariant_files() -> list[str]:
    """Names (relative to ``sql/``) of the invariant queries under ``sql/tests``."""
    return sorted(f"tests/{p.name}" for p in (sql_dir() / "tests").glob("*.sql"))
