"""
Reconstructs the legacy tool's "Consolidated Input" equivalent: one row per
Plant-Line-LinkCode-Period, with Current FIN, Opening DOS, Target DOS, DOS Gap,
Priority, MOQ, Throughput and GE% all joined together.

This version of the tool is Link-Code level only (LinkCode-Change branch):
the Monthly Production Plan is read from MPS Output's `Link Code Line
Loading 1` sheet, which has no SKU column at all -- there is no SKU concept
anywhere in this codebase, not an alias for Link Code.

Priority and MOQ come from the Manual Input workbook's `Priority(Linkcode
Level)` sheet (REQ-CR-01 rebuild -- replaces the old text-matched "RCCP"
sheet; see LIMITATIONS.md L1, resolved), joined by **(Link Code, Plant,
Line)** -- not Link Code alone, since the same Link Code can carry a
different Priority/MOQ depending on which physical line produces it
(confirmed against the real client file: Link Code 324811 differs between
DPC Baddi/DPC-Choc and Makson B/Makson B). Priority is read per-period
(bare-integer columns "1".."14", matching Linkcode_DIFC / 2.Demand Input's
own convention) rather than a single static value, so it can differ month to
month for the same Link Code/Line. MOQ stays a single value -- not extended
to a month dimension (client decision, since it was never formally in
CR-01's scope).

Priority(Linkcode Level) is Link-Code level by design -- it has no SKU
column at all. SKU-level priority sequencing (the two-key language in the
flow doc's "SKU Sequencing and Prioritization" section, and CR-04's
SKU-vs-Link-Code hierarchy) has no basis in this or any other current
input. This is a structural fact about the input set, independent of
whether SKU happens to equal Link Code in today's data -- that coincidence
is not the reason SKU-level priority is out of scope, and shouldn't be
relied on as one.

Any FIN row whose (Link Code, Plant, Line) has no match in Priority(Linkcode
Level) gets no MOQ constraint (all volume via Run 2) and sorts *after*
every real-priority row in its (plant_line, period) group -- never
interleaved with real priorities via a bare counter landing in the same
field (the pre-pass below computes each group's max real priority for
exactly this reason).

Target DOS comes from Linkcode_DIFC's `Avg_min_dos_target` column (MPS Output),
joined by numeric Link Code -- real per-product values, and the source is
flagged per run. If a Link Code has no value there, Target DOS defaults to
Opening DOS (so DOS gap = 0). See LIMITATIONS.md #8.

Throughput is read from the SOC sheet's `SOC` column (per the ground-truth
doc's stated input mapping: Throughput/GE -> "4. SOC Sheet & Flag"), with GE%
applied as a separate multiplier at allocation time (engine/allocation.py's
hours<->quantity conversion) — never pre-baked into the throughput value here.

Contract:
    consumes: MPSInputData, MPSOutputData, ManualInputData, FallbackDecisions
    produces: ConsolidatedTable
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass

import pandas as pd

from engine.fallback import FallbackDecisions
from engine.parsers.manual_input_parser import ManualInputData
from engine.parsers.mps_input_parser import MPSInputData
from engine.parsers.mps_output_parser import MPSOutputData, plant_line_columns

CONSOLIDATED_COLUMNS = [
    "period", "month_num", "month_key", "plant", "line", "plant_line",
    "link_code", "link_desc", "brand",
    "current_fin", "opening_dos", "target_dos", "dos_gap", "daily_demand",
    "priority", "moq_days", "throughput_per_day", "ge_pct",
    "row_assumptions",
]


@dataclass
class ConsolidatedTable:
    data: pd.DataFrame  # columns per CONSOLIDATED_COLUMNS


def _period_to_month_info(period_calendar: pd.DataFrame) -> dict[int, tuple[int, str, int]]:
    """Period Calendar Matrix: Key (date) -> Period.
    Returns Period -> (calendar month number, month_key string e.g. "Jun-26",
    actual days in that month). The month_key matches the Calendar sheet's
    Key1/Key2 format; days-in-month is leap-year-correct since it comes straight
    from the period's own date, and is used to turn monthly demand into a
    per-day rate (see daily_demand below).
    """
    if period_calendar.empty:
        return {}
    out = {}
    for _, row in period_calendar.iterrows():
        key, period = row.get("Key"), row.get("Period")
        if pd.isna(key) or pd.isna(period):
            continue
        ts = pd.Timestamp(key)
        out[int(period)] = (ts.month, ts.strftime("%b-%y"), calendar.monthrange(ts.year, ts.month)[1])
    return out


def build(
    mps_input: MPSInputData,
    mps_output: MPSOutputData,
    manual_input: ManualInputData,
    fallback: FallbackDecisions,
) -> ConsolidatedTable:
    monthly_fin = mps_output.monthly_fin
    plant_line_cols = plant_line_columns(monthly_fin)

    # Link Code comes straight from the FIN sheet -- there is no SKU column to
    # read on this branch (mps_input.sku_master stays parsed-but-unused, same
    # as on the SKU-based version; see its module docstring and LIMITATIONS.md L4).
    long_fin = monthly_fin.melt(
        id_vars=["Period", "Link Code", "Link Desc Description", "Brand"],
        value_vars=plant_line_cols,
        var_name="plant_line",
        value_name="current_fin",
    )
    long_fin = long_fin[long_fin["current_fin"].fillna(0) > 0].copy()
    long_fin[["plant", "line"]] = long_fin["plant_line"].str.split("_", n=1, expand=True)

    period_month = _period_to_month_info(mps_input.period_calendar)

    # Opening DOS lookup: Linkcode_DIFC has one column per period number (1..N)
    difc = mps_output.linkcode_difc
    difc_by_link = {}
    if not difc.empty:
        for _, row in difc.iterrows():
            difc_by_link[row["Link Code"]] = row

    # Priority/MOQ lookup, keyed by (Link Code, Plant, Line) -- the same Link
    # Code can carry a different Priority/MOQ depending on which physical line
    # produces it (see module docstring).
    priority_by_key = {}
    if (manual_input.priority is not None
            and {"Link Code", "Plant", "Line"}.issubset(manual_input.priority.columns)):
        for _, row in manual_input.priority.iterrows():
            priority_by_key[(row.get("Link Code"), row.get("Plant"), row.get("Line"))] = row

    # SOC lookup for throughput/GE%, keyed by (Link Code, Period, Plant, Line)
    soc = mps_input.soc
    soc_by_key = {}
    if not soc.empty:
        for _, row in soc.iterrows():
            key = (row.get("Link Code"), row.get("Period"), row.get("Plant"), row.get("Line"))
            soc_by_key[key] = row

    # Monthly demand lookup (2.Demand Input), keyed by Link Code with one column
    # per period number -- same shape engine/dos_difc.py consumes. Used to turn
    # the DOS gap (days of cover) into a tonnage at allocation time.
    demand = mps_input.demand
    demand_by_link = {}
    if not demand.empty and "Link Code" in demand.columns:
        for _, row in demand.iterrows():
            demand_by_link[row["Link Code"]] = row

    # Pre-pass: per (plant_line, period) group, find the highest real priority
    # value among Link Codes that DO match Priority(Linkcode Level), so
    # unmatched Link Codes can be sorted strictly after every matched one in
    # the main loop below -- never interleaved via a bare counter landing in
    # the same field as real, planner-assigned priorities.
    max_priority_by_group: dict[tuple, float] = {}
    if priority_by_key and not fallback.use_default_priority:
        for _, r in long_fin.iterrows():
            period = int(r["Period"])
            priority_row = priority_by_key.get((r["Link Code"], r["plant"], r["line"]))
            if priority_row is None or period not in priority_row.index:
                continue
            val = priority_row[period]
            if pd.isna(val):
                continue
            group_key = (r["plant_line"], period)
            val = float(val)
            if val > max_priority_by_group.get(group_key, 0.0):
                max_priority_by_group[group_key] = val

    records = []
    fallback_row_order_counter: dict[tuple, int] = {}

    for _, r in long_fin.iterrows():
        period = int(r["Period"])
        link_code = r["Link Code"]
        link_desc = r["Link Desc Description"]
        plant, line = r["plant"], r["line"]
        plant_line = r["plant_line"]
        row_assumptions: list[str] = []

        month_num, month_key, days_in_month = period_month.get(period, (None, None, None))

        difc_row = difc_by_link.get(link_code)
        opening_dos = None
        if difc_row is not None and period in difc_row:
            val = difc_row[period]
            opening_dos = float(val) if pd.notna(val) else None
        if opening_dos is None:
            # Genuine gap discovered testing against the client's real sample data:
            # Linkcode_DIFC can have NaN for a specific SKU/period even when the SKU
            # itself is otherwise present. Defaulting to 0 is the conservative choice
            # (it maximizes DOS gap rather than assuming stock cover that may not
            # exist) -- flagged per-row rather than silently assumed.
            opening_dos = 0.0
            row_assumptions.append(
                f"No Opening DOS found for Link Code {link_code}, period {period} — "
                f"defaulted to 0."
            )

        priority_row = priority_by_key.get((link_code, plant, line)) if priority_by_key else None
        if priority_row is None and not fallback.use_default_priority and priority_by_key:
            row_assumptions.append(
                f"No Priority(Linkcode Level) match for Link Code {link_code} at "
                f"{plant}/{line} — Priority and MOQ not found for this row; planned in "
                f"file order with no run-length constraint (all volume via Run 2)."
            )

        group_key = (plant_line, period)
        priority_val = priority_row.get(period) if priority_row is not None else None
        if (priority_row is not None and period in priority_row.index
                and not pd.isna(priority_val) and not fallback.use_default_priority):
            priority = float(priority_val)
        else:
            # Unmatched (or no value for this specific period): sort strictly
            # after every real-priority row in this (plant_line, period) group,
            # then by file order among themselves -- never interleaved with
            # real priorities via a bare counter landing in the same field.
            fallback_row_order_counter[group_key] = fallback_row_order_counter.get(group_key, 0) + 1
            priority = max_priority_by_group.get(group_key, 0.0) + fallback_row_order_counter[group_key]
            if "Priority not supplied" not in "".join(fallback.messages):
                row_assumptions.append(
                    "Priority defaulted to file order, after every matched Link Code "
                    "(no Priority(Linkcode Level) match for this row/period)."
                )

        if priority_row is not None and not pd.isna(priority_row.get("MOQ")) and not fallback.use_default_moq:
            moq_days = float(priority_row["MOQ"])
        else:
            moq_days = None  # signals "no MOQ constraint" to allocation.py
            if priority_row is not None and not fallback.use_default_moq:
                # Matched on (Link Code, Plant, Line) but its MOQ cell is blank
                # -- flag it (the no-match case above already carries its own
                # message).
                row_assumptions.append(
                    f"MOQ not found for Link Code {link_code} at {plant}/{line} — "
                    f"planned with no run-length constraint (all volume via Run 2)."
                )

        # Target DOS: sole source is Linkcode_DIFC's `Avg_min_dos_target` column
        # (MPS Output), joined by numeric Link Code -- real per-product values,
        # available even for a Link Code with no Priority(Linkcode Level) match. If a Link Code has no
        # value there, Target DOS defaults to Opening DOS (DOS gap = 0). The
        # source is flagged (constant strings -> one line each in the
        # Assumption Applied tab). See LIMITATIONS.md #8.
        difc_target = None
        if (difc_row is not None and "Avg_min_dos_target" in difc_row
                and not pd.isna(difc_row["Avg_min_dos_target"])):
            difc_target = float(difc_row["Avg_min_dos_target"])

        if difc_target is not None:
            target_dos = difc_target
            row_assumptions.append(
                "Target DOS is taken from Linkcode_DIFC.Avg_min_dos_target (MPS Output)."
            )
        else:
            target_dos = opening_dos  # no Avg_min_dos_target for this Link Code -> DOS gap = 0
            row_assumptions.append(
                "One or more Link Codes have no Linkcode_DIFC.Avg_min_dos_target value — "
                "their DOS gap is treated as 0."
            )

        soc_row = soc_by_key.get((link_code, period, plant, line))
        # ASSUMPTION: SOC's "SOC" column is the daily throughput rate, in the same
        # unit as FIN (e.g. Tons/day) -- matches the worked example's "37 Ton/Day"
        # pattern. Needs confirmation from the client before go-live.
        throughput_per_day = float(soc_row["SOC"]) if soc_row is not None and not pd.isna(soc_row.get("SOC")) else 0.0
        ge_pct = float(soc_row["GE%"]) if soc_row is not None and not pd.isna(soc_row.get("GE%")) else 1.0

        # Daily demand = monthly demand (2.Demand Input, per-period column) / days
        # in the month. This is the rate that depletes days of stock cover, so it
        # -- not throughput -- is what converts the DOS gap into a tonnage in
        # engine/allocation.py's Run 1 (Case D). Same definition as dos_difc.py.
        demand_row = demand_by_link.get(link_code)
        monthly_demand = float(demand_row[period]) if (
            demand_row is not None and period in demand_row and not pd.isna(demand_row[period])
        ) else 0.0
        daily_demand = monthly_demand / (days_in_month or 30) if monthly_demand else 0.0

        dos_gap = max(target_dos - opening_dos, 0.0)
        if dos_gap > 0 and daily_demand == 0:
            row_assumptions.append(
                f"No monthly demand for Link Code {link_code}, period {period} — "
                f"DOS gap cannot be sized in tonnes; it will be closed via Run 2."
            )

        records.append({
            "period": period,
            "month_num": month_num,
            "month_key": month_key,
            "plant": plant,
            "line": line,
            "plant_line": plant_line,
            "link_code": link_code,
            "link_desc": link_desc,
            "brand": r["Brand"],
            "current_fin": float(r["current_fin"]),
            "opening_dos": opening_dos,
            "target_dos": target_dos,
            "dos_gap": dos_gap,
            "daily_demand": daily_demand,
            "priority": priority,
            "moq_days": moq_days,
            "throughput_per_day": throughput_per_day,
            "ge_pct": ge_pct,
            "row_assumptions": row_assumptions,
        })

    df = pd.DataFrame.from_records(records, columns=CONSOLIDATED_COLUMNS)
    return ConsolidatedTable(data=df)
