from __future__ import annotations

import pandas as pd

from engine import dos_difc
from engine.allocation import SkuAllocation
from engine.fallback import FallbackDecisions


def _consolidated_row(link_code="L1", period=1, opening_dos=20.0, month_num=1):
    return {"link_code": link_code, "period": period, "opening_dos": opening_dos, "month_num": month_num}


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
