"""
End-to-end test of the full call sequence in Development Planning Document,
Section 2.3 -- parsers through to a downloadable workbook -- using small,
CONSTRUCTED, date-aligned workbooks (not the client's real sample files,
which don't share a common period range with each other; see the Risk
Register). This is the test that proves the whole pipeline is actually wired
together correctly, headless, with no Dash/UI involved (Rule 3).
"""
from __future__ import annotations

import os
import tempfile

import openpyxl
import pandas as pd

from orchestration.models import RunParams
from orchestration.run_manager import execute_run


def _build_mps_input(path: str):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({
            "Link Code": [111111], "SKU": [111111], "Brand": ["TestBrand"],
            "Link Desc Description": ["Test Product"],
        }).to_excel(writer, sheet_name="SKU Master", index=False)

        pd.DataFrame({"Link Code": [111111], 1: [620.0]}).to_excel(
            writer, sheet_name="2.Demand Input", index=False)

        pd.DataFrame({"Key": [pd.Timestamp("2026-06-01")], "Period": [1]}).to_excel(
            writer, sheet_name="Period Calendar Matrix", index=False)

        pd.DataFrame({
            "Link Code": [111111], "Period": [1], "Plant": ["TestPlant"], "Line": ["Line1"],
            "GE%": [1.0], "SOC": [24.0],
        }).to_excel(writer, sheet_name="4.SOC Sheet & Flag", index=False)


def _build_mps_output(path: str):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({
            "Period": [1], "Brand": ["TestBrand"], "Link Code": [111111],
            "Link Desc Description": ["Test Product"], "O/S": [10], "DOS": [20],
            "TestPlant_Line1": [300.0],
        }).to_excel(writer, sheet_name="Link Code Line Loading 1", index=False)

        pd.DataFrame({
            "Link Code": [111111], "Brand": ["TestBrand"], "Link Desc Description": ["Test Product"],
            1: [20.0], "Min": [20.0], "Max": [20.0], "Avg": [20.0], "Avg_min_dos_target": [20.0],
        }).to_excel(writer, sheet_name="Linkcode_DIFC", index=False)


def test_full_pipeline_headless_produces_valid_workbook():
    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path = os.path.join(tmp, "mps_input.xlsx")
        mps_output_path = os.path.join(tmp, "mps_output.xlsx")
        _build_mps_input(mps_input_path)
        _build_mps_output(mps_output_path)

        params = RunParams(start_period=1, end_period=1)
        result = execute_run(mps_input_path, mps_output_path, None, params, output_dir=tmp)

        assert result.status.value == "degraded"  # Manual Input absent -> fallback path
        assert result.output_path and os.path.exists(result.output_path)
        assert any("Priority not supplied" in m for m in result.assumption_messages)
        assert any("Calendar not supplied" in m for m in result.assumption_messages)

        wb = openpyxl.load_workbook(result.output_path)
        weekly_plan = wb["Weekly Plan"]
        headers_row2 = [c.value for c in next(weekly_plan.iter_rows(min_row=2, max_row=2))]
        total_col = headers_row2.index("Total Produced") + 1
        total_value = weekly_plan.cell(row=3, column=total_col).value
        assert round(total_value, 1) == 300.0  # must equal FIN -- the whole point of reconciliation


