"""Writes the Weekly Plan tab — Architecture Document, Section 5.9."""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    rows = []
    for alloc in result.reconciled.rows:
        rows.append({
            "Plant": alloc.plant,
            "Line": alloc.line,
            "Linkcode": alloc.link_code,
            "Brand": alloc.brand,
            "Link Desc Description": alloc.link_desc,
            "Month": alloc.month_key,
            "Period": alloc.period,
            "Opening DOS": alloc.opening_dos,
            "Target DOS": alloc.target_dos,
            "Priority": alloc.priority,
            "MOQ": alloc.moq_days,
            "Total FIN(T)": alloc.current_fin,
            "OPENING CARRYOVER": alloc.carryover_fin_in,
            "W1A": alloc.wk1a,
            "W1": alloc.wk1,
            "W2": alloc.wk2,
            "W3": alloc.wk3,
            "W4": alloc.wk4,
            "W5": alloc.wk5,
            "CARRYOVER_MPLUS1": alloc.carryover_next,
            "TOTAL PRODUCED": round(alloc.total_all, 1),
            "CASE": alloc.moq_case,
            "Notes": "; ".join(alloc.assumptions),
        })
    return pd.DataFrame(rows)
