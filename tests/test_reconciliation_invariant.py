from __future__ import annotations

import itertools

from engine import allocation
from engine.fallback import FallbackDecisions
from engine.reconciliation import assert_conservation, reconcile
from tests.conftest import make_consolidated, make_row


def test_reconciliation_holds_across_generated_combinations():
    """Property-based-in-spirit: generate a grid of FIN/MOQ/DOS-gap/priority
    combinations (not just the one hand-picked worked example) and confirm
    the conservation law holds for every single one. This is what the BRD's
    'zero tolerance' NFR actually requires -- not passing on the examples we
    happened to think of, but holding for everything reasonable."""
    fin_values = [50, 150, 300, 750]
    moq_days_values = [None, 2, 5, 12]
    dos_gaps = [0, 3, 9, 15]
    priorities = [1, 2, 3]

    rows = []
    i = 0
    for fin, moq_days, gap, priority in itertools.product(fin_values, moq_days_values, dos_gaps, priorities):
        i += 1
        rows.append(make_row(
            f"GenPlant_Line{i % 3}",  # spread across a few lines so capacity contention varies
            link_code=f"LC{i}",
            current_fin=float(fin), moq_days=moq_days,
            opening_dos=10.0, target_dos=10.0 + gap,
            priority=float(priority), throughput_per_day=20.0,
        ))

    table = make_consolidated(rows)
    result = allocation.run(table, calendar_df=None, fallback=FallbackDecisions())
    reconciled = reconcile(result)
    violations = assert_conservation(reconciled)
    assert violations == [], f"{len(violations)} conservation violations, e.g.: {violations[:5]}"


def test_large_shortfall_is_capped_at_capacity_and_carried_forward():
    """Regression for #13/H3: reconciliation must NOT close an oversized,
    capacity-driven shortfall by inflating weekly buckets past what the line
    can physically make. FIN here (~9x real capacity) can only be produced up
    to the line's true weekly capacity; the rest rolls to CARRYOVER_MPLUS1.

    (Supersedes the old test_large_shortfall_still_closes_via_active_bucket_
    adjustment, which asserted the pre-fix behaviour -- gap crammed into
    buckets, carryover_next == 0 -- that this fix deliberately removes.)
    """
    row = make_row("Tight_Line1", period=1, current_fin=5000.0, moq_days=5,
                    opening_dos=10, target_dos=10, throughput_per_day=20.0)
    table = make_consolidated([row])
    result = allocation.run(table, calendar_df=None, fallback=FallbackDecisions())
    reconciled = reconcile(result)
    alloc = reconciled.rows[0]

    # No Calendar -> 4 full weeks at 20 T/day => 168h * (20/24) = 140 T/week.
    week_capacity_qty = 168 * (20 / 24)
    for wk in ("wk1", "wk1a", "wk2", "wk3", "wk4", "wk5"):
        assert getattr(alloc, wk) <= round(week_capacity_qty, 1) + 0.05, wk

    assert round(alloc.total_all, 1) == round(4 * week_capacity_qty, 1)  # 560.0, not 5000
    assert alloc.carryover_next > 0.0                                    # remainder carried, not inflated
    assert assert_conservation(reconciled) == []                        # 560 produced + 4440 carried == 5000


def test_rounding_residual_still_absorbs_into_active_bucket_within_capacity():
    """The common case must not regress: a small reconciliation gap (rounding
    scale) still lands in an active bucket when that week has real headroom --
    it is only the capacity-exceeding remainder that gets carried forward."""
    from engine.allocation import AllocationResult, SkuAllocation

    alloc = SkuAllocation(
        plant_line="P_L", period=1, link_code="L1", priority=1.0,
        current_fin=100.0, carryover_fin_in=0.0,
        throughput_per_day=24.0, ge_pct=1.0,
    )
    alloc.wk1 = 99.6  # 0.4 short of FIN -- a rounding-sized residual
    result = AllocationResult(
        rows=[alloc],
        leftover_capacity={("P_L", 1): {
            "wk1a": 0.0, "wk1": 50.0, "wk2": 0.0, "wk3": 0.0, "wk4": 0.0, "wk5": 0.0,
        }},
    )
    reconciled = reconcile(result)
    assert reconciled.rows[0].carryover_next == 0.0
    assert round(reconciled.rows[0].wk1, 1) == 100.0
    assert assert_conservation(reconciled) == []


def test_link_code_with_zero_capacity_left_carries_entire_fin_forward():
    """A low-priority Link Code sharing a line with a high-priority Link Code
    that consumes all available capacity should get zero allocation -- and
    its entire FIN should roll to CARRYOVER_MPLUS1, not vanish."""
    hungry = make_row("Shared_Line1", link_code="HUNGRY", priority=1.0,
                       current_fin=10000.0, moq_days=None, throughput_per_day=20.0,
                       opening_dos=10, target_dos=10)
    starved = make_row("Shared_Line1", link_code="STARVED", priority=2.0,
                        current_fin=200.0, moq_days=None, throughput_per_day=20.0,
                        opening_dos=10, target_dos=10)
    table = make_consolidated([hungry, starved])
    result = allocation.run(table, calendar_df=None, fallback=FallbackDecisions())
    reconciled = reconcile(result)
    starved_alloc = next(a for a in reconciled.rows if a.link_code == "STARVED")
    assert starved_alloc.total_all == 0.0
    assert starved_alloc.carryover_next == 200.0
    assert assert_conservation(reconciled) == []


