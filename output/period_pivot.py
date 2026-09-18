"""Shared "period pivot" scaffold for wide-format output sheets: one row per
(Plant, Line, Linkcode), planning periods spread ACROSS the sheet as
repeating column blocks instead of down it as repeated rows. Used by
comparison_table_sheet.py and difc_summary_sheet.py.

output/weekly_plan_sheet.py deliberately does NOT use this: it shipped and
was verified (63 tests, a real-data reconciliation cross-check) before this
module existed. Refactoring it to share this scaffold would re-risk already
-correct, already-reviewed code for a DRY-only gain, against this project's
own UAT discipline (surgical changes, no "while I'm here" refactors). Two new
sheets is enough to justify extracting the scaffold once; it doesn't obligate
rewriting a third that already works.

A caller supplies:
    rows: objects exposing .plant, .line, .link_code, .period, .month_key
          (SkuAllocation and DIFCRow both do).
    static_fields: [(label, fn(any_row_in_group) -> value), ...] -- shown
                   once, left of the period blocks.
    period_fields: [(label, fn(row) -> value), ...] -- present in every
                   period block.
    extra_period_fields(month_num, period_rows) -> [(label, fn), ...] --
                   fields present only for some periods. Receives every row
                   in that period so the decision can be data-driven rather
                   than assumed from the calendar month alone -- e.g.
                   dos_difc.py only populates a "wk5" key on a row when that
                   row's own wk5 production is nonzero (a per-row truthiness
                   gate, not a per-period one), so a Weekly DIFC block needs a
                   WK5 column whenever ANY row that period has the key, not
                   simply because the calendar month is a five-week month.
                   Pass a no-op returning [] if there are no such fields.

The period band label is the month key carried on the rows themselves,
already derived from the Period Calendar Matrix upstream -- not assumed here.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd


def month_num(month_key: str) -> int | None:
    try:
        return datetime.strptime(str(month_key), "%b-%y").month
    except (ValueError, TypeError):
        return None


def build(
    rows: list,
    static_fields: list[tuple[str, "callable"]],
    period_fields: list[tuple[str, "callable"]],
    extra_period_fields: "callable",
) -> tuple[pd.DataFrame, list[str], list[str]]:
    periods = sorted({r.period for r in rows})
    period_rows = {p: [r for r in rows if r.period == p] for p in periods}

    # period -> (band label, this period's full field list incl. extras)
    pinfo: dict[int, tuple[str, list]] = {}
    for p in periods:
        prows = period_rows[p]
        band = next((r.month_key for r in prows if r.month_key), None) or f"P{p}"
        mn = month_num(band)
        pinfo[p] = (band, period_fields + extra_period_fields(mn, prows))

    keyed: dict[tuple, dict[int, object]] = {}
    for r in rows:
        keyed.setdefault((r.plant, r.line, r.link_code), {})[r.period] = r

    left_labels = [label for label, _ in static_fields]
    header_row1 = list(left_labels)
    header_row2 = list(left_labels)
    col_specs: list[tuple[int, "callable", str]] = []  # (period, value_fn, flat_col)
    for p in periods:
        band, fields = pinfo[p]
        for label, fn in fields:
            header_row1.append(band)
            header_row2.append(label)
            col_specs.append((p, fn, f"{band} | {label}"))
    flat_cols = left_labels + [col for _, _, col in col_specs]

    records = []
    for key in sorted(keyed, key=lambda k: (str(k[0]), str(k[1]), str(k[2]))):
        by_period = keyed[key]
        any_row = next(iter(by_period.values()))
        rec = {label: fn(any_row) for label, fn in static_fields}
        for p, fn, col in col_specs:
            row = by_period.get(p)
            rec[col] = None if row is None else fn(row)
        records.append(rec)

    df = pd.DataFrame.from_records(records, columns=flat_cols)
    return df, header_row1, header_row2
