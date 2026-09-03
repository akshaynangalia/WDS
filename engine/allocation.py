"""
The core Two-Run allocation heuristic, run per Plant-Line-Period, SKUs
processed in priority order:

    Run 1 (DOS-gap closure), Case A/B/C/D:
        A: FIN < 1.5 x MOQ         -> produce entire FIN, skip Run 2
        B: DOS gap = 0             -> produce one MOQ batch
        C: DOS gap exists, < MOQ   -> produce one full MOQ (floor)
        D: DOS gap exists, >= MOQ  -> produce exactly the DOS gap

    Run 2 (remaining FIN distribution): whatever FIN Run 1 didn't cover is
    spread across remaining weekly capacity, in week order, never producing
    below the MOQ floor per run.

Both runs, for every SKU on a line, are each done as a full pass across all
SKUs before the next pass starts -- matching the legacy VBA's two-loop
structure (all SKUs get Run 1 first, updating shared capacity; then all SKUs
get Run 2). This matters: a low-priority SKU's Run 1 can still be blocked by
a high-priority SKU's Run 1 exhausting a week's capacity first.

If fallback.use_default_moq is set (MOQ not supplied), Run 1 is skipped
entirely for every SKU on the affected line and 100% of FIN goes through
Run 2 -- this is what "MOQ not supplied, run-length constraints not
enforced" (Development Planning Document, Section 5) means concretely. The
same treatment is applied per-SKU to any single SKU whose MOQ is missing
(e.g. no RCCP match for that row) even when other SKUs on the line do have
one.

Contract:
    consumes: ConsolidatedTable, calendar_df (or None), FallbackDecisions,
              carryover_fin_in (dict keyed by (plant_line, link_code))
    produces: AllocationResult
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from engine import capacity
from engine.consolidation import ConsolidatedTable
from engine.fallback import FallbackDecisions

WEEK_ORDER = ("wk1", "wk2", "wk3", "wk4", "wk5")


@dataclass
class SkuAllocation:
    plant_line: str
    period: int
    link_code: object
    sku: object
    priority: float
    current_fin: float
    carryover_fin_in: float
    wk1a: float = 0.0
    wk1: float = 0.0
    wk2: float = 0.0
    wk3: float = 0.0
    wk4: float = 0.0
    wk5: float = 0.0
    carryover_next: float = 0.0  # CARRYOVER_MPLUS1 -- filled in by reconciliation.py
    gap_vs_fin: float = 0.0      # post-reconciliation residual, should be ~0 -- COMPARISON_TABLE field
    moq_case: str = ""           # Run 1 branch that applied: "A"/"B"/"C"/"D"/"No MOQ" -- COMPARISON_TABLE field
    throughput_per_day: float = 0.0  # carried so reconciliation.py can convert its capacity ceiling hours<->quantity
    ge_pct: float = 1.0
    assumptions: list[str] = field(default_factory=list)

    @property
    def total_current_month(self) -> float:
        return self.wk1 + self.wk2 + self.wk3 + self.wk4 + self.wk5

    @property
    def total_all(self) -> float:
        return self.wk1a + self.total_current_month


@dataclass
class AllocationResult:
    rows: list[SkuAllocation]
    capacity_messages: list[str] = field(default_factory=list)
    # Real remaining weekly capacity in HOURS after all allocation passes, keyed
    # by (plant_line, period): 24*7 - downtime - hours already used that week.
    # reconciliation.py tops up shortfalls within -- never past -- these values.
    leftover_capacity: dict[tuple[str, int], dict[str, float]] = field(default_factory=dict)


def _hours_needed(qty: float, throughput_per_day: float, ge_pct: float = 1.0) -> float:
    if not throughput_per_day:
        return 0.0
    rate_per_hour = throughput_per_day / 24.0 * ge_pct  # GE% reduces the effective production rate
    return qty / rate_per_hour if rate_per_hour else 0.0


def _qty_from_hours(hours: float, throughput_per_day: float, ge_pct: float = 1.0) -> float:
    if not throughput_per_day:
        return 0.0
    rate_per_hour = throughput_per_day / 24.0 * ge_pct  # GE% reduces the effective production rate
    return hours * rate_per_hour


def run(
    consolidated: ConsolidatedTable,
    calendar_df: pd.DataFrame | None,
    fallback: FallbackDecisions,
    carryover_fin_in: dict[tuple[str, object], float] | None = None,
) -> AllocationResult:
    carryover_fin_in = carryover_fin_in or {}
    all_rows: list[SkuAllocation] = []
    capacity_messages: list[str] = []
    leftover_capacity: dict[tuple[str, int], dict[str, float]] = {}

    for (plant_line, period), group in consolidated.data.groupby(["plant_line", "period"], sort=False):
        plant, line = plant_line.split("_", 1)
        month_key = group["month_key"].iloc[0]
        month_num = group["month_num"].iloc[0]

        caps, cap_msgs = capacity.build(calendar_df, plant, line, month_key, month_num)
        capacity_messages.extend(cap_msgs)

        rem_wk1a = caps.wk1a
        rem = {"wk1": caps.wk1, "wk2": caps.wk2, "wk3": caps.wk3, "wk4": caps.wk4,
               "wk5": caps.wk5 if caps.wk5 is not None else 0.0}
        active_weeks = ["wk1", "wk2", "wk3", "wk4"] + (["wk5"] if caps.wk5 is not None else [])

        skus = group.sort_values("priority").to_dict("records")

        allocations: dict[object, SkuAllocation] = {}
        for r in skus:
            key = (plant_line, r["link_code"])
            carry_in = carryover_fin_in.get(key, 0.0)
            allocations[r["sku"]] = SkuAllocation(
                plant_line=plant_line, period=period, link_code=r["link_code"], sku=r["sku"],
                priority=r["priority"], current_fin=r["current_fin"], carryover_fin_in=carry_in,
                throughput_per_day=r["throughput_per_day"], ge_pct=r["ge_pct"],
                assumptions=list(r["row_assumptions"]),
            )

        # --- Carryover (W1A) pass: happens before Run 1, per ground-truth doc ---
        for r in skus:
            alloc = allocations[r["sku"]]
            if alloc.carryover_fin_in <= 0:
                continue
            hrs_needed = _hours_needed(alloc.carryover_fin_in, r["throughput_per_day"], r["ge_pct"])
            hrs_used = min(hrs_needed, rem_wk1a) if rem_wk1a > 0 else 0.0
            produced = _qty_from_hours(hrs_used, r["throughput_per_day"], r["ge_pct"]) if hrs_used else 0.0
            alloc.wk1a = round(produced, 1)
            rem_wk1a = round(rem_wk1a - hrs_used, 1)
            residual = alloc.carryover_fin_in - produced
            if residual > 0.01:
                # Residual carryover spreads across W1-W4 of the current month (ground-truth doc)
                per_week = residual / 4.0
                alloc.assumptions.append(
                    f"Carryover exceeded W1A capacity; {residual:.1f} spread across W1-W4."
                )
                for wk in ("wk1", "wk2", "wk3", "wk4"):
                    hrs = _hours_needed(per_week, r["throughput_per_day"], r["ge_pct"])
                    hrs_used_wk = min(hrs, rem[wk])
                    produced_wk = _qty_from_hours(hrs_used_wk, r["throughput_per_day"], r["ge_pct"])
                    setattr(alloc, wk, round(getattr(alloc, wk) + produced_wk, 1))
                    rem[wk] = round(rem[wk] - hrs_used_wk, 1)

        # --- Run 1: DOS-gap closure (Case A/B/C/D) ---
        run1_qty: dict[object, float] = {}
        for r in skus:
            sku = r["sku"]
            moq_days = r["moq_days"]
            # No MOQ -> no run-length concept for this SKU: skip Run 1, let Run 2
            # distribute 100% of FIN. Covers both the global fallback and a
            # per-SKU RCCP miss (consolidation.py sets moq_days=None, which
            # becomes NaN once it's in the frame). Applying the Fallback Matrix's
            # "MOQ absent -> unbounded, entire FIN through Run 2" rule at SKU
            # level. `pd.isna` catches None, Python nan and numpy nan alike --
            # without this guard `(moq_days or 0)` lets NaN through (NaN is
            # truthy) and it then floods wk1..wk5, carryover, and rem[wk].
            if fallback.use_default_moq or moq_days is None or pd.isna(moq_days):
                run1_qty[sku] = 0.0
                allocations[sku].moq_case = "No MOQ"
                continue

            fin = r["current_fin"]
            moq_qty_equiv = (moq_days or 0) * (r["throughput_per_day"] or 0)  # MOQ expressed as a quantity, for the 1.5x test
            dos_gap_qty = 0.0
            if r["throughput_per_day"]:
                # DOS gap (days) -> quantity, via the SKU's own daily throughput
                dos_gap_qty = r["dos_gap"] * (r["throughput_per_day"])

            if moq_qty_equiv and fin < 1.5 * moq_qty_equiv:
                qty, case = fin, "A"
            elif r["dos_gap"] == 0:
                qty, case = moq_qty_equiv, "B"
            elif dos_gap_qty < moq_qty_equiv:
                qty, case = moq_qty_equiv, "C"
            else:
                qty, case = dos_gap_qty, "D"

            run1_qty[sku] = min(qty, fin)
            allocations[sku].moq_case = case

        for r in skus:
            sku = r["sku"]
            alloc = allocations[sku]
            qty = run1_qty[sku]
            produced_total = 0.0
            for wk in active_weeks:
                if qty - produced_total <= 0:
                    break
                hrs_needed = _hours_needed(qty - produced_total, r["throughput_per_day"], r["ge_pct"])
                hrs_used = min(hrs_needed, rem[wk])
                produced = _qty_from_hours(hrs_used, r["throughput_per_day"], r["ge_pct"])
                setattr(alloc, wk, round(getattr(alloc, wk) + produced, 1))
                rem[wk] = round(rem[wk] - hrs_used, 1)
                produced_total += produced

        # --- Run 2: distribute whatever FIN remains ---
        for r in skus:
            sku = r["sku"]
            alloc = allocations[sku]
            remaining_fin = r["current_fin"] - alloc.total_current_month
            if remaining_fin <= 0:
                continue

            # H1: MOQ is a minimum run length. Run 2 may top up a week this SKU
            # is already producing in by any amount, but it must not *start* a
            # fresh run in an otherwise-empty week for less than one MOQ. Any
            # sliver it therefore can't place is left as an open gap for
            # reconciliation.py to fold into an existing active week (within real
            # remaining capacity) or roll to M+1. No MOQ supplied -> no floor.
            moq_days = r["moq_days"]
            if fallback.use_default_moq or moq_days is None or pd.isna(moq_days):
                moq_qty = 0.0
            else:
                moq_qty = (moq_days or 0) * (r["throughput_per_day"] or 0)

            produced_total = 0.0
            for wk in active_weeks:
                if remaining_fin - produced_total <= 0:
                    break
                hrs_needed = _hours_needed(remaining_fin - produced_total, r["throughput_per_day"], r["ge_pct"])
                hrs_used = min(hrs_needed, rem[wk])
                produced = _qty_from_hours(hrs_used, r["throughput_per_day"], r["ge_pct"])
                if produced > 0 and getattr(alloc, wk) == 0 and produced + 1e-9 < moq_qty:
                    continue  # would be a sub-MOQ new run -- skip, leave for reconciliation
                setattr(alloc, wk, round(getattr(alloc, wk) + produced, 1))
                rem[wk] = round(rem[wk] - hrs_used, 1)
                produced_total += produced

            deferred = round(remaining_fin - produced_total, 1)
            if deferred > 0.01 and moq_qty > 0:
                alloc.assumptions.append(
                    f"Run 2 remainder {deferred:.1f} was below the MOQ run-length floor "
                    f"for every unused week -- deferred to reconciliation."
                )

        leftover_capacity[(plant_line, period)] = {
            "wk1a": rem_wk1a, "wk1": rem["wk1"], "wk2": rem["wk2"],
            "wk3": rem["wk3"], "wk4": rem["wk4"], "wk5": rem["wk5"],
        }

        all_rows.extend(allocations.values())

    return AllocationResult(
        rows=all_rows,
        capacity_messages=capacity_messages,
        leftover_capacity=leftover_capacity,
    )
