"""Thin runner: load inputs, then run the SQL in order. All planning logic is SQL."""

from __future__ import annotations

import duckdb

from pegtrace.sqlfiles import execute_script, invariant_files, query_file

OUTPUT_TABLES = [
    "explosion",
    "llc",
    "demand",
    "planned",
    "net_weekly",
    "supply",
    "supply_ranges",
    "demand_ranges",
    "peg",
    "unpegged_planned",
    "impact_paths",
    "late_demand",
    "impacted_orders",
    "netting_comparison",
    "run_info",
    "whatif_diff",
    "base_impacted_orders",
]


class CycleError(Exception):
    """The bill of materials contains a cycle; ``paths`` lists each one."""

    def __init__(self, paths: list[str]):
        self.paths = paths
        super().__init__("bill of materials has a cycle: " + "; ".join(paths))


class InvariantError(Exception):
    """A query under ``sql/tests`` returned rows; ``failures`` maps file name to rows."""

    def __init__(self, failures: dict[str, list[tuple]]):
        self.failures = failures
        lines = [
            f"{name}: {len(rows)} offending row(s), first {rows[0]}"
            for name, rows in failures.items()
        ]
        super().__init__("plan invariants violated: " + "; ".join(lines))


def find_cycles(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Cycle paths in the BOM, e.g. ``["SUB-A -> SUB-B -> SUB-A"]`` (empty when acyclic)."""
    _, rows = query_file(con, "cycles.sql")
    return [r[0] for r in rows]


def check_invariants(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple]]:
    """Run every ``sql/tests`` query; return the ones that returned rows."""
    failures: dict[str, list[tuple]] = {}
    for name in invariant_files():
        _, rows = query_file(con, name)
        if rows:
            failures[name] = rows
    return failures


def run_plan(con: duckdb.DuckDBPyConnection, as_of_week: int = 1) -> None:
    """Plan the loaded inputs: cycle check, explosion, LLC, level-by-level netting,
    pegging, impact walk, and the invariant queries. Raises ``CycleError`` or
    ``InvariantError``."""
    for table in OUTPUT_TABLES:  # never leave a previous run's results next to new inputs
        con.execute(f"DROP TABLE IF EXISTS {table}")
    cycles = find_cycles(con)
    if cycles:
        raise CycleError(cycles)

    con.execute("SET VARIABLE as_of_week = ?", [int(as_of_week)])
    execute_script(con, "explode.sql")
    execute_script(con, "llc.sql")
    execute_script(con, "init_plan.sql")

    top = con.execute("SELECT coalesce(max(llc), 0) FROM llc").fetchone()[0]
    for level in range(top + 1):
        con.execute("SET VARIABLE llc = ?", [level])
        execute_script(con, "net_level.sql")

    execute_script(con, "peg.sql")
    execute_script(con, "impact.sql")
    for level in range(top, -1, -1):
        con.execute("SET VARIABLE llc = ?", [level])
        execute_script(con, "impact_level.sql")
    execute_script(con, "impacted_orders.sql")
    execute_script(con, "naive.sql")

    con.execute(
        "CREATE OR REPLACE TABLE run_info AS SELECT ?::INTEGER AS as_of_week", [int(as_of_week)]
    )

    failures = check_invariants(con)
    if failures:
        raise InvariantError(failures)
