from __future__ import annotations

from engine.allocation import SkuAllocation
from engine.health_checks import CONSERVATION_TOLERANCE_T, check


def _row(link_code="L1", *, fin=100.0, carry_in=0.0, wk1=100.0, carry_out=0.0, period=1, **extra):
    return SkuAllocation(
        plant_line="P_L1", period=period, link_code=link_code, priority=1.0,
        current_fin=fin, carryover_fin_in=carry_in, wk1=wk1, carryover_next=carry_out, **extra,
    )


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_a_clean_run_passes_every_check():
    report = check([_row("A"), _row("B", fin=50.0, wk1=30.0, carry_out=20.0)])
    assert report.ok
    assert report.warnings == []


def test_rounding_scale_deviation_does_not_raise_a_false_alarm():
    # Real data (942 rows): worst deviation is 0.22 T purely from 0.1 T rounding.
    # An alarm that fired on that would fire on every run and be ignored.
    report = check([_row(fin=43.58, carry_in=0.0, wk1=43.8)])  # dev = +0.22
    assert report.ok
    assert "max_dev=0.220T" in _check(report, "conservation").detail


def test_lost_volume_fails_conservation():
    # 50 T of FIN neither produced nor carried forward: a real fault.
    report = check([_row(fin=100.0, wk1=50.0, carry_out=0.0)])
    conservation = _check(report, "conservation")
    assert not conservation.ok and not report.ok
    assert "P_L1/L1/P1" in conservation.failures[0]
    assert "-50.00 T" in conservation.failures[0]
    assert report.warnings[0].startswith("conservation:")


def test_double_counted_volume_also_fails():
    report = check([_row(fin=100.0, wk1=100.0, carry_out=40.0)])  # 40 T counted twice
    assert not _check(report, "conservation").ok


def test_tolerance_boundary_is_the_documented_value():
    just_inside = _row(fin=100.0, wk1=100.0 + CONSERVATION_TOLERANCE_T - 0.01)
    just_outside = _row(fin=100.0, wk1=100.0 + CONSERVATION_TOLERANCE_T + 0.01)
    assert _check(check([just_inside]), "conservation").ok
    assert not _check(check([just_outside]), "conservation").ok


def test_nan_is_caught_because_it_silently_passes_every_comparison():
    nan = float("nan")
    report = check([_row(wk2=nan)])
    nan_check = _check(report, "nan")
    assert not nan_check.ok
    assert "wk2 is NaN" in nan_check.failures[0]
    # NaN rows are skipped by the arithmetic check rather than compared falsely.
    assert _check(report, "conservation").ok


def test_negative_quantity_is_caught():
    report = check([_row(wk1=100.0, carry_out=-5.0)])
    negative = _check(report, "negative")
    assert not negative.ok
    assert "carryover_next=-5.00 is negative" in negative.failures[0]


def test_checks_never_modify_the_rows():
    row = _row(fin=100.0, wk1=50.0)
    before = (row.wk1, row.carryover_next, row.current_fin)
    check([row])
    assert (row.wk1, row.carryover_next, row.current_fin) == before
