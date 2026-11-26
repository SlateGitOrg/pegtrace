from __future__ import annotations

import duckdb
import pytest

from pegtrace.generator import Dataset, generate_dataset
from pegtrace.runner import run_plan
from pegtrace.schema import load_rows


def item(item_id: str, kind: str, lead: int, scrap: float = 0.0) -> tuple:
    return (item_id, item_id.lower(), kind, lead, scrap)


def plan(
    items: list[tuple],
    bom: list[tuple] = (),
    on_hand: list[tuple] = (),
    receipts: list[tuple] = (),
    orders: list[tuple] = (),
    as_of: int = 1,
) -> duckdb.DuckDBPyConnection:
    """Load a small hand-built scenario into a fresh in-memory database and plan it."""
    con = duckdb.connect()
    load_rows(
        con,
        items=items,
        bom=bom,
        on_hand=on_hand,
        scheduled_receipts=receipts,
        sales_orders=orders,
    )
    run_plan(con, as_of)
    return con


def rows(con: duckdb.DuckDBPyConnection, sql: str, *params) -> list[tuple]:
    return con.execute(sql, list(params)).fetchall()


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate_dataset(11)


@pytest.fixture(scope="session")
def base(dataset: Dataset) -> duckdb.DuckDBPyConnection:
    """Seed-11 dataset planned as of week 1 (read-only use)."""
    con = duckdb.connect()
    load_rows(con, **dataset.tables())
    run_plan(con, 1)
    return con
