"""Item master and bill of materials for the synthetic rooftop-unit plant.

Structure (all of it is fixed by construction, the seed only picks quantities and
which parts go where):

* 10 finished goods (``RTU-1`` .. ``RTU-10``), 30 subassemblies, 110 purchased
  components, BOM depth 4.
* Subassemblies are either first-level (under a finished good) or second-level
  (under a first-level subassembly), so components sit at BOM level 1, 2 or 3.
* 12 components are deliberately used at two different levels ("shared").
* Parts are split into pool ``A`` (reachable from RTU-5 and RTU-7), pool ``B``
  (reachable from the other models only) and shared. The what-if scenario
  perturbs a part that only RTU-5 and RTU-7 use, so pool A is kept free of
  shortages elsewhere and pool B is where the ordinary exceptions live.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

FINISHED_GOODS = [f"RTU-{i}" for i in range(1, 11)]
TONNAGE = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 10, 8: 12, 9: 15, 10: 20}
FG_COMPRESSOR = {
    1: "3T",
    2: "3T",
    3: "4T",
    4: "6T",
    5: "5T",
    6: "6T",
    7: "5T",
    8: "7T",
    9: "8T",
    10: "8T",
}

# Subassemblies. Pool A first-level subs are listed first.
L1_SUBS = [
    ("SUB-COIL-1", "A"),
    ("SUB-COIL-3", "A"),
    ("SUB-CTRL-1", "A"),
    ("SUB-FAN-1", "A"),
    ("SUB-CAB-1", "A"),
    ("SUB-CAB-2", "A"),
    ("SUB-COIL-2", "B"),
    ("SUB-COIL-4", "B"),
    ("SUB-COIL-5", "B"),
    ("SUB-CTRL-2", "B"),
    ("SUB-CTRL-3", "B"),
    ("SUB-FAN-2", "B"),
    ("SUB-FAN-3", "B"),
    ("SUB-CAB-3", "B"),
]
L2_SUBS = [
    ("SUB-REFR-1", "A"),
    ("SUB-REFR-2", "A"),
    ("SUB-HEAT-1", "A"),
    ("SUB-WIRE-1", "A"),
    ("SUB-ECON-1", "A"),
    ("SUB-DRN-1", "A"),
    ("SUB-REFR-3", "B"),
    ("SUB-REFR-4", "B"),
    ("SUB-HEAT-2", "B"),
    ("SUB-HEAT-3", "B"),
    ("SUB-ECON-2", "B"),
    ("SUB-WIRE-2", "B"),
    ("SUB-WIRE-3", "B"),
    ("SUB-DRN-2", "B"),
    ("SUB-MTG-1", "B"),
    ("SUB-MTG-2", "B"),
]

# (family prefix, suffixes, description template, lead-time range in weeks)
TIER1_FAMILIES = [
    ("CMP", ["3T", "4T", "5T", "6T", "7T", "8T"], "scroll compressor {}", (10, 14)),
    ("DSC", ["30A", "60A", "100A"], "fusible disconnect {}", (2, 5)),
    ("PNL", ["R1", "R2", "R3", "R4", "R5"], "roof panel set {}", (3, 8)),
    ("TST", ["A", "B", "C"], "thermostat kit {}", (2, 6)),
    ("BAS", ["S", "M", "L"], "base rail kit {}", (3, 8)),
]
TIER2_FAMILIES = [
    ("COIL", ["24", "30", "36", "42", "48", "60"], "purchased coil {} MBH", (8, 12)),
    ("FM", ["A", "B", "C", "D", "E", "F"], "condenser fan motor {}", (6, 10)),
    ("FB", ["1", "2", "3", "4"], "fan blade {}", (3, 7)),
    ("CB", ["100", "300", "400", "500"], "control board {}", (8, 14)),
    ("CTR", ["20", "30", "50", "60", "75"], "contactor {}A", (3, 8)),
    ("SNS", ["P1", "P2", "T2", "T3"], "sensor {}", (2, 6)),
]
TIER3_FAMILIES = [
    ("TXV", ["A1", "A2", "B1", "B2", "C1", "C2"], "expansion valve {}", (6, 12)),
    ("CU", ["14", "12", "58", "34", "78", "118", "158", "218"], "copper tube {} in", (3, 8)),
    ("FIN", ["A", "B", "C", "D", "E", "F"], "fin stock {}", (3, 7)),
    ("GSK", ["A", "B", "C", "D", "E"], "gasket {}", (2, 5)),
    ("HRN", ["1", "2", "3", "4", "5", "6"], "wire harness {}", (4, 9)),
    ("FST", ["M3", "M4", "M5", "M10", "M12", "S1", "S2", "S3"], "fastener kit {}", (2, 4)),
    ("CAP", ["1", "2", "3", "4", "5"], "run capacitor {}", (3, 7)),
    ("SWI", ["1", "2", "3", "4", "5"], "pressure switch {}", (4, 9)),
]
# (item id, description, the two BOM levels it is used at, lead time)
SHARED_PARTS = [
    ("CB-200", "control board 200", (1, 2), 6),
    ("CTR-40", "contactor 40A", (1, 2), 5),
    ("SNS-T1", "temperature sensor T1", (1, 2), 4),
    ("FM-PSC", "PSC fan motor", (2, 3), 8),
    ("CAP-45", "dual run capacitor 45uF", (1, 3), 5),
    ("FST-M8", "fastener kit M8", (1, 3), 3),
    ("FST-M6", "fastener kit M6", (2, 3), 3),
    ("GSK-FLT", "filter-drier gasket", (1, 2), 3),
    ("TXV-STD", "standard expansion valve", (2, 3), 9),
    ("FLT-20", "filter-drier 20 cu in", (1, 2), 4),
    ("CU-38", "copper tube 3/8 in", (2, 3), 5),
    ("WIR-14", "wire spool 14 AWG", (2, 3), 4),
]


@dataclass
class Item:
    item_id: str
    description: str
    make_buy: str
    lead_time_weeks: int
    scrap_pct: float
    tier: int  # 0 finished good, 1-3 component tier (BOM level), 4 shared; subs: 1 or 2
    pool: str  # "A", "B" or "S" (shared)
    levels: tuple[int, ...] = field(default_factory=tuple)


@dataclass
class Catalog:
    items: dict[str, Item]
    bom: dict[tuple[str, str], int]

    def __post_init__(self) -> None:
        self._children: dict[str, list[str]] = {}
        for parent, child in sorted(self.bom):
            self._children.setdefault(parent, []).append(child)

    def children(self, parent: str) -> list[str]:
        return self._children.get(parent, [])

    def topological_order(self) -> list[str]:
        """Parents before children (Kahn's algorithm, ties broken by item id)."""
        indegree = {i: 0 for i in self.items}
        for _, child in self.bom:
            indegree[child] += 1
        ready = sorted(i for i, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for child in self.children(node):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()
        return order

    def closure(self, roots: list[str]) -> set[str]:
        """Every item reachable from the given roots (roots included)."""
        seen: set[str] = set()
        stack = list(roots)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self.children(node))
        return seen


def _component_items(rng: np.random.Generator) -> list[Item]:
    comps: list[Item] = []
    for tier, families in ((1, TIER1_FAMILIES), (2, TIER2_FAMILIES), (3, TIER3_FAMILIES)):
        for prefix, suffixes, template, (lo, hi) in families:
            half = (len(suffixes) + 1) // 2
            for i, suffix in enumerate(suffixes):
                item_id = f"{prefix}-{suffix}"
                lead = int(rng.integers(lo, hi + 1))
                if item_id == "CMP-5T":
                    lead = 12
                comps.append(
                    Item(
                        item_id,
                        template.format(suffix),
                        "buy",
                        lead,
                        0.0,
                        tier,
                        "A" if i < half else "B",
                        (tier,),
                    )
                )
    for item_id, desc, levels, lead in SHARED_PARTS:
        comps.append(Item(item_id, desc, "buy", lead, 0.0, 4, "S", levels))
    return comps


def _assign(
    parents: list[str],
    must_cover: list[str],
    allowed: dict[str, list[str]],
    count: dict[str, tuple[int, int]],
    rng: np.random.Generator,
    edges: dict[tuple[str, str], int],
    forced: dict[str, list[str]],
) -> None:
    """Give every parent its forced children, make sure each ``must_cover`` component is
    used by at least one parent that may use it, then top parents up to a random count."""
    kids: dict[str, list[str]] = {p: list(forced.get(p, [])) for p in parents}
    cursor = 0
    for comp in must_cover:
        if any(comp in k for k in kids.values()):
            continue
        for step in range(len(parents)):
            parent = parents[(cursor + step) % len(parents)]
            if comp in allowed[parent]:
                kids[parent].append(comp)
                cursor = (cursor + step + 1) % len(parents)
                break
    for parent in parents:
        lo, hi = count[parent]
        want = int(rng.integers(lo, hi + 1))
        pool = [c for c in allowed[parent] if c not in kids[parent]]
        while len(kids[parent]) < want and pool:
            pick = pool.pop(int(rng.integers(0, len(pool))))
            kids[parent].append(pick)
    for parent, children in kids.items():
        for child in children:
            edges[(parent, child)] = 0


def _qty_per(child: str, rng: np.random.Generator) -> int:
    if child.startswith("CMP-") or child.startswith(("CB-", "TST-")):
        return 1
    if child.startswith(("FST-", "GSK-", "CU-", "FIN-")):
        return int(rng.integers(2, 9))
    return int(rng.choice([1, 1, 1, 2, 2, 3, 4]))


def build_catalog(rng: np.random.Generator) -> Catalog:
    """Items and BOM edges (``qty_per`` filled in), deterministic for a given generator."""
    items: dict[str, Item] = {}
    comps = _component_items(rng)
    comp_by_id = {c.item_id: c for c in comps}
    for c in comps:
        items[c.item_id] = c

    for i, fg in enumerate(FINISHED_GOODS, start=1):
        items[fg] = Item(fg, f"{TONNAGE[i]}-ton rooftop unit", "make", 1, 0.0, 0, "S")
    for sub_id, pool in L1_SUBS:
        items[sub_id] = Item(sub_id, "first-level subassembly", "make", 0, 0.0, 1, pool)
    for sub_id, pool in L2_SUBS:
        items[sub_id] = Item(sub_id, "second-level subassembly", "make", 0, 0.0, 2, pool)

    edges: dict[tuple[str, str], int] = {}
    l1 = [s for s, _ in L1_SUBS]
    l1_a = [s for s, p in L1_SUBS if p == "A"]
    l1_b = [s for s, p in L1_SUBS if p == "B"]
    l2_a = [s for s, p in L2_SUBS if p == "A"]
    l2_b = [s for s, p in L2_SUBS if p == "B"]

    # finished good -> first-level subassemblies
    fg_subs: dict[str, list[str]] = {
        "RTU-5": ["SUB-COIL-1", "SUB-CTRL-1", "SUB-FAN-1", "SUB-CAB-1"],
        "RTU-7": ["SUB-COIL-3", "SUB-CTRL-1", "SUB-FAN-1", "SUB-CAB-2"],
    }
    others = [fg for fg in FINISHED_GOODS if fg not in fg_subs]
    for k, fg in enumerate(others):
        picks = [l1_b[k % len(l1_b)]]
        if fg in ("RTU-3", "RTU-9"):
            picks.append("SUB-COIL-3")
        pool = [s for s in l1 if s not in picks]
        want = int(rng.integers(4, 6))
        while len(picks) < want:
            picks.append(pool.pop(int(rng.integers(0, len(pool)))))
        fg_subs[fg] = picks
    for fg, subs in fg_subs.items():
        for sub in subs:
            edges[(fg, sub)] = 0

    # first-level -> second-level subassemblies
    parents_a = [s for s in l1_a if s != "SUB-COIL-3"]
    for i, sub in enumerate(l2_a):
        edges[(parents_a[i % len(parents_a)], sub)] = 0
    for i, sub in enumerate(l2_b):
        edges[(l1_b[i % len(l1_b)], sub)] = 0
    for sub in l2_b[:4]:  # a few second-level subs are used by two parents
        extra = l1_b[(l2_b.index(sub) + 3) % len(l1_b)]
        edges[(extra, sub)] = 0

    # components, tier by tier
    shared_for = {lvl: [s[0] for s in SHARED_PARTS if lvl in s[2]] for lvl in (1, 2, 3)}

    def tier_ids(tier: int, pool: str | None = None) -> list[str]:
        return [c.item_id for c in comps if c.tier == tier and (pool is None or c.pool == pool)]

    # level 1: finished goods
    t1_forced = {f"RTU-{i}": [f"CMP-{FG_COMPRESSOR[i]}"] for i in range(1, 11)}
    for fg in ("RTU-7", "RTU-8", "RTU-2"):
        t1_forced[fg].append("CB-200")
    allowed_t1 = {}
    for fg in FINISHED_GOODS:
        pool = [c for c in tier_ids(1) if not c.startswith("CMP-")] + shared_for[1]
        if fg in ("RTU-5", "RTU-7"):
            pool = [c for c in pool if comp_by_id[c].pool in ("A", "S")]
        allowed_t1[fg] = pool + [c for c in t1_forced[fg] if c not in pool]
    must_t1 = [c for c in tier_ids(1) if not c.startswith("CMP-")] + shared_for[1]
    _assign(
        FINISHED_GOODS,
        must_t1,
        allowed_t1,
        {fg: (3, 4) for fg in FINISHED_GOODS},
        rng,
        edges,
        t1_forced,
    )

    # level 2: first-level subassemblies
    t2_forced = {
        f"SUB-COIL-{k}": [f"COIL-{c}"]
        for k, c in zip((1, 2, 3, 4, 5), ("24", "30", "36", "42", "48"), strict=True)
    }
    t2_forced["SUB-COIL-3"].append("CB-200")
    pool_t2 = tier_ids(2) + shared_for[2]
    allowed_t2 = {}
    for sub in l1:
        if sub in l1_a:
            allowed_t2[sub] = [c for c in pool_t2 if comp_by_id[c].pool in ("A", "S")]
        else:
            allowed_t2[sub] = list(pool_t2)
        if sub != "SUB-COIL-3":  # CB-200 reaches the BOM only directly and via SUB-COIL-3
            allowed_t2[sub] = [c for c in allowed_t2[sub] if c != "CB-200"]
        allowed_t2[sub] += [c for c in t2_forced.get(sub, []) if c not in allowed_t2[sub]]
    must_t2 = [c for c in pool_t2 if c != "CB-200"]
    _assign(l1, must_t2, allowed_t2, {s: (4, 6) for s in l1}, rng, edges, t2_forced)

    # level 3: second-level subassemblies
    l2 = [s for s, _ in L2_SUBS]
    pool_t3 = tier_ids(3) + shared_for[3]
    allowed_t3 = {}
    for sub in l2:
        if sub in l2_a:
            allowed_t3[sub] = [c for c in pool_t3 if comp_by_id[c].pool in ("A", "S")]
        else:
            allowed_t3[sub] = list(pool_t3)
    _assign(l2, pool_t3, allowed_t3, {s: (4, 6) for s in l2}, rng, edges, {})

    # quantities
    for key in sorted(edges):
        parent, child = key
        edges[key] = 1 if child.startswith(("RTU-", "SUB-")) else _qty_per(child, rng)
    edges[("RTU-5", "CMP-5T")] = 1
    edges[("RTU-7", "CMP-5T")] = 1

    # make-item lead times and scrap; items under RTU-5/RTU-7 stay within 1-2 weeks so
    # their orders can be planned without a past-due release
    catalog = Catalog(items, edges)
    pool_a_closure = catalog.closure(["RTU-5", "RTU-7"])
    for item in items.values():
        if item.make_buy != "make" or item.tier == 0:
            continue
        cap = 2 if item.item_id in pool_a_closure else 3
        item.lead_time_weeks = int(rng.integers(1, cap + 1))
        item.scrap_pct = float(rng.choice([0, 0, 1, 2, 3, 5]))
    items["SUB-COIL-3"].scrap_pct = 5.0
    items["SUB-COIL-3"].lead_time_weeks = 2
    return catalog


def shared_components(catalog: Catalog) -> list[str]:
    """Purchased components that appear at more than one BOM level."""
    levels: dict[str, set[int]] = {}

    def walk(node: str, depth: int) -> None:
        levels.setdefault(node, set()).add(depth)
        for child in catalog.children(node):
            walk(child, depth + 1)

    for fg in FINISHED_GOODS:
        walk(fg, 0)
    return sorted(
        i for i, lv in levels.items() if catalog.items[i].make_buy == "buy" and len(lv) > 1
    )
