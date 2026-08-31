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
      (typically a small rounding residual) across those active buckets.
    - If NO bucket has any production at all, the entire pool rolls to
      CARRYOVER_MPLUS1 for next month -- nothing is silently dropped.

Conservation law enforced (tests/test_reconciliation_invariant.py checks
this on every row, always):

    (wk1a + wk1 + wk2 + wk3 + wk4 + wk5) + carryover_next == current_fin + carryover_fin_in
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.allocation import AllocationResult, SkuAllocation

ALL_BUCKETS = ("wk1a", "wk1", "wk2", "wk3", "wk4", "wk5")
GAP_TOLERANCE = 0.05


@dataclass
class ReconciledResult:
    rows: list[SkuAllocation]


def reconcile(alloc_result: AllocationResult) -> ReconciledResult:
    for alloc in alloc_result.rows:
        total_pool = alloc.current_fin + alloc.carryover_fin_in
        produced = sum(getattr(alloc, bucket) for bucket in ALL_BUCKETS)
        gap = round(total_pool - produced, 2)

        if abs(gap) <= GAP_TOLERANCE:
            alloc.gap_vs_fin = 0.0
            continue

        active_buckets = [b for b in ALL_BUCKETS if getattr(alloc, b) > 0]
        if active_buckets:
            per_bucket = gap / len(active_buckets)
            for b in active_buckets:
                setattr(alloc, b, round(getattr(alloc, b) + per_bucket, 1))
            alloc.gap_vs_fin = 0.0
        else:
            alloc.carryover_next = round(max(gap, 0.0), 1)
            alloc.gap_vs_fin = round(gap - alloc.carryover_next, 1)  # should be 0

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
