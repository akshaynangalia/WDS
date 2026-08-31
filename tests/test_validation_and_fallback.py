from __future__ import annotations

import os

import pandas as pd

from engine import fallback
from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser, validation

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sample_files")


def _real_mps_input():
    return mps_input_parser.parse(os.path.join(FIXTURES, "MPS_Input_File.xlsx"))


def _real_mps_output():
    return mps_output_parser.parse(os.path.join(FIXTURES, "MPS_Output_File.xlsx"))


def test_can_run_with_all_three_files():
    manual_input = manual_input_parser.parse(os.path.join(FIXTURES, "Manual_Input.xlsx"))
    result = validation.validate(_real_mps_input(), _real_mps_output(), manual_input)
    assert result.can_run
    assert result.rccp_present
    assert result.calendar_present
    decisions = fallback.resolve(result)
    # Weekly Demand is never present in any of the three sample workbooks (matches the
    # reference UI's own "Weekly Demand -- optional, not present" checklist item), so
    # the monthly-average DIFC approximation is expected to fire even on an otherwise
    # fully-supplied run. Priority/MOQ/Target DOS/Calendar should NOT be defaulted, though.
    assert decisions.use_monthly_avg_dos
    assert not decisions.use_default_priority
    assert not decisions.use_default_moq
    assert not decisions.use_default_target_dos
    assert not decisions.use_default_calendar


def test_hard_stop_when_mps_input_missing():
    empty_mps_input = mps_input_parser.MPSInputData(
        sku_master=pd.DataFrame(), demand=pd.DataFrame(),
        period_calendar=pd.DataFrame(), soc=pd.DataFrame(), sheets_found=set(),
    )
    manual_input = manual_input_parser.parse(None)
    result = validation.validate(empty_mps_input, _real_mps_output(), manual_input)
    assert not result.can_run
    assert result.errors  # specific error, not a silent failure


def test_degraded_mode_when_manual_input_absent():
    manual_input = manual_input_parser.parse(None)
    result = validation.validate(_real_mps_input(), _real_mps_output(), manual_input)
    assert result.can_run  # MPS Input/Output alone are enough to proceed
    assert not result.manual_input_present

    decisions = fallback.resolve(result)
    assert decisions.any_fallback_applied
    assert decisions.use_default_priority
    assert decisions.use_default_moq
    assert decisions.use_default_target_dos
    assert decisions.use_default_calendar
    assert len(decisions.messages) == 5  # priority, moq, target dos, calendar, weekly demand


def test_partial_manual_input_only_flags_missing_fields():
    # RCCP present but missing the Target DOS column specifically.
    rccp = pd.DataFrame({"Link Code Desc": ["X"], "Priority": [1], "MOQ": [5]})
    manual_input = manual_input_parser.ManualInputData(rccp=rccp, calendar=pd.DataFrame({"a": [1]}),
                                                        sheets_found={"RCCP", "Calendar"})
    result = validation.validate(_real_mps_input(), _real_mps_output(), manual_input)
    decisions = fallback.resolve(result)
    assert not decisions.use_default_priority
    assert not decisions.use_default_moq
    assert decisions.use_default_target_dos  # only this one should be flagged
    assert not decisions.use_default_calendar
