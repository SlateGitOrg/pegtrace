"""Command line: generate, run, impact, whatif, report."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import duckdb
import typer

from pegtrace import reports
from pegtrace.generator import generate_dataset, write_dataset
from pegtrace.runner import CycleError, InvariantError, run_plan
from pegtrace.schema import load_csv_dir
from pegtrace.whatif import run_whatif

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="MRP in DuckDB SQL: net shared components once, peg shortages to customer orders.",
)

DbOption = Annotated[Path, typer.Option("--db", help="DuckDB file written by `run`.")]
DEFAULT_DB = Path("pegtrace.duckdb")


def _fail(message: str) -> None:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(1)


def _open_planned(db: Path) -> duckdb.DuckDBPyConnection:
    if not db.is_file():
        _fail(f"{db} does not exist; run `pegtrace run` first")
    con = duckdb.connect(str(db), read_only=True)
    try:
        con.execute("SELECT 1 FROM run_info")
    except duckdb.Error:
        con.close()
        _fail(f"{db} holds no completed plan; run `pegtrace run` first")
    return con


@app.command()
def generate(
    seed: Annotated[int, typer.Option(help="Random seed.")] = 11,
    out: Annotated[Path, typer.Option(help="Output directory for the CSV files.")] = Path("data"),
    inject_cycle: Annotated[
        bool, typer.Option("--inject-cycle", help="Add the cycle SUB-A -> SUB-B -> SUB-A.")
    ] = False,
) -> None:
    """Write the synthetic plant (BOM, stock, open orders, sales orders) as CSV files."""
    dataset = generate_dataset(seed, inject_cycle=inject_cycle)
    paths = write_dataset(dataset, out)
    for table, rows in dataset.tables().items():
        typer.echo(f"{table:<20} {len(rows):>5} rows")
    typer.echo(f"wrote {len(paths)} files to {out}/")


@app.command()
def run(
    as_of_week: Annotated[int, typer.Option("--as-of-week", help="Planning week.")] = 1,
    data: Annotated[Path, typer.Option(help="Directory written by `generate`.")] = Path("data"),
    db: DbOption = DEFAULT_DB,
) -> None:
    """Plan the data: explode, low-level codes, net level by level, peg, walk impacts."""
    con = duckdb.connect(str(db))
    try:
        load_csv_dir(con, data)
        run_plan(con, as_of_week)
    except FileNotFoundError as exc:
        _fail(str(exc))
    except CycleError as exc:
        _fail("bill of materials has a cycle: " + "; ".join(exc.paths))
    except InvariantError as exc:
        _fail(str(exc))
    typer.echo(_run_summary(con, as_of_week))
    con.close()


def _run_summary(con: duckdb.DuckDBPyConnection, as_of_week: int) -> str:
    n_items, max_llc, n_planned, n_past, n_pegs, n_unpegged = con.execute(
        "SELECT (SELECT count(*) FROM items), (SELECT max(llc) FROM llc), "
        "(SELECT count(*) FROM planned), (SELECT count(*) FROM planned WHERE past_due), "
        "(SELECT count(*) FROM peg), (SELECT count(*) FROM unpegged_planned)"
    ).fetchone()
    n_imp, rev, total = con.execute(
        "SELECT (SELECT count(*) FROM impacted_orders), "
        "(SELECT coalesce(sum(revenue_at_risk), 0) FROM impacted_orders), "
        "(SELECT sum(revenue) FROM sales_orders)"
    ).fetchone()
    return "\n".join(
        [
            f"planned as of week {as_of_week}: {n_items} items, low-level codes 0..{max_llc}",
            f"planned orders        {n_planned:>6}  ({n_past} released past due)",
            f"peg rows              {n_pegs:>6}  ({n_unpegged} planned orders unpegged)",
            f"orders made late      {n_imp:>6}  {reports.money(rev)} of {reports.money(total)} "
            "revenue at risk",
            "invariant queries     all clear",
        ]
    )


@app.command()
def impact(
    item: Annotated[str, typer.Option(help="Item id to inspect.")],
    db: DbOption = DEFAULT_DB,
) -> None:
    """Customer orders an item makes late, and its netting against the per-path baseline."""
    con = _open_planned(db)
    try:
        typer.echo(reports.item_report(con, item))
    except KeyError as exc:
        _fail(exc.args[0])
    finally:
        con.close()


@app.command()
def whatif(
    po: Annotated[str, typer.Option(help="Scheduled receipt id, e.g. PO-0042.")],
    slip: Annotated[int, typer.Option(help="Weeks to push the receipt out (negative: pull in).")],
    db: DbOption = DEFAULT_DB,
) -> None:
    """Slip one open PO or work order, replan a copy, and diff impacted orders."""
    con = _open_planned(db)
    try:
        result = run_whatif(con, po, slip)
    except (KeyError, ValueError) as exc:
        _fail(str(exc.args[0]))
    finally:
        con.close()
    typer.echo(
        f"{result.receipt_id} ({result.item_id}) due week {result.old_due_week} -> "
        f"{result.new_due_week}\n"
    )
    if result.rows:
        typer.echo(reports.whatif_table(result.columns, result.rows))
    else:
        typer.echo("No order changes: the slip does not make any order later.")


@app.command()
def report(
    out: Annotated[Path, typer.Option(help="Markdown file to write.")] = Path("report.md"),
    db: DbOption = DEFAULT_DB,
) -> None:
    """Write the Markdown report: impacted orders, chains, past-due releases, candidates."""
    con = _open_planned(db)
    try:
        text = reports.markdown_report(con)
    finally:
        con.close()
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {out}")
