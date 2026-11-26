"""Independent lot-for-lot MRP in plain Python, used only to check the SQL.

It shares nothing with the SQL: low-level codes come from a memoised recursion over
parents, netting is a week-by-week projected-balance loop (no cumulative sums, no
window functions) and the scrap gross-up uses exact fractions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction


def reference_plan(items, bom, on_hand, receipts, orders, as_of):
    """Return (llc, gross, planned): gross[item][week] after as-of bucketing and
    planned[item][receipt_week]."""
    lead = {i[0]: i[3] for i in items}
    scrap = {i[0]: Fraction(i[4]) for i in items}
    parents = defaultdict(list)
    children = defaultdict(list)
    for parent, child, per in bom:
        parents[child].append(parent)
        children[parent].append((child, per))

    memo: dict[str, int] = {}

    def level(item_id: str) -> int:
        if item_id not in memo:
            memo[item_id] = (
                0 if not parents[item_id] else 1 + max(level(p) for p in parents[item_id])
            )
        return memo[item_id]

    llc = {i[0]: level(i[0]) for i in items}
    stock = dict(on_hand)
    sched = defaultdict(lambda: defaultdict(int))
    for _, item_id, _, qty, due in receipts:
        sched[item_id][max(due, as_of)] += qty
    gross = defaultdict(lambda: defaultdict(int))
    for _, _, item_id, qty, due, _ in orders:
        gross[item_id][max(due, as_of)] += qty

    planned = defaultdict(dict)
    for item_id in sorted(llc, key=lambda i: (llc[i], i)):
        weeks = set(gross[item_id]) | set(sched[item_id])
        if not weeks:
            continue
        balance = stock.get(item_id, 0)
        for week in range(as_of, max(weeks) + 1):
            balance += sched[item_id].get(week, 0) - gross[item_id].get(week, 0)
            if balance < 0:
                planned[item_id][week] = -balance
                balance = 0
        for week, qty in planned[item_id].items():
            release = week - lead[item_id]
            for child, per in children[item_id]:
                need = math.ceil(Fraction(per * qty) / (1 - scrap[item_id] / 100))
                gross[child][max(release, as_of)] += need
    return llc, gross, planned
