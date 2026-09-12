"""Writes the Comparison Table tab (auditability) -- Architecture Document,
Section 5.9. Wide/transposed layout via output/period_pivot.py: one row per
(Plant, Line, Linkcode), planning periods as repeating column blocks.

Static, once: Plant, Line, Linkcode, Brand, Link Desc Description.
Per period: Total FIN(T), Opening Carryover, Total Produced, Carryover M+1,
gap_vs_fin, Active Weeks, CASE.
    - gap_vs_fin repeats per period on purpose, even though it is ~0 for
      essentially every real row today under the zero-tolerance reconciliation
      invariant: its job is to flag the one period where that invariant
      doesn't hold. Collapsing it to a single value would defeat that purpose
      the moment it ever happens -- this isn't the same kind of "usually
      constant" field MOQ or Target DOS are on the Weekly Plan sheet.
    - CASE is included here (Weekly Plan deliberately omits it, since this is
      its home sheet). It genuinely varies period to period -- a Link Code's
      Run 1 case changes as its DOS gap changes -- so it must repeat, not sit
      as a static column.
    - Total Produced and Carryover M+1 duplicate two Weekly Plan columns; that
      overlap predates this change (both sheets always read the same
      SkuAllocation fields) and is carried forward unchanged, not introduced
      or removed here.
"""
from __future__ import annotations

import pandas as pd

from engine.allocation import WEEK_ORDER
from engine.engine_result import EngineResult
from output import period_pivot

STATIC_FIELDS = [
    ("Plant", lambda a: a.plant),
    ("Line", lambda a: a.line),
    ("Linkcode", lambda a: a.link_code),
    ("Brand", lambda a: a.brand),
    ("Link Desc Description", lambda a: a.link_desc),
]


def _active_weeks(alloc) -> int:
    return sum(1 for wk in WEEK_ORDER if getattr(alloc, wk) > 0)


_PERIOD_FIELDS = [
    ("Total FIN(T)", lambda a: a.current_fin),
    ("Opening Carryover", lambda a: a.carryover_fin_in),
    ("Total Produced", lambda a: round(a.total_all, 1)),
    ("Carryover M+1", lambda a: a.carryover_next),
    ("gap_vs_fin", lambda a: a.gap_vs_fin),
    ("Active Weeks", _active_weeks),
    ("CASE", lambda a: a.moq_case),
]


def _no_extra_fields(month_num, period_rows):
    return []  # no week-conditional columns on this sheet


def build(result: EngineResult) -> tuple[pd.DataFrame, list[str], list[str]]:
    return period_pivot.build(
        result.reconciled.rows, STATIC_FIELDS, _PERIOD_FIELDS, _no_extra_fields,
    )
