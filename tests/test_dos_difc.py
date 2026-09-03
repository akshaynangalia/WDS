from __future__ import annotations

import pandas as pd

from engine import dos_difc
from engine.allocation import SkuAllocation
from engine.fallback import FallbackDecisions


def _consolidated_row(link_code="L1", period=1, opening_dos=20.0, month_num=1, month_key=None):
    return {"link_code": link_code, "period": period, "opening_dos": opening_dos,
            "month_num": month_num, "month_key": month_key}


def test_closing_difc_matches_hand_calculation():
    # Opening DIFC=20, monthly demand=310 (Jan, 31 days) -> daily=10, weekly=70 (fallback: daily*7)
    # Production W1 = 100 -> Closing = (20*10 - 70 + 100)/10 = 230/10 = 23.0
    consolidated_df = pd.DataFrame([_consolidated_row(opening_dos=20.0, month_num=1)])
    demand_df = pd.DataFrame([{"Link Code": "L1", 1: 310.0}])
    alloc = SkuAllocation(plant_line="P_L", period=1, link_code="L1", sku="L1", priority=1.0,
                           current_fin=100.0, carryover_fin_in=0.0, wk1=100.0)
    fb = FallbackDecisions(use_monthly_avg_dos=True)

    result = dos_difc.compute([alloc], consolidated_df, demand_df, fb)
    row = result.rows[0]
    assert row.closing_by_week["wk1"] == 23.0
    assert row.approximated is True


def test_closing_difc_floors_at_zero():
    # Large weekly demand relative to opening stock + production should floor at 0, not go negative.
    consolidated_df = pd.DataFrame([_consolidated_row(opening_dos=2.0, month_num=1)])
    demand_df = pd.DataFrame([{"Link Code": "L1", 1: 3100.0}])  # daily=100, weekly=700
    alloc = SkuAllocation(plant_line="P_L", period=1, link_code="L1", sku="L1", priority=1.0,
                           current_fin=50.0, carryover_fin_in=0.0, wk1=10.0)
    fb = FallbackDecisions(use_monthly_avg_dos=True)

    result = dos_difc.compute([alloc], consolidated_df, demand_df, fb)
    assert result.rows[0].closing_by_week["wk1"] == 0.0


def test_missing_demand_data_does_not_crash():
    consolidated_df = pd.DataFrame([_consolidated_row()])
    demand_df = pd.DataFrame()  # no demand data at all
    alloc = SkuAllocation(plant_line="P_L", period=1, link_code="L1", sku="L1", priority=1.0,
                           current_fin=50.0, carryover_fin_in=0.0, wk1=10.0)
    result = dos_difc.compute([alloc], consolidated_df, demand_df, FallbackDecisions())
    assert result.rows[0].closing_by_week["wk1"] == 0.0  # no demand -> daily_demand=0 -> closing=0, no crash


def test_days_in_month_handles_leap_year_february():
    # Regression for the hard-coded "February = 28". Year comes from month_key.
    assert dos_difc._days_in_month(2, "Feb-28") == 29    # 2028 is a leap year
    assert dos_difc._days_in_month(2, "Feb-26") == 28    # 2026 is not
    assert dos_difc._days_in_month(2, "Feb-32") == 29    # 2032 is a leap year
    assert dos_difc._days_in_month(4, "Apr-26") == 30
    assert dos_difc._days_in_month(None, None) == 30     # period absent -> coarse fallback
    assert dos_difc._days_in_month(2, None) == 28        # year unknown -> non-leap fallback


def test_february_difc_reflects_leap_year_day_count():
    # Same SKU/demand; only the year in month_key differs. Feb 2028 has 29 days,
    # Feb 2026 has 28, so daily demand -- hence closing DIFC -- must differ.
    demand_df = pd.DataFrame([{"Link Code": "L1", 2: 290.0}])
    alloc = SkuAllocation(plant_line="P_L", period=2, link_code="L1", sku="L1", priority=1.0,
                           current_fin=1000.0, carryover_fin_in=0.0, wk1=1000.0)
    fb = FallbackDecisions(use_monthly_avg_dos=True)

    def closing_wk1(month_key):
        df = pd.DataFrame([_consolidated_row(period=2, opening_dos=20.0, month_num=2, month_key=month_key)])
        return dos_difc.compute([alloc], df, demand_df, fb).rows[0].closing_by_week["wk1"]

    assert closing_wk1("Feb-28") == round(20 - 7 + 1000 / (290 / 29), 1)   # leap: daily demand = 10.0
    assert closing_wk1("Feb-26") == round(20 - 7 + 1000 / (290 / 28), 1)   # non-leap
    assert closing_wk1("Feb-28") != closing_wk1("Feb-26")