def test_reconciliation_with_carryover_in_and_out_across_two_periods():
    """A Link Code whose entire FIN was carried forward from a starved period 1
    should have that exact amount show up as carryover_fin_in in period 2 --
    and the two periods together must still conserve exactly."""
    hungry = make_row("Tight2_Line1", period=1, link_code="HUNGRY", priority=1.0,
                       current_fin=10000.0, moq_days=None, throughput_per_day=20.0,
                       opening_dos=10, target_dos=10)
    starved = make_row("Tight2_Line1", period=1, link_code="STARVED", priority=2.0,
                        current_fin=200.0, moq_days=None, throughput_per_day=20.0,
                        opening_dos=10, target_dos=10)
    table_p1 = make_consolidated([hungry, starved])
    result_p1 = allocation.run(table_p1, calendar_df=None, fallback=FallbackDecisions())
    reconciled_p1 = reconcile(result_p1)
    assert assert_conservation(reconciled_p1) == []

    from engine.carryover import extract_carryover
    carry = extract_carryover(reconciled_p1)
    assert carry[("Tight2_Line1", "STARVED")] == 200.0

    row_p2 = make_row("Tight2_Line1", period=2, link_code="STARVED",
                       current_fin=500.0, moq_days=5, opening_dos=10, target_dos=10,
                       throughput_per_day=20.0)
    table_p2 = make_consolidated([row_p2])
    result_p2 = allocation.run(table_p2, calendar_df=None, fallback=FallbackDecisions(), carryover_fin_in=carry)
    reconciled_p2 = reconcile(result_p2)
    assert assert_conservation(reconciled_p2) == []
    assert reconciled_p2.rows[0].carryover_fin_in == 200.0


def test_recon_adjustment_records_the_net_change_reconciliation_made():
    """Calculation Trace fact: recon_adjustment is exactly what reconciliation
    added to (or trimmed from) the weekly buckets, so the trace can account
    for every tonne. Same fixture as the rounding-residual test above."""
    from engine.allocation import AllocationResult, SkuAllocation

    alloc = SkuAllocation(
        plant_line="P_L", period=1, link_code="L1", priority=1.0,
        current_fin=100.0, carryover_fin_in=0.0, throughput_per_day=24.0, ge_pct=1.0,
    )
    alloc.wk1 = 99.6  # 0.4 short of FIN -- reconciliation tops wk1 up to 100.0
    result = AllocationResult(rows=[alloc], leftover_capacity={("P_L", 1): {
        "wk1a": 0.0, "wk1": 50.0, "wk2": 0.0, "wk3": 0.0, "wk4": 0.0, "wk5": 0.0}})

    reconciled = reconcile(result)
    assert reconciled.rows[0].recon_adjustment == 0.4
    assert reconciled.rows[0].total_all == 100.0


def test_recon_adjustment_is_zero_when_reconciliation_changed_nothing():
    hungry = make_row("Shared_Line1", link_code="HUNGRY", priority=1.0, current_fin=10000.0,
                      moq_days=None, throughput_per_day=20.0, opening_dos=10, target_dos=10)
    starved = make_row("Shared_Line1", link_code="STARVED", priority=2.0, current_fin=200.0,
                       moq_days=None, throughput_per_day=20.0, opening_dos=10, target_dos=10)
    result = allocation.run(make_consolidated([hungry, starved]), calendar_df=None, fallback=FallbackDecisions())
    before = {a.link_code: a.total_all for a in result.rows}
    reconciled = reconcile(result)
    for a in reconciled.rows:
        assert a.recon_adjustment == round(a.total_all - before[a.link_code], 1)
    assert next(a for a in reconciled.rows if a.link_code == "STARVED").recon_adjustment == 0.0


# --- gap_vs_fin is measured after reconciliation, not assigned -----------------

def _stored(**buckets):
    """A reconciled-looking row: FIN 100, no carry-in/out, weekly buckets as given."""
    from engine.allocation import SkuAllocation

    alloc = SkuAllocation(plant_line="P_L", period=1, link_code="L1", priority=1.0,
                          current_fin=100.0, carryover_fin_in=0.0, throughput_per_day=24.0, ge_pct=1.0)
    for name, qty in buckets.items():
        setattr(alloc, name, qty)
    return alloc


