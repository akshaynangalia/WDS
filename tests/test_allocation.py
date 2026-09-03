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


def test_qty_and_hours_conversion_apply_ge_percent():
    # GE% multiplies the production rate. Regression for "GE% read from SOC but
    # never used" -- before the fix these helpers took only 2 args.
    assert round(allocation._qty_from_hours(120, 37, 1.0), 1) == 185.0
    assert round(allocation._qty_from_hours(120, 37, 0.8), 1) == 148.0   # 185.0 x 0.8
    # _hours_needed is the inverse: 148 T at GE 0.8 needs the same 120 h
    assert round(allocation._hours_needed(148.0, 37, 0.8), 1) == 120.0


def test_ge_percent_reduces_effective_weekly_capacity(no_fallback):
    # A line at 80% GE makes 80% of the tonnage in the same weekly hours.
    # FIN is set above total capacity at both GE levels so the buckets are
    # capacity-bound; asserted before reconcile(), which would otherwise force
    # the weekly total back up to FIN.
    def produced_before_reconcile(ge):
        row = make_row("GEPlant_Line1", current_fin=1000.0, moq_days=None,
                       throughput_per_day=24.0, ge_pct=ge, opening_dos=20, target_dos=20)
        res = allocation.run(make_consolidated([row]), calendar_df=None, fallback=no_fallback)
        return res.rows[0].total_all

    full = produced_before_reconcile(1.0)
    assert round(full, 1) == 672.0                                 # 4 wks x 168 h x 1 T/h
    assert round(produced_before_reconcile(0.8), 1) == round(full * 0.8, 1)   # 537.6, not 672


def test_run2_will_not_open_a_sub_moq_run_in_an_empty_week(no_fallback):
    # H1: a high-priority No-MOQ SKU consumes Run 2 capacity and leaves only a
    # sub-MOQ sliver (52 T, vs a 120 T MOQ run length) free in wk4. Run 2 must
    # NOT drop that sliver into wk4 for the low-priority SKU as a tiny
    # standalone run -- the SKU keeps only its Run 1 MOQ batch and the
    # unplaceable 80 T remainder carries to M+1 (no active week has room).
    hungry = make_row("Tight_Line1", sku="HUNGRY", link_code="HUNGRY", priority=1.0,
                      current_fin=500.0, moq_days=None, throughput_per_day=24.0,
                      opening_dos=20, target_dos=20)
    starved = make_row("Tight_Line1", sku="STARVED", link_code="STARVED", priority=2.0,
                       current_fin=200.0, moq_days=5, throughput_per_day=24.0,
                       opening_dos=20, target_dos=20)          # Case B -> Run 1 places one 120 T batch
    result = allocation.run(make_consolidated([hungry, starved]), calendar_df=None, fallback=no_fallback)
    starved_alloc = next(a for a in result.rows if a.sku == "STARVED")

    assert round(starved_alloc.wk1, 1) == 120.0                # the Run 1 MOQ batch
    assert starved_alloc.wk4 == 0.0                            # Run 2 did NOT open a sub-MOQ run here
    assert any("below the MOQ run-length floor" in m for m in starved_alloc.assumptions)

    reconciled = reconcile(result)
    assert assert_conservation(reconciled) == []
    sr = next(a for a in reconciled.rows if a.sku == "STARVED")
    assert round(sr.total_all + sr.carryover_next, 1) == 200.0  # nothing lost
    assert round(sr.carryover_next, 1) == 80.0                  # the deferred remainder went to M+1


def test_run_records_the_moq_case_per_sku(no_fallback):
    # COMPARISON_TABLE's "MOQ Case" column: allocation.run() must tag every SKU
    # with the Run 1 branch that applied (A/B/C/D or "No MOQ").
    rows = [
        make_row("PlantA_Line1", sku="A", link_code="A", current_fin=300.0, moq_days=10,
                 opening_dos=20, target_dos=20),                             # A: FIN < 1.5 x MOQ
        make_row("PlantB_Line1", sku="B", link_code="B", current_fin=500.0, moq_days=5,
                 opening_dos=20, target_dos=20),                             # B: dos_gap == 0
        make_row("PlantC_Line1", sku="C", link_code="C", current_fin=500.0, moq_days=5,
                 opening_dos=18, target_dos=20),                             # C: 0 < gap < MOQ
        make_row("PlantD_Line1", sku="D", link_code="D", current_fin=500.0, moq_days=5,
                 opening_dos=10, target_dos=20),                             # D: gap >= MOQ
        make_row("PlantN_Line1", sku="N", link_code="N", current_fin=200.0, moq_days=None,
                 opening_dos=20, target_dos=20),                             # no MOQ for this SKU
    ]
    result = allocation.run(make_consolidated(rows), calendar_df=None, fallback=no_fallback)
    assert {a.sku: a.moq_case for a in result.rows} == {
        "A": "A", "B": "B", "C": "C", "D": "D", "N": "No MOQ",
    }
