"""What-if: slip PO-0042 and compare against the injected truth."""

from __future__ import annotations

import pytest

from pegtrace.runner import check_invariants
from pegtrace.whatif import run_whatif

from conftest import rows


@pytest.fixture(scope="module")
def slip4(base):
    return run_whatif(base, "PO-0042", 4)


def test_slip_of_four_weeks_matches_the_injected_expectation_exactly(slip4, dataset):
    got = {
        r[slip4.columns.index("order_id")]: r[slip4.columns.index("weeks_late")] for r in slip4.rows
    }
    expected = {row[0]: row[4] for row in dataset.expected_whatif}
    assert got == expected
    assert len(got) == 12


def test_slip_revenue_at_risk_equals_the_sum_of_the_expected_revenue(slip4, dataset):
    assert slip4.total_revenue_at_risk == round(sum(r[5] for r in dataset.expected_whatif), 2)
    assert slip4.total_revenue_delta == slip4.total_revenue_at_risk  # base had none of it


def test_slipped_orders_are_whole_orders(slip4, dataset):
    ix = {c: i for i, c in enumerate(slip4.columns)}
    qty = {r[0]: r[2] for r in dataset.expected_whatif}
    for r in slip4.rows:
        assert r[ix["qty_at_risk"]] == qty[r[ix["order_id"]]]


def test_every_impacted_chain_ends_at_cmp_5t(slip4):
    ix = slip4.columns.index("chain")
    root = slip4.columns.index("root_item")
    assert all(r[ix].endswith(" <- CMP-5T") for r in slip4.rows)
    assert {r[root] for r in slip4.rows} == {"CMP-5T"}
    assert slip4.rows[0][ix].count(" <- ") == 2  # order <- model <- part


def test_zero_slip_gives_an_empty_diff(base):
    assert run_whatif(base, "PO-0042", 0).rows == []


def test_pulling_the_receipt_in_does_not_change_any_order(base):
    assert run_whatif(base, "PO-0042", -2).rows == []


def test_shorter_slips_hit_only_the_orders_that_fall_short(base):
    result = run_whatif(base, "PO-0042", 2)
    due = {r[0]: r[4] for r in base.execute("SELECT * FROM sales_orders").fetchall()}
    ix = {c: i for i, c in enumerate(result.columns)}
    got = {r[ix["order_id"]]: r[ix["weeks_late"]] for r in result.rows}
    assert got and all(w == 9 - due[o] for o, w in got.items())  # new due 8, need d - 1
    assert {due[o] for o in got} == {7, 8}


def test_invariant_queries_are_clean_on_the_base_and_the_scenario_run(base, slip4):
    assert check_invariants(base) == {}
    assert check_invariants(slip4.scenario) == {}


def test_base_run_has_no_late_order_for_rtu_5_or_rtu_7(base):
    assert rows(base, "SELECT count(*) FROM impacted_orders WHERE model IN ('RTU-5', 'RTU-7')") == [
        (0,)
    ]


def test_the_scenario_leaves_the_base_tables_untouched(base):
    before = rows(base, "SELECT * FROM scheduled_receipts ORDER BY 1")
    run_whatif(base, "PO-0042", 4)
    assert rows(base, "SELECT * FROM scheduled_receipts ORDER BY 1") == before
    assert rows(base, "SELECT due_week FROM scheduled_receipts WHERE receipt_id = 'PO-0042'") == [
        (6,)
    ]


def test_the_slipped_po_makes_its_planned_replacements_cancel_candidates(base, slip4):
    po_qty = rows(base, "SELECT qty FROM scheduled_receipts WHERE receipt_id = 'PO-0042'")[0][0]
    unpegged = rows(
        slip4.scenario,
        "SELECT sum(unpegged_qty), min(suggestion) FROM unpegged_planned WHERE item_id = 'CMP-5T'",
    )
    assert unpegged == [(po_qty, "cancel")]
    assert rows(base, "SELECT count(*) FROM planned WHERE item_id = 'CMP-5T'") == [(0,)]


def test_unknown_receipt_and_impossible_slip_are_rejected(base):
    with pytest.raises(KeyError):
        run_whatif(base, "PO-9999", 1)
    with pytest.raises(ValueError):
        run_whatif(base, "PO-0042", -6)


def test_a_slip_of_one_week_hits_only_the_first_orders_in_the_window(base):
    result = run_whatif(base, "PO-0042", 1)
    ix = {c: i for i, c in enumerate(result.columns)}
    assert {r[ix["due_week"]] for r in result.rows} == {7}
    assert {r[ix["weeks_late"]] for r in result.rows} == {1}


def test_walk_and_quantity_steps_agree_on_which_orders_are_impacted(base):
    walked = {r[0] for r in rows(base, "SELECT DISTINCT order_id FROM impact_paths")}
    quantified = {r[0] for r in rows(base, "SELECT order_id FROM impacted_orders")}
    assert walked == quantified and len(walked) > 0
