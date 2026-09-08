"""Weekly Plan Transposed tab -- the same numbers as the Weekly Plan tab,
pivoted to the client's sample layout: one row per (Plant, Line, Linkcode),
with planning periods spread ACROSS the sheet as repeating column blocks
instead of down it as repeated rows.

Per-period block: W1, W2, W3, W4, [W5], Carryover M+1, Total Produced.
    - W1 here is W1A + W1 (the whole first calendar week, including the days
      that fall in the previous month). The Weekly Plan tab keeps W1A broken
      out on its own; this tab folds it in to match the client sample, which
      has no W1A column. Total Produced is unchanged, so every row still
      reconciles to FIN.
    - W5 appears only for a five-week month (calendar month in Mar/Jun/Sep/Dec,
      i.e. month MOD 3 == 0) -- the same rule the engine uses to decide whether
      a W5 bucket exists at all. Those period blocks are one column wider.

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
W1_LABEL = "W1 (=W1A+W1)"
_BASE_WEEK_LABELS = ["W1", "W2", "W3", "W4"]
_TAIL_LABELS = ["Carryover M+1", "Total Produced"]

NOTE = (
    'Note: W1 = W1A + W1 -- the first calendar week, including the days that '
    'fall in the previous month (prior-month carryover is produced on those '
    'days). The "Weekly Plan" sheet keeps W1A broken out as its own column.'
)


def _month_num(month_key: str) -> int | None:
    try:
        return datetime.strptime(str(month_key), "%b-%y").month
    except (ValueError, TypeError):
        return None


def _week_labels(has_w5: bool) -> list[str]:
    return _BASE_WEEK_LABELS + (["W5"] if has_w5 else []) + _TAIL_LABELS


def _value_for(alloc, label: str):
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
    raise KeyError(label)  # unreachable -- guards a typo in _week_labels


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

    header_row1 = list(ID_COLS)
    header_row2 = list(ID_COLS)
    col_specs: list[tuple[int, str]] = []  # (period, week label) in column order
    for p in periods:
        band, has_w5 = pinfo[p]
        for wl in _week_labels(has_w5):
            header_row1.append(band)
            header_row2.append(W1_LABEL if wl == "W1" else wl)
            col_specs.append((p, wl))

    flat_cols = ID_COLS + [f"{band} | {lbl}" for band, lbl in zip(header_row1[len(ID_COLS):], header_row2[len(ID_COLS):])]

    records = []
    for key in sorted(keyed, key=lambda k: (str(k[0]), str(k[1]), str(k[2]))):
        by_period = keyed[key]
        any_alloc = next(iter(by_period.values()))
        rec = {
            "Plant": key[0], "Line": key[1], "Linkcode": key[2],
            "Brand": any_alloc.brand, "Link Desc Description": any_alloc.link_desc,
        }
        for (p, wl), col in zip(col_specs, flat_cols[len(ID_COLS):]):
            alloc = by_period.get(p)
            rec[col] = None if alloc is None else _value_for(alloc, wl)
        records.append(rec)

    df = pd.DataFrame.from_records(records, columns=flat_cols)
    return df, header_row1, header_row2
