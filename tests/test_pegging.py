"""FIFO pegging and the upward impact walk on small hand-computed plants."""

from __future__ import annotations

from conftest import item, plan, rows


def test_fifo_pegs_split_demand_across_supplies_in_availability_order():
    con = plan(
        items=[item("A", "buy", 1)],
        on_hand=[("A", 6)],
        receipts=[("PO-1", "A", "PO", 10, 3)],
        orders=[("S1", "X", "A", 5, 2, 1.0), ("S2", "X", "A", 8, 4, 1.0)],
    )
    pegs = rows(
        con, "SELECT demand_id, supply_id, qty, weeks_late FROM peg ORDER BY demand_id, supply_id"
    )
    assert pegs == [("S1", "OH-A", 5, 0), ("S2", "OH-A", 1, 0), ("S2", "PO-1", 7, 0)]


def test_a_receipt_due_after_the_need_week_is_late_by_the_difference():
    # one-week lead time makes a planned order possible, so use a long lead time:
    # the planned order cannot arrive before week 1 + 6, the PO arrives in week 5
    con = plan(
        items=[item("A", "buy", 6)],
        receipts=[("PO-1", "A", "PO", 10, 5)],
        orders=[("S", "X", "A", 10, 2, 5000.0)],
    )
    assert rows(con, "SELECT supply_id, qty, weeks_late FROM peg") == [("PO-1", 10, 3)]
    # the planned order for the same week is not needed: a cancel candidate
    assert rows(con, "SELECT planned_id, qty, unpegged_qty, suggestion FROM unpegged_planned") == [
        ("PL-A-2", 10, 10, "cancel")
    ]
    assert rows(con, "SELECT release_week, past_due FROM planned") == [(-4, True)]


def test_partly_pegged_planned_order_is_a_reduce_candidate():
    con = plan(
        items=[item("A", "buy", 6)],
        receipts=[("PO-1", "A", "PO", 6, 5)],
        orders=[("S", "X", "A", 10, 2, 5000.0)],
    )
    assert rows(con, "SELECT supply_id, qty FROM peg ORDER BY supply_id") == [
        ("PL-A-2", 4),
        ("PO-1", 6),
    ]
    assert rows(con, "SELECT unpegged_qty, suggestion FROM unpegged_planned") == [(6, "reduce")]


def test_scheduled_receipt_wins_a_tie_on_availability_against_a_planned_order():
    con = plan(
        items=[item("A", "buy", 6)],
        receipts=[("PO-1", "A", "PO", 10, 7)],
        orders=[("S", "X", "A", 10, 2, 5000.0)],
    )
    # planned order is available at max(2, 1 + 6) = 7, the same week as the PO
    assert rows(con, "SELECT supply_id FROM peg") == [("PO-1",)]


def _two_level():
    """F = 2 x C. C has 8 on hand and a lead time too long for a planned order to help."""
    return plan(
        items=[item("F", "make", 1), item("C", "buy", 6)],
        bom=[("F", "C", 2)],
        on_hand=[("C", 8)],
        receipts=[("PO-C", "C", "PO", 8, 7)],
        orders=[("SO-1", "Acme", "F", 3, 5, 3000.0), ("SO-2", "Beta", "F", 5, 5, 5000.0)],
    )


def test_impact_walk_carries_late_quantity_pro_rata_up_to_each_order():
    con = _two_level()
    # C is needed in week 4 (F releases in week 4), 16 units: 8 from stock, 8 from the PO
    # that arrives in week 7, three weeks late. Half the F planned order is late.
    assert rows(
        con,
        "SELECT order_id, qty_at_risk, weeks_late, revenue_at_risk, root_item, chain "
        "FROM impacted_orders ORDER BY order_id",
    ) == [
        ("SO-1", 1.5, 3, 1500.0, "C", "SO-1 <- F <- C"),
        ("SO-2", 2.5, 3, 2500.0, "C", "SO-2 <- F <- C"),
    ]


def test_impact_paths_reach_only_sales_orders():
    con = _two_level()
    assert rows(
        con,
        "SELECT order_id, root_item, weeks_late, chain FROM impact_paths ORDER BY order_id",
    ) == [("SO-1", "C", 3, ["C", "F"]), ("SO-2", "C", 3, ["C", "F"])]


def test_one_child_demand_late_through_several_supplies_counts_every_late_unit():
    # A needs 1 B per unit and SO-1 wants 10 A in week 10. B has a 10 week lead time, so
    # a planned order cannot land before week 11. PO-1 (4 units, week 11) and the planned
    # order (6 units, week 11) are both 2 weeks late and cover different units of the
    # same demand: all 10 units are late, not just the larger supply's 6.
    con = plan(
        items=[item("A", "make", 1), item("B", "buy", 10)],
        bom=[("A", "B", 1)],
        receipts=[("PO-1", "B", "PO", 4, 11), ("PO-2", "B", "PO", 6, 12)],
        orders=[("SO-1", "Acme", "A", 10, 10, 1000.0)],
    )
    assert rows(
        con,
        "SELECT supply_id, qty, weeks_late FROM peg WHERE item_id = 'B' ORDER BY supply_id",
    ) == [("PL-B-9", 6, 2), ("PO-1", 4, 2)]
    assert rows(
        con,
        "SELECT qty_at_risk, weeks_late, revenue_at_risk, root_item, chain FROM impacted_orders",
    ) == [(10.0, 2, 1000.0, "B", "SO-1 <- A <- B")]


