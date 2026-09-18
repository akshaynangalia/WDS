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
from output import comparison_table_sheet, difc_summary_sheet, excel_writer, weekly_plan_sheet


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
            "Weekly Plan", "Comparison Table",
            "Weekly DIFC Summary", "Assumption Applied",
        }

        weekly_plan = wb["Weekly Plan"]
        headers_row2 = [c.value for c in next(weekly_plan.iter_rows(min_row=2, max_row=2))]
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
                      wk3=0.0, wk4=0.0, wk5=0.0, carryover_next=0.0, current_fin=100.0,
                      priority=1.0, moq_days=None, opening_dos=0.0, target_dos=0.0):
    return SkuAllocation(
        plant_line="Baddi_E2", period=period, link_code=link_code, priority=priority,
        current_fin=current_fin, carryover_fin_in=wk1a, wk1a=wk1a, wk1=wk1, wk2=wk2,
        wk3=wk3, wk4=wk4, wk5=wk5, carryover_next=carryover_next,
        plant="Baddi", line="E2", brand="CDM Base", link_desc="CDM 10", month_key=month_key,
        moq_days=moq_days, opening_dos=opening_dos, target_dos=target_dos,
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

    df, _, _ = weekly_plan_sheet.build(result)
    row = df.iloc[0]
    assert row["Feb-26 | W1 (=W1A+W1)"] == alloc.wk1a + alloc.wk1 == 35.0
    assert row["Feb-26 | W2"] == 65.0
    assert row["Feb-26 | Total Produced"] == 100.0        # unchanged -- still reconciles to FIN


def test_transposed_w5_block_appears_only_for_five_week_months():
    rows = [
        _transposed_alloc(1, "Jun-26", "L1", wk1=50.0, wk5=10.0, current_fin=60.0),  # month 6 -> W5
        _transposed_alloc(2, "Jul-26", "L1", wk1=40.0, current_fin=40.0),            # month 7 -> no W5
    ]
    df, hdr1, _ = weekly_plan_sheet.build(result := _transposed_result(rows))

    assert "Jun-26 | W5" in df.columns
    assert "Jul-26 | W5" not in df.columns
    assert "Jun-26" in hdr1 and "Jul-26" in hdr1          # bands come from month_key
    assert len(df) == 1                                    # one row per (Plant, Line, Linkcode)


def test_transposed_leaves_blank_cells_where_a_linkcode_is_absent_in_a_period():
    rows = [
        _transposed_alloc(1, "Jan-26", "A", wk1=10.0, current_fin=10.0),
        _transposed_alloc(2, "Feb-26", "B", wk1=20.0, current_fin=20.0),
    ]
    df = weekly_plan_sheet.build(_transposed_result(rows))[0].set_index("Linkcode")

    assert df.loc["A", "Jan-26 | Total Produced"] == 10.0
    assert pd.isna(df.loc["A", "Feb-26 | Total Produced"])   # A never ran in Feb
    assert pd.isna(df.loc["B", "Jan-26 | Total Produced"])


def test_weekly_plan_moq_is_static_while_opening_dos_target_dos_priority_repeat_per_period():
    rows = [
        _transposed_alloc(1, "Jan-26", "L1", wk1=10.0, current_fin=10.0,
                          moq_days=3.0, priority=2.0, opening_dos=20.0, target_dos=25.0),
        _transposed_alloc(2, "Feb-26", "L1", wk1=20.0, current_fin=20.0,
                          moq_days=3.0, priority=1.0, opening_dos=22.0, target_dos=25.0),
    ]
    df, header_row1, _ = weekly_plan_sheet.build(_transposed_result(rows))
    row = df.iloc[0]

    # MOQ: exactly one column -- not repeated per period, unlike Opening DOS/Priority.
    assert header_row1.count("MOQ") == 1
    assert "Jan-26 | MOQ" not in df.columns and "Feb-26 | MOQ" not in df.columns
    assert row["MOQ"] == 3.0

    # Opening DOS and Priority genuinely change period to period -- each period
    # keeps its own value.
    assert row["Jan-26 | Opening DOS"] == 20.0 and row["Feb-26 | Opening DOS"] == 22.0
    assert row["Jan-26 | Priority"] == 2.0 and row["Feb-26 | Priority"] == 1.0
    # Target DOS repeats too (kept per-period even though it's usually constant --
    # see the module docstring for why a static column would be unsafe).
    assert row["Jan-26 | Target DOS"] == 25.0 and row["Feb-26 | Target DOS"] == 25.0

    # CASE lives on Comparison Table only -- not duplicated here.
    assert not any(col.endswith("CASE") or col == "CASE" for col in df.columns)


def test_weekly_plan_sheet_has_two_row_banded_header_and_the_w1_note():
    result = _transposed_result([_transposed_alloc(1, "Feb-26", "L1", wk1a=5.0, wk1=95.0, moq_days=3.0)])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        ws = openpyxl.load_workbook(path)["Weekly Plan"]

        row1 = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        row2 = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]

        assert row1[0] == "Plant"                          # id col (vertical-merge anchor, row 1)
        moq_idx = row1.index("MOQ")                        # static column -- once, not per period
        band_idx = row1.index("Feb-26")                    # the one period block
        assert band_idx > moq_idx                          # static block precedes the period blocks
        assert row2[band_idx] == "Opening DOS"              # context columns lead the block
        assert row2[band_idx + 3] == "W1 (=W1A+W1)"

        data_row = [c.value for c in next(ws.iter_rows(min_row=3, max_row=3))]
        assert data_row[0] == "Baddi"                       # data starts row 3
        assert data_row[moq_idx] == 3.0

        band_cell = ws.cell(row=1, column=band_idx + 1)
        assert band_cell.fill.fgColor.rgb == "FF4F2170"
        assert band_cell.font.bold is True

        note = next((c.value for col in ws.iter_cols() for c in col
                     if isinstance(c.value, str) and c.value.startswith("Note: W1 = W1A + W1")), None)
        assert note is not None


