"""The window-function netting against an independent row-by-row loop, item-week by item-week."""

from __future__ import annotations

import duckdb
import pytest

from pegtrace.runner import run_plan
from pegtrace.schema import load_rows

from conftest import rows
from reference_mrp import reference_plan


def _reference(dataset, as_of):
    t = dataset.tables()
    return reference_plan(
        t["items"], t["bom"], t["on_hand"], t["scheduled_receipts"], t["sales_orders"], as_of
    )


def _compare(con, dataset, as_of):
    llc, gross, planned = _reference(dataset, as_of)
    sql_llc = dict(rows(con, "SELECT item_id, llc FROM llc"))
    sql_planned = {
        (i, w): q for i, w, q in rows(con, "SELECT item_id, receipt_week, qty FROM planned")
    }
    ref_planned = {(i, w): q for i, weeks in planned.items() for w, q in weeks.items()}
    sql_gross = {
        (i, w): q
        for i, w, q in rows(con, "SELECT item_id, eff_week, sum(qty) FROM demand GROUP BY 1, 2")
    }
    ref_gross = {(i, w): q for i, weeks in gross.items() for w, q in weeks.items() if q}
    return (
        sql_llc == llc,
        {
            k
            for k in sql_planned.keys() | ref_planned.keys()
            if sql_planned.get(k) != ref_planned.get(k)
        },
        {k for k in sql_gross.keys() | ref_gross.keys() if sql_gross.get(k) != ref_gross.get(k)},
        len(ref_planned),
        len(ref_gross),
    )


def test_window_netting_equals_row_by_row_loop_for_every_item_week(base, dataset):
    same_llc, planned_diff, gross_diff, n_planned, n_gross = _compare(base, dataset, 1)
    assert same_llc
    assert planned_diff == set()
    assert gross_diff == set()
    assert n_planned > 1000 and n_gross > 1000  # a real comparison, not an empty one


@pytest.mark.parametrize("as_of", [3, 8])
def test_equivalence_holds_with_a_later_as_of_week(dataset, as_of):
    con = duckdb.connect()
    load_rows(con, **dataset.tables())
    run_plan(con, as_of)
    same_llc, planned_diff, gross_diff, _, _ = _compare(con, dataset, as_of)
    assert same_llc and planned_diff == set() and gross_diff == set()


def test_equivalence_holds_on_another_seed():
    from pegtrace.generator import generate_dataset

    ds = generate_dataset(5)
    con = duckdb.connect()
    load_rows(con, **ds.tables())
    run_plan(con, 1)
    same_llc, planned_diff, gross_diff, _, _ = _compare(con, ds, 1)
    assert same_llc and planned_diff == set() and gross_diff == set()


def test_llc_net_requirement_is_at_least_the_sum_of_per_path_requirements(base):
    comparison = rows(base, "SELECT item_id, llc_net, per_path_net, usages FROM netting_comparison")
    assert len(comparison) >= 12
    assert all(llc_net >= per_path for _, llc_net, per_path, _ in comparison)
    assert all(usages >= 2 for *_, usages in comparison)


def test_property_holds_for_every_shared_component_on_other_seeds():
    from pegtrace.generator import generate_dataset

    for seed in (1, 2, 3):
        ds = generate_dataset(seed)
        con = duckdb.connect()
        load_rows(con, **ds.tables())
        run_plan(con, 1)
        shared = {
            r[0]
            for r in rows(
                con,
                "SELECT item_id FROM explosion GROUP BY item_id HAVING count(DISTINCT level) > 1 "
                "AND item_id NOT LIKE 'RTU-%' AND item_id NOT LIKE 'SUB-%'",
            )
        }
        assert len(shared) == 12
        got = {
            r[0]: (r[1], r[2])
            for r in rows(con, "SELECT item_id, llc_net, per_path_net FROM netting_comparison")
        }
        assert shared <= got.keys()
        assert all(got[i][0] >= got[i][1] for i in shared)


def test_cb_200_shows_the_double_counting_in_the_seeded_data(base):
    row = rows(
        base,
        "SELECT usages, gross_total, on_hand, open_receipts, llc_net, per_path_net "
        "FROM netting_comparison WHERE item_id = 'CB-200'",
    )
    assert row == [(4, 742, 522, 0, 220, 0)]


def test_netting_is_consistent_with_the_projected_balance_identity(base):
    # gross - on hand - receipts + planned reconciles for every netted item at horizon end
    off = rows(
        base,
        """
        SELECT item_id FROM (
            SELECT item_id,
                   arg_max(on_hand + cum_scheduled + cum_planned - cum_gross, week) AS closing
            FROM net_weekly GROUP BY item_id
        ) WHERE closing < 0
        """,
    )
    assert off == []
