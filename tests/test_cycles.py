"""Cycle detection in the BOM and the guard in the explosion."""

from __future__ import annotations

import duckdb
import pytest

from pegtrace.runner import CycleError, find_cycles, run_plan
from pegtrace.schema import load_rows
from pegtrace.sqlfiles import execute_script

from conftest import item


def _con(bom, extra_items=()):
    con = duckdb.connect()
    ids = sorted({i for edge in bom for i in edge[:2]})
    items = [item(i, "make", 1) for i in ids] + list(extra_items)
    load_rows(con, items=items, bom=bom)
    return con


def test_cycle_path_is_reported_from_the_first_item():
    con = _con([("RTU", "SUB-A", 1), ("SUB-A", "SUB-B", 1), ("SUB-B", "SUB-A", 1)])
    assert find_cycles(con) == ["SUB-A -> SUB-B -> SUB-A"]


def test_run_fails_with_the_cycle_path_in_the_message():
    con = _con([("RTU", "SUB-A", 1), ("SUB-A", "SUB-B", 1), ("SUB-B", "SUB-A", 1)])
    with pytest.raises(CycleError, match=r"SUB-A -> SUB-B -> SUB-A"):
        run_plan(con, 1)


def test_cycle_without_an_end_item_above_it_is_still_found():
    con = _con([("SUB-A", "SUB-B", 1), ("SUB-B", "SUB-C", 1), ("SUB-C", "SUB-A", 1)])
    assert find_cycles(con) == ["SUB-A -> SUB-B -> SUB-C -> SUB-A"]


def test_self_reference_is_a_cycle():
    con = _con([("RTU", "X", 1), ("X", "X", 1)])
    assert find_cycles(con) == ["X -> X"]


def test_two_separate_cycles_are_both_reported():
    con = _con([("A", "B", 1), ("B", "A", 1), ("C", "D", 1), ("D", "E", 1), ("E", "C", 1)])
    assert find_cycles(con) == ["A -> B -> A", "C -> D -> E -> C"]


def test_acyclic_bom_with_a_diamond_has_no_cycle():
    con = _con([("R", "L", 1), ("R", "M", 1), ("L", "P", 1), ("M", "P", 1)])
    assert find_cycles(con) == []


def test_explosion_terminates_on_a_cyclic_bom():
    con = _con([("RTU", "SUB-A", 1), ("SUB-A", "SUB-B", 1), ("SUB-B", "SUB-A", 1)])
    execute_script(con, "explode.sql")
    paths = [r[0] for r in con.execute("SELECT path_text FROM explosion ORDER BY 1").fetchall()]
    assert paths == ["RTU", "RTU > SUB-A", "RTU > SUB-A > SUB-B"]


def test_failed_run_leaves_no_stale_results():
    from conftest import plan

    con = plan(items=[item("A", "buy", 1)], orders=[("S", "X", "A", 1, 3, 1.0)])
    assert con.execute("SELECT count(*) FROM planned").fetchone() == (1,)
    con.execute("INSERT INTO items VALUES ('B', 'b', 'make', 1, 0), ('C', 'c', 'make', 1, 0)")
    con.execute("INSERT INTO bom VALUES ('B', 'C', 1), ('C', 'B', 1)")
    with pytest.raises(CycleError):
        run_plan(con, 1)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "planned" not in tables and "run_info" not in tables
