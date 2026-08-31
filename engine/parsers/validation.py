"""
Structural validation: classifies presence/absence of every expected input,
at both the file level and the field level within Manual Input.

This is what the Fallback Matrix (Development Planning Document, Section 5)
is keyed off of. It does NOT decide what default to apply — that's
engine/fallback.py's job. This module only answers "what do we have?".

Contract:
    consumes: MPSInputData, MPSOutputData, ManualInputData
    produces: ValidationResult
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.parsers import manual_input_parser, mps_input_parser, mps_output_parser
from engine.parsers.manual_input_parser import ManualInputData
from engine.parsers.mps_input_parser import MPSInputData
from engine.parsers.mps_output_parser import MPSOutputData


@dataclass
class ValidationResult:
    mps_input_ok: bool
    mps_input_missing_sheets: list[str]
    mps_output_ok: bool
    mps_output_missing_sheets: list[str]

    manual_input_present: bool
    rccp_present: bool
    calendar_present: bool
    priority_present: bool
    moq_present: bool
    target_dos_present: bool
    weekly_demand_present: bool

    errors: list[str] = field(default_factory=list)

    @property
    def can_run(self) -> bool:
        """MPS Input and MPS Output are mandatory (Section 5). Manual Input is not."""
        return self.mps_input_ok and self.mps_output_ok


def validate(
    mps_input: MPSInputData,
    mps_output: MPSOutputData,
    manual_input: ManualInputData,
    weekly_demand_present: bool = False,
) -> ValidationResult:
    mps_input_missing = mps_input_parser.missing_sheets(mps_input)
    mps_output_missing = mps_output_parser.missing_sheets(mps_output)

    errors = []
    if mps_input_missing:
        errors.append(f"MPS Input is missing required sheet(s): {', '.join(mps_input_missing)}")
    if mps_output_missing:
        errors.append(f"MPS Output is missing required sheet(s): {', '.join(mps_output_missing)}")

    rccp_present = manual_input.rccp is not None and not manual_input.rccp.empty
    calendar_present = manual_input.calendar is not None and not manual_input.calendar.empty

    return ValidationResult(
        mps_input_ok=not mps_input_missing,
        mps_input_missing_sheets=mps_input_missing,
        mps_output_ok=not mps_output_missing,
        mps_output_missing_sheets=mps_output_missing,
        manual_input_present=rccp_present or calendar_present,
        rccp_present=rccp_present,
        calendar_present=calendar_present,
        priority_present=manual_input_parser.has_column(manual_input.rccp, "Priority"),
        moq_present=manual_input_parser.has_column(manual_input.rccp, "MOQ"),
        target_dos_present=manual_input_parser.has_column(manual_input.rccp, "Target DOS"),
        weekly_demand_present=weekly_demand_present,
        errors=errors,
    )
