from __future__ import annotations

import os
import tempfile

import openpyxl
import pandas as pd

from engine.allocation import SkuAllocation
from engine.dos_difc import DIFCResult, DIFCRow
from engine.engine_result import EngineResult
from engine.fallback import FallbackDecisions
from engine.reconciliation import ReconciledResult
from output import comparison_table_sheet, excel_writer, weekly_plan_transposed_sheet


def _sample_engine_result(fallback_applied: bool) -> EngineResult:
    alloc = SkuAllocation(
        plant_line="PlantA_Line1", period=1, link_code="L1", priority=1.0,
        current_fin=100.0, carryover_fin_in=0.0, wk1=100.0,
        plant="PlantA", line="Line1", brand="BrandA", link_desc="Product A",
        month_key="Feb-26", opening_dos=20.0, target_dos=30.0, moq_days=5.0,
    )
    reconciled = ReconciledResult(rows=[alloc])
    difc = DIFCResult(rows=[DIFCRow(plant_line="PlantA_Line1", period=1, link_code="L1",
                                     closing_by_week={"wk1": 25.0}, approximated=False,
                                     plant="PlantA", line="Line1", brand="BrandA",
                                     link_desc="Product A", month_key="Feb-26", opening_dos=20.0)])
    fb = FallbackDecisions(
        use_default_calendar=fallback_applied,
        messages=["Calendar not supplied — capacity is a coarse approximation."] if fallback_applied else [],
    )
    return EngineResult(reconciled=reconciled, difc=difc, fallback=fb, capacity_messages=[])


