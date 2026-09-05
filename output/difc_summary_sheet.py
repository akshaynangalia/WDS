"""Writes the Weekly DIFC Summary tab (REQ-CR-06) — Architecture Document, Section 5.9."""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    rows = []
    for row in result.difc.rows:
        record = {
            "Plant": row.plant,
            "Line": row.line,
            "Linkcode": row.link_code,
            "Brand": row.brand,
            "Link Desc Description": row.link_desc,
            "Month": row.month_key,
            "Period": row.period,
            "Opening DOS": row.opening_dos,
        }
        record.update({wk.upper(): val for wk, val in row.closing_by_week.items()})
        record["Approximated (monthly avg)"] = "Yes" if row.approximated else "No"
        rows.append(record)
    df = pd.DataFrame(rows)
    # Column order must stay Plant..Opening DOS, W1-W5, Approximated regardless of
    # which rows are five-week months -- otherwise pandas places WK5 wherever it
    # first appears across rows, which can land it after "Approximated".
    week_cols = [c for c in ("WK1", "WK2", "WK3", "WK4", "WK5") if c in df.columns]
    lead_cols = ["Plant", "Line", "Linkcode", "Brand", "Link Desc Description", "Month", "Period", "Opening DOS"]
    return df[[c for c in lead_cols if c in df.columns] + week_cols + ["Approximated (monthly avg)"]]