def test_comparison_table_case_and_gap_vs_fin_repeat_per_period():
    # CASE genuinely changes period to period as a Link Code's DOS gap
    # changes -- unlike Weekly Plan (which deliberately omits CASE since this
    # is its home sheet), it must repeat here, not sit static.
    rows = [
        SkuAllocation(plant_line="P_L1", period=1, link_code="L1", priority=1.0,
                      current_fin=100.0, carryover_fin_in=0.0, wk1=100.0, moq_case="D",
                      plant="P", line="L1", brand="B", link_desc="D", month_key="Jan-26"),
        SkuAllocation(plant_line="P_L1", period=2, link_code="L1", priority=1.0,
                      current_fin=50.0, carryover_fin_in=0.0, wk1=50.0, moq_case="B",
                      plant="P", line="L1", brand="B", link_desc="D", month_key="Feb-26"),
    ]
    result = EngineResult(reconciled=ReconciledResult(rows=rows), difc=DIFCResult(rows=[]),
                          fallback=FallbackDecisions(), capacity_messages=[])
    df, _, _ = comparison_table_sheet.build(result)
    row = df.iloc[0]

    assert row["Jan-26 | CASE"] == "D" and row["Feb-26 | CASE"] == "B"
    # gap_vs_fin also repeats -- even though it's 0 in both periods here, it
    # exists to flag the one period reconciliation doesn't hold, so it must
    # never be collapsed to a single static value.
    assert row["Jan-26 | gap_vs_fin"] == 0.0 and row["Feb-26 | gap_vs_fin"] == 0.0
    assert not any(label in ("CASE", "gap_vs_fin") for label, _ in comparison_table_sheet.STATIC_FIELDS)


def _difc_row(period, month_key, link_code, *, closing_by_week=None, approximated=False, opening_dos=0.0):
    return DIFCRow(
        plant_line="P_L1", period=period, link_code=link_code,
        closing_by_week=closing_by_week or {}, approximated=approximated,
        plant="P", line="L1", brand="B", link_desc="D", month_key=month_key, opening_dos=opening_dos,
    )


def test_difc_summary_approximated_is_static_and_wk5_only_where_data_exists():
    rows = [
        _difc_row(1, "Jun-26", "L1", closing_by_week={"wk1": 10.0, "wk5": 5.0}, approximated=True, opening_dos=20.0),
        _difc_row(1, "Jun-26", "L2", closing_by_week={"wk1": 8.0}, approximated=True, opening_dos=15.0),  # no wk5 this period
        _difc_row(2, "Jul-26", "L1", closing_by_week={"wk1": 12.0}, approximated=True, opening_dos=22.0),
    ]
    result = EngineResult(reconciled=ReconciledResult(rows=[]), difc=DIFCResult(rows=rows),
                          fallback=FallbackDecisions(), capacity_messages=[])
    df, header_row1, _ = difc_summary_sheet.build(result)

    # Approximated: one static column, not repeated per period.
    assert header_row1.count("Approximated (monthly avg)") == 1
    assert df.set_index("Linkcode").loc["L1", "Approximated (monthly avg)"] == "Yes"

    # WK5 exists for the Jun-26 block because L1 has a wk5 value that period --
    # even though L2, in the very same period, has none and shows blank there.
    # It's a data-driven decision, not "month MOD 3 == 0" alone.
    assert "Jun-26 | WK5" in df.columns
    assert "Jul-26 | WK5" not in df.columns  # no row has a wk5 value that period
    by_lc = df.set_index("Linkcode")
    assert by_lc.loc["L1", "Jun-26 | WK5"] == 5.0
    assert pd.isna(by_lc.loc["L2", "Jun-26 | WK5"])  # same period, no wk5 key for this row
