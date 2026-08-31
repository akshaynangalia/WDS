"""Writes the DIFC/DOS Summary tab (REQ-CR-06) — Architecture Document, Section 5.9."""
from __future__ import annotations

import pandas as pd

from engine.engine_result import EngineResult


def build_dataframe(result: EngineResult) -> pd.DataFrame:
    rows = []
    for row in result.difc.rows:
        record = {
            "Plant / Line": row.plant_line.replace("_", " / "),
            "SKU / Link Code": row.sku,
            "Period": row.period,
        }
        record.update({wk.upper(): val for wk, val in row.closing_by_week.items()})
        record["Approximated (monthly avg)"] = "Yes" if row.approximated else "No"
        rows.append(record)
    return pd.DataFrame(rows)
