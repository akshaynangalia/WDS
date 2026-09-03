"""
Reconciliation pass.

The pool this SKU must fully account for across the run is:
    total_pool = current_fin + carryover_fin_in

That pool is produced across wk1a + wk1..wk5 (carryover and current-month
FIN can land in the same bucket -- see engine/allocation.py's carryover
spillover logic), so reconciliation compares against the POOL, not just
current_fin, and treats wk1a as an active bucket like any other:

    gap = total_pool - (wk1a + wk1 + wk2 + wk3 + wk4 + wk5)
    - If at least one bucket already has production, distribute the gap
      (typically a small rounding residual) across those active buckets --
      but only as far as each week's REAL remaining capacity allows
      (24*7 - downtime - hours already used on the line; carried on
      AllocationResult.leftover_capacity). Whatever still won't fit rolls
      to CARRYOVER_MPLUS1, exactly like a SKU that got no allocation.
    - If NO bucket has any production at all, the entire pool rolls to
      CARRYOVER_MPLUS1 for next month -- nothing is silently dropped.

Conservation law enforced (tests/test_reconciliation_invariant.py checks
this on every row, always):

    (wk1a + wk1 + wk2 + wk3 + wk4 + wk5) + carryover_next == current_fin + carryover_fin_in
"""
from __future__ import annotations

from dataclasses import dataclass

# _hours_needed / _qty_from_hours are the GE%-aware hours<->quantity converters;
# reused here (rather than re-implemented) to keep the capacity ceiling in the
# exact same units as allocation.
from engine.allocation import (
    AllocationResult,
    SkuAllocation,
    _hours_needed,
    _qty_from_hours,
)

ALL_BUCKETS = ("wk1a", "wk1", "wk2", "wk3", "wk4", "wk5")
GAP_TOLERANCE = 0.05


@dataclass
class ReconciledResult:
    rows: list[SkuAllocation]


def reconcile(alloc_result: AllocationResult) -> ReconciledResult:
    # Mutable copy of each line's real remaining weekly capacity (hours), so a
    # top-up for one SKU reduces what is still available to the next SKU sharing
    # that line-week -- mirroring how allocation shares weekly capacity.
    leftover = {key: dict(caps) for key, caps in alloc_result.leftover_capacity.items()}

    for alloc in alloc_result.rows:
        total_pool = alloc.current_fin + alloc.carryover_fin_in
        produced = sum(getattr(alloc, bucket) for bucket in ALL_BUCKETS)
        gap = round(total_pool - produced, 2)

        if abs(gap) <= GAP_TOLERANCE:
            alloc.gap_vs_fin = 0.0
            continue

        active_buckets = [b for b in ALL_BUCKETS if getattr(alloc, b) > 0]

        if gap < 0:
            # Over-produced vs the pool (rounding-scale): pull the excess back
            # out evenly across active buckets. Removing volume can't breach a
            # capacity ceiling, so this direction stays uncapped, as before.
            if active_buckets:
                per_bucket = gap / len(active_buckets)
                for b in active_buckets:
                    setattr(alloc, b, round(getattr(alloc, b) + per_bucket, 1))
            alloc.gap_vs_fin = 0.0
            continue

        # gap > 0 -- a genuine shortfall. Top up active buckets, but never past
        # that week's real remaining capacity; roll the rest to CARRYOVER_MPLUS1.
        line_caps = leftover.get((alloc.plant_line, alloc.period))
        remaining = gap
        for b in active_buckets:
            if remaining <= 0:
                break
            if line_caps is None:
                add = remaining  # no capacity record supplied -> legacy uncapped behaviour
            else:
                max_qty = _qty_from_hours(
                    line_caps.get(b, 0.0), alloc.throughput_per_day, alloc.ge_pct
                )
                add = min(remaining, max_qty)
            if add <= 0:
                continue
            setattr(alloc, b, round(getattr(alloc, b) + add, 1))
            if line_caps is not None:
                line_caps[b] = round(
                    line_caps.get(b, 0.0)
                    - _hours_needed(add, alloc.throughput_per_day, alloc.ge_pct),
                    1,
                )
            remaining -= add

        # Recompute from the actual (rounded) bucket values so every per-bucket
        # rounding hair is absorbed into this one carryover figure -- the
        # conservation law then holds to a single rounding step, not N.
        residual = round(total_pool - sum(getattr(alloc, b) for b in ALL_BUCKETS), 1)
        if residual > GAP_TOLERANCE:
            alloc.carryover_next = round(alloc.carryover_next + residual, 1)
            alloc.gap_vs_fin = 0.0
        elif residual < -GAP_TOLERANCE and active_buckets:
            # Rounding overshoot -- trim it off the largest active bucket.
            b = max(active_buckets, key=lambda x: getattr(alloc, x))
            setattr(alloc, b, round(getattr(alloc, b) + residual, 1))
            alloc.gap_vs_fin = 0.0
        else:
            alloc.gap_vs_fin = 0.0

    return ReconciledResult(rows=alloc_result.rows)


def assert_conservation(reconciled: ReconciledResult) -> list[str]:
    """Returns violation messages -- empty means the invariant holds for
    every row. Used by tests/test_reconciliation_invariant.py."""
    violations = []
    for alloc in reconciled.rows:
        lhs = alloc.total_all + alloc.carryover_next
        rhs = alloc.current_fin + alloc.carryover_fin_in
        if abs(lhs - rhs) > GAP_TOLERANCE:
            violations.append(
                f"{alloc.plant_line}/{alloc.sku}/period {alloc.period}: "
                f"produced+carryover_next={lhs:.2f} != fin+carryover_in={rhs:.2f}"
            )
    return violations
