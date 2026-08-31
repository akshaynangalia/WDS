"""
Builds weekly capacity buckets (in hours) for a given Plant-Line-Period,
mirroring the legacy tool's capacity math:

    tot_cap_wk1a = 24 * allocated_days_prev - proportional downtime
    tot_cap_wk1  = 24 * allocated_days_curr - proportional downtime
    tot_cap_wk[2..4] = 24*7 - downtime for that week
    tot_cap_wk5 exists only when month_num MOD 3 == 0 (five-week-month rule)

GE% is intentionally NOT applied here — per client confirmation (Architecture
Doc, Section 8, item 3) it's applied as a separate multiplier at allocation
time, not baked into capacity.

Falls back to a full 7-day, zero-downtime week — per SKU-week, not just
per-file — whenever the Calendar sheet has no matching row for a given
Plant-Line-Month. This is a finer-grained application of the same principle
as the file-level Fallback Matrix (Development Planning Document, Section 5):
missing data degrades gracefully rather than crashing the run.

Contract:
    consumes: calendar_df (or None), plant, line, month_key, month_num
    produces: CapacityBuckets, list[str] of assumption messages
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

FULL_WEEK_HOURS = 24 * 7


@dataclass
class CapacityBuckets:
    wk1a: float
    wk1: float
    wk2: float
    wk3: float
    wk4: float
    wk5: float | None  # None unless this is a five-week month


def _find_week_row(calendar_df: pd.DataFrame, month_key: str, week_label: str):
    if calendar_df is None or calendar_df.empty or "Key2" not in calendar_df.columns:
        return None
    match = calendar_df[calendar_df["Key2"] == f"{month_key}|{week_label}"]
    return match.iloc[0] if not match.empty else None


def build(
    calendar_df: pd.DataFrame | None,
    plant: str,
    line: str,
    month_key: str,
    month_num: int | None,
) -> tuple[CapacityBuckets, list[str]]:
    messages: list[str] = []
    downtime_col = f"{plant} - {line}"
    is_five_week_month = month_num is not None and month_num % 3 == 0

    w1_row = _find_week_row(calendar_df, month_key, "W1")
    if w1_row is None or downtime_col not in (calendar_df.columns if calendar_df is not None else []):
        messages.append(
            f"No Calendar data found for {plant}/{line} in {month_key} — "
            f"using default full-week capacity for this Plant-Line-Month."
        )
        wk1a = 0.0
        wk1 = FULL_WEEK_HOURS
    else:
        allocated_prev = float(w1_row.get("Allocated Days - Previous Month", 0) or 0)
        allocated_curr = float(w1_row.get("Allocated Days - Current Month", 7) or 7)
        downtime_total_wk1 = float(w1_row.get(downtime_col, 0) or 0)
        downtime_wk1a = (allocated_prev / 7) * downtime_total_wk1
        downtime_wk1 = (allocated_curr / 7) * downtime_total_wk1
        wk1a = round(24 * allocated_prev - downtime_wk1a, 1)
        wk1 = round(24 * allocated_curr - downtime_wk1, 1)

    def _week_capacity(week_label: str) -> float:
        row = _find_week_row(calendar_df, month_key, week_label)
        if row is None or downtime_col not in (calendar_df.columns if calendar_df is not None else []):
            messages.append(
                f"No Calendar data found for {plant}/{line}, {month_key} {week_label} — "
                f"using default full-week capacity."
            )
            return FULL_WEEK_HOURS
        downtime = float(row.get(downtime_col, 0) or 0)
        return round(FULL_WEEK_HOURS - downtime, 1)

    wk2 = _week_capacity("W2")
    wk3 = _week_capacity("W3")
    wk4 = _week_capacity("W4")
    wk5 = _week_capacity("W5") if is_five_week_month else None

    return CapacityBuckets(wk1a=wk1a, wk1=wk1, wk2=wk2, wk3=wk3, wk4=wk4, wk5=wk5), messages
