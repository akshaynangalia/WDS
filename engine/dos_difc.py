"""
Weekly Closing DIFC/DOS (REQ-CR-06):

    Closing DIFC(W) = MAX( (Opening_DIFC * Daily_Demand - Weekly_Demand + Production_W)
                           / Daily_Demand, 0 )
    Daily Demand = Monthly Demand / days in month

Weekly Demand should come from a dedicated weekly-demand input (optional --
see the reference UI's "Weekly Demand (for weekly DIFC) -- optional, not
present" checklist item). None of the three sample workbooks on hand actually
carry it, so in practice this always runs in the fallback path today:
Weekly Demand is approximated as Daily_Demand * 7 (Development Planning
Document, Section 5, last row).

Contract:
    consumes: reconciled rows (SkuAllocation), demand_df, opening DOS per
              (link_code, period) from the consolidated table, FallbackDecisions
    produces: DIFCResult
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

import pandas as pd

from engine.allocation import SkuAllocation
from engine.fallback import FallbackDecisions

WEEKS = ("wk1", "wk2", "wk3", "wk4", "wk5")


def _days_in_month(month_num, month_key) -> int:
    """Actual calendar days in the period's month, leap years included.

    Normal case: month_num and month_key both come from the same Period
    Calendar Matrix date, so the year is known -- "Feb-28" -> 2028 -> 29.
    Fallbacks (each unchanged from the old hard-coded table):
      - month_num missing (period absent from the Period Calendar Matrix):
        no month and no year, so a coarse 30-day guess.
      - month_num known but month_key missing/odd (not reachable with real
        data): assume a non-leap year, so February = 28.
    month_key is "Feb-26" style (strftime %b-%y); only its year part is read.
    """
    if not month_num:
        return 30
    year = 2001  # non-leap fallback
    if month_key:
        try:
            year = 2000 + int(str(month_key).split("-")[-1])
        except (ValueError, IndexError):
            pass
    return calendar.monthrange(year, int(month_num))[1]


@dataclass
class DIFCRow:
    plant_line: str
    period: int
    link_code: object
    sku: object
    closing_by_week: dict[str, float] = field(default_factory=dict)
    approximated: bool = False
    # Output-only identifying/context fields, mirroring SkuAllocation's --
    # see engine/allocation.py for why these are carried rather than re-joined.
    plant: str = ""
    line: str = ""
    brand: object = None
    link_desc: object = None
    month_key: str = ""
    opening_dos: float = 0.0


@dataclass
class DIFCResult:
    rows: list[DIFCRow]


def compute(
    reconciled_rows: list[SkuAllocation],
    consolidated_df: pd.DataFrame,
    demand_df: pd.DataFrame,
    fallback: FallbackDecisions,
) -> DIFCResult:
    opening_lookup = {
        (row["link_code"], row["period"]): (row["opening_dos"], row["month_num"], row.get("month_key"))
        for _, row in consolidated_df.iterrows()
    }
    demand_by_link = {}
    if not demand_df.empty and "Link Code" in demand_df.columns:
        for _, row in demand_df.iterrows():
            demand_by_link[row["Link Code"]] = row

    difc_rows: list[DIFCRow] = []
    for alloc in reconciled_rows:
        opening, month_num, month_key = opening_lookup.get((alloc.link_code, alloc.period), (0.0, None, None))
        days_in_month = _days_in_month(month_num, month_key)

        demand_row = demand_by_link.get(alloc.link_code)
        monthly_demand = float(demand_row[alloc.period]) if (
            demand_row is not None and alloc.period in demand_row and not pd.isna(demand_row[alloc.period])
        ) else 0.0
        daily_demand = monthly_demand / days_in_month if days_in_month else 0.0
        weekly_demand = daily_demand * 7  # fallback approximation (see module docstring)

        closing_by_week = {}
        running_opening = opening
        weeks_to_compute = WEEKS if alloc.wk5 or getattr(alloc, "wk5", 0) else WEEKS[:4]
        for wk in weeks_to_compute:
            production_w = getattr(alloc, wk, 0.0)
            if daily_demand:
                closing = max(
                    (running_opening * daily_demand - weekly_demand + production_w) / daily_demand,
                    0.0,
                )
            else:
                closing = 0.0
            closing_by_week[wk] = round(closing, 1)
            running_opening = closing

        difc_rows.append(DIFCRow(
            plant_line=alloc.plant_line, period=alloc.period, link_code=alloc.link_code,
            sku=alloc.sku, closing_by_week=closing_by_week,
            plant=alloc.plant, line=alloc.line, brand=alloc.brand, link_desc=alloc.link_desc,
            month_key=alloc.month_key, opening_dos=opening,
            approximated=fallback.use_monthly_avg_dos,
        ))

    return DIFCResult(rows=difc_rows)
