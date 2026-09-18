from __future__ import annotations

from engine.allocation import SkuAllocation
from engine.changeover import compute_priority_overrides
from engine.reconciliation import ReconciledResult


def _alloc(link_code, *, plant_line="P_L1", month_key="Jan-26", wk4=0.0, wk5=0.0,
          carryover_next=0.0, moq_case="D"):
    return SkuAllocation(
        plant_line=plant_line, period=1, link_code=link_code, priority=1.0,
        current_fin=100.0, carryover_fin_in=0.0, wk4=wk4, wk5=wk5,
        carryover_next=carryover_next, moq_case=moq_case, month_key=month_key,
    )


def test_qualifies_when_producing_in_last_week_with_carryover_left():
    rows = [_alloc("A", wk4=50.0, carryover_next=20.0)]  # Jan-26 -> not five-week -> last week is W4
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == {("P_L1", "A")}


def test_does_not_qualify_when_carryover_is_zero():
    rows = [_alloc("A", wk4=50.0, carryover_next=0.0)]
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == set()


def test_does_not_qualify_when_it_finished_before_the_last_week():
    # Produced earlier in the month (not captured here -- wk4 is what's checked)
    # but nothing in W4 itself, even though it still has carryover (e.g. its
    # own remainder was below the MOQ floor and deferred without touching W4).
    rows = [_alloc("A", wk4=0.0, carryover_next=20.0)]
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == set()


def test_everyone_idle_in_the_real_last_week_means_nobody_qualifies():
    # The line went idle by W3; W4 (the period's real last week) has zero
    # production for EVERYONE, even though one Link Code still has carryover
    # (e.g. deferred by the MOQ floor). Nothing was actively running when the
    # month ended, so there is no in-progress run to protect -- confirmed
    # explicitly during design review.
    rows = [
        _alloc("A", wk4=0.0, carryover_next=15.0),
        _alloc("B", wk4=0.0, carryover_next=0.0),
    ]
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == set()


def test_five_week_month_checks_wk5_not_wk4():
    rows = [_alloc("A", month_key="Jun-26", wk4=30.0, wk5=20.0, carryover_next=10.0)]  # June -> five-week month
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == {("P_L1", "A")}


def test_five_week_month_a_link_code_only_reaching_wk4_does_not_qualify():
    # Five-week month, but this Link Code stopped at W4 -- W5 is the real
    # last week here, and it never produced there.
    rows = [_alloc("A", month_key="Jun-26", wk4=30.0, wk5=0.0, carryover_next=10.0)]
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == set()


def test_case_agnostic_any_moq_case_can_qualify():
    rows = [
        _alloc("A", wk4=10.0, carryover_next=5.0, moq_case="A"),
        _alloc("B", wk4=10.0, carryover_next=5.0, moq_case="B"),
        _alloc("C", wk4=10.0, carryover_next=5.0, moq_case="No MOQ"),
    ]
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == {
        ("P_L1", "A"), ("P_L1", "B"), ("P_L1", "C"),
    }


def test_multiple_qualifiers_on_one_line_and_independence_across_lines():
    rows = [
        _alloc("A", plant_line="P_L1", wk4=10.0, carryover_next=5.0),
        _alloc("B", plant_line="P_L1", wk4=10.0, carryover_next=0.0),   # no carryover -- excluded
        _alloc("C", plant_line="P_L2", wk4=10.0, carryover_next=8.0),
    ]
    assert compute_priority_overrides(ReconciledResult(rows=rows)) == {
        ("P_L1", "A"), ("P_L2", "C"),
    }
