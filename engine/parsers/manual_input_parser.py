"""
Parses the Manual Input workbook — Priority(Linkcode Level) and Calendar sheets.

This is the ONE optional input file (Development Planning Document, Section 5 —
Fallback Matrix). `parse(None)` is a valid, expected call: it returns a
ManualInputData with both fields set to None, which engine/fallback.py turns
into concrete defaults.

Priority(Linkcode Level) replaces the old "RCCP" sheet (REQ-CR-01 rebuild):
its header is a single row (no title/grouping row above it), unlike Calendar,
which still has a two-row header block.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

CALENDAR_HEADER_ROW = 1   # 0-indexed: real column headers are Excel row 2


@dataclass
class ManualInputData:
    priority: pd.DataFrame | None
    calendar: pd.DataFrame | None
    sheets_found: set[str]


def parse(file) -> ManualInputData:
    """`file` may be None (Manual Input not supplied at all)."""
    if file is None:
        return ManualInputData(priority=None, calendar=None, sheets_found=set())

    # Opened in a `with` block so the workbook handle is released before this
    # function returns -- see the note in mps_input_parser.parse for why.
    with pd.ExcelFile(file) as xl:
        sheets_found = set(xl.sheet_names)

        priority = None
        if "Priority(Linkcode Level)" in sheets_found:
            priority = xl.parse("Priority(Linkcode Level)")
            priority = priority.dropna(how="all")

        calendar = None
        if "Calendar" in sheets_found:
            calendar = xl.parse("Calendar", header=CALENDAR_HEADER_ROW)
            calendar = calendar.dropna(how="all")

        return ManualInputData(priority=priority, calendar=calendar, sheets_found=sheets_found)


def has_column(df: pd.DataFrame | None, column: str) -> bool:
    return df is not None and column in df.columns and df[column].notna().any()


def has_period_columns(df: pd.DataFrame | None) -> bool:
    """True if `df` has at least one bare-integer period column (the "1".."14"
    convention shared with Linkcode_DIFC / 2.Demand Input) with real data —
    Priority(Linkcode Level)'s per-period replacement for the old static
    "Priority" column."""
    if df is None:
        return False
    period_cols = [c for c in df.columns if isinstance(c, int)]
    return bool(period_cols) and df[period_cols].notna().any().any()
