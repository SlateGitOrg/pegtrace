"""Plain-text tables for the CLI and the Markdown report."""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from pegtrace.sqlfiles import query_file


def fmt(value: object) -> str:
    """Display form of one cell: whole floats as integers, money-like floats with commas."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def money(value: float) -> str:
    return f"${value:,.0f}"


def text_table(
    headers: Sequence[str], rows: Sequence[Sequence[object]], right: Sequence[str] = ()
) -> str:
    """Fixed-width table; columns named in ``right`` are right-aligned."""
    cells = [[fmt(c) for c in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]

    def line(parts: Sequence[str]) -> str:
        out = []
        for i, part in enumerate(parts):
            out.append(part.rjust(widths[i]) if headers[i] in right else part.ljust(widths[i]))
        return "  ".join(out).rstrip()

    rule = "  ".join("-" * w for w in widths)
    return "\n".join([line(list(headers)), rule, *[line(r) for r in cells]])


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    cells = [[fmt(c).replace("|", "\\|") for c in row] for row in rows]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in cells]
    return "\n".join(out)


def whatif_table(columns: list[str], rows: list[tuple]) -> str:
    """The what-if diff as the table shown by ``pegtrace whatif``, with a total line."""
    ix = {c: columns.index(c) for c in columns}
    shown = [
        (
            r[ix["order_id"]],
            r[ix["customer"]],
            r[ix["model"]],
            r[ix["qty_at_risk"]],
            r[ix["weeks_late"]],
            money(r[ix["revenue_at_risk"]]),
            r[ix["chain"]],
        )
        for r in rows
    ]
    headers = [
        "sales order",
        "customer",
        "model",
        "qty at risk",
        "weeks late",
        "revenue at risk",
        "chain",
    ]
    table = text_table(headers, shown, right=["qty at risk", "weeks late", "revenue at risk"])
    total_qty = sum(r[ix["qty_at_risk"]] for r in rows)
    total_rev = sum(r[ix["revenue_at_risk"]] for r in rows)
    return (
        f"{table}\n\n{len(rows)} orders, {fmt(total_qty)} units, {money(total_rev)} revenue at risk"
    )


def set_item(con: duckdb.DuckDBPyConnection, item_id: str) -> None:
    con.execute("SET VARIABLE item = ?", [item_id])


def item_report(con: duckdb.DuckDBPyConnection, item_id: str) -> str:
    """Orders late through an item, and how LLC netting compares with per-path netting."""
    found = con.execute("SELECT 1 FROM items WHERE item_id = ?", [item_id]).fetchone()
    if found is None:
        raise KeyError(f"unknown item {item_id!r}")
    set_item(con, item_id)
    cols, rows = query_file(con, "item_impact.sql")
    parts = []
    if rows:
        ix = {c: i for i, c in enumerate(cols)}
        shown = [
            (
                r[ix["order_id"]],
                r[ix["customer"]],
                r[ix["model"]],
                r[ix["qty_at_risk"]],
                r[ix["weeks_late"]],
                money(r[ix["revenue_at_risk"]]),
                r[ix["chain"]],
            )
            for r in rows
        ]
        headers = [
            "sales order",
            "customer",
            "model",
            "qty at risk",
            "weeks late",
            "revenue at risk",
            "chain",
        ]
        parts.append(
            f"Orders put late through {item_id}\n\n"
            + text_table(headers, shown, right=["qty at risk", "weeks late", "revenue at risk"])
        )
        parts.append(
            f"{len(rows)} orders, "
            f"{money(sum(r[ix['revenue_at_risk']] for r in rows))} revenue at risk"
        )
    else:
        parts.append(f"No order is late through {item_id}.")
    cols, rows = query_file(con, "item_summary.sql")
    s = dict(zip(cols, rows[0], strict=True))
    lines = [
        f"Netting of {item_id} (low-level code {s['llc']}, {s['make_buy']}, "
        f"lead time {s['lead_time_weeks']} weeks)",
        f"  gross requirements        {fmt(s['gross_requirements'])}",
        f"  on hand                   {fmt(s['on_hand'])}",
        f"  open receipts             {fmt(s['open_receipts'])}",
        f"  planned quantity, LLC      {fmt(s['llc_net_requirement'])}",
    ]
    if s["usages"] is not None:
        lines.append(
            f"  planned quantity, per path {fmt(s['per_path_net'])}"
            f"   ({s['usages']} usages, each netted against the full stock)"
        )
    parts.append("\n".join(lines))
    return "\n\n".join(parts)


def markdown_report(con: duckdb.DuckDBPyConnection) -> str:
    """The full Markdown report for the last run."""
    (as_of,) = con.execute("SELECT as_of_week FROM run_info").fetchone()
    n_items, n_planned, n_past = con.execute(
        "SELECT (SELECT count(*) FROM items), (SELECT count(*) FROM planned), "
        "(SELECT count(*) FROM planned WHERE past_due)"
    ).fetchone()
    n_orders, revenue = con.execute(
        "SELECT count(*), coalesce(sum(revenue), 0) FROM sales_orders"
    ).fetchone()
    imp_n, imp_rev = con.execute(
        "SELECT count(*), coalesce(sum(revenue_at_risk), 0) FROM impacted_orders"
    ).fetchone()

    out = ["# pegtrace report", ""]
    out.append(
        f"Planned as of week {as_of}: {n_items} items, {n_planned} planned orders "
        f"({n_past} released past due), {n_orders} sales orders worth {money(revenue)}."
    )
    out.append(f"{imp_n} orders are made late, {money(imp_rev)} of revenue is at risk.")
    out.append("")

    rows = con.execute(
        "SELECT order_id, customer, model, due_week, qty_at_risk, weeks_late, revenue_at_risk, "
        "root_item, chain FROM impacted_orders ORDER BY weeks_late DESC, order_id"
    ).fetchall()
    out += ["## Impacted orders", ""]
    if rows:
        out.append(
            markdown_table(
                [
                    "Order",
                    "Customer",
                    "Model",
                    "Due",
                    "Qty at risk",
                    "Weeks late",
                    "Revenue at risk",
                    "Root cause",
                    "Chain",
                ],
                [(*r[:6], money(r[6]), r[7], f"`{r[8]}`") for r in rows],
            )
        )
    else:
        out.append("None.")
    out.append("")

    rows = con.execute(
        "SELECT root_item, count(*), sum(revenue_at_risk), max(weeks_late) FROM impacted_orders "
        "GROUP BY root_item ORDER BY sum(revenue_at_risk) DESC, root_item"
    ).fetchall()
    out += ["## Root causes", ""]
    if rows:
        out.append(
            markdown_table(
                ["Item", "Orders", "Revenue at risk", "Max weeks late"],
                [(r[0], r[1], money(r[2]), r[3]) for r in rows],
            )
        )
    else:
        out.append("None.")
    out.append("")

    rows = con.execute(
        "SELECT p.item_id, i.make_buy, p.receipt_week, p.release_week, p.qty, "
        "? - p.release_week AS weeks_overdue FROM planned AS p "
        "JOIN items AS i ON i.item_id = p.item_id WHERE p.past_due "
        "ORDER BY weeks_overdue DESC, p.item_id, p.receipt_week",
        [as_of],
    ).fetchall()
    out += ["## Past-due planned releases", ""]
    if rows:
        out.append(
            markdown_table(
                ["Item", "Make/buy", "Receipt week", "Release week", "Qty", "Weeks overdue"], rows
            )
        )
    else:
        out.append("None.")
    out.append("")

    rows = con.execute(
        "SELECT planned_id, item_id, receipt_week, release_week, qty, unpegged_qty, suggestion "
        "FROM unpegged_planned ORDER BY item_id, receipt_week"
    ).fetchall()
    out += ["## Cancel / reschedule candidates", ""]
    if rows:
        out.append(
            markdown_table(
                [
                    "Planned order",
                    "Item",
                    "Receipt week",
                    "Release week",
                    "Qty",
                    "Unpegged qty",
                    "Suggestion",
                ],
                rows,
            )
        )
    else:
        out.append("None.")
    out.append("")

    rows = con.execute(
        "SELECT n.item_id, n.llc, n.usages, n.gross_total, n.on_hand, n.open_receipts, "
        "n.per_path_net, n.llc_net, n.llc_net - n.per_path_net AS understated "
        "FROM netting_comparison AS n JOIN items AS i ON i.item_id = n.item_id "
        "WHERE i.make_buy = 'buy' AND n.llc_net > n.per_path_net "
        "ORDER BY understated DESC, n.item_id LIMIT 15"
    ).fetchall()
    out += ["## Shared components: LLC netting against per-path netting", ""]
    out.append(
        "The 15 purchased components with the largest gap. Per-path netting lets every "
        "usage consume the same stock, so it understates the requirement."
    )
    out.append("")
    if rows:
        out.append(
            markdown_table(
                [
                    "Item",
                    "LLC",
                    "Usages",
                    "Gross",
                    "On hand",
                    "Open receipts",
                    "Per-path net",
                    "LLC net",
                    "Understated by",
                ],
                rows,
            )
        )
    else:
        out.append("None.")
    out.append("")
    return "\n".join(out)
