"""Input tables and their loaders (CSV directories or Python rows)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import duckdb

# table -> (column definitions, CSV column order)
INPUT_TABLES: dict[str, list[tuple[str, str]]] = {
    "items": [
        ("item_id", "VARCHAR PRIMARY KEY"),
        ("description", "VARCHAR"),
        ("make_buy", "VARCHAR NOT NULL CHECK (make_buy IN ('make', 'buy'))"),
        ("lead_time_weeks", "INTEGER NOT NULL CHECK (lead_time_weeks >= 0)"),
        ("scrap_pct", "DOUBLE NOT NULL CHECK (scrap_pct >= 0 AND scrap_pct < 100)"),
    ],
    "bom": [
        ("parent_id", "VARCHAR NOT NULL"),
        ("child_id", "VARCHAR NOT NULL"),
        ("qty_per", "INTEGER NOT NULL CHECK (qty_per > 0)"),
    ],
    "on_hand": [
        ("item_id", "VARCHAR PRIMARY KEY"),
        ("qty", "INTEGER NOT NULL CHECK (qty >= 0)"),
    ],
    "scheduled_receipts": [
        ("receipt_id", "VARCHAR PRIMARY KEY"),
        ("item_id", "VARCHAR NOT NULL"),
        ("receipt_type", "VARCHAR NOT NULL CHECK (receipt_type IN ('PO', 'WO'))"),
        ("qty", "INTEGER NOT NULL CHECK (qty > 0)"),
        ("due_week", "INTEGER NOT NULL"),
    ],
    "sales_orders": [
        ("order_id", "VARCHAR PRIMARY KEY"),
        ("customer", "VARCHAR NOT NULL"),
        ("item_id", "VARCHAR NOT NULL"),
        ("qty", "INTEGER NOT NULL CHECK (qty > 0)"),
        ("due_week", "INTEGER NOT NULL"),
        ("revenue", "DOUBLE NOT NULL"),
    ],
}


def columns(table: str) -> list[str]:
    """Column names of an input table, in CSV order."""
    return [name for name, _ in INPUT_TABLES[table]]


def create_input_tables(con: duckdb.DuckDBPyConnection) -> None:
    """(Re)create the five empty input tables."""
    for table, cols in INPUT_TABLES.items():
        ddl = ", ".join(f"{name} {decl}" for name, decl in cols)
        con.execute(f"CREATE OR REPLACE TABLE {table} ({ddl})")


def load_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    items: Iterable[Sequence] = (),
    bom: Iterable[Sequence] = (),
    on_hand: Iterable[Sequence] = (),
    scheduled_receipts: Iterable[Sequence] = (),
    sales_orders: Iterable[Sequence] = (),
) -> None:
    """Create the input tables and fill them from row tuples (CSV column order)."""
    create_input_tables(con)
    data = {
        "items": items,
        "bom": bom,
        "on_hand": on_hand,
        "scheduled_receipts": scheduled_receipts,
        "sales_orders": sales_orders,
    }
    for table, rows in data.items():
        rows = [tuple(r) for r in rows]
        if rows:
            marks = ", ".join("?" for _ in columns(table))
            con.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)


def load_csv_dir(con: duckdb.DuckDBPyConnection, directory: str | Path) -> None:
    """Create the input tables and fill them from ``<table>.csv`` files in a directory."""
    directory = Path(directory)
    create_input_tables(con)
    for table in INPUT_TABLES:
        path = directory / f"{table}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"missing input file {path}; run `pegtrace generate` first")
        cols = ", ".join(columns(table))
        con.execute(
            f"INSERT INTO {table} ({cols}) "
            f"SELECT {cols} FROM read_csv(?, header = true, all_varchar = false)",
            [str(path)],
        )


def copy_input_tables(source: duckdb.DuckDBPyConnection, target: duckdb.DuckDBPyConnection) -> None:
    """Copy the five input tables from one connection to another."""
    create_input_tables(target)
    for table in INPUT_TABLES:
        cols = ", ".join(columns(table))
        rows = source.execute(f"SELECT {cols} FROM {table} ORDER BY 1, 2").fetchall()
        if rows:
            marks = ", ".join("?" for _ in columns(table))
            target.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
