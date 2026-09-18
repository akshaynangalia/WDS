"""Writes the Weekly DIFC Summary tab (REQ-CR-06) -- Architecture Document,
Section 5.9. Wide/transposed layout via output/period_pivot.py: one row per
(Plant, Line, Linkcode), planning periods as repeating column blocks.

Static, once: Plant, Line, Linkcode, Brand, Link Desc Description,
Approximated (monthly avg).
    - Approximated is read from a single whole-run FallbackDecisions flag
      (engine/dos_difc.py: `approximated=fallback.use_monthly_avg_dos`), set
      once per run before any period is processed -- it cannot differ by
      period, structurally, not just empirically (confirmed: 0/115 real
      (Plant, Line, Linkcode) groups show any variation).
Per period: Opening DOS, WK1, WK2, WK3, WK4, [WK5].
    - WK5 is added to a period's block whenever ANY row in that period has a
      "wk5" key in its closing_by_week dict -- NOT simply because the
      calendar month is a five-week month (month MOD 3 == 0). dos_difc.py
      only computes a wk5 closing value for a row when that row's OWN wk5
      production is nonzero (`alloc.wk5 or ...`), a per-row truthiness gate --
      so within one five-week month, most rows can still have no wk5 key at
      all (confirmed on real data: Jun-26, a five-week month, has wk5 present
      on only 5 of its 90 rows). Gating the column purely on month MOD 3 would
      still be directionally right but would mislabel the mechanism; gating on
      "any row this period has the key" matches what the current long-format
      sheet actually does (pandas unions row keys), so the transposed sheet's
      WK5 presence is identical, not just similar, to what it replaces.
"""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult
from output import period_pivot

STATIC_FIELDS = [
    ("Plant", lambda r: r.plant),
    ("Line", lambda r: r.line),
    ("Linkcode", lambda r: r.link_code),
    ("Brand", lambda r: r.brand),
    ("Link Desc Description", lambda r: r.link_desc),
    ("Approximated (monthly avg)", lambda r: "Yes" if r.approximated else "No"),
]

_PERIOD_FIELDS = [
    ("Opening DOS", lambda r: r.opening_dos),
    ("WK1", lambda r: r.closing_by_week.get("wk1")),
    ("WK2", lambda r: r.closing_by_week.get("wk2")),
    ("WK3", lambda r: r.closing_by_week.get("wk3")),
    ("WK4", lambda r: r.closing_by_week.get("wk4")),
]

_WK5_FIELD = [("WK5", lambda r: r.closing_by_week.get("wk5"))]


def _extra_period_fields(month_num, period_rows):
    has_wk5 = any("wk5" in r.closing_by_week for r in period_rows)
    return _WK5_FIELD if has_wk5 else []


def build(result: EngineResult) -> tuple[pd.DataFrame, list[str], list[str]]:
    return period_pivot.build(
        result.difc.rows, STATIC_FIELDS, _PERIOD_FIELDS, _extra_period_fields,
    )