def test_gap_vs_fin_reports_a_real_gap_and_is_not_a_constant():
    from engine.reconciliation import measured_gap

    assert measured_gap(_stored(wk1=100.0)) == 0.0                 # exact
    assert measured_gap(_stored(wk1=100.6)) == -0.6                # over-produced by 0.6 T: must show, not read 0
    assert measured_gap(_stored(wk1=99.4)) == 0.6                  # 0.6 T not accounted for: must show
    alloc = _stored(wk1=99.4)
    alloc.carryover_next = 0.6                                     # ...unless it was carried out
    assert measured_gap(alloc) == 0.0


def test_gap_vs_fin_allows_only_the_plans_own_rounding_per_active_week():
    """Each active week is stored to 0.1 T, so it may be up to 0.05 T off:
    the allowance is 0.05 T x active weeks (never less than 0.05 T)."""
    from engine.reconciliation import measured_gap

    five_weeks = dict(wk1a=20.0, wk1=20.0, wk2=20.0, wk3=20.0, wk4=20.22)   # 5 active weeks -> allowance 0.25 T
    assert measured_gap(_stored(**five_weeks)) == 0.0                       # 0.22 T over: inside the rounding
    assert measured_gap(_stored(**{**five_weeks, "wk4": 20.32})) == -0.32   # 0.32 T over: a real gap, shown
    assert measured_gap(_stored(wk1=60.0, wk2=40.1)) == 0.0                 # 2 weeks: 0.1 T is the boundary, still 0
    assert measured_gap(_stored(wk1=60.0, wk2=40.2)) == -0.2                # 2 weeks: 0.2 T is not


def test_gap_vs_fin_with_no_production_and_nothing_carried_shows_the_full_gap():
    from engine.reconciliation import measured_gap

    assert measured_gap(_stored()) == 100.0                                 # nothing produced, nothing carried: all 100 T missing
    alloc = _stored()
    alloc.carryover_next = 100.0
    assert measured_gap(alloc) == 0.0                                       # rolled forward: fully accounted for


def test_reconcile_leaves_the_plan_untouched_and_gap_vs_fin_reads_zero_for_rounding_dust():
    """Real-data row (DPC Baddi 324811, period 2): FIN 21.78 + carry-in 21.8 = 43.58 T pool,
    produced 43.8 T over 5 weeks. reconcile() has never trimmed this (0.044 T a week rounds to
    nothing) and must not start now -- the live plan is unchanged; only the measured gap is new.
    The raw 0.22 T stays visible as 'Difference (T)' on the Calculation Trace."""
    from engine.allocation import AllocationResult, SkuAllocation

    alloc = SkuAllocation(
        plant_line="P_L", period=1, link_code="L1", priority=1.0,
        current_fin=21.78196661689216, carryover_fin_in=21.8, throughput_per_day=24.0, ge_pct=1.0,
    )
    alloc.wk1a, alloc.wk1, alloc.wk2, alloc.wk3, alloc.wk4 = 16.0, 23.3, 1.5, 1.5, 1.5
    before = (alloc.wk1a, alloc.wk1, alloc.wk2, alloc.wk3, alloc.wk4, alloc.carryover_next)

    reconciled = reconcile(AllocationResult(rows=[alloc], leftover_capacity={}))
    row = reconciled.rows[0]
    assert (row.wk1a, row.wk1, row.wk2, row.wk3, row.wk4, row.carryover_next) == before
    assert row.gap_vs_fin == 0.0
    assert round((row.total_all + row.carryover_next) - (row.current_fin + row.carryover_fin_in), 2) == 0.22


def test_gap_vs_fin_is_zero_when_a_capacity_shortfall_rolls_to_carry_out():
    row = make_row("Tight_Line1", period=1, current_fin=5000.0, moq_days=5,
                   opening_dos=10, target_dos=10, throughput_per_day=20.0)
    result = allocation.run(make_consolidated([row]), calendar_df=None, fallback=FallbackDecisions())
    alloc = reconcile(result).rows[0]
    assert alloc.carryover_next > 1000.0          # most of it could not be made...
    assert alloc.gap_vs_fin == 0.0                # ...but every tonne is accounted for


def test_gap_vs_fin_is_within_rounding_for_every_generated_combination():
    """Same grid as the conservation test: after reconciliation no row may carry a
    reportable gap."""
    fin_values = [50, 150, 300, 750]
    moq_days_values = [None, 2, 5, 12]
    dos_gaps = [0, 3, 9, 15]
    rows, i = [], 0
    for fin, moq_days, gap, priority in itertools.product(fin_values, moq_days_values, dos_gaps, [1, 2, 3]):
        i += 1
        rows.append(make_row(f"GenPlant_Line{i % 3}", link_code=f"LC{i}", current_fin=float(fin), moq_days=moq_days,
                             opening_dos=10.0, target_dos=10.0 + gap, priority=float(priority), throughput_per_day=20.0))
    reconciled = reconcile(allocation.run(make_consolidated(rows), calendar_df=None, fallback=FallbackDecisions()))
    assert [a.gap_vs_fin for a in reconciled.rows if a.gap_vs_fin != 0.0] == []
