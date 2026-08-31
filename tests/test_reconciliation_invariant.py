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
            sku=f"SKU{i}", link_code=f"SKU{i}",
            current_fin=float(fin), moq_days=moq_days,
            opening_dos=10.0, target_dos=10.0 + gap,
            priority=float(priority), throughput_per_day=20.0,
        ))

    table = make_consolidated(rows)
    result = allocation.run(table, calendar_df=None, fallback=FallbackDecisions())
    reconciled = reconcile(result)
    violations = assert_conservation(reconciled)
    assert violations == [], f"{len(violations)} conservation violations, e.g.: {violations[:5]}"


def test_large_shortfall_still_closes_via_active_bucket_adjustment():
    """IMPORTANT DOCUMENTED ASSUMPTION: per the ground-truth doc's literal
    wording, reconciliation distributes gap_vs_fin across ANY active bucket
    (one with nonzero production), with no magnitude cap -- so even a huge
    capacity-driven shortfall gets closed this way as long as the SKU got
    *some* allocation. Only a SKU with literally zero allocation anywhere
    rolls its gap to CARRYOVER_MPLUS1 instead (see the next test). This is a
    literal reading of the doc, not a judgment call we made silently -- it's
    worth the client confirming whether an *oversized* gap (like this one,
    where FIN is ~9x actual capacity) should really be "reconciled" this way
    rather than partially carried forward. Flagged in the Dev Plan Risk
    Register rather than resolved unilaterally.
    """
    row = make_row("Tight_Line1", period=1, current_fin=5000.0, moq_days=5,
                    opening_dos=10, target_dos=10, throughput_per_day=20.0)
    table = make_consolidated([row])
    result = allocation.run(table, calendar_df=None, fallback=FallbackDecisions())
    reconciled = reconcile(result)
    alloc = reconciled.rows[0]
    assert alloc.carryover_next == 0.0  # got *some* allocation -> gap closed via buckets, not carried
    assert assert_conservation(reconciled) == []
    assert round(alloc.total_all, 1) == 5000.0


def test_sku_with_zero_capacity_left_carries_entire_fin_forward():
    """A low-priority SKU sharing a line with a high-priority SKU that
    consumes all available capacity should get zero allocation -- and its
    entire FIN should roll to CARRYOVER_MPLUS1, not vanish."""
    hungry = make_row("Shared_Line1", sku="HUNGRY", link_code="HUNGRY", priority=1.0,
                       current_fin=10000.0, moq_days=None, throughput_per_day=20.0,
                       opening_dos=10, target_dos=10)
    starved = make_row("Shared_Line1", sku="STARVED", link_code="STARVED", priority=2.0,
                        current_fin=200.0, moq_days=None, throughput_per_day=20.0,
                        opening_dos=10, target_dos=10)
    table = make_consolidated([hungry, starved])
    result = allocation.run(table, calendar_df=None, fallback=FallbackDecisions())
    reconciled = reconcile(result)
    starved_alloc = next(a for a in reconciled.rows if a.sku == "STARVED")
    assert starved_alloc.total_all == 0.0
    assert starved_alloc.carryover_next == 200.0
    assert assert_conservation(reconciled) == []


def test_reconciliation_with_carryover_in_and_out_across_two_periods():
    """A SKU whose entire FIN was carried forward from a starved period 1
    should have that exact amount show up as carryover_fin_in in period 2 --
    and the two periods together must still conserve exactly."""
    hungry = make_row("Tight2_Line1", period=1, sku="HUNGRY", link_code="HUNGRY", priority=1.0,
                       current_fin=10000.0, moq_days=None, throughput_per_day=20.0,
                       opening_dos=10, target_dos=10)
    starved = make_row("Tight2_Line1", period=1, sku="STARVED", link_code="STARVED", priority=2.0,
                        current_fin=200.0, moq_days=None, throughput_per_day=20.0,
                        opening_dos=10, target_dos=10)
    table_p1 = make_consolidated([hungry, starved])
    result_p1 = allocation.run(table_p1, calendar_df=None, fallback=FallbackDecisions())
    reconciled_p1 = reconcile(result_p1)
    assert assert_conservation(reconciled_p1) == []

    from engine.carryover import extract_carryover
    carry = extract_carryover(reconciled_p1)
    assert carry[("Tight2_Line1", "STARVED")] == 200.0

    row_p2 = make_row("Tight2_Line1", period=2, sku="STARVED", link_code="STARVED",
                       current_fin=500.0, moq_days=5, opening_dos=10, target_dos=10,
                       throughput_per_day=20.0)
    table_p2 = make_consolidated([row_p2])
    result_p2 = allocation.run(table_p2, calendar_df=None, fallback=FallbackDecisions(), carryover_fin_in=carry)
    reconciled_p2 = reconcile(result_p2)
    assert assert_conservation(reconciled_p2) == []
    assert reconciled_p2.rows[0].carryover_fin_in == 200.0
