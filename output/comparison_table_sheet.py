"""Writes the COMPARISON_TABLE tab (auditability) — Architecture Document, Section 5.9."""
from __future__ import annotations

import pandas as pd

from engine.allocation import WEEK_ORDER
from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    rows = []
    for alloc in result.reconciled.rows:
        active_weeks = sum(1 for wk in WEEK_ORDER if getattr(alloc, wk) > 0)
        rows.append({
            "Plant / Line": alloc.plant_line.replace("_", " / "),
            "SKU / Link Code": alloc.sku,
            "Period": alloc.period,
            "FIN": alloc.current_fin,
            "Carryover In": alloc.carryover_fin_in,
            "Total Produced": round(alloc.total_all, 1),
            "gap_vs_fin": alloc.gap_vs_fin,
            "Carryover Out (M+1)": alloc.carryover_next,
            "Active Weeks": active_weeks,
        })
    return pd.DataFrame(rows)
