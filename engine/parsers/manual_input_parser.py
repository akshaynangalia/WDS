"""
Parses the Manual Input workbook — RCCP and Calendar sheets.

This is the ONE optional input file (Development Planning Document, Section 5 —
Fallback Matrix). `parse(None)` is a valid, expected call: it returns a
ManualInputData with both fields set to None, which engine/fallback.py turns
into concrete defaults.

Both sheets have a two-row header block in the source workbook (a grouping
title row, then the real column-header row), so each is read with the
appropriate `header=` offset rather than the default header=0.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

RCCP_HEADER_ROW = 2       # 0-indexed: real column headers are Excel row 3
CALENDAR_HEADER_ROW = 1   # 0-indexed: real column headers are Excel row 2


@dataclass
class ManualInputData:
    rccp: pd.DataFrame | None
    calendar: pd.DataFrame | None
    sheets_found: set[str]


def parse(file) -> ManualInputData:
    """`file` may be None (Manual Input not supplied at all)."""
    if file is None:
        return ManualInputData(rccp=None, calendar=None, sheets_found=set())

    # Opened in a `with` block so the workbook handle is released before this
    # function returns -- see the note in mps_input_parser.parse for why.
    with pd.ExcelFile(file) as xl:
        sheets_found = set(xl.sheet_names)

        rccp = None
        if "RCCP" in sheets_found:
            rccp = xl.parse("RCCP", header=RCCP_HEADER_ROW)
            rccp = rccp.dropna(how="all")

        calendar = None
        if "Calendar" in sheets_found:
            calendar = xl.parse("Calendar", header=CALENDAR_HEADER_ROW)
            calendar = calendar.dropna(how="all")

        return ManualInputData(rccp=rccp, calendar=calendar, sheets_found=sheets_found)


def has_column(df: pd.DataFrame | None, column: str) -> bool:
    return df is not None and column in df.columns and df[column].notna().any()
