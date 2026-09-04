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
per-file — whenever the Calendar sheet has no matching downtime column or row
for a given Plant-Line-Month. This is a finer-grained application of the same
principle as the file-level Fallback Matrix (Development Planning Document,
Section 5): missing data degrades gracefully rather than crashing the run.

Downtime column matching (Risk Register #12): the monthly plan's own
"Plant_Line" column header (e.g. "Induri_Induri ML") is the client's current,
preferred Calendar naming convention -- match it exactly first. Older files
used "Plant - Line" instead. Beyond those two, _resolve_downtime_col() falls
back to a separator-agnostic normalised match, and finally to a bare line
name with no plant prefix at all (accepted only when it uniquely identifies
one column) -- so the match survives naming drift without guessing wrong.

A blank downtime cell (once the column IS found) means "nothing recorded for
this line-week" -- i.e. 0 downtime, a normal full week -- and is read that
way via _numeric_or_zero(), never as the unbounded capacity a naive
`value or 0` would silently produce for a NaN cell.

Contract:
    consumes: calendar_df (or None), plant, line, month_key, month_num
    produces: CapacityBuckets, list[str] of assumption messages
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

FULL_WEEK_HOURS = 24 * 7

# Calendar sheet's own non-line columns -- never a downtime column, so they're
# excluded before any line-name matching is attempted.
_CALENDAR_META_COLUMNS = {
    "Key1", "Key2", "MonthNum", "Month", "Year", "Month Week", "Year Week",
    "Week Start Date", "Week End Date",
    "Allocated Days - Current Month", "Allocated Days - Previous Month",
}


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


def _numeric_or_zero(value, default: float = 0.0) -> float:
    """A blank Calendar cell means "no downtime recorded for this line-week"
    -- i.e. 0, a normal full week -- never "infinite". Python's `value or 0`
    idiom gets this wrong for a blank cell: pandas reads it as NaN, and NaN is
    truthy, so `nan or 0` evaluates to `nan`, not `0`. That NaN then behaves as
    unlimited capacity everywhere it's used downstream. `pd.isna` catches
    None/NaN alike and is the only correct way to spot a blank cell here."""
    return default if pd.isna(value) else float(value)


def _norm(s) -> str:
    """Lowercase, alphanumeric-only -- makes matching survive any separator
    (space, dash, underscore, none) and case difference between sheets."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _resolve_downtime_col(
    calendar_df: pd.DataFrame | None, plant: str, line: str
) -> tuple[str | None, str | None]:
    """Finds the Calendar sheet's downtime column for a Plant-Line.

    Tries, in order:
      1. "Plant_Line" -- an exact copy of the monthly plan's own column
         header. The client's current, preferred convention.
      2. "Plant - Line" -- the older space-dash-space convention.
      3. A separator-agnostic normalised match: the unique Calendar column
         whose normalised name contains both the plant and the line.
      4. A bare line name with no plant prefix at all -- accepted only when
         it is the unique such column on the sheet.

    Returns (column_name, info_message_or_None) on a match -- (None, None)
    when there's no Calendar to search at all -- or (None, loud_message) when
    nothing matches.
    """
    if calendar_df is None or calendar_df.empty:
        return None, (
            f"No Calendar data supplied — using default full-week capacity "
            f"for Plant-Line '{plant}/{line}'."
        )

    cols = list(calendar_df.columns)

    plant_line = f"{plant}_{line}"
    if plant_line in cols:
        return plant_line, None

    legacy = f"{plant} - {line}"
    if legacy in cols:
        return legacy, None

    candidates = [c for c in cols if c not in _CALENDAR_META_COLUMNS]
    nz_plant, nz_line = _norm(plant), _norm(line)

    both = [c for c in candidates if nz_plant in _norm(c) and nz_line in _norm(c)]
    if len(both) == 1:
        return both[0], (
            f"Matched Calendar column '{both[0]}' to Plant-Line '{plant}/{line}' "
            f"by name normalisation."
        )

    line_only = [c for c in candidates if _norm(c) == nz_line]
    if len(line_only) == 1:
        return line_only[0], (
            f"Matched Calendar column '{line_only[0]}' to Plant-Line '{plant}/{line}' "
            f"by line name alone (no plant prefix found in the Calendar column)."
        )

    searched = ", ".join(candidates) if candidates else "(no line columns found)"
    return None, (
        f"No Calendar downtime column found for Plant-Line '{plant}/{line}' "
        f"(tried '{plant_line}', '{legacy}', and a normalised name match; "
        f"Calendar has: {searched}). Using full-week, zero-downtime capacity "
        f"for this Plant-Line-Month — treat its plan with caution."
    )


def build(
    calendar_df: pd.DataFrame | None,
    plant: str,
    line: str,
    month_key: str,
    month_num: int | None,
) -> tuple[CapacityBuckets, list[str]]:
    messages: list[str] = []
    downtime_col, resolve_msg = _resolve_downtime_col(calendar_df, plant, line)
    if resolve_msg:
        messages.append(resolve_msg)
    is_five_week_month = month_num is not None and month_num % 3 == 0

    w1_row = _find_week_row(calendar_df, month_key, "W1")
    if w1_row is None or downtime_col is None:
        if w1_row is None and downtime_col is not None:
            # Column matched fine -- this specific month/week just isn't in
            # the Calendar sheet's Key2 rows. A distinct failure mode from
            # "no matching column at all", so it gets its own message.
            messages.append(
                f"No Calendar data found for {plant}/{line} in {month_key} — "
                f"using default full-week capacity for this Plant-Line-Month."
            )
        wk1a = 0.0
        wk1 = FULL_WEEK_HOURS
    else:
        allocated_prev = _numeric_or_zero(w1_row.get("Allocated Days - Previous Month"), default=0.0)
        allocated_curr = _numeric_or_zero(w1_row.get("Allocated Days - Current Month"), default=7.0)
        downtime_total_wk1 = _numeric_or_zero(w1_row.get(downtime_col))
        downtime_wk1a = (allocated_prev / 7) * downtime_total_wk1
        downtime_wk1 = (allocated_curr / 7) * downtime_total_wk1
        wk1a = round(24 * allocated_prev - downtime_wk1a, 1)
        wk1 = round(24 * allocated_curr - downtime_wk1, 1)

    def _week_capacity(week_label: str) -> float:
        row = _find_week_row(calendar_df, month_key, week_label)
        if row is None or downtime_col is None:
            if row is None and downtime_col is not None:
                messages.append(
                    f"No Calendar data found for {plant}/{line}, {month_key} {week_label} — "
                    f"using default full-week capacity."
                )
            return FULL_WEEK_HOURS
        downtime = _numeric_or_zero(row.get(downtime_col))
        return round(FULL_WEEK_HOURS - downtime, 1)

    wk2 = _week_capacity("W2")
    wk3 = _week_capacity("W3")
    wk4 = _week_capacity("W4")
    wk5 = _week_capacity("W5") if is_five_week_month else None

    return CapacityBuckets(wk1a=wk1a, wk1=wk1, wk2=wk2, wk3=wk3, wk4=wk4, wk5=wk5), messages
