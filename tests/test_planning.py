"""Hand-computed netting, scrap, as-of handling and the shared-component fix."""

from __future__ import annotations

import pytest

from conftest import item, plan, rows


@pytest.fixture
def textbook():
    return plan(
        items=[item("A", "make", 1), item("B", "make", 2), item("C", "buy", 3)],
        bom=[("A", "B", 2), ("A", "C", 1), ("B", "C", 3)],
        on_hand=[("A", 10), ("B", 20), ("C", 50)],
        receipts=[("PO-1", "C", "PO", 100, 2)],
        orders=[("S1", "X", "A", 30, 6, 3000.0), ("S2", "X", "A", 40, 8, 4000.0)],
    )


def test_textbook_planned_releases(textbook):
    got = rows(
        textbook,
        "SELECT item_id, release_week, qty FROM planned ORDER BY item_id, release_week",
    )
    assert got == [
        ("A", 5, 20),
        ("A", 7, 40),
        ("B", 3, 20),
        ("B", 5, 80),
        ("C", 2, 170),
        ("C", 4, 40),
    ]


def test_textbook_low_level_codes(textbook):
    assert rows(textbook, "SELECT item_id, llc FROM llc ORDER BY item_id") == [
        ("A", 0),
        ("B", 1),
        ("C", 2),
    ]


def test_textbook_shared_child_is_netted_once_at_its_low_level_code(textbook):
    # C is a direct child of A (level 1) and of B (level 2): all of its demand is
    # collected before netting, so the 50 on hand and the 100 receipt are used once.
    gross = rows(textbook, "SELECT week, gross FROM net_weekly WHERE item_id = 'C' ORDER BY week")
    assert gross == [(2, 0), (3, 60), (5, 260), (7, 40)]
    (total,) = rows(textbook, "SELECT sum(qty) FROM planned WHERE item_id = 'C'")[0]
    assert total == 210  # 360 gross - 50 on hand - 100 receipt


def test_shared_component_llc_netting_versus_per_path_baseline():
    # CB-200: 100 on hand, 70 used directly (level 1) and 50 inside SUB-CTRL (level 2).
    con = plan(
        items=[
            item("FG", "make", 1),
            item("SUB-CTRL", "make", 1),
            item("CB-200", "buy", 4),
        ],
        bom=[("FG", "CB-200", 7), ("FG", "SUB-CTRL", 5), ("SUB-CTRL", "CB-200", 1)],
        on_hand=[("CB-200", 100)],
        orders=[("SO-1", "X", "FG", 10, 8, 100000.0)],
    )
    assert rows(con, "SELECT llc FROM llc WHERE item_id = 'CB-200'") == [(2,)]
    (item_id, _, usages, gross, on_hand, receipts, llc_net, per_path) = rows(
        con,
        "SELECT item_id, llc, usages, gross_total, on_hand, open_receipts, llc_net, "
        "per_path_net FROM netting_comparison",
    )[0]
    assert (item_id, usages, gross, on_hand, receipts) == ("CB-200", 2, 120, 100, 0)
    assert llc_net == 20
    assert per_path == 0


def test_scrap_grosses_up_child_requirement():
    con = plan(
        items=[item("P", "make", 1, scrap=5.0), item("C", "buy", 1)],
        bom=[("P", "C", 1)],
        orders=[("S", "X", "P", 40, 5, 1.0)],
    )
    assert rows(con, "SELECT qty FROM demand WHERE item_id = 'C'") == [(43,)]


def test_scrap_rounding_is_exact_when_the_division_is_whole():
    # 19 / 0.95 is 20 exactly; floating point gives 20.000000000000004
    con = plan(
        items=[item("P", "make", 1, scrap=5.0), item("C", "buy", 1)],
        bom=[("P", "C", 1)],
        orders=[("S", "X", "P", 19, 5, 1.0)],
    )
    assert rows(con, "SELECT qty FROM demand WHERE item_id = 'C'") == [(20,)]


def test_lot_for_lot_planned_receipt_is_the_exact_weekly_shortfall():
    con = plan(
        items=[item("A", "buy", 2)],
        on_hand=[("A", 5)],
        orders=[
            ("S1", "X", "A", 7, 6, 1.0),
            ("S2", "X", "A", 5, 6, 1.0),
            ("S3", "X", "A", 3, 9, 1.0),
        ],
    )
    assert rows(con, "SELECT receipt_week, qty FROM planned ORDER BY receipt_week") == [
        (6, 7),
        (9, 3),
    ]


