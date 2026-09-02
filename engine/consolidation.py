"""
Reconstructs the legacy tool's "Consolidated Input" equivalent: one row per
Plant-Line-SKU-Period, with Current FIN, Opening DOS, Target DOS, DOS Gap,
Priority, MOQ, Throughput and GE% all joined together.

ASSUMPTION FLAGGED FOR CLIENT CONFIRMATION (see Development Planning Document,
Risk Register): the sample Manual Input (RCCP) file identifies a Link Code only
by its text description ("Link Code Desc"), not by the numeric Link Code used
in the MPS Input/Output files. This module joins on a normalized description
match as a best effort. A numeric Link Code column in RCCP would be far more
reliable and should be requested from the client before go-live. Any SKU that
doesn't find an RCCP match is treated exactly like "RCCP missing" for that row
(same fallback defaults, logged per-row).

Throughput is read from the SOC sheet's `SOC` column (per the ground-truth
doc's stated input mapping: Throughput/GE -> "4. SOC Sheet & Flag"), with GE%
applied as a separate multiplier at allocation time (engine/allocation.py's
hours<->quantity conversion) — never pre-baked into the throughput value here.

Contract:
    consumes: MPSInputData, MPSOutputData, ManualInputData, FallbackDecisions
    produces: ConsolidatedTable
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from engine.fallback import FallbackDecisions
from engine.parsers.manual_input_parser import ManualInputData
from engine.parsers.mps_input_parser import MPSInputData
from engine.parsers.mps_output_parser import MPSOutputData, plant_line_columns

CONSOLIDATED_COLUMNS = [
    "period", "month_num", "month_key", "plant", "line", "plant_line",
    "link_code", "link_desc", "sku",
    "current_fin", "opening_dos", "target_dos", "dos_gap",
    "priority", "moq_days", "throughput_per_day", "ge_pct",
    "row_assumptions",
]


@dataclass
class ConsolidatedTable:
    data: pd.DataFrame  # columns per CONSOLIDATED_COLUMNS


def _normalize(text) -> str:
    if pd.isna(text):
        return ""
    return str(text).strip().lower()


def _period_to_month_info(period_calendar: pd.DataFrame) -> dict[int, tuple[int, str]]:
    """Period Calendar Matrix: Key (date) -> Period.
    Returns Period -> (calendar month number, month_key string e.g. "Jun-26"),
    the latter matching the format Calendar sheet's Key1/Key2 columns use.
    """
    if period_calendar.empty:
        return {}
    out = {}
    for _, row in period_calendar.iterrows():
        key, period = row.get("Key"), row.get("Period")
        if pd.isna(key) or pd.isna(period):
            continue
        ts = pd.Timestamp(key)
        out[int(period)] = (ts.month, ts.strftime("%b-%y"))
    return out


def build(
    mps_input: MPSInputData,
    mps_output: MPSOutputData,
    manual_input: ManualInputData,
    fallback: FallbackDecisions,
) -> ConsolidatedTable:
    monthly_fin = mps_output.monthly_fin
    plant_line_cols = plant_line_columns(monthly_fin)

    long_fin = monthly_fin.melt(
        id_vars=["Period", "SKU", "Link Code", "Link Desc Description"],
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

    # RCCP lookup, keyed by normalized Link Code Desc (best-effort — see module docstring)
    rccp_by_desc = {}
    if manual_input.rccp is not None and "Link Code Desc" in manual_input.rccp.columns:
        for _, row in manual_input.rccp.iterrows():
            rccp_by_desc[_normalize(row.get("Link Code Desc"))] = row

    # SOC lookup for throughput/GE%, keyed by (Link Code, Period, Plant, Line)
    soc = mps_input.soc
    soc_by_key = {}
    if not soc.empty:
        for _, row in soc.iterrows():
            key = (row.get("Link Code"), row.get("Period"), row.get("Plant"), row.get("Line"))
            soc_by_key[key] = row

    records = []
    fallback_row_order_counter: dict[tuple, int] = {}

    for _, r in long_fin.iterrows():
        period = int(r["Period"])
        link_code = r["Link Code"]
        link_desc = r["Link Desc Description"]
        plant, line = r["plant"], r["line"]
        plant_line = r["plant_line"]
        row_assumptions: list[str] = []

        month_num, month_key = period_month.get(period, (None, None))

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

        rccp_row = rccp_by_desc.get(_normalize(link_desc)) if rccp_by_desc else None
        if rccp_row is None and not fallback.use_default_priority and rccp_by_desc:
            row_assumptions.append(
                f"No RCCP match for '{link_desc}' — MOQ and Target DOS not found for "
                f"this SKU; planned with no run-length constraint (all volume via "
                f"Run 2) and DOS gap treated as 0."
            )

        group_key = (plant_line, period)
        if rccp_row is not None and not pd.isna(rccp_row.get("Priority")) and not fallback.use_default_priority:
            priority = float(rccp_row["Priority"])
        else:
            fallback_row_order_counter[group_key] = fallback_row_order_counter.get(group_key, 0) + 1
            priority = float(fallback_row_order_counter[group_key])
            if "Priority not supplied" not in "".join(fallback.messages):
                row_assumptions.append("Priority defaulted to file order (no RCCP match).")

        if rccp_row is not None and not pd.isna(rccp_row.get("MOQ")) and not fallback.use_default_moq:
            moq_days = float(rccp_row["MOQ"])
        else:
            moq_days = None  # signals "no MOQ constraint" to allocation.py
            if rccp_row is not None and not fallback.use_default_moq:
                # RCCP matched this SKU but its MOQ cell is blank -- flag it
                # (the no-match case above already carries its own message).
                row_assumptions.append(
                    f"MOQ not found for '{link_desc}' — planned with no run-length "
                    f"constraint (all volume via Run 2)."
                )

        if rccp_row is not None and not pd.isna(rccp_row.get("Target DOS")) and not fallback.use_default_target_dos:
            target_dos = float(rccp_row["Target DOS"])
        else:
            target_dos = opening_dos  # forces DOS gap = 0 (Case B)

        soc_row = soc_by_key.get((link_code, period, plant, line))
        # ASSUMPTION: SOC's "SOC" column is the daily throughput rate, in the same
        # unit as FIN (e.g. Tons/day) -- matches the worked example's "37 Ton/Day"
        # pattern. Needs confirmation from the client before go-live.
        throughput_per_day = float(soc_row["SOC"]) if soc_row is not None and not pd.isna(soc_row.get("SOC")) else 0.0
        ge_pct = float(soc_row["GE%"]) if soc_row is not None and not pd.isna(soc_row.get("GE%")) else 1.0

        records.append({
            "period": period,
            "month_num": month_num,
            "month_key": month_key,
            "plant": plant,
            "line": line,
            "plant_line": plant_line,
            "link_code": link_code,
            "link_desc": link_desc,
            "sku": r["SKU"],
            "current_fin": float(r["current_fin"]),
            "opening_dos": opening_dos,
            "target_dos": target_dos,
            "dos_gap": max(target_dos - opening_dos, 0.0),
            "priority": priority,
            "moq_days": moq_days,
            "throughput_per_day": throughput_per_day,
            "ge_pct": ge_pct,
            "row_assumptions": row_assumptions,
        })

    df = pd.DataFrame.from_records(records, columns=CONSOLIDATED_COLUMNS)
    return ConsolidatedTable(data=df)
