"""
REQ-CR-05 -- Month-end changeover / split-week handling.

A Link Code producing in a line's real final calendar week of the period
(W4, or W5 in a five-week month) that still has carryover_next > 0 must be
served first for that leftover volume in the following period -- ahead of
every other Link Code's carryover or fresh FIN on that line -- so no
changeover is inserted between the two months' runs on that resource.

Applies regardless of which Run 1 Case (A/B/C/D/No MOQ) produced the
shortfall. The override is scoped strictly to the carryover-servicing step
(engine/allocation.py's W1A pass and its W1-W4 residual spread) for the next
period -- that Link Code's own fresh FIN the following period is still
processed at its normal assigned priority through Run 1/Run 2, unaffected.
Any number of Link Codes on a line may qualify simultaneously; among
themselves they keep their normal relative priority order, all ahead of
every non-qualifying Link Code. No new input file/column is required -- the
trigger is derived entirely from existing engine state (production
placement and carryover).

"Last week" is the period's fixed calendar-final week -- W5 if the month is
a five-week month (month MOD 3 == 0), else W4 -- not "whichever week
happened to have output". A week with zero production for everyone (the
line went idle early) never triggers this, regardless of leftover volume:
nothing was actively running when the month ended, so there is no
in-progress run for a changeover to interrupt.

Contract:
    consumes: ReconciledResult (one period's finished allocation)
    produces: set of (plant_line, link_code) pairs that must be served first
              in the NEXT period's carryover-servicing step -- fed forward by
              orchestration/run_manager.py, the same way carryover.py's
              extracted quantities are.
"""
from __future__ import annotations

from datetime import datetime

from engine.reconciliation import ReconciledResult

_CARRYOVER_EPSILON = 0.01  # matches the tolerance already used in allocation.py's residual checks


def _month_num(month_key: str) -> int | None:
    try:
        return datetime.strptime(str(month_key), "%b-%y").month
    except (ValueError, TypeError):
        return None


def compute_priority_overrides(reconciled: ReconciledResult) -> set[tuple[str, object]]:
    by_plant_line: dict[str, list] = {}
    for row in reconciled.rows:
        by_plant_line.setdefault(row.plant_line, []).append(row)

    overrides: set[tuple[str, object]] = set()
    for plant_line, rows in by_plant_line.items():
        month_num = _month_num(rows[0].month_key)
        # Fallback to W4 (the coarser, more common case) if the month can't
        # be determined -- consistent with this codebase's other coarse
        # defaults (e.g. capacity.py's full-week fallback) rather than
        # silently skipping the line.
        last_week_attr = "wk5" if month_num is not None and month_num % 3 == 0 else "wk4"

        for row in rows:
            if getattr(row, last_week_attr) > 0 and row.carryover_next > _CARRYOVER_EPSILON:
                overrides.add((plant_line, row.link_code))

    return overrides
