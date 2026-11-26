"""What-if: shift one scheduled receipt, replan a copy, diff impacted orders."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from pegtrace.runner import run_plan
from pegtrace.schema import copy_input_tables
from pegtrace.sqlfiles import execute_script


@dataclass
class WhatIfResult:
    """Outcome of one scenario. ``scenario`` is the replanned in-memory connection."""

    receipt_id: str
    item_id: str
    old_due_week: int
    new_due_week: int
    columns: list[str]
    rows: list[tuple]
    scenario: duckdb.DuckDBPyConnection

    @property
    def total_revenue_delta(self) -> float:
        index = self.columns.index("revenue_delta")
        return round(sum(r[index] for r in self.rows), 2)

    @property
    def total_revenue_at_risk(self) -> float:
        index = self.columns.index("revenue_at_risk")
        return round(sum(r[index] for r in self.rows), 2)


def run_whatif(base: duckdb.DuckDBPyConnection, receipt_id: str, slip_weeks: int) -> WhatIfResult:
    """Replan with ``receipt_id`` due ``slip_weeks`` later (negative pulls it in).

    ``base`` must hold a completed ``run_plan``. The base connection is only read.
    """
    found = base.execute(
        "SELECT item_id, due_week FROM scheduled_receipts WHERE receipt_id = ?", [receipt_id]
    ).fetchone()
    if found is None:
        raise KeyError(f"no scheduled receipt {receipt_id!r}")
    item_id, old_due = found
    new_due = old_due + slip_weeks
    if new_due < 1:
        raise ValueError(f"slipping {receipt_id} by {slip_weeks} weeks gives week {new_due}")
    (as_of,) = base.execute("SELECT as_of_week FROM run_info").fetchone()

    scenario = duckdb.connect()
    copy_input_tables(base, scenario)
    scenario.execute(
        "UPDATE scheduled_receipts SET due_week = ? WHERE receipt_id = ?", [new_due, receipt_id]
    )
    run_plan(scenario, as_of)

    scenario.execute(
        "CREATE TABLE base_impacted_orders AS SELECT * FROM impacted_orders WHERE false"
    )
    base_rows = base.execute("SELECT * FROM impacted_orders").fetchall()
    if base_rows:
        marks = ", ".join("?" for _ in base_rows[0])
        scenario.executemany(f"INSERT INTO base_impacted_orders VALUES ({marks})", base_rows)
    execute_script(scenario, "whatif_diff.sql")
    cursor = scenario.execute("SELECT * FROM whatif_diff ORDER BY order_id")
    columns = [d[0] for d in cursor.description]
    return WhatIfResult(receipt_id, item_id, old_due, new_due, columns, cursor.fetchall(), scenario)