def test_cr05_changeover_override_beats_next_periods_better_priority():
    # End-to-end proof of REQ-CR-05's wiring through run_manager.py, not just
    # allocation.py's own unit test of the tie-break rule. Two Link Codes
    # share one line:
    #   FAST (111111)    Period 1 priority 1 -- consumes the entire line's
    #                     capacity, still touches W4, ends with carryover.
    #   STARVED (222222) Period 1 priority 2 -- gets zero capacity, never
    #                     touches W4 -- does NOT qualify for the override.
    # In Period 2 the listing is reversed so STARVED has the BETTER priority
    # (1) and FAST the worse one (2) -- with no CR-05, STARVED (better
    # priority) would be served first and FAST would stay short. The
    # override should flip that: FAST (flagged from Period 1) goes first
    # despite its worse Period-2 priority.
    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path = os.path.join(tmp, "mps_input.xlsx")
        mps_output_path = os.path.join(tmp, "mps_output.xlsx")

        with pd.ExcelWriter(mps_input_path, engine="openpyxl") as writer:
            pd.DataFrame({
                "Link Code": [111111, 222222], "SKU": [111111, 222222], "Brand": ["B", "B"],
                "Link Desc Description": ["Fast Product", "Starved Product"],
            }).to_excel(writer, sheet_name="SKU Master", index=False)
            pd.DataFrame({"Link Code": [111111, 222222], 1: [900.0, 500.0], 2: [900.0, 500.0]}).to_excel(
                writer, sheet_name="2.Demand Input", index=False)
            pd.DataFrame({"Key": [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")],
                          "Period": [1, 2]}).to_excel(writer, sheet_name="Period Calendar Matrix", index=False)
            pd.DataFrame({
                "Link Code": [111111, 222222, 111111, 222222], "Period": [1, 1, 2, 2],
                "Plant": ["TestPlant"] * 4, "Line": ["Line1"] * 4, "GE%": [1.0] * 4, "SOC": [24.0] * 4,
            }).to_excel(writer, sheet_name="4.SOC Sheet & Flag", index=False)

        with pd.ExcelWriter(mps_output_path, engine="openpyxl") as writer:
            pd.DataFrame({
                # Row order sets file-order priority per (line, period) -- Period 1:
                # FAST first (priority 1); Period 2: STARVED first (priority 1).
                "Period": [1, 1, 2, 2], "Brand": ["B"] * 4,
                "Link Code": [111111, 222222, 222222, 111111],
                "Link Desc Description": ["Fast Product", "Starved Product", "Starved Product", "Fast Product"],
                "O/S": [10] * 4, "DOS": [20] * 4,
                "TestPlant_Line1": [900.0, 500.0, 1.0, 1.0],
            }).to_excel(writer, sheet_name="Link Code Line Loading 1", index=False)
            pd.DataFrame({
                "Link Code": [111111, 222222], "Brand": ["B", "B"],
                "Link Desc Description": ["Fast Product", "Starved Product"],
                1: [20.0, 20.0], 2: [20.0, 20.0],
                "Min": [20.0, 20.0], "Max": [20.0, 20.0], "Avg": [20.0, 20.0],
                "Avg_min_dos_target": [20.0, 20.0],
            }).to_excel(writer, sheet_name="Linkcode_DIFC", index=False)

        params = RunParams(start_period=1, end_period=2)
        result = execute_run(mps_input_path, mps_output_path, None, params, output_dir=tmp)
        assert result.status.value == "degraded"

        wp = pd.read_excel(result.output_path, sheet_name="Weekly Plan", header=[0, 1])
        wp = wp.set_index(("Linkcode", "Unnamed: 2_level_1"))

        # Period 1: confirms the trigger fired the way the fixture intends.
        assert wp.loc[111111.0, ("Jul-26", "W4")] == 168.0        # FAST touched the real last week
        assert wp.loc[111111.0, ("Jul-26", "Carryover M+1")] == 228.0
        assert wp.loc[222222.0, ("Jul-26", "W4")] == 0.0          # STARVED never got a turn
        assert wp.loc[222222.0, ("Jul-26", "Carryover M+1")] == 500.0

        # Period 2: FAST (worse priority=2 this period) gets its carryover
        # essentially fully served; STARVED (better priority=1) is squeezed --
        # the opposite of what plain priority alone would have produced.
        assert wp.loc[111111.0, ("Aug-26", "Priority")] == 2.0
        assert wp.loc[222222.0, ("Aug-26", "Priority")] == 1.0
        assert wp.loc[111111.0, ("Aug-26", "Total Produced")] == 228.0
        assert wp.loc[111111.0, ("Aug-26", "Carryover M+1")] <= 1.0   # rounding dust only
        assert wp.loc[222222.0, ("Aug-26", "Total Produced")] == 444.0
        assert wp.loc[222222.0, ("Aug-26", "Carryover M+1")] == 57.0  # left short despite better priority


def test_fails_cleanly_when_mps_output_missing():
    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path = os.path.join(tmp, "mps_input.xlsx")
        _build_mps_input(mps_input_path)
        params = RunParams(start_period=1, end_period=1)
        result = execute_run(mps_input_path, mps_input_path, None, params, output_dir=tmp)
        # passing mps_input twice means MPS Output's required sheets are missing
        assert result.status.value == "failed"
        assert result.output_path is None
        assert result.errors


# --- Logging, failure handling and health checks (PR: run logging) ----------

import logging

import pytest


@pytest.fixture
def run_log():
    """Collect everything the run logger emits, independent of how (or whether)
    the host process configured logging."""
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(f"{record.levelname} {record.getMessage()}")

    handler = _Capture()
    logger = logging.getLogger("wds.run")
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


def _inputs(tmp):
    mps_input_path = os.path.join(tmp, "mps_input.xlsx")
    mps_output_path = os.path.join(tmp, "mps_output.xlsx")
    _build_mps_input(mps_input_path)
    _build_mps_output(mps_output_path)
    return mps_input_path, mps_output_path


def test_a_successful_run_logs_its_stages_inputs_and_outcome(run_log):
    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path, mps_output_path = _inputs(tmp)
        result = execute_run(mps_input_path, mps_output_path, None,
                             RunParams(start_period=1, end_period=1), output_dir=tmp)

    joined = "\n".join(run_log)
    assert result.trace_id and result.status.value == "degraded"
    assert "RUN_START periods=1-1 lines=all" in joined
    assert "INPUT mps_input sha256=" in joined and "INPUT manual_input not-supplied" in joined
    for stage in ("parse", "validate", "consolidation", "dos_difc", "excel_write"):
        assert f"STAGE {stage} END" in joined
    assert "FALLBACK" in joined                       # manual input absent -> run-level fallbacks logged
    assert "HEALTH conservation ok" in joined
    assert "RUN_END status=degraded" in joined
    assert "RUN_FAILED" not in joined and "INTEGRITY_FAILED" not in joined


def test_a_crash_in_any_stage_is_a_clean_failed_result_naming_stage_and_period(monkeypatch, run_log):
    from orchestration import run_manager

    def boom(*args, **kwargs):
        raise KeyError("throughput_per_day")

    monkeypatch.setattr(run_manager.allocation, "run", boom)

    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path, mps_output_path = _inputs(tmp)
        result = execute_run(mps_input_path, mps_output_path, None,
                             RunParams(start_period=1, end_period=1), output_dir=tmp)  # must not raise

    assert result.status.value == "failed" and result.output_path is None
    assert "'allocation' failed (period 1)" in result.errors[0]
    assert "throughput_per_day" in result.errors[0]
    assert f"[ref {result.trace_id}]" in result.errors[0]

    joined = "\n".join(run_log)
    assert "STAGE allocation FAILED period=1 KeyError" in joined
    assert "RUN_FAILED stage=allocation period=1" in joined
    assert "RUN_END status=failed" in joined


def test_a_crash_outside_the_wrapped_stages_is_still_not_an_unrecorded_crash(monkeypatch, run_log):
    from orchestration import run_manager

    def boom(*args, **kwargs):
        raise RuntimeError("something odd")

    monkeypatch.setattr(run_manager, "_run_pipeline", boom)
    result = execute_run("a", "b", None, RunParams(start_period=1, end_period=1))
    assert result.status.value == "failed"
    assert "Unexpected error: something odd" in result.errors[0] and "[ref " in result.errors[0]
    assert any("RUN_FAILED stage=unexpected" in line for line in run_log)


def test_parse_failure_keeps_its_existing_message_text(run_log):
    with tempfile.TemporaryDirectory() as tmp:
        garbage = os.path.join(tmp, "not_a_workbook.xlsx")
        with open(garbage, "wb") as f:
            f.write(b"this is not an excel file")
        result = execute_run(garbage, garbage, None, RunParams(start_period=1, end_period=1), output_dir=tmp)
    assert result.status.value == "failed" and result.output_path is None
    assert result.errors and "[ref" not in result.errors[0]      # unchanged text: no reference suffix added
    assert any("RUN_FAILED stage=parse" in line for line in run_log)
    assert any("RUN_END status=failed" in line for line in run_log)


def test_validation_failure_keeps_its_existing_messages_and_is_logged(run_log):
    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path = os.path.join(tmp, "mps_input.xlsx")
        _build_mps_input(mps_input_path)
        # Same workbook as both inputs: it parses fine, but MPS Output's required sheets are absent.
        result = execute_run(mps_input_path, mps_input_path, None,
                             RunParams(start_period=1, end_period=1), output_dir=tmp)
    assert result.status.value == "failed"
    assert "MPS Output is missing required sheet(s)" in result.errors[0]
    assert "[ref" not in result.errors[0]
    assert any("RUN_FAILED stage=validate" in line for line in run_log)


def test_a_failed_health_check_warns_loudly_but_still_produces_the_output(monkeypatch, run_log):
    from engine.health_checks import HealthCheck, HealthReport
    from orchestration import run_manager

    failing = HealthReport(checks=[HealthCheck(
        "conservation", False, "rows=1 max_dev=50.000T tol=0.5T violations=1",
        ["P_L1/L1/P1: produced+carryover_out differs from FIN+carryover_in by -50.00 T"],
    )])
    monkeypatch.setattr(run_manager.health_checks, "check", lambda rows: failing)

    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path, mps_output_path = _inputs(tmp)
        result = execute_run(mps_input_path, mps_output_path, None,
                             RunParams(start_period=1, end_period=1), output_dir=tmp)
        assert result.status.value == "degraded"                       # not failed, not blocked
        assert result.output_path and os.path.exists(result.output_path)
        assert result.integrity_warnings and result.integrity_warnings[0].startswith("conservation:")

    joined = "\n".join(run_log)
    assert "ERROR INTEGRITY_FAILED check=conservation" in joined
    assert "INTEGRITY_FAILED_ROW P_L1/L1/P1" in joined


def test_a_broken_health_check_never_fails_the_run(monkeypatch, run_log):
    from orchestration import run_manager

    def boom(rows):
        raise RuntimeError("checker bug")

    monkeypatch.setattr(run_manager.health_checks, "check", boom)

    with tempfile.TemporaryDirectory() as tmp:
        mps_input_path, mps_output_path = _inputs(tmp)
        result = execute_run(mps_input_path, mps_output_path, None,
                             RunParams(start_period=1, end_period=1), output_dir=tmp)
        assert result.status.value == "degraded" and os.path.exists(result.output_path)
        assert result.integrity_warnings == []
    assert any("HEALTH check could not run" in line for line in run_log)
