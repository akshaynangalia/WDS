"""Weekly Plan tab -- the tool's only weekly-plan output, in the client's
sample layout: one row per (Plant, Line, Linkcode), with planning periods
spread ACROSS the sheet as repeating column blocks instead of down it as
repeated rows. (An earlier, untransposed "Weekly Plan" tab -- one row per
period -- has been removed; this tab replaces it, not supplements it.)

Static columns, shown once (left of the period blocks): Plant, Line,
Linkcode, Brand, Link Desc Description, MOQ.
    - MOQ is read once per (Plant, Line, Linkcode) row, not repeated per
      period: it comes from a single, non-period-indexed column on
      Priority(Linkcode Level), looked up once per (Link Code, Plant, Line)
      before the per-FIN-row loop even runs (consolidation.py) -- it cannot
      differ by period for the same row. Verified empirically too: 0 of 115
      real (Plant, Line, Linkcode) groups show any MOQ variation across
      periods.

Per-period block: Opening DOS, Target DOS, Priority, W1, W2, W3, W4, [W5],
Carryover M+1, Total Produced.
    - Opening DOS and Priority genuinely change period to period (105/115 and
      83/115 real groups vary) -- each period must show its own value.
    - Target DOS is usually constant per Link Code (its source,
      Linkcode_DIFC.Avg_min_dos_target, is also not period-indexed) but is
      NOT structurally guaranteed constant: when that column has no value for
      a Link Code, consolidation.py falls back to that period's Opening DOS,
      which does vary. Kept per-period rather than static for this reason,
      even though it is empirically constant on real data today.
    - W1 here is W1A + W1 (the whole first calendar week, including the days
      that fall in the previous month). W1A has no column of its own on this
      sheet -- folded into W1 to match the client sample, which has no W1A
      column either. Stated in the column header and in NOTE below. Total
      Produced is unchanged, so every row still reconciles to FIN.
    - W5 appears only for a five-week month (calendar month in Mar/Jun/Sep/Dec,
      i.e. month MOD 3 == 0) -- the same rule the engine uses to decide whether
      a W5 bucket exists at all. Those period blocks are one column wider.
    - CASE is deliberately NOT included here -- it already lives on the
      Comparison Table (the audit artifact); repeating it here would just
      duplicate that sheet with no new information.

The period band label is the month key straight from consolidation.py, which
derives it from the Period Calendar Matrix (period -> Key date -> "%b-%y") --
it is not assumed here.

Contract:
    consumes: EngineResult
    produces: (DataFrame with flat unique columns, header_row1, header_row2)
              -- excel_writer lays the two header rows down itself so it can
              merge each month band.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from engine.engine_result import EngineResult

ID_COLS = ["Plant", "Line", "Linkcode", "Brand", "Link Desc Description"]
STATIC_COLS = ["MOQ"]  # constant per row, but not part of the row's identity
LEFT_COLS = ID_COLS + STATIC_COLS

W1_LABEL = "W1 (=W1A+W1)"
_PERIOD_CONTEXT_LABELS = ["Opening DOS", "Target DOS", "Priority"]
_BASE_WEEK_LABELS = ["W1", "W2", "W3", "W4"]
_TAIL_LABELS = ["Carryover M+1", "Total Produced"]

NOTE = (
    'Note: W1 = W1A + W1 -- the first calendar week, including the days that '
    'fall in the previous month (prior-month carryover is produced on those days).'
)


def _month_num(month_key: str) -> int | None:
    try:
        return datetime.strptime(str(month_key), "%b-%y").month
    except (ValueError, TypeError):
        return None


def _period_block_labels(has_w5: bool) -> list[str]:
    return _PERIOD_CONTEXT_LABELS + _BASE_WEEK_LABELS + (["W5"] if has_w5 else []) + _TAIL_LABELS


def _value_for(alloc, label: str):
    if label == "Opening DOS":
        return alloc.opening_dos
    if label == "Target DOS":
        return alloc.target_dos
    if label == "Priority":
        return alloc.priority
    if label == "W1":
        return round(alloc.wk1a + alloc.wk1, 1)
    if label == "W2":
        return round(alloc.wk2, 1)
    if label == "W3":
        return round(alloc.wk3, 1)
    if label == "W4":
        return round(alloc.wk4, 1)
    if label == "W5":
        return round(alloc.wk5, 1)
    if label == "Carryover M+1":
        return round(alloc.carryover_next, 1)
    if label == "Total Produced":
        return round(alloc.total_all, 1)
    raise KeyError(label)  # unreachable -- guards a typo in _period_block_labels


def build(result: EngineResult) -> tuple[pd.DataFrame, list[str], list[str]]:
    rows = result.reconciled.rows

    periods = sorted({r.period for r in rows})
    # period -> (band label, has_w5)
    pinfo: dict[int, tuple[str, bool]] = {}
    for p in periods:
        month_key = next((r.month_key for r in rows if r.period == p and r.month_key), None) or f"P{p}"
        mn = _month_num(month_key)
        has_w5 = (mn % 3 == 0) if mn is not None else any(r.period == p and r.wk5 for r in rows)
        pinfo[p] = (month_key, has_w5)

    keyed: dict[tuple, dict[int, object]] = {}
    for r in rows:
        keyed.setdefault((r.plant, r.line, r.link_code), {})[r.period] = r

    header_row1 = list(LEFT_COLS)
    header_row2 = list(LEFT_COLS)
    col_specs: list[tuple[int, str]] = []  # (period, label) in column order
    for p in periods:
        band, has_w5 = pinfo[p]
        for lbl in _period_block_labels(has_w5):
            header_row1.append(band)
            header_row2.append(W1_LABEL if lbl == "W1" else lbl)
            col_specs.append((p, lbl))

    flat_cols = LEFT_COLS + [f"{band} | {lbl}" for band, lbl in zip(header_row1[len(LEFT_COLS):], header_row2[len(LEFT_COLS):])]

    records = []
    for key in sorted(keyed, key=lambda k: (str(k[0]), str(k[1]), str(k[2]))):
        by_period = keyed[key]
        any_alloc = next(iter(by_period.values()))
        rec = {
            "Plant": key[0], "Line": key[1], "Linkcode": key[2],
            "Brand": any_alloc.brand, "Link Desc Description": any_alloc.link_desc,
            "MOQ": any_alloc.moq_days,  # invariant across periods for this row -- see module docstring
        }
        for (p, lbl), col in zip(col_specs, flat_cols[len(LEFT_COLS):]):
            alloc = by_period.get(p)
            rec[col] = None if alloc is None else _value_for(alloc, lbl)
        records.append(rec)

    df = pd.DataFrame.from_records(records, columns=flat_cols)
    return df, header_row1, header_row2
