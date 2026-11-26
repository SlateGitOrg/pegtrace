"""The synthetic plant: sizes, injected patterns, determinism and CSV round trip."""

from __future__ import annotations

import csv
from collections import defaultdict

import duckdb

from pegtrace.generator import (
    EXPECTED_COLUMNS,
    generate_dataset,
    gross_by_week,
    write_dataset,
)
from pegtrace.schema import columns, load_csv_dir, load_rows


def test_same_seed_gives_identical_data_and_other_seeds_differ():
    a, b, c = generate_dataset(11), generate_dataset(11), generate_dataset(12)
    assert a.tables() == b.tables()
    assert a.sales_orders != c.sales_orders


def test_item_counts_and_make_buy_split(dataset):
    kinds = defaultdict(int)
    for item_id, _, make_buy, _, _ in dataset.items:
        prefix = item_id.split("-")[0]
        kinds["fg" if prefix == "RTU" else "sub" if prefix == "SUB" else "comp"] += 1
        assert (make_buy == "make") == (prefix in ("RTU", "SUB"))
    assert dict(kinds) == {"fg": 10, "sub": 30, "comp": 110}


def test_lead_times_and_scrap_stay_in_range(dataset):
    for item_id, _, make_buy, lead, scrap in dataset.items:
        if make_buy == "buy":
            assert 2 <= lead <= 14, item_id
            assert scrap == 0
        else:
            assert 1 <= lead <= 3, item_id
        assert 0 <= scrap <= 5


def test_bom_is_four_levels_deep_with_twelve_components_shared_across_levels(base):
    assert base.execute("SELECT max(level) FROM explosion").fetchone() == (3,)
    shared = base.execute(
        "SELECT item_id FROM explosion GROUP BY item_id HAVING count(DISTINCT level) > 1 "
        "AND item_id NOT LIKE 'RTU-%' AND item_id NOT LIKE 'SUB-%'"
    ).fetchall()
    assert len(shared) == 12


def test_every_item_is_used_and_every_low_level_code_is_present(base):
    unused = base.execute(
        "SELECT item_id FROM items WHERE item_id NOT LIKE 'RTU-%' AND item_id NOT IN "
        "(SELECT child_id FROM bom)"
    ).fetchall()
    assert unused == []
    assert base.execute("SELECT count(*) FROM llc").fetchone() == (150,)


def test_sales_orders_match_the_stated_profile(dataset):
    orders = dataset.sales_orders
    assert len(orders) == 280
    for _, _, item_id, qty, due, revenue in orders:
        unit = revenue / qty
        assert 1 <= qty <= 12
        assert 2 <= due <= 26
        assert 8_000 <= unit <= 40_000, (item_id, unit)


def test_open_orders_stock_coverage_and_receipt_mix(dataset):
    assert 130 <= len(dataset.scheduled_receipts) <= 150
    types = {r[2] for r in dataset.scheduled_receipts}
    assert types == {"PO", "WO"}
    assert 0.55 <= len(dataset.on_hand) / len(dataset.items) <= 0.65
    assert all(1 <= r[4] <= 26 for r in dataset.scheduled_receipts)


def test_cmp_5t_is_used_only_by_rtu_5_and_rtu_7_at_level_one_without_stock(dataset):
    users = [(p, q) for p, c, q in dataset.bom if c == "CMP-5T"]
    assert users == [("RTU-5", 1), ("RTU-7", 1)]
    assert "CMP-5T" not in {i for i, _ in dataset.on_hand}
    assert not {"RTU-5", "RTU-7"} & {i for i, _ in dataset.on_hand}
    scrap = {i[0]: i[4] for i in dataset.items}
    assert scrap["RTU-5"] == scrap["RTU-7"] == 0
    lead = {i[0]: i[3] for i in dataset.items}
    assert lead["RTU-5"] == lead["RTU-7"] == 1


def test_po_0042_covers_exactly_the_orders_due_in_weeks_7_to_10(dataset):
    sole = [o for o in dataset.sales_orders if o[2] in ("RTU-5", "RTU-7")]
    receipts = {r[0]: r for r in dataset.scheduled_receipts}
    assert receipts["PO-0042"][1:] == (
        "CMP-5T",
        "PO",
        sum(o[3] for o in sole if 7 <= o[4] <= 10),
        6,
    )
    assert receipts["PO-0043"][1:] == ("CMP-5T", "PO", sum(o[3] for o in sole if o[4] >= 12), 11)
    assert not [o for o in sole if o[4] == 11 or o[4] < 7]
    assert [r[0] for r in dataset.scheduled_receipts if r[1] == "CMP-5T"] == ["PO-0042", "PO-0043"]


def test_sub_coil_3_has_five_percent_scrap_and_holds_cb_200(dataset):
    scrap = {i[0]: i[4] for i in dataset.items}
    assert scrap["SUB-COIL-3"] == 5.0
    assert ("SUB-COIL-3", "CB-200", 1) in dataset.bom


def test_expected_whatif_lists_the_orders_due_in_weeks_7_to_10(dataset):
    orders = {o[0]: o for o in dataset.sales_orders}
    assert len(dataset.expected_whatif) == 12
    for order_id, item_id, qty, due, late, revenue in dataset.expected_whatif:
        _, _, o_item, o_qty, o_due, o_revenue = orders[order_id]
        assert (item_id, qty, due, revenue) == (o_item, o_qty, o_due, o_revenue)
        assert 7 <= due <= 10 and late == 11 - due


def test_gross_bound_ignores_stock_and_applies_scrap_and_lead_time():
    from pegtrace.bomgen import Catalog, Item

    items = {
        "P": Item("P", "p", "make", 2, 5.0, 0, "S"),
        "C": Item("C", "c", "buy", 3, 0.0, 1, "S"),
    }
    gross = gross_by_week(Catalog(items, {("P", "C"): 1}), [("S", "X", "P", 40, 9, 1.0)])
    assert gross["C"] == {7: 43}


def test_csv_round_trip_reproduces_the_tables(dataset, tmp_path):
    paths = write_dataset(dataset, tmp_path)
    assert {p.name for p in paths} == {
        "items.csv",
        "bom.csv",
        "on_hand.csv",
        "scheduled_receipts.csv",
        "sales_orders.csv",
        "expected_whatif_impacts.csv",
    }
    con = duckdb.connect()
    load_csv_dir(con, tmp_path)
    for table, expected in dataset.tables().items():
        got = con.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        assert sorted(got) == sorted(tuple(r) for r in expected), table
    with (tmp_path / "expected_whatif_impacts.csv").open() as handle:
        assert next(csv.reader(handle)) == EXPECTED_COLUMNS
    assert columns("bom") == ["parent_id", "child_id", "qty_per"]


def test_inject_cycle_adds_the_two_item_loop():
    ds = generate_dataset(11, inject_cycle=True)
    assert ("SUB-A", "SUB-B", 1) in ds.bom and ("SUB-B", "SUB-A", 1) in ds.bom
    assert {"SUB-A", "SUB-B"} <= {i[0] for i in ds.items}
    con = duckdb.connect()
    load_rows(con, **ds.tables())
    from pegtrace.runner import find_cycles

    assert find_cycles(con) == ["SUB-A -> SUB-B -> SUB-A"]
