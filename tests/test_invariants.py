"""Each invariant query in sql/tests must actually catch the fault it guards against."""

from __future__ import annotations

import pytest

from pegtrace.runner import InvariantError, check_invariants, run_plan
from pegtrace.sqlfiles import invariant_files

from conftest import item, plan, rows


@pytest.fixture
def con():
    return plan(
        items=[item("F", "make", 1), item("C", "buy", 2)],
        bom=[("F", "C", 2)],
        on_hand=[("C", 4)],
        orders=[("S1", "X", "F", 3, 6, 3000.0), ("S2", "X", "F", 4, 8, 4000.0)],
    )


def test_a_healthy_plan_has_no_failures(con):
    assert check_invariants(con) == {}


def test_there_is_one_query_per_stated_invariant():
    assert {name.split("/")[1] for name in invariant_files()} == {
        "impact_bounds.sql",
        "llc_edges.sql",
        "no_negative_planned.sql",
        "peg_conservation_demand.sql",
        "peg_conservation_supply.sql",
        "projected_balance.sql",
    }


def test_demand_conservation_catches_a_missing_peg(con):
    con.execute("DELETE FROM peg WHERE demand_id = 'S1'")
    assert "tests/peg_conservation_demand.sql" in check_invariants(con)


def test_supply_conservation_catches_an_over_pegged_supply(con):
    con.execute("UPDATE peg SET qty = qty + 5 WHERE supply_id = 'OH-C'")
    assert "tests/peg_conservation_supply.sql" in check_invariants(con)


def test_llc_check_catches_a_child_that_is_not_deeper_than_its_parent(con):
    con.execute("UPDATE llc SET llc = 0 WHERE item_id = 'C'")
    assert "tests/llc_edges.sql" in check_invariants(con)


def test_planned_check_catches_a_negative_planned_receipt(con):
    con.execute("UPDATE net_weekly SET planned_receipt = -1 WHERE planned_receipt > 0")
    assert "tests/no_negative_planned.sql" in check_invariants(con)


def test_planned_check_catches_a_release_that_ignores_the_lead_time(con):
    con.execute("UPDATE planned SET release_week = release_week + 1")
    assert "tests/no_negative_planned.sql" in check_invariants(con)


def test_balance_check_catches_a_short_plan(con):
    con.execute("UPDATE net_weekly SET cum_planned = 0")
    assert "tests/projected_balance.sql" in check_invariants(con)


def test_impact_bounds_catch_revenue_above_the_order(con):
    late = plan(
        items=[item("A", "buy", 6)],
        receipts=[("PO-1", "A", "PO", 10, 5)],
        orders=[("S", "X", "A", 10, 2, 5000.0)],
    )
    assert check_invariants(late) == {}
    late.execute("UPDATE impacted_orders SET revenue_at_risk = revenue * 2")
    assert "tests/impact_bounds.sql" in check_invariants(late)


def _multi_supply():
    return plan(
        items=[item("A", "make", 1), item("B", "buy", 10)],
        bom=[("A", "B", 1)],
        receipts=[("PO-1", "B", "PO", 4, 11), ("PO-2", "B", "PO", 6, 12)],
        orders=[("SO-1", "Acme", "A", 10, 10, 1000.0)],
    )


def test_impact_bounds_compare_late_quantity_with_the_pegs_of_a_multi_supply_demand():
    con = _multi_supply()
    assert check_invariants(con) == {}
    # losing one of the two late pegs from the child demand's late quantity is caught
    con.execute("UPDATE late_demand SET late_qty = 6 WHERE item_id = 'B'")
    found = check_invariants(con)["tests/impact_bounds.sql"]
    assert {r[0] for r in found} >= {"late quantity below own late pegs"}


def test_impact_bounds_catch_a_late_share_that_is_not_carried_up_to_the_order():
    con = _multi_supply()
    con.execute("UPDATE late_demand SET late_qty = 6 WHERE item_id = 'A'")
    found = check_invariants(con)["tests/impact_bounds.sql"]
    assert {r[0] for r in found} == {"late share lost on the way up"}


def test_run_plan_raises_when_an_invariant_fails(monkeypatch, con):
    monkeypatch.setattr(
        "pegtrace.runner.check_invariants", lambda _c: {"tests/x.sql": [("bad row",)]}
    )
    with pytest.raises(InvariantError, match="tests/x.sql"):
        run_plan(con, 1)


def test_pegged_totals_equal_demand_totals_per_item(con):
    per_item = rows(
        con,
        "SELECT d.item_id, sum(d.qty), (SELECT sum(qty) FROM peg p WHERE p.item_id = d.item_id) "
        "FROM demand d GROUP BY d.item_id ORDER BY 1",
    )
    assert all(demand == pegged for _, demand, pegged in per_item)
