"""
Consolidation is tested against the REAL sample files structurally (does it
build a sane table, are the derived columns populated correctly) rather than
against exact numbers -- the sample files don't share a common date range
(Development Planning Document, Risk Register), so there's no numerically
"correct" answer to check against here. The exact-number checks against the
ground-truth worked example live in test_allocation.py instead, using
synthetic, controlled input built directly from the doc's own figures.
"""
from __future__ import annotations

import os

import pandas as pd

from engine import consolidation, fallback
from engine.fallback import FallbackDecisions
from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser, validation
from engine.parsers.manual_input_parser import ManualInputData
from engine.parsers.mps_input_parser import MPSInputData
from engine.parsers.mps_output_parser import MPSOutputData

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sample_files")


def _load_all():
    mps_input = mps_input_parser.parse(os.path.join(FIXTURES, "MPS_Input_File.xlsx"))
    mps_output = mps_output_parser.parse(os.path.join(FIXTURES, "MPS_Output_File.xlsx"))
    manual_input = manual_input_parser.parse(os.path.join(FIXTURES, "Manual_Input.xlsx"))
    return mps_input, mps_output, manual_input


def test_consolidation_builds_nonempty_table_with_expected_columns():
    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)

    table = consolidation.build(mps_input, mps_output, manual_input, decisions)
    df = table.data
    assert not df.empty
    assert list(df.columns) == consolidation.CONSOLIDATED_COLUMNS
    assert (df["current_fin"] > 0).all()  # zero-FIN rows should have been filtered out
    assert df["plant"].notna().all()
    assert df["line"].notna().all()


def test_dos_gap_is_never_negative():
    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)
    table = consolidation.build(mps_input, mps_output, manual_input, decisions)
    assert (table.data["dos_gap"] >= 0).all()


def test_daily_demand_is_monthly_demand_over_calendar_days():
    # #14: the DOS gap (days of cover) is converted to a tonnage in allocation
    # using daily demand, so consolidation must expose it as
    # monthly demand / actual days in that period's month.
    import calendar as _cal

    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)
    df = consolidation.build(mps_input, mps_output, manual_input, decisions).data

    assert "daily_demand" in df.columns
    assert (df["daily_demand"] >= 0).all()

    row = df[df["daily_demand"] > 0].iloc[0]
    dem = mps_input.demand
    drow = dem[dem["Link Code"] == row["link_code"]].iloc[0]
    monthly = float(drow[row["period"]])
    days = _cal.monthrange(2000 + int(str(row["month_key"]).split("-")[1]), int(row["month_num"]))[1]
    assert round(row["daily_demand"], 4) == round(monthly / days, 4)


def test_target_dos_comes_from_avg_min_dos_target():
    # Target DOS comes solely from Linkcode_DIFC.Avg_min_dos_target, joined by
    # numeric Link Code -- so it works even for a SKU with no RCCP text match.
    mps_input = MPSInputData(
        sku_master=pd.DataFrame(),
        demand=pd.DataFrame(),
        period_calendar=pd.DataFrame({"Key": [pd.Timestamp("2026-02-01")], "Period": [1]}),
        soc=pd.DataFrame({"Link Code": [111, 222], "Period": [1, 1], "Plant": ["P", "P"],
                          "Line": ["L", "L"], "GE%": [1.0, 1.0], "SOC": [24.0, 24.0]}),
        sheets_found=set(),
    )
    mps_output = MPSOutputData(
        monthly_fin=pd.DataFrame({
            "Period": [1, 1], "SKU": [111, 222], "Link Code": [111, 222],
            "Link Desc Description": ["Prod A", "Prod B"], "P_L": [100.0, 50.0],
        }),
        linkcode_difc=pd.DataFrame({
            "Link Code": [111, 222], 1: [25.0, 20.0], "Avg_min_dos_target": [42.0, 35.0],
        }),
        sheets_found=set(),
    )
    manual_input = ManualInputData(
        rccp=pd.DataFrame({"Link Code Desc": ["Prod A"], "Priority": [1.0], "MOQ": [5.0]}),
        calendar=None, sheets_found={"RCCP"},
    )

    df = consolidation.build(mps_input, mps_output, manual_input, FallbackDecisions()).data
    by_link = df.set_index("link_code")

    assert by_link.loc[111, "target_dos"] == 42.0   # from Avg_min_dos_target
    assert by_link.loc[111, "dos_gap"] == 17.0      # 42 - 25
    assert by_link.loc[222, "target_dos"] == 35.0   # applied even with no RCCP match
    assert by_link.loc[222, "dos_gap"] == 15.0      # 35 - 20
    assert any("Avg_min_dos_target" in a for a in by_link.loc[111, "row_assumptions"])


def test_target_dos_falls_back_to_opening_when_avg_min_dos_target_missing():
    # No Avg_min_dos_target value -> target = opening -> DOS gap 0, and it's flagged.
    mps_input = MPSInputData(
        sku_master=pd.DataFrame(), demand=pd.DataFrame(),
        period_calendar=pd.DataFrame({"Key": [pd.Timestamp("2026-02-01")], "Period": [1]}),
        soc=pd.DataFrame({"Link Code": [111], "Period": [1], "Plant": ["P"], "Line": ["L"],
                          "GE%": [1.0], "SOC": [24.0]}),
        sheets_found=set(),
    )
    mps_output = MPSOutputData(
        monthly_fin=pd.DataFrame({"Period": [1], "SKU": [111], "Link Code": [111],
                                  "Link Desc Description": ["Prod A"], "P_L": [100.0]}),
        linkcode_difc=pd.DataFrame({"Link Code": [111], 1: [25.0], "Avg_min_dos_target": [float("nan")]}),
        sheets_found=set(),
    )
    manual_input = ManualInputData(rccp=None, calendar=None, sheets_found=set())

    df = consolidation.build(mps_input, mps_output, manual_input, FallbackDecisions()).data
    assert df.iloc[0]["target_dos"] == 25.0   # == opening_dos
    assert df.iloc[0]["dos_gap"] == 0.0
    assert any("no Linkcode_DIFC.Avg_min_dos_target" in a for a in df.iloc[0]["row_assumptions"])


def test_no_rccp_match_falls_back_gracefully_without_crashing():
    # Manual Input present overall, but its Link Code Desc values are text
    # descriptions that won't match every SKU in the sample MPS Output file
    # (documented join-key ambiguity -- see consolidation.py's module docstring).
    # This should degrade gracefully per-row, not crash.
    mps_input, mps_output, manual_input = _load_all()
    result = validation.validate(mps_input, mps_output, manual_input)
    decisions = fallback.resolve(result)
    table = consolidation.build(mps_input, mps_output, manual_input, decisions)
    # every row must have SOME priority/target_dos value (defaulted or matched), never NaN
    assert table.data["priority"].notna().all()
    assert table.data["target_dos"].notna().all()
