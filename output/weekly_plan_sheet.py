"""Writes the WEEKLY_PLAN tab — Architecture Document, Section 5.9."""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    rows = []
    for alloc in result.reconciled.rows:
        rows.append({
            "Plant / Line": alloc.plant_line.replace("_", " / "),
            "SKU / Link Code": alloc.sku,
            "Period": alloc.period,
            "W1A": alloc.wk1a,
            "W1": alloc.wk1,
            "W2": alloc.wk2,
            "W3": alloc.wk3,
            "W4": alloc.wk4,
            "W5": alloc.wk5,
            "CARRYOVER_MPLUS1": alloc.carryover_next,
            "TOTAL": round(alloc.total_all, 1),
        })
    return pd.DataFrame(rows)
