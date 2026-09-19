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


# --- Run Report sheet ---------------------------------------------------------

import dataclasses

from engine.health_checks import HealthCheck, HealthReport
from engine.run_report import RunReport, StageTiming
from output import run_report_sheet


def _report(**overrides):
    base = dict(
        reference="20260919-125409-29d5", generated_utc="2026-09-19 12:54:09", version="0.1.0+abc1234",
        status="degraded", periods="1-10", lines="all", min_dos_entered=None,
        inputs=[("MPS Input", "sha256=7de74d4805b5 size=940149"), ("Manual Input", "not-supplied")],
        stages=[StageTiming("parse", 1, 0.74), StageTiming("allocation", 10, 0.62)],
        elapsed_seconds=2.1,
        fallback_messages=["Weekly Demand not supplied - DIFC approximated."],
        capacity_messages=[],
        health=HealthReport(checks=[HealthCheck("conservation", True, "rows=942 max_dev=0.218T tol=0.5T violations=0")]),
    )
    base.update(overrides)
    return RunReport(**base)


def _write_with_report(report):
    result = dataclasses.replace(_sample_engine_result(fallback_applied=False), run_report=report)
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "out.xlsx")
    excel_writer.write(result, path)
    return tmp, openpyxl.load_workbook(path)


def _find(ws, label, after_section=None):
    """(row, value) of the first row whose column A equals label."""
    for row in range(1, ws.max_row + 1):
        if ws.cell(row=row, column=1).value == label:
            return row, ws.cell(row=row, column=2).value
    raise AssertionError(f"no row labelled {label!r}")


def test_no_run_report_sheet_unless_the_run_supplies_one():
    result = _sample_engine_result(fallback_applied=False)  # run_report defaults to None
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.xlsx")
        excel_writer.write(result, path)
        assert openpyxl.load_workbook(path).sheetnames == [
            "Weekly Plan", "Comparison Table", "Weekly DIFC Summary", "Assumption Applied",
        ]


def test_run_report_is_appended_last_so_approved_sheets_do_not_move():
    tmp, wb = _write_with_report(_report())
    with tmp:
        assert wb.sheetnames == [
            "Weekly Plan", "Comparison Table", "Weekly DIFC Summary", "Assumption Applied",
            "Run Report", "Calculation Trace",
        ]


