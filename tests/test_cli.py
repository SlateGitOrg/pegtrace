"""Command line behaviour through typer's test runner."""

from __future__ import annotations

import csv

import pytest
from typer.testing import CliRunner

from pegtrace.cli import app

runner = CliRunner()


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    path = tmp_path_factory.mktemp("cli")
    data, db = path / "data", path / "plan.duckdb"
    assert runner.invoke(app, ["generate", "--seed", "11", "--out", str(data)]).exit_code == 0
    result = runner.invoke(app, ["run", "--data", str(data), "--db", str(db)])
    assert result.exit_code == 0, result.output
    return path, data, db


def test_generate_writes_every_csv_and_reports_counts(tmp_path):
    result = runner.invoke(app, ["generate", "--out", str(tmp_path / "d")])
    assert result.exit_code == 0
    assert "sales_orders" in result.output and "280 rows" in result.output
    assert (tmp_path / "d" / "expected_whatif_impacts.csv").is_file()


def test_run_prints_a_summary(workdir):
    _, data, db = workdir
    result = runner.invoke(app, ["run", "--data", str(data), "--db", str(db)])
    assert result.exit_code == 0
    assert "low-level codes 0..3" in result.output
    assert "invariant queries     all clear" in result.output


def test_inject_cycle_makes_run_exit_non_zero_with_the_cycle_path(tmp_path):
    data = tmp_path / "data"
    runner.invoke(app, ["generate", "--inject-cycle", "--out", str(data)])
    result = runner.invoke(app, ["run", "--data", str(data), "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    assert "SUB-A -> SUB-B -> SUB-A" in result.output


def test_run_without_data_fails_cleanly(tmp_path):
    result = runner.invoke(app, ["run", "--data", str(tmp_path), "--db", str(tmp_path / "x.db")])
    assert result.exit_code == 1 and "pegtrace generate" in result.output


def test_whatif_table_lists_the_expected_orders_and_the_total(workdir):
    path, data, db = workdir
    result = runner.invoke(app, ["whatif", "--po", "PO-0042", "--slip", "4", "--db", str(db)])
    assert result.exit_code == 0
    with (data / "expected_whatif_impacts.csv").open() as handle:
        expected = list(csv.DictReader(handle))
    for row in expected:
        assert row["order_id"] in result.output
    assert "12 orders, 54 units, $1,258,640 revenue at risk" in result.output
    assert "PO-0042 (CMP-5T) due week 6 -> 10" in result.output


def test_whatif_with_no_slip_says_nothing_changes(workdir):
    _, _, db = workdir
    result = runner.invoke(app, ["whatif", "--po", "PO-0042", "--slip", "0", "--db", str(db)])
    assert result.exit_code == 0 and "No order changes" in result.output


def test_whatif_slip_to_a_week_before_week_one_fails_cleanly(workdir):
    _, _, db = workdir
    result = runner.invoke(app, ["whatif", "--po", "PO-0042", "--slip", "-6", "--db", str(db)])
    assert result.exit_code == 1
    assert "week 0" in result.output and "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_whatif_unknown_po_fails(workdir):
    _, _, db = workdir
    result = runner.invoke(app, ["whatif", "--po", "PO-9999", "--slip", "1", "--db", str(db)])
    assert result.exit_code == 1 and "PO-9999" in result.output


def test_impact_shows_the_two_netting_results_for_cb_200(workdir):
    _, _, db = workdir
    result = runner.invoke(app, ["impact", "--item", "CB-200", "--db", str(db)])
    assert result.exit_code == 0
    assert "planned quantity, LLC      220" in result.output
    assert "planned quantity, per path 0" in result.output


def test_impact_lists_orders_late_through_an_item(workdir):
    _, _, db = workdir
    result = runner.invoke(app, ["impact", "--item", "CAP-5", "--db", str(db)])
    assert result.exit_code == 0
    assert "Orders put late through CAP-5" in result.output
    assert " <- CAP-5" in result.output


def test_impact_unknown_item_fails(workdir):
    _, _, db = workdir
    assert runner.invoke(app, ["impact", "--item", "NOPE", "--db", str(db)]).exit_code == 1


def test_report_writes_the_markdown_sections(workdir):
    path, _, db = workdir
    out = path / "report.md"
    result = runner.invoke(app, ["report", "--out", str(out), "--db", str(db)])
    assert result.exit_code == 0
    text = out.read_text()
    for heading in (
        "## Impacted orders",
        "## Root causes",
        "## Past-due planned releases",
        "## Cancel / reschedule candidates",
        "## Shared components",
    ):
        assert heading in text
    assert "49 orders are made late" in text


def test_commands_need_a_completed_run(tmp_path):
    result = runner.invoke(app, ["report", "--db", str(tmp_path / "missing.duckdb")])
    assert result.exit_code == 1 and "pegtrace run" in result.output
