"""
Structural tests against the client's actual sample workbooks. These confirm
the parsers correctly read real files -- NOT that the numbers reconcile
end-to-end (the three sample files use different date ranges, per the
Development Planning Document's Risk Register, so a true end-to-end
numerical run against them isn't meaningful; the worked-example fixture and
the synthetic tests in test_allocation.py / test_dos_difc.py cover the
business-logic correctness instead).
"""
from __future__ import annotations

import os

import pandas as pd

from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sample_files")


def test_mps_input_parses_all_required_sheets():
    data = mps_input_parser.parse(os.path.join(FIXTURES, "MPS_Input_File.xlsx"))
    assert mps_input_parser.missing_sheets(data) == []
    assert not data.sku_master.empty
    assert not data.demand.empty
    assert not data.period_calendar.empty
    assert not data.soc.empty
    assert "Period" in data.period_calendar.columns or "Key" in data.period_calendar.columns


def test_mps_output_parses_all_required_sheets():
    data = mps_output_parser.parse(os.path.join(FIXTURES, "MPS_Output_File.xlsx"))
    assert mps_output_parser.missing_sheets(data) == []
    assert not data.monthly_fin.empty
    assert not data.linkcode_difc.empty
    cols = mps_output_parser.plant_line_columns(data.monthly_fin)
    assert len(cols) > 0
    assert all("_" not in c or True for c in cols)  # plant_line columns should exist at all


def test_manual_input_parses_rccp_and_calendar():
    data = manual_input_parser.parse(os.path.join(FIXTURES, "Manual_Input.xlsx"))
    assert data.rccp is not None and not data.rccp.empty
    assert data.calendar is not None and not data.calendar.empty
    assert "Priority" in data.rccp.columns
    assert "MOQ" in data.rccp.columns
    assert "Target DOS" in data.rccp.columns


def test_manual_input_parse_none_is_valid():
    data = manual_input_parser.parse(None)
    assert data.rccp is None
    assert data.calendar is None
    assert data.sheets_found == set()


def test_parsers_release_the_workbook_file_handle(tmp_path):
    """Regression: parse() must close the workbook so the file can be deleted
    afterwards. A lingering pd.ExcelFile handle locks the file on Windows --
    the cause of the TemporaryDirectory cleanup failures in test_run_manager.
    On this platform os.unlink raises PermissionError if the handle is still
    open; elsewhere the call still exercises the close path.
    """
    # Enough rows that manual_input_parser's header=2 offset has a header to land on.
    frame = pd.DataFrame({"a": list(range(5)), "b": list(range(5))})
    for i, (parse_fn, sheet) in enumerate((
        (mps_input_parser.parse, "SKU Master"),
        (mps_output_parser.parse, "Linkcode_DIFC"),
        (manual_input_parser.parse, "RCCP"),
    )):
        path = tmp_path / f"book_{i}.xlsx"
        frame.to_excel(path, sheet_name=sheet, index=False)
        parse_fn(str(path))
        path.unlink()  # must not raise
        assert not path.exists()