def test_late_pegs_of_one_demand_add_while_parallel_components_still_overlap():
    # A needs B and C. B is late through two supplies (4 + 6 = all 10 units), C only for
    # 3 units: the 10 late units of B already include C's, so 10 are at risk, not 13.
    con = plan(
        items=[item("A", "make", 1), item("B", "buy", 10), item("C", "buy", 10)],
        bom=[("A", "B", 1), ("A", "C", 1)],
        on_hand=[("C", 7)],
        receipts=[("PO-1", "B", "PO", 4, 11), ("PO-2", "B", "PO", 6, 12)],
        orders=[("SO-1", "Acme", "A", 10, 10, 1000.0)],
    )
    assert rows(con, "SELECT qty_at_risk, revenue_at_risk FROM impacted_orders") == [(10.0, 1000.0)]


def test_only_the_planned_part_of_a_partly_stocked_middle_item_is_late():
    con = plan(
        items=[
            item("A", "make", 1),
            item("M", "make", 1),
            item("L", "buy", 10),
        ],
        bom=[("A", "M", 1), ("M", "L", 1)],
        on_hand=[("M", 4)],
        orders=[("SO-1", "Acme", "A", 10, 10, 1000.0)],
    )
    # M: 4 on hand, 6 planned (release week 8); L is needed in week 8 for those 6 only,
    # so the 4 units from stock are not at risk
    assert rows(con, "SELECT qty_at_risk, revenue_at_risk FROM impacted_orders") == [(6.0, 600.0)]


def test_two_late_children_of_one_order_cover_the_same_units_so_they_do_not_add():
    # SO needs 8 F. C1 is half late (4 weeks), C2 a quarter late (6 weeks): the
    # affected units overlap, so at risk is the larger share, not the sum.
    con = plan(
        items=[
            item("F", "make", 1),
            item("C1", "buy", 12),
            item("C2", "buy", 14),
        ],
        bom=[("F", "C1", 1), ("F", "C2", 1)],
        on_hand=[("C1", 4), ("C2", 6)],
        orders=[("SO", "Acme", "F", 8, 10, 8000.0)],
    )
    assert rows(
        con,
        "SELECT qty_at_risk, weeks_late, revenue_at_risk, root_item, chain FROM impacted_orders",
    ) == [(4.0, 6, 4000.0, "C2", "SO <- F <- C2")]


def test_distinct_supplies_of_one_order_add_up():
    # F has a 10 week lead time, so a planned order cannot arrive before week 11. The
    # work order (week 8) serves 2 units 2 weeks late, the planned order the other 4
    # units 5 weeks late: different supplies cover different units, so they add up.
    con = plan(
        items=[item("F", "make", 10)],
        receipts=[("WO-F", "F", "WO", 2, 8)],
        orders=[("SO", "Acme", "F", 6, 6, 6000.0)],
    )
    assert rows(con, "SELECT supply_id, qty, weeks_late FROM peg ORDER BY supply_id") == [
        ("PL-F-6", 4, 5),
        ("WO-F", 2, 2),
    ]
    assert rows(
        con, "SELECT qty_at_risk, weeks_late, revenue_at_risk, root_item FROM impacted_orders"
    ) == [(6.0, 5, 6000.0, "F")]


def test_lateness_inherited_from_a_past_due_parent_is_not_a_second_root_cause():
    # F has a 5 week lead time and is due in week 3: its release is already past due.
    # C is in stock, but it is needed before the as-of week, so its peg is late too.
    con = plan(
        items=[item("F", "make", 5), item("C", "buy", 2)],
        bom=[("F", "C", 1)],
        on_hand=[("C", 10)],
        orders=[("SO", "Acme", "F", 2, 3, 2000.0)],
    )
    assert rows(con, "SELECT weeks_late FROM peg WHERE item_id = 'C'") == [(3,)]
    assert rows(con, "SELECT root_item, weeks_late, chain FROM impacted_orders") == [
        ("F", 3, "SO <- F")
    ]


def test_order_due_before_the_as_of_week_is_late_by_the_distance_to_availability():
    con = plan(
        items=[item("A", "buy", 1)],
        on_hand=[("A", 5)],
        orders=[("SO", "Acme", "A", 5, 1, 900.0)],
        as_of=4,
    )
    assert rows(con, "SELECT weeks_late FROM peg") == [(3,)]
    # stock in hand, nothing planned: the order is late only because the as-of
    # week is already past its due week, which is not a supply cause
    assert rows(con, "SELECT count(*) FROM impacted_orders") == [(0,)]


def test_whole_plan_passes_every_invariant_query_on_a_deep_plant(base):
    from pegtrace.runner import check_invariants

    assert check_invariants(base) == {}


def test_dependent_demand_ids_point_back_to_the_parent_planned_order(base):
    bad = rows(
        base,
        "SELECT d.demand_id FROM demand d "
        "LEFT JOIN planned p ON p.planned_id = d.source_planned_id "
        "WHERE d.kind = 'dependent' AND (p.planned_id IS NULL OR p.item_id <> d.parent_item_id)",
    )
    assert bad == []