def test_workbook_has_all_four_tabs_with_expected_headers():
    result = _sample_engine_result(fallback_applied=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        wb = openpyxl.load_workbook(path)
        assert set(wb.sheetnames) == {
            "Weekly Plan Transposed", "Comparison Table",
            "Weekly DIFC Summary", "Assumption Applied",
        }

        transposed = wb["Weekly Plan Transposed"]
        headers_row2 = [c.value for c in next(transposed.iter_rows(min_row=2, max_row=2))]
        assert "Total Produced" in headers_row2 and "Carryover M+1" in headers_row2
        assert "SKU" not in headers_row2  # this version is Link-Code only -- no SKU concept anywhere


def test_header_row_is_styled_purple_with_white_bold_text():
    result = _sample_engine_result(fallback_applied=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        wb = openpyxl.load_workbook(path)
        for sheet_name in ("Comparison Table", "Weekly DIFC Summary", "Assumption Applied"):
            cell = wb[sheet_name]["A1"]
            assert cell.fill.fgColor.rgb == "FF4F2170"
            assert cell.font.bold is True
            assert cell.font.color.rgb == "FFFFFFFF"


def test_assumptions_tab_empty_when_no_fallback_applied():
    result = _sample_engine_result(fallback_applied=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        wb = openpyxl.load_workbook(path)
        sheet = wb["Assumption Applied"]
        assert sheet.max_row == 1  # header only, no data rows


def test_assumptions_tab_populated_when_fallback_applied():
    result = _sample_engine_result(fallback_applied=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        wb = openpyxl.load_workbook(path)
        sheet = wb["Assumption Applied"]
        assert sheet.max_row > 1
        assert "Calendar not supplied" in sheet.cell(row=2, column=1).value


def _transposed_alloc(period, month_key, link_code, *, wk1a=0.0, wk1=0.0, wk2=0.0,
                      wk3=0.0, wk4=0.0, wk5=0.0, carryover_next=0.0, current_fin=100.0):
    return SkuAllocation(
        plant_line="Baddi_E2", period=period, link_code=link_code, priority=1.0,
        current_fin=current_fin, carryover_fin_in=wk1a, wk1a=wk1a, wk1=wk1, wk2=wk2,
        wk3=wk3, wk4=wk4, wk5=wk5, carryover_next=carryover_next,
        plant="Baddi", line="E2", brand="CDM Base", link_desc="CDM 10", month_key=month_key,
    )


def _transposed_result(rows):
    # difc_summary_sheet needs at least one DIFCRow to build its frame; the
    # transposed-sheet tests don't exercise DIFC so one placeholder row is enough.
    difc = DIFCResult(rows=[DIFCRow(
        plant_line="Baddi_E2", period=rows[0].period, link_code=rows[0].link_code,
        closing_by_week={"wk1": 0.0}, approximated=False, plant="Baddi", line="E2",
        brand="CDM Base", link_desc="CDM 10", month_key=rows[0].month_key, opening_dos=0.0,
    )])
    return EngineResult(reconciled=ReconciledResult(rows=rows), difc=difc,
                        fallback=FallbackDecisions(), capacity_messages=[])


def test_transposed_w1_column_folds_w1a_into_w1():
    alloc = _transposed_alloc(1, "Feb-26", "L1", wk1a=15.0, wk1=20.0, wk2=65.0)  # total_all == 100
    result = _transposed_result([alloc])

    df, _, _ = weekly_plan_transposed_sheet.build(result)
    row = df.iloc[0]
    assert row["Feb-26 | W1 (=W1A+W1)"] == alloc.wk1a + alloc.wk1 == 35.0
    assert row["Feb-26 | W2"] == 65.0
    assert row["Feb-26 | Total Produced"] == 100.0        # unchanged -- still reconciles to FIN


def test_transposed_w5_block_appears_only_for_five_week_months():
    rows = [
        _transposed_alloc(1, "Jun-26", "L1", wk1=50.0, wk5=10.0, current_fin=60.0),  # month 6 -> W5
        _transposed_alloc(2, "Jul-26", "L1", wk1=40.0, current_fin=40.0),            # month 7 -> no W5
    ]
    df, hdr1, _ = weekly_plan_transposed_sheet.build(result := _transposed_result(rows))

    assert "Jun-26 | W5" in df.columns
    assert "Jul-26 | W5" not in df.columns
    assert "Jun-26" in hdr1 and "Jul-26" in hdr1          # bands come from month_key
    assert len(df) == 1                                    # one row per (Plant, Line, Linkcode)


def test_transposed_leaves_blank_cells_where_a_linkcode_is_absent_in_a_period():
    rows = [
        _transposed_alloc(1, "Jan-26", "A", wk1=10.0, current_fin=10.0),
        _transposed_alloc(2, "Feb-26", "B", wk1=20.0, current_fin=20.0),
    ]
    df = weekly_plan_transposed_sheet.build(_transposed_result(rows))[0].set_index("Linkcode")

    assert df.loc["A", "Jan-26 | Total Produced"] == 10.0
    assert pd.isna(df.loc["A", "Feb-26 | Total Produced"])   # A never ran in Feb
    assert pd.isna(df.loc["B", "Jan-26 | Total Produced"])


def test_transposed_sheet_has_two_row_banded_header_and_the_w1_note():
    result = _transposed_result([_transposed_alloc(1, "Feb-26", "L1", wk1a=5.0, wk1=95.0)])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        ws = openpyxl.load_workbook(path)["Weekly Plan Transposed"]

        assert ws.cell(row=1, column=1).value == "Plant"                  # id col, row 1
        assert ws.cell(row=1, column=6).value == "Feb-26"                 # month band, row 1
        assert ws.cell(row=2, column=6).value == "W1 (=W1A+W1)"           # week label, row 2
        assert ws.cell(row=3, column=1).value == "Baddi"                  # data starts row 3
        assert ws.cell(row=1, column=6).fill.fgColor.rgb == "FF4F2170"
        assert ws.cell(row=1, column=6).font.bold is True

        note = next((c.value for col in ws.iter_cols() for c in col
                     if isinstance(c.value, str) and c.value.startswith("Note: W1 = W1A + W1")), None)
        assert note is not None


def test_comparison_table_has_moq_case_column():
    # The spec lists "MOQ compliance flags" for COMPARISON_TABLE; it surfaces as
    # the per-Link-Code Run 1 case (A/B/C/D or "No MOQ").
    a = SkuAllocation(plant_line="P_L1", period=1, link_code="L1", priority=1.0,
                      current_fin=100.0, carryover_fin_in=0.0, wk1=100.0, moq_case="D")
    b = SkuAllocation(plant_line="P_L1", period=1, link_code="L2", priority=2.0,
                      current_fin=50.0, carryover_fin_in=0.0, wk1=50.0, moq_case="No MOQ")
    result = EngineResult(reconciled=ReconciledResult(rows=[a, b]), difc=DIFCResult(rows=[]),
                          fallback=FallbackDecisions(), capacity_messages=[])
    df = comparison_table_sheet.build_dataframe(result)
    assert "CASE" in df.columns
    assert df.set_index("Linkcode")["CASE"].to_dict() == {"L1": "D", "L2": "No MOQ"}