def test_cumulative_planned_is_the_running_maximum_of_the_deficit():
    # a receipt in week 4 pays back the week-3 deficit, so the week-5 demand is netted
    # against what is left of it
    con = plan(
        items=[item("A", "buy", 1)],
        receipts=[("PO-1", "A", "PO", 10, 4)],
        orders=[("S1", "X", "A", 6, 3, 1.0), ("S2", "X", "A", 6, 5, 1.0)],
    )
    deficits = rows(con, "SELECT week, cum_deficit, cum_planned FROM net_weekly ORDER BY week")
    assert deficits == [(3, 6, 6), (4, -4, 6), (5, 2, 6)]
    assert rows(con, "SELECT receipt_week, qty FROM planned") == [(3, 6)]


def test_release_before_the_as_of_week_is_flagged_past_due():
    con = plan(
        items=[item("A", "buy", 3)],
        orders=[("S", "X", "A", 4, 2, 1.0)],
    )
    assert rows(con, "SELECT receipt_week, release_week, past_due FROM planned") == [(2, -1, True)]


def test_release_on_the_as_of_week_is_not_past_due():
    con = plan(items=[item("A", "buy", 1)], orders=[("S", "X", "A", 4, 2, 1.0)])
    assert rows(con, "SELECT release_week, past_due FROM planned") == [(1, False)]


def test_requirement_before_as_of_is_netted_in_the_as_of_bucket_but_keeps_its_need_week():
    con = plan(
        items=[item("A", "buy", 1)],
        on_hand=[("A", 4)],
        orders=[("S", "X", "A", 4, 1, 1.0), ("T", "X", "A", 2, 6, 1.0)],
        as_of=3,
    )
    assert rows(con, "SELECT need_week, eff_week FROM demand WHERE demand_id = 'S'") == [(1, 3)]
    # the on-hand covers the old requirement; the week-6 order needs a planned receipt
    assert rows(con, "SELECT receipt_week, qty FROM planned") == [(6, 2)]
    # served from stock in week 3 against a need week of 1: two weeks late
    assert rows(con, "SELECT weeks_late FROM peg WHERE demand_id = 'S'") == [(2,)]


def test_scheduled_receipt_due_before_the_as_of_week_arrives_in_the_as_of_week():
    con = plan(
        items=[item("A", "buy", 1)],
        receipts=[("PO-1", "A", "PO", 5, 2)],
        orders=[("S", "X", "A", 5, 4, 1.0)],
        as_of=3,
    )
    assert rows(con, "SELECT count(*) FROM planned") == [(0,)]
    assert rows(con, "SELECT avail_week FROM supply WHERE supply_id = 'PO-1'") == [(3,)]


def test_as_of_week_moves_past_due_flags():
    items = [item("A", "buy", 4)]
    orders = [("S", "X", "A", 1, 8, 1.0)]
    early = plan(items, orders=orders, as_of=1)
    late = plan(items, orders=orders, as_of=6)
    assert rows(early, "SELECT past_due FROM planned") == [(False,)]
    assert rows(late, "SELECT past_due FROM planned") == [(True,)]


def test_planned_demand_does_not_exist_for_items_with_no_orders():
    con = plan(
        items=[item("A", "make", 1), item("B", "buy", 1), item("U", "buy", 1)],
        bom=[("A", "B", 1)],
        orders=[("S", "X", "A", 1, 4, 1.0)],
    )
    assert rows(con, "SELECT count(*) FROM planned WHERE item_id = 'U'") == [(0,)]


def test_low_level_code_is_the_maximum_depth_over_all_paths():
    con = plan(
        items=[
            item("FG", "make", 1),
            item("S1", "make", 1),
            item("S2", "make", 1),
            item("P", "buy", 1),
        ],
        bom=[("FG", "S1", 1), ("S1", "S2", 1), ("S2", "P", 1), ("FG", "P", 1)],
        orders=[("O", "X", "FG", 1, 9, 1.0)],
    )
    assert rows(con, "SELECT item_id, llc FROM llc ORDER BY item_id") == [
        ("FG", 0),
        ("P", 3),
        ("S1", 1),
        ("S2", 2),
    ]
