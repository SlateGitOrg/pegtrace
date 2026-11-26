"""Seeded synthetic dataset: stock, open supply and customer orders on top of the BOM.

Everything that makes the data interesting is placed by construction so the
analysis has something known to recover:

* RTU-5 and RTU-7 are the only users of compressor CMP-5T (quantity 1, no scrap,
  no stock). PO-0042 (due week 6) covers exactly their orders due in weeks 7-10;
  nothing is due in week 11; PO-0043 (due week 11) covers the later ones.
  ``expected_whatif_impacts.csv`` lists what slipping PO-0042 to week 10 breaks.
* Control board CB-200 is used directly by three models and inside SUB-COIL-3.
  Its stock covers the busiest single usage but not all usages together.
* Every other purchased part and subassembly has stock or open supply that covers
  the demand falling inside its lead time, except a handful of "problem" parts in
  pool B whose supply arrives late, which give the base plan ordinary exceptions.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pegtrace import schema
from pegtrace.bomgen import (
    Catalog,
    build_catalog,
)

HORIZON_WEEKS = 26
UNIT_PRICE = {
    1: 8400,
    2: 10200,
    3: 12600,
    4: 15600,
    5: 18800,
    6: 22400,
    7: 26400,
    8: 30200,
    9: 34600,
    10: 38600,
}
MODEL_WEIGHT = [1.3, 1.3, 1.2, 1.1, 1.0, 1.0, 1.0, 0.9, 0.8, 0.7]
SOLE_USER_PO = ("PO-0042", "PO-0043")
SLIP_SCENARIO_WEEKS = 4

_PREFIXES = [
    "Summit",
    "Ridgeline",
    "Harbor",
    "Prairie",
    "Keystone",
    "Lakeshore",
    "Granite",
    "Cedar",
    "Meridian",
    "Atlas",
    "Bluebird",
    "Copperline",
]
_SUFFIXES = ["Mechanical", "Property Group", "HVAC Supply", "Facilities", "Builders"]


@dataclass
class Dataset:
    """The five input tables as row tuples (CSV column order) plus the injected truth."""

    items: list[tuple] = field(default_factory=list)
    bom: list[tuple] = field(default_factory=list)
    on_hand: list[tuple] = field(default_factory=list)
    scheduled_receipts: list[tuple] = field(default_factory=list)
    sales_orders: list[tuple] = field(default_factory=list)
    expected_whatif: list[tuple] = field(default_factory=list)

    def tables(self) -> dict[str, list[tuple]]:
        return {
            "items": self.items,
            "bom": self.bom,
            "on_hand": self.on_hand,
            "scheduled_receipts": self.scheduled_receipts,
            "sales_orders": self.sales_orders,
        }


EXPECTED_COLUMNS = ["order_id", "item_id", "qty", "due_week", "weeks_late", "revenue_at_risk"]


def _customers() -> list[str]:
    names = [f"{p} {s}" for s in _SUFFIXES for p in _PREFIXES]
    return names[:30]


def gross_by_week(catalog: Catalog, orders: list[tuple]) -> dict[str, dict[int, int]]:
    """Time-phased gross requirement per item with no netting at any level.

    This is an upper bound on what the plan will need, used only to size stock and
    open supply. A planned release is the requirement shifted back by the lead time;
    each child quantity is grossed up for the parent's scrap and rounded up.
    """
    gross: dict[str, dict[int, int]] = {i: {} for i in catalog.items}
    for order in orders:
        _, _, item_id, qty, due_week, _ = order
        gross[item_id][due_week] = gross[item_id].get(due_week, 0) + qty

    for item_id in catalog.topological_order():
        item = catalog.items[item_id]
        for child in catalog.children(item_id):
            per = catalog.bom[(item_id, child)]
            for week, qty in gross[item_id].items():
                release = week - item.lead_time_weeks
                need = math.ceil(round(per * qty / (1 - item.scrap_pct / 100.0), 6))
                gross[child][release] = gross[child].get(release, 0) + need
    return gross


def _cum(gross: dict[int, int], week: int) -> int:
    return sum(q for w, q in gross.items() if w <= week)


def _plan_supply(
    gross: dict[int, int], lead: int, start: int, rng: np.random.Generator, oh: int, late: bool
) -> list[tuple[int, int]]:
    """Open receipts (due week, qty) so that on hand plus receipts due by week w covers the
    cumulative gross requirement for every week w up to the item's lead time, from ``start``
    on. Beyond the lead time, planned orders can still be released on time."""
    receipts: list[tuple[int, int]] = []

    def supply_at(w: int) -> int:
        return oh + sum(q for d, q in receipts if d <= w)

    w = start
    while w <= lead:
        if _cum(gross, w) > supply_at(w):
            end = min(lead, w + int(rng.integers(2, 6)))
            qty = _cum(gross, end) - supply_at(w)
            qty = math.ceil(qty * (1 + float(rng.uniform(0, 0.1))))
            due = w if late else max(1, w - int(rng.integers(0, 3)))
            receipts.append((due, qty))
        w += 1
    return receipts


def generate_dataset(seed: int = 11, inject_cycle: bool = False) -> Dataset:
    """Build the synthetic plant. The same seed always gives the same dataset."""
    rng = np.random.default_rng(seed)
    catalog = build_catalog(rng)
    items = catalog.items

    # ---- customer orders -------------------------------------------------
    customers = _customers()
    weights = np.array(MODEL_WEIGHT) / sum(MODEL_WEIGHT)
    coil3_users = {p for (p, c) in catalog.bom if c == "SUB-COIL-3" and p.startswith("RTU-")}
    raw: list[tuple[int, int, int, int]] = []  # (due week, model number, qty, customer idx)

    def add_order(model: int, week: int) -> None:
        qty = int(min(12, max(1, rng.geometric(0.28))))
        raw.append((week, model, qty, int(rng.integers(0, len(customers)))))

    # the two sole users of CMP-5T: nothing before week 7, nothing in week 11
    for week in range(7, 11):
        for _ in range(3):
            add_order(int(rng.choice([5, 7])), week)
    for _ in range(26):
        add_order(int(rng.choice([5, 7])), int(rng.integers(12, HORIZON_WEEKS + 1)))
    n_special = len(raw)
    while len(raw) < 280:
        model = int(rng.choice(np.arange(1, 11), p=weights))
        if model in (5, 7):
            continue
        low = 4 if f"RTU-{model}" in coil3_users else 2
        add_order(model, int(rng.integers(low, HORIZON_WEEKS + 1)))
    assert n_special == 38

    raw.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    orders: list[tuple] = []
    for n, (week, model, qty, cust) in enumerate(raw):
        noise = float(rng.uniform(0.97, 1.03))
        revenue = round(qty * UNIT_PRICE[model] * noise, -1)
        orders.append(
            (f"SO-{1001 + n}", customers[cust], f"RTU-{model}", qty, week, float(revenue))
        )

    gross = gross_by_week(catalog, orders)

    # ---- sole-user purchase orders for CMP-5T -----------------------------
    sole = [o for o in orders if o[2] in ("RTU-5", "RTU-7")]
    early_qty = sum(o[3] for o in sole if 7 <= o[4] <= 10)
    late_qty = sum(o[3] for o in sole if o[4] >= 12)
    assert not any(o[4] == 11 or o[4] < 7 for o in sole)

    # ---- stock and open supply -------------------------------------------
    closure_a = catalog.closure(["RTU-5", "RTU-7"])
    candidates = sorted(
        i
        for i, it in items.items()
        if it.pool == "B" and i not in closure_a and it.make_buy == "buy" and it.tier in (1, 2, 3)
    )
    problem: list[str] = []
    wanted = {1: 1, 2: 3, 3: 4}
    for tier, count in wanted.items():
        tier_items = [i for i in candidates if items[i].tier == tier and _cum(gross[i], 6) > 0]
        order = rng.permutation(len(tier_items))
        problem.extend(tier_items[int(k)] for k in order[:count])
    sub_candidates = sorted(
        i
        for i, it in items.items()
        if it.make_buy == "make" and it.tier == 1 and it.pool == "B" and _cum(gross[i], 6) > 0
    )
    problem.append(sub_candidates[int(rng.integers(0, len(sub_candidates)))])
    problem_set = set(problem)

    fixed = {"CMP-5T", "CB-200", "SUB-COIL-3"}
    eligible = sorted(
        i for i in items if items[i].tier != 0 and i not in fixed and i not in problem_set
    )
    n_oh = round(0.6 * len(items)) - 1  # CB-200 always holds stock
    oh_items = {eligible[int(k)] for k in rng.permutation(len(eligible))[:n_oh]}

    on_hand: dict[str, int] = {}
    receipts: list[tuple[str, int, int]] = []  # (item, due, qty)
    for item_id in sorted(items):
        item = items[item_id]
        if item.tier == 0 or item_id in fixed:
            continue
        lead = item.lead_time_weeks
        need = _cum(gross[item_id], lead)
        is_problem = item_id in problem_set
        oh = 0
        if item_id in oh_items:
            if need > 0:
                oh = max(1, round(need * float(rng.uniform(0.3, 1.2))))
            else:
                oh = int(rng.integers(5, 40))
            on_hand[item_id] = oh
        start = 1
        if is_problem:
            start = int(rng.integers(4, max(5, min(lead, 9)) + 1))
        for due, qty in _plan_supply(gross[item_id], lead, start, rng, oh, is_problem):
            receipts.append((item_id, due, qty))

    # CB-200: stock covers the largest single usage, not the sum of usages
    usage: dict[str, int] = {}
    for parent, child in catalog.bom:
        if child != "CB-200":
            continue
        per = catalog.bom[(parent, child)]
        total = 0
        scrap = items[parent].scrap_pct
        for qty in gross[parent].values():
            total += math.ceil(round(per * qty / (1 - scrap / 100.0), 6))
        usage[parent] = total
    on_hand["CB-200"] = math.ceil(1.02 * max(usage.values()))
    assert _cum(gross["CB-200"], items["CB-200"].lead_time_weeks) <= on_hand["CB-200"]
    assert sum(usage.values()) > on_hand["CB-200"] >= max(usage.values())

    # a few surplus open orders so the plan has supply that nothing needs yet
    target = 140
    surplus_pool = sorted(
        i for i in items if items[i].tier != 0 and i not in fixed and i not in problem_set
    )
    while len(receipts) < target:
        item_id = surplus_pool[int(rng.integers(0, len(surplus_pool)))]
        receipts.append(
            (item_id, int(rng.integers(8, HORIZON_WEEKS + 1)), int(rng.integers(3, 30)))
        )

    # ---- number the receipts ----------------------------------------------
    receipts.sort(key=lambda r: (r[0], r[1], r[2]))
    rows: list[tuple] = []
    po_n, wo_n = 0, 0
    for item_id, due, qty in receipts:
        if items[item_id].make_buy == "buy":
            po_n += 1
            while f"PO-{po_n:04d}" in SOLE_USER_PO:
                po_n += 1
            rows.append((f"PO-{po_n:04d}", item_id, "PO", qty, due))
        else:
            wo_n += 1
            rows.append((f"WO-{wo_n:04d}", item_id, "WO", qty, due))
    rows.append((SOLE_USER_PO[0], "CMP-5T", "PO", early_qty, 6))
    rows.append((SOLE_USER_PO[1], "CMP-5T", "PO", late_qty, 11))
    rows.sort(key=lambda r: r[0])

    # ---- expected what-if result ------------------------------------------
    expected = [
        (o[0], o[2], o[3], o[4], 11 - o[4], o[5])
        for o in orders
        if o[2] in ("RTU-5", "RTU-7") and 7 <= o[4] <= 10
    ]

    bom_rows = [(p, c, q) for (p, c), q in sorted(catalog.bom.items())]
    item_rows = [
        (i.item_id, i.description, i.make_buy, i.lead_time_weeks, i.scrap_pct)
        for _, i in sorted(items.items())
    ]
    if inject_cycle:
        item_rows += [
            ("SUB-A", "cyclic subassembly A", "make", 1, 0.0),
            ("SUB-B", "cyclic subassembly B", "make", 1, 0.0),
        ]
        bom_rows += [("RTU-1", "SUB-A", 1), ("SUB-A", "SUB-B", 1), ("SUB-B", "SUB-A", 1)]
        bom_rows.sort()
        item_rows.sort()

    return Dataset(
        items=item_rows,
        bom=bom_rows,
        on_hand=sorted(on_hand.items()),
        scheduled_receipts=rows,
        sales_orders=orders,
        expected_whatif=expected,
    )


def write_dataset(dataset: Dataset, out_dir: str | Path) -> list[Path]:
    """Write the five input CSVs and ``expected_whatif_impacts.csv``; return the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for table, rows in dataset.tables().items():
        written.append(_write_csv(out / f"{table}.csv", schema.columns(table), rows))
    written.append(
        _write_csv(out / "expected_whatif_impacts.csv", EXPECTED_COLUMNS, dataset.expected_whatif)
    )
    return written


def _write_csv(path: Path, header: list[str], rows: list[tuple]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path
