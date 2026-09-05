"""Writes the Comparison Table tab (auditability) — Architecture Document, Section 5.9."""
from __future__ import annotations

import pandas as pd

from engine.allocation import WEEK_ORDER
from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    rows = []
    for alloc in result.reconciled.rows:
        active_weeks = sum(1 for wk in WEEK_ORDER if getattr(alloc, wk) > 0)
        rows.append({
            "Plant": alloc.plant,
            "Line": alloc.line,
            "Linkcode": alloc.link_code,
            "Brand": alloc.brand,
            "Link Desc Description": alloc.link_desc,
            "Month": alloc.month_key,
            "Period": alloc.period,
            "Total FIN(T)": alloc.current_fin,
            "OPENING CARRYOVER": alloc.carryover_fin_in,
            "TOTAL PRODUCED": round(alloc.total_all, 1),
            "CARRYOVER_MPLUS1": alloc.carryover_next,
            "gap_vs_fin": alloc.gap_vs_fin,
            "ACTIVE WEEKS": active_weeks,
            "CASE": alloc.moq_case,  # A/B/C/D or "No MOQ" -- how MOQ governance was applied
        })
    return pd.DataFrame(rows)
