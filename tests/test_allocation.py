from __future__ import annotations

from engine import allocation
from engine.fallback import FallbackDecisions
from engine.reconciliation import assert_conservation, reconcile
from tests.conftest import make_consolidated, make_row


def test_qty_conversion_matches_worked_example():
    """Ground-truth doc worked example: 37 T/day throughput, 120 available
    hours -> ~184.99 T weekly capacity (before GE adjustment)."""
    qty = allocation._qty_from_hours(120, 37)
    assert round(qty, 2) == 185.0  # doc rounds to 184.99; within a rounding hair


def test_case_a_full_fin_in_one_run(no_fallback):
    # FIN(300) < 1.5 * MOQ(240) -> Case A: entire FIN in Run 1, skip Run 2.
    row = make_row("PlantA_Line1", current_fin=300.0, moq_days=10, throughput_per_day=24.0,
                    opening_dos=20.0, target_dos=20.0)  # dos_gap = 0, irrelevant to Case A
    table = make_consolidated([row])
    result = allocation.run(table, calendar_df=None, fallback=no_fallback)
    alloc = result.rows[0]
    assert alloc.wk1 == 168.0
    assert alloc.wk2 == 132.0
    assert alloc.wk3 == 0.0
    assert round(alloc.total_current_month, 1) == 300.0


def test_case_d_produces_exact_dos_gap(no_fallback):
    # dos_gap(10d * 24T/day = 240T) >= MOQ(5d * 24T/day = 120T) -> Case D: produce exactly the gap.
    # FIN set equal to the Case D quantity so Run 2 contributes nothing -- isolates Run 1.
    row = make_row("PlantD_Line1", current_fin=240.0, moq_days=5, throughput_per_day=24.0,
                    opening_dos=10.0, target_dos=20.0)  # dos_gap = 10 days
    table = make_consolidated([row])
    result = allocation.run(table, calendar_df=None, fallback=no_fallback)
    alloc = result.rows[0]
    assert alloc.wk1 == 168.0
    assert alloc.wk2 == 72.0
    assert round(alloc.total_current_month, 1) == 240.0


def test_moq_missing_fallback_skips_run1_and_still_reconciles():
    fb = FallbackDecisions(use_default_moq=True, messages=["MOQ not supplied..."])
    row = make_row("PlantM_Line1", current_fin=400.0, moq_days=None)
    table = make_consolidated([row])
    result = allocation.run(table, calendar_df=None, fallback=fb)
    reconciled = reconcile(result)
    assert assert_conservation(reconciled) == []
    assert round(reconciled.rows[0].total_current_month, 1) == 400.0


def test_all_cases_together_satisfy_reconciliation_invariant(no_fallback):
    rows = [
        make_row("PlantA_Line1", current_fin=300.0, moq_days=10, opening_dos=20, target_dos=20),  # A
        make_row("PlantB_Line1", current_fin=500.0, moq_days=5, opening_dos=20, target_dos=20),    # B (gap=0)
        make_row("PlantC_Line1", current_fin=500.0, moq_days=5, opening_dos=18, target_dos=20),    # C (gap<moq)
        make_row("PlantD_Line1", current_fin=500.0, moq_days=5, opening_dos=10, target_dos=20),    # D (gap>=moq)
    ]
    table = make_consolidated(rows)
    result = allocation.run(table, calendar_df=None, fallback=no_fallback)
    reconciled = reconcile(result)
    violations = assert_conservation(reconciled)
    assert violations == [], violations
    for alloc in reconciled.rows:
        assert round(alloc.total_all + alloc.carryover_next, 1) == round(alloc.current_fin + alloc.carryover_fin_in, 1)


def test_carryover_in_is_fully_conserved_even_when_w1a_has_no_capacity(no_fallback):
    # With no Calendar supplied, capacity.py's default gives W1A = 0 hours (no
    # split-week assumed) -- so carryover_fin_in has nowhere to land in W1A and
    # must spill into W1-W4 instead (engine/allocation.py's residual-spread
    # logic). The invariant this test actually cares about: none of that 30T
    # of incoming carryover disappears, regardless of which bucket it lands in.
    row = make_row("PlantE_Line1", current_fin=100.0, moq_days=5, opening_dos=20, target_dos=20)
    table = make_consolidated([row])
    carry_in = {("PlantE_Line1", "L1"): 30.0}
    result = allocation.run(table, calendar_df=None, fallback=no_fallback, carryover_fin_in=carry_in)
    reconciled = reconcile(result)
    alloc = reconciled.rows[0]
    assert alloc.wk1a == 0.0  # confirmed: default fallback gives zero W1A capacity
    assert assert_conservation(reconciled) == []
    assert round(alloc.total_all + alloc.carryover_next, 1) == 130.0  # 100 FIN + 30 carryover-in


def test_missing_moq_on_one_sku_does_not_poison_its_plan_or_the_line(no_fallback):
    # A SKU with no RCCP match has moq_days=None, which becomes NaN once it's in
    # the consolidated frame. Before the guard in allocation.run(), `(moq_days
    # or 0)` let that NaN through Case B and it flooded wk1..wk5, carryover, and
    # the shared rem[wk] capacity -- the SKU (and often its line-mates) came out
    # blank. It must instead be planned in full via Run 2 (Fallback Matrix:
    # "MOQ absent -> unbounded"), and a second SKU sharing the line must be
    # unaffected.
    rows = [
        make_row("PlantX_Line1", sku="NOMOQ", link_code="NOMOQ", current_fin=120.0,
                 moq_days=None, opening_dos=20, target_dos=20),          # dos_gap = 0
        make_row("PlantX_Line1", sku="HASMOQ", link_code="HASMOQ", current_fin=80.0,
                 moq_days=5, opening_dos=20, target_dos=20, priority=2.0),
    ]
    result = allocation.run(make_consolidated(rows), calendar_df=None, fallback=no_fallback)
    reconciled = reconcile(result)

    assert assert_conservation(reconciled) == []
    for alloc in reconciled.rows:
        for wk in ("wk1a", "wk1", "wk2", "wk3", "wk4", "wk5"):
            val = getattr(alloc, wk)
            assert val == val, f"{alloc.sku}.{wk} is NaN"          # NaN != NaN
        assert alloc.carryover_next == alloc.carryover_next        # not NaN
        assert round(alloc.total_all + alloc.carryover_next, 1) == alloc.current_fin

    nomoq = next(a for a in reconciled.rows if a.sku == "NOMOQ")
    assert round(nomoq.total_all, 1) == 120.0                      # planned in full, nothing lost
