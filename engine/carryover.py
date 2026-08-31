"""
Extracts Carryover M+1 from a reconciled period's results, in the shape
allocation.run() expects as its `carryover_fin_in` argument for the *next*
period in the horizon. This is what makes a multi-period run a closed loop
across planning periods, per the ground-truth doc's "Carryover M+1
Generation" section.

For the very first period in a run, there is no prior period computed by
this tool -- an external "opening carryover" (matching the "Opening
Carryover (first month only)" input seen in the reference UI screenshots)
is used instead, defaulting to 0 per SKU if not supplied.

Contract:
    consumes: ReconciledResult
    produces: dict[(plant_line, link_code), float] -- ready to pass straight
              back into allocation.run() for the next period
"""
from __future__ import annotations

from engine.reconciliation import ReconciledResult


def extract_carryover(reconciled: ReconciledResult) -> dict[tuple[str, object], float]:
    out: dict[tuple[str, object], float] = {}
    for alloc in reconciled.rows:
        if alloc.carryover_next > 0:
            out[(alloc.plant_line, alloc.link_code)] = alloc.carryover_next
    return out