def test_run_report_shows_the_run_summary_inputs_stages_and_fallbacks():
    tmp, wb = _write_with_report(_report(min_dos_entered=None))
    with tmp:
        ws = wb["Run Report"]
        assert _find(ws, "Reference")[1] == "20260919-125409-29d5"
        assert _find(ws, "Generated (UTC)")[1] == "2026-09-19 12:54:09"
        assert _find(ws, "Tool version")[1] == "0.1.0+abc1234"
        assert "Degraded" in _find(ws, "Status")[1]
        assert _find(ws, "Periods")[1] == "1-10"
        assert _find(ws, "MPS Input")[1] == "sha256=7de74d4805b5 size=940149"
        assert _find(ws, "Manual Input")[1] == "not-supplied"
        assert _find(ws, "allocation")[1] == "10 runs, 0.62 s total"
        assert _find(ws, "parse")[1] == "1 run, 0.74 s total"
        assert _find(ws, "Run-level fallbacks applied")[1] == 1
        assert any(ws.cell(row=r, column=2).value == "Weekly Demand not supplied - DIFC approximated."
                   for r in range(1, ws.max_row + 1))
        assert "Minimum DOS override entered" not in [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        assert not any("INTEGRITY WARNING" in str(ws.cell(row=r, column=1).value) for r in range(1, ws.max_row + 1))


def test_a_minimum_dos_the_planner_typed_is_reported_as_not_applied():
    # The UI collects it but the engine does not use it yet -- the report must
    # not let a planner believe it took effect.
    tmp, wb = _write_with_report(_report(min_dos_entered=5.0))
    with tmp:
        _, value = _find(wb["Run Report"], "Minimum DOS override entered")
        assert "5 days" in value and "does not apply it" in value


def test_a_failed_health_check_gives_a_loud_red_banner_and_fail_rows():
    failing = HealthReport(checks=[
        HealthCheck("conservation", False, "rows=942 max_dev=50.000T tol=0.5T violations=3", ["a", "b", "c"]),
        HealthCheck("nan", True, "rows=942 violations=0"),
    ])
    tmp, wb = _write_with_report(_report(health=failing))
    with tmp:
        ws = wb["Run Report"]
        banner = ws["A3"]
        assert "INTEGRITY WARNING" in banner.value and "conservation (3 row(s))" in banner.value
        assert "20260919-125409-29d5" in banner.value               # log reference, to find the rows
        assert banner.fill.fgColor.rgb == "FFC0392B" and banner.font.bold
        row, value = _find(ws, "conservation")
        assert value.startswith("FAIL") and ws.cell(row=row, column=2).fill.fgColor.rgb == "FFF8D7DA"
        row, value = _find(ws, "nan")
        assert value.startswith("PASS") and ws.cell(row=row, column=2).fill.fgColor.rgb == "FFDFF0D8"


def test_health_checks_that_could_not_run_are_shown_not_hidden():
    tmp, wb = _write_with_report(_report(health=None))
    with tmp:
        _, value = _find(wb["Run Report"], "All checks")
        assert value.startswith("NOT RUN")


def test_long_capacity_fallback_lists_are_capped_with_a_pointer_to_the_full_list():
    messages = [f"No Calendar data found for P/L{i}, Jun-26 W2 -- using default full-week capacity." for i in range(30)]
    tmp, wb = _write_with_report(_report(capacity_messages=messages))
    with tmp:
        ws = wb["Run Report"]
        assert _find(ws, "Capacity fallbacks applied")[1] == 30
        shown = [ws.cell(row=r, column=2).value for r in range(1, ws.max_row + 1)]
        assert sum(1 for v in shown if isinstance(v, str) and v.startswith("No Calendar data found")) == 10
        assert any(isinstance(v, str) and "and 20 more" in v and "Assumption Applied" in v for v in shown)


def test_a_broken_run_report_never_costs_the_plan(monkeypatch):
    def boom(workbook, report):
        workbook.create_sheet(run_report_sheet.SHEET_NAME)  # half-built sheet, then failure
        raise RuntimeError("renderer bug")

    monkeypatch.setattr(run_report_sheet, "write", boom)
    tmp, wb = _write_with_report(_report())
    with tmp:
        assert wb.sheetnames == ["Weekly Plan", "Comparison Table", "Weekly DIFC Summary", "Assumption Applied",
                                 "Calculation Trace"]  # the other diagnostic sheet is unaffected


# --- Calculation Trace sheet ---------------------------------------------------

import random
import re

from output import calculation_trace_sheet
from output.calculation_trace_sheet import difference_t, explain


def _traced(**kw):
    base = dict(
        plant_line="P_L1", period=1, link_code="L1", priority=1.0, current_fin=100.0, carryover_fin_in=0.0,
        plant="P", line="L1", month_key="Jun-26", throughput_per_day=24.0, ge_pct=1.0, daily_demand=24.0,
        moq_case="A", moq_qty=240.0, run1_target=100.0, run1_placed=100.0, wk1=100.0,
    )
    base.update(kw)
    return SkuAllocation(**base)


def test_explain_case_a_whole_fin_in_run_1():
    a = _traced(current_fin=90.6, moq_qty=110.3, run1_target=90.6, run1_placed=90.6, wk1=90.6)
    assert explain(a) == "Case A: FIN 90.6 T < 1.5 x MOQ batch 110.3 T -> whole FIN in Run 1. Carry-out 0.0 T."


def test_explain_case_b_split_shows_half_in_run_1_and_the_rest_in_run_2():
    a = _traced(moq_case="B", current_fin=454.0, moq_qty=54.0, run1_target=227.0, run1_placed=227.0,
                run2_placed=227.0, wk1=454.0)
    assert explain(a) == ("Case B: no DOS gap, FIN 454.0 T >= 1.5 x MOQ batch 54.0 T -> half (227.0 T) in Run 1. "
                          "Run 2 placed 227.0 T. Carry-out 0.0 T.")


def test_explain_case_c_and_d_show_the_dos_gap_arithmetic():
    c = _traced(moq_case="C", current_fin=500.0, dos_gap_days=2.0, daily_demand=24.0, dos_gap_qty=48.0,
                moq_qty=120.0, run1_target=120.0, run1_placed=120.0, run2_placed=380.0)
    assert explain(c).startswith("Case C: DOS gap 2.0 d x 24.0 T/d = 48.0 T < MOQ batch 120.0 T "
                                 "-> one MOQ batch (120.0 T) in Run 1.")
    d = _traced(moq_case="D", current_fin=500.0, dos_gap_days=10.0, daily_demand=24.0, dos_gap_qty=240.0,
                moq_qty=120.0, run1_target=240.0, run1_placed=240.0, run2_placed=260.0)
    assert explain(d).startswith("Case D: DOS gap 10.0 d x 24.0 T/d = 240.0 T >= MOQ batch 120.0 T -> 240.0 T in Run 1.")


def test_explain_no_moq_skips_run_1():
    a = _traced(moq_case="No MOQ", run1_target=0.0, run1_placed=0.0, run2_placed=100.0)
    assert explain(a) == "No MOQ: all FIN goes through Run 2. Run 2 placed 100.0 T. Carry-out 0.0 T."


def test_explain_carry_in_spread_unplaced_and_served_first():
    a = _traced(carryover_fin_in=335.1, wk1a=51.8, carry_spread=283.2, changeover_first=True, wk1=283.2,
                run1_target=0.0, run1_placed=0.0, moq_case="No MOQ")
    assert explain(a).startswith("Carry-in 335.1 T: 51.8 T in W1A, 283.2 T spread over W1-W4, "
                                 "0.1 T could not be placed (no capacity); served first (month-end changeover rule).")


def test_explain_says_when_run_1_could_not_place_its_target_and_why_run_2_deferred():
    a = _traced(moq_case="B", current_fin=883.0, moq_qty=116.5, run1_target=441.5, run1_placed=248.7,
                run2_deferred=351.1, run2_moq_blocked=False, wk1=248.7, carryover_next=634.4)
    text = explain(a)
    assert "half (441.5 T) in Run 1, only 248.7 T fitted." in text
    assert "351.1 T could not be placed in Run 2 (no capacity left)." in text
    assert text.endswith("Carry-out 634.4 T.")

    blocked = _traced(run2_deferred=44.3, run2_moq_blocked=True, carryover_next=44.3)
    assert "44.3 T could not be placed in Run 2 (below the MOQ run-length floor)." in explain(blocked)


def test_explain_mentions_a_reconciliation_adjustment_only_when_it_is_material():
    assert "Reconciliation adjusted +0.4 T." in explain(_traced(recon_adjustment=0.4))
    assert "Reconciliation" not in explain(_traced(recon_adjustment=0.0))
    assert "Reconciliation" not in explain(_traced(recon_adjustment=0.04))


def test_displayed_dos_gap_arithmetic_always_checks_out_on_a_calculator():
    # A planner multiplying the two displayed factors must get the displayed product
    # to within the display precision (0.05 T) whenever the sentence says "=". Where
    # that would need more than 3 decimals it says "~" instead -- never a false "=".
    # (With a fixed one-decimal display, 57 of 102 real Case C/D rows failed this.)
    rng = random.Random(7)
    pattern = re.compile(r"DOS gap ([\d.]+) d x ([\d.]+) T/d ([=~]) ([\d.]+) T")
    approx = 0
    for _ in range(3000):
        days, demand = rng.uniform(0.05, 60), rng.uniform(0.05, 40)
        a = _traced(moq_case="D", dos_gap_days=days, daily_demand=demand, dos_gap_qty=days * demand,
                    run1_target=days * demand, run1_placed=days * demand)
        factor1, factor2, connector, product = pattern.search(explain(a)).groups()
        assert max(len(factor1.split(".")[1]), len(factor2.split(".")[1])) <= 3
        error = abs(float(factor1) * float(factor2) - float(product))
        if connector == "=":
            assert error <= 0.0501, (days, demand, explain(a))
        else:
            approx += 1
            assert error <= 0.15, (days, demand, explain(a))     # still close, and honest about it
    assert approx < 3000 * 0.25                                    # "~" is the exception, not the rule


def test_explain_says_approximately_when_an_exact_product_would_need_many_decimals():
    # The real Baddi/E2 687104 Oct-26 row: exact factors would be 4.98833 x 85.73015.
    a = _traced(moq_case="D", dos_gap_days=4.98833, daily_demand=85.73015, dos_gap_qty=427.7,
                moq_qty=52.0, run1_target=427.7, run1_placed=427.7)
    assert "DOS gap 4.988 d x 85.730 T/d ~ 427.7 T" in explain(a)


def test_difference_is_the_real_conservation_residual():
    # Real-data example: 21.78 FIN + 21.8 carry-in = 43.58 pool, but 43.8 produced.
    a = _traced(current_fin=21.78196661689216, carryover_fin_in=21.8, wk1a=16.0, wk1=23.3, wk2=1.5, wk3=1.5, wk4=1.5)
    assert difference_t(a) == 0.22
    assert difference_t(_traced(current_fin=100.0, wk1=100.0)) == 0.0


def _trace_ws(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    calculation_trace_sheet.write(wb, rows)
    return wb[calculation_trace_sheet.SHEET_NAME]


def test_trace_sheet_is_long_format_sorted_filterable_with_a_footnote():
    rows = [
        _traced(plant="P2", plant_line="P2_L1", link_code="LC9", period=2, month_key="Jul-26", wk1=50.0, current_fin=50.0),
        _traced(plant="P1", plant_line="P1_L1", link_code="LC5", period=2, month_key="Jul-26", wk1=20.0, current_fin=20.0),
        _traced(plant="P1", plant_line="P1_L1", link_code="LC5", period=1, month_key="Jun-26", wk1=30.0, current_fin=30.0),
    ]
    ws = _trace_ws(rows)

    assert [c.value for c in ws[1]] == [
        "Plant", "Line", "Linkcode", "Month", "Case", "Total FIN (T)", "Carry-in (T)", "Throughput (T/day)", "GE %",
        "Daily demand (T/day)", "Produced (T)", "Carry-out (T)", "Difference (T)", "How it was calculated",
    ]
    assert ws["A1"].fill.fgColor.rgb == "FF4F2170" and ws["A1"].font.bold          # same header style as the other tabs
    assert [(ws.cell(row=r, column=1).value, ws.cell(row=r, column=3).value, ws.cell(row=r, column=4).value)
            for r in (2, 3, 4)] == [("P1", "LC5", "Jun-26"), ("P1", "LC5", "Jul-26"), ("P2", "LC9", "Jul-26")]
    assert ws.freeze_panes == "E2" and ws.auto_filter.ref == "A1:N4"               # header + 4 id columns frozen; data only
    assert ws["I2"].number_format == "0.0%"
    assert "Difference = (produced + carry-out) - (FIN + carry-in)" in ws["A6"].value   # footnote sits outside the filter
    assert ws["M2"].value == 0.0 and ws["K2"].value == 30.0


def test_trace_sheet_gives_long_sentences_taller_rows():
    long_text = _traced(carryover_fin_in=335.1, wk1a=51.8, carry_spread=283.2, changeover_first=True,
                        moq_case="B", current_fin=883.0, moq_qty=116.5, run1_target=441.5, run1_placed=248.7,
                        run2_deferred=351.1, carryover_next=634.4)
    ws = _trace_ws([long_text, _traced(link_code="L2")])
    heights = sorted(ws.row_dimensions[r].height for r in (2, 3))
    assert heights[0] == 15 and heights[1] >= 30


def test_trace_sheet_is_written_for_real_runs_after_the_run_report():
    tmp, wb = _write_with_report(_report())
    with tmp:
        assert wb.sheetnames[-2:] == ["Run Report", "Calculation Trace"]
        ws = wb["Calculation Trace"]
        assert ws.max_row >= 2 and ws["C2"].value == "L1"


def test_a_broken_trace_sheet_never_costs_the_plan_or_the_run_report(monkeypatch):
    def boom(workbook, rows):
        workbook.create_sheet(calculation_trace_sheet.SHEET_NAME)   # half-built, then failure
        raise RuntimeError("renderer bug")

    monkeypatch.setattr(calculation_trace_sheet, "write", boom)
    tmp, wb = _write_with_report(_report())
    with tmp:
        assert wb.sheetnames == ["Weekly Plan", "Comparison Table", "Weekly DIFC Summary", "Assumption Applied",
                                 "Run Report"]
